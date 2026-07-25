"""Tests del grafo de conversacion con un LLM falso (sin red)."""

import pytest
from langchain_core.messages import AIMessage, HumanMessage

import config
import conversation


class FakeLLM:
    """Doble del cliente Gemini: devuelve respuestas predefinidas en orden."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        return AIMessage(self._replies.pop(0))


class GeminiLikeLLM(FakeLLM):
    """Como FakeLLM pero exige al menos un turno humano, igual que Gemini.

    Gemini falla con "contents are required" si no hay ningun HumanMessage; este doble
    reproduce esa restriccion para cubrir el primer turno (que solo trae SystemMessage).
    """

    def invoke(self, messages):
        if not any(isinstance(m, HumanMessage) for m in messages):
            raise ValueError("contents are required.")
        return super().invoke(messages)


class BlockContentLLM:
    """Doble que devuelve contenido en bloques, como a veces hace Gemini.

    `AIMessage.content` puede ser [{"type": "text", "text": "..."}] en vez de un string.
    """

    def __init__(self, texts):
        self._texts = list(texts)

    def invoke(self, messages):
        text = self._texts.pop(0)
        return AIMessage([{"type": "text", "text": text, "extras": {"signature": "x"}}])


def _scores(pronunciation):
    return {
        "pronunciation": pronunciation,
        "accuracy": pronunciation,
        "fluency": pronunciation,
        "prosody": pronunciation,
    }


def test_start_asks_first_question():
    graph = conversation.build_graph(FakeLLM(["What did you do yesterday?"]))
    conversation_id, question = conversation.start("Roleplay sobre trabajo", 2, graph=graph)
    assert isinstance(conversation_id, str) and conversation_id
    assert question == "What did you do yesterday?"


def test_first_ask_includes_human_turn_for_gemini():
    # Reproduce el bug real: en el primer turno solo hay SystemMessage y Gemini exige un
    # turno humano. El nodo `ask` debe agregar un empujon humano para arrancar.
    graph = conversation.build_graph(GeminiLikeLLM(["What did you do yesterday?"]))
    _, question = conversation.start("Roleplay sobre trabajo", 2, graph=graph)
    assert question == "What did you do yesterday?"


def test_block_content_is_flattened_to_string():
    # Reproduce el bug "[object Object]": Gemini puede devolver contenido en bloques.
    # La pregunta y el feedback deben salir como strings planos.
    graph = conversation.build_graph(BlockContentLLM(["Q1", "FEEDBACK"]))
    conversation_id, q1 = conversation.start("Roleplay", 1, graph=graph)
    assert q1 == "Q1"
    result = conversation.answer(conversation_id, "hi", _scores(80.0), [], graph=graph)
    assert result["final"]["content_feedback"] == "FEEDBACK"


def test_full_flow_reaches_feedback():
    graph = conversation.build_graph(FakeLLM(["Q1", "Q2", "FEEDBACK"]))
    conversation_id, q1 = conversation.start("Roleplay", 2, graph=graph)
    assert q1 == "Q1"

    r1 = conversation.answer(conversation_id, "answer one", _scores(80.0), [], graph=graph)
    assert r1 == {"question": "Q2"}

    r2 = conversation.answer(conversation_id, "answer two", _scores(90.0), [], graph=graph)
    assert "final" in r2
    assert r2["final"]["content_feedback"] == "FEEDBACK"
    assert r2["final"]["questions_asked"] == 2
    assert r2["final"]["scores"]["pronunciation"] == 85.0
    assert r2["final"]["system_prompt"] == "Roleplay"


def test_words_accumulate_across_turns():
    graph = conversation.build_graph(FakeLLM(["Q1", "FEEDBACK"]))
    words_turn = [{"word": "hello", "error_type": "None", "accuracy": 90.0, "phonemes": []}]
    conversation_id, _ = conversation.start("Roleplay", 1, graph=graph)
    result = conversation.answer(conversation_id, "hello", _scores(90.0), words_turn, graph=graph)
    assert result["final"]["words"] == words_turn


def test_answer_unknown_conversation_raises_404():
    graph = conversation.build_graph(FakeLLM([]))
    with pytest.raises(conversation.ConversationError) as error:
        conversation.answer("does-not-exist", "hi", _scores(80.0), [], graph=graph)
    assert error.value.status == 404


def test_answer_after_finished_raises_409_and_does_not_reinvoke_graph():
    graph = conversation.build_graph(FakeLLM(["Q1", "Q2", "FEEDBACK"]))
    conversation_id, _ = conversation.start("Roleplay", 2, graph=graph)
    conversation.answer(conversation_id, "answer one", _scores(80.0), [], graph=graph)
    result = conversation.answer(conversation_id, "answer two", _scores(90.0), [], graph=graph)
    assert "final" in result

    # La conversacion ya termino: llamar answer() de nuevo no debe re-invocar el grafo
    # (el FakeLLM no tiene mas respuestas: un re-invoke lanzaria IndexError) y debe
    # devolver 409 en su lugar.
    with pytest.raises(conversation.ConversationError) as error:
        conversation.answer(conversation_id, "answer three", _scores(70.0), [], graph=graph)
    assert error.value.status == 409


def test_start_without_api_key_raises_500(monkeypatch):
    """Sin GEMINI_API_KEY, _get_graph() debe fallar con 500 al construir el grafo real."""
    monkeypatch.setattr(config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(conversation, "_graph", None)

    with pytest.raises(conversation.ConversationError) as error:
        conversation.start("Roleplay", 2)

    assert error.value.status == 500
