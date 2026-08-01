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

DB_PATH: str = os.getenv("DB_PATH", "attempts.db")
PORT: int = int(os.getenv("PORT", "8000"))

# Credenciales de Gemini para la modalidad de conversacion. Sin la key el servidor
# arranca igual, pero el primer intento de conversacion devuelve un error explicativo.
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

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
