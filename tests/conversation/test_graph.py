"""El nodo `review` corre como un agente aparte: prompt propio, LLM propio, contexto
reducido. Estos tests fijan justamente lo que NO debe llegarle."""

from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.conversation import prompts
from app.conversation.graph import ConversationGraph, FeedbackReport, initial_state

UN_BRIEF = (
    "### Puntos que quiero estudiar y sobre los que debo recibir feedback\n"
    "- Pasado simple\n"
    "\n"
    "### Contexto\n"
    "Trabajé en una API de pagos. Mi CV dice que sé Python y Postgres."
)


class FakeLLM:
    """Doble de LLM que guarda lo que recibió y devuelve una respuesta fija."""

    def __init__(self, reply=None) -> None:
        self.reply = reply
        self.received = None

    def invoke(self, messages):
        self.received = messages
        return SimpleNamespace(content="What did you work on last week?")

    def with_structured_output(self, schema):
        assert schema is FeedbackReport
        return self

    def __call__(self, messages):  # pragma: no cover - no se usa
        raise AssertionError("el grafo debe invocar con .invoke")


class FakeReviewLLM(FakeLLM):
    """Igual, pero su `.invoke` devuelve un FeedbackReport en vez de un mensaje."""

    def invoke(self, messages):
        self.received = messages
        return FeedbackReport(feedback="Bien el pasado.", words=[], phrases=[])


def corre_hasta_el_review(tutor_llm, review_llm, max_questions=1):
    """Arranca una conversación y la lleva hasta que dispara el nodo `review`."""
    graph = ConversationGraph(tutor_llm, review_llm).compile()
    thread = {"configurable": {"thread_id": "t1"}}
    graph.invoke(initial_state(UN_BRIEF, max_questions), thread)
    return graph.invoke({"messages": [HumanMessage("I worked in a API.")]}, thread)


def texto_recibido(llm):
    """Todo lo que le llegó al LLM, concatenado, para preguntar qué contiene y qué no."""
    return "\n".join(str(message.content) for message in llm.received)


def test_el_revisor_no_recibe_el_prompt_del_tutor():
    """Problema 1 del diseño: el prompt del tutor prohíbe corregir, y al revisor se le pide
    exactamente lo contrario."""
    review_llm = FakeReviewLLM()
    corre_hasta_el_review(FakeLLM(), review_llm)
    assert "You are an English tutor" not in texto_recibido(review_llm)


def test_el_revisor_no_recibe_el_material_del_alumno():
    """El `### Contexto` sirve para elegir de qué conversar, no para juzgar el inglés, y
    puede ser larguísimo."""
    review_llm = FakeReviewLLM()
    corre_hasta_el_review(FakeLLM(), review_llm)
    recibido = texto_recibido(review_llm)
    assert "### Contexto" not in recibido
    assert "API de pagos" not in recibido


def test_el_revisor_recibe_los_puntos_y_la_transcripcion():
    review_llm = FakeReviewLLM()
    corre_hasta_el_review(FakeLLM(), review_llm)
    recibido = texto_recibido(review_llm)
    assert "- Pasado simple" in recibido
    assert "Learner: I worked in a API." in recibido
    assert "Tutor: What did you work on last week?" in recibido


def test_el_revisor_arranca_con_su_propio_system_prompt():
    review_llm = FakeReviewLLM()
    corre_hasta_el_review(FakeLLM(), review_llm)
    primero = review_llm.received[0]
    assert isinstance(primero, SystemMessage)
    assert primero.content == prompts.load(prompts.REVIEWER_GENERAL)


def test_la_conversacion_no_entra_como_mensajes_del_propio_modelo():
    """Problema 2: como AIMessage, el modelo se estaría autoevaluando. Va como dato."""
    review_llm = FakeReviewLLM()
    corre_hasta_el_review(FakeLLM(), review_llm)
    assert not any(isinstance(message, AIMessage) for message in review_llm.received)


def test_el_tutor_y_el_revisor_son_instancias_distintas():
    """Cada nodo usa la suya: si compartieran una, la temperatura por rol no existiría."""
    tutor_llm, review_llm = FakeLLM(), FakeReviewLLM()
    corre_hasta_el_review(tutor_llm, review_llm)
    assert tutor_llm.received is not None
    assert review_llm.received is not None
    assert tutor_llm.received is not review_llm.received


def test_el_resultado_del_review_llega_al_estado():
    resultado = corre_hasta_el_review(FakeLLM(), FakeReviewLLM())
    assert resultado["finished"] is True
    assert resultado["content_feedback"] == "Bien el pasado."
    assert resultado["practice_words"] == []
    assert resultado["practice_phrases"] == []
