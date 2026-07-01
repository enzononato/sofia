# PROJECT STATE — Clinic SaaS Multi-tenant
> Handover técnico gerado em 2026-04-28. Última atualização: 2026-06-23 (§17 humanização de mensagens WhatsApp). **Alembic head `b2c3d4e5f6a7` — APLICADA ✅** (CRM, invitations, reminders/gcal). §17 sem migration.

---

## 1. Visão do Produto

SaaS Multi-tenant de Gestão de Clínicas com IA. Cada clínica (tenant) recebe:
- Canal de atendimento via **WhatsApp** (UAZAPI)
- **Secretária virtual autônoma "Sofia"** (Gemini) que agenda, consulta disponibilidade e responde pacientes sem intervenção humana
- **Dashboard de gestão** completo: Inbox, Calendário, Configurações

Modelo de negócio: uma base de código única, múltiplas clínicas isoladas por `tenant_id`.

---

## 2. Stack Técnica

### Backend
| Camada | Tecnologia |
|---|---|
| API | Python 3.13, FastAPI 0.115, Uvicorn |
| ORM / DB | SQLAlchemy 2.0 (async), asyncpg, PostgreSQL 16 |
| Migrations | Alembic 1.14 |
| Validação | Pydantic v2, pydantic-settings |
| Auth | JWT (python-jose), bcrypt 3.2.2 + passlib 1.7.4 |
| IA | Google Gemini (`google-genai 1.10`), Function Calling |
| WhatsApp | UAZAPI (provider-managed) |
| HTTP client | httpx 0.28 |
| Infra local | Docker Compose (postgres:16-alpine + pgAdmin) |

### Frontend
| Camada | Tecnologia |
|---|---|
| Framework | Next.js 14+ (App Router) |
| Styling | Tailwind CSS v3 |
| Components | shadcn/ui (Base UI primitives) |
| State (Auth) | Zustand (persisted via localStorage) |
| State (Async) | TanStack React Query v5 |
| HTTP client | Axios (interceptors para JWT + X-Tenant-ID + refresh token) |
| Forms | react-hook-form + zod |
| Icons | lucide-react |

**Dependências críticas de versão:**
- `bcrypt==3.2.2` — fixado porque passlib 1.7.4 é incompatível com bcrypt ≥ 4.0
- `httpx==0.28.1` — google-genai 1.10 exige `>=0.28.1`
- shadcn/ui gera classes Tailwind **v4** (`data-active:`, `data-horizontal:`) — devem ser convertidas manualmente para v3 (`data-[active]:`, `flex-col`) sempre que um novo componente é adicionado via `npx shadcn@latest add`.

---

## 3. Arquitetura Multi-tenant

### 3.1 Isolamento no Banco — `TenantScopedMixin`

```
app/models/base.py
```

Toda tabela de negócio (User, Contact, Service, Appointment, Message) herda de `TenantScopedMixin`, que impõe:
- `tenant_id: UUID NOT NULL INDEX FK → tenants(id) ON DELETE CASCADE`

Nenhuma query de negócio deve ser executada sem `WHERE tenant_id = ?`. O campo está no nível do modelo, não da aplicação, então um ORM mal-configurado ainda teria o campo disponível para filtrar.

### 3.2 Resolução de Tenant — `TenantMiddleware`

```
app/middleware/tenant.py → class TenantMiddleware
```

Executa em **toda requisição não-pública**. Três estratégias (configurável via `.env`):

| Estratégia | Fonte | Lookup |
|---|---|---|
| `header` (padrão) | `X-Tenant-ID` header | UUID ou slug |
| `subdomain` | `Host` header (ex: `clinica.saas.com`) | slug |
| `jwt` | Claim `tenant_id` no Bearer token | UUID |

Resultado armazenado em `request.state.tenant_id` e `request.state.tenant`.

**Paths públicos** (bypassam o middleware):
```python
_PUBLIC_PATHS = {"/", "/docs", "/redoc", "/openapi.json", "/health", "/favicon.ico", "/api/v1/auth/signup"}
_PUBLIC_PREFIXES = ("/api/v1/webhooks/",)  # webhook resolve tenant internamente pelo slug da URL
```

Respostas de erro:
- `401` — tenant não identificado ou não encontrado
- `403` — tenant encontrado mas `is_active = False`

### 3.3 Isolamento nas Dependências FastAPI

```
app/api/deps.py
```

```python
CurrentTenantId = Annotated[uuid.UUID, Depends(get_current_tenant_id)]
CurrentUser     = Annotated[User,      Depends(get_current_user)]
DBSession       = Annotated[AsyncSession, Depends(get_db)]
```

`get_current_user` valida que:
1. JWT é válido e não expirado
2. `token.tenant_id == request.state.tenant_id` — token de uma clínica não funciona em outra
3. Usuário existe e `is_active = True` no banco

### 3.4 JWT + Refresh Token

```
app/core/security.py → create_access_token / decode_access_token
app/services/tokens.py → create_refresh_token / rotate_refresh_token
```

Payload do Access Token JWT:
```json
{ "sub": "<user_id>", "tenant_id": "<tenant_id>", "role": "owner", "email": "...", "exp": ... }
```

| Token | Duração | Armazenamento |
|---|---|---|
| Access Token | 30 minutos | Frontend (Zustand/localStorage) |
| Refresh Token | 14 dias | Frontend (Zustand/localStorage) + DB (`refresh_tokens` table) |

O frontend Axios intercepta `401` automaticamente, tenta `POST /auth/refresh` com o refresh token, e se bem-sucedido, reenvia a requisição original. Se o refresh falhar, faz logout e redireciona para `/login`.

---

## 4. Modelos de Banco

### Tabelas

| Tabela | Herda | Propósito |
|---|---|---|
| `tenants` | `TimestampMixin` | Clínica: nome, slug (único), plano, `ai_config` JSONB, `settings` JSONB |
| `users` | `TenantScopedMixin` | Funcionários/donos. Roles: owner/admin/receptionist/professional/viewer |
| `contacts` | `TenantScopedMixin` | Pacientes/leads. `status`: lead/active/inactive/blocked. Novos campos: `whatsapp_name`, `profile_picture_url`, `ai_paused` (bool). |
| `services` | `TenantScopedMixin` | Procedimentos: nome, `duration_minutes`, `price` |
| `appointments` | `TenantScopedMixin` | Agendamentos. FK → contacts, services (nullable), users (professional, nullable) |
| `messages` | `TenantScopedMixin` | Histórico WhatsApp. `direction`: inbound/outbound. Multimodal: `media_type` (audio/image/video/document), `media_mime_type`, `media_size_bytes`, `media_url` (data URI; vai migrar pra object storage no futuro). `content` carrega o texto OU a legenda da mídia. |
| `refresh_tokens` | `TenantScopedMixin` | Tokens de refresh opacos, rotação enforced server-side |

### Campos JSONB importantes em `tenants`

**`ai_config`** — configuração da IA por clínica:
```json
{
  "model": "gemini-2.5-flash",
  "system_prompt": "Você é Sofia, secretária da Clínica X...",
  "temperature": 0.7,
  "max_output_tokens": 1024,
  "multimodal_enabled": false,
  "scheduling_mode": "capacity",
  "prompt_first_contact": "<override opcional>",
  "prompt_imminent_appointment": "<override opcional>",
  "prompt_post_appointment": "<override opcional>",
  "prompt_active_patient": "<override opcional>",
  "prompt_returning_lead": "<override opcional>",
  "prompt_reactivation": "<override opcional>"
}
```

> **Segredos NUNCA são serializados ao cliente** (§13): `GET/PATCH /tenants/me` removem `ai_config.gemini_api_key` e `settings.whatsapp.{webhook_secret,api_key,api_url}` da resposta (validators em `TenantRead`). A chave por tenant (`gemini_api_key`) foi **descontinuada** — a IA usa sempre a `GEMINI_API_KEY` global do servidor; o `PATCH` descarta a chave se enviada.
>
> `multimodal_enabled` (default `false`) liga o processamento de áudio (até 1m30s), imagem, vídeo e documento via Gemini multimodal. Se desligado, Sofia responde com mensagem polida pedindo texto. Ligue por tenant na aba IA ou rode `python -m scripts.enable_multimodal [slug]`.
>
> `scheduling_mode` (default `"capacity"`) escolhe entre agenda por capacidade da clínica ou **por profissional** (`"per_professional"`). Ver §12.
>
> Os 6 `prompt_*` são overlays aplicados no topo do `system_prompt` conforme o estágio detectado da conversa (ver §7.4). Se omitidos, usam defaults em [app/services/ai_stages.py](app/services/ai_stages.py).

