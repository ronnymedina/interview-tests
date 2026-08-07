"""content_text normaliza el `content` de un mensaje del LLM a texto plano.

LangChain declara `content` como `str | list[str | dict]`, así que el mismo campo llega en
tres formas distintas según el proveedor y si la respuesta es multimodal. Esta función es el
único punto donde eso se aplana: si se rompe, el tutor devuelve texto vacío o revienta con
un TypeError en medio de la conversación.
"""

from types import SimpleNamespace

from app.conversation.messages import content_text


def a_message(content):
    """Un mensaje del LLM: a `content_text` solo le importa el atributo `content`."""
    return SimpleNamespace(content=content)


def test_devuelve_el_string_tal_cual():
    assert content_text(a_message("hello there")) == "hello there"


def test_no_recorta_el_string_plano():
    """El strip solo aplica al camino de bloques: un string ya viene como lo mandó el LLM."""
    assert content_text(a_message("  hello  ")) == "  hello  "


def test_aplana_una_lista_de_strings():
    assert content_text(a_message(["hello ", "there"])) == "hello there"


def test_aplana_una_lista_de_bloques():
    """La forma que devuelve Gemini cuando responde en bloques."""
    message = a_message([{"type": "text", "text": "hello "}, {"type": "text", "text": "there"}])
    assert content_text(message) == "hello there"


def test_mezcla_strings_y_bloques():
    assert content_text(a_message(["hello ", {"text": "there"}])) == "hello there"


def test_ignora_los_bloques_sin_texto():
    """Un bloque de imagen no aporta texto, pero no debe romper ni dejar un None colado."""
    message = a_message([{"type": "image_url", "image_url": "x"}, {"text": "hello"}])
    assert content_text(message) == "hello"


def test_ignora_los_bloques_de_tipo_inesperado():
    """Ni str ni dict: se descarta en vez de propagar un TypeError al grafo."""
    assert content_text(a_message([42, {"text": "hello"}, None])) == "hello"


def test_recorta_los_bordes_al_unir_bloques():
    assert content_text(a_message([{"text": "  hello there  "}])) == "hello there"


def test_lista_vacia_da_string_vacio():
    assert content_text(a_message([])) == ""
