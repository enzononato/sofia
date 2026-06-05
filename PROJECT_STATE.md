# PROJECT STATE — Clinic SaaS Multi-tenant
> Handover técnico gerado em 2026-04-28. Última atualização: 2026-05-06 (sessão 7 — Sofia 2.0: multimodal + stages + tools novas).

---

## 1. Visão do Produto

SaaS Multi-tenant de Gestão de Clínicas com IA. Cada clínica (tenant) recebe:
- Canal de atendimento via **WhatsApp** (Evolution API)
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
| WhatsApp | Evolution API (self-hosted, provider-managed) |
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
  "gemini_api_key": "<chave-por-tenant-opcional>",
  "multimodal_enabled": false,
  "prompt_first_contact": "<override opcional>",
  "prompt_imminent_appointment": "<override opcional>",
  "prompt_post_appointment": "<override opcional>",
  "prompt_active_patient": "<override opcional>",
  "prompt_returning_lead": "<override opcional>",
  "prompt_reactivation": "<override opcional>"
}
```

> `multimodal_enabled` (default `false`) liga o processamento de áudio (até 1m30s), imagem, vídeo e documento via Gemini multimodal. Se desligado, Sofia responde com mensagem polida pedindo texto.
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
    "slot_granularity_minutes": 30
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

> `settings.clinic` é exposto pela tool `get_clinic_info` para que Sofia responda perguntas sobre endereço, telefone, valores e formas de pagamento sem precisar de prompt customizado.

> **IMPORTANTE:** As credenciais da Evolution API (`EVOLUTION_API_URL`, `EVOLUTION_API_KEY`) são variáveis de ambiente do servidor (provider-managed) — **nunca** armazenadas no tenant. O tenant só guarda o `instance` name e o `status` de conexão.

---

## 5. Fluxo de Conexão WhatsApp (Evolution API)

### Arquitetura
O **provedor SaaS** hospeda uma instância única da Evolution API. Cada clínica recebe uma instância nomeada `clinic-{tenant_slug}` (determinístico, sem colisões).

### Fluxo
```
Dono da clínica abre Configurações > WhatsApp
           │
           ▼
POST /tenants/me/whatsapp/connect  (Frontend)
  ├─ Backend gera webhook_secret (se não existe)
  ├─ Chama Evolution API: POST /instance/create (idempotente, 409 = já existe)
  │    └─ Configura webhook apontando para POST /webhooks/whatsapp/{slug}
  ├─ Chama Evolution API: GET /instance/connect/{instance} → QR Code (base64)
  ├─ Salva instance + status "connecting" em tenant.settings
  └─ Retorna { instance, qr_code } para o frontend
           │
           ▼
Frontend exibe QR Code → Dono escaneia com WhatsApp Business
           │
           ▼
Evolution API envia webhook: event="connection.update", state="open"
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
| PATCH | `/tenants/me` | OWNER / ADMIN | Atualiza nome, `ai_config`, `settings` |

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
| GET | `/users/{id}` | Qualquer | Detalhe |
| PATCH | `/users/{id}` | OWNER / ADMIN | Atualiza |

### Webhooks (público)
| Método | Rota | Descrição |
|---|---|---|
| POST | `/webhooks/whatsapp/{tenant_slug}` | Recebe eventos da Evolution API. Processa `messages.upsert` (mensagens) e `connection.update` (status de conexão) |

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

### 7.2 As 8 Ferramentas (`app/services/ai_tools.py`)

| Tool | Parâmetros | O que faz |
|---|---|---|
| `list_services` | nenhum | `SELECT * FROM services WHERE tenant_id=? AND is_active=true` |
| `check_availability` | `date` (YYYY-MM-DD), `service_id?` | Slots livres respeitando `tenant.settings.schedule` |
| `create_appointment` | `scheduled_at` (ISO 8601), `service_id?`, `notes?` | Insere `Appointment`. `tenant_id` e `contact_id` fixos do contexto |
| `get_upcoming_appointments` | nenhum | Próximos agendamentos do contato atual |
| `cancel_appointment` | `appointment_id` (UUID), `reason?` | Cancela agendamento. Valida `tenant_id` e `contact_id` |
| `reschedule_appointment` | `appointment_id`, `new_scheduled_at`, `new_service_id?` | Atomic reschedule (evita cancela+cria). Recalcula `ends_at` se trocar serviço |
| `get_clinic_info` | nenhum | Devolve `tenant.settings.clinic` + horário. Para perguntas sobre endereço, valores, formas de pagamento |
| `update_contact_info` | `full_name?`, `email?`, `date_of_birth?`, `address?` | Whitelist de campos cadastrais que Sofia pode atualizar. **Nunca** edita `phone`, `status`, `ai_paused` |

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
Webhook → detecta audioMessage/imageMessage/videoMessage/documentMessage
        → POST /chat/getBase64FromMediaMessage/{instance}  (Evolution API)
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
| `/dashboard/services` | 🔲 | CRUD de procedimentos |
| `/dashboard/team` | 🔲 | CRUD de equipe |

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