**`settings`** — configuração operacional por clínica:
```json
{
  "whatsapp": {
    "instance": "clinic-minha-clinica",
    "status": "connected",
    "webhook_secret": "<auto-gerado-pelo-backend>"
  },
  "schedule": {
    "timezone": "America/Sao_Paulo",
    "working_days": [1, 2, 3, 4, 5],
    "open_time": "08:00",
    "close_time": "18:00",
    "lunch_start": "12:00",
    "lunch_end": "13:00",
    "slot_granularity_minutes": 30,
    "capacity": 1
  },
  "clinic": {
    "address": "Rua X, 123 - Bairro - Cidade/UF",
    "phone": "(11) 99999-9999",
    "email": "contato@clinica.com",
    "instagram": "@clinica",
    "payment_methods": ["pix", "cartão", "dinheiro"],
    "additional_info": "Estacionamento conveniado..."
  }
}
```

> `settings.schedule.capacity` (default `1`) = nº de atendimentos simultâneos que a clínica suporta (≈ profissionais/salas). Usado por `check_availability` e pela validação anti-dupla-marcação (§12).

> `settings.clinic` é exposto pela tool `get_clinic_info` para que Sofia responda perguntas sobre endereço, telefone, valores e formas de pagamento sem precisar de prompt customizado.

> **IMPORTANTE:** As credenciais da UAZAPI (`UAZAPI_URL`, `UAZAPI_ADMIN_TOKEN`) são variáveis de ambiente do servidor (provider-managed) — **nunca** armazenadas no tenant. O tenant guarda o `instance` (id), o `token` da instância (credencial, sanitizado) e o `status` de conexão.

---

## 5. Fluxo de Conexão WhatsApp (UAZAPI)

### Arquitetura
O **provedor SaaS** hospeda um servidor UAZAPI único. Cada clínica recebe sua própria instância, criada via `admintoken`; o `token` retornado autentica os envios daquela clínica. A UAZAPI identifica a instância pelo header `token` (não por nome no path).

### Fluxo
```
Dono da clínica abre Configurações > WhatsApp
           │
           ▼
POST /tenants/me/whatsapp/connect  (Frontend)
  ├─ Backend gera webhook_secret (se não existe)
  ├─ Se ainda não há token: POST /instance/create (admintoken) → token da instância
  │    └─ Persiste o token IMEDIATAMENTE (recliques reusam, sem criar órfãs)
  ├─ POST /webhook (configura eventos messages/connection/presence; secret no ?token= da URL)
  ├─ POST /instance/connect → QR Code (data:image/png;base64)
  ├─ Salva instance + token + status "connecting" em tenant.settings
  └─ Retorna { instance, status, qr_code } para o frontend
           │
           ▼
Frontend exibe QR Code → Dono escaneia com WhatsApp Business
           │
           ▼
UAZAPI envia webhook: event="connection" → connected
  └─ Backend atualiza tenant.settings.whatsapp.status = "connected"
           │
           ▼
Frontend faz polling em GET /tenants/me/whatsapp/status → detecta "connected" → UI verde
```

### Endpoints WhatsApp
| Método | Rota | Role | Descrição |
|---|---|---|---|
| POST | `/tenants/me/whatsapp/connect` | OWNER / ADMIN | Cria instância + retorna QR Code |
| GET | `/tenants/me/whatsapp/status` | Qualquer | Status atual da conexão |
| DELETE | `/tenants/me/whatsapp/disconnect` | OWNER | Deleta instância, marca como desconectado |

### Envio de Mensagens
`wa_service.send_text_message(instance_name, phone, text)` — usa credenciais globais do env, nunca do tenant.

---

## 6. Endpoints da API

### Auth
| Método | Rota | Auth | Descrição |
|---|---|---|---|
| POST | `/auth/signup` | Nenhuma | Cria Tenant + User(OWNER) atomicamente, retorna JWT + refresh_token |
| POST | `/auth/login` | Middleware (tenant) | Valida email+senha, retorna JWT + refresh_token |
| POST | `/auth/refresh` | Nenhuma (body) | Rotaciona refresh token, retorna novo access_token + refresh_token |

### Tenants
| Método | Rota | Role mínima | Descrição |
|---|---|---|---|
| GET | `/tenants/me` | Qualquer autenticado | Dados da clínica atual |
| PATCH | `/tenants/me` | OWNER / ADMIN | Atualiza nome, `ai_config`, `settings`. `ai_config`/`settings` são **merge** top-level (não substituem o JSONB inteiro) |

### WhatsApp Connection
| Método | Rota | Role mínima | Descrição |
|---|---|---|---|
| POST | `/tenants/me/whatsapp/connect` | OWNER / ADMIN | Provisiona instância + retorna QR code |
| GET | `/tenants/me/whatsapp/status` | Qualquer | Status da conexão WhatsApp |
| DELETE | `/tenants/me/whatsapp/disconnect` | OWNER | Deleta instância |

### Services
| Método | Rota | Role mínima | Descrição |
|---|---|---|---|
| POST | `/services` | OWNER / ADMIN | Cria serviço |
| GET | `/services` | Qualquer | Lista serviços ativos do tenant |
| GET | `/services/{id}` | Qualquer | Detalhe de serviço |
| PATCH | `/services/{id}` | OWNER / ADMIN | Atualiza serviço |

### Appointments
| Método | Rota | Role mínima | Descrição |
|---|---|---|---|
| POST | `/appointments` | OWNER / ADMIN / RECEPTIONIST | Cria agendamento |
| GET | `/appointments` | Qualquer | Lista com filtros |
| GET | `/appointments/{id}` | Qualquer | Detalhe |
| PATCH | `/appointments/{id}` | OWNER / ADMIN / RECEPTIONIST | Atualiza/cancela |

### Contacts
| Método | Rota | Role mínima | Descrição |
|---|---|---|---|
| GET | `/contacts` | Qualquer | Lista contatos com preview da última mensagem |
| GET | `/contacts/{id}` | Qualquer | Detalhe do contato |
| GET | `/contacts/{id}/messages` | Qualquer | Histórico de mensagens |
| POST | `/contacts/{id}/messages` | OWNER / ADMIN / RECEPTIONIST | Envia mensagem manual e **pausa a IA** automaticamente para este contato |
| POST | `/contacts/{id}/messages/media` | OWNER / ADMIN / RECEPTIONIST | Envia áudio (base64), imagem ou documento via WhatsApp |
| PATCH | `/contacts/{id}` | Qualquer | Atualiza dados/status ou toggle de `ai_paused` |

### Users / Staff
| Método | Rota | Role mínima | Descrição |
|---|---|---|---|
| POST | `/users` | OWNER / ADMIN | Cria funcionário |
| GET | `/users` | Qualquer | Lista equipe |
| GET | `/users/{id}` | Qualquer | Detalhe (inclui `service_ids` + `work_hours`) |
| PATCH | `/users/{id}` | OWNER / ADMIN | Atualiza |
| PUT | `/users/{id}/services` | OWNER / ADMIN | Define os serviços que o profissional realiza (Fase 2) |
| PUT | `/users/{id}/work-hours` | OWNER / ADMIN | Define os blocos de horário de trabalho do profissional (Fase 2) |

### Webhooks (público)
| Método | Rota | Descrição |
|---|---|---|
| POST | `/webhooks/whatsapp/{tenant_slug}?token=SECRET` | Recebe eventos da UAZAPI. Processa `messages` (mensagens), `connection` (status) e `presence` (digitando). Secret validado via query param `token` |

---

## 7. O Cérebro da Sofia — Function Calling

### 7.1 Fluxo Geral

```
Webhook recebe mensagem WhatsApp
          │
          ▼ (background task, sessão única)
AsyncSessionLocal() as db:
  ├─ _find_or_create_contact(db, tenant, phone, push_name)
  ├─ Salva Message(INBOUND) → db.flush()
  ├─ _fetch_history(db, tenant_id, contact_id, limit=AI_HISTORY_LIMIT)
  │
  ├─ ai_service.generate_reply(tenant, contact, text, history, db)
  │    └─ Loop até 5 iterações:
  │         Gemini → function_call? → execute_tool(db) → FunctionResponse → Gemini
  │         Gemini → texto puro → retorna (reply_text, model_name)
  │
  ├─ Salva Message(OUTBOUND)
  └─ db.commit()  ← commit único: contact + inbound + appointments (se criados) + outbound
          │
          ▼ (fora da sessão, após commit)
wa_service.send_text_message(instance_name, phone, reply_text)
```

### 7.2 As 9 Ferramentas (`app/services/ai_tools.py`)

> O agendamento tem 2 modos via `ai_config.scheduling_mode` (§12): **`capacity`** (default — N atendimentos em paralelo por clínica) e **`per_professional`** (agenda por profissional). As tools de agenda têm caminho duplo conforme o modo.

