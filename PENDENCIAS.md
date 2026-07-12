# Pendências antes de abrir o sistema ao público

Lista viva do que falta para ir de "MVP funcional" para "pronto para vender ao público".
Atualizada após a rodada de robustez (Waves 1-2: núcleo do atendimento, hardening da API,
handoff/follow-ups, testes de integração, tetos de uso de IA, LGPD manual, migração de
dependências de auth, mitigação de payload de mídia).

Legenda: ✅ feito no código · 🔴 bloqueador · 🟡 recomendado · ⏳ só você pode fazer (painel externo)

---

## ✅ Rodada de robustez (Waves 1-2) — resolvido no código

Executada em duas ondas por subagentes em paralelo (ver `PLANO_EXECUCAO.md` para o
diagnóstico e priorização original). Tudo abaixo tem testes automatizados cobrindo
(99 testes puros + 39 de integração contra Postgres real, `tests/integration/`) e passou
pelo checklist completo (pytest, alembic upgrade/downgrade round-trip, `tsc`, `npm run build`).

**Atendimento da Sofia:**
- [x] **Horário no passado oferecido/aceito no agendamento** — `check_availability` podia
  oferecer 09:00 às 16h, e nada impedia criar um agendamento ontem. Agora rejeitado em
  ambos os modos (capacity e por-profissional), com antecedência mínima configurável
  (`MIN_BOOKING_LEAD_MINUTES`, default 30 min — **valor não confirmado por você, ver
  dúvida aberta abaixo**). (`ai_tools.py`)
- [x] **Falha do Gemini quebrando a persona** — erro na chamada mandava "problema técnico,
  tente novamente" (tom de robô) e marcava a pergunta como respondida, perdendo-a. Agora
  tenta de novo silenciosamente e, se falhar tudo, NÃO marca como respondida — a pergunta
  volta a ser tratada na próxima mensagem do paciente. (`ai.py`)
- [x] **Tool `confirm_appointment`** — a Sofia agora registra de verdade quando o paciente
  confirma presença (em resposta a um lembrete ou espontaneamente), em vez de só dizer
  "confirmado!" sem mudar nada no banco. (`ai_tools.py`)
- [x] **Mensagens humanas pelo celular ignoradas** — quando alguém da equipe respondia
  direto no WhatsApp/celular (sem passar pelo sistema), a Sofia nunca via essa mensagem e
  podia contradizer o que já foi combinado. Agora é gravada no histórico, e a Sofia
  **pausa automaticamente por 60 minutos** (renovado a cada mensagem humana) para não
  disputar espaço com o atendente. (`webhooks.py`, `Contact.human_takeover_until`)
- [x] **Reengajamento genérico** — a mensagem de "sumiu, volta aqui" agora menciona o
  interesse real do paciente na conversa (quando há sinal claro), em vez de um texto
  sempre igual. (`ai.py::generate_followup_message`, `followups.py`)
- [x] **Lembrete de agendamento sempre com o mesmo texto** — 6 variações, sorteadas a
  cada envio. (`followups.py`)
- [x] **Tetos de uso diário de IA** — 40 respostas/contato/dia e 400/clínica/dia (valores
  que você aprovou); ao estourar, pausa e envia alerta por e-mail em vez de continuar
  respondendo sem limite. **Já LIGADO por padrão** (`AI_USAGE_LIMITS_ENABLED=True`).
- [x] **Alerta ativo de handoff** — quando a Sofia transfere para humano, agora envia
  e-mail para `tenant.email` (desativável em Configurações → Follow-ups), além do badge
  visual. Novo job a cada 10 min alerta se um contato pausado ficar sem resposta humana
  por tempo demais (`HANDOFF_ALERT_JOB_MINUTES`).
- [x] **UI com dados fabricados removida** — card "Análise de Presença Online" (85%/+12%
  inventados) e botão "Sofia Insights" sem função, ambos removidos do painel.

**Segurança e isolamento:**
- [x] **Webhook do WhatsApp fail-open sem segredo** — agora rejeita por padrão quando o
  tenant não tem `webhook_secret` gravado (antes aceitava qualquer request). Comparação
  agora é constant-time. **Tenants antigos sem secret vão parar de receber mensagens até
  reconectar o WhatsApp** — verifique isso nos logs de boot (WARNING por tenant afetado).
- [x] **Duplicação de mensagem em entrega concorrente do webhook** — constraint real de
  unicidade no banco (antes só uma checagem em código, que não protegia contra corrida).
