"""Configuración única del logging del proyecto, sobre structlog.

Se llama una vez al arrancar (el servidor en su `lifespan`, el script de ingesta en su
`main`). El resto del código solo hace `logger = structlog.get_logger(__name__)` y loguea
eventos con datos como claves, en vez de armar strings.

## El contrato

Todo evento sale con los mismos campos, y con los nombres que esperan los agregadores
(Datadog, Loki, Elastic). structlog por defecto no los usa: emite `event` donde Datadog
espera `message`, y `level` donde espera `status`; sin renombrarlos los logs entran pero
quedan sin severidad ni mensaje reconocidos, y se pierde el filtrado por nivel.

    timestamp                                 ISO-8601 en UTC
    status                                    nivel (Datadog lo usa para severidad)
    message                                   nombre del evento
    service / env / version                   unified service tagging
    logger.name / logger.thread_name          origen
    error.kind / error.message / error.stack  excepciones, como Datadog las agrupa
    request_id                                correlación, si el evento ocurre en un request

## Por qué pasa todo por el mismo formateador

Los logs no vienen solo de nuestro código: uvicorn, httpx y psycopg emiten por el `logging`
de la stdlib. Si structlog formateara únicamente lo nuestro, la salida sería una mezcla de
dos formatos, y en JSON eso significa líneas que el agregador no puede parsear.

`ProcessorFormatter` resuelve eso: se instala como formateador del handler raíz, y los
registros ajenos pasan por `foreign_pre_chain` para que terminen cumpliendo el mismo
contrato que los nuestros.

## Formato

`LOG_FORMAT=auto` (el default) usa consola con colores si la salida es una terminal, y JSON
si no. Con eso, desarrollo local se lee cómodo y el contenedor emite JSON sin configurar
nada, porque ahí la salida no es un TTY.
"""

import logging

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

from config import settings


def _add_service_context(
    _logger: WrappedLogger, _method: str, event_dict: EventDict
) -> EventDict:
    """Agrega el unified service tagging a cada evento.

    Va en cada línea y no como tag del agente porque así los logs siguen siendo
    interpretables cuando se leen sueltos: un archivo volcado o un `docker logs` conserva de
    qué servicio y entorno salieron.
    """
    event_dict["service"] = settings.SERVICE_NAME
    event_dict["env"] = settings.ENVIRONMENT
    event_dict["version"] = settings.SERVICE_VERSION
    return event_dict


def _drop_uvicorn_noise(
    _logger: WrappedLogger, _method: str, event_dict: EventDict
) -> EventDict:
    """Descarta `color_message`, que uvicorn pasa por `extra`.

    Es el mismo mensaje que `message` pero con códigos ANSI adentro. En consola no se ve
    porque nadie lo imprime, pero en JSON viaja al agregador y ensucia cada evento de
    uvicorn con una copia ilegible.
    """
    event_dict.pop("color_message", None)
    return event_dict


def _rename_logger_fields(
    _logger: WrappedLogger, _method: str, event_dict: EventDict
) -> EventDict:
    """Mueve `logger`/`thread_name` a los nombres `logger.name` y `logger.thread_name`.

    Son atributos estándar: con esos nombres, Datadog los indexa y los ofrece como faceta
    sin que haya que declararlos a mano.
    """
    if (name := event_dict.pop("logger", None)) is not None:
        event_dict["logger.name"] = name
    if (thread := event_dict.pop("thread_name", None)) is not None:
        event_dict["logger.thread_name"] = thread
    return event_dict


def _format_exception(
    _logger: WrappedLogger, _method: str, event_dict: EventDict
) -> EventDict:
    """Traduce la excepción al trío `error.kind` / `error.message` / `error.stack`.

    Es el formato con el que Datadog agrupa errores: sin `error.kind` no puede juntar las
    ocurrencias del mismo fallo, y quedan como líneas sueltas sin relación entre sí.

    Corre después de `dict_tracebacks`, que deja la excepción ya estructurada en la clave
    `exception`.
    """
    tracebacks = event_dict.pop("exception", None)
    if not tracebacks:
        return event_dict
    # dict_tracebacks devuelve una lista (una entrada por excepción encadenada); la última
    # es la que se levantó, que es la que interesa como identidad del error.
    if isinstance(tracebacks, list) and tracebacks:
        last = tracebacks[-1]
        event_dict["error.kind"] = last.get("exc_type", "")
        event_dict["error.message"] = last.get("exc_value", "")
        event_dict["error.stack"] = structlog.processors.JSONRenderer()(
            _logger, _method, {"frames": tracebacks}
        )
    else:
        # Con `format_exc_info` la excepción llega como string ya formateado.
        event_dict["error.stack"] = str(tracebacks)
    return event_dict


