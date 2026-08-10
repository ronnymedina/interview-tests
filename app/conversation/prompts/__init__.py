"""Conversation prompts, versioned as files instead of inlined in the code.

Naming convention: ``v<N>_<name>.md``. A change that alters the tutor's behaviour creates
a new version (``v2_...``) instead of editing the current one, so the exact text behind an
old trace still exists and can be compared.

Prompts are written in English (they are for the LLM) and in Markdown, because the prompt
itself uses headings and lists.
"""

from pathlib import Path

_DIR = Path(__file__).parent

#: Fixed tutor guardrails. Loaded as a `SystemMessage`, they take precedence over the
#: student's brief.
TUTOR_SYSTEM = "v1_tutor_system"

#: System prompt del revisor general. Define por sí solo qué evaluar; los `### Puntos` del
#: alumno lo refinan. Agregar un revisor especializado (`v1_reviewer_past_tense`) es agregar
#: un archivo y una constante acá.
REVIEWER_GENERAL = "v1_reviewer_general"


def load(name: str) -> str:
    """Return the text of ``prompts/<name>.md``.

    Raises `FileNotFoundError` when the file is missing: that is a deployment error (the
    prompt never made it into the image) and it should surface at startup.
    """
    # NOTE: reads from disk on every call. Today each prompt is loaded once, at import
    # time, so this is not on any hot path. If a caller ever needs it repeatedly (inside
    # a graph node, a request handler), add `@functools.cache` on top of this function.
    return (_DIR / f"{name}.md").read_text(encoding="utf-8").strip()
