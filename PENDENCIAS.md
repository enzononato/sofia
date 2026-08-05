# Pendências antes de abrir o sistema ao público

Lista viva do que **falta**. Itens concluídos são removidos daqui (o histórico fica no git).

**Estado geral:** o núcleo funciona ponta a ponta — webhook → Sofia → resposta humanizada no
WhatsApp, Inbox em tempo real (SSE), CRM, agenda, relatórios, equipe/convites, LGPD manual.
Suíte automatizada: **200 testes puros** (`pytest tests/`, sem DB, ~2s) + **53 testes de
integração** contra Postgres real (`tests/integration/`, Gemini e UAZAPI mockados).
O que sobrou são pontos mortos de UI, dados fabricados em telas de configuração, limites de
paginação que escondem pacientes, e as tarefas de painel externo que só você pode fazer.

Legenda: 🔴 bloqueador · 🟡 recomendado · ⏳ só você pode fazer (painel externo) · 🟢 bom ter

---

## 🔴 Bloqueadores — código

- [ ] **A landing page `/` ainda é o template do create-next-app**
  (`frontend/src/app/page.tsx`) — logo do Next.js e links para `vercel.com/new`,
  `nextjs.org/docs` e `nextjs.org/learn`. Qualquer visitante que abrir a raiz do domínio vê
  isso. Precisa virar uma landing real ou, no mínimo, um redirect para `/login`.

- [ ] **Não existe recuperação de senha em lugar nenhum.**
  - `app/api/v1/routes/auth.py` tem apenas signup/login/refresh/logout/accept-invite —
    nenhum `forgot-password` / `reset-password`.
  - O link "Esqueceu?" na tela de login (`frontend/src/app/login/page.tsx:196`) é
    `href="#"` — botão morto.
  - O backend **já aceita** trocar senha (`PATCH /users/{id}` com `password`, ver
    `app/api/v1/routes/users.py:271`), mas o painel nunca expõe isso: `UserUpdate` em
    `frontend/src/hooks/useTeam.ts:33` só tem `full_name/role/is_active`, e o campo de senha
    do modal de Equipe só aparece na criação.
  - Resultado prático: recepcionista que esquece a senha fica travada e só se resolve com
    acesso direto ao banco. Para um SaaS aberto ao público, isso é bloqueador.

- [ ] **"Feriados e Datas Especiais" é 100% falso** —
  `frontend/src/components/settings/schedule-tab.tsx:259-307`. Dois feriados chumbados no
  código ("Independência do Brasil 07/09" e "Nossa Sra. Aparecida 12/10"), botão
  "Adicionar Data" **sem `onClick`**, e os "X" de remover também **sem `onClick`**. Não existe
  campo de feriados em `TenantSettings` nem no backend, e `check_availability`
  (`app/services/ai_tools.py`) não sabe o que é feriado. A clínica olha essa tela, acredita
  que está fechada nessas datas, e a Sofia agenda paciente normalmente. Ou implementa de
  verdade (campo em `settings.schedule.holidays` + filtro na disponibilidade) ou remove a
  seção — deixar como está é pior que não ter.

- [ ] **Inbox, Calendário e CRM só enxergam a primeira página de contatos.**
  `useContacts()` (`frontend/src/hooks/useInbox.ts:48`) chama `/contacts` **sem `limit`**, ou
  seja, `DEFAULT_PAGE_LIMIT = 50` (`app/config.py:172`). Não há paginação nem scroll infinito
  em lugar nenhum. Cascata de consequências reais assim que a clínica passar de 50 pacientes:
  - **Busca do Inbox não acha ninguém antigo** — `contact-list.tsx:23` filtra **no cliente**
    sobre esses 50, enquanto o backend já suporta `?search=` server-side (usado só pela página
    Pacientes). O usuário digita o nome e vê "Nenhum paciente encontrado".
  - **Não dá para agendar paciente antigo** — o `<select>` de paciente em
    `appointment-modal.tsx:166` lista apenas esses 50, e não tem busca.
  - **A agenda mostra "Paciente" no lugar do nome** — `daily-timeline.tsx:112` faz
    `contacts.find(...)` e cai no fallback `"Paciente"` quando o contato não está nos 50.
  - **O badge da sidebar subconta** — `sidebar.tsx:42` conta `ai_paused` só nos 50.
  - **O deep-link `?contact=<id>` da página Pacientes falha em silêncio** —
    `inbox-layout.tsx:24` só abre a conversa se o id estiver na lista já carregada.
  - CRM (`useCrm.ts:37`, `limit: 200` = teto máximo) e Pacientes (`usePatients.ts:48`,
    `limit: 100`) truncam sem avisar. Em Pacientes, os cards "Total de Pacientes /
    Leads Quentes / Sofia Pausada" contam `patients.length` (a página buscada), não
    `meta.total` — então a partir de 100 contatos o "Total" mostra 100 para sempre.

