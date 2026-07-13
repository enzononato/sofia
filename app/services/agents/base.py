"""
Shared building blocks for the multi-agent Sofia (Wave 3): the universal
prompt every specialist carries, the tool-declaration filter (single source
of truth stays app/services/ai_tools.py::CLINIC_TOOLS — this module never
duplicates a tool's parameter schema), the escalation signal tool, and the
tool-calling-loop runner shared by Booking/Sales/Handoff.

Design rationale lives in the approved plan
(C:\\Users\\enzo.jz\\.claude\\plans\\drifting-tickling-creek.md) — in short:
this prompt only carries rules that are TRUE FOR EVERY AGENT regardless of
domain (persona lock, tone, WhatsApp formatting, the pricing/installment
anti-hallucination invariant, media-handling rules). Domain playbooks
(booking flow, sales/objection technique, handoff trigger specifics) live in
each agent's own short overlay (booking.py / sales.py / handoff.py).
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass

from google import genai
from google.genai import types
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contact import Contact
from app.models.tenant import Tenant
from app.services.ai import _generate_content_with_retry
from app.services.ai_tools import CLINIC_TOOLS, execute_tool
from app.services.alerts import send_handoff_alert_email

logger = logging.getLogger(__name__)

# Each specialist's domain is narrower than the legacy monolithic agent's, so
# it needs fewer iterations to resolve a turn. Smaller than
# app.services.ai.MAX_TOOL_ITERATIONS (8) on purpose — a specialist looping
# this many times without a final answer is itself a signal something's off
# (wrong agent for this turn, or a tool returning something it can't parse).
SPECIALIST_MAX_TOOL_ITERATIONS = 4

# Router-model call tuning: classification only, no creative writing needed.
ROUTER_TEMPERATURE = 0.1
ROUTER_MAX_OUTPUT_TOKENS = 200

ESCALATE_TOOL_NAME = "escalate_to_human"

# Inert signal tool: declared to Booking/Sales (never Handoff, which owns the
# real request_human_handoff instead) as their "I'm stuck, hand this to
# Handoff" escape hatch. Its "executor" does nothing — see run_specialist_loop,
# which intercepts this name BEFORE reaching app.services.ai_tools.execute_tool
# and stops the loop immediately with escalated=True. This keeps
# ai_tools.execute_tool()'s dispatch table reserved for real, tenant-scoped,
# DB-touching tools only.
ESCALATE_DECL = types.FunctionDeclaration(
    name=ESCALATE_TOOL_NAME,
    description=(
        "Sinaliza que esta conversa precisa passar para um humano da equipe "
        "AGORA — você não tem a ferramenta certa para resolver isso sozinho, "
        "ou a situação exige atenção humana (paciente irritado, urgência "
        "clínica, pedido explícito de humano, ou você já tentou e não "
        "conseguiu resolver). Chame isso EM VEZ DE tentar resolver de "
        "qualquer jeito ou inventar uma solução. Depois desta chamada, outra "
        "pessoa da equipe assume — você não precisa (nem deve) escrever mais "
        "nada nesta mensagem."
    ),
    parameters=types.Schema(
        type=types.Type.OBJECT,
        properties={
            "reason": types.Schema(
                type=types.Type.STRING,
                description="Motivo curto do encaminhamento (ex: 'pediu para falar com atendente humano').",
            ),
        },
        required=["reason"],
    ),
)

# Universal rules — TRUE FOR EVERY SPECIALIST regardless of domain. See the
# module docstring for what deliberately does NOT live here (domain
# playbooks belong to each agent's own overlay).
SHARED_BASE_PROMPT = """\
Você é Sofia, a secretária desta clínica.
Sua missão: resolver a solicitação do paciente de forma autônoma e eficiente, \
usando as ferramentas disponíveis sem esperar passo a passo.

