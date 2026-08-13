# Limpeza de redundâncias — design

**Data:** 2026-08-13
**Status:** aprovado, pronto para plano de implementação
**Baseline:** 200 testes unitários passando (`venv\Scripts\python -m pytest tests/ -q`, 6,4s)

## Objetivo

Remover código, dependências e documentação redundantes ou mortos, e unificar as
duplicações reais que já viraram risco de correção, **sem alterar o comportamento
observável do sistema**. O projeto está em pré-lançamento (ver `PENDENCIAS.md`),
então o envelope é deliberadamente conservador: nada de reestruturação de módulo
no caminho crítico da Sofia.

## Envelope de risco (decidido)

- **Dentro:** remoção de código morto verificável + unificação de duplicações
  cujo comportamento é idêntico hoje.
- **Fora:** reestruturar `app/services/ai_tools.py` (~1900 linhas) e
  `app/api/v1/routes/webhooks.py` (1160 linhas). Registrado como dívida técnica
  na seção final.
- **Fora:** deletar o caminho legacy de geração de resposta. Ele é o **default em
  produção**; o multi-agente custa 2-3 chamadas Gemini por turno e está desligado
  aguardando piloto. Decisão de produto, não de limpeza.

## Critério de aceite global

1. `venv\Scripts\python -m pytest tests/ -q` → **no mínimo 200 passando**, sem
   alterar nenhuma asserção existente. Duas exceções autorizadas:
   - `tests/test_human_takeover.py` e `tests/test_followups_guards.py` hoje testam
     duas cópias separadas da mesma regra e passam a apontar para a função
     compartilhada;
   - testes **novos** para `app/services/takeover.py` são esperados, cobrindo as
     duas formas: a função Python (janela ativa / expirada / `None`) e o predicado
     SQLAlchemy (que hoje não tem cobertura unitária — só é exercitado
     indiretamente pelo recovery sweep). O predicado deve ser testado por
     comparação de SQL compilado ou por uma query real na suíte de integração,
     conforme couber melhor no padrão existente.
2. `cd frontend && npx tsc --noEmit` → sem erros.
3. `cd frontend && npm run build` → build de produção conclui.
4. `venv\Scripts\python -c "import app.main"` → OK.
5. Suíte de integração (`docker compose up -d` + `pytest tests/integration -q`)
   se o Docker estiver disponível no ambiente de execução.

---

## Seção 1 — Remoção de código morto

Zero mudança de comportamento. Cada item abaixo foi verificado por busca no
repositório inteiro, não por inspeção visual.

### 1.1 Componentes de UI sem nenhum import

Nenhum dos três é referenciado por qualquer um dos 64 arquivos `.ts`/`.tsx` em
`frontend/src/`:

- `frontend/src/components/ui/accordion.tsx`
- `frontend/src/components/ui/calendar.tsx`
- `frontend/src/components/ui/card.tsx`

### 1.2 Dependências npm órfãs

Remover de `frontend/package.json` (9 pacotes):

| Pacote | Por quê |
|---|---|
| `@radix-ui/react-avatar` | `avatar.tsx` usa `@base-ui/react/avatar` |
| `@radix-ui/react-dialog` | `dialog.tsx` e `sheet.tsx` usam `@base-ui/react/dialog` |
| `@radix-ui/react-dropdown-menu` | `dropdown-menu.tsx` usa `@base-ui/react/menu` |
| `@radix-ui/react-scroll-area` | `scroll-area.tsx` usa `@base-ui/react/scroll-area` |
| `@radix-ui/react-tooltip` | `tooltip.tsx` usa `@base-ui/react/tooltip` |
| `@dnd-kit/sortable` | só `@dnd-kit/core` é importado (`kanban-board.tsx`) |
| `@dnd-kit/utilities` | idem |
| `react-day-picker` | único consumidor era `ui/calendar.tsx`, removido em 1.1 |
| `shadcn` | é CLI de scaffolding, não dependência de runtime |

**Preservar explicitamente** (parecem órfãos numa busca superficial, mas não são):

- `@radix-ui/react-label` e `@radix-ui/react-slot` — usados por
  `ui/form.tsx`, que por sua vez é usado pelas páginas de auth.
- `tw-animate-css` — importado em `frontend/src/app/globals.css` linha 1, não em TS.
- `react-dom` — peer requirement do Next.js.
- `@dnd-kit/core` — usado em `kanban-board.tsx`.

Após editar `package.json`, rodar `npm install` para regenerar
`package-lock.json`, e então o gate `npm run build`.

