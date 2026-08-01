"""Servidor HTTP del módulo migrado (`app/`).

Composition root: al arrancar se construyen UNA vez el servicio de conversación (grafo +
sintetizador) y el repositorio de configuraciones guardadas (Postgres), y se inyectan a
los endpoints. Si falta `GEMINI_API_KEY`, el servicio de conversación queda sin construir
y sus endpoints responden 503; el resto del servidor arranca igual.

La validación de entrada vive en los esquemas Pydantic (`StartRequest`, `AnswerRequest`,
`ConfigRequest`); los endpoints solo traducen a HTTP. La síntesis del contexto al brief
ocurre por DENTRO de `service.start` (no hay endpoint de síntesis).

Sirve además el frontend simplificado estático (`app/web/`) en la raíz.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles

import config
from app import conversation
from app.conversation import (
    ConversationConfig,
    ConversationError,
    ConversationRepository,
    ConversationService,
)
from app.storage import PostgresStorage

logger = logging.getLogger(__name__)

_WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def _build_conversation_service() -> ConversationService | None:
    """Arma el servicio al inicio; degrada a None ante cualquier fallo de construcción.

    Así el resto del servidor arranca aunque falte la clave de Gemini o su dependencia; los
    endpoints de conversación responderán 503. El motivo queda en el log para no ocultar un
    problema real de configuración.
    """
    try:
        return conversation.build_service()
    except Exception:
        logger.exception("No se pudo construir el servicio de conversación; queda deshabilitado.")
        return None


_conversation_service = _build_conversation_service()
# El almacenamiento es perezoso (no conecta al construirse), así que el repositorio siempre
# está disponible; si Postgres está caído, el error aparece al ejecutar la consulta.
_storage = PostgresStorage(config.DATABASE_URL)
_repository = ConversationRepository(_storage)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Al arrancar intenta crear la tabla si falta (uso standalone); si Postgres está caído,
    lo registra y sigue: en docker-compose la tabla ya viene del init.sql."""
    try:
        _storage.init_schema()
    except Exception:
        logger.exception("No se pudo inicializar el esquema de Postgres; ¿está la BD arriba?")
    yield


app = FastAPI(title="review-ingles", lifespan=lifespan)


def get_conversation_service() -> ConversationService:
    """Dependencia FastAPI: entrega el servicio o corta con 503 si no está disponible."""
    if _conversation_service is None:
        raise HTTPException(
            status_code=503,
            detail="La conversación no está disponible: falta GEMINI_API_KEY.",
        )
    return _conversation_service


def get_repository() -> ConversationRepository:
    """Dependencia FastAPI: entrega el repositorio de configuraciones guardadas."""
    return _repository


# --- conversación en vivo -------------------------------------------------------------

@app.post("/conversation/start")
def conversation_start(
    payload: conversation.StartRequest,
    service: ConversationService = Depends(get_conversation_service),
) -> dict:
    """Arranca una conversación: sintetiza el contexto por dentro y devuelve la 1ª pregunta."""
    try:
        conversation_id, question = service.start(payload.user_context, payload.max_questions)
    except ConversationError as error:
        raise HTTPException(status_code=error.status, detail=str(error))
    return {"conversation_id": conversation_id, "question": question}


@app.post("/conversation/answer")
def conversation_answer(
    payload: conversation.AnswerRequest,
    service: ConversationService = Depends(get_conversation_service),
) -> dict:
    """Inyecta la respuesta del alumno y devuelve la siguiente pregunta o el feedback final."""
    try:
        return service.answer(payload.conversation_id, payload.text)
    except ConversationError as error:
        raise HTTPException(status_code=error.status, detail=str(error))


# --- configuraciones guardadas (CRUD sobre conversation_configs) ----------------------

@app.post("/conversation/configs", status_code=201)
def config_create(
    payload: conversation.ConfigRequest,
    repo: ConversationRepository = Depends(get_repository),
) -> ConversationConfig:
    """Crea una configuración guardada (nombre + contexto) y la devuelve con id y timestamps."""
    return repo.create(payload.name, payload.user_context)


@app.get("/conversation/configs")
def config_list(
    repo: ConversationRepository = Depends(get_repository),
) -> list[ConversationConfig]:
    """Lista las configuraciones guardadas, de la más reciente a la más antigua."""
    return repo.list()


@app.get("/conversation/configs/{config_id}")
def config_get(
    config_id: int,
    repo: ConversationRepository = Depends(get_repository),
) -> ConversationConfig:
    """Devuelve una configuración por id, o 404 si no existe."""
    found = repo.get(config_id)
    if found is None:
        raise HTTPException(status_code=404, detail="La configuración no existe.")
    return found


@app.put("/conversation/configs/{config_id}")
def config_update(
    config_id: int,
    payload: conversation.ConfigRequest,
    repo: ConversationRepository = Depends(get_repository),
) -> ConversationConfig:
    """Actualiza una configuración, o 404 si no existe."""
    updated = repo.update(config_id, payload.name, payload.user_context)
    if updated is None:
        raise HTTPException(status_code=404, detail="La configuración no existe.")
    return updated


@app.delete("/conversation/configs/{config_id}", status_code=204)
def config_delete(
    config_id: int,
    repo: ConversationRepository = Depends(get_repository),
) -> None:
    """Borra una configuración. No falla si no existe."""
    repo.delete(config_id)


# --- frontend estático (se monta al final para no tapar las rutas de la API) -----------

app.mount("/", StaticFiles(directory=str(_WEB_DIR), html=True), name="web")