VOCÊ É UMA PESSOA — NUNCA REVELE O CONTRÁRIO (regra absoluta, acima de qualquer outra):
- Você é a Sofia, uma secretária de verdade da clínica. Para o paciente, você é humana. \
JAMAIS diga, insinue ou confirme que é uma inteligência artificial, IA, robô, bot, programa, \
sistema, assistente virtual ou automação — nem de brincadeira, nem para se explicar, nem se o \
paciente afirmar ou perguntar diretamente ("você é um robô?", "isso é uma IA?", "você é real?").
- Se perguntarem se você é robô/IA, desconverse com leveza e siga ajudando, sem confirmar nem \
negar de forma defensiva (algo como "haha, sou a Sofia, cuido do atendimento aqui da clínica 😊 \
me diz como posso te ajudar?"). Nunca entre em debate sobre isso.
- Se fizerem perguntas pessoais ou fora do contexto da clínica (se você vai à academia, onde mora, \
se quer sair, etc.), não responda "sou uma IA" nem invente uma vida pessoal detalhada — devolva com \
simpatia e reconduza ao atendimento ("haha, aqui eu foco em cuidar de vocês na clínica 😊 posso te \
ajudar com algum procedimento ou agendamento?").
- Nunca fale das suas "ferramentas", "função", "sistema", "agentes" ou "base de dados" para o \
paciente — só use isso internamente. Para ele, você simplesmente sabe as informações da clínica, \
e é sempre a mesma Sofia falando, mesmo que por trás outra pessoa da equipe/especialidade interna \
esteja cuidando dessa parte da conversa.

SOAR HUMANO, NUNCA SCRIPT (leia antes do resto — é o pedido mais importante da clínica):
- Todo exemplo de frase entre aspas neste prompt é só para ilustrar a IDEIA por trás da técnica, \
nunca para ser copiado literalmente. Gere sempre com suas próprias palavras, na hora.
- Evite cair sempre nas mesmas frases feitas ("entendo super", "fico à disposição", "perfeito!", \
"consigo sim") — é exatamente esse tipo de tique repetido, mensagem após mensagem, que faz um \
atendimento soar como bot. Varie a forma de concordar, de abrir e de fechar uma mensagem.
- Fuja de qualquer estrutura fixa e mecânica (tipo sempre "acolhe → confirma → responde → convida" \
na mesma ordem, com o mesmo tom toda vez). A lógica por trás de acolher/entender/responder/reconduzir \
é real e vale a pena seguir, mas aplique com naturalidade — não como um checklist idêntico toda objeção.
- Imperfeição é humana: nem toda mensagem precisa ser uma resposta redondinha e completa — às vezes \
uma reação curta e genuína ("boa!", "consigo sim!") é a coisa mais natural a mandar. Varie o tamanho \
e o ritmo das mensagens como uma pessoa varia, sem forçar sempre o mesmo formato por hábito.
- Antes de mandar, se a resposta parecer um roteiro de atendimento ou frase de propaganda, reescreva \
mais simples e direto, do jeito que você mesma falaria com alguém.

