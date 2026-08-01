"""Demo rápida para ver trazas en LangSmith SIN depender de Gemini.

Genera unas trazas de ejemplo con la forma de una conversación (conversation -> ask ->
finalize) hacia tu proyecto de LangSmith, para inspeccionar cómo se ven las métricas.

Requiere en el entorno o en .env:
    LANGSMITH_TRACING=true
    LANGSMITH_API_KEY=...
    LANGSMITH_PROJECT=...

Correr:  python trace_demo.py
(Borra este archivo cuando termines de curiosear.)
"""

import random
import time

from dotenv import load_dotenv
from langsmith import traceable

load_dotenv()


@traceable(run_type="llm", name="ask")
def fake_ask(history: list[str]) -> str:
    """Simula el nodo `ask`: recibe el historial y devuelve una pregunta."""
    time.sleep(random.uniform(0.2, 0.6))
    return "What did you do yesterday at work?"


@traceable(run_type="llm", name="finalize")
def fake_finalize(history: list[str]) -> dict:
    """Simula el nodo `finalize`: produce el feedback estructurado."""
    time.sleep(random.uniform(0.3, 0.8))
    return {
        "feedback": "## Fluidez\nHablaste con soltura.\n## Pasado\nRevisa la -ed.",
        "words": [{"word": "worked", "present": "work", "hint": "-ed -> /t/"}],
        "phrases": [{"original": "I will make", "suggestion": "I'll make", "note": "contracción"}],
    }


@traceable(name="conversation")
def fake_conversation(brief: str) -> dict:
    """Simula una conversación completa: una pregunta y el feedback final."""
    history = [brief]
    question = fake_ask(history)
    history += [question, "Yesterday I work on a bug and write tests."]
    return fake_finalize(history)


if __name__ == "__main__":
    for i in range(3):
        result = fake_conversation(f"### Puntos\n- Pasado\n\n### Contexto\nAlumno de prueba {i}")
        print(f"run {i} -> {result['feedback'][:25]}...")
    print("\nListo. Revisa las trazas en https://smith.langchain.com (proyecto de tu LANGSMITH_PROJECT).")