| Tool | Parâmetros | O que faz |
|---|---|---|
| `list_services` | nenhum | Serviços ativos do tenant. Em `per_professional`, só os que têm ≥1 profissional vinculado |
| `check_availability` | `date`, `service_id?`, `professional_id?` | `capacity`: slots livres respeitando `schedule` enquanto `sobreposições < capacity`. `per_professional`: slots por profissional (horário próprio/fallback) — retorna quem está livre em cada horário |
| `create_appointment` | `scheduled_at`, `service_id?`, `professional_id?`, `notes?` | Insere `Appointment` (`tenant_id`/`contact_id` do contexto). Valida slot + advisory lock + sempre grava `ends_at`; naive = fuso da clínica. `per_professional`: exige serviço, atribui/pergunta profissional, constraint de overlap no banco |
| `get_upcoming_appointments` | nenhum | Próximos agendamentos do contato atual |
| `cancel_appointment` | `appointment_id`, `reason?` | Cancela agendamento. Valida `tenant_id` e `contact_id` |
| `reschedule_appointment` | `appointment_id`, `new_scheduled_at`, `new_service_id?`, `new_professional_id?` | Atomic reschedule. Revalida o novo slot (excluindo o próprio do overlap); `per_professional` valida o profissional |
| `get_clinic_info` | nenhum | Devolve `tenant.settings.clinic` + horário. Endereço, valores, formas de pagamento |
| `update_contact_info` | `full_name?`, `email?`, `date_of_birth?`, `address?` | Whitelist de campos cadastrais. **Nunca** edita `phone`, `status`, `ai_paused` |
| `list_professionals` | `service_id?` | Profissionais ativos e os serviços que cada um realiza (para a Sofia apresentar/escolher) |

> O nome da clínica (`tenant.name`) é injetado no `system_prompt` em todas as conversas.

### 7.3 Segurança — Prevenção de IDOR / Prompt Injection

> **O backend nunca aceita `tenant_id` ou `contact_id` vindos dos argumentos da IA.**
> São sempre injetados do contexto Python. Mesmo que um prompt malicioso tente enviar IDs falsos, o executor ignora.

`update_contact_info` aplica também whitelist de campos editáveis (`full_name`, `email`, `date_of_birth`, `address`). Email é validado por regex; data de nascimento pelo formato ISO. `phone`, `status` e `ai_paused` jamais podem ser alterados pela IA.

### 7.4 Estágios da Conversa (`app/services/ai_stages.py`)

Sofia detecta o estágio do contato a cada mensagem e aplica um overlay de prompt diferente:

| Estágio | Detecção | Tom/foco |
|---|---|---|
| `first_contact` | `history` vazio | Apresentar Sofia + clínica, acolher |
| `imminent_appointment` | SCHEDULED/CONFIRMED nas próximas 48h | Antecipar confirmação/remarcação |
| `post_appointment` | Última visita finalizada nas últimas 48h | Pergunta como foi, oferece próximo |
| `active_patient` | Tem COMPLETED no passado | Tom íntimo, sem repetir explicações |
| `returning_lead` | Tem mensagens, zero appointments | Proativa, sugerir agendamento |
| `reactivation` | Última msg > 30 dias atrás | "Que bom ter você de volta!" |

Composição do prompt enviado ao Gemini:

```
system_instruction = BASE (ai_config.system_prompt OR default)
                   + STAGE_OVERLAY (ai_config.prompt_<stage> OR default)
                   + CONTEXT_BLOCK (nome, email, próximo agendamento, etc.)
```

`CONTEXT_BLOCK` é gerado dinamicamente por `ai_stages.build_context_block()` — injeta dados do contato direto no prompt para que Sofia não precise perguntar coisas que já sabe.

### 7.5 Multimodal (áudio + imagem + vídeo + documento)

Quando `tenant.ai_config.multimodal_enabled = true`:

```
Webhook → detecta messageType de mídia (image/audio/ptt/video/document)
        → POST /message/download {id: messageid, return_base64: true}  (UAZAPI)
        → salva inbound com media_url=data URI + media_type/mime/size
        → passa bytes para Gemini como Part(inline_data=Blob(...))
        → Sofia interpreta nativamente e responde
```

Restrições:
- Áudio: máximo 1m30s (`_AUDIO_MAX_SECONDS` em [webhooks.py](app/api/v1/routes/webhooks.py))
- Quando `multimodal_enabled = false`: Sofia responde com mensagem polida pedindo texto
- Diagnóstico médico de imagem: BLOQUEADO no `DEFAULT_SYSTEM_PROMPT` ("oriente a buscar consulta presencial")
- Storage v1: data URI no DB (`media_url`); v2 vai migrar para object storage

---

## 8. Frontend — Dashboard

### 8.1 Páginas Implementadas

| Rota | Status | Descrição |
|---|---|---|
| `/login` | ✅ | Login com email + senha |
| `/signup` | ✅ | Registro de clínica + owner |
| `/dashboard` | ✅ | Redirect para inbox |
| `/dashboard/inbox` | ✅ | Inbox WhatsApp-style (lista de contatos + chat window + handoff manual) |
| `/dashboard/calendar` | ✅ | Agenda diária com timeline 07h–19h, now indicator, cards por status |
| `/dashboard/settings` | ✅ | 4 abas: Perfil, WhatsApp (QR code connect), IA (prompt/modelo), Horários |
| `/dashboard/services` | ✅ | CRUD de procedimentos (grid de cards, toggle ativo). Hooks em `useCalendar.ts` |
| `/dashboard/team` | ✅ | CRUD de equipe (tabela + modal, roles, ativo/inativo) + **dialog de atendimento por profissional: serviços que faz + horários de trabalho** (Fase 2 — §12). Hooks em `useTeam.ts` |

### 8.2 Arquitetura Frontend

```
frontend/src/
├── app/
│   ├── layout.tsx           # Root layout (providers: React Query, Theme)
│   ├── login/page.tsx       # Tela de login
│   ├── signup/page.tsx      # Tela de registro
│   └── dashboard/
│       ├── layout.tsx       # DashboardLayout (sidebar + navbar + auth guard)
│       ├── inbox/page.tsx   # Inbox
│       ├── calendar/page.tsx # Calendário
│       └── settings/page.tsx # Configurações
├── components/
│   ├── dashboard/
│   │   ├── sidebar.tsx      # Sidebar com navegação
│   │   └── navbar.tsx       # Top navbar com avatar + logout
│   ├── inbox/
│   │   ├── inbox-layout.tsx # Layout 2 colunas
│   │   ├── contact-list.tsx # Lista de contatos com foto e preview
│   │   └── chat-window.tsx  # Janela de chat estilo WhatsApp Web (scroll fixo, gravação de áudio, anexos, player de áudio)
│   ├── calendar/
│   │   ├── calendar-page.tsx # Layout calendário + sidebar + timeline
│   │   └── (componentes internos)
│   ├── settings/
│   │   ├── settings-layout.tsx # Tabs container
│   │   ├── general-tab.tsx    # Perfil da clínica
│   │   ├── whatsapp-tab.tsx   # Conexão QR Code (novo fluxo)
│   │   ├── ai-tab.tsx         # Config IA (modelo, prompt, temperatura)
│   │   └── schedule-tab.tsx   # Horários de funcionamento
│   └── ui/                   # shadcn/ui components
├── hooks/
│   ├── useInbox.ts           # useContacts(), useMessages(), useSendMessage()
│   ├── useCalendar.ts        # useAppointments(), useServices()
│   └── useSettings.ts        # useTenantProfile(), useUpdateTenant()
├── store/
│   └── useAuthStore.ts       # Zustand: tokens, tenant, user, login(), logout()
├── lib/
│   └── axios.ts              # Axios instance (baseURL, JWT interceptor, refresh token rotation)
│   └── utils.ts              # cn() helper
```

### 8.3 React Query — Estratégia de Cache

| Hook | staleTime | Estratégia |
|---|---|---|
| `useContacts()` | 30s | Refetch on window focus |
| `useMessages(contactId)` | 15s | Refetch on window focus |
| `useAppointments(from, to)` | 60s | `placeholderData: keepPreviousData` (troca de dia sem flicker) |
| `useServices()` | 5 min | Cache longo, serviços raramente mudam |
| `useTenantProfile()` | 5 min | Cache longo, atualizado via `setQueryData` após PATCH |

### 8.4 Axios — baseURL

```
baseURL = "http://localhost:8000/api/v1"
```

> **ATENÇÃO:** Todas as chamadas nos hooks devem usar paths relativos SEM `/api/v1` (ex: `/contacts`, `/tenants/me`). O baseURL já inclui o prefixo. Caminhos absolutos como `/api/v1/contacts` resultarão em `404` por duplicação.

