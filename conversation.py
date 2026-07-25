"""Grafo de conversacion con LangGraph + Gemini.

Este archivo es el UNICO punto que habla con LangGraph y con Gemini (analogo a como
azure_speech.py aisla Azure). Mantiene el estado de cada conversacion en memoria mediante
el checkpointer de LangGraph, indexado por conversation_id (el thread_id del grafo).

El turno del usuario (audio -> Azure -> texto reconocido) ocurre fuera del grafo, en el
endpoint HTTP; aqui solo entra el texto ya reconocido como mensaje humano.
"""

import operator
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
    per_turn_scores: Annotated[list[dict], operator.add]
    per_turn_words: Annotated[list[dict], operator.add]
    content_feedback: str
    finished: bool


def build_graph(llm):
    """Construye y compila el grafo con un checkpointer en memoria.

    `llm` es cualquier objeto con `.invoke(messages).content -> str`.
    En cada invocacion corre exactamente un nodo (ask o finalize) y termina; el estado
    persiste por thread_id entre invocaciones.
    """

    def route(state: State) -> str:
        return "finalize" if state["questions_asked"] >= state["max_questions"] else "ask"

    def ask(state: State) -> dict:
        question = llm.invoke(state["messages"]).content
        return {
            "messages": [AIMessage(question)],
            "questions_asked": state["questions_asked"] + 1,
        }

    def finalize(state: State) -> dict:
        feedback = llm.invoke(
            state["messages"] + [HumanMessage(_FEEDBACK_INSTRUCTION)]
        ).content
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
            "per_turn_scores": [],
            "per_turn_words": [],
            "content_feedback": "",
            "finished": False,
        },
        _config(conversation_id),
    )
    return conversation_id, result["messages"][-1].content


def answer(
    conversation_id: str,
    recognized_text: str,
    turn_scores: dict,
    turn_words: list[dict],
    graph=None,
) -> dict:
    """Inyecta la respuesta del usuario y devuelve la siguiente pregunta o el resultado final."""
    graph = graph or _get_graph()
    cfg = _config(conversation_id)

    # Conversacion desconocida (proceso reiniciado o id invalido): el checkpointer no tiene
    # estado para ese thread_id.
    if not graph.get_state(cfg).values:
        raise ConversationError("La conversacion no existe o expiro.", status=404)

    result = graph.invoke(
        {
            "messages": [HumanMessage(recognized_text)],
            "per_turn_scores": [turn_scores],
            "per_turn_words": list(turn_words),
        },
        cfg,
    )

    if result["finished"]:
        return {
            "final": {
                "scores": aggregate_scores(result["per_turn_scores"]),
                "content_feedback": result["content_feedback"],
                "system_prompt": result["system_prompt"],
                "questions_asked": result["questions_asked"],
                "words": result["per_turn_words"],
            }
        }
    return {"question": result["messages"][-1].content}


def aggregate_scores(per_turn_scores: list[dict]) -> dict:
    """Promedia los scores de todos los turnos. Ignora None (ej. prosody no soportada)."""

    def avg(key: str):
        values = [s[key] for s in per_turn_scores if s.get(key) is not None]
        return round(sum(values) / len(values), 1) if values else None

    return {
        "pronunciation": avg("pronunciation"),
        "accuracy": avg("accuracy"),
        "fluency": avg("fluency"),
        "prosody": avg("prosody"),
    }