---

## 🔴 Bloqueadores — só você pode fazer (painéis externos)

- [ ] ⏳ **Rotacionar a `GEMINI_API_KEY`** — a chave real vazou em texto claro num arquivo de
  transcript local numa rodada anterior (não foi publicada em lugar nenhum, mas rotacionar é a
  prática segura). Gere uma nova e atualize `.env` local + EasyPanel.

- [ ] ⏳ **Rotacionar as demais credenciais expostas em chat** — admin token da UAZAPI
  (`UAZAPI_ADMIN_TOKEN`) e a API key do Google (Stitch). Gerar novas em cada painel e atualizar
  no `.env` local **e** no EasyPanel.

- [ ] ⏳ **Redeploy do backend + rebuild do frontend no EasyPanel** — nada do que foi feito
  desde o último deploy (remoção do handoff, releitura de estado fresco no `_generate_and_send`,
  copiloto "Sugerir resposta", SSE do Inbox, filtro por profissional no calendário) chega aos
  pacientes sem isso.

- [ ] ⏳ **LGPD — política de privacidade + base legal** (dados de saúde no Brasil)
  - Publicar política de privacidade linkável.
  - Definir base legal para tratamento de dados de pacientes.
  - **Decisão registrada:** a Sofia continua se passando por atendente humana (sem aviso de
    "sou uma IA"), por escolha de negócio. Isso é legítimo, mas **aumenta** a importância da
    política e da base legal — não reduz. Reavaliar com apoio jurídico antes do lançamento
    público amplo.

- [ ] ⏳ **Google Calendar: submeter o app para verificação do Google**
  - ✅ As credenciais **já estão configuradas em produção**: os logs do EasyPanel mostram
    `⏰ agendador iniciado ... gcal=True` e o job `run_google_sync_reconcile` executando a cada
    15 min com sucesso. `GOOGLE_CLIENT_ID`/`SECRET`/`REDIRECT_URI` estão no ambiente.
  - Falta apenas: para uso público sem a tela de aviso "app não verificado", submeter o app
    para verificação do Google (processo do Google Cloud Console, leva dias).
  - Continua valendo o item da seção "Recomendado": a sincronização é só de ida (o
    `check_availability` não consulta o free/busy do profissional).

---

## 🟡 Recomendado — código

- [ ] **Dados fabricados ainda presentes nas telas de Configurações.** O painel principal já foi
  limpo, mas duas abas continuam mostrando números inventados como se fossem métricas reais:
  - `settings/followups-tab.tsx:264-283` — card "Resumo da Atividade": "Lembretes hoje **128**",
    "Leads reengajados **12**", barra fixa em `w-3/4` com "Eficiência das Automações: **75%**".
    Tudo chumbado.
  - `settings/followups-tab.tsx:259` — "reduzem o No-show em até **34%**" (estatística
    inventada).
  - `settings/followups-tab.tsx:295` — preview do WhatsApp chumba o nome de outra clínica
    ("Lumina Clinic") em vez de usar `tenant.name`.
  - `settings/schedule-tab.tsx:334-358` — card "Resumo de Atendimento": "48 horas",
    "14 pacientes/dia", "8 turnos", barra em 82% com "82% OCUPADA". Tudo chumbado.
  - `settings/schedule-tab.tsx:322-330` — "Dica da Sofia" afirma "Notei que suas segundas-feiras
    costumam ter alta demanda" (nenhuma análise existe) e o botão **"Aplicar Sugestão" não tem
    `onClick`**.
  - `settings/schedule-tab.tsx:367` — "Ver Tutorial" com `href="#"`.

