from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

from . import prompts
from .messages import content_text, render_transcript
from .synthesizer import focus_points

# Fixed tutor guardrails, versioned in `prompts/v1_tutor_system.md`. They go in as a
# SystemMessage and take precedence over the student's brief. The brief enters as the FIRST
# HumanMessage, so Gemini's `contents` is never empty and no artificial kickoff is needed.
_SYSTEM_PROMPT = prompts.load(prompts.TUTOR_SYSTEM)

# Reviewer system prompt. Unlike the tutor's, it is NOT part of the conversation history:
# the `review` node builds its own message list from scratch, so nothing the tutor was told
# leaks into the evaluation.
_REVIEWER_PROMPT = prompts.load(prompts.REVIEWER_GENERAL)


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


class ConversationGraph:
    """The practice graph: `ask`/`review` nodes, function-based routing, checkpointer.

    Two separate LLM instances on purpose: `ask` runs hot (varied, natural questions) and
    `review` runs cold (stable, reproducible evaluation). See
    `docs/superpowers/specs/2026-08-09-revisor-separado-design.md`.

    Instantiate once with the collaborators and call `compile()` to get the runnable graph.
    Each invocation of that graph runs exactly one node (ask or review) and ends; the state
    persists per `thread_id` across invocations thanks to the checkpointer.
    """

    ASK = "ask"
    REVIEW = "review"

    def __init__(self, tutor_llm, review_llm, checkpointer: BaseCheckpointSaver | None = None):
        self._tutor_llm = tutor_llm
        self._review_llm = review_llm
        self._checkpointer = checkpointer or InMemorySaver()

    def compile(self):
        """Wire the nodes and edges and compile the graph."""
        builder = StateGraph(State)
        builder.add_node(self.ASK, self._ask)
        builder.add_node(self.REVIEW, self._review)
        builder.add_conditional_edges(
            START, self._route, {self.ASK: self.ASK, self.REVIEW: self.REVIEW}
        )
        builder.add_edge(self.ASK, END)
        builder.add_edge(self.REVIEW, END)
        return builder.compile(checkpointer=self._checkpointer)

    def _route(self, state: State) -> str:
        # From START: go to `review` once the question cap is reached, otherwise to `ask`.
        return self.REVIEW if state["questions_asked"] >= state["max_questions"] else self.ASK

    def _ask(self, state: State) -> dict:
        # The history already starts with SystemMessage + the brief as a HumanMessage (see
        # `initial_state`), so there is always a user turn and no kickoff is needed.
        question = content_text(self._tutor_llm.invoke(state["messages"]))
        return {
            "messages": [AIMessage(question)],
            "questions_asked": state["questions_asked"] + 1,
        }

    def _review(self, state: State) -> dict:
        # A separate agent: its own system prompt and a message list built from scratch.
        # The conversation goes in as DATA inside a HumanMessage, never as the history —
        # as AIMessages the model would be judging its own turns, and it goes easy on
        # itself. The brief's `### Contexto` stays out: it is what to talk about, not what
        # to evaluate, and it can be huge.
        report = self._review_llm.with_structured_output(FeedbackReport).invoke(
            [
                SystemMessage(_REVIEWER_PROMPT),
                HumanMessage(
                    "### Points to evaluate\n"
                    f"{focus_points(state['session_brief'])}\n\n"
                    "### Transcript\n"
                    f"{render_transcript(state['messages'])}"
                ),
            ]
        )
        return {
            "finished": True,
            "content_feedback": report.feedback,
            "practice_words": [word.model_dump() for word in report.words],
            "practice_phrases": [phrase.model_dump() for phrase in report.phrases],
        }
