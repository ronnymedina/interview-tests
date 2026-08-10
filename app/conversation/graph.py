from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from . import prompts
from .messages import content_text

# Fixed tutor guardrails, versioned in `prompts/v1_tutor_system.md`. They go in as a
# SystemMessage and take precedence over the student's brief. The brief enters as the FIRST
# HumanMessage, so Gemini's `contents` is never empty and no artificial kickoff is needed.
_SYSTEM_PROMPT = prompts.load(prompts.TUTOR_SYSTEM)

# Final feedback instruction. It defines only the BEHAVIOUR and the output format.
# 'feedback' is FREE-FORM Markdown text (not a fixed checklist); WHAT to evaluate comes from
# the "### Puntos" section of the brief. Words and phrases are structured separately.
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
    """Mutable state that travels through the graph, persisted per conversation by the checkpointer."""

    messages: Annotated[list[AnyMessage], add_messages]
    session_brief: str  # the student's brief, already synthesized (### Puntos + ### Contexto)
    max_questions: int
    questions_asked: int
    content_feedback: str  # free-form Markdown feedback
    practice_words: list[dict]
    practice_phrases: list[dict]
    finished: bool


def initial_state(session_brief: str, max_questions: int) -> State:
    """Initial state to start a conversation.

    Seeds the history with the fixed rules (SystemMessage) and the student's brief as the
    FIRST HumanMessage. That way Gemini's `contents` already carries a real user turn and the
    `ask` node can request the first question without any artificial kickoff.
    """
    return {
        "messages": [SystemMessage(_SYSTEM_PROMPT), HumanMessage(session_brief)],
        "session_brief": session_brief,
        "max_questions": max_questions,
        "questions_asked": 0,
        "content_feedback": "",
        "practice_words": [],
        "practice_phrases": [],
        "finished": False,
    }


def build_graph(llm, checkpointer: BaseCheckpointSaver | None = None):
    """Build and compile the graph: `ask`/`review` nodes, function-based routing, checkpointer.

    Each invocation runs exactly one node (ask or review) and ends; the state persists per
    `thread_id` across invocations thanks to the checkpointer.
    """

    def route(state: State) -> str:
        # From START: go to `review` once the question cap is reached, otherwise to `ask`.
        return "review" if state["questions_asked"] >= state["max_questions"] else "ask"


    def ask(state: State) -> dict:
        # The history already starts with SystemMessage + the brief as a HumanMessage (see
        # `initial_state`), so there is always a user turn and no kickoff is needed.
        question = content_text(llm.invoke(state["messages"]))
        return {
            "messages": [AIMessage(question)],
            "questions_asked": state["questions_asked"] + 1,
        }


    def review(state: State) -> dict:
        # Conversation reviewer: closes the practice session and emits the FeedbackReport.
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
