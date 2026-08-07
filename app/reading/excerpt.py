"""Recorte del artículo completo al fragmento que el usuario lee en voz alta.

Función pura a propósito: no toca la base, ni la config, ni la red. Eso es lo que permite
recalcular el extracto en la evaluación en vez de guardarlo en una caché en memoria — dado
el mismo cuerpo y el mismo tope, devuelve siempre exactamente el mismo texto, así que el
servidor puede reconstruir el texto que le mostró al usuario a partir del `reading_id`.
"""

import re

# Corta después de . ? o ! seguidos de espacio. No usamos un tokenizador de oraciones real
# (nltk, spacy) porque sería una dependencia pesada para una heurística que, si falla en una
# abreviatura ("Dr. Smith"), solo produce un extracto un poco más corto.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def make_excerpt(body: str, max_words: int) -> str:
    """Devuelve el fragmento inicial de `body` que no pasa de `max_words` palabras.

    Corta en el último límite de oración que quepa, para que el usuario lea algo con sentido
    y no una frase truncada a media idea. Si ni la primera oración cabe, corta tras la última
    palabra completa que entre: un extracto algo abrupto es mejor que uno vacío.

    Devuelve siempre un PREFIJO LITERAL del cuerpo, nunca un texto reconstruido. Esa es la
    diferencia que conserva los saltos de párrafo del artículo: partir en oraciones y volver
    a unirlas con un espacio los borraba todos.
    """
    words = body.split()
    if not words:
        return ""
    if len(words) <= max_words:
        return body.strip()

    text = body.strip()

    # Se avanza oración a oración guardando la última posición de corte que cabe. `cut` es un
    # índice dentro de `text`, no un texto acumulado: por eso lo que hay entre oraciones
    # (espacios, saltos de línea, párrafos en blanco) sobrevive tal cual.
    cut = 0
    count = 0
    start = 0
    for separator in _SENTENCE_END.finditer(text):
        sentence_words = len(text[start : separator.start()].split())
        if count + sentence_words > max_words:
            break
        count += sentence_words
        cut = separator.start()
        start = separator.end()

    if cut:
        return text[:cut]

    # Ni la primera oración cabe. Se corta tras la última palabra completa que entra, otra
    # vez por posición, para no perder los espacios interiores.
    end = 0
    for index, word in enumerate(re.finditer(r"\S+", text)):
        if index == max_words:
            break
        end = word.end()
    return text[:end]