---

## 9. Configuração do Ambiente

### `.env` (variáveis obrigatórias para rodar)

```env
SECRET_KEY=<32+ chars aleatórios>
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/clinic_saas
GEMINI_API_KEY=AIza...

# UAZAPI (provider-managed, global)
UAZAPI_URL=https://sua-instancia.uazapi.com
UAZAPI_ADMIN_TOKEN=seu-admin-token
APP_BASE_URL=http://localhost:8000  # URL pública do backend (usada para construir webhook URLs)

TENANT_RESOLUTION_STRATEGY=header  # header | subdomain | jwt
```

### Subir infra e aplicação

```bash
# Backend
docker compose up -d                  # PostgreSQL 16 + pgAdmin (localhost:5050)
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head                  # cria todas as tabelas
uvicorn app.main:app --reload         # API em localhost:8000

# Frontend
cd frontend
npm install
npm run dev                           # Next.js em localhost:3000
```

---

## 10. Estrutura de Pastas (Backend)

```
AI Agent SaaS/
├── app/
│   ├── main.py              # Factory do FastAPI, registro de middlewares
│   ├── config.py            # Settings (pydantic-settings, lê .env)
│   ├── database.py          # Engine async, AsyncSessionLocal, Base
│   ├── models/
│   │   ├── base.py          # TimestampMixin, TenantScopedMixin
│   │   ├── tenant.py        # Tenant, TenantPlan enum
│   │   ├── user.py          # User, UserRole enum
│   │   ├── contact.py       # Contact, ContactStatus enum
│   │   ├── service.py       # Service
│   │   ├── appointment.py   # Appointment, AppointmentStatus enum
│   │   └── message.py       # Message, MessageDirection, MessageChannel
│   ├── schemas/             # Pydantic v2 (Create/Update/Read por entidade)
│   ├── api/
│   │   ├── deps.py          # DBSession, CurrentTenantId, CurrentUser
│   │   └── v1/
│   │       ├── router.py    # Registro central dos sub-routers
│   │       └── routes/
│   │           ├── auth.py          # signup, login, refresh
│   │           ├── tenants.py       # GET/PATCH /tenants/me
│   │           ├── whatsapp.py      # connect, status, disconnect
│   │           ├── services.py      # CRUD serviços
│   │           ├── appointments.py  # CRUD agendamentos
│   │           ├── contacts.py      # CRUD contatos + mensagens + envio manual
│   │           ├── users.py         # CRUD equipe / staff
│   │           └── webhooks.py      # POST /webhooks/whatsapp/{slug}
│   ├── core/
│   │   ├── security.py      # hash_password, verify_password, create/decode JWT
│   │   └── errors.py        # APIError hierarchy + error envelope
│   ├── middleware/
│   │   └── tenant.py        # TenantMiddleware (3 estratégias)
│   └── services/
│       ├── ai.py            # generate_reply() — loop de function calling + multimodal
│       ├── ai_stages.py     # detect stage, prompt overlays, context block builder
│       ├── ai_tools.py      # 8 tools: list_services, check_availability,
│       │                    #          create_appointment, get_upcoming_appointments,
│       │                    #          cancel_appointment, reschedule_appointment,
│       │                    #          get_clinic_info, update_contact_info
│       ├── tokens.py        # Refresh token lifecycle
│       ├── whatsapp.py      # send_text_message(instance_name, phone, text)
│       └── whatsapp_instance.py  # create_or_fetch_instance, get_qr_code, get_connection_state,
│                                 # delete_instance, download_media_base64, fetch_profile_picture
├── alembic/
├── docker/
├── frontend/                # Next.js 14 App (ver seção 8)
├── docker-compose.yml
├── alembic.ini
├── requirements.txt
└── .env
```

---

## 11. Próximos Passos (Backlog Priorizado)

### ✅ Concluído
- **Backend completo** — Auth, Tenants, Services, Appointments, Contacts, Users, Webhooks
- **Refresh Token** — rotação server-side, interceptor Axios no frontend
- **Rate Limiting** — por tenant, endpoints auth protegidos (10/min login, 5/hour signup, 30/min refresh)
- **Global Error Handling** — `APIError` hierarchy + error envelope padronizado
- **Frontend: Inbox** — lista de contatos, chat window, envio manual (handoff). Polling agressivo aplicado (10s contatos / 5s mensagens). Caminho para SSE documentado abaixo.
- **Frontend: Calendário** — agenda diária, timeline 07h–19h, now indicator, cards por status
- **Frontend: Configurações** — 4 abas (perfil, WhatsApp QR, IA, horários)
- **WhatsApp Connection Flow** — provisionamento automático de instância, QR code, polling de status

### 🔲 Pendente

| Prioridade | Feature | Notas |
|---|---|---|
| 1 | **Settings UI — Sofia 2.0** (Fase 2 do upgrade da Sofia) | Aba de configuração da IA precisa ganhar: (a) toggle `multimodal_enabled`; (b) 6 textareas para overlays de estágio (`prompt_first_contact`, `prompt_imminent_appointment`, `prompt_post_appointment`, `prompt_active_patient`, `prompt_returning_lead`, `prompt_reactivation`); (c) nova aba "Clínica" para `settings.clinic` (address, phone, email, instagram, payment_methods, additional_info). Backend já aceita via `PATCH /tenants/me`. Defaults dos overlays vivem em [app/services/ai_stages.py](app/services/ai_stages.py). |
| 2 | **Frontend: Serviços** | CRUD de procedimentos (nome, duração, preço) — necessário para a Sofia saber o que oferecer |
| 3 | **Frontend: Equipe** | CRUD de funcionários (roles, permissões) |
| 4 | ~~**Criptografia de `ai_config`**~~ | ✅ Resolvido por remoção (§13.1): BYOK descontinuado, IA usa a chave global do servidor; segredos nunca vão ao frontend |
| 5 | **Object storage para mídia** | Hoje `messages.media_url` armazena data URI inline (rápido pra MVP). Quando passar de ~10K mensagens com mídia, migrar para S3/Supabase Storage e guardar só URL. |
| 6 | **Tempo real no Inbox** | Migrar de polling para SSE quando passar de ~50 usuários simultâneos. Roteiro detalhado abaixo. |
| 7 | **Deploy produção** | Docker multi-stage, HTTPS, configuração de domínio |

### Caminho de evolução do Inbox para tempo real

Hoje o inbox usa polling (React Query, 10s para contatos / 5s para mensagens).
Decisão consciente: simples, robusto, sem estado em conexões longas, suficiente
para MVP. Migrar para tempo real quando passar de ~50 usuários simultâneos.

**Estágio 1 (atual)**: polling agressivo via `refetchInterval` no React Query.
- `useContacts`: `staleTime: 5s`, `refetchInterval: 10s`
- `useMessages`: `staleTime: 3s`, `refetchInterval: 5s`
- `refetchIntervalInBackground: false` — pausa quando a aba não está focada

**Estágio 2**: SSE (Server-Sent Events).
- Endpoint `GET /api/v1/events/stream` — conexão por tenant
- `_process_inbound_message` publica num pub/sub interno após salvar mensagem
- Frontend usa `EventSource` e invalida cache do React Query no recebimento
- Single-worker: `asyncio.Queue` por tenant. Multi-worker: Redis Pub/Sub.

**Estágio 3**: WebSocket — só se precisar de cliente → servidor em tempo real
(ex: typing indicators, marcação de leitura). Caso contrário SSE é mais simples.

Por que não pular direto para SSE/WebSocket: introduz estado em conexões longas,
complica deploy multi-worker (precisa Redis), e o ganho de UX vs polling de 5s nao justifica a complexidade enquanto o volume for baixo.

---

## 12. Agenda multi-profissional & anti-dupla-marcacao

> Decisao de produto (sessao 2026-06-17): a clinica atende **varios profissionais em paralelo**. A agenda evolui de "global por tenant" para "por profissional". Implementacao faseada.

### Fase 1 - Concluida (trava de dupla marcacao)
Arquivo: [app/services/ai_tools.py](app/services/ai_tools.py)

- **`settings.schedule.capacity`** (novo, default `1`): numero de atendimentos simultaneos que a clinica suporta (aprox. profissionais/salas). Ponte ate a atribuicao real de profissional (Fase 3). Com `capacity=1` o comportamento e identico ao anterior.
- **`check_availability`** agora conta sobreposicoes e libera o slot enquanto `n. de agendamentos sobrepostos < capacity`.
- **`create_appointment` / `reschedule_appointment`** passaram a:
  1. Adquirir **advisory lock por tenant** (`pg_advisory_xact_lock`) - serializa reservas concorrentes e fecha a race entre checar->gravar.
  2. **Revalidar** o horario antes de gravar: dia util, dentro do expediente, fora do almoco e `overlaps < capacity`. Em caso de falha devolvem `{"error": ...}` e a Sofia explica ao paciente.
  3. **Sempre preencher `ends_at`** (antes nascia `NULL`).
