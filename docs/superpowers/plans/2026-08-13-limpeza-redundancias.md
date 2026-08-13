# Limpeza de Redundâncias — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remover código, dependências e documentação mortos e unificar três duplicações reais do Clinic SaaS, sem alterar nenhum comportamento observável.

**Architecture:** Oito tarefas independentes e sequenciais. As três primeiras são remoção pura (risco zero). As tarefas 3-4 criam uma fonte única para a regra de janela de atendimento humano, hoje expressa em três lugares. As 5-6 fazem o caminho legacy de geração de resposta delegar para o mesmo loop de tool-calling que os specialists já usam. As 7-8 acertam o registro de logs e arquivam documentação solta.

**Tech Stack:** Python 3.13 · FastAPI · SQLAlchemy 2.0 async · pytest/pytest-asyncio · Next.js 14 · TypeScript · Tailwind v3

**Spec:** `docs/superpowers/specs/2026-08-13-limpeza-redundancias-design.md`

## Global Constraints

- **Nenhuma mudança de comportamento observável.** Toda tarefa preserva a saída atual; só a estrutura interna muda.
- **Baseline de testes: 200 passando.** `venv\Scripts\python -m pytest tests/ -q` nunca pode regredir. Contagem pode subir (testes novos), nunca descer.
- **Não alterar asserção de teste existente**, exceto onde este plano manda explicitamente (Tarefa 4).
- **Fora de escopo, não tocar:** `app/services/ai_tools.py` e `app/api/v1/routes/webhooks.py` não são reestruturados; só recebem as edições pontuais descritas aqui.
- **Não deletar o caminho legacy** (`_legacy_generate_reply`). Ele é o default em produção.
- `httpx==0.28.1` — exigido por google-genai 1.10. Nunca atualizar.
- `bcrypt==3.2.2` — pin deliberado, validado contra os hashes `$2b$` já no banco.
- Tailwind é **v3**. Não introduzir classes v4.
- Comandos rodam do diretório raiz do repo, em PowerShell. O Python do backend é `venv\Scripts\python`.
- Branch de trabalho: `cleanup/remocao-redundancias` (já criado, com o spec commitado).

## File Structure

**Criados:**
| Arquivo | Responsabilidade |
|---|---|
| `app/services/takeover.py` | Fonte única da regra de janela de atendimento humano — a forma Python e a forma SQL, lado a lado |
| `tests/test_takeover.py` | Testes puros do módulo acima |
| `docs/archive/` | Material de trabalho não versionado, tirado da raiz |

**Modificados:**
| Arquivo | Mudança |
|---|---|
| `frontend/package.json` | Remove 9 dependências órfãs |
| `app/api/v1/routes/webhooks.py` | Remove `_in_human_takeover` local; 3 call sites passam a usar `takeover.py` |
| `app/services/followups.py` | Remove `_in_human_takeover` local; 2 call sites passam a usar `takeover.py` |
| `app/services/agents/base.py` | `run_specialist_loop` ganha `max_iterations` + logs de "resposta pronta" |
| `app/services/ai.py` | `_legacy_generate_reply` delega o loop para `run_specialist_loop` |
| `app/core/logging.py` | `_EVENT_STYLE`: remove entradas mortas/quebradas, registra a família `agent_*` |
| `tests/test_human_takeover.py` | 4 testes puros apontam para a função compartilhada |
| `tests/test_followups_guards.py` | Import da função compartilhada |
| `.gitignore` | Ignora `docs/archive/` e `graphify-out/` |
| `CLAUDE.md` | Documenta o loop único e o `takeover.py`; corrige "12 tools" → 11 |

**Deletados:** 3 componentes de UI, 3 scripts one-off, 1 arquivo vazio.
**Movido:** `backfill_contacts.py` → `scripts/backfill_contacts.py`.

---

### Task 1: Remover componentes de UI mortos e dependências npm órfãs

**Files:**
- Delete: `frontend/src/components/ui/accordion.tsx`
- Delete: `frontend/src/components/ui/calendar.tsx`
- Delete: `frontend/src/components/ui/card.tsx`
- Modify: `frontend/package.json` (bloco `dependencies`)

**Interfaces:**
- Consumes: nada.
- Produces: nada. Nenhuma tarefa posterior depende desta.

**Contexto:** Os três componentes não são importados por nenhum dos 64 arquivos `.ts`/`.tsx` em `frontend/src/`. Os 5 pacotes `@radix-ui/*` removidos ficaram para trás quando os componentes migraram para `@base-ui/react`.

- [ ] **Step 1: Confirmar que os três componentes não têm nenhum consumidor**

```powershell
Select-String -Path (Get-ChildItem frontend\src -Recurse -Include *.tsx,*.ts).FullName -Pattern "ui/accordion|ui/calendar|ui/card"
```

Esperado: **nenhuma saída**. Se aparecer qualquer linha, PARE e reporte — a premissa da tarefa está errada.

- [ ] **Step 2: Deletar os três componentes**

```powershell
git rm frontend/src/components/ui/accordion.tsx frontend/src/components/ui/calendar.tsx frontend/src/components/ui/card.tsx
```

- [ ] **Step 3: Remover as 9 dependências órfãs do package.json**

Editar `frontend/package.json` e remover **exatamente** estas linhas do bloco `dependencies`:

```
"@radix-ui/react-avatar"
"@radix-ui/react-dialog"
"@radix-ui/react-dropdown-menu"
"@radix-ui/react-scroll-area"
"@radix-ui/react-tooltip"
"@dnd-kit/sortable"
"@dnd-kit/utilities"
"react-day-picker"
"shadcn"
```

