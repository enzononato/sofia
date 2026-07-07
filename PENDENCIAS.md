# Pendências antes de abrir o sistema ao público

Lista viva do que falta para ir de "MVP funcional" para "pronto para vender ao público".
Atualizada após a rodada de correções da Sofia (atendimento) + implementação de alertas.

Legenda: ✅ feito no código · 🔴 bloqueador · 🟡 recomendado · ⏳ só você pode fazer (painel externo)

---

## ✅ Resolvido no código nesta rodada

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

> Os 3 itens de código abaixo têm **plano de implementação detalhado** em
> [`PLANO_IMPLEMENTACAO.md`](PLANO_IMPLEMENTACAO.md), pronto para execução.

- [ ] **Handoff humano** (Item 1 do plano) — a Sofia reconhecer quando não sabe/não pode
  resolver e pausar a si mesma (`request_human_handoff`; o flag `ai_paused` e a UI do
  Inbox já existem).
- [ ] **Testes automatizados** (Item 2 do plano) — suíte pytest para a lógica crítica.
- [ ] **Página "Pacientes" dedicada** (Item 3 do plano) — rota própria com busca/filtros.
- [ ] **Confirmar presença "digitando" com log real** em produção.
- [ ] **Termos de uso / contrato de adesão** para as clínicas clientes.
- [ ] **Teste de carga** com múltiplos tenants simultâneos.

---

## Rotina de verificação após qualquer mudança de código
```bash
# Backend
venv\Scripts\python -c "import app.main; print('OK')"

# Frontend
cd frontend
npx tsc --noEmit
npm run build
```