- [ ] **"Canal de envio prioritário" (WhatsApp / E-mail) é decorativo** —
  `settings/followups-tab.tsx:128-143`: dois `<button>` sem `onClick`, sem estado, sem
  persistência. Pior: o cabeçalho da seção diz "Envio automático via WhatsApp **e E-mail**",
  mas `app/services/followups.py` só envia por WhatsApp — não existe canal de e-mail para
  lembretes. Remover os botões e corrigir o texto, ou implementar o canal.

- [ ] **O Inbox só carrega as últimas 25 mensagens e não tem como ver o histórico antigo.**
  `useMessages` (`frontend/src/hooks/useInbox.ts:76`) manda `limit: MESSAGES_POLL_LIMIT` (25)
  **também na primeira carga**, e `chat-window.tsx` não tem nenhum handler de scroll-up nem
  botão "carregar mais". O comentário no próprio `useInbox.ts` afirma que o histórico completo
  vem "ao rolar para cima" — esse caminho não existe no código. Conversa longa fica com o começo
  inacessível pelo painel.

- [ ] **A pausa por atendimento humano é invisível no painel.** `Contact.human_takeover_until`
  (pausa automática de 60 min quando alguém da equipe responde direto pelo celular) **não está
  em `ContactRead`** (`app/schemas/contact.py:47`), então o frontend não recebe esse campo. O
  chat mostra "Secretária IA: **Ativa**" enquanto a Sofia está calada, e ninguém entende por
  quê. Expor o campo e mostrar um badge tipo "pausada até HH:MM (atendimento humano)".

- [ ] **LGPD implementada no backend, inalcançável pelo painel (funcionalidade órfã).**
  `GET /contacts/{id}/export` e `POST /contacts/{id}/anonymize`
  (`app/api/v1/routes/privacy.py`) existem, têm 7 testes de integração e nenhuma UI: nenhum
  hook do frontend chama `/export` ou `/anonymize`. Na prática, atender um pedido de acesso ou
  de esquecimento hoje exige curl/Postman. Um botão na página Pacientes (exportar JSON) e um
  em modal de confirmação (anonimizar, só owner/admin) fecham isso.

- [ ] **A Sofia multi-agente está pronta e desligada, sem nenhum jeito de ligar pela UI.**
  `AI_MULTI_AGENT_ENABLED = False` (`app/config.py:206`); o override por clínica é
  `tenant.ai_config["multi_agent_enabled"]`, que nenhuma tela escreve (a aba IA em
  `settings/ai-tab.tsx` só gerencia model/temperature/max_tokens/multimodal/scheduling_mode).
  São ~880 linhas em `app/services/agents/` + 35 testes puros + 2 de integração rodando como
  código morto em produção. Decidir: expor um toggle (mesmo que escondido/admin) para canariar
  em 1-2 clínicas, ou assumir que fica desligado.

- [ ] **Sincronização com Google Calendar é só de ida.** `app/services/google_calendar.py`
  empurra agendamentos do SaaS para o Google, mas `check_availability`
  (`app/services/ai_tools.py`) nunca consulta o free/busy do profissional — não há nenhuma
  chamada de `freeBusy` no código. Um compromisso pessoal bloqueado no Google Agenda do
  profissional não impede a Sofia de marcar por cima. Relevante justamente no modo
  "por profissional", que é o default.

- [ ] **`/docs`, `/redoc` e `/openapi.json` são públicos em produção** — estão em
  `_PUBLIC_PATHS` (`app/middleware/tenant.py:36-42`) sem nenhuma condição de `DEBUG`. Toda a
  superfície da API fica documentada para qualquer um. Desabilitar fora de `DEBUG`
  (`docs_url=None` em `app/main.py:86`) ou proteger com auth.

