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

    async def random(self):
        if not self._rows:
            return None
        reading_id = next(iter(self._rows))
        return StoredReadingText(id=reading_id, text=self._rows[reading_id])

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
