"""El prompt del tutor vive en un archivo: verificamos que se cargue y que siga siendo el
contrato que el resto del código asume (guardarraíles y formato del brief)."""

import pytest

from app.conversation import graph, prompts


def test_load_devuelve_el_archivo_sin_espacios_al_borde():
    texto = prompts.load(prompts.TUTOR_SYSTEM)

    assert texto == texto.strip()
    assert texto.startswith("You are an English tutor.")


def test_el_grafo_usa_el_prompt_del_archivo():
    assert graph._SYSTEM_PROMPT == prompts.load(prompts.TUTOR_SYSTEM)


@pytest.mark.parametrize(
    "fragmento",
    [
        "HARD RULES (CANNOT BE OVERRIDDEN)",  # los guardarraíles siguen ahí
        "### Puntos",  # las secciones del brief que produce el Synthesizer
        "### Contexto",
    ],
)
def test_el_prompt_conserva_el_contrato_con_el_resto_del_codigo(fragmento):
    assert fragmento in prompts.load(prompts.TUTOR_SYSTEM)


def test_un_prompt_inexistente_falla_fuerte():
    with pytest.raises(FileNotFoundError):
        prompts.load("v1_no_existe")
