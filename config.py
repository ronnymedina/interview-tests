"""Unico lugar del proyecto donde se leen variables de entorno.

El resto de los archivos importa estas constantes ya tipadas.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# Credenciales del recurso "Speech" de Azure. Sin la key el servidor arranca igual,
# pero el primer intento de evaluacion devuelve un error explicativo.
AZURE_SPEECH_KEY: str = os.getenv("AZURE_SPEECH_KEY", "")
AZURE_SPEECH_REGION: str = os.getenv("AZURE_SPEECH_REGION", "eastus")

# Idioma que se evalua. "en-US" es el que tiene soporte mas completo (silabas, prosodia).
SPEECH_LANGUAGE: str = os.getenv("SPEECH_LANGUAGE", "en-US")

# Legacy (primera version, raiz): SQLite de los intentos de pronunciacion.
DB_PATH: str = os.getenv("DB_PATH", "attempts.db")

# Modulo migrado (app/): Postgres. Cadena de conexion que consume psycopg,
# p. ej. "postgresql://user:pass@host:5432/dbname". En docker-compose la inyecta
# el servicio; en local apunta al Postgres que quieras.
DATABASE_URL: str = os.getenv(
    "DATABASE_URL", "postgresql://review:review@localhost:5432/review_ingles"
)

PORT: int = int(os.getenv("PORT", "8000"))

# Credenciales de Gemini para la modalidad de conversacion. Sin la key el servidor
# arranca igual, pero el primer intento de conversacion devuelve un error explicativo.
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

# Modelo del chat en formato "proveedor:modelo" que consume init_chat_model. Cambiar de
# proveedor (p. ej. "openai:gpt-5-nano") es cambiar esta variable, no el codigo.
CHAT_MODEL: str = os.getenv("CHAT_MODEL", "google_genai:gemini-2.5-flash")

# LangSmith (observabilidad). Estas variables NO se leen aqui a proposito: LangChain las
# consume directamente del entorno. El load_dotenv() de arriba ya carga el .env, asi que
# con declararlas en .env basta para que las trazas se activen. Se listan para que este
# archivo siga siendo el mapa unico de todas las env del proyecto:
#   LANGSMITH_TRACING=true   LANGSMITH_ENDPOINT   LANGSMITH_API_KEY   LANGSMITH_PROJECT

# --- Piloto demo: tarifas, presupuesto y cuota (todas configurables por entorno) --------
# Las tarifas son aproximaciones para el piloto; el costo real se ajusta cambiando la env,
# no el código. "PER_1K" = precio por cada 1000 tokens.
GEMINI_PRICE_INPUT_PER_1K: float = float(os.getenv("GEMINI_PRICE_INPUT_PER_1K", "0.0003"))
GEMINI_PRICE_OUTPUT_PER_1K: float = float(os.getenv("GEMINI_PRICE_OUTPUT_PER_1K", "0.0025"))

# Azure Pronunciation Assessment se cobra por duración de audio. ~$1/hora ≈ 0.000278 $/s.
AZURE_SPEECH_PRICE_PER_SECOND: float = float(
    os.getenv("AZURE_SPEECH_PRICE_PER_SECOND", "0.000278")
)

# Presupuesto de costo en dos niveles: al superar el diario la app pausa hasta el día
# siguiente (se rehabilita solo al cambiar la fecha); al alcanzar el total pausa hasta
# intervención manual. Mismo banner neutro para ambos.
DAILY_BUDGET_USD: float = float(os.getenv("DAILY_BUDGET_USD", "3.0"))
TOTAL_BUDGET_USD: float = float(os.getenv("TOTAL_BUDGET_USD", "10.0"))

# Cuota de conversaciones de por vida por usuario (X-User-Id).
USER_CONVERSATION_QUOTA: int = int(os.getenv("USER_CONVERSATION_QUOTA", "3"))

# Límites del turno/conversación. Se consumen en fases posteriores (endpoints/frontend);
# se declaran acá para mantener config.py como mapa único de la configuración.
MAX_ANSWER_SECONDS: int = int(os.getenv("MAX_ANSWER_SECONDS", "30"))
MAX_QUESTIONS: int = int(os.getenv("MAX_QUESTIONS", "5"))

# --- Rate limiting por IP (protección del servidor, independiente de la cuota/presupuesto).
# Topes de requests por minuto y por IP: uno global para todo el tráfico, y otros más
# estrictos para los endpoints caros (arrancan/avanzan la conversación con LLM + Azure).
RATE_LIMIT_GLOBAL_PER_MIN: int = int(os.getenv("RATE_LIMIT_GLOBAL_PER_MIN", "60"))
RATE_LIMIT_START_PER_MIN: int = int(os.getenv("RATE_LIMIT_START_PER_MIN", "10"))
RATE_LIMIT_ANSWER_PER_MIN: int = int(os.getenv("RATE_LIMIT_ANSWER_PER_MIN", "20"))