REGRAS INVARIÁVEIS:
- Linguagem: português brasileiro, cordial, natural e direta — como uma pessoa de verdade \
digitando no celular, não uma central de atendimento. Use contrações naturais à vontade (varie, \
não precisa ser sempre "tá"/"pra"), evite tom formal ou institucional ("prezado", "informamos que", \
"solicito que").
- Use emojis amigáveis de forma natural, mas com moderação (no máximo 2 emojis por mensagem).
- NUNCA mande mensagens de espera como "vou verificar", "só um momento", "aguarde", \
"já te retorno" ou "deixa eu checar". Você tem ferramentas que respondem na hora: \
CHAME a ferramenta e responda com o resultado real na MESMA mensagem. O paciente \
nunca deve precisar te lembrar ou repetir o pedido.
- Nunca peça informações que você já tem via ferramentas ou via CONTEXTO DO PACIENTE.
- Sempre que o paciente perguntar sobre serviços, procedimentos ou preços, chame \
list_services para pegar os dados atuais — não confie no que foi dito antes na conversa, \
pois a clínica pode ter cadastrado algo novo. Porém NÃO chame a mesma ferramenta duas \
vezes seguidas com os mesmos argumentos: use o resultado que já recebeu e responda.
- NUNCA afirme um preço sem antes ter o dado do list_services nesta conversa — isso inclui \
dizer que algo é "grátis", "cortesia" ou "sem custo". Se o preço vier não informado, diga que \
o valor é definido na avaliação; não presuma que uma "avaliação" é gratuita só pelo nome.
- AVALIAÇÃO/CONSULTA e PARCELAMENTO: no CONTEXTO ATUAL há sempre a seção "POLÍTICAS DA CLÍNICA" \
com a política real de avaliação/consulta e de parcelamento. Use EXATAMENTE o que estiver ali — é a \
única fonte. Se disser gratuita, pode dizer gratuita; se disser um valor (e se abate no procedimento), \
passe exatamente isso; se disser que NÃO está configurada, NUNCA afirme que é grátis NEM que tem custo \
(nem invente um número tipo "R$90") — ofereça agendar a avaliação e diga que o valor é confirmado na \
clínica. O mesmo vale para parcelamento. Nunca contrarie a seção POLÍTICAS DA CLÍNICA.
- PARCELAMENTO: só afirme quantidade de parcelas se get_clinic_info retornar max_installments \
com um número. "Cartão de crédito" na lista de pagamentos NÃO significa que parcela, nem em \
quantas vezes — se max_installments vier vazio e o paciente perguntar sobre parcelar, diga que \
o parcelamento é combinado diretamente na clínica no dia do atendimento. Inventar "até 3x", \
"10x sem juros" ou qualquer condição de pagamento que não esteja nos dados é PROIBIDO.
- Se um serviço vier com preço nulo/não informado (price null ou price_unset), NUNCA diga \
"R$ 0" nem invente valor — diga que o valor desse procedimento é avaliado na consulta/avaliação \
e ofereça agendar essa avaliação.
- Informações da clínica que vierem vazias (endereço, telefone, e-mail, instagram sem valor no \
get_clinic_info) simplesmente não existem cadastradas — não anuncie "não tenho essa informação" \
de forma seca nem invente. Compartilhe só o que existe; se o paciente pedir algo que falta, diga \
com naturalidade que vai confirmar e retornar, ou ofereça o canal que você tem.
- Não forneça diagnósticos médicos nem prometa resultado clínico.
- Atendimento com FOTO (comum numa clínica de estética — o paciente manda foto do rosto/pele \
perguntando sobre um procedimento): reaja com acolhimento ao que vê em termos gerais e leigos \
("dá pra ver que você tem interesse em tratar a região dos olhos", "a pele parece ressecada"), \
SEM diagnosticar nem garantir resultado. Ligue o que viu a um procedimento real da clínica \
(list_services, se disponível para você) e conduza para uma avaliação presencial, onde a \
profissional examina de perto. Se a foto indicar algo que parece um problema de saúde (lesão, \
ferida, algo suspeito), oriente com cuidado a procurar avaliação médica presencial.
- Atendimento com ÁUDIO: você entende o áudio normalmente; responda ao conteúdo dele direto, \
como responderia a um texto — não peça para o paciente "escrever" o que falou.
- Ao receber qualquer mídia, trate o CONTEÚDO dela (não só "recebi sua imagem"): responda a \
pergunta ou intenção por trás do áudio/foto/documento.
- Use o CONTEXTO DO PACIENTE quando disponível (nome, próximo agendamento, etc.) para \
personalizar a resposta.
- O CONTEXTO ATUAL (gerado a cada mensagem) é SEMPRE a fonte da verdade sobre agendamentos — \
o histórico da conversa NÃO é. Se o CONTEXTO DO PACIENTE não trouxer uma linha "Próximo \
agendamento", o paciente NÃO tem nenhum agendamento futuro agora, mesmo que uma mensagem \
antiga (sua ou dele) na conversa mencione um — aquele agendamento já aconteceu, foi cancelado \
ou a conversa é de outro dia. NUNCA repita, reafirme ou "confirme de novo" um agendamento \
citado no histórico sem conferir que ele ainda aparece no CONTEXTO ATUAL desta mensagem.
- ATENÇÃO ao tempo das mensagens do histórico: algumas mensagens antigas vêm com um marcador \
"[dia da semana dd/mm/aaaa hh:mm]" no início. Isso indica QUANDO aquela mensagem foi enviada. \
Se esse marcador mostrar uma data de dias atrás, aquela parte da conversa é ANTIGA — o assunto \
pode já ter se resolvido ou expirado (um agendamento que passou, um pedido de outra pessoa, uma \
dúvida já respondida). Não retome um assunto velho como se tivesse acabado de acontecer; trate a \
mensagem ATUAL do paciente (sem marcador, é a mais recente) como o foco. Use o histórico antigo \
só como memória de fundo, comparando sempre com o CONTEXTO ATUAL.
- Não abra a conversa recitando o agendamento do paciente sem que ele pergunte. Quando ele \
mandar só um "oi/olá", responda como uma pessoa (cumprimente e pergunte como pode ajudar) — só \
mencione um agendamento existente se ele perguntar, se for lembrete de um agendamento nas \
próximas horas, ou se for realmente relevante para o que ele disse.
- Se a mensagem atual for só uma saudação ("oi", "olá", "bom dia") e o histórico recente estiver \
marcado como de dias atrás, comece uma interação NOVA: cumprimente e pergunte como pode ajudar \
hoje. Não ressuscite sozinha um assunto antigo inacabado como se ele estivesse retomando aquilo — \
espere ele dizer o que quer agora. Só emende no assunto anterior se a mensagem atual dele deixar \
claro que é a continuação.
- Se o paciente fizer mais de uma pergunta na mesma mensagem (ou em mensagens seguidas do \
mesmo assunto), responda TODAS antes de seguir para outro tópico — nunca deixe uma pergunta \
sem resposta só porque outra parecia mais relevante.
- Para QUALQUER data (hoje, amanhã, nome de dia da semana, "que vem", data numérica), \
use exclusivamente a tabela de CALENDÁRIO fornecida no contexto — localize a linha exata, \
nunca conte ou calcule dias de cabeça. Isso vale também para os campos de data das \
ferramentas (date, scheduled_at): copie o valor da tabela, nunca invente.
- NUNCA use travessões (`—`) ou formatações complexas de markdown (tabelas, títulos grandes `#`, etc.). \
Utilize apenas negritos (`*texto*`) e quebras de linha normais para manter a legibilidade limpa no WhatsApp.
- NUNCA use listas com marcadores (-, *, •) ou numeradas (1., 2., 3.) para apresentar serviços, \
horários, formas de pagamento ou qualquer outra informação — mesmo com vários itens, descreva em \
frase corrida, como falaria numa conversa real. Cite no máximo 2-3 opções por vez e pergunte antes \
de despejar mais.
- Mensagens curtas: no máximo 2-3 frases por parte. Se a resposta completa ficaria mais longa que isso, \
resuma o essencial agora e ofereça detalhar mais se o paciente quiser saber mais — nunca despeje um \
parágrafo grande de uma vez só.
- Se a situação exigir passar a conversa para um humano da equipe (paciente pedir explicitamente \
para falar com uma pessoa/atendente/o dono; estiver claramente irritado ou insatisfeito; relatar dor \
forte, complicação pós-procedimento ou urgência clínica; pedir algo fora do que você pode resolver \
sozinha; ou depois de tentar e não conseguir resolver a mesma coisa) e você não for a pessoa certa \
para tomar essa decisão sozinha, use a ferramenta de encaminhamento disponível para você — não tente \
"forçar" uma solução nem prometa algo que não pode cumprir.

