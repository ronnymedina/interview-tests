"""Prompts del módulo de conversación, versionados en archivos en vez de en el código.

Convención de nombre: ``v<N>_<nombre>.md``. Un cambio que altere el comportamiento del
tutor crea una versión nueva (``v2_...``) en lugar de editar la vigente: así el texto
exacto que produjo una traza vieja sigue existiendo y se puede comparar.

Los prompts van en inglés (son para el LLM) y en Markdown, porque el propio prompt usa
encabezados y listas.
"""

from functools import cache
from pathlib import Path

_DIR = Path(__file__).parent

#: Reglas fijas del tutor. Se cargan como `SystemMessage` y tienen precedencia sobre el
#: brief del alumno.
TUTOR_SYSTEM = "v1_tutor_system"


@cache
def load(name: str) -> str:
    """Devuelve el texto de ``prompts/<name>.md``, leído del disco una sola vez.

    Falla con `FileNotFoundError` si el archivo no existe: es un error de despliegue
    (el prompt no llegó a la imagen) y conviene que se vea en el arranque.
    """
    return (_DIR / f"{name}.md").read_text(encoding="utf-8").strip()
