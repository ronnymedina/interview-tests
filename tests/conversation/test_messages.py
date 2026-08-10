"""content_text normaliza el `content` de un mensaje del LLM a texto plano.

LangChain declara `content` como `str | list[str | dict]`, así que el mismo campo llega en
tres formas distintas según el proveedor y si la respuesta es multimodal. Esta función es el
único punto donde eso se aplana: si se rompe, el tutor devuelve texto vacío o revienta con
un TypeError en medio de la conversación.
"""

from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.conversation.messages import content_text, render_transcript


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


def una_conversacion():
    """El historial tal como lo arma `initial_state` más dos turnos completos."""
    return [
        SystemMessage("You are an English tutor."),
        HumanMessage("### Puntos\n- Pasado simple\n\n### Contexto\nMi CV"),
        AIMessage("What did you work on last week?"),
        HumanMessage("I worked in a API for payments."),
        AIMessage("Nice. What was the hardest part?"),
        HumanMessage("The tests was difficult."),
    ]


def test_etiqueta_los_turnos_de_cada_lado():
    assert render_transcript(una_conversacion()) == (
        "Tutor: What did you work on last week?\n"
        "Learner: I worked in a API for payments.\n"
        "Tutor: Nice. What was the hardest part?\n"
        "Learner: The tests was difficult."
    )


def test_descarta_el_system_prompt_del_tutor():
    """El revisor no debe ver las reglas del tutor: son las que lo hacen indulgente."""
    assert "English tutor" not in render_transcript(una_conversacion())


def test_descarta_el_session_brief():
    """El brief entra como primer HumanMessage, pero no es algo que el alumno haya dicho."""
    transcripcion = render_transcript(una_conversacion())
    assert "### Puntos" not in transcripcion
    assert "### Contexto" not in transcripcion


def test_solo_descarta_el_primer_human_message():
    """El segundo HumanMessage ya es una respuesta real y tiene que aparecer."""
    messages = [
        SystemMessage("rules"),
        HumanMessage("el brief"),
        HumanMessage("una respuesta suelta"),
    ]
    assert render_transcript(messages) == "Learner: una respuesta suelta"


def test_aplana_el_contenido_en_bloques():
    """Gemini puede devolver `content` como lista de bloques; se aplana con content_text."""
    messages = [
        SystemMessage("rules"),
        HumanMessage("el brief"),
        AIMessage([{"type": "text", "text": "Tell me more."}]),
    ]
    assert render_transcript(messages) == "Tutor: Tell me more."


def test_una_lista_vacia_da_string_vacio():
    """No es alcanzable por el flujo real, pero el helper no asume."""
    assert render_transcript([]) == ""


def test_una_conversacion_sin_turnos_da_string_vacio():
    assert render_transcript([SystemMessage("rules"), HumanMessage("el brief")]) == ""