# Evolution API (provider-managed, global)
EVOLUTION_API_URL=https://sua-evolution-api.com
EVOLUTION_API_KEY=sua-global-api-key
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
| 4 | **Criptografia de `ai_config`** | `gemini_api_key` por tenant deve ser criptografado at rest |
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
complica deploy multi-worker (precisa Redis), e o ganho de UX vs polling de 5s
| Camada | Tecnologia |
|---|---|
| API | Python 3.13, FastAPI 0.115, Uvicorn |
| ORM / DB | SQLAlchemy 2.0 (async), asyncpg, PostgreSQL 16 |
| Migrations | Alembic 1.14 |
| Validação | Pydantic v2, pydantic-settings |
| Auth | JWT (python-jose), bcrypt 3.2.2 + passlib 1.7.4 |
| IA | Google Gemini (`google-genai 1.10`), Function Calling |
| WhatsApp | Evolution API (self-hosted, webhooks) |
| HTTP client | httpx 0.28 |
| Infra local | Docker Compose (postgres:16-alpine + pgAdmin) |

**Dependências críticas de versão:**
- `bcrypt==3.2.2` — fixado porque passlib 1.7.4 é incompatível com bcrypt ≥ 4.0
- `httpx==0.28.1` — google-genai 1.10 exige `>=0.28.1`

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

### 3.4 JWT

```
app/core/security.py → create_access_token / decode_access_token
```

Payload do JWT:
```json
{ "sub": "<user_id>", "tenant_id": "<tenant_id>", "role": "owner", "email": "...", "exp": ... }
```

Expiração padrão: 24h (`ACCESS_TOKEN_EXPIRE_MINUTES=1440`).

---

## 4. Modelos de Banco

### Tabelas

| Tabela | Herda | Propósito |
|---|---|---|
| `tenants` | `TimestampMixin` | Clínica: nome, slug (único), plano, `ai_config` JSONB, `settings` JSONB |
| `users` | `TenantScopedMixin` | Funcionários/donos. Roles: owner/admin/receptionist/professional/viewer |
| `contacts` | `TenantScopedMixin` | Pacientes/leads. `status`: lead/active/inactive/blocked |
| `services` | `TenantScopedMixin` | Procedimentos: nome, `duration_minutes`, `price` |
| `appointments` | `TenantScopedMixin` | Agendamentos. FK → contacts, services (nullable), users (professional, nullable) |
| `messages` | `TenantScopedMixin` | Histórico de mensagens WhatsApp. `direction`: inbound/outbound |

### Campos JSONB importantes em `tenants`

**`ai_config`** — configuração da IA por clínica:
```json
{
  "model": "gemini-2.0-flash",
  "system_prompt": "Você é Sofia, secretária da Clínica X...",
  "temperature": 0.7,
  "max_output_tokens": 1024,
  "gemini_api_key": "<chave-por-tenant-opcional>"
}
```

**`settings`** — configuração operacional por clínica:
```json
{
  "whatsapp": {
    "provider": "evolution",
    "api_url": "https://evolution.clinica.com.br",
    "api_key": "SUA_KEY",
    "instance": "nome-da-instancia",
    "webhook_secret": "token-validacao"
  },
  "schedule": {
    "timezone": "America/Sao_Paulo",
    "working_days": [1, 2, 3, 4, 5],
    "open_time": "08:00",
    "close_time": "18:00",
    "lunch_start": "12:00",
    "lunch_end": "13:00",
    "slot_granularity_minutes": 30
  }
}
```

`schedule` — todos os campos são opcionais. Defaults: UTC, Seg–Sex, 08h–18h, sem almoço, granularidade = duração do serviço.
- `working_days`: ISO weekday (1=Segunda … 7=Domingo)
- `slot_granularity_minutes`: espaçamento da grade de horários (ex: 30 → slots às 08:00, 08:30, 09:00…). Se omitido, usa a duração do serviço solicitado.

---

## 5. Endpoints da API

### Auth (público / semi-público)
| Método | Rota | Auth | Descrição |
|---|---|---|---|
| POST | `/auth/signup` | Nenhuma | Cria Tenant + User(OWNER) atomicamente, retorna JWT |
| POST | `/auth/login` | Middleware (tenant) | Valida email+senha no tenant resolvido, retorna JWT |

### Tenants (protegido)
| Método | Rota | Role mínima | Descrição |
|---|---|---|---|
| GET | `/tenants/me` | Qualquer autenticado | Dados da clínica atual |
| PATCH | `/tenants/me` | OWNER / ADMIN | Atualiza nome, `ai_config`, `settings` |

