"""Propiedades y casos concretos de make_excerpt (función pura, sin BD ni red)."""

from hypothesis import given
from hypothesis import strategies as st

from app.reading.excerpt import make_excerpt


def test_corta_en_limite_de_oracion():
    body = "One two three. Four five six. Seven eight nine."
    # Con 7 palabras de tope entran las dos primeras oraciones (6 palabras);
    # la tercera las llevaría a 9, así que se descarta entera.
    assert make_excerpt(body, 7) == "One two three. Four five six."


def test_devuelve_el_cuerpo_entero_si_ya_cabe():
    body = "One two three. Four five."
    assert make_excerpt(body, 100) == body


def test_primera_oracion_mas_larga_que_el_tope_corta_por_palabras():
    body = "One two three four five six seven eight."
    # No hay ningún límite de oración que quepa: se corta en la última palabra completa.
    assert make_excerpt(body, 3) == "One two three"


def test_cuerpo_vacio_da_extracto_vacio():
    assert make_excerpt("", 10) == ""
    assert make_excerpt("   \n  ", 10) == ""


def test_respeta_signos_de_interrogacion_y_exclamacion():
    body = "Is this real? Yes it is! And more words here."
    assert make_excerpt(body, 7) == "Is this real? Yes it is!"


@given(
    body=st.text(min_size=0, max_size=500),
    max_words=st.integers(min_value=1, max_value=50),
)
def test_nunca_excede_el_maximo_de_palabras(body, max_words):
    assert len(make_excerpt(body, max_words).split()) <= max_words


@given(
    body=st.text(min_size=0, max_size=500),
    max_words=st.integers(min_value=1, max_value=50),
)
def test_todas_las_palabras_del_extracto_estan_en_el_cuerpo(body, max_words):
    """Nunca parte una palabra por la mitad ni inventa texto."""
    original = body.split()
    for word in make_excerpt(body, max_words).split():
        assert word in original


@given(
    body=st.text(min_size=1, max_size=500),
    max_words=st.integers(min_value=1, max_value=50),
)
def test_es_determinista(body, max_words):
    """Es la propiedad de la que depende que no haga falta cachear el extracto."""
    assert make_excerpt(body, max_words) == make_excerpt(body, max_words)


def test_conserva_los_saltos_de_parrafo():
    """Los artículos de Engoo vienen con párrafos; el extracto no debe aplanarlos."""
    body = "One two three.\n\nFour five six.\n\nSeven eight nine."
    assert make_excerpt(body, 7) == "One two three.\n\nFour five six."


def test_conserva_los_espacios_dobles_del_original():
    body = "One  two three. Four five six. Seven eight."
    assert make_excerpt(body, 6) == "One  two three. Four five six."


def test_corte_por_palabras_tambien_conserva_los_espacios():
    """Cuando ni la primera oración cabe, el recorte sigue siendo texto literal."""
    body = "One  two three four five."
    assert make_excerpt(body, 3) == "One  two three"


@given(
    body=st.text(min_size=0, max_size=500),
    max_words=st.integers(min_value=1, max_value=50),
)
def test_el_extracto_es_un_prefijo_literal_del_cuerpo(body, max_words):
    """La garantía de la que dependen las demás: no se pierde ni un espacio ni un salto."""
    assert body.strip().startswith(make_excerpt(body, max_words))