### 1.3 Scripts one-off rastreados no git

- `frontend/fix_css.js`
- `frontend/revert_css.js`
- `frontend/fix_opacity.js`

Os três mutam `frontend/src/app/globals.css` **in-place** e já foram executados.
`fix_css.js` remove os wrappers `oklch(...)`; `revert_css.js` os recoloca. Manter
ambos versionados é um footgun: executar qualquer um hoje corrompe o CSS atual.

### 1.4 Arquivo vazio rastreado

- `frontend/form.json` — 0 bytes, nenhum consumidor.

### 1.5 Script fora de lugar

`backfill_contacts.py` (raiz) → `scripts/backfill_contacts.py`.

**Mover, não deletar:** preenche `Contact.profile_picture_url` a partir da UAZAPI
e é reexecutável para contatos novos sem foto. `scripts/` já é a casa desse tipo
de utilitário (`enable_multimodal.py`). Os imports dentro do arquivo são
absolutos (`from app.database import ...`), então a mudança de diretório não
quebra nada; `scripts/__init__.py` já existe.

### 1.6 Entrada de log morta

Remover de `_EVENT_STYLE` em `app/core/logging.py`:

```python
"human_handoff_requested": ("🙋", "TRANSFERIDO para humano"),
```

Nenhum ponto do código emite esse evento. É resto do handoff removido, e o rótulo
descreve um comportamento que o `CLAUDE.md` declara explicitamente inexistente
("No human handoff — Sofia resolves every turn herself"). Há inclusive um teste
estrutural que prova a ausência da feature
(`tests/test_agents_tool_partition.py::TestNoHandoffTool`).

---

## Seção 2 — Uma casa só para `in_human_takeover`

### Problema

A mesma regra de domínio está expressa **três vezes**:

| Local | Forma |
|---|---|
| `app/api/v1/routes/webhooks.py:70` | `_in_human_takeover(contact)` — usa `datetime.now(timezone.utc)` internamente |
| `app/services/followups.py:163` | `_in_human_takeover(contact, now)` — recebe `now` injetado |
| `app/api/v1/routes/webhooks.py:1190-1193` | predicado SQLAlchemy no recovery sweep: `or_(human_takeover_until.is_(None), human_takeover_until <= now)` |

As duas primeiras retornam `until is not None and until > now` — corpo idêntico.
A terceira é a mesma regra negada, em SQL, e o comentário no código **já admite a
duplicação**: *"same intent as `_in_human_takeover`, expressed as a SQL predicate
since this runs as one aggregate query, not per-contact."*

Isto é exatamente o padrão que o `CLAUDE.md` documenta como já tendo causado bug
no projeto, na seção de prompts: cópias parafraseadas em que *"every fix had to be
made twice and one was always forgotten"*. E o próprio `CLAUDE.md` afirma que
**todo ponto de decisão de resposta** precisa checar essa janela — uma invariante
espalhada em três expressões, em dois arquivos, é frágil por construção. Uma
mudança semântica (por exemplo, adicionar um período de carência) hoje exige três
edições que nada obriga a acontecer juntas.

### Solução

Novo módulo `app/services/takeover.py`, mínimo e puro, exportando as **duas**
formas lado a lado:

```python
def in_human_takeover(contact: Contact, now: datetime) -> bool:
    """True enquanto a janela de atendimento humano deste contato está ativa."""

def not_in_human_takeover_clause(now: datetime):
    """A mesma regra, negada, como predicado SQLAlchemy — para queries
    agregadas que filtram contatos sem carregar cada um em Python."""
```

Colocar as duas no mesmo arquivo é o ponto: uma mudança de semântica fica visível
como duas linhas adjacentes, em vez de três edições espalhadas que alguém precisa
lembrar de sincronizar.

Assinatura vencedora é a de `followups.py` (com `now` injetado): é a testável, e
as guardas de fuso horário em `tests/test_followups_guards.py` dependem disso.

### Call sites a atualizar

| Arquivo | Linha | Ação |
|---|---|---|
| `webhooks.py` | 569 | `human_takeover = in_human_takeover(contact, datetime.now(timezone.utc))` |
| `webhooks.py` | 923 | idem, com `now` explícito |
| `webhooks.py` | 1190-1193 | substituir o `or_(...)` inline por `not_in_human_takeover_clause(now)` |
| `followups.py` | 191, 354 | trocar para o import compartilhado (`now` já está em escopo) |