- **Fuso horario**: horario ISO *naive* vindo da IA agora e interpretado como **fuso da clinica** (antes assumia UTC - bug para clinicas fora de UTC).

Helpers compartilhados em `ai_tools.py`: `_resolve_schedule`, `_booked_windows`, `_validate_booking`, `_lock_tenant`, `_clinic_tz`. Sem migration: `ends_at`/`professional_id` ja existiam no schema; `capacity` vive no JSONB `settings`.

> ~~**Limitacao conhecida (Fase 1):** o endpoint manual `POST /appointments` ainda nao passa por essa validacao.~~ **Resolvido** (rodada de correcoes 2026-06-17): o create/update manual agora preenche `ends_at` e a constraint `no_overlap_per_professional` recusa overlap (→ `409 appointment_overlap`).

### Decisões de produto (2026-06-17) que guiam as Fases 2 e 3
1. **Escolha do profissional:** Sofia pergunta **só se houver vários** disponíveis; se só um faz o serviço, atribui direto.
2. **Horário de trabalho:** **próprio por profissional** (cada um tem seus dias/blocos); a clínica é fallback quando o profissional não definir.
3. **Serviço sem profissional vinculado:** **não é oferecido** pela Sofia até ter ao menos um profissional ativo vinculado.
4. **Profissional = `User` com `role=professional`** (reaproveita a entidade e a página de Equipe). Owners/admins que atendem também podem ser vinculados.

### Fase 2 — Modelo de dados + configuração no sistema ✅ Concluída (2026-06-17)
> Objetivo: a clínica cadastrar **quem faz o quê e quando**, tudo pela UI. Sem isso a Fase 3 não tem dados.

**Banco** (migration `c1d2e3f4a5b6`):
- `professional_services` (M:N): `professional_id` → users, `service_id` → services; PK (`professional_id`,`service_id`); índice por `service_id`; ON DELETE CASCADE. **`tenant_id` omitido de propósito** (ambos os lados já são tenant-scoped; a API valida que profissional + serviço são do mesmo tenant antes de vincular).
- `professional_work_hours`: `id`, `tenant_id`, `professional_id`, `weekday` (ISO 1–7), `start_time`, `end_time` + timestamps. **Múltiplos blocos/dia** (turnos divididos → o intervalo entre blocos é o almoço). CHECK: `weekday∈[1,7]`, `end_time>start_time`. Sem linhas = herda `settings.schedule` da clínica.
- Models: [app/models/professional.py](app/models/professional.py); relações `User.offered_services`/`User.work_hours` e `Service.professionals`.
- (Exceções/folgas/feriados ficam para o backlog "bloqueio de agenda".)

**API** (tenant-scoped, OWNER/ADMIN) — [app/api/v1/routes/users.py](app/api/v1/routes/users.py):
- `GET /users/{id}` agora retorna `UserDetailRead` (inclui `service_ids` + `work_hours`).
- `PUT /users/{id}/services` body `{service_ids: [...]}` — substitui o conjunto; valida que todos os serviços são do tenant.
- `PUT /users/{id}/work-hours` body `{blocks: [{weekday,start_time,end_time}]}` — substitui os blocos; valida ordem e sobreposição (Pydantic).

**Frontend** — [team/page.tsx](frontend/src/app/dashboard/team/page.tsx) + [professional-config-dialog.tsx](frontend/src/components/team/professional-config-dialog.tsx):
- Ação "Serviços e horários" (ícone relógio) nas linhas de `professional`/`owner` abre dialog com multiseleção de serviços + editor de blocos por dia. Hooks novos em [useTeam.ts](frontend/src/hooks/useTeam.ts): `useUserDetail`, `useSetUserServices`, `useSetUserWorkHours`.

### Fase 3 — Sofia usa a equipe ✅ Concluída (2026-06-17)
**Flag de rollout:** `ai_config.scheduling_mode` = `"capacity"` (default, Fase 1) | `"per_professional"` (Fase 3). Ligar por tenant **depois** que a clínica vinculou serviços e definiu horários — senão a Sofia para de oferecer serviços sem profissional. Threaded via `execute_tool(..., ai_config=...)` em [ai.py](app/services/ai.py).

**Tools** ([ai_tools.py](app/services/ai_tools.py)) — em modo `per_professional`:
- `list_services` retorna **apenas** serviços com ≥1 profissional ativo vinculado (decisão 3).
- `check_availability(date, service_id, professional_id?)`: resolve os profissionais do serviço; por profissional calcula os blocos do dia (horário próprio, ou fallback da clínica só se ele não tiver **nenhum** horário definido) menos seus agendamentos; retorna `slots: [{time, professionals:[{id,name}]}]` + `available_slots`.
- `create_appointment(scheduled_at, service_id, professional_id?, notes?)`: exige serviço; valida que o profissional o realiza; sem `professional_id` e com **um** livre → atribui; com **vários** → `{needs_selection, professionals}` para a Sofia perguntar (decisão 1); grava `professional_id` + `ends_at`. Insert em `begin_nested`; `IntegrityError` da constraint → "horário acabou de ser preenchido".
- `reschedule_appointment(..., new_professional_id?)`: mesma validação por profissional (exclui o próprio do overlap).
- Nova tool `list_professionals(service_id?)` — profissionais ativos + serviços que cada um faz.
- **Nome da clínica** (`tenant.name`) injetado no `system_prompt` ([ai.py](app/services/ai.py)).

**Banco** (migration `d2e3f4a5b6c7`): `btree_gist` + constraint anti-overlap **por profissional**:
```sql
EXCLUDE USING gist (professional_id WITH =, tstzrange(scheduled_at, ends_at) WITH &&)
  WHERE (status <> 'cancelled' AND professional_id IS NOT NULL AND ends_at IS NOT NULL)
```
À prova de race no nível do banco; agendamentos `capacity` (sem `professional_id`) não são afetados.

**Helpers novos** em ai_tools: `_resolve_service`, `_professionals_for_service`, `_professional_offers`, `_clinic_fallback_blocks`, `_professional_work_blocks`, `_slots_in_blocks`, `_professional_slot_ok`, `_granularity`.

**Dependência:** adicionado `tzdata` ao [requirements.txt](requirements.txt) — `zoneinfo` falha sem ele no Windows / containers mínimos (afetava `check_availability` desde a Fase 1).

> Em `per_professional`, o `capacity` da Fase 1 deixa de ser usado para reservas (legado; remover quando todos os tenants migrarem).
>
> **Validado** com smoke test E2E (tenant temporário, rollback): availability por profissional, atribuição automática, recusa de horário ocupado/fora de expediente, filtro de `list_services`, e rejeição de overlap pela constraint do banco.

### Fase 4 — Frontend de agenda (pendente, fora deste plano)
- Calendário com coluna/filtro por profissional.

### Robustez transversal (backlog)
- ~~Idempotencia do webhook por `whatsapp_message_id`~~ ✅ feito (dedup no inicio da Phase 1 do webhook).
- Debounce de mensagens rapidas do mesmo contato.
- `webhook_secret` obrigatorio (hoje so valida se existir).
- Lembrete/confirmacao automatica de agendamento (reduz no-show).

### Rodada de correções (2026-06-17) — migration `e3f4a5b6c7d8`
Revisão de bugs do app:
1. **`PATCH /tenants/me` agora faz MERGE** de `ai_config`/`settings` (top-level) em vez de substituir — salvar uma aba não apaga mais chaves de outra (ex.: `scheduling_mode`). A aba de IA passou a enviar strings vazias (não `undefined`) para permitir limpar campos.
2. **Casing de status no frontend** (`calendar-layout`, `daily-timeline`, `useCalendar`): a API devolve minúsculas (`scheduled`…); o front comparava em MAIÚSCULAS → contadores e cores do calendário estavam quebrados. Alinhado para minúsculas.
3. **`POST /appointments`**: preenche `ends_at` e trata overlap por profissional (`409 appointment_overlap`).
4. **Idempotência do webhook** por `whatsapp_message_id`.
5. **`PATCH /appointments`**: recalcula `ends_at` ao mudar horário/serviço; mesmo tratamento de overlap.
6. **`users.last_login_at`**: coluna nova, gravada no login, exposta em `UserRead` (a UI da Equipe já lia o campo).
- Dependência: `tzdata` adicionado ao `requirements.txt` (Fase 3).

---

## 13. Rodada de hardening + Sofia time-aware (2026-06-18)

> **Atualizado 2026-06-23:** §17 — Humanização de mensagens (batching + replies particionadas + simulação humana).