- [ ] **Não existe cadastro manual de paciente.** Não há `POST /contacts` no backend — um
  contato só nasce de uma mensagem no WhatsApp (`webhooks.py`). Paciente que ligou, ou que a
  clínica quer pré-cadastrar antes do primeiro contato, não tem como entrar no sistema, e por
  consequência não tem como ser agendado.

- [ ] **Pausa da Sofia: semântica inconsistente e kill-switch invisível.**
  - Responder pelo painel (`contacts.py`, `send_manual_message`/`send_media_message`) faz
    `ai_paused = True` **permanente** — a recepcionista responde uma vez e a Sofia fica muda
    para aquele paciente indefinidamente, inclusive no sábado à noite. O mesmo ato feito pelo
    celular gera janela de 60 min que expira sozinha. Unificar na janela auto-expirante,
    deixando o toggle do header para a pausa permanente explícita.
  - O teto diário por clínica escreve `tenant.settings["ai_paused"] = True`, o que **desliga a
    Sofia para a clínica inteira**, e não existe nenhuma UI para ver ou limpar isso (só
    editando o banco). Falta um banner no dashboard com botão "Reativar Sofia" — o
    `PATCH /tenants/me` já faz deep-merge de `settings`, não precisa de endpoint novo.
  - Consequência hoje: o filtro "Aguardando Humano" e o badge da sidebar acumulam para sempre
    toda conversa que alguém já respondeu uma vez — a métrica vira ruído.

- [ ] **O painel não mostra nada sobre a Sofia — maior gap de retenção.** `GET /reports/overview`
  traz leads, conversão, no-show e volume de mensagens, mas nada responde "o que a Sofia fez por
  mim este mês?". Os dados já existem, exceto um campo: `Message.ai_model_used IS NOT NULL` dá
  as respostas dela, `crm_stage_source='ai'` dá os leads que ela qualificou, e o tempo de
  primeira resposta sai dos timestamps. Falta apenas `Appointment.created_by` (`"ai" | "staff"`)
  para poder dizer quantos agendamentos ela gerou.

- [ ] **`attended`/`no_show` são zumbis e o KPI de no-show mente.** Nada marca um agendamento
  como concluído ou faltado automaticamente; depende de alguém abrir o modal do calendário todo
  dia. Na prática a coluna "Compareceu" do Kanban fica vazia, `no_show_rate` mostra 0% para
  sempre, e o estágio `post_care` nunca acontece. Uma lista "pendentes de fechamento"
  (agendamentos cuja data já passou e ainda estão `scheduled`/`confirmed`) com dois botões
  resolve sem automação escondida.

- [ ] **Remarcação/cancelamento feitos no painel não avisam o paciente.**
  `PATCH /appointments/{id}` altera a data e só sincroniza o Google Calendar. A recepcionista
  remarca e o paciente aparece no horário antigo.

- [ ] **Tool writes são commitados antes da checagem de "resposta superada".** Em
  `_generate_and_send`, o `commit()` acontece antes de `_has_newer_inbound`. Se o paciente
  escreveu enquanto a Sofia "digitava", a resposta é abortada — mas o `create_appointment` já
  foi gravado e ele nunca recebeu a confirmação. Ele acha que não agendou; a agenda diz que sim.

- [ ] **A memória efetiva da Sofia é ~metade do que parece.** `AI_HISTORY_LIMIT=20`, mas cada
  resposta dela vira uma `Message` por PARTE (o `[[BREAK]]` divide antes de salvar). Com
  respostas de 2-3 partes, 20 mensagens cobrem só ~5 trocas reais — é isso que faz ela
  "esquecer" o que foi combinado 10 minutos antes. Coalescer turnos consecutivos do mesmo papel
  em `build_conversation_contents` resolve sem aumentar custo.

- [ ] **Textos de sistema quebram a persona** — "só consigo responder mensagens de texto",
  "muito grande para processar", "tive um probleminha para processar sua mensagem". Além do tom
  robótico, alguns são enviados fora do pipeline de humanização (sem read receipt, sem
  "digitando", sem delay), então chegam instantaneamente enquanto todo o resto demora ~20s — o
  que os denuncia ainda mais.

