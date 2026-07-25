"""Grafo de conversacion con LangGraph + Gemini.

Este archivo es el UNICO punto que habla con LangGraph y con Gemini (analogo a como
azure_speech.py aisla Azure). Mantiene el estado de cada conversacion en memoria mediante
el checkpointer de LangGraph, indexado por conversation_id (el thread_id del grafo).

El turno del usuario (audio -> Azure -> texto reconocido) ocurre fuera del grafo, en el
endpoint HTTP; aqui solo entra el texto ya reconocido como mensaje humano.
"""

import uuid
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

import config

# Instruccion interna que envuelve al system prompt del usuario. Fija el formato (una
# pregunta por turno) sin pisar el escenario que define el usuario.
_ASK_INSTRUCTION = (
    "You are a spoken English practice partner. Follow the scenario described below. "
    "Ask exactly ONE short, natural question in English per turn, then stop and wait for "
    "the learner's spoken answer. Never answer on the learner's behalf. Scenario:\n\n"
)

# Empujon humano para el primer turno: Gemini exige al menos un turno de usuario en
# `contents` (el SystemMessage se manda como system_instruction, no cuenta). Solo se usa
# para la llamada al LLM del primer `ask`; no se persiste en el historial.
_KICKOFF = "Let's begin. Ask me your first question."

# Instruccion para el feedback final de contenido.
_FEEDBACK_INSTRUCTION = (
    "The practice is over. In Spanish, give the learner brief feedback (4-6 sentences) on "
    "their English across the whole conversation: grammar, vocabulary and how to improve."
)


class ConversationError(Exception):
    """Error pensado para mostrarse al usuario. `status` es el codigo HTTP."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    system_prompt: str
    max_questions: int
    questions_asked: int
    content_feedback: str
    finished: bool


def _content_text(message) -> str:
    """Extrae el texto plano de un mensaje del LLM.

    `AIMessage.content` de Gemini puede ser un string o una lista de bloques
    (p.ej. [{"type": "text", "text": "..."}]). Normalizamos a string para que la pagina
    y la BD nunca reciban un objeto (que se pintaria como "[object Object]").
    """
    content = message.content
    if isinstance(content, str):
        return content
    parts = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict):
            parts.append(block.get("text", ""))
    return "".join(parts).strip()


def build_graph(llm):
    """Construye y compila el grafo con un checkpointer en memoria.

    `llm` es cualquier objeto con `.invoke(messages).content` (string o lista de bloques).
    En cada invocacion corre exactamente un nodo (ask o finalize) y termina; el estado
    persiste por thread_id entre invocaciones.
    """

    def route(state: State) -> str:
        return "finalize" if state["questions_asked"] >= state["max_questions"] else "ask"

    def ask(state: State) -> dict:
        messages = state["messages"]
        # En el primer turno solo hay un SystemMessage; Gemini requiere al menos un turno
        # humano en `contents`. Agregamos el empujon solo para esta llamada (no se guarda).
        if not any(isinstance(m, HumanMessage) for m in messages):
            messages = messages + [HumanMessage(_KICKOFF)]
        question = _content_text(llm.invoke(messages))
        return {
            "messages": [AIMessage(question)],
            "questions_asked": state["questions_asked"] + 1,
        }

    def finalize(state: State) -> dict:
        feedback = _content_text(
            llm.invoke(state["messages"] + [HumanMessage(_FEEDBACK_INSTRUCTION)])
        )
        return {"finished": True, "content_feedback": feedback}

    graph = StateGraph(State)
    graph.add_node("ask", ask)
    graph.add_node("finalize", finalize)
    graph.add_conditional_edges(START, route, {"ask": "ask", "finalize": "finalize"})
    graph.add_edge("ask", END)
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=InMemorySaver())


# Grafo real (Gemini), construido una sola vez. Los tests usan build_graph con un doble.
_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        if not config.GEMINI_API_KEY:
            raise ConversationError(
                "Falta GEMINI_API_KEY en el archivo .env. Copia .env.example a .env "
                "y pon tu clave de Gemini.",
                status=500,
            )
        from langchain_google_genai import ChatGoogleGenerativeAI

        llm = ChatGoogleGenerativeAI(
            model=config.GEMINI_MODEL, google_api_key=config.GEMINI_API_KEY
        )
        _graph = build_graph(llm)
    return _graph


def _config(conversation_id: str) -> dict:
    return {"configurable": {"thread_id": conversation_id}}


def start(system_prompt: str, max_questions: int, graph=None) -> tuple[str, str]:
    """Crea una conversacion nueva y devuelve (conversation_id, primera_pregunta)."""
    graph = graph or _get_graph()
    conversation_id = uuid.uuid4().hex
    result = graph.invoke(
        {
            "messages": [SystemMessage(_ASK_INSTRUCTION + system_prompt)],
            "system_prompt": system_prompt,
            "max_questions": max_questions,
            "questions_asked": 0,
            "content_feedback": "",
            "finished": False,
        },
        _config(conversation_id),
    )
    return conversation_id, result["messages"][-1].content


def exists(conversation_id: str, graph=None) -> bool:
    """Chequeo barato de si el id de conversacion es valido, sin invocar el grafo.

    Pensado para validar el id ANTES de gastar una llamada paga a Azure en el endpoint.
    """
    graph = graph or _get_graph()
    return bool(graph.get_state(_config(conversation_id)).values)


def answer(conversation_id: str, recognized_text: str, graph=None) -> dict:
    """Inyecta la respuesta del usuario y devuelve la siguiente pregunta o el resultado final.

    El scoring de pronunciacion ya no vive en el grafo: se acumula aparte (scoring.py) y el
    endpoint lo agrega al finalizar.
    """
    graph = graph or _get_graph()
    cfg = _config(conversation_id)

    # Conversacion desconocida (proceso reiniciado o id invalido).
    state_values = graph.get_state(cfg).values
    if not state_values:
        raise ConversationError("La conversacion no existe o expiro.", status=404)

    # Conversacion ya finalizada: no re-invocar el grafo (evitaria otra llamada a Gemini y
    # un segundo guardado en la BD).
    if state_values.get("finished"):
        raise ConversationError("La conversacion ya termino.", status=409)

    result = graph.invoke({"messages": [HumanMessage(recognized_text)]}, cfg)

    if result["finished"]:
        return {
            "final": {
                "content_feedback": result["content_feedback"],
                "system_prompt": result["system_prompt"],
                "questions_asked": result["questions_asked"],
            }
        }
    return {"question": result["messages"][-1].content}