> Foco: segurança (nenhum segredo no frontend), correção de fuso para a Sofia agendar certo, e polimento de inbox/equipe. **Sem migration** (Alembic head segue `e3f4a5b6c7d8`).

### 13.1 Segurança — segredos fora do frontend
- **`TenantRead` sanitiza a resposta** ([app/schemas/tenant.py](app/schemas/tenant.py)): `field_validator`s removem `ai_config.gemini_api_key` e `settings.whatsapp.{webhook_secret,api_key,api_url,apikey}` de **toda** resposta que usa o schema (GET e PATCH `/tenants/me`). Campos públicos (`instance`, `status`, `schedule`, `clinic`) preservados.
- **BYOK removido**: `app/services/ai.py` usa **sempre** `settings.GEMINI_API_KEY` (global do servidor) — nunca mais instancia client com chave por tenant. `PATCH /tenants/me` faz `pop("gemini_api_key")` no merge (defesa em profundidade) e o campo sumiu da aba IA do frontend.
- **Merge profundo** em `PATCH /tenants/me` (`_deep_merge`): updates parciais de `settings.whatsapp`/`schedule`/`clinic` não apagam mais chaves irmãs (ex.: `webhook_secret`).
- **`SECRET_KEY` validado no boot** ([app/config.py](app/config.py)): `model_validator` falha se for o placeholder ou `<32` chars quando `DEBUG=false`; só avisa em dev.
- **Headers de segurança** ([app/middleware/security_headers.py](app/middleware/security_headers.py)): `X-Content-Type-Options`, `X-Frame-Options=DENY`, `Referrer-Policy`, `Permissions-Policy`, `COOP`; HSTS só sob HTTPS. Registrado em [app/main.py](app/main.py).
- **Decisão (2026-06-18):** tokens permanecem em localStorage por ora (migração para cookies httpOnly fica no backlog — risco/esforço alto).

### 13.2 Sofia agora sabe que horas são (fuso do Brasil)
- **Bug raiz:** a data/hora atual nunca era injetada no prompt → a IA "chutava" datas relativas (amanhã/segunda) e mostrava horários em UTC.
- `ai_stages.build_context_block(..., tenant_settings)` agora abre com **`Data e hora agora: <dia-da-semana> DD/MM/YYYY HH:MM (fuso ...)`** + instrução de sempre interpretar/responder datas nesse fuso. Horários de agendamentos no contexto são localizados.
- Helper único `_fmt_local(dt, tz)` + `_WEEKDAYS_PT` em [app/services/ai_tools.py](app/services/ai_tools.py) (reusado por `ai_stages`); nomes de dia em pt-BR manualmente (strftime de locale é instável no Windows).
- **`get_upcoming_appointments`** agora recebe `tenant_settings`, localiza `scheduled_at` (+ `scheduled_at_iso`) e inclui `service_name` e `professional_name` (lookups em lote, sem N+1).
- `create_appointment`/`reschedule` (capacity e per_professional) retornam `scheduled_at_local` (pt-BR) para confirmações naturais.

### 13.3 `get_clinic_info` enriquecido
- Recebe `tenant_name` (threaded via `execute_tool(..., tenant_name=tenant.name)`) e retorna `name` + `working_days_names` (dias por extenso em pt-BR).

### 13.4 Multimodal
- `multimodal_enabled` **ligado** para as clínicas existentes via [scripts/enable_multimodal.py](scripts/enable_multimodal.py) (idempotente). Novas clínicas continuam com default `false`.

### 13.5 Inbox estilo WhatsApp Web
- **Prévia de mídia** na lista de contatos ([contact-list.tsx](frontend/src/components/inbox/contact-list.tsx)): `🎤 Áudio`, `📷 Foto`, `🎬 Vídeo`, `📄 Documento` em vez de texto vazio.
- **Separadores de data** no chat ([chat-window.tsx](frontend/src/components/inbox/chat-window.tsx)): divisórias `Hoje`/`Ontem`/data quando o dia muda.

### 13.6 Criação de equipe
- **Senha opcional** em `UserCreate` ([app/schemas/user.py](app/schemas/user.py)); `create_user` gera senha forte (`secrets.token_urlsafe`) quando ausente → profissional pode ser cadastrado como recurso agendável sem credencial.
- **Frontend** ([team/page.tsx](frontend/src/app/dashboard/team/page.tsx)): role `professional` esconde o campo de senha e mostra nota; ao criar um profissional, abre **automaticamente** o dialog de serviços/horários (fluxo único). Validação de senha alinhada ao backend (mín. 8).

### 13.7 Frontend correções herdadas (mesma sessão)
- `Input` reescrito como `<input>` nativo com `forwardRef` (RHF voltou a ler valores → fim do "Invalid input").
- `Switch` corrigido para os data-attributes do Base UI v1.4.1 (`data-[checked]`/`data-[unchecked]`).
- `schedule-tab` aceita `HH:MM:SS` do browser (normaliza para `HH:MM`).
- Toggle "Ignorar mensagens de grupos" (default ligado) em WhatsApp → backend filtra JIDs `@g.us`.

### Backlog atualizado
- ~~Criptografia de `ai_config.gemini_api_key`~~ → **resolvido por remoção** (BYOK descontinuado; chave global do servidor).
- Pendente: migrar sessão para cookies httpOnly; object storage para mídia; SSE no inbox; limpeza de tenant duplicado de teste (`59nqq...`).

---

## 14. Expansão do produto — CRM, Agenda CRUD, Relatórios (Fase A, 2026-06-18)

> Plano aprovado de 6 capacidades (CRM Kanban, Agenda completa, Relatórios, Convites por e-mail + papéis, Google Calendar, Follow-up automático), entregue em fases. **Fase A concluída** (CRM, Agenda CRUD, Relatórios). Fases B e C em andamento.
>
> **Migration nova `f4a5b6c7d8e9`** (head passa a ser esta). ⚠️ Requer `alembic upgrade head` — não aplicada ainda nesta máquina porque o Postgres/Docker estava parado durante o desenvolvimento.
>
> **Libs novas no frontend:** `@dnd-kit/core` + `@dnd-kit/sortable` + `@dnd-kit/utilities` (Kanban), `recharts` (gráficos).

### 14.1 CRM Kanban (IA classifica + drag manual)
- **Modelo** ([app/models/contact.py](app/models/contact.py)): enum `CrmStage` (`new_lead`, `in_conversation`, `scheduled`, `attended`, `post_care`, `lost`) + colunas `crm_stage` (default `new_lead`, indexado), `crm_stage_source` (`ai`|`manual`), `crm_stage_updated_at`, e denormalizações `last_inbound_at`/`last_followup_at` (para Fase C).
- **Classificação determinística** ([app/services/crm.py](app/services/crm.py)): `mark_inbound` (inbound vivo → `last_inbound_at` + lead novo vira `in_conversation`), `mark_scheduled` (agendamento criado → `scheduled`, fato, avança mesmo card manual), `mark_attended` (status `completed` → `attended`). Ordem linear evita regressão automática; **movimento manual** (`source=manual`) é respeitado pela IA.
- **Tool da IA** `set_crm_stage(stage, reason)` ([app/services/ai_tools.py](app/services/ai_tools.py)): Sofia move o card (`in_conversation`/`post_care`/`lost`; `scheduled`/`attended` são só por fato). Estágio atual exposto no `CONTEXT_BLOCK` ([ai_stages.py](app/services/ai_stages.py)).
- **Hooks de evento**: `crm.mark_inbound` no [webhooks.py](app/api/v1/routes/webhooks.py); `crm.mark_scheduled` nas tools `create_appointment`/`create_appointment_pp` e no `POST /appointments`; `crm.mark_attended` no `PATCH /appointments` (status completed).
- **API**: `crm_stage` exposto em `ContactRead` e aceito em `PATCH /contacts/{id}` (drag manual → marca `source=manual` + `updated_at`).
- **Frontend**: página [crm/page.tsx](frontend/src/app/dashboard/crm/page.tsx) + [kanban-board.tsx](frontend/src/components/crm/kanban-board.tsx) (dnd-kit, optimistic update via [useCrm.ts](frontend/src/hooks/useCrm.ts)). Item "CRM" no sidebar.

### 14.2 Agenda completa (CRUD no frontend)
- Backend de appointments já existia (CRUD + status + overlap). Adicionados hooks [useCalendar.ts](frontend/src/hooks/useCalendar.ts): `useCreateAppointment`, `useUpdateAppointment` (invalidam `appointments` + `contacts`).
- Modal [appointment-modal.tsx](frontend/src/components/calendar/appointment-modal.tsx): criar/editar (paciente, serviço, profissional, data/hora via `datetime-local` → ISO, observações) + **ações rápidas de status** (Confirmar/Compareceu/Não compareceu/Cancelar — cancelar pede motivo). Trata `409 appointment_overlap`.
- [calendar-layout.tsx](frontend/src/components/calendar/calendar-layout.tsx): botão "Novo agendamento"; clique no card da [daily-timeline.tsx](frontend/src/components/calendar/daily-timeline.tsx) abre o modal em edição (`onSelect`).
- **Fuso:** o modal envia `new Date(local).toISOString()` (UTC-aware) — consistente com a exibição local do calendário.

