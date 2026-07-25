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