### Services (protegido)
| Método | Rota | Role mínima | Descrição |
|---|---|---|---|
| POST | `/services` | OWNER / ADMIN | Cria serviço (`tenant_id` injetado pelo backend) |
| GET | `/services` | Qualquer | Lista serviços ativos do tenant |
| GET | `/services/{id}` | Qualquer | Detalhe de serviço |
| PATCH | `/services/{id}` | OWNER / ADMIN | Atualiza serviço |

### Appointments (protegido)
| Método | Rota | Role mínima | Descrição |
|---|---|---|---|
| POST | `/appointments` | OWNER / ADMIN / RECEPTIONIST | Cria agendamento com validação cruzada de FKs |
| GET | `/appointments` | Qualquer | Lista com filtros: `status`, `contact_id`, `professional_id`, `date_from`, `date_to`, `limit`, `offset` |
| GET | `/appointments/{id}` | Qualquer | Detalhe |
| PATCH | `/appointments/{id}` | OWNER / ADMIN / RECEPTIONIST | Atualiza; `cancellation_reason` obrigatório ao cancelar |

### Webhooks (público — tenant resolvido internamente)
| Método | Rota | Descrição |
|---|---|---|
| POST | `/webhooks/whatsapp/{tenant_slug}` | Entrada da Evolution API. Valida `X-Webhook-Secret`, processa em background task |

### Contacts (protegido)
| Método | Rota | Role mínima | Descrição |
|---|---|---|---|
| GET | `/contacts` | Qualquer | Lista contatos com preview da última mensagem. Filtros: `status`, `search` (nome/telefone), `limit`, `offset` |
| GET | `/contacts/{id}` | Qualquer | Detalhe do contato |
| GET | `/contacts/{id}/messages` | Qualquer | Histórico de mensagens do contato (mais recente primeiro) |
| PATCH | `/contacts/{id}` | OWNER / ADMIN / RECEPTIONIST | Atualiza dados e status do contato |

### Users / Staff (protegido)
| Método | Rota | Role mínima | Descrição |
|---|---|---|---|
| POST | `/users` | OWNER / ADMIN | Cria funcionário; só OWNER pode criar outro OWNER |
| GET | `/users` | Qualquer | Lista equipe ativa (ou com `?include_inactive=true`) |
| GET | `/users/{id}` | Qualquer | Detalhe do funcionário |
| PATCH | `/users/{id}` | OWNER / ADMIN | Atualiza dados, role ou senha. ADMIN não pode editar OWNERs |

### Modelos sem rotas
- `Message` — gravado automaticamente pelo webhook; leitura via `GET /contacts/{id}/messages`

---

## 6. O Cérebro da Sofia — Function Calling

### 6.1 Fluxo Geral

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
wa_service.send_text_message(tenant.settings, phone, reply_text)
```

### 6.2 Loop de Function Calling (`app/services/ai.py`)

```python
MAX_TOOL_ITERATIONS = 5

for iteration in range(MAX_TOOL_ITERATIONS):
    response = await client.aio.models.generate_content(model, contents, config)
    function_call_part = next((p for p in response.candidates[0].content.parts
                               if p.function_call is not None), None)
    if function_call_part is None:
        return response.text, model          # ← saída normal

    tool_result = await execute_tool(fn.name, dict(fn.args), db, tenant.id, contact.id)
    contents.append(response_content)        # turno do modelo
    contents.append(Content(role="user",     # turno com resultado da tool
        parts=[Part(function_response=FunctionResponse(fn.name, tool_result))]))

