# Sofia — Clinic SaaS Multi-tenant com IA e WhatsApp

Sofia é um **SaaS Multi-tenant de Gestão de Clínicas** integrado a uma **secretária virtual inteligente** (IA baseada no Gemini). Cada clínica (tenant) cadastrada ganha um painel administrativo completo e uma inteligência artificial autônoma capaz de interagir com pacientes, agendar consultas, responder dúvidas institucionais e gerenciar o fluxo de atendimento de forma humana e sem interrupções.

---

## 🚀 Funcionalidades Principais

- **Arquitetura Multi-tenant:** Isolamento completo de dados por clínica (`tenant_id`).
- **Secretária Virtual Autônoma "Sofia":**
  - Integração com **Google Gemini** para conversação natural.
  - **Function Calling** nativo para interagir com o sistema (consultar agenda, criar agendamentos, cancelar/remarcar consultas, coletar dados do paciente).
  - Reconhecimento de **Estágios da Conversa** para adaptar o tom e a abordagem (primeiro contato, pós-consulta, reativação, etc.).
- **Integração WhatsApp:** Conexão direta com a **Evolution API** para envio e recebimento de mensagens, incluindo suporte a mídias multimodais (mensagens de voz, fotos e documentos).
- **Painel de Controle Administrador (Dashboard):**
  - **Inbox (Chat em Tempo Real):** Interface estilo WhatsApp Web com capacidade de intervenção manual (handoff), pausando temporariamente a IA.
  - **Calendário Dinâmico:** Grade de horários com controle de profissionais, status de consultas e atualização visual automática.
  - **Configurações Centralizadas:** Gestão do perfil da clínica, conexão por QR Code com o WhatsApp, prompts e tom da IA, e horários de funcionamento.

---

## 🛠️ Stack Técnica

### Backend
- **Framework:** FastAPI (Python 3.13)
- **Banco de Dados:** PostgreSQL 16 com SQLAlchemy 2.0 (Async)
- **Migrações:** Alembic
- **Integração de IA:** Google Gemini SDK (`google-genai`)
- **API do WhatsApp:** Evolution API (Self-hosted)
- **Ambiente Virtual:** Python `venv` + Docker Compose para serviços locais

### Frontend
- **Framework:** Next.js 14+ (App Router)
- **Estilização:** Tailwind CSS v3 & Shadcn/UI
- **Gerenciamento de Estado:** Zustand (Auth/Tokens)
- **Consumo de API:** Axios com Interceptors para renovação automática de tokens (JWT Refresh Token) e controle de tenant.
- **Requisições e Cache:** TanStack React Query v5

---

## 📦 Pré-requisitos

Antes de iniciar, certifique-se de ter instalado em sua máquina:
1. [Docker & Docker Desktop](https://www.docker.com/)
2. [Python 3.13+](https://www.python.org/)
3. [Node.js 18+](https://nodejs.org/)

---

## 🔧 Configuração e Instalação

### 1. Configurar Variáveis de Ambiente
Na raiz do projeto, crie um arquivo `.env` com base no arquivo `.env.example`:

```bash
cp .env.example .env
```

Abra o `.env` e preencha as variáveis de ambiente necessárias (como a `GEMINI_API_KEY` e as credenciais da `EVOLUTION_API`).

---

### 2. Configurar o Backend e Banco de Dados

1. **Subir os serviços no Docker (Banco de dados PostgreSQL & pgAdmin):**
   ```powershell
   docker compose up -d
   ```

2. **Ativar o Ambiente Virtual do Python:**
   - No Windows (PowerShell):
     ```powershell
     .\venv\Scripts\activate
     ```
   - No Linux/macOS:
     ```bash
     source venv/bin/activate
     ```

3. **Instalar as dependências:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Executar as Migrações do Banco:**
   ```bash
   alembic upgrade head
   ```

5. **Iniciar o Servidor Backend (FastAPI):**
   ```bash
   uvicorn app.main:app --reload
   ```
   *O backend estará acessível em `http://localhost:8000`. A documentação da API estará disponível em `http://localhost:8000/docs`.*

---

### 3. Configurar o Frontend (Next.js)

1. **Navegar até o diretório do frontend:**
   ```bash
   cd frontend
   ```

2. **Instalar as dependências do Node.js:**
   ```bash
   npm install
   ```

3. **Iniciar o servidor Next.js em modo de desenvolvimento:**
   ```bash
   npm run dev
   ```
   *O frontend estará acessível em `http://localhost:3000`.*

---

## 📂 Estrutura de Pastas Simplificada

```text
├── alembic/              # Arquivos e versões de migração do banco
├── app/                  # Código-fonte do Backend (FastAPI)
│   ├── api/              # Rotas, dependências e controllers
│   ├── core/             # Segurança, tratamento de erros e configs
│   ├── middleware/       # Resolvedor de tenant por requisição
│   ├── models/           # Modelos SQLAlchemy com escopo de tenant
│   ├── schemas/          # Schemas de validação Pydantic
│   └── services/         # Integrações de IA (Gemini), ferramentas e WhatsApp
├── docker/               # Configurações do ambiente Docker
├── frontend/             # Código-fonte do Frontend (Next.js)
│   ├── src/app/          # Páginas e rotas (App Router)
│   ├── src/components/   # Componentes da interface
│   ├── src/hooks/        # Hooks Customizados (Axios/React Query)
│   └── src/store/        # Gerenciamento de estado local (Zustand)
├── docker-compose.yml    # Infraestrutura local
├── requirements.txt      # Dependências Python
└── README.md             # Documentação do projeto
```

---

## 🤝 Contribuindo

1. Faça o fork do projeto.
2. Crie uma branch para sua nova funcionalidade (`git checkout -b feature/nova-funcionalidade`).
3. Faça o commit de suas alterações (`git commit -m 'Adiciona nova funcionalidade'`).
4. Envie a branch para o repositório remoto (`git push origin feature/nova-funcionalidade`).
5. Abra um Pull Request.