**PRESERVAR obrigatoriamente** (parecem órfãos numa busca superficial, mas não são):
- `@radix-ui/react-label` e `@radix-ui/react-slot` — usados por `ui/form.tsx`
- `tw-animate-css` — importado em `frontend/src/app/globals.css` linha 1, não em TS
- `react-dom` — peer requirement do Next.js
- `@dnd-kit/core` — usado em `kanban-board.tsx`

Cuidado com a vírgula final do JSON após remover entradas.

- [ ] **Step 4: Regenerar o lockfile**

```powershell
cd frontend; npm install
```

Esperado: conclui sem erro. `package-lock.json` é modificado.

- [ ] **Step 5: Type-check limpo**

```powershell
cd frontend; npx tsc --noEmit
```

Esperado: **nenhum erro**. Se acusar módulo faltando, algum componente ainda era usado — reverta e reporte.

- [ ] **Step 6: Build de produção passa**

```powershell
cd frontend; npm run build
```

Esperado: build conclui com sucesso.

- [ ] **Step 7: Commit**

```powershell
git add frontend/package.json frontend/package-lock.json frontend/src/components/ui/
git commit -m "chore(frontend): remove 3 componentes de UI sem uso e 9 deps orfas"
```

---

### Task 2: Remover scripts one-off e mover backfill_contacts.py

**Files:**
- Delete: `frontend/fix_css.js`, `frontend/revert_css.js`, `frontend/fix_opacity.js`
- Delete: `frontend/form.json`
- Move: `backfill_contacts.py` → `scripts/backfill_contacts.py`

**Interfaces:**
- Consumes: nada.
- Produces: nada.

**Contexto:** Os três scripts JS mutam `frontend/src/app/globals.css` **in-place** e já foram executados. `fix_css.js` remove os wrappers `oklch(...)`; `revert_css.js` os recoloca — são mutuamente contraditórios. Executar qualquer um hoje corrompe o CSS atual. `form.json` tem 0 bytes.

- [ ] **Step 1: Confirmar que form.json está vazio e que os scripts não são referenciados**

```powershell
(Get-Item frontend\form.json).Length
Select-String -Path frontend\package.json,frontend\Dockerfile -Pattern "fix_css|revert_css|fix_opacity|form.json"
```

Esperado: tamanho `0`, e **nenhuma saída** do Select-String. Se algum script estiver referenciado no `package.json` (scripts npm) ou no Dockerfile, PARE e reporte.

- [ ] **Step 2: Deletar os quatro arquivos**

```powershell
git rm frontend/fix_css.js frontend/revert_css.js frontend/fix_opacity.js frontend/form.json
```