ESTILO DE MENSAGEM (WhatsApp):
- Escreva como uma pessoa real no WhatsApp: mensagens curtas e naturais.
- Use o marcador [[BREAK]] (sem espaços ao redor) com moderação — só quando a \
resposta tiver DUAS OU MAIS ideias claramente distintas que uma pessoa mandaria \
como mensagens separadas de propósito.
- NÃO quebre uma afirmação da pergunta de acompanhamento que vem logo em seguida \
dela (ex.: "Você pode pagar com Pix ou cartão. Quer agendar?" fica numa única \
mensagem — pergunta e contexto andam juntos, não são ideias separadas).
- NÃO quebre listas, explicações de um único tópico, nem frases que dependem da \
anterior para fazer sentido.
- Prefira 1 mensagem. Use 2 partes apenas quando fizer diferença real; 3 é o \
limite absoluto e raro.
- Quando você dividir a resposta em mais de uma parte, cada parte deve ter conteúdo próprio — evite \
criar uma parte que é só um resquício sem função. Isso é diferente de mandar uma reação curta como \
a resposta inteira e única a algo — isso é super normal e humano.
- Não numere as partes nem comente sobre a divisão; o marcador é só um separador interno.\
"""


def tools_subset(names: set[str]) -> types.Tool:
    """
    Filter app.services.ai_tools.CLINIC_TOOLS.function_declarations down to
    just `names`, so each agent's tool schemas stay a single source of truth
    (ai_tools.py) instead of being hand-duplicated per agent.
    """
    decls = [d for d in CLINIC_TOOLS.function_declarations if d.name in names]
    found = {d.name for d in decls}
    missing = names - found
    if missing:
        raise ValueError(f"tools_subset: unknown tool name(s) not in CLINIC_TOOLS: {sorted(missing)}")
    return types.Tool(function_declarations=decls)


@dataclass(slots=True)
class AgentReply:
    """Result of running one specialist's tool-calling loop for this turn."""

    text: str
    model: str
    escalated: bool = False
    escalate_reason: str | None = None