Remover as duas definições locais (`webhooks.py:70`, `followups.py:163`).

### Por que módulo novo

- `webhooks.py` (rota) importar de `followups.py` (serviço de disparo proativo) é
  dependência na direção errada — a rota passaria a depender do agendador.
- Um módulo puro, sem I/O, testável direto segue o padrão que `app/services/crm.py`
  já estabelece no projeto.
- A alternativa considerada era virar método no modelo `Contact`. Descartada: os
  modelos do projeto são deliberadamente só-dados (`contact.py` tem apenas
  `__repr__`), e introduzir métodos de domínio em modelos seria um padrão novo,
  contra a orientação de seguir os padrões existentes.

### Execução

1. Criar `app/services/takeover.py` com a função e docstring explicando a
   distinção de `ai_paused` (esta janela expira sozinha; `ai_paused` não).
2. Substituir os dois `_in_human_takeover` locais por import do módulo novo.
3. Atualizar **todos** os call sites em `webhooks.py` para passar `now`.
4. `tests/test_human_takeover.py` e `tests/test_followups_guards.py` passam a
   exercitar a função compartilhada.

---

## Seção 3 — Um loop de tool-calling só

### Problema

`app/services/ai.py::_legacy_generate_reply` (linhas ~449-605) e
`app/services/agents/base.py::run_specialist_loop` (linhas 78-224) são o mesmo
loop. O docstring de `base.py` admite: *"Mirrors app.services.ai._legacy_generate_reply's
loop shape but parameterized by system_prompt/tools/allowed_tool_names."*

Ambos implementam, na mesma ordem: chamada com retry → tratamento de candidate
vazio com `empty_retries < 1` → detecção de `function_call` → `execute_tool` com
argumentos idênticos → append do par `function_call`/`function_response` →
fallback de loop esgotado forçando uma completion final sem tools.

Duas strings **voltadas ao paciente** estão duplicadas literalmente nos dois
arquivos:

- `"Desculpe, tive um probleminha para processar sua mensagem agora. Pode me mandar de novo, por favor? 😊"`
- `"Desculpe, não consegui processar sua solicitação no momento. Tente novamente."`

### Solução

`run_specialist_loop` ganha um parâmetro `max_iterations: int` com default
`SPECIALIST_MAX_TOOL_ITERATIONS` (4). `_legacy_generate_reply` passa a delegar
para ele com:

- `max_iterations=MAX_TOOL_ITERATIONS` (8) — preserva o comportamento atual;
- `tools=CLINIC_TOOLS` (as 11 declarações);
- `allowed_tool_names={d.name for d in CLINIC_TOOLS.function_declarations}` —
  derivado da própria declaração, nunca uma lista literal repetida. Como cobre
  todas as tools, o gate de allowlist vira no-op para este caminho: sem mudança
  de comportamento;
- `contents` já montado por `build_conversation_contents` (o loop faz cópia local,
  então não há mutação compartilhada).

O retorno `AgentReply(text, model)` é adaptado para a tupla `(str, str)` que
`_legacy_generate_reply` deve continuar devolvendo aos seus chamadores.

**Import circular:** `agents/base.py` importa `_generate_content_with_retry` de
`ai.py` no nível de módulo. Portanto `ai.py` deve importar `run_specialist_loop`
**dentro da função** — exatamente o padrão que `generate_staff_suggestion` já usa
hoje no mesmo arquivo.

Ganho: ~150 linhas removidas e fonte única para as strings ao paciente.

### Consequência nos logs (aceita conscientemente)

Ao delegar, os slugs de log do caminho legacy mudam para a família `agent_*` que
o loop compartilhado já emite. Foi verificado que **nada no repositório consulta
esses slugs** além do próprio `app/core/logging.py` — não há alerta, teste ou
consulta acoplada a eles. O operador continua vendo os mesmos ícones e rótulos em
português no terminal, porque a Seção 4 reregistra a família nova com os mesmos
ícones e textos.

Ganho colateral: hoje o caminho multi-agente emite `agent_*` **sem nenhum rótulo
registrado**, aparecendo cru no formatter de dev. Depois desta mudança ele passa
a ter os mesmos rótulos amigáveis do legacy.

### Emissão de "resposta pronta" no loop compartilhado

Hoje só o legacy loga `gemini_reply_ready` ("🤖 resposta gerada") — a linha de log
mais útil do sistema. O loop compartilhado não loga nada ao retornar texto puro.

