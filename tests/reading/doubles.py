"""Dobles compartidos por los tests de app/reading.

Viven acá y no dentro de un test para que test_service.py no tenga que importar de
test_repository.py: un test que importa de otro test acopla dos suites que deberían poder
moverse por separado.
"""

from app.reading.model import ReadingText
from app.reading.repository import StoredReadingText, UpsertResult


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


def a_text(title="A title", body="One two three.", level=None):
    return ReadingText(
        source="engoo",
        source_url=f"https://x/{title}",
        title=title,
        body=body,
        level=level,
    )