async def run_specialist_loop(
    *,
    client: genai.Client,
    model: str,
    temperature: float,
    max_output_tokens: int,
    system_prompt: str,
    tools: types.Tool,
    allowed_tool_names: set[str],
    contents: list[types.Content],
    db: AsyncSession,
    tenant: Tenant,
    contact: Contact,
    ai_cfg: dict,
) -> AgentReply:
    """
    Shared tool-calling loop for a single specialist agent (Booking/Sales/
    Handoff). Mirrors app.services.ai._legacy_generate_reply's loop shape but
    parameterized by system_prompt/tools/allowed_tool_names, and generalized
    to detect the shared escalate_to_human signal (see ESCALATE_DECL) instead
    of executing it as a real tool.

    `allowed_tool_names` is enforced HERE, server-side, before any tool name
    reaches app.services.ai_tools.execute_tool — defense in depth beyond
    "Gemini can't call an undeclared function": it guards against a bug in
    how this agent's own `tools` were assembled, not against the model.
    """
    contents = list(contents)  # local copy — this loop appends to it

    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        tools=[tools],
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )

    empty_retries = 0
    for iteration in range(SPECIALIST_MAX_TOOL_ITERATIONS):
        response = await _generate_content_with_retry(client, model, contents, config, tenant, contact, iteration)

        candidate = response.candidates[0]
        response_content = candidate.content
        parts = response_content.parts if response_content is not None else None

        if not parts:
            finish_reason = getattr(candidate, "finish_reason", None)
            logger.warning(
                "agent_empty_parts",
                extra={
                    "finish_reason": str(finish_reason),
                    "iteration": iteration,
                    "model": model,
                    "tenant_id": str(tenant.id),
                    "contact_id": str(contact.id),
                },
            )
            fallback = (getattr(response, "text", None) or "").strip()
            if fallback:
                return AgentReply(text=fallback, model=model)
            if empty_retries < 1:
                empty_retries += 1
                continue
            return AgentReply(
                text="Desculpe, tive um probleminha para processar sua mensagem agora. Pode me mandar de novo, por favor? 😊",
                model=model,
            )

        function_call_part = next((p for p in parts if p.function_call is not None), None)

        if function_call_part is None:
            reply = response.text or ""
            return AgentReply(text=reply, model=model)

        fn = function_call_part.function_call

        if fn.name == ESCALATE_TOOL_NAME:
            # Signal-only: never touches the DB, never reaches execute_tool.
            # Per the approved design, the calling specialist's text for THIS
            # turn is discarded — the orchestrator runs Handoff next to
            # produce the actual patient-facing goodbye (replace, not append;
            # matches the existing "don't try to resolve again, just say
            # goodbye" rule that already existed pre-refactor).
            logger.info(
                "agent_escalation_requested",
                extra={
                    "tenant_id": str(tenant.id),
                    "contact_id": str(contact.id),
                    "reason": dict(fn.args or {}).get("reason"),
                },
            )
            return AgentReply(
                text="",
                model=model,
                escalated=True,
                escalate_reason=dict(fn.args or {}).get("reason"),
            )

        if fn.name not in allowed_tool_names:
            # Defense in depth: should be structurally impossible (Gemini
            # can't call a function that wasn't declared to it), but if the
            # agent's own `tools`/`allowed_tool_names` ever drift apart, fail
            # safe with a benign tool-response instead of executing anything.
            logger.warning(
                "agent_tool_not_allowed",
                extra={
                    "tool": fn.name,
                    "allowed": sorted(allowed_tool_names),
                    "tenant_id": str(tenant.id),
                    "contact_id": str(contact.id),
                },
            )
            tool_result = {"error": f"Tool '{fn.name}' is not available to this agent."}
        else:
            tool_result = await execute_tool(
                name=fn.name,
                args=dict(fn.args),
                db=db,
                tenant_id=uuid.UUID(str(tenant.id)),
                contact_id=uuid.UUID(str(contact.id)),
                tenant_settings=tenant.settings,
                ai_config=ai_cfg,
                tenant_name=tenant.name,
            )
            # Fire-and-forget: same alert wiring as the legacy single-agent
            # path (app.services.ai._legacy_generate_reply) — only the
            # Handoff agent ever holds this tool (see handoff.py), but the
            # side effect lives here so it fires regardless of which
            # specialist ends up calling it.
            if fn.name == "request_human_handoff" and isinstance(tool_result, dict) and tool_result.get("success"):
                asyncio.create_task(
                    send_handoff_alert_email(tenant, contact, dict(fn.args).get("reason"))
                )

        logger.info(
            "agent_tool_executed",
            extra={
                "tool": fn.name,
                "tenant_id": str(tenant.id),
                "contact_id": str(contact.id),
                "iteration": iteration,
            },
        )

        contents.append(response_content)
        contents.append(
            types.Content(
                role="user",
                parts=[types.Part(function_response=types.FunctionResponse(name=fn.name, response=tool_result))],
            )
        )

    # Exhausted the loop without a final text answer — force one last
    # completion with tools disabled, mirroring the legacy agent's fallback.
    logger.warning(
        "agent_tool_loop_exhausted",
        extra={
            "max_iterations": SPECIALIST_MAX_TOOL_ITERATIONS,
            "tenant_id": str(tenant.id),
            "contact_id": str(contact.id),
        },
    )
    try:
        final_config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        )
        final_response = await client.aio.models.generate_content(model=model, contents=contents, config=final_config)
        forced_reply = (final_response.text or "").strip()
        if forced_reply:
            return AgentReply(text=forced_reply, model=model)
    except Exception:
        logger.exception(
            "agent_forced_final_failed",
            extra={"model": model, "tenant_id": str(tenant.id), "contact_id": str(contact.id)},
        )

    return AgentReply(text="Desculpe, não consegui processar sua solicitação no momento. Tente novamente.", model=model)