- [x] **`PATCH /tenants/me` aceitando sobrescrever segredos** — um admin da clínica podia,
  sem querer ou não, sobrescrever `webhook_secret`/`token` do WhatsApp via um PATCH normal
  de configurações, ou se auto-promover de plano. Ambos bloqueados agora.
- [x] **Profissional lendo conversa de paciente de outro profissional** — a listagem já
  filtrava certo, mas os endpoints de detalhe/mensagens/edição de contato não. Corrigido
  em todos os pontos.
- [x] **Bug real de segurança encontrado pelos testes**: a revogação de família de refresh
  token (proteção contra reuso de token roubado) era descartada por rollback — o token
  irmão do atacante continuava válido mesmo depois do sistema "detectar" o roubo. Corrigido
  e coberto por teste de regressão. (`app/services/tokens.py`)
- [x] **`python-jose`/`passlib` (sem manutenção ativa) substituídos** por `PyJWT` e uso
  direto de `bcrypt` — sem quebra de compatibilidade (tokens e senhas já existentes
  continuam válidos, testado manualmente).

**Recuperação e resiliência:**
- [x] **Mensagem perdida se o servidor reiniciar durante a janela de espera** — uma
  varredura no boot recupera conversas com mensagem do paciente sem resposta.

**LGPD (manual, conforme sua decisão — sem automação de retenção):**
- [x] **Exportação de dados do paciente** — `GET /contacts/{id}/export`.
- [x] **Anonimização/"direito ao esquecimento"** — `POST /contacts/{id}/anonymize`
  (irreversível; limpa também o telefone, então uma mensagem futura desse número vira um
  contato novo em vez de reativar o antigo).

**Performance/payload:**
- [x] **Payload de mídia inflando listagem do Inbox e a memória da IA** — a listagem de
  contatos e o histórico interno que a IA lê não carregam mais o `media_url` (só a
  conversa aberta, que precisa de verdade). Medido: ~4,27MB → 883 bytes por contato na
  listagem, num teste com 2 fotos.

**Testes (novos, cobrindo tudo acima):**
- [x] Suíte de integração com Postgres real (`tests/integration/`) — isolamento entre
  clínicas, autenticação, webhook (fail-closed, idempotência, auto-pausa, tetos de IA,
  `confirm_appointment`), e os dois endpoints de LGPD. 39 testes.
