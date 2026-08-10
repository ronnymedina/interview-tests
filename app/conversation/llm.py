"""Construcción de los chat models de LangChain que consumen los nodos del grafo.

Vive aparte del servicio a propósito: es el único punto del módulo que traduce la
configuración (`settings`) a una instancia concreta de proveedor. Quien la use recibe el
modelo ya armado por inyección y no sabe de dónde salió — ver `build_conversation_graph_service`
en `__init__.py`, que es quien lo llama.
"""

from typing import Any

from config import settings

from .service import ConversationError


def build_chat_model(model: str = "", temperature: float | None = None):
    """Construye un chat model leyendo la configuración. Falla claro si falta la clave.

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