- [ ] **Dois fallbacks de erro contradizem a decisão de "ficar em silêncio".** O
  `AIGenerationError` foi desenhado para não mandar texto robótico e não marcar a rajada como
  respondida. Mas os outros dois caminhos de falha (candidato vazio após retry, e loop de tools
  esgotado) retornam texto normalmente — ele é enviado E a pergunta do paciente é marcada como
  respondida, perdendo-a para sempre.

- [ ] **Lacunas concretas de teste** (não é "escrever mais testes" genérico — são caminhos que
  mandam mensagem/e-mail para paciente real ou fazem controle de acesso, hoje sem nenhuma
  cobertura):
  - `app/services/followups.py` — os guards de envio proativo já têm 20 testes puros
    (`tests/test_followups_guards.py`), mas os 3 jobs em si continuam sem teste de ponta a
    ponta: janelas de lembrete, anti-duplicidade via `Appointment.reminders`, cooldown de
    reengajamento e deduplicação de "episódio" via `Contact.handoff_alerted_at`. Um bug aqui
    manda mensagem repetida para paciente.
  - `app/api/v1/routes/users.py` + convites + `POST /auth/accept-invite` — **zero testes**.
    Ficam sem cobertura as guardas de escalonamento de privilégio: "só OWNER cria OWNER",
    "não é possível convidar como proprietário", revogação e expiração de convite,
    `revoke_all_user_tokens` na troca de senha/desativação.
  - `app/api/v1/routes/appointments.py` — a constraint de sobreposição
    (`no_overlap_per_professional` → 409), o `cancellation_reason` obrigatório no cancelamento
    e o recálculo de `ends_at` não têm teste.
  - `app/api/v1/routes/reports.py` — só há teste de isolamento entre clínicas
    (`test_tenant_isolation.py:262`); a agregação em si (`conversion_rate`, `no_show_rate`,
    séries com dias vazios) nunca é verificada.
  - `app/services/google_calendar.py` — zero testes.

- [ ] **Ajustes pequenos, todos verificados:**
  - `dashboard/navbar.tsx:52` — o rótulo de papel cai em "Profissional" para
    `receptionist` e `viewer`; uma recepcionista vê "Profissional" no cabeçalho.
  - `inbox/inbox-layout.tsx:14` — `error` é desestruturado de `useContacts()` e nunca usado:
    se `/contacts` falhar, o Inbox mostra "Nenhum paciente encontrado" para sempre, sem
    estado de erro.
  - `settings/followups-tab.tsx:232` — o texto do alerta ainda diz "quando a Sofia transfere
    uma conversa para a equipe". A Sofia não transfere mais nada; hoje o alerta dispara por
    teto de uso de IA ou pausa manual no Inbox. Reescrever o rótulo.
  - `app/services/alerts.py:41,65` — o corpo dos e-mails de alerta também descreve
    transferência ("A Sofia transferiu esta conversa para a equipe"). Mesmo ajuste.

---

## 🟡 Multi-agente — consertado, aguardando piloto

Você optou por consertar e ligar. O trabalho de código está feito: prompts unificados numa
fonte única (), tools alinhadas por agente (Sales ganhou
// por ser a rota padrão do
Router; Booking ganhou ), e 17 invariantes de prompt travadas por teste.
O toggle por clínica está em **Configurações → IA → "Atendimento por especialistas (beta)"**.

- [ ] ⏳ **Ativar em UMA clínica de teste primeiro** e acompanhar as conversas. Custa de 2 a 3
  chamadas ao Gemini por mensagem (contra 1 hoje), então o custo sobe proporcionalmente.
- [ ] **Limitar partes no modo composite** — dois especialistas × até 3 partes dá até 6 mensagens
  seguidas no WhatsApp, contra a regra de "prefira 1, máximo 3". O segundo especialista também
  não sabe que o primeiro já fez um convite, então podem sair dois CTAs na mesma resposta.