# Procesadores que se aplican a TODOS los eventos, vengan de structlog o de la stdlib.
_SHARED: list[Processor] = [
    # merge_contextvars primero: así lo que se ató al contexto (request_id) está disponible
    # para todo lo que sigue.
    structlog.contextvars.merge_contextvars,
    structlog.stdlib.add_log_level,
    structlog.stdlib.add_logger_name,
    # El hilo importa acá: el SDK de Azure es bloqueante y sus llamadas van dentro de
    # `asyncio.to_thread`, así que sin este campo no se distingue qué corrió en el event
    # loop y qué en un worker.
    structlog.processors.CallsiteParameterAdder(
        {structlog.processors.CallsiteParameter.THREAD_NAME}
    ),
    structlog.processors.TimeStamper(fmt="iso", utc=True, key="timestamp"),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.dict_tracebacks,
    _format_exception,
    _rename_logger_fields,
    _drop_uvicorn_noise,
    # Al final: renombra `level`→`status` y `event`→`message`, los dos nombres que esperan
    # los agregadores.
    structlog.processors.EventRenamer("message"),
]

# Loggers de terceros que hablan de más. httpx emite una línea INFO por request, lo que en
# una corrida de ingesta son decenas de líneas que tapan lo que importa; sus fallos reales
# siguen llegando por las excepciones que ya manejamos.
_NOISY = ("httpx", "httpcore", "urllib3")

# uvicorn instala sus propios handlers y corta la propagación. Se los vaciamos para que sus
# mensajes suban al handler raíz y salgan cumpliendo el mismo contrato.
_UVICORN = ("uvicorn", "uvicorn.error", "uvicorn.access")

_configured = False


def _level_to_status(
    _logger: WrappedLogger, _method: str, event_dict: EventDict
) -> EventDict:
    """Renombra `level` a `status`, que es el campo de severidad estándar."""
    if (level := event_dict.pop("level", None)) is not None:
        event_dict["status"] = level
    return event_dict


def configure_logging() -> None:
    """Deja el logging listo. Es idempotente: llamarla dos veces no duplica handlers.

    Importa que sea idempotente porque el servidor la llama en el `lifespan` y `--reload`
    puede reejecutar el módulo; sin la guarda, cada evento saldría repetido.
    """
    global _configured
    if _configured:
        return

    to_console = settings.log_format_resolved == "console"
    renderer: Processor = (
        # En consola el nivel se ve mejor como columna coloreada que como un campo más, así
        # que ahí no se renombra a `status`: eso es para el agregador.
        structlog.dev.ConsoleRenderer(event_key="message")
        if to_console
        else structlog.processors.JSONRenderer()
    )

    chain: list[Processor] = list(_SHARED)
    if not to_console:
        # Solo para el agregador. En consola serían tres campos constantes repitiéndose en
        # cada línea, que es ruido: en local siempre valen lo mismo.
        chain.append(_add_service_context)
        chain.append(_level_to_status)

    formatter = structlog.stdlib.ProcessorFormatter(
        # Los eventos de structlog ya pasaron por la cadena; los ajenos entran por acá para
        # terminar con los mismos campos.
        foreign_pre_chain=[structlog.stdlib.ExtraAdder(), *chain],
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(settings.LOG_LEVEL)

    for name in _UVICORN:
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True

    for name in _NOISY:
        logging.getLogger(name).setLevel(logging.WARNING)

    structlog.configure(
        processors=[
            *chain,
            # Deja el evento listo para ProcessorFormatter, que hace el render de verdad.
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    _configured = True