- [x] Harness de teste E2E manual contra o Gemini real (`scripts/e2e_sofia.py`) — 9
  cenários prontos (agendamento feliz, data relativa, horário passado, preço/parcelamento
  não configurados, objeção de preço, pedido de humano, confirmação pós-lembrete, "você é
  um robô?"). **Só roda manualmente** (`venv\Scripts\python scripts\e2e_sofia.py
  --scenario <nome>`) — cada rodada com `--all` custa dinheiro real de API, nunca
  automatize isso. Ainda não foi rodado por completo — recomendo rodar antes do próximo
  redeploy para validar visualmente as conversas.

> ⚠️ **Tudo isso só chega aos pacientes após o REDEPLOY em produção** (ver bloqueador abaixo).

---

## 🔴 Novo bloqueador desta rodada

- [ ] ⏳ **Rotacionar a `GEMINI_API_KEY` de novo** — durante esta rodada, um agente
  copiou o `.env` e a chave real acabou aparecendo em texto claro num arquivo de log local
  de transcript (não foi publicado nem enviado a lugar nenhum, mas rotacionar é a prática
  seguro). Gere uma nova chave e atualize `.env` local + EasyPanel.

## Dúvidas abertas (defaults assumidos — confirme ou ajuste)

- **Antecedência mínima para agendar no mesmo dia**: adotei 30 minutos
  (`MIN_BOOKING_LEAD_MINUTES`). Ajuste se quiser outro valor.
- **Limiar do alerta de "pausado esquecido"**: 30 minutos sem resposta humana após o
  handoff. Ajuste se quiser outro valor.
- **E-mail de destino dos alertas** (handoff, teto de IA, "pausado esquecido"): hoje vai
  para `tenant.email` (o cadastro da própria clínica). Se preferir um e-mail operacional
  separado, isso precisa de um campo novo.

---

## ✅ Resolvido no código (rodada anterior)

- [x] **Fuso horário / datas erradas** — o default caía em UTC, então clínicas sem
  timezone configurado (o caso real) tinham a data "virando" para o dia seguinte à
  noite. Default agora é `America/Sao_Paulo`. (`ai_tools.py`)
- [x] **Sofia confundindo contexto antigo** — o histórico ia para o modelo sem
  nenhuma marca de tempo, então mensagens de dias atrás pareciam atuais (agendamento
  fantasma, assunto velho retomado). Agora mensagens antigas levam marcador
  `[dia dd/mm/aaaa hh:mm]`. (`ai.py`)
- [x] **Crash com resposta vazia do Gemini** — `parts=None` (thinking estourando o
  limite de tokens) quebrava a resposta. Thinking desligado + guarda contra vazio. (`ai.py`)
- [x] **Preço R$ 0,00** — serviço sem preço (price 0/nulo) fazia a Sofia dizer
  "R$ 0,00". Agora vira "valor avaliado na consulta", no backend (tool) e no frontend
  (badge "Valor na consulta"). (`ai_tools.py`, `services/page.tsx`)
- [x] **Atendimento multimodal** — prompt reforçado para responder ao CONTEÚDO de
  foto/áudio (comum em estética), ligar a um serviço real e conduzir à avaliação, sem
  diagnosticar. Pipeline testado. (`ai.py`)
- [x] **Técnica de vendas / objeções / classificação frio-quente** — playbook de
  objeções, técnicas de fechamento, e classificação de CRM (hot/cold lead). (`ai.py`, `ai_tools.py`)
- [x] **Default de modelo deprecado** — `gemini-2.0-flash` trocado por
  `gemini-2.5-flash` no frontend, backend e `.env.example`.
- [x] **Alertas de erro por e-mail** — handler que envia e-mail em log de nível ERROR,
  em thread separada (não bloqueia) e com throttle anti-tempestade. Desligado por
  padrão; ligar via `ALERT_EMAIL_ENABLED=true` + SMTP no `.env`/EasyPanel. (`app/core/alerting.py`)
- [x] **Sofia inventando parcelamento ("até 3x")** — conversa real mostrou a Sofia
  afirmando um número de parcelas que não existe nos dados. Novo campo estruturado
  `max_installments` na aba Clínica (Configurações → formas de pagamento); a tool
  `get_clinic_info` agora expõe o valor (ou avisa "não configurado — não invente") e o
  prompt proíbe citar parcelas sem o dado. Reproduzido e validado com o cenário real.
  (`ai_tools.py`, `ai.py`, `clinic-tab.tsx`, `useSettings.ts`)
- [x] **Deploy que morria se o Postgres não estivesse resolvível** — o CMD do Dockerfile
  agora tenta a migração 12x com 5s de pausa antes de desistir (corrida de DNS do
  EasyPanel vista nos logs de deploy). (`Dockerfile`)

> ⚠️ **Tudo isso só chega aos pacientes após o REDEPLOY em produção** (ver bloqueador abaixo).

---

## 🔴 Bloqueadores — só você pode fazer (painéis externos)

- [ ] ⏳ **Redeploy do backend + frontend no EasyPanel** — PARCIAL
  - ✅ Backend redeployado em 07/07 (logs confirmam: migração `c3d4e5f6a7b8` aplicada,
    app saudável). Porém os commits de 07/07 à tarde (parcelamento, retry do deploy)
    exigem **novo** redeploy do backend + rebuild do frontend (campo de parcelas na aba Clínica).
  - Frontend: confirmar se já foi redeployado com o design novo.

- [ ] ⏳ **Rotacionar credenciais expostas no chat**
  - Admin token da UAZAPI (`UAZAPI_ADMIN_TOKEN`) e a API key do Google (Stitch).
  - Gerar novas em cada painel e atualizar no `.env` local **e** no EasyPanel.

- [ ] ⏳ **LGPD — política de privacidade + base legal** (dados de saúde no Brasil)
  - Publicar política de privacidade linkável.
  - Definir base legal para tratamento de dados de pacientes.
  - **Decisão registrada:** a Sofia vai **continuar se passando por atendente humana**
    (sem aviso de "sou uma IA"), por escolha de negócio. Isso é legítimo, mas **aumenta**
    a importância da política de privacidade e da base legal — não reduz. Reavaliar com
    apoio jurídico antes do lançamento público amplo.
  - ✅ **Suporte técnico já existe** (rodada de robustez): exportação e anonimização
    manuais de dados do paciente, sob demanda da equipe da clínica (ver seção acima).
    Automação de retenção/exclusão automática continua **fora de escopo** por decisão sua
    — só implementar com um go-ahead explícito.

- [ ] ⏳ **Configurar Google Calendar OAuth no Google Cloud Console**
  - Criar projeto, habilitar Google Calendar API, tela de consentimento OAuth.
  - Criar credenciais (Client ID + Secret) com os redirect URIs corretos.
  - `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` / `GOOGLE_REDIRECT_URI` no `.env` e EasyPanel.
  - Para uso público sem aviso de "app não verificado": submeter para verificação do Google.

---

## 🟡 Recomendado — só você pode fazer (produção/infra)

- [ ] ⏳ **1 único worker do backend no EasyPanel** — scheduler e message batcher são
  estado em memória; 2+ workers duplicam lembretes e quebram o debounce silenciosamente.
- [ ] ⏳ **`SECRET_KEY` e `ENCRYPTION_KEY` fortes em produção** — não podem ser os
  defaults do `.env.example`. (O backend já recusa subir com SECRET_KEY fraca fora de DEBUG.)
- [ ] ⏳ **Backup do banco (Postgres)** — confirmar backup automático do EasyPanel ou `pg_dump` agendado.
- [ ] ⏳ **Ligar os alertas de e-mail** — código pronto; preencher `ALERT_*` no EasyPanel
  (`ALERT_EMAIL_ENABLED=true` + SMTP). Sugestão: e-mail dedicado com senha de app.
- [ ] ⏳ **Cadastrar os dados reais da clínica** — o tenant real tem serviços com preço 0
  e **sem horário de funcionamento configurado**. O código agora lida com isso graciosamente,
  mas para a Sofia informar preços e horários corretos, a clínica precisa preencher:
  preços dos serviços, horário de funcionamento (dias, abertura/fechamento) e timezone.
- [ ] ⏳ **Testar o fluxo por profissional de ponta a ponta em produção** — configurar um
  profissional (serviços + horários), agendar via WhatsApp, confirmar atribuição e o evento
  no Google Calendar. A lógica está implementada e revisada, mas nunca exercida em produção.

---

## 🟢 Bom ter (pode esperar o pós-lançamento)

Os 3 itens do [`PLANO_IMPLEMENTACAO.md`](PLANO_IMPLEMENTACAO.md) foram **implementados**:

- [x] **Handoff humano** (Item 1) — tool `request_human_handoff` pausa a Sofia (`ai_paused`,
  unidirecional) quando o paciente pede humano, está irritado ou relata urgência.
- [x] **Testes automatizados** (Item 2) — suíte pytest (`tests/`, `pytest.ini`,
  `requirements-dev.txt`): 51 testes puros (sem DB, sem Gemini). `venv\Scripts\python -m pytest tests/ -q`.
- [x] **Página "Pacientes" dedicada** (Item 3) — `/dashboard/patients` com busca, filtro por
  estágio, badge de Sofia pausada e edição; deep-link `?contact=<id>` para o Inbox.
- [ ] **Confirmar presença "digitando" com log real** em produção.
- [ ] **Termos de uso / contrato de adesão** para as clínicas clientes.
- [ ] **Teste de carga** com múltiplos tenants simultâneos.

## ✅ Correções desta rodada (a partir de conversa real)

- [x] **Sofia se revelou como IA** — regra absoluta no prompt: ela é uma pessoa para o paciente,
  nunca diz/insinua que é IA/robô; removido "virtual" das identidades internas.
- [x] **Sofia inventou que a consulta é "de graça"** — nova política estruturada de avaliação
  na aba Clínica (gratuita / com custo / abate no procedimento). Sem configurar, ela não afirma
  nem grátis nem pago.
- [x] **Áudio não entendido** — quando o paciente mandava 2 áudios seguidos, só o último ia para
  a IA. Agora todas as mídias da rajada são enviadas juntas.
- [x] **Logs visuais** — formatter de texto legível (ícones + rótulos pt-BR); `LOG_FORMAT=text`
  virou o padrão (console do EasyPanel fica legível sem configurar nada).

> ⚠️ Tudo isso exige **novo redeploy** do backend + frontend para valer em produção.
> E preencher, na aba Clínica: parcelamento máximo e a política de avaliação.

---

## Rotina de verificação após qualquer mudança de código
```bash
# Backend
venv\Scripts\python -c "import app.main; print('OK')"
venv\Scripts\python -m pytest tests/ -q              # suíte pura (rápida, sem DB)

# Backend — suíte de integração (Postgres real, sem custo de Gemini — tudo mockado)
docker compose up -d
venv\Scripts\python -m pytest tests/integration -q

# Frontend
cd frontend
npx tsc --noEmit
npm run build
```

Harness E2E manual contra o Gemini real (custa dinheiro — nunca automatize):
```bash
venv\Scripts\python scripts\e2e_sofia.py --list
venv\Scripts\python scripts\e2e_sofia.py --scenario <nome>
```
