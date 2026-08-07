"""El doble en memoria de ReadingTextStore: contrato que consumen la ingesta y el servicio.

No hay test contra Postgres real acá a propósito (la suite no levanta base); lo que se
verifica es que el doble cumpla el Protocol, para que inyectarlo en los tests del servicio
sea representativo.
"""

from app.reading.repository import ReadingTextStore

from .doubles import InMemoryReadingTextStore, a_text


def test_el_doble_cumple_el_protocol():
    assert isinstance(InMemoryReadingTextStore(), ReadingTextStore)


async def test_random_devuelve_none_con_catalogo_vacio():
    assert await InMemoryReadingTextStore().random() is None


async def test_random_devuelve_id_y_texto():
    store = InMemoryReadingTextStore([a_text()])
    stored = await store.random()
    assert stored.id == 1
    assert stored.text.title == "A title"


async def test_get_devuelve_none_si_el_id_no_existe():
    assert await InMemoryReadingTextStore([a_text()]).get(999) is None


async def test_get_devuelve_el_texto_por_id():
    store = InMemoryReadingTextStore([a_text(title="Uno"), a_text(title="Dos")])
    stored = await store.get(2)
    assert stored.text.title == "Dos"


# --- filtro por nivel máximo ------------------------------------------------------------

async def test_random_sin_filtro_devuelve_cualquiera():
    store = InMemoryReadingTextStore([a_text(level=7)])
    assert (await store.random()).text.level == 7


async def test_random_respeta_el_nivel_maximo():
    store = InMemoryReadingTextStore([a_text(level=7), a_text(level=4)])
    assert (await store.random(max_level=5)).text.level == 4


async def test_random_excluye_los_textos_sin_nivel_al_filtrar():
    """'No sé el nivel' no es 'nivel fácil': podría ser un 8."""
    store = InMemoryReadingTextStore([a_text(level=None)])
    assert await store.random(max_level=5) is None


async def test_random_incluye_los_textos_sin_nivel_si_no_hay_filtro():
    store = InMemoryReadingTextStore([a_text(level=None)])
    assert (await store.random()) is not None
