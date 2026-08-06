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
    y no una frase truncada a media idea. Si ni la primera oración cabe, corta por palabras:
    un extracto algo abrupto es mejor que uno vacío.
    """
    words = body.split()
    if not words:
        return ""
    if len(words) <= max_words:
        return body.strip()

    excerpt = ""
    count = 0
    for sentence in _SENTENCE_END.split(body.strip()):
        sentence_words = len(sentence.split())
        if count + sentence_words > max_words:
            break
        excerpt = f"{excerpt} {sentence}".strip() if excerpt else sentence
        count += sentence_words

    if not excerpt:
        # Ni la primera oración cabe: se corta en la última palabra completa.
        return " ".join(words[:max_words])
    return excerpt