- [ ] **Step 3: Mover o backfill para scripts/**

```powershell
git mv backfill_contacts.py scripts/backfill_contacts.py
```

Não editar o conteúdo: os imports já são absolutos (`from app.database import ...`), e `scripts/__init__.py` já existe.

- [ ] **Step 4: Confirmar que o app ainda importa e o script é válido**

```powershell
venv\Scripts\python -c "import app.main; print('OK')"
venv\Scripts\python -c "import ast,pathlib; ast.parse(pathlib.Path('scripts/backfill_contacts.py').read_text(encoding='utf-8')); print('OK')"
```

Esperado: `OK` nas duas.

- [ ] **Step 5: Suíte continua verde**

```powershell
venv\Scripts\python -m pytest tests/ -q
```

Esperado: **200 passed**.

- [ ] **Step 6: Commit**

```powershell
git add -A
git commit -m "chore: remove scripts one-off de CSS e move backfill_contacts para scripts/"
```

---

### Task 3: Criar app/services/takeover.py com testes (TDD)

**Files:**
- Create: `app/services/takeover.py`
- Test: `tests/test_takeover.py`

**Interfaces:**
- Consumes: `app.models.contact.Contact`.
- Produces — usado pelas Tarefas 4:
  - `in_human_takeover(contact: Contact, now: datetime) -> bool`
  - `not_in_human_takeover_clause(now: datetime)` → predicado SQLAlchemy (`BooleanClauseList`), usável dentro de `.where(...)`

**Contexto:** A mesma regra está hoje em três lugares: `webhooks.py:70` (função), `followups.py:163` (função) e `webhooks.py:1190-1193` (predicado SQL no recovery sweep, cujo comentário já admite a duplicação). Este módulo passa a ser a única fonte.

**Detalhe crítico:** a função **precisa** usar `getattr(contact, "human_takeover_until", None)` e não acesso direto ao atributo. O teste existente `tests/test_human_takeover.py:51` passa um `SimpleNamespace()` sem o campo, e não pode explodir.

- [ ] **Step 1: Escrever os testes que falham**

Criar `tests/test_takeover.py`:

```python
"""
Testes da fonte única da janela de atendimento humano
(app/services/takeover.py). Puros — sem DB, sem rede, sem Gemini.

A regra vive em duas formas que precisam concordar: a função Python
(decisão por contato) e o predicado SQLAlchemy (filtro em query agregada,
usado pelo recovery sweep).
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.takeover import in_human_takeover, not_in_human_takeover_clause


def _now() -> datetime:
    return datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc)


class TestInHumanTakeover:
    def test_true_while_the_window_is_open(self):
        now = _now()
        contact = SimpleNamespace(human_takeover_until=now + timedelta(minutes=30))
        assert in_human_takeover(contact, now) is True

    def test_false_once_the_window_expired(self):
        now = _now()
        contact = SimpleNamespace(human_takeover_until=now - timedelta(minutes=1))
        assert in_human_takeover(contact, now) is False

    def test_false_exactly_at_the_boundary(self):
        # Comparação estrita (until > now): no instante exato do vencimento a
        # janela já está fechada e a Sofia volta a responder.
        now = _now()
        contact = SimpleNamespace(human_takeover_until=now)
        assert in_human_takeover(contact, now) is False

    def test_false_when_never_set(self):
        contact = SimpleNamespace(human_takeover_until=None)
        assert in_human_takeover(contact, _now()) is False

    def test_false_when_the_attribute_is_missing(self):
        # Dublês de teste podem não declarar o campo — não pode levantar.
        assert in_human_takeover(SimpleNamespace(), _now()) is False


class TestNotInHumanTakeoverClause:
    def test_covers_both_cases_the_python_form_accepts(self):
        # O predicado é o complemento da função: passa quem nunca teve janela
        # (NULL) e quem já venceu (<= now).
        compiled = str(not_in_human_takeover_clause(_now()))
        assert "human_takeover_until IS NULL" in compiled
        assert "human_takeover_until <=" in compiled

    def test_is_an_or_of_exactly_two_conditions(self):
        compiled = str(not_in_human_takeover_clause(_now()))
        assert " OR " in compiled
```

- [ ] **Step 2: Rodar e confirmar que falha**

```powershell
venv\Scripts\python -m pytest tests/test_takeover.py -q
```

Esperado: **FAIL** com `ModuleNotFoundError: No module named 'app.services.takeover'`.

- [ ] **Step 3: Implementar o módulo**

Criar `app/services/takeover.py`:

```python
"""
Fonte única da regra de "janela de atendimento humano" (item D4).

Quando alguém da equipe responde um paciente direto do próprio celular /
WhatsApp Web (evento com fromMe=true e wasSentByApi=false),
`Contact.human_takeover_until` recebe `now + HUMAN_TAKEOVER_PAUSE_MINUTES`.
Enquanto essa janela está aberta a Sofia não responde, e nenhum disparo
proativo (lembrete / reengajamento) sai para esse contato.

Distinta de `Contact.ai_paused`: esta janela EXPIRA sozinha assim que "now"
ultrapassa o timestamp — não existe ação de "despausar". Já `ai_paused` fica
até alguém da equipe limpar manualmente no Inbox.

Este módulo existe porque a mesma regra estava expressa em três lugares
(app/api/v1/routes/webhooks.py duas vezes — uma função e um predicado SQL — e
app/services/followups.py). Manter as duas formas lado a lado aqui faz de
qualquer mudança de semântica uma edição visível de duas linhas adjacentes,
em vez de três edições espalhadas que nada obriga a acontecer juntas.
"""

from datetime import datetime

from sqlalchemy import or_

from app.models.contact import Contact


def in_human_takeover(contact: Contact, now: datetime) -> bool:
    """
    True enquanto a equipe está atendendo este contato à mão.

    `now` é injetado (em vez de chamado aqui dentro) porque as guardas de
    disparo proativo em app/services/followups.py precisam avaliar a regra
    num instante controlado para testar fuso horário.

    O `getattr` defensivo é proposital: chamadores de teste passam dublês
    que podem não declarar o campo.
    """
    until = getattr(contact, "human_takeover_until", None)
    return until is not None and until > now


def not_in_human_takeover_clause(now: datetime):
    """
    A mesma regra, negada, como predicado SQLAlchemy — para queries agregadas
    que precisam filtrar contatos sem carregar cada um em Python (o recovery
    sweep roda como uma query só, não por contato).

    Deve permanecer o complemento exato de `in_human_takeover`: passa quem
    nunca teve janela (NULL) e quem já venceu (<= now).
    """
    return or_(
        Contact.human_takeover_until.is_(None),
        Contact.human_takeover_until <= now,
    )
```

- [ ] **Step 4: Rodar e confirmar que passa**

```powershell
venv\Scripts\python -m pytest tests/test_takeover.py -q
```

Esperado: **7 passed**.

- [ ] **Step 5: Suíte inteira continua verde**

```powershell
venv\Scripts\python -m pytest tests/ -q
```

Esperado: **207 passed** (200 do baseline + 7 novos).

- [ ] **Step 6: Commit**

```powershell
git add app/services/takeover.py tests/test_takeover.py
git commit -m "feat(takeover): fonte unica da regra de janela de atendimento humano"
```

---

### Task 4: Migrar os cinco call sites para takeover.py

**Files:**
- Modify: `app/api/v1/routes/webhooks.py` (remover def na linha 70; call sites 569, 923, 1190-1193)
- Modify: `app/services/followups.py` (remover def na linha 163; call sites 191, 354)
- Modify: `tests/test_human_takeover.py` (4 testes puros, linhas ~32-53)
- Modify: `tests/test_followups_guards.py` (import)

**Interfaces:**
- Consumes da Tarefa 3: `in_human_takeover(contact, now)` e `not_in_human_takeover_clause(now)`.
- Produces: nada de novo.

**Contexto:** `datetime` e `timezone` já estão importados nos dois arquivos de produção. `or_` já está importado em `webhooks.py` — só remover do import se não sobrar outro uso.

- [ ] **Step 1: webhooks.py — adicionar o import**

Adicionar junto aos outros imports `from app.services...` no topo de `app/api/v1/routes/webhooks.py`:

```python
from app.services.takeover import in_human_takeover, not_in_human_takeover_clause
```

- [ ] **Step 2: webhooks.py — remover a definição local**

Apagar a função inteira em `app/api/v1/routes/webhooks.py` linha ~70, incluindo docstring:

```python
def _in_human_takeover(contact: Contact) -> bool:
    """
    True while a staff member is actively replying to this contact by hand
    ...
    """
    until = getattr(contact, "human_takeover_until", None)
    return until is not None and until > datetime.now(timezone.utc)
```

- [ ] **Step 3: webhooks.py — migrar o call site da linha ~569**

De:

```python
                human_takeover = _in_human_takeover(contact)
```

Para:

```python
                human_takeover = in_human_takeover(contact, datetime.now(timezone.utc))
```

- [ ] **Step 4: webhooks.py — migrar o call site da linha ~923**

De:

```python
            if _in_human_takeover(contact):
```

Para:

```python
            if in_human_takeover(contact, datetime.now(timezone.utc)):
```

Preservar intacto o comentário logo abaixo (explica por que a re-checagem tardia importa).

- [ ] **Step 5: webhooks.py — migrar o predicado SQL (linhas ~1186-1193)**

De:

```python
                    # Item D4: don't resurrect a reply for a contact a human
                    # is currently handling by hand — same intent as
                    # `_in_human_takeover`, expressed as a SQL predicate since
                    # this runs as one aggregate query, not per-contact.
                    or_(
                        Contact.human_takeover_until.is_(None),
                        Contact.human_takeover_until <= now,
                    ),
```

Para:

```python
                    # Item D4: não ressuscitar resposta para contato que um
                    # humano está atendendo agora. Mesma regra de
                    # in_human_takeover, na forma SQL — este sweep roda como
                    # uma query agregada, não por contato.
                    not_in_human_takeover_clause(now),
```

- [ ] **Step 6: webhooks.py — remover o import de `or_`, que fica órfão**

Verificado na análise: `or_(` tinha exatamente **um** uso no arquivo, o predicado substituído no Step 5. Confirmar e remover:

```powershell
Select-String -Path app\api\v1\routes\webhooks.py -Pattern "or_\("
```

Esperado: **nenhuma saída**. Então alterar:

```python
from sqlalchemy import desc, func, or_, select
```

para:

```python
from sqlalchemy import desc, func, select
```

Se, contra o esperado, ainda houver algum uso, deixar o import como está e seguir.

- [ ] **Step 7: followups.py — adicionar import e remover a definição local**

Adicionar aos imports de `app/services/followups.py`:

```python
from app.services.takeover import in_human_takeover
```

Apagar a definição na linha ~163:

```python
def _in_human_takeover(contact: Contact, now: datetime) -> bool:
    """Staff are handling this contact by hand right now (see
    Contact.human_takeover_until / webhooks._process_human_outbound_message)."""
    until = getattr(contact, "human_takeover_until", None)
    return until is not None and until > now
```

- [ ] **Step 8: followups.py — migrar os dois call sites**

Linha ~191, de `if _in_human_takeover(contact, now):` para `if in_human_takeover(contact, now):`

Linha ~354, de `if _in_human_takeover(contact, now):` para `if in_human_takeover(contact, now):`

(`now` já está em escopo nos dois pontos — só cai o underscore.)

- [ ] **Step 9: Atualizar os 4 testes puros em tests/test_human_takeover.py**

Substituir o bloco de testes puros (linhas ~32-53) por:

```python
# ---------------------------------------------------------------------------
# in_human_takeover — predicado puro (agora em app/services/takeover.py)
# ---------------------------------------------------------------------------

def test_in_human_takeover_true_when_timestamp_is_in_the_future():
    contact = SimpleNamespace(
        human_takeover_until=datetime.now(timezone.utc) + timedelta(minutes=30)
    )
    assert in_human_takeover(contact, datetime.now(timezone.utc)) is True


def test_in_human_takeover_false_when_timestamp_is_in_the_past():
    contact = SimpleNamespace(
        human_takeover_until=datetime.now(timezone.utc) - timedelta(minutes=1)
    )
    assert in_human_takeover(contact, datetime.now(timezone.utc)) is False


def test_in_human_takeover_false_when_none():
    assert in_human_takeover(
        SimpleNamespace(human_takeover_until=None), datetime.now(timezone.utc)
    ) is False


def test_in_human_takeover_false_when_attribute_missing():
    assert in_human_takeover(SimpleNamespace(), datetime.now(timezone.utc)) is False
```

Adicionar aos imports do arquivo:

```python
from app.services.takeover import in_human_takeover
```

Conferir que `datetime`, `timezone`, `timedelta` e `SimpleNamespace` já estão importados; se algum faltar, acrescentar. **Não alterar** o resto do arquivo — em especial `test_generate_and_send_skips_when_in_human_takeover` (linha ~175), que testa integração e deve continuar como está.

- [ ] **Step 10: Ajustar tests/test_followups_guards.py se ele importa a função antiga**

```powershell
Select-String -Path tests\test_followups_guards.py -Pattern "_in_human_takeover"
```

Se houver saída, trocar para `in_human_takeover` importado de `app.services.takeover`. Se não houver (o arquivo testa `can_send_proactive`, que é a API pública), **não mexer no arquivo**.

- [ ] **Step 11: Confirmar que não sobrou nenhuma referência ao nome antigo**

```powershell
Select-String -Path (Get-ChildItem app,tests -Recurse -Include *.py).FullName -Pattern "_in_human_takeover"
```

Esperado: **nenhuma saída**.

- [ ] **Step 12: Suíte verde**

```powershell
venv\Scripts\python -m pytest tests/ -q
venv\Scripts\python -c "import app.main; print('OK')"
```

Esperado: **207 passed** e `OK`.

- [ ] **Step 13: Commit**

```powershell
git add app/api/v1/routes/webhooks.py app/services/followups.py tests/
git commit -m "refactor(takeover): tres expressoes da mesma regra passam a usar takeover.py"
```

---

### Task 5: Parametrizar run_specialist_loop e logar "resposta pronta"

**Files:**
- Modify: `app/services/agents/base.py:78-224`

**Interfaces:**
- Consumes: nada de tarefas anteriores.
- Produces — usado pela Tarefa 6: `run_specialist_loop(..., max_iterations: int = SPECIALIST_MAX_TOOL_ITERATIONS) -> AgentReply`. Novo parâmetro **keyword-only com default**, então os 3 chamadores existentes (`orchestrator.py:135`, `ai.py:694`, e 4 call sites em `tests/test_agents_base.py`) continuam funcionando sem alteração.

**Contexto:** Hoje o loop é fixo em `SPECIALIST_MAX_TOOL_ITERATIONS = 4`. O legacy precisa de 8 (`MAX_TOOL_ITERATIONS`). E hoje o loop compartilhado não loga nada ao devolver texto puro, enquanto o legacy loga `gemini_reply_ready` — a linha de log mais útil do sistema. Movida para cá, os três caminhos passam a ter.

- [ ] **Step 1: Adicionar o parâmetro max_iterations**

Em `app/services/agents/base.py`, na assinatura de `run_specialist_loop`, acrescentar após `ai_cfg: dict`:

```python
    max_iterations: int = SPECIALIST_MAX_TOOL_ITERATIONS,
```

- [ ] **Step 2: Usar o parâmetro no loop e no log de esgotamento**

Trocar:

```python
    for iteration in range(SPECIALIST_MAX_TOOL_ITERATIONS):
```

por:

```python
    for iteration in range(max_iterations):
```

E no log de loop esgotado, trocar:

```python
            "max_iterations": SPECIALIST_MAX_TOOL_ITERATIONS,
```

por:

```python
            "max_iterations": max_iterations,
```

- [ ] **Step 3: Logar quando a resposta em texto puro fica pronta**

Trocar:

```python
        if function_call_part is None:
            reply = response.text or ""
            return AgentReply(text=reply, model=model)
```

por:

```python
        if function_call_part is None:
            reply = response.text or ""
            logger.info(
                "agent_reply_ready",
                extra={
                    "model": model,
                    "iterations": iteration + 1,
                    "tenant_id": str(tenant.id),
                    "contact_id": str(contact.id),
                    "reply_length": len(reply),
                },
            )
            return AgentReply(text=reply, model=model)
```

- [ ] **Step 4: Logar a resposta final forçada**

Trocar:

```python
        forced_reply = (final_response.text or "").strip()
        if forced_reply:
            return AgentReply(text=forced_reply, model=model)
```

por:

```python
        forced_reply = (final_response.text or "").strip()
        if forced_reply:
            logger.info(
                "agent_forced_final_reply",
                extra={
                    "model": model,
                    "tenant_id": str(tenant.id),
                    "contact_id": str(contact.id),
                    "reply_length": len(forced_reply),
                },
            )
            return AgentReply(text=forced_reply, model=model)
```

- [ ] **Step 5: Preservar a explicação do thinking_budget**

`run_specialist_loop` monta o `GenerateContentConfig` com `thinking_config=types.ThinkingConfig(thinking_budget=0)` sem explicar por quê. A explicação existe hoje só no config do caminho legacy, que a Tarefa 6 vai apagar — então ela precisa mudar de casa antes.

Em `app/services/agents/base.py`, na construção do `config` dentro de `run_specialist_loop`, trocar:

```python
        thinking_config=types.ThinkingConfig(thinking_budget=0),
```

por:

```python
        # Desliga o "thinking": gemini-2.5-flash pensa por padrão, e esses
        # tokens contam contra max_output_tokens. Em turnos com function call
        # isso podia queimar o orçamento inteiro antes de emitir qualquer part,
        # resultando em finish_reason=MAX_TOKENS sem conteúdo. Uma secretária de
        # WhatsApp fazendo tool call não precisa de raciocínio estendido —
        # desligar deixa as respostas mais rápidas e evita esse modo de falha.
        thinking_config=types.ThinkingConfig(thinking_budget=0),
```

- [ ] **Step 6: Atualizar o docstring da constante**

O comentário acima de `SPECIALIST_MAX_TOOL_ITERATIONS` (linha ~38) diz que o valor é menor que o do legacy "de propósito". Acrescentar uma frase esclarecendo que agora é apenas o **default**, e que o caminho legacy passa o seu próprio valor:

```python
# Cada specialist tem domínio mais estreito que o agente monolítico legacy, então
# precisa de menos iterações para resolver um turno. Menor que
# app.services.ai.MAX_TOOL_ITERATIONS (8) de propósito — um specialist iterando
# tanto sem resposta final já é sinal de que algo está errado (agente errado para
# o turno, ou tool devolvendo algo que ele não consegue interpretar).
# É o DEFAULT de run_specialist_loop: o caminho legacy passa max_iterations=8
# explicitamente para preservar seu comportamento histórico.
SPECIALIST_MAX_TOOL_ITERATIONS = 4
```

- [ ] **Step 7: Suíte verde — os chamadores existentes não podem quebrar**

```powershell
venv\Scripts\python -m pytest tests/test_agents_base.py tests/test_agents_orchestrator.py tests/test_staff_suggestion.py -q
venv\Scripts\python -m pytest tests/ -q
```

Esperado: **207 passed**.

- [ ] **Step 8: Commit**

```powershell
git add app/services/agents/base.py
git commit -m "refactor(agents): run_specialist_loop aceita max_iterations e loga resposta pronta"
```

---

### Task 6: _legacy_generate_reply delega para o loop compartilhado

**Files:**
- Modify: `app/services/ai.py` (corpo de `_legacy_generate_reply`, aproximadamente linhas 449-605)

**Interfaces:**
- Consumes da Tarefa 5: `run_specialist_loop(..., max_iterations=...)` → `AgentReply(text: str, model: str)`.
- Produces: `_legacy_generate_reply` continua devolvendo `tuple[str, str]` — assinatura pública **inalterada**.

**Contexto:** Os dois loops são o mesmo — o próprio docstring de `base.py` diz *"Mirrors app.services.ai._legacy_generate_reply's loop shape"*. Inclui duas strings ao paciente duplicadas literalmente. O import precisa ser **dentro da função**: `agents/base.py` importa `_generate_content_with_retry` de `ai.py` no nível de módulo, então um import no topo criaria ciclo. É o mesmo truque que `generate_staff_suggestion` já usa neste arquivo.

- [ ] **Step 1: Substituir o config local + o loop inteiro pela delegação**

Em `app/services/ai.py`, apagar TUDO desde a linha `config = types.GenerateContentConfig(` (linha ~435) até o `return` final da função (linha ~605, `return "Desculpe, não consegui processar sua solicitação no momento. Tente novamente.", model`), e colocar no lugar o bloco abaixo.

**Atenção ao ponto de início:** o `config` local (linhas ~435-447) também precisa sair. `run_specialist_loop` monta o seu próprio `GenerateContentConfig` internamente, então deixar esse bloco para trás cria uma variável morta. O comentário sobre `thinking_budget` que vive nele já foi migrado para `base.py` na Tarefa 5, Step 5 — confirme que a migração aconteceu antes de apagar aqui.

Bloco novo:

```python
    # Um único loop de tool-calling para todos os caminhos (legacy, specialists
    # e o copiloto "Sugerir resposta"). Import tardio de propósito:
    # agents/base.py importa _generate_content_with_retry deste módulo no nível
    # de módulo, então importar no topo criaria ciclo — mesmo truque usado em
    # generate_staff_suggestion.
    from app.services.agents.base import run_specialist_loop

    reply = await run_specialist_loop(
        client=client,
        model=model,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        system_prompt=system_prompt,
        tools=CLINIC_TOOLS,
        # O caminho legacy declara TODAS as tools, então o gate de allowlist é
        # no-op aqui. Derivado da própria declaração para nunca virar uma lista
        # literal que possa dessincronizar de CLINIC_TOOLS.
        allowed_tool_names={d.name for d in CLINIC_TOOLS.function_declarations},
        contents=contents,
        db=db,
        tenant=tenant,
        contact=contact,
        ai_cfg=ai_cfg,
        max_iterations=MAX_TOOL_ITERATIONS,
    )
    return reply.text, reply.model
```

**Preservar acima disso, sem tocar:** a normalização de `media`, a montagem de `system_prompt`, o log `ai_prompt_composed`, e a chamada a `build_conversation_contents`. A substituição começa só no loop.

- [ ] **Step 2: Atualizar o docstring da função**

No docstring de `_legacy_generate_reply`, trocar a frase que diz "one big prompt + all 12 tools declared, one tool-calling loop" por:

```
    Single-agent path (pre-Wave-3): um prompt único com as 11 tools de
    CLINIC_TOOLS declaradas. O loop de tool-calling em si é o compartilhado
    (app/services/agents/base.py::run_specialist_loop), com max_iterations=8;
    o que distingue este caminho é o prompt monolítico e o conjunto completo
    de tools, não um loop próprio.
```

- [ ] **Step 3: Limpar o import de `execute_tool`, que fica órfão**

Verificado na análise: `execute_tool` só aparece em `ai.py` no import (linha 48) e dentro do loop que acabou de ser apagado. Depois desta tarefa fica sem nenhum uso.

```powershell
Select-String -Path app\services\ai.py -Pattern "execute_tool"
```

Se a **única** saída for a linha do import, alterar:

```python
from app.services.ai_tools import CLINIC_TOOLS, execute_tool, _clinic_tz, _fmt_local
```

para:

```python
from app.services.ai_tools import CLINIC_TOOLS, _clinic_tz, _fmt_local
```

**Não remover `types`:** continua sendo usado fora do loop (`build_conversation_contents`, `generate_followup_message`, a anotação de tipo em `_generate_content_with_retry`). **Não remover `MAX_TOOL_ITERATIONS`:** passa a ser usado na chamada nova.

```powershell
Select-String -Path app\services\ai.py -Pattern "MAX_TOOL_ITERATIONS"
```

Esperado: a definição (linha ~53) e o uso novo dentro de `_legacy_generate_reply`.

- [ ] **Step 4: App importa e suíte verde**

```powershell
venv\Scripts\python -c "import app.main; print('OK')"
venv\Scripts\python -m pytest tests/ -q
```

Esperado: `OK` e **207 passed**.

- [ ] **Step 5: Rodar especificamente os testes do caminho de IA**

```powershell
venv\Scripts\python -m pytest tests/test_ai_retry.py tests/test_multi_agent_toggle.py tests/test_staff_suggestion.py tests/test_media_history_guard.py tests/test_history_markers.py -q
```

Esperado: todos passando.

- [ ] **Step 6: Commit**

```powershell
git add app/services/ai.py
git commit -m "refactor(ai): caminho legacy delega para o loop de tool-calling compartilhado"
```

---

### Task 7: Corrigir o registro de eventos de log

**Files:**
- Modify: `app/core/logging.py` (dicionário `_EVENT_STYLE`, linhas ~91-113)

**Interfaces:**
- Consumes: os slugs `agent_*` que a Tarefa 5 garantiu que são emitidos.
- Produces: nada.

**Contexto:** Três problemas no registro atual. (1) `human_handoff_requested` não tem emissor nenhum — resto do handoff removido, e o rótulo "TRANSFERIDO para humano" descreve comportamento que o `CLAUDE.md` declara inexistente. (2) A chave `gemini_call_failed` **nunca casou**: o evento emitido em `ai.py:348` é `gemini_call_failed_will_retry`. (3) A família `agent_*` nunca foi registrada, então o caminho multi-agente sempre logou sem rótulo amigável — e depois da Tarefa 6 o legacy passa a usar essa família.

- [ ] **Step 1: Confirmar quais slugs realmente são emitidos agora**

```powershell
Select-String -Path (Get-ChildItem app -Recurse -Include *.py).FullName -Pattern 'logger\.(info|warning|error|exception)\(\s*"([a-z_]+)"' | ForEach-Object { $_.Matches[0].Groups[2].Value } | Sort-Object -Unique
```

Usar essa lista como verdade. Nenhuma chave de `_EVENT_STYLE` deve ficar sem emissor correspondente.

- [ ] **Step 2: Aplicar as mudanças no _EVENT_STYLE**

Em `app/core/logging.py`, **remover** estas seis entradas:

```python
    "human_handoff_requested": ("🙋", "TRANSFERIDO para humano"),
    "gemini_reply_ready": ("🤖", "resposta gerada"),
    "gemini_forced_final_reply": ("🤖", "resposta gerada (final)"),
    "ai_tool_executed": ("🔧", "ferramenta usada"),
    "gemini_empty_parts": ("⚠️", "modelo retornou vazio"),
    "gemini_tool_loop_exhausted": ("🔁", "loop de ferramentas esgotado"),
```

E **substituir** a entrada quebrada:

```python
    "gemini_call_failed": ("💥", "falha na chamada ao modelo"),
```

**Acrescentar** no lugar, mantendo o agrupamento visual do dicionário:

```python
    # Loop de tool-calling compartilhado (legacy, specialists e copiloto)
    "agent_reply_ready": ("🤖", "resposta gerada"),
    "agent_forced_final_reply": ("🤖", "resposta gerada (final)"),
    "agent_tool_executed": ("🔧", "ferramenta usada"),
    "agent_empty_parts": ("⚠️", "modelo retornou vazio"),
    "agent_tool_loop_exhausted": ("🔁", "loop de ferramentas esgotado"),
    "agent_tool_not_allowed": ("🚫", "ferramenta bloqueada"),
    # Chamada ao Gemini (fora do loop)
    "gemini_call_failed_will_retry": ("💥", "falha na chamada ao modelo"),
    "gemini_call_exhausted": ("💥", "modelo falhou em todas as tentativas"),
```

- [ ] **Step 3: Verificar que toda chave registrada tem emissor de verdade**

Gravar `scripts/_check_log_events.py` (temporário, apagado no Step 4):

```python
"""Confere que toda chave de _EVENT_STYLE é realmente emitida por algum
logger.<level>("slug") em app/. Entrada sem emissor é rótulo morto."""

import pathlib
import re

root = pathlib.Path("app")
logging_py = root / "core" / "logging.py"

registered = set(
    re.findall(r'^\s+"([a-z_]+)":\s*\(', logging_py.read_text(encoding="utf-8"), re.M)
)

emitted = set()
for path in root.rglob("*.py"):
    if path == logging_py:
        continue
    emitted |= set(
        re.findall(
            r'logger\.(?:info|warning|error|exception|debug)\(\s*"([a-z_]+)"',
            path.read_text(encoding="utf-8"),
        )
    )

# request_completed vem do middleware de acesso HTTP, emitido por outro caminho.
orphans = sorted(registered - emitted - {"request_completed"})
unlabeled = sorted(emitted - registered)

print("chaves registradas sem emissor:", orphans)
print("eventos emitidos sem rotulo (ok, so informativo):", len(unlabeled))
```

Rodar:

```powershell
venv\Scripts\python scripts\_check_log_events.py
```

Esperado: `chaves registradas sem emissor: []`. Se listar qualquer slug, é entrada morta — remover ou corrigir a chave antes de seguir.

- [ ] **Step 4: Apagar o script temporário**

```powershell
Remove-Item scripts\_check_log_events.py
```

- [ ] **Step 5: Suíte verde e app importa**

```powershell
venv\Scripts\python -c "import app.main; print('OK')"
venv\Scripts\python -m pytest tests/ -q
```

Esperado: `OK` e **207 passed**.

- [ ] **Step 6: Commit**

```powershell
git status --short
git add app/core/logging.py
git commit -m "fix(logging): remove eventos mortos, corrige chave que nunca casava e registra familia agent_*"
```

`git status` antes do commit é para confirmar que o script temporário do Step 3 foi mesmo apagado e não vai junto.

---

### Task 8: Arquivar documentação solta e atualizar CLAUDE.md

**Files:**
- Create: `docs/archive/` (destino dos arquivos movidos)
- Modify: `.gitignore`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: nada.
- Produces: nada.

**Contexto:** ~750 KB de material de trabalho na raiz, todos **não rastreados** no git. Arquivar em vez de deletar: sem histórico no git, uma deleção seria irrecuperável.

- [ ] **Step 1: Confirmar que os alvos são mesmo não rastreados**

```powershell
git status --short
```

Esperado: os arquivos abaixo aparecem com `??`. Se algum aparecer como rastreado (`M`/`A`), PARE e reporte.

- [ ] **Step 2: Criar o destino e mover**

```powershell
New-Item -ItemType Directory -Force -Path docs\archive | Out-Null
Move-Item -Path z.html,zz.html,SOFIA_DOCUMENTACAO_COMPLETA.md,SOFIA_TESTE_AGENDA.md,SOFIA_TESTE_CONVERSA.md,PLANO_EXECUCAO.md,GEMINI_PROMPT_REDESIGN.md,GEMINI_PROMPT_SETTINGS_REFINE.md,FABLE_PROMPT_PLANO_SOFIA.md,prompt-ated.md,claude_prompt_wave3.md,scratch -Destination docs\archive -Force
Get-ChildItem docs\archive
```

Esperado: os 12 itens listados no destino.

- [ ] **Step 3: Atualizar o .gitignore**

Acrescentar ao final de `.gitignore`:

```
# Documentação arquivada (material de trabalho, não versionado)
docs/archive/

# Artefato gerado pelo graphify
graphify-out/
```

- [ ] **Step 4: Confirmar que a raiz ficou limpa e nada rastreado sumiu**

```powershell
git status --short
```

Esperado: apenas `.gitignore` modificado (`M`) e `docs/superpowers/` já commitado. Nenhum `D` de arquivo rastreado.

- [ ] **Step 5: Atualizar o CLAUDE.md**

Três edições na seção `### AI (Sofia)`:

1. Onde o texto descreve os dois caminhos de geração, acrescentar ao final do parágrafo **Two generation paths, one prompt**:

```
Both paths run the SAME tool-calling loop: `app/services/agents/base.py::run_specialist_loop`, parameterized by `system_prompt`/`tools`/`allowed_tool_names`/`max_iterations` (legacy passes 8, specialists default to 4). The staff "Sugerir resposta" copilot is the third caller. Before this, `_legacy_generate_reply` carried a hand-rolled copy of the same loop, down to two byte-identical patient-facing fallback strings — the same "two paraphrased copies, every fix made twice, one always forgotten" failure this file documents for the prompts.
```

2. Onde o texto diz "one big prompt + **all 12 tools** declared", corrigir para **11** — `CLINIC_TOOLS` declara 11 `FunctionDeclaration`.

3. Na seção que descreve `human_takeover_until` (dentro de **Human takeover auto-pause**), acrescentar:

```
The rule itself has ONE home: `app/services/takeover.py` — `in_human_takeover(contact, now)` for per-contact decisions and `not_in_human_takeover_clause(now)` for the recovery sweep's aggregate query. It used to be expressed three times (twice in `webhooks.py`, once in `followups.py`); keeping both forms adjacent makes a semantic change one visible edit instead of three.
```

- [ ] **Step 6: Verificação final completa**

```powershell
venv\Scripts\python -m pytest tests/ -q
venv\Scripts\python -c "import app.main; print('OK')"
cd frontend; npx tsc --noEmit; cd ..
```

Esperado: **207 passed**, `OK`, e type-check sem erros.

- [ ] **Step 7: Commit**

```powershell
git add .gitignore CLAUDE.md
git commit -m "docs: arquiva material de trabalho solto e atualiza CLAUDE.md"
```

---

## Verificação final (após todas as tarefas)

- [ ] `venv\Scripts\python -m pytest tests/ -q` → **207 passed**
- [ ] `venv\Scripts\python -c "import app.main"` → OK
- [ ] `cd frontend && npx tsc --noEmit` → sem erros
- [ ] `cd frontend && npm run build` → build conclui
- [ ] `git status --short` → árvore limpa
- [ ] Suíte de integração, **se o Docker estiver disponível**:
      `docker compose up -d` e `venv\Scripts\python -m pytest tests/integration -q`.
      Se o Docker não estiver disponível no ambiente, reportar como não executada —
      não marcar como passando.

## Dívida técnica registrada (fora do escopo)

1. `app/services/ai_tools.py` — ~1900 linhas com quatro responsabilidades: declarações de tools, motor de agenda `capacity`, motor `per_professional` (`_check_availability_pp` / `_create_appointment_pp` / `_reschedule_appointment_pp` são implementações paralelas das mesmas três operações) e info da clínica/CRM.
2. `app/api/v1/routes/webhooks.py` — 1160 linhas numa rota, misturando validação de webhook, persistência, caps de uso de IA, presença/typing e o pipeline de geração-e-envio.

Revisitar depois do lançamento, cada um com seu próprio ciclo de spec → plano.
