# Plano de implementação — pendências restantes (para execução pelo Sonnet)

> Este documento é autossuficiente: contém contexto, arquivos exatos, desenho da solução e
> critérios de verificação de cada item. Execute os itens **na ordem** (1 → 3). Ao terminar
> cada item, rode a rotina de verificação e atualize o checkbox correspondente no
> `PENDENCIAS.md`.

## Contexto do sistema (leia antes)

- SaaS multi-tenant de clínicas com secretária IA ("Sofia", Google Gemini) no WhatsApp.
  Backend FastAPI + SQLAlchemy 2.0 async + PostgreSQL; frontend Next.js 14 + Tailwind **v3**.
- Sofia: prompt fixo em código (`app/services/ai.py` → `DEFAULT_SYSTEM_PROMPT`), tools em
  `app/services/ai_tools.py` (declarações Gemini + executores + `execute_tool()` dispatcher).
- **Invariantes de segurança (NUNCA violar):**
  - `tenant_id`/`contact_id` **nunca** vêm de argumentos da IA — sempre injetados do contexto Python.
  - Toda query filtra por `tenant_id`.
  - Segredos nunca serializam ao frontend (`app/schemas/tenant.py` sanitiza).
  - A IA nunca pode editar `phone`, `status` — e `ai_paused` só pela nova tool do item 1 (one-way: só pausar, nunca despausar).
- Frontend: sempre usar a instância `api` de `frontend/src/lib/axios.ts` (nunca axios cru).
  Texto de UI em pt-BR. Tailwind v3 (sem sintaxe v4).
- Rotina de verificação após qualquer mudança:
  ```bash
  venv\Scripts\python -c "import app.main; print('OK')"   # backend
  cd frontend && npx tsc --noEmit && npm run build          # frontend
  ```

### Padrão de teste E2E da Sofia (usado nos itens 1 e 2)
Os testes de comportamento da Sofia desta base seguem um padrão de harness: script Python que
(1) cria um **tenant descartável** com slug `zzz-teste-*`, serviços e contato; (2) roda
`ai.generate_reply()` com Gemini real; (3) verifica a resposta/tool calls com asserts; (4)
**apaga o tenant no final** (delete cascade) e confirma que só sobraram os tenants reais.
Requer Postgres local (`docker compose up -d`) e `GEMINI_API_KEY` no `.env`. Exemplos de
referência ficaram no scratchpad da sessão anterior; o padrão é simples de reproduzir a partir
desta descrição.

---

## Item 1 — Handoff humano (prioridade máxima: é atendimento)

**Objetivo:** a Sofia reconhecer quando NÃO deve continuar atendendo e transferir para a
equipe humana, pausando a si mesma naquele contato.

**O que JÁ existe (não recriar):**
- `Contact.ai_paused` (bool) — quando `True`, o webhook ignora o inbound para a IA
  (`app/api/v1/routes/webhooks.py` linhas ~479/511/567 — inclusive re-checagem tardia após o debounce).
- Inbox no frontend já mostra badge de pausado, filtro "waiting" (`contact-list.tsx`) e botão
  de pausar/retomar (`chat-window.tsx` → `updateContact({ ai_paused })`).
- `PATCH /contacts/{id}` já aceita `ai_paused` (uso pela equipe).

**O que implementar:**

1. **Nova tool `request_human_handoff`** em `app/services/ai_tools.py`:
   - Declaração (`types.FunctionDeclaration`): nome `request_human_handoff`; descrição dizendo
     quando usar — o paciente pediu explicitamente falar com humano/atendente/dono; reclamação
     séria ou irritação clara; assunto clínico delicado além de informação geral (dor forte,
     complicação pós-procedimento, urgência); negociação que a Sofia não pode fazer (desconto,
     exceção de política); ou 2+ tentativas falhas de resolver a mesma coisa. Parâmetro:
     `reason` (STRING, obrigatório, motivo curto).
   - Executor `_request_human_handoff(db, tenant_id, contact_id, args)`: carrega o contato
     escopado por tenant, seta `ai_paused = True`, `flush()`, loga em nível **WARNING** com
     `extra={"tenant_id", "contact_id", "reason"}` e msg `human_handoff_requested` (fica visível
     nos logs estruturados; se os alertas de e-mail forem ligados para WARNING no futuro, já
     está pronto). Retorna `{"success": True, "message": "Atendimento transferido para a equipe.
     Envie UMA mensagem curta de despedida avisando que alguém da equipe já vai assumir."}`.
   - Registrar em `CLINIC_TOOLS` e no `execute_tool()`.
   - **Atenção:** a tool só PAUSA. Nunca aceitar `ai_paused=False` por essa via.
