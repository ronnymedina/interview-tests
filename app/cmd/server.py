"""Servidor HTTP del módulo migrado (`app/`).

Composition root: al arrancar se construyen UNA vez el servicio de conversación (grafo +
sintetizador) y el repositorio de configuraciones guardadas (Postgres), y se inyectan a
los endpoints. Si falta `GEMINI_API_KEY`, el servicio de conversación queda sin construir
y sus endpoints responden 503; el resto del servidor arranca igual.

La validación de entrada vive en los esquemas Pydantic (`StartRequest`, `ConfigRequest`);
los endpoints solo traducen a HTTP. `/conversation/answer` recibe multipart (audio + transcript)
y valida sus campos inline. La síntesis del contexto al brief ocurre por DENTRO de `service.start`
(no hay endpoint de síntesis).

Sirve además el frontend simplificado estático (`app/web/`) en la raíz.
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.staticfiles import StaticFiles
from langchain_core.callbacks import get_usage_metadata_callback

import config
from app import conversation
from app.conversation import (
    ConversationConfig,
    ConversationError,
    ConversationRepository,
    ConversationService,
)
from app.limits import LimitsService, build_limits_service
from app.speech import SpeechService, build_speech_service
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

# LimitsService: SIEMPRE se construye (la cuota/presupuesto son parte del piloto). Comparte el
# mismo almacenamiento perezoso; si Postgres está caído, la consulta falla al ejecutarse y el
# endpoint corta conservador.
_limits_service = build_limits_service(_storage)

# SpeechService: puede ser None si falta AZURE_SPEECH_KEY. En ese caso la conversación funciona
# igual (transcripción del navegador + feedback de Gemini) y se omite el scoring de Azure.
_speech_service = build_speech_service()
if _speech_service is None:
    logger.info("AZURE_SPEECH_KEY ausente: scoring de pronunciación deshabilitado.")


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


def get_limits_service() -> LimitsService:
    """Dependencia FastAPI: entrega el servicio de límites (cuota + presupuesto)."""
    return _limits_service


def get_speech_service() -> "SpeechService | None":
    """Dependencia FastAPI: entrega el servicio de pronunciación, o None si Azure no está."""
    return _speech_service


def get_user_id(x_user_id: str = Header(default="")) -> str:
    """Identidad del navegador (header X-User-Id). Obligatoria; 400 si falta o viene vacía."""
    user_id = x_user_id.strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="Falta el header X-User-Id.")
    return user_id


def _gemini_tokens(callback) -> tuple[int, int]:
    """Suma input/output tokens capturados por get_usage_metadata_callback (por todos los modelos)."""
    input_tokens = output_tokens = 0
    for usage in callback.usage_metadata.values():
        input_tokens += usage.get("input_tokens", 0)
        output_tokens += usage.get("output_tokens", 0)
    return input_tokens, output_tokens


# --- conversación en vivo -------------------------------------------------------------

@app.post("/conversation/start")
def conversation_start(
    payload: conversation.StartRequest,
    user_id: str = Depends(get_user_id),
    service: ConversationService = Depends(get_conversation_service),
    limits: LimitsService = Depends(get_limits_service),
) -> dict:
    """Arranca una conversación si el usuario tiene cuota y el presupuesto lo permite.

    Chequea límites ANTES de gastar; si no puede, corta con 429 y un motivo tipado. Si puede,
    sintetiza el contexto y devuelve la 1ª pregunta (por dentro de `service.start`), registra el
    inicio para la cuota y el uso de Gemini (tokens reales capturados alrededor de la llamada).
    """
    try:
        decision = limits.check_can_start(user_id)
    except Exception:
        logger.exception("check_can_start falló (¿Postgres?); se corta conservador como 'paused'.")
        raise HTTPException(status_code=429, detail={"reason": "paused"})

    if not decision.allowed:
        raise HTTPException(status_code=429, detail={"reason": decision.reason})

    try:
        with get_usage_metadata_callback() as callback:
            conversation_id, question = service.start(payload.user_context, payload.max_questions)
    except ConversationError as error:
        raise HTTPException(status_code=error.status, detail=str(error))

    limits.record_conversation_start(user_id, conversation_id)
    input_tokens, output_tokens = _gemini_tokens(callback)
    limits.record_gemini_usage(user_id, conversation_id, "synthesis", input_tokens, output_tokens)

    return {"conversation_id": conversation_id, "question": question}


@app.post("/conversation/answer")
def conversation_answer(
    conversation_id: str = Form(...),
    transcript: str = Form(...),
    audio: UploadFile = File(...),
    user_id: str = Depends(get_user_id),
    service: ConversationService = Depends(get_conversation_service),
    limits: LimitsService = Depends(get_limits_service),
    speech: "SpeechService | None" = Depends(get_speech_service),
) -> dict:
    """Procesa una respuesta: encola el audio para Azure (no espera) y avanza el grafo.

    Recibe multipart: el `transcript` del navegador (mueve la conversación rápido) y el `audio`
    WAV (lo puntúa Azure en segundo plano). En el turno final combina el feedback de Gemini con
    la evaluación de pronunciación agregada. Registra el uso de Gemini en cada turno y el de
    Azure una vez, al final, por la duración total.
    """
    text = transcript.strip()
    if not text:
        raise HTTPException(status_code=422, detail="La respuesta está vacía.")

    # Encola el WAV para el scoring en segundo plano ANTES de llamar al grafo (no bloquea).
    if speech is not None:
        speech.score_answer(conversation_id, audio.file.read())

    try:
        with get_usage_metadata_callback() as callback:
            result = service.answer(conversation_id, text)
    except ConversationError as error:
        raise HTTPException(status_code=error.status, detail=str(error))

    input_tokens, output_tokens = _gemini_tokens(callback)
    is_final = "final" in result

    limits.record_gemini_usage(
        user_id, conversation_id, "feedback" if is_final else "question",
        input_tokens, output_tokens,
    )

    if is_final:
        pronunciation = None
        if speech is not None:
            pronunciation = speech.final_pronunciation(conversation_id)
            limits.record_azure_usage(user_id, conversation_id, pronunciation["audio_seconds"])
        result["final"]["pronunciation"] = pronunciation

    return result


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
