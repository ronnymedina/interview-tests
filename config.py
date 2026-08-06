"""Unico lugar del proyecto donde se leen variables de entorno.

El resto de los archivos hace `from config import settings` y recibe valores ya tipados y
validados. `settings` es un singleton: importarlo desde cualquier lado devuelve el mismo
objeto, asi que los tests pueden parchear un valor con
`monkeypatch.setattr(settings, "CAMPO", ...)` sin importar quien lo haya importado.

Que la validacion la haga pydantic-settings y no un `int(os.getenv(...))` cambia el modo de
fallar: con un valor invalido el servidor no arranca y el error dice exactamente que campo
esta mal y por que, en vez de reventar con un ValueError sin contexto en la primera linea
que lo use.
"""

import sys
from typing import Literal

from dotenv import load_dotenv
from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# pydantic-settings lee el .env para sus propios campos, pero NO lo carga en os.environ.
# Este load_dotenv() sigue haciendo falta: LangChain lee las variables de LangSmith
# directamente del entorno, y sin esto las trazas se apagan en silencio.
load_dotenv()


class Settings(BaseSettings):
    """Configuracion completa del proyecto, leida del entorno y del .env."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # El entorno trae muchas variables que no son nuestras (incluidas las de LangSmith,
        # que consume LangChain por su cuenta); ignorarlas en vez de fallar.
        extra="ignore",
        case_sensitive=True,
    )

    # --- Azure Speech --------------------------------------------------------------------
    # Sin la key el servidor arranca igual, pero el primer intento de evaluacion devuelve un
    # error explicativo.
    AZURE_SPEECH_KEY: str = ""
    AZURE_SPEECH_REGION: str = "eastus"

    # Idioma que se evalua. "en-US" es el que tiene soporte mas completo (silabas, prosodia).
    SPEECH_LANGUAGE: str = "en-US"

    # --- Almacenamiento ------------------------------------------------------------------
    # Legacy (primera version, raiz): SQLite de los intentos de pronunciacion.
    DB_PATH: str = "attempts.db"

    # Modulo migrado (app/): Postgres. Cadena que consume psycopg. En docker-compose la
    # inyecta el servicio; en local apunta al Postgres que quieras.
    DATABASE_URL: str = "postgresql://review:review@localhost:5432/review_ingles"

    PORT: int = 8000

    # --- Logging (structlog) -------------------------------------------------------------
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # "console" (legible, con colores), "json" (una linea por evento, para agregadores) o
    # "auto": consola si la salida es una terminal, json si esta redirigida o es un contenedor.
    LOG_FORMAT: Literal["auto", "console", "json"] = "auto"

    # Unified service tagging de Datadog. Los nombres DD_* son los que el agente de Datadog
    # ya inyecta solo en un despliegue tipico, asi que se leen de ahi primero; SERVICE_NAME
    # y compania quedan como alias para no atar el proyecto a un proveedor.
    SERVICE_NAME: str = Field(
        default="review-ingles",
        validation_alias=AliasChoices("DD_SERVICE", "SERVICE_NAME"),
    )
    ENVIRONMENT: str = Field(
        default="development",
        validation_alias=AliasChoices("DD_ENV", "ENVIRONMENT"),
    )
    SERVICE_VERSION: str = Field(
        default="0.1.0",
        validation_alias=AliasChoices("DD_VERSION", "SERVICE_VERSION"),
    )

    # --- Conversacion (Gemini) -----------------------------------------------------------
    # Sin la key el servidor arranca igual y los endpoints de conversacion responden 503.
    GEMINI_API_KEY: str = ""

    # Modelo del chat en formato "proveedor:modelo" que consume init_chat_model. Cambiar de
    # proveedor (p. ej. "openai:gpt-5-nano") es cambiar esta variable, no el codigo.
    CHAT_MODEL: str = "google_genai:gemini-2.5-flash"

    # LangSmith (observabilidad). Estas variables NO se declaran como campos a proposito:
    # LangChain las consume directamente del entorno, y el load_dotenv() de arriba ya las
    # carga. Se listan para que este archivo siga siendo el mapa unico de la configuracion:
    #   LANGSMITH_TRACING=true   LANGSMITH_ENDPOINT   LANGSMITH_API_KEY   LANGSMITH_PROJECT

    # --- Piloto demo: tarifas, presupuesto y cuota ---------------------------------------
    # Las tarifas son aproximaciones para el piloto; el costo real se ajusta cambiando la
    # env, no el codigo. "PER_1K" = precio por cada 1000 tokens.
    GEMINI_PRICE_INPUT_PER_1K: float = 0.0003
    GEMINI_PRICE_OUTPUT_PER_1K: float = 0.0025

    # Azure Pronunciation Assessment se cobra por duracion de audio. ~$1/hora.
    AZURE_SPEECH_PRICE_PER_SECOND: float = 0.000278

    # Presupuesto en dos niveles: al superar el diario la app pausa hasta el dia siguiente
    # (se rehabilita sola al cambiar la fecha); al alcanzar el total pausa hasta
    # intervencion manual. Mismo banner neutro para ambos.
    DAILY_BUDGET_USD: float = 3.0
    TOTAL_BUDGET_USD: float = 10.0

    # Cuota de conversaciones de por vida por usuario (X-User-Id).
    USER_CONVERSATION_QUOTA: int = 3

    # Cuota de lecturas evaluadas, tambien de por vida por usuario. Es un contador aparte a
    # proposito: leer no debe gastar las conversaciones, son modalidades distintas y
    # mezclarlas seria confuso. El presupuesto en dolares si es compartido.
    USER_READING_QUOTA: int = 10

    # Limites del turno/conversacion.
    MAX_ANSWER_SECONDS: int = 30
    MAX_QUESTIONS: int = 5

    # --- Rate limiting por IP ------------------------------------------------------------
    # Proteccion del servidor, independiente de la cuota y el presupuesto: requests por
    # minuto y por IP. Uno global para todo el trafico, y topes mas estrictos en los
    # endpoints caros (arrancan/avanzan la conversacion con LLM + Azure).
    RATE_LIMIT_GLOBAL_PER_MIN: int = 60
    RATE_LIMIT_START_PER_MIN: int = 10
    RATE_LIMIT_ANSWER_PER_MIN: int = 20
    # Mismo tope que el de responder: cubre una operacion equivalente (subir audio y esperar
    # a que Azure lo evalue).
    RATE_LIMIT_READING_PER_MIN: int = 20

    # --- Practica de lectura: ingesta del catalogo (app/reading) --------------------------
    # El catalogo se puebla con un job periodico, no scrapeando en vivo: asi una caida de la
    # fuente degrada a "textos algo viejos" en vez de a "feature caida".

    # Cada cuantas horas repite la ingesta la tarea de fondo del servidor.
    READING_INGEST_INTERVAL_HOURS: int = Field(default=24, gt=0)

    # Cuantas paginas se recorren por categoria. La ingesta corta antes si una pagina no
    # trae articulos, asi que subir esto no cuesta requests de mas.
    READING_INGEST_PAGES: int = Field(default=3, gt=0)

    # Rango de dificultad que se ingiere. Se aplica como filtro en la URL de la fuente, asi
    # que lo que no entra en el rango ni siquiera se descarga.
    READING_MIN_LEVEL: int = Field(default=4, ge=1)
    READING_MAX_LEVEL: int = Field(default=7, ge=1)

    # Tope de articulos por corrida y cuantos se bajan a la vez. Ambos son cortesia con la
    # fuente: el catalogo se llena igual en un par de dias.
    READING_INGEST_MAX_ARTICLES: int = Field(default=60, gt=0)
    READING_INGEST_CONCURRENCY: int = Field(default=5, gt=0)

    READING_HTTP_TIMEOUT_SECONDS: float = Field(default=20.0, gt=0)

    # Engoo es una SPA: con un User-Agent normal devuelve solo el shell vacio, y el HTML
    # renderizado aparece unicamente al declararse Googlebot. Es una dependencia de un
    # comportamiento no documentado; por eso es configurable.
    READING_USER_AGENT: str = (
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
    )

    # --- Practica de lectura: lo que se lee y cuanto se puede leer ------------------------
    # Tamano del extracto que se lee en voz alta. 120 palabras son ~40-60 s de lectura:
    # suficiente para que Azure tenga senal, y corto para que el usuario no se canse.
    # El articulo se guarda completo; el recorte se calcula al servir (app/reading/excerpt).
    READING_MAX_WORDS: int = Field(default=120, gt=0)

    @property
    def log_format_resolved(self) -> Literal["console", "json"]:
        """Resuelve LOG_FORMAT="auto" mirando si la salida es una terminal.

        En docker-compose la salida no es un TTY, asi que el contenedor emite JSON sin que
        haya que configurarle nada.
        """
        if self.LOG_FORMAT != "auto":
            return self.LOG_FORMAT
        return "console" if sys.stderr.isatty() else "json"


settings = Settings()
