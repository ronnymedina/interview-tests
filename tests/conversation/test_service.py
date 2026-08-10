"""`ConversationService` orquesta el grafo: contrato del servicio hacia el endpoint."""

from types import SimpleNamespace

from app.conversation.service import ConversationService


class FakeGraph:
    """Doble del grafo compilado: solo lo que `ConversationService` le pide.

    `get_state().values` es el estado ANTES del turno (todavía sin terminar, porque si no
    `answer` corta con 409), e `invoke` devuelve el estado ya actualizado. Acá se testea el
    contrato del servicio hacia el endpoint, no el grafo.
    """

    def __init__(self, values: dict) -> None:
        self._values = values

    def get_state(self, config):
        return SimpleNamespace(values={**self._values, "finished": False})

    def invoke(self, payload, config=None):
        return self._values


def test_answer_final_devuelve_el_session_brief():
    """La clave del payload es `session_brief`, no `brief`: es la única superficie
    pública del rename."""
    graph = FakeGraph(
        {
            "finished": True,
            "content_feedback": "Muy bien el pasado simple.",
            "session_brief": "### Puntos\n- Pasado simple\n\n### Contexto\nMi CV",
            "questions_asked": 5,
            "max_questions": 5,
            "practice_words": [],
            "practice_phrases": [],
        }
    )
    service = ConversationService(graph, synthesizer=None)

    result = service.answer("abc123", "I worked on a payments API")

    assert result["final"]["session_brief"].startswith("### Puntos")
    assert "brief" not in result["final"]