- [ ] **Rodar o harness E2E manual nos dois caminhos** antes de considerar fechado
  (). Custa dinheiro de API; os transcripts que existem no repo são de
  07/07 e são anteriores a praticamente todas as regras atuais.

## 🟡 Recomendado — só você pode fazer (produção/infra)

- [ ] ⏳ **1 único worker do backend no EasyPanel** — scheduler e message batcher são estado em
  memória; 2+ workers duplicam lembretes e quebram o debounce silenciosamente.
- [ ] ⏳ **`SECRET_KEY` e `ENCRYPTION_KEY` fortes em produção** — não podem ser os defaults do
  `.env.example`. (O backend já recusa subir com `SECRET_KEY` fraca fora de `DEBUG` —
  `app/config.py:216`.)
- [ ] ⏳ **Backup do banco (Postgres)** — confirmar backup automático do EasyPanel ou `pg_dump`
  agendado.
- [ ] ⏳ **Ligar os alertas de e-mail** — código pronto (`app/core/alerting.py`); preencher os
  `ALERT_*` no EasyPanel (`ALERT_EMAIL_ENABLED=true` + SMTP). Sugestão: e-mail dedicado com
  senha de app. Sem isso, os alertas de teto de uso de IA e de "pausado e esquecido" não saem.
- [ ] ⏳ **Cadastrar os dados reais da clínica** — o tenant real tem serviços com preço 0 e
  **sem horário de funcionamento configurado**. O código lida com isso graciosamente, mas para a
  Sofia informar preços e horários corretos a clínica precisa preencher: preços dos serviços,
  horário de funcionamento (dias, abertura/fechamento), timezone, parcelamento máximo e a
  política de avaliação (aba Clínica).
- [ ] ⏳ **Testar o fluxo por profissional de ponta a ponta em produção** — configurar um
  profissional (serviços + horários), agendar via WhatsApp, confirmar a atribuição e o evento no
  Google Calendar. A lógica está implementada e revisada, mas nunca foi exercida em produção.
- [ ] ⏳ **Rodar o harness E2E manual contra o Gemini real antes do próximo redeploy** —
  `venv\Scripts\python scripts\e2e_sofia.py --list` para ver os cenários. Custa dinheiro de API
  a cada rodada; nunca automatizar. Nunca foi rodado por completo.

---

## Dúvidas abertas (defaults assumidos — confirme ou ajuste)

- **Antecedência mínima para agendar no mesmo dia**: 30 minutos
  (`MIN_BOOKING_LEAD_MINUTES`, `app/config.py:50`).
- **Limiar do alerta de "pausado e esquecido"**: 30 minutos sem resposta humana
  (`HANDOFF_ALERT_STALE_MINUTES`).
- **E-mail de destino dos alertas** (teto de IA, "pausado esquecido"): hoje vai para
  `tenant.email` (o cadastro da própria clínica). Se preferir um e-mail operacional separado,
  isso precisa de um campo novo.

---

## 🟢 Bom ter (pode esperar o pós-lançamento)

- [ ] Confirmar a presença "digitando" com log real em produção (a UAZAPI precisa estar
  enviando o evento `presence`; a lista de eventos só é reaplicada quando a clínica **reconecta**
  o WhatsApp).
- [ ] Termos de uso / contrato de adesão para as clínicas clientes.
- [ ] Teste de carga com múltiplos tenants simultâneos.
- [ ] Exclusão de serviço e remoção de membro da equipe — hoje só existe desativar
  (`is_active`), sem `DELETE` no backend. Aceitável, mas some da UI que existe uma diferença.

---

## Rotina de verificação após qualquer mudança de código

```bash
# Backend
venv\Scripts\python -c "import app.main; print('OK')"
venv\Scripts\python -m pytest tests/ -q              # suíte pura (200 testes, ~2s, sem DB)

# Backend — suíte de integração (Postgres real, sem custo de Gemini — tudo mockado)
docker compose up -d
venv\Scripts\python -m pytest tests/integration -q   # 48 testes

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
