"""Orquestación de la conversación como servicio con inyección de dependencias.

`ConversationService` recibe ya armados el grafo y el sintetizador; no sabe cómo se
construyen ni de qué proveedor de LLM salen. La construcción (una sola vez) vive en el
punto de arranque, que llama a `build_service` e inyecta el resultado. Para tests, se
construye la clase directamente con dobles del grafo/sintetizador.
"""

import uuid
from typing import Any

from langchain_core.messages import HumanMessage

from config import settings

from .graph import build_graph, initial_state
from .synthesizer import Synthesizer


class ConversationError(Exception):
    """Error pensado para mostrarse al usuario. `status` es el código HTTP."""

    def __init__(self, message: str, status: int = 502) -> None:
        super().__init__(message)
        self.status = status


class ConversationService:
    """Orquesta el grafo de conversación y la síntesis del brief.

    Recibe sus dependencias por constructor (grafo + sintetizador); ambas se comparten
    entre requests. El grafo trae su propio checkpointer, así que el estado de cada
    conversación persiste por `thread_id` mientras viva este servicio.
    """

    def __init__(self, graph, synthesizer: Synthesizer) -> None:
        self._graph = graph
        self._synthesizer = synthesizer

    @staticmethod
    def _thread(conversation_id: str) -> dict:
        return {"configurable": {"thread_id": conversation_id}}

    def start(self, user_context: str, max_questions: int) -> tuple[str, str, int, int]:
        """Crea una conversación y devuelve (id, 1ª pregunta, nº de pregunta, total).

        Sintetiza el contexto CRUDO del alumno al `session_brief` de dos secciones POR
        DENTRO (no es un paso separado que pida el frontend), genera un `thread_id` fresco
        y siembra el estado con las reglas fijas + el brief como primer turno humano
        (`initial_state`). El nº de pregunta y el total permiten al frontend mostrar
        "Pregunta X de N".
        """
        session_brief = self._synthesizer.synthesize(user_context)
        conversation_id = uuid.uuid4().hex
        result = self._graph.invoke(
            initial_state(session_brief, max_questions), self._thread(conversation_id)
        )
        return (
            conversation_id,
            result["messages"][-1].content,
            result["questions_asked"],
            result["max_questions"],
        )

    def exists(self, conversation_id: str) -> bool:
        """Chequeo barato de si el id de conversación es válido, sin invocar el grafo."""
        return bool(self._graph.get_state(self._thread(conversation_id)).values)

    def answer(self, conversation_id: str, recognized_text: str) -> dict:
        """Inyecta la respuesta del alumno y devuelve la siguiente pregunta o el resultado final."""
        thread = self._thread(conversation_id)

        state_values = self._graph.get_state(thread).values
        if not state_values:
            raise ConversationError("La conversación no existe o expiró.", status=404)
        if state_values.get("finished"):
            raise ConversationError("La conversación ya terminó.", status=409)

        result = self._graph.invoke({"messages": [HumanMessage(recognized_text)]}, thread)

        if result["finished"]:
            return {
                "final": {
                    "content_feedback": result["content_feedback"],
                    "session_brief": result["session_brief"],
                    "questions_asked": result["questions_asked"],
                    "practice_words": result["practice_words"],
                    "practice_phrases": result["practice_phrases"],
                }
            }
        return {
            "question": result["messages"][-1].content,
            "question_number": result["questions_asked"],
            "total_questions": result["max_questions"],
        }


def build_llm(model: str = "", temperature: float | None = None):
    """Construye un LLM leyendo la configuración. Falla claro si falta la clave.

    Usa `init_chat_model`: el proveedor y el modelo salen de un string "proveedor:modelo",
    así cambiar de proveedor es cambiar config, no código. Sin argumentos usa
    `settings.CHAT_MODEL` y deja la temperatura por default del proveedor, que es el
    comportamiento histórico del que depende el sintetizador.
    """
    if not settings.GEMINI_API_KEY:
        raise ConversationError(
            "Falta GEMINI_API_KEY en el archivo .env. Copia .env.example a .env "
            "y pon tu clave de Gemini.",
            status=500,
        )
    from langchain.chat_models import init_chat_model

    # No se pasa `temperature=None`: algunos proveedores lo mandan literal en el request en
    # vez de tratarlo como "sin especificar". Si no se pide, la clave ni existe.
    kwargs: dict[str, Any] = {} if temperature is None else {"temperature": temperature}
    return init_chat_model(model or settings.CHAT_MODEL, api_key=settings.GEMINI_API_KEY, **kwargs)


def build_service(checkpointer=None) -> ConversationService:
    """Composition root: arma los tres LLM → grafo → sintetizador y devuelve el servicio.

    Se llama UNA vez en el arranque. Tres roles, tres instancias: el sintetizador conserva
    el comportamiento histórico (`build_llm()` pelado), el tutor corre caliente y el revisor
    frío. `REVIEW_CHAT_MODEL` vacío cae a `CHAT_MODEL`, así que por default los tres apuntan
    al mismo modelo y el costo por token no cambia.
    """
    synthesizer_llm = build_llm()
    tutor_llm = build_llm(settings.CHAT_MODEL, settings.CHAT_TEMPERATURE)
    review_llm = build_llm(
        settings.REVIEW_CHAT_MODEL or settings.CHAT_MODEL, settings.REVIEW_TEMPERATURE
    )
    return ConversationService(
        build_graph(tutor_llm, review_llm, checkpointer), Synthesizer(synthesizer_llm)
    )