### 14.3 Relatórios
- **Backend** [reports.py](app/api/v1/routes/reports.py) (`GET /reports/overview?days=30`, **somente owner/admin**): KPIs (conversão, novos leads, agendamentos futuros, no-show) + séries (tendência de leads, distribuição por estágio CRM, agendamentos por status, volume de mensagens, top serviços). Agregações SQL escopadas por tenant; dias preenchidos para séries contínuas. Schemas em [report.py](app/schemas/report.py); router registrado em [router.py](app/api/v1/router.py).
- **Frontend** [reports/page.tsx](frontend/src/app/dashboard/reports/page.tsx) com `recharts` (Line/Bar/Pie) + seletor 7/30/90 dias + [useReports.ts](frontend/src/hooks/useReports.ts). Item "Relatórios" no sidebar.

### 14.4 Verificação
- ✅ Estática: `python -c "import app.main"` OK (sem ciclo: `crm` só importa models; `ai_tools`/`webhooks`/`appointments` importam `crm`); `npx tsc --noEmit` limpo.
- ⏳ **Pendente (Docker/Postgres parado):** `alembic upgrade head` (migration `f4a5b6c7d8e9`) + E2E (criar/editar/cancelar agendamento; mover card no Kanban; abrir relatórios). Rodar quando o banco subir.

---

## 15. Papéis (admin/profissional) + Convite por e-mail (Fase B, 2026-06-18)

> **Migration nova `a1b2c3d4e5f6`** (tabela `invitations`). Convite por e-mail via **Resend** com fallback de link copiável.

### 15.1 Convite por e-mail
- **Modelo** [invitation.py](app/models/invitation.py) + migration `a1b2c3d4e5f6`: `invitations` (email, role, `token_hash` SHA-256, `expires_at`, `accepted_at`, `invited_by_user_id`). Registrado em [models/__init__.py](app/models/__init__.py).
- **E-mail** [email.py](app/services/email.py): `send_email` via Resend (httpx). **Sem `RESEND_API_KEY` → retorna False** e o fluxo cai no link copiável (sem quebrar). Config nova: `RESEND_API_KEY`, `MAIL_FROM`, `FRONTEND_BASE_URL`, `INVITE_EXPIRE_HOURS` ([config.py](app/config.py)).
- **Rotas** [users.py](app/api/v1/routes/users.py) (admin): `POST /users/invite` (cria token + dispara e-mail; retorna `{invitation, invite_link, email_sent}`), `GET /users/invitations` (pendentes), `DELETE /users/invitations/{id}`. **Declaradas antes de `/{user_id}`** para não colidir com a rota paramétrica. `POST /auth/accept-invite` (público — adicionado a `_PUBLIC_PATHS` em [tenant.py](app/middleware/tenant.py)): valida token, cria `User` no tenant do convite e já loga (token pair). Schemas em [invitation.py](app/schemas/invitation.py).
- **Frontend**: hooks `useInvitations`/`useInviteUser`/`useRevokeInvitation` ([useTeam.ts](frontend/src/hooks/useTeam.ts)); botão "Convidar por e-mail" + dialog (mostra "enviado" ou link copiável) + lista de convites pendentes na [team/page.tsx](frontend/src/app/dashboard/team/page.tsx); página pública [accept-invite/page.tsx](frontend/src/app/accept-invite/page.tsx).

### 15.2 Acesso por papel (admin_clinica / profissional)
- **admin da clínica** = `owner`+`admin` (acesso total). **profissional** = `professional` (restrito).
- Backend scoping: `professional` vê **só os próprios** agendamentos ([appointments.py](app/api/v1/routes/appointments.py) list+detail filtram por `professional_id == current_user.id`) e **só os contatos com quem atende** ([contacts.py](app/api/v1/routes/contacts.py) list filtra por subquery de appointments). Relatórios já eram owner/admin.
- Frontend: [sidebar.tsx](frontend/src/components/dashboard/sidebar.tsx) esconde Relatórios/Serviços/Equipe/Configurações para profissional (lê `userRole` do JWT no `useAuthStore`). Inbox/CRM/Calendário visíveis (com dados escopados no backend).
- ⚠️ **Pendente/backlog:** escopar também `GET /contacts/{id}` e `/messages` por profissional (hoje exigem conhecer o UUID; baixo risco intra-clínica).

### 15.3 Verificação
- ✅ `python -c "import app.main"` OK; `npx tsc --noEmit` limpo.
- ⏳ **Pendente (Docker parado):** `alembic upgrade head` (`a1b2c3d4e5f6`) + E2E (convidar → aceitar → login; login como profissional e checar escopo). `RESEND_API_KEY`/`MAIL_FROM` opcionais no `.env` (sem eles, usa link copiável).

---

## 16. Agendador + Follow-up automático + Google Calendar (Fase C, 2026-06-18)

> **Migration nova `b2c3d4e5f6a7`** (head atual): `appointments.reminders` (JSONB) + `appointments.google_event_id` + tabela `google_calendar_credentials`. **Deps novas** (já no `requirements.txt` e instaladas na venv): `apscheduler`, `cryptography`, `google-auth`, `google-auth-oauthlib`, `google-api-python-client`.
>
> **Princípio de segurança:** todos os recursos da Fase C degradam graciosamente — sem `GOOGLE_CLIENT_ID/SECRET` o GCal fica off; `SCHEDULER_ENABLED=false` desliga os jobs; falhas de rede são logadas, nunca quebram booking/boot.

### 16.1 Agendador (APScheduler in-process)
- [scheduler.py](app/services/scheduler.py): `AsyncIOScheduler` iniciado/parado no `lifespan` de [main.py](app/main.py), guardado por `SCHEDULER_ENABLED`. Jobs: lembretes (cada `REMINDER_JOB_MINUTES`), reengajamento (cada `REENGAGE_JOB_HOURS`), reconciliação GCal (só se configurado). `max_instances=1, coalesce=True`.
- ⚠️ **Multi-worker:** rodar o scheduler em **1 worker só** (ou `SCHEDULER_ENABLED=false` e disparar via cron externo) para não duplicar envios.

### 16.2 Follow-up automático + lembretes
- [followups.py](app/services/followups.py): `run_appointment_reminders` (janelas marcam `appointments.reminders` p/ não repetir; lógica de "banda" entre janelas) e `run_reengagement` (contatos com `last_inbound_at` > N dias, estágio `new_lead`/`in_conversation`, não bloqueado/pausado, cooldown). Mensagem de reengajamento gerada por `ai.generate_followup_message` (chamada única ao Gemini, sem tools). Envios via `wa_service`, cada um em try/except; outbound persistido como `Message` (`ai_model_used="sofia-followup"`) → aparece no inbox.
- **Configurável por clínica** em `settings.followups` (aba **Lembretes & Follow-up** em Configurações — [followups-tab.tsx](frontend/src/components/settings/followups-tab.tsx)): `reminders_enabled`, `reminder_hours` (lista de horas-antes, ex. `[24,2]`, máx. 72h cada), `reengagement_enabled`, `reengage_after_days`, `reengage_cooldown_days`. Defaults globais em [config.py](app/config.py) (`REMINDER_JOB_MINUTES`, `REENGAGE_JOB_HOURS`, `REENGAGE_AFTER_DAYS`, `REENGAGE_COOLDOWN_DAYS`) usados como fallback. `_reminder_windows()`/`_int_cfg()` leem e validam a config do tenant.

### 16.3 Google Calendar por profissional
- **Cripto** [crypto.py](app/core/crypto.py): Fernet via `ENCRYPTION_KEY` (ou derivado do `SECRET_KEY`). Refresh token guardado **criptografado**; nunca volta ao cliente (status expõe só boolean).
- **Modelo** [google_credentials.py](app/models/google_credentials.py) (`google_calendar_credentials`, 1 por usuário) + `appointments.google_event_id`.
- **OAuth** [integrations.py](app/api/v1/routes/integrations.py): `GET /integrations/google/connect` (URL de consent com `state` JWT assinado), `GET /integrations/google/callback` (**público** — em `_PUBLIC_PREFIXES`; troca code→refresh token, salva cifrado, redireciona p/ `/dashboard/calendar?google=...`), `GET /integrations/google/status`, `DELETE /integrations/google`.
- **Sync** [google_calendar.py](app/services/google_calendar.py): chamadas síncronas do google-api-client em `asyncio.to_thread`; `sync_appointment(id)` cria/atualiza/deleta o evento no GCal do profissional (sessão própria, best-effort). Disparado em background nas rotas manuais `POST/PATCH /appointments` e pelo job `run_google_sync_reconcile` (cobre agendamentos criados pela Sofia — futuros, com profissional conectado e sem `google_event_id`).
- **Frontend**: [useGoogleCalendar.ts](frontend/src/hooks/useGoogleCalendar.ts) + [google-calendar-button.tsx](frontend/src/components/calendar/google-calendar-button.tsx) no header do Calendário (visível a todos os papéis — cada um conecta a própria conta). Oculto se o servidor não tiver GCal configurado.

