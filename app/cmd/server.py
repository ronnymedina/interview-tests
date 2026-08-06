"""Servidor HTTP del módulo migrado (`app/`).

Composition root: al arrancar se construyen UNA vez el servicio de conversación (grafo +
sintetizador) y el repositorio de configuraciones guardadas (Postgres), y se inyectan a
los endpoints. Si falta `GEMINI_API_KEY`, el servicio de conversación queda sin construir
y sus endpoints responden 503; el resto del servidor arranca igual.

La validación de entrada vive en los esquemas Pydantic (`StartRequest`, `ConfigRequest`);
los endpoints solo traducen a HTTP. `/conversation/answer` recibe multipart (audio + transcript)
y valida sus campos inline. La síntesis del contexto al brief ocurre por DENTRO de `service.start`
(no hay endpoint de síntesis).

Sirve además el frontend (`app/web/`): las páginas se renderizan con plantillas Jinja2
(`app/web/templates/`) y los archivos estáticos van montados bajo `/static`.
"""

import asyncio
import uuid
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import structlog

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from langchain_core.callbacks import get_usage_metadata_callback

from config import settings
from app import conversation
from app.ratelimit import IpRateLimiter, client_ip
from app.conversation import (
    ConversationConfig,
    ConversationError,
    ConversationRepository,
    ConversationService,
)
from app.feedback import FeedbackRepository, FeedbackRequest
from app.limits import LimitsService, build_limits_service
from app.logconfig import configure_logging
from app.reading import ReadingError, ReadingService, build_reading_service
from app.reading.ingest import build_default_ingest
from app.reading.scheduler import ingest_loop
from app.speech import SpeechService, build_speech_service
from app.storage import AsyncPostgresStorage, PostgresStorage

# Al importar y no solo en el `lifespan`: uvicorn importa este módulo antes de emitir sus
# primeras líneas ("Started server process"), y sin esto esas líneas salen con el formato de
# uvicorn en vez del nuestro — texto suelto que el agregador no puede parsear. La función es
# idempotente, así que la llamada del `lifespan` no duplica nada.
configure_logging()

logger = structlog.get_logger(__name__)

_WEB_DIR = Path(__file__).resolve().parent.parent / "web"
_TEMPLATES_DIR = _WEB_DIR / "templates"
_STATIC_DIR = _WEB_DIR / "static"

_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


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
_storage = PostgresStorage(settings.DATABASE_URL)
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

_feedback_repository = FeedbackRepository(_storage)

# ReadingService: usa el almacenamiento ASÍNCRONO, porque app/reading corre dentro del event
# loop. Convive con `_storage`, el síncrono, que sirve a los repositorios aún no migrados.
_async_storage = AsyncPostgresStorage(settings.DATABASE_URL)
_reading_service = build_reading_service(_async_storage)

