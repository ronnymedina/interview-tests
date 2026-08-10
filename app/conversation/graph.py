from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from . import prompts
from .messages import content_text

# Guardarraíles fijos del tutor, versionados en `prompts/v1_tutor_system.md`. Van como
# SystemMessage y tienen precedencia sobre el brief del alumno. El brief entra como PRIMER
# HumanMessage, así que `contents` de Gemini nunca queda vacío y no hace falta un empujón
# artificial.
_SYSTEM_PROMPT = prompts.load(prompts.TUTOR_SYSTEM)

# Instrucción del feedback final. Define solo el COMPORTAMIENTO y el formato de salida.
# 'feedback' es TEXTO LIBRE en Markdown (no una lista fija); QUÉ evaluar sale de la sección
# "### Puntos" del brief. Las palabras y las frases sí van estructuradas aparte.
_FEEDBACK_INSTRUCTION = (
    "The practice is over. Produce a FeedbackReport.\n"
    "- 'feedback': free-form feedback in Spanish, written in Markdown (use headings and bullets "
    "as you see fit). Be clear and as detailed as useful, focused on the aspects the learner "
    "listed in the '### Puntos' section of their brief. Do NOT restrict yourself to a fixed "
    "checklist; cover what actually matters for THIS learner.\n"
    "- 'words': up to 10 English words the learner should practice (mispronounced or worth "
    "improving). For each: 'hint' is a short pronunciation cue (e.g. '-ed -> /t/'), empty string "
    "if none; 'present' is the present/base form when the word is a verb (especially a past-tense "
    "verb, e.g. 'work' for 'worked'), empty string when it does not apply (nouns, etc.).\n"
    "- 'phrases': phrase-level suggestions. Whenever the learner said something that could be more "
    "natural or was grammatically off, add an entry with 'original' (what they said), 'suggestion' "
    "(a better version) and 'note' (a short reason in Spanish, empty string if none). "
    "E.g. original 'I will make' -> suggestion \"I'll make\" (contraction); original 'I doesn't' -> "
    "suggestion \"I don't\" (negative conjugation)."
)


class PracticeWord(BaseModel):
    word: str = Field(description="English word the learner should practice")
    present: str = Field(
        default="", description="Present/base form when the word is a verb; empty string if N/A"
    )
    hint: str = Field(description="Short pronunciation hint, e.g. '-ed -> /t/'. Empty string if none.")


class PhraseSuggestion(BaseModel):
    original: str = Field(description="What the learner said, e.g. 'I will make'")
    suggestion: str = Field(description="A better/more natural version, e.g. \"I'll make\"")
    note: str = Field(
        default="", description="Short reason in Spanish (e.g. 'contracción'); empty string if none"
    )


class FeedbackReport(BaseModel):
    feedback: str = Field(description="Free-form feedback in Spanish, written in Markdown")
    words: list[PracticeWord] = Field(
        default_factory=list, description="Up to 10 words to practice, each with a pronunciation hint"
    )
    phrases: list[PhraseSuggestion] = Field(
        default_factory=list, description="Phrase-level suggestions: original -> better version"
    )


class State(TypedDict):
    """Estado mutable que viaja por el grafo, persistido por el checkpointer y por conversación."""

    messages: Annotated[list[AnyMessage], add_messages]
    brief: str  # brief del alumno ya sintetizado (### Puntos + ### Contexto)
    max_questions: int
    questions_asked: int
    content_feedback: str  # feedback libre en Markdown
    practice_words: list[dict]
    practice_phrases: list[dict]
    finished: bool


def initial_state(brief: str, max_questions: int) -> State:
    """Estado inicial para arrancar una conversación.

    Siembra el historial con las reglas fijas (SystemMessage) y el brief del alumno como
    PRIMER HumanMessage. Así `contents` de Gemini ya trae un turno de usuario real y el
    nodo `ask` puede pedir la primera pregunta sin ningún empujón artificial.
    """
    return {
        "messages": [SystemMessage(_SYSTEM_PROMPT), HumanMessage(brief)],
        "brief": brief,
        "max_questions": max_questions,
        "questions_asked": 0,
        "content_feedback": "",
        "practice_words": [],
        "practice_phrases": [],
        "finished": False,
    }


def build_graph(llm, checkpointer: BaseCheckpointSaver | None = None):
    """Arma y compila el grafo: nodos `ask`/`review`, ruteo por función y checkpointer.

    En cada invocación corre exactamente un nodo (ask o review) y termina; el estado
    persiste por `thread_id` entre invocaciones gracias al checkpointer.
    """

    def route(state: State) -> str:
        # Desde START: a `review` si ya se alcanzó el tope de preguntas, si no a `ask`.
        return "review" if state["questions_asked"] >= state["max_questions"] else "ask"


    def ask(state: State) -> dict:
        # El historial ya arranca con SystemMessage + el brief como HumanMessage (ver
        # `initial_state`), así que siempre hay un turno de usuario y no hace falta empujón.
        question = content_text(llm.invoke(state["messages"]))
        return {
            "messages": [AIMessage(question)],
            "questions_asked": state["questions_asked"] + 1,
        }


    def review(state: State) -> dict:
        # Revisor de la conversación: cierra la práctica y emite el FeedbackReport.
        report = llm.with_structured_output(FeedbackReport).invoke(
            state["messages"] + [HumanMessage(_FEEDBACK_INSTRUCTION)]
        )
        return {
            "finished": True,
            "content_feedback": report.feedback,
            "practice_words": [word.model_dump() for word in report.words],
            "practice_phrases": [phrase.model_dump() for phrase in report.phrases],
        }


    builder = StateGraph(State)
    builder.add_node("ask", ask)
    builder.add_node("review", review)
    builder.add_conditional_edges(START, route, {"ask": "ask", "review": "review"})
    builder.add_edge("ask", END)
    builder.add_edge("review", END)
    return builder.compile(checkpointer=checkpointer or InMemorySaver())