### 16.4 Verificação (2026-06-18, com Postgres no ar)
- ✅ `alembic upgrade head` aplicado; colunas/tabelas confirmadas via information_schema.
- ✅ Smoke tests contra o banco real: `/reports/overview` (KPIs + 31 pts de série), `list_contacts` (serializa `crm_stage` + escopo de papel), `set_crm_stage` + helpers de `crm.py` (com rollback), criação de convite com fallback de link (+ cleanup).
- ✅ Boot completo (uvicorn): `/health` 200 e **scheduler inicia** os jobs no lifespan sem erro (`gcal=False` sem credenciais).
- ✅ `npx tsc --noEmit` limpo; `crypto` round-trip OK.
- ⚠️ **Não executei os jobs de envio** (`run_appointment_reminders`/`run_reengagement`) contra dados reais — eles disparam WhatsApp de verdade. Quando o backend de produção reiniciar com o scheduler ligado, lembretes passam a sair para agendamentos nas próximas 72h e reengajamento para contatos inativos (só com `last_inbound_at` preenchido = mensagens novas).
- ⏳ **Pendente do usuário (opcional):** `.env` `GOOGLE_CLIENT_ID/SECRET/REDIRECT_URI` (GCal) e `RESEND_API_KEY`/`MAIL_FROM` (envio automático de convites). Sem eles, o resto funciona (GCal oculto; convite usa link).

### 16.5 Correção (revisão pós-implementação)
- `crm.mark_scheduled`/`mark_attended` reescritos: um lead `lost` que agenda é **revivido** para `scheduled` (a ordenação linear anterior travava em "lost"). Guarda agora por conjunto "já neste estágio ou adiante".

---

## 17. Humanização de Mensagens WhatsApp (2026-06-23)

> **Sem migration.** Três camadas empilhadas que fazem a Sofia parecer uma pessoa real no WhatsApp. Todas in-process (1-worker, mesma restrição do scheduler). Cada camada pode ser desligada independentemente via flag no `.env`.

### 17.1 Message Batching (debounce por contato)

**Arquivo:** [app/services/message_batcher.py](app/services/message_batcher.py)

- Registry `contact_id → asyncio.Task` em memória de processo.
- `schedule(contact_id, work)`: cancela o timer existente e cria um novo com janela aleatória entre `BATCH_WINDOW_MIN_SECONDS` e `BATCH_WINDOW_MAX_SECONDS` (padrão 8–10 s). O timer reseta a cada nova mensagem do mesmo contato.
- Quando o timer dispara, executa `work` **uma única vez** — que por sua vez re-lê **todas** as mensagens inbound não respondidas do banco (Phase 2 não depende de qual mensagem acionou o timer).
- `flush(contact_id, work)`: cancela o timer e executa imediatamente. Usado para **mensagens de mídia**, que não devem esperar a janela de debounce.
- `MESSAGE_BATCHING_ENABLED=false` desativa o debounce e despacha imediatamente.
- **Cuidado:** timer perdido em reinício do worker. A mensagem persiste no banco (Phase 1 sempre salva), mas a resposta automática não acontece para bursts no exato momento do restart.

### 17.2 Replies Particionadas

**Arquivo:** [app/services/humanizer.py](app/services/humanizer.py) + prompt em [app/services/ai.py](app/services/ai.py)

- `DEFAULT_SYSTEM_PROMPT` instrui a Sofia a separar partes longas com `[[BREAK]]` (extremamente improvável em texto natural pt-BR).
- `split_reply(text)`:
  1. Se `[[BREAK]]` presente → divide aí (caminho principal).
  2. Se `RESPONSE_SPLIT_ENABLED=true` e texto > `RESPONSE_SPLIT_MAX_CHARS` (padrão 320) → fallback por parágrafos/frases (`_split_by_length` + `_split_sentences`).
  3. Retorna sempre `list[str]` com ≥ 1 item, nunca vaza o marcador.
- Cada parte é enviada como mensagem WhatsApp separada.

### 17.3 Simulação de Comportamento Humano

**Arquivos:** [app/services/whatsapp.py](app/services/whatsapp.py) + [app/api/v1/routes/webhooks.py](app/api/v1/routes/webhooks.py)

Sequência por burst respondido:
1. **Marcação como lida** (`mark_messages_as_read`) — blue ticks antes de qualquer digitação.
2. Por cada parte da resposta:
   - `send_presence("composing")` — "digitando…" no WhatsApp do paciente.
   - `asyncio.sleep(typing_delay_seconds(parte))` — pausa proporcional ao tamanho.
   - `send_text_message()` — envia a parte.
   - `_save_outbound()` — salva como `Message(OUTBOUND)` separada no banco.

`typing_delay_seconds(text)`:
```
base = clamp(len(text) / TYPING_CHARS_PER_SECOND, TYPING_MIN_SECONDS, TYPING_MAX_SECONDS)
delay = base × uniform(1 - TYPING_JITTER, 1 + TYPING_JITTER)
```
Padrão: 25 cps, 1.2–6.0 s, ±15% jitter.

- `send_presence` e `mark_messages_as_read` são **best-effort**: swallam qualquer exceção (log `warning`), nunca abortam o envio.
- Se `TYPING_SIMULATION_ENABLED=false`, a presença não é enviada mas o delay ainda ocorre (desligar `MESSAGE_BATCHING_ENABLED` também é recomendado em dev para não bloquear testes).
- `READ_RECEIPT_ENABLED=false` pula a marcação como lida.

### 17.4 Ponto de entrada — `_generate_and_send`

Função em [webhooks.py](app/api/v1/routes/webhooks.py) chamada pelo batcher após a janela de debounce:

```
1. Recarrega Contact do banco (ai_paused pode ter mudado durante a espera)
2. _collect_unanswered(db, tenant_id, contact_id) → todas as inbound desde o último outbound
3. Combina textos + _latest_media (decodifica data URI do campo media_url)
4. generate_reply() → commit das tool writes (ex.: create_appointment)
5. mark_messages_as_read (best-effort)
6. Para cada parte em split_reply(reply_text):
   send_presence → sleep(typing_delay) → send_text_message → _save_outbound
```

### 17.5 Variáveis de ambiente

Todas opcionais (defaults já ativam o comportamento humanizado):

| Variável | Default | Descrição |
|---|---|---|
| `MESSAGE_BATCHING_ENABLED` | `true` | Debounce de burst de mensagens |
| `BATCH_WINDOW_MIN_SECONDS` | `8.0` | Mínimo da janela de debounce |
| `BATCH_WINDOW_MAX_SECONDS` | `10.0` | Máximo da janela de debounce |
| `RESPONSE_SPLIT_ENABLED` | `true` | Fallback de split por tamanho |
| `RESPONSE_SPLIT_MAX_CHARS` | `320` | Limite de caracteres para o fallback |
| `TYPING_SIMULATION_ENABLED` | `true` | Envia "digitando…" antes de cada parte |
| `TYPING_CHARS_PER_SECOND` | `25.0` | Velocidade de digitação simulada |
| `TYPING_MIN_SECONDS` | `1.2` | Delay mínimo por parte |
| `TYPING_MAX_SECONDS` | `6.0` | Delay máximo por parte |
| `TYPING_JITTER` | `0.15` | Variação aleatória ±15% |
| `READ_RECEIPT_ENABLED` | `true` | Marcar como lida (blue ticks) |

### 17.6 Verificação

- ✅ `venv\Scripts\python.exe -m compileall -q app` — nenhum erro
- ✅ `python -c "import app.main"` — boot completo OK
- ✅ 7 testes inline do humanizer (split por marcador, fallback por tamanho, delay com jitter, batch_window)
- ✅ 3 testes async do batcher (debounce reseta, flush imediato, disabled → imediato)
- ⚠️ `send_presence`/`mark_messages_as_read` são best-effort — falha nunca impede a resposta. Fluxo de conexão UAZAPI (create→webhook→connect→QR) validado end-to-end contra o servidor real.
