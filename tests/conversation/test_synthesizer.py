"""`focus_points` recorta el brief a lo único que el revisor necesita: los `### Puntos`.

El `### Contexto` es el material que pegó el alumno (un CV, varios PDF). Mandárselo al
revisor no aporta a evaluar su inglés y multiplica los tokens de cada revisión.
"""

from app.conversation.synthesizer import focus_points

UN_BRIEF = (
    "### Puntos que quiero estudiar y sobre los que debo recibir feedback\n"
    "- Pasado simple\n"
    "- Contracciones\n"
    "\n"
    "### Contexto\n"
    "Soy backend developer. Trabajé en una API de pagos con Python y Postgres."
)


def test_devuelve_la_seccion_de_puntos():
    assert focus_points(UN_BRIEF) == (
        "### Puntos que quiero estudiar y sobre los que debo recibir feedback\n"
        "- Pasado simple\n"
        "- Contracciones"
    )


def test_deja_afuera_el_contexto():
    resultado = focus_points(UN_BRIEF)
    assert "### Contexto" not in resultado
    assert "backend developer" not in resultado


def test_sin_el_marcador_cae_al_brief_completo():
    """Un brief malformado degrada a 'el revisor ve de más', nunca a 'no sabe qué evaluar'."""
    brief = "- Pasado simple\n- Contracciones"
    assert focus_points(brief) == brief


def test_recorta_los_bordes():
    assert focus_points("\n  ### Puntos\n- Pasado  \n\n### Contexto\nx") == "### Puntos\n- Pasado"


def test_un_brief_vacio_da_string_vacio():
    assert focus_points("") == ""
