"""Orquestación de la conversación como servicio con inyección de dependencias.

`ConversationService` recibe ya armados el grafo y el sintetizador; no sabe cómo se
construyen ni de qué proveedor de LLM salen. La construcción (una sola vez) vive en el
punto de arranque, que llama a `build_service` e inyecta el resultado. Para tests, se
construye la clase directamente con dobles del grafo/sintetizador.
"""

import uuid

from langchain_core.messages import HumanMessage

import config

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

        Sintetiza el contexto CRUDO del alumno al brief de dos secciones POR DENTRO (no es
        un paso separado que pida el frontend), genera un `thread_id` fresco y siembra el
        estado con las reglas fijas + el brief como primer turno humano (`initial_state`).
        El nº de pregunta y el total permiten al frontend mostrar "Pregunta X de N".
        """
        brief = self._synthesizer.synthesize(user_context)
        conversation_id = uuid.uuid4().hex
        result = self._graph.invoke(
            initial_state(brief, max_questions), self._thread(conversation_id)
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
                    "brief": result["brief"],
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


def build_llm():
    """Construye el LLM leyendo la configuración. Falla claro si falta la clave.

    Usa `init_chat_model`: el proveedor y el modelo salen de `config.CHAT_MODEL`
    (formato "proveedor:modelo"), así cambiar de proveedor es cambiar config, no código.
    """
    if not config.GEMINI_API_KEY:
        raise ConversationError(
            "Falta GEMINI_API_KEY en el archivo .env. Copia .env.example a .env "
            "y pon tu clave de Gemini.",
            status=500,
        )
    from langchain.chat_models import init_chat_model

    return init_chat_model(config.CHAT_MODEL, api_key=config.GEMINI_API_KEY)


def build_service(checkpointer=None) -> ConversationService:
    """Composition root: arma LLM → grafo → sintetizador y devuelve el servicio listo.

    Se llama UNA vez en el arranque; el mismo LLM alimenta al grafo y al sintetizador.
    """
    llm = build_llm()
    return ConversationService(build_graph(llm, checkpointer), Synthesizer(llm))