2. **Prompt** (`app/services/ai.py`, seção REGRAS INVARIÁVEIS): adicionar regra — quando o
   paciente pedir para falar com uma pessoa/humano/dono, estiver claramente irritado, relatar
   dor/complicação/urgência, ou você não conseguir resolver após 2 tentativas: chame
   `request_human_handoff` e responda SÓ uma despedida curta e acolhedora ("vou te passar para
   alguém da equipe, já já te respondem por aqui mesmo 😊") — sem tentar resolver de novo, sem
   prometer prazo específico. Nunca finja ser capaz de resolver o que a ferramenta não permite.
3. **Fluxo pós-handoff:** nada a mudar no webhook — com `ai_paused=True` ele já ignora os
   próximos inbounds e a equipe responde manualmente pelo Inbox (o botão de retomar já existe).

**Verificação:**
- Harness E2E: paciente manda "quero falar com uma pessoa de verdade, não com robô" → assert:
  tool `request_human_handoff` chamada, `contact.ai_paused` virou True no banco, resposta é só
  despedida curta. Segundo turno do mesmo contato → `generate_reply` nem deve ser chamado
  (simular checagem do webhook: `contact.ai_paused is True`).
- Caso negativo: conversa normal de agendamento NÃO dispara handoff.
- Rotina de verificação padrão (import backend).

---

## Item 2 — Testes automatizados (pytest)

**Objetivo:** suíte de regressão para a lógica crítica que hoje só é coberta por harnesses manuais.

**Setup:**
- Criar `requirements-dev.txt` com `pytest` e `pytest-asyncio` (não tocar no `requirements.txt`
  de produção; **não** mexer nas versões pinadas `bcrypt==3.2.2` / `httpx==0.28.1`).
- Criar `tests/` com `__init__.py` e `conftest.py`. Config `asyncio_mode=auto` via
  `pytest.ini`/`pyproject`. Testes **unitários puros** (sem DB, sem Gemini) — o que precisar de
  DB fica fora desta fase (os harnesses E2E cobrem).

**Testes a escrever (todos determinísticos):**
1. `tests/test_humanizer.py` — `split_reply()`: separa por `[[BREAK]]`; sem marcador e texto
   curto → 1 parte; respeita máximo de partes; nunca retorna parte vazia.
2. `tests/test_crm.py` — `mark_inbound()` NÃO muda `crm_stage` (só `last_inbound_at`);
   `mark_scheduled()` avança e revive `lost`, mas não regride `attended`/`post_care`;
   `mark_attended()` idem. Usar objetos `Contact` em memória (sem DB).
3. `tests/test_ai_stages.py` — `build_context_block()`: com `schedule` vazio o cabeçalho usa
   fuso `America/Sao_Paulo` (nunca UTC); a tabela de calendário tem 14 linhas com
   `date=YYYY-MM-DD` coerente com o dia da semana em pt-BR; sem appointment futuro NÃO existe a
   linha "Próximo agendamento"; com appointment futuro ela existe com o id.
4. `tests/test_clinic_info.py` — `_get_clinic_info()`: `max_installments` ausente/0/1/"abc" →
   `None` + `installments_info` dizendo que não está configurado; `=6` → 6 + texto "até 6x".
   Serviços: preço `0`/`None` → `price=None, price_unset=True` (função `_price` interna ao
   `_list_services` — se necessário, extraia-a para nível de módulo para ficar testável, sem
   mudar comportamento).
5. `tests/test_alerting.py` — `EmailAlertHandler`: nível INFO não envia; ERROR envia; erro
   idêntico dentro do intervalo é suprimido (throttle); destinatários múltiplos separados por
   vírgula. Mockar `smtplib.SMTP`/`SMTP_SSL` (padrão já usado na validação manual desta sessão).
6. `tests/test_history_markers.py` — a lógica de marcadores de tempo do histórico em
   `generate_reply` (abre/fecha bloco antigo: 1ª mensagem de dia diferente, gap ≥4h antes OU
   depois; mensagens da mesma sessão sem marcador). A lógica está inline em `generate_reply`;
   **extraia-a para uma função pura** (ex.: `_annotate_history(usable, tz, now_local)` →
   lista de `(role, text)`) e teste a função — refactor sem mudança de comportamento.

**Verificação:** `venv\Scripts\python -m pytest tests/ -v` verde + rotina padrão.

---

## Item 3 — Página "Pacientes" dedicada

**Objetivo:** rota `/dashboard/patients` com a lista completa de pacientes (hoje coberto de
forma fragmentada por Inbox/CRM), no design system Sofia (dark, glass, violeta).

**Backend:** `GET /contacts` já existe com paginação (`app/api/v1/routes/contacts.py`).
Verificar se aceita busca textual (`search`/`q`); se não aceitar, adicionar parâmetro `search`
(ilike em `full_name`/`phone`/`email`, escopado por tenant) — mudança pequena e retrocompatível.

**Frontend:**
1. `frontend/src/app/dashboard/patients/page.tsx` — nova rota:
   - Tabela glass (seguir o padrão visual de `dashboard/services/page.tsx`): colunas Paciente
     (avatar com `profile_picture_url`/inicial + nome + telefone), Estágio CRM (badge colorido
     com os MESMOS rótulos/cores do kanban: Novo Lead/Lead Frio/Lead Quente/Agendado/
     Compareceu/Pós-atendimento/Perdido), Último contato (`last_inbound_at` relativo),
     Sofia (badge "pausada" quando `ai_paused`), Ações (link para o Inbox do contato).
   - Busca no topo (nome/telefone) + filtro por estágio (dropdown).
   - Clique na linha → drawer/dialog com detalhes do contato (dados cadastrais editáveis via
     `PATCH /contacts/{id}` — reusar padrões de formulário existentes; email/data validados).
   - Estados de loading (skeleton), vazio e erro — copiar o padrão da página de serviços.
2. Hook: criar `useContacts` (ou estender o existente em `useCrm.ts`/`useInbox.ts` — verificar
   qual lista já traz `ai_paused` + `last_message` e reusar; evitar hook duplicado novo se um
   existente servir).
3. Sidebar (`frontend/src/components/layout/sidebar.tsx` ou equivalente): item "Pacientes" com
   ícone `Users` do lucide-react, marcado `adminOnly` **não** (professionals podem ver os seus —
   o backend já escopa por papel; verificar comportamento existente de `GET /contacts` para o
   papel `professional` e seguir o mesmo).

**Verificação:** `npx tsc --noEmit` + `npm run build` verdes; conferir manualmente que a página
lista, busca, filtra e edita; papel `professional` vê só o esperado.

---

## Fora deste plano (não são código / dependem do operador)

- Redeploy no EasyPanel (backend ✅ feito em 07/07 — logs confirmam; frontend a confirmar),
  rotação de credenciais, LGPD/política de privacidade, Google Calendar OAuth, chaves fortes,
  backup do Postgres, ligar `ALERT_EMAIL_*`, cadastrar dados reais da clínica (preços, horário
  de funcionamento, **parcelamento máximo** — campo novo na aba Clínica), teste de carga,
  termos de uso. Ver `PENDENCIAS.md`.

## Ao final de tudo

1. Rodar a rotina de verificação completa (backend + tsc + build).
2. Rodar `pytest tests/ -v`.
3. Atualizar os checkboxes do `PENDENCIAS.md` (handoff, testes, página Pacientes).
4. Commit por item (mensagens descritivas em inglês, padrão conventional commits do repo).