return "Desculpe, não consegui...", model    # ← fallback se esgotou iterações
```

### 6.3 As 5 Ferramentas (`app/services/ai_tools.py`)

| Tool | Parâmetros | O que faz |
|---|---|---|
| `list_services` | nenhum | `SELECT * FROM services WHERE tenant_id=? AND is_active=true` |
| `check_availability` | `date` (YYYY-MM-DD), `service_id?` | Slots livres respeitando `tenant.settings.schedule`: fuso, dias úteis, horário, almoço e granularidade. Detecção de conflito por janela real (start→end) com batch lookup de duração dos serviços agendados |
| `create_appointment` | `scheduled_at` (ISO 8601), `service_id?`, `notes?` | Insere `Appointment`. `tenant_id` e `contact_id` fixos do contexto — **jamais dos args** |
| `get_upcoming_appointments` | nenhum | Próximos agendamentos do contato atual (`scheduled_at >= now()`) |
| `cancel_appointment` | `appointment_id` (UUID), `reason?` | Cancela agendamento do contato atual. Valida `tenant_id` e `contact_id` — IA não pode cancelar agendamentos de outros pacientes |

### 6.4 Segurança Crítica — Prevenção de IDOR / Prompt Injection

> **O backend nunca aceita `tenant_id` ou `contact_id` vindos dos argumentos da IA.**

Em `execute_tool()` e em cada handler de tool, esses valores são sempre lidos do contexto Python (`tenant_id` e `contact_id` passados como parâmetros da função), nunca de `args`. Se um prompt malicioso instruir a IA a passar `contact_id` de outro paciente, o parâmetro `args` simplymente não contém esse campo nas declarações — e mesmo que viesse em `args`, o executor ignora e usa o `contact_id` do contexto.

Adicionalmente, em `_create_appointment`:
```python
# service_id vinda da IA é validada com AND tenant_id = ? antes de ser aceita
svc_result = await db.execute(
    select(Service).where(Service.id == candidate, Service.tenant_id == tenant_id)
)
```

---

## 7. Configuração do Ambiente

### `.env` (variáveis obrigatórias para rodar)

```env
SECRET_KEY=<32+ chars aleatórios>
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/clinic_saas
GEMINI_API_KEY=AIza...
TENANT_RESOLUTION_STRATEGY=header   # header | subdomain | jwt
```

### Subir infra e aplicação

```bash
docker compose up -d                  # PostgreSQL 16 + pgAdmin (localhost:5050)
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt
alembic upgrade head                  # cria todas as tabelas
uvicorn app.main:app --reload         # API em localhost:8000
```

### Testar signup inicial

```bash
curl -X POST http://localhost:8000/api/v1/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"clinic_name":"Clínica X","clinic_slug":"clinica-x","clinic_email":"contato@x.com",
       "owner_name":"Dr. João","owner_email":"joao@x.com","password":"senha1234"}'
```

---

## 8. Estrutura de Pastas

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
│   │           ├── auth.py          # signup, login
│   │           ├── tenants.py       # GET/PATCH /tenants/me
│   │           ├── services.py      # CRUD serviços
│   │           ├── appointments.py  # CRUD agendamentos
│   │           └── webhooks.py      # POST /webhooks/whatsapp/{slug}
│   ├── core/
│   │   └── security.py      # hash_password, verify_password, create/decode JWT
│   ├── middleware/
│   │   └── tenant.py        # TenantMiddleware (3 estratégias)
│   └── services/
│       ├── ai.py            # generate_reply() — loop de function calling
│       ├── ai_tools.py      # CLINIC_TOOLS declarations + execute_tool()
│       └── whatsapp.py      # send_text_message() — cliente Evolution API
├── alembic/
│   ├── env.py               # Config async do Alembic
│   └── versions/            # Migrations geradas
├── docker/
│   └── pgadmin-servers.json # Servidor pré-configurado no pgAdmin
├── docker-compose.yml       # PostgreSQL 16 + pgAdmin
├── alembic.ini
├── requirements.txt
└── .env.example
```

---

## 9. Próximos Passos (Backlog Priorizado)

### ✅ Concluído
- **Contacts API** — `GET /contacts`, `GET /contacts/{id}`, `GET /contacts/{id}/messages`, `PATCH /contacts/{id}`
- **Users/Staff API** — `POST /users`, `GET /users`, `GET /users/{id}`, `PATCH /users/{id}`
- **Tool `cancel_appointment`** — Sofia pode criar e cancelar agendamentos
- **Frontend UI** — Configuração da IA (Sofia 2.0 multimodal e estágios), CRUD de Serviços e CRUD de Equipe concluídos.

### 🔲 Pendente

| Prioridade | Feature | Notas |
|---|---|---|
| 1 | **Frontend Dashboard** | Next.js — inbox de conversas, calendário de agendamentos, config da IA |
| 2 | **Refresh Token** | JWT de 24h é curto para prod; adicionar refresh token |
| 3 | **Rate limiting** | Por tenant — evitar abuso no endpoint de webhook |
| 4 | **Criptografia de `ai_config`** | `gemini_api_key` por tenant deve ser criptografado at rest |

### 8. Estrutura de Pastas (atualizada)

```
app/api/v1/routes/
    ├── auth.py          # signup, login
    ├── tenants.py       # GET/PATCH /tenants/me
    ├── services.py      # CRUD serviços
    ├── appointments.py  # CRUD agendamentos
    ├── contacts.py      # CRUD contatos + GET histórico de mensagens  ← NOVO
    ├── users.py         # CRUD equipe / staff                         ← NOVO
    └── webhooks.py      # POST /webhooks/whatsapp/{slug}

app/services/
    ├── ai.py            # generate_reply() — loop de function calling
    ├── ai_tools.py      # 5 tools: list_services, check_availability,
    │                    #          create_appointment, get_upcoming_appointments,
    │                    #          cancel_appointment                  ← NOVO
    └── whatsapp.py      # send_text_message()

app/schemas/
    └── contact.py       # ContactReadWithLastMessage adicionado        ← NOVO
```