Mover essa emissão para dentro de `run_specialist_loop`, como `agent_reply_ready`,
com os extras `model`, `iterations`, `reply_length`, `tenant_id`, `contact_id`
(paridade com o que o legacy loga hoje). Assim os **três** chamadores — legacy,
specialists e o copiloto "Sugerir resposta" — passam a logar quando a resposta
fica pronta. Mesmo tratamento para `gemini_forced_final_reply` →
`agent_forced_final_reply`.

---

## Seção 4 — Registro de eventos de log consistente

Ajustes em `_EVENT_STYLE` (`app/core/logging.py`):

**Remover:**

- `human_handoff_requested` — sem emissor (Seção 1.6).
- `gemini_reply_ready`, `gemini_forced_final_reply`, `ai_tool_executed`,
  `gemini_empty_parts`, `gemini_tool_loop_exhausted` — deixam de ser emitidos
  quando o legacy passa a delegar (Seção 3).
- `gemini_call_failed` — **a chave nunca casou**. O evento realmente emitido em
  `ai.py:348` é `gemini_call_failed_will_retry`, então esse rótulo amigável nunca
  apareceu desde que foi escrito.

**Adicionar:**

| Slug | Ícone | Rótulo |
|---|---|---|
| `agent_reply_ready` | 🤖 | resposta gerada |
| `agent_forced_final_reply` | 🤖 | resposta gerada (final) |
| `agent_tool_executed` | 🔧 | ferramenta usada |
| `agent_empty_parts` | ⚠️ | modelo retornou vazio |
| `agent_tool_loop_exhausted` | 🔁 | loop de ferramentas esgotado |
| `agent_tool_not_allowed` | 🚫 | ferramenta bloqueada |
| `gemini_call_failed_will_retry` | 💥 | falha na chamada ao modelo |
| `gemini_call_exhausted` | 💥 | modelo falhou em todas as tentativas |

`gemini_call_exhausted` é emitido em `ai.py:346` e nunca esteve registrado.

---

## Seção 5 — Documentação

### 5.1 Arquivar o material solto

Mover para `docs/archive/` (~750 KB, todos **não rastreados** no git hoje):

`z.html`, `zz.html`, `SOFIA_DOCUMENTACAO_COMPLETA.md`, `SOFIA_TESTE_AGENDA.md`,
`SOFIA_TESTE_CONVERSA.md`, `PLANO_EXECUCAO.md`, `GEMINI_PROMPT_REDESIGN.md`,
`GEMINI_PROMPT_SETTINGS_REFINE.md`, `FABLE_PROMPT_PLANO_SOFIA.md`,
`prompt-ated.md`, `claude_prompt_wave3.md`, `scratch/`.

Arquivar, não deletar: são arquivos sem histórico no git, então uma deleção seria
irrecuperável. O usuário decide depois o que apagar.

### 5.2 `.gitignore`

Acrescentar:

```
# Documentação arquivada (material de trabalho, não versionado)
docs/archive/

# Artefato gerado pelo graphify
graphify-out/
```

### 5.3 `CLAUDE.md`

- Atualizar a seção de IA para descrever que existe **um** loop de tool-calling
  compartilhado (`run_specialist_loop`), usado pelos três caminhos, parametrizado
  por `max_iterations`/`tools`/`allowed_tool_names`.
- Corrigir a deriva de contagem: o texto e o docstring de `_legacy_generate_reply`
  dizem "all 12 tools"; `CLINIC_TOOLS` declara **11**.
- Registrar `app/services/takeover.py` como a fonte única da regra de janela de
  atendimento humano.

---

## Dívida técnica registrada (fora do escopo desta rodada)

Levantada durante a análise, deliberadamente **não** endereçada agora por estar
no caminho crítico da Sofia às vésperas do lançamento:

1. **`app/services/ai_tools.py` — ~1900 linhas, quatro responsabilidades:**
   declarações de tools, motor de agenda `capacity`, motor `per_professional`
   (`_check_availability_pp`, `_create_appointment_pp`, `_reschedule_appointment_pp`
   são implementações paralelas das mesmas três operações), e info da clínica/CRM.
   Candidato natural a virar um pacote `ai_tools/` com um módulo por motor.

2. **`app/api/v1/routes/webhooks.py` — 1160 linhas** numa rota, misturando
   validação de webhook, persistência de mensagem, caps de uso de IA, presença/
   typing e o pipeline de geração-e-envio.

Revisitar depois do lançamento, cada um com seu próprio ciclo de spec → plano.
