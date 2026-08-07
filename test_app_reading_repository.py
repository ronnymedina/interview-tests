"""El doble en memoria de ReadingTextStore: contrato que consumen la ingesta y el servicio.

No hay test contra Postgres real acá a propósito (la suite no levanta base); lo que se
verifica es que el doble cumpla el Protocol, para que inyectarlo en los tests del servicio
sea representativo.
"""

from app.reading.model import ReadingText
from app.reading.repository import ReadingTextStore, StoredReadingText, UpsertResult


class InMemoryReadingTextStore:
    """Doble en memoria de ReadingTextStore. `random()` devuelve el primero, no uno al azar:
    un test que dependiera del azar sería un test que falla de vez en cuando."""

    def __init__(self, texts=None):
        self._rows = {}
        self._next_id = 1
        if texts:
            for text in texts:
                self._rows[self._next_id] = text
                self._next_id += 1

    async def upsert_many(self, texts):
        inserted = 0
        for text in texts:
            self._rows[self._next_id] = text
            self._next_id += 1
            inserted += 1
        return UpsertResult(inserted=inserted, updated=0)

    async def count(self):
        return len(self._rows)

    async def random(self, max_level=None):
        for reading_id, text in self._rows.items():
            if max_level is None:
                return StoredReadingText(id=reading_id, text=text)
            # Un texto sin nivel podría ser más difícil de lo pedido: no entra al filtrar.
            if text.level is not None and text.level <= max_level:
                return StoredReadingText(id=reading_id, text=text)
        return None

    async def get(self, reading_id):
        text = self._rows.get(reading_id)
        return None if text is None else StoredReadingText(id=reading_id, text=text)


def a_text(title="A title", body="One two three."):
    return ReadingText(source="engoo", source_url=f"https://x/{title}", title=title, body=body)


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

def a_text_with_level(level, title="T"):
    return ReadingText(
        source="engoo", source_url=f"https://x/{title}", title=title,
        body="One two three.", level=level,
    )


async def test_random_sin_filtro_devuelve_cualquiera():
    store = InMemoryReadingTextStore([a_text_with_level(7)])
    assert (await store.random()).text.level == 7


async def test_random_respeta_el_nivel_maximo():
    store = InMemoryReadingTextStore([a_text_with_level(7), a_text_with_level(4)])
    assert (await store.random(max_level=5)).text.level == 4


async def test_random_excluye_los_textos_sin_nivel_al_filtrar():
    """'No sé el nivel' no es 'nivel fácil': podría ser un 8."""
    store = InMemoryReadingTextStore([a_text_with_level(None)])
    assert await store.random(max_level=5) is None


async def test_random_incluye_los_textos_sin_nivel_si_no_hay_filtro():
    store = InMemoryReadingTextStore([a_text_with_level(None)])
    assert (await store.random()) is not None