# Rate limiter por IP (en memoria): protege el servidor de floods, aparte de la cuota/
# presupuesto por usuario. Los endpoints caros (start/answer) tienen su propio tope.
_rate_limiter = IpRateLimiter(
    {
        "global": settings.RATE_LIMIT_GLOBAL_PER_MIN,
        "start": settings.RATE_LIMIT_START_PER_MIN,
        "answer": settings.RATE_LIMIT_ANSWER_PER_MIN,
    }
)
# (método, ruta) -> scope extra (además del 'global' que aplica a todo el tráfico).
_RATE_SCOPES = {
    ("POST", "/conversation/start"): "start",
    ("POST", "/conversation/answer"): "answer",
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Al arrancar intenta crear la tabla si falta (uso standalone); si Postgres está caído,
    lo registra y sigue: en docker-compose la tabla ya viene del init.sql.

    Además levanta la ingesta de textos de lectura como tarea de fondo. Va acá y no en un
    proceso aparte porque no necesita uno: es un `sleep` largo entre corridas. Se cancela al
    apagar, y el `await` posterior espera a que termine de verdad."""
    # Va acá y no al importar el módulo: uvicorn configura su propio logging al arrancar, y
    # si lo hiciéramos antes nos lo pisaría.
    configure_logging()
    try:
        _storage.init_schema()
    except Exception:
        logger.exception("No se pudo inicializar el esquema de Postgres; ¿está la BD arriba?")

    source, store = build_default_ingest()
    ingest_task = asyncio.create_task(ingest_loop(source, store))
    try:
        yield
    finally:
        ingest_task.cancel()
        with suppress(asyncio.CancelledError):
            await ingest_task


app = FastAPI(title="review-ingles", lifespan=lifespan)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """Ata un `request_id` al contexto para que TODO lo que se loguee durante el request lo
    lleve, sin que ninguna función tenga que recibirlo ni pasarlo.

    Es lo que permite reconstruir qué pasó en una request concreta cuando algo falla: en el
    agregador se filtra por ese id y aparecen en orden los eventos de todas las capas,
    incluidos los de uvicorn y los de las librerías.

    Respeta un `X-Request-ID` entrante para no romper la traza si hay un proxy adelante que
    ya la empezó.
    """
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    structlog.contextvars.bind_contextvars(request_id=request_id)
    try:
        response = await call_next(request)
    finally:
        # Limpiar siempre: el contexto vive en la task, y sin esto un id podría filtrarse a
        # otro request si el worker reutiliza el contexto.
        structlog.contextvars.clear_contextvars()
    response.headers["X-Request-ID"] = request_id
    return response


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    """Aplica el rate limit por IP antes de cada request: el tope global a todo el tráfico
    y, en los endpoints caros, además su tope específico. Al excederse corta con 429 y un
    motivo tipado ('rate_limited') más el header Retry-After."""
    ip = client_ip(request)
    scopes = ["global"]
    extra = _RATE_SCOPES.get((request.method, request.url.path))
    if extra:
        scopes.append(extra)
    for scope in scopes:
        retry_after = _rate_limiter.hit(ip, scope)
        if retry_after is not None:
            return JSONResponse(
                status_code=429,
                content={"detail": {"reason": "rate_limited"}},
                headers={"Retry-After": str(retry_after)},
            )
    return await call_next(request)


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


def get_reading_service() -> ReadingService:
    """Dependencia FastAPI: entrega el servicio de la práctica de lectura."""
    return _reading_service


def get_feedback_repository() -> FeedbackRepository:
    """Dependencia FastAPI: entrega el repositorio del feedback del piloto."""
    return _feedback_repository


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
            conversation_id, question, question_number, total_questions = service.start(
                payload.user_context, payload.max_questions
            )
    except ConversationError as error:
        raise HTTPException(status_code=error.status, detail=str(error))

    limits.record_conversation_start(user_id, conversation_id)
    input_tokens, output_tokens = _gemini_tokens(callback)
    limits.record_gemini_usage(user_id, conversation_id, "synthesis", input_tokens, output_tokens)

    return {
        "conversation_id": conversation_id,
        "question": question,
        "question_number": question_number,
        "total_questions": total_questions,
    }


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


# --- práctica de lectura --------------------------------------------------------------

@app.get("/reading/random")
async def reading_random(
    user_id: str = Depends(get_user_id),
    reading: ReadingService = Depends(get_reading_service),
    limits: LimitsService = Depends(get_limits_service),
) -> dict:
    """Entrega un texto al azar del catálogo, ya recortado al extracto que se lee.

    Consulta los límites para avisar temprano si no se va a poder evaluar, pero NO consume
    cuota: pedir un texto no cuesta dinero, evaluarlo sí.

    Es `async def` porque el repositorio de lectura usa psycopg asíncrono; por eso la llamada
    a `limits`, que es sincrónica y va a Postgres, se aparta a un hilo: dentro del event loop
    bloquearía a todos los demás usuarios mientras dura la consulta.
    """
    try:
        decision = await asyncio.to_thread(limits.check_can_read, user_id)
    except Exception:
        logger.exception("check_can_read falló (¿Postgres?); se corta conservador como 'paused'.")
        raise HTTPException(status_code=429, detail={"reason": "paused"})

    if not decision.allowed:
        raise HTTPException(status_code=429, detail={"reason": decision.reason})

    try:
        return await reading.random_excerpt()
    except ReadingError as error:
        raise HTTPException(status_code=error.status, detail=str(error))


@app.post("/feedback", status_code=201)
def feedback_create(
    payload: FeedbackRequest,
    user_id: str = Depends(get_user_id),
    repo: FeedbackRepository = Depends(get_feedback_repository),
) -> dict:
    """Guarda el formulario de feedback del piloto con la identidad del navegador (X-User-Id)."""
    feedback_id = repo.save(user_id, payload)
    return {"id": feedback_id}


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


# --- frontend ------------------------------------------------------------------------
# Los estáticos van bajo /static (no en la raíz) para no tapar las rutas de la API, y cada
# página es un endpoint que renderiza su plantilla.

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    """Sirve la página de la conversación."""
    return _templates.TemplateResponse(request, "index.html")


@app.get("/reading", response_class=HTMLResponse)
def reading_page(request: Request) -> HTMLResponse:
    """Sirve la pantalla de práctica de lectura (dos paneles)."""
    return _templates.TemplateResponse(request, "reading.html")
