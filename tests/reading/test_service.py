"""El servicio de lectura, con repositorio en memoria y Azure falso (sin BD ni red).

El test que más importa es `test_assess_usa_como_referencia_el_mismo_extracto_que_se_mostro`:
que el texto de referencia se recalcule desde la base es lo que permite no cachearlo.
"""

import pytest

from app.reading.model import ReadingText
from app.reading.service import ReadingError, ReadingService
from app.speech.assessment import SpeechError
from config import settings

from .doubles import InMemoryReadingTextStore

BODY = "One two three. Four five six. Seven eight nine. Ten eleven twelve."


def a_text(title="Daily news", body=BODY, level=5):
    return ReadingText(
        source="engoo",
        source_url="https://engoo.com/a",
        title=title,
        body=body,
        level=level,
        category="World",
        published_at="2026-08-01",
    )


class FakeAssess:
    """Doble de assess_scripted: registra con qué referencia lo llamaron."""

    def __init__(self, result=None, error=None):
        self._result = result or {
            "scores": {"pronunciation": 90.0},
            "words": [],
            "recognized_text": "one two three",
            "audio_seconds": 3.0,
        }
        self._error = error
        self.called_with = None

    def __call__(self, wav_path, reference_text):
        self.called_with = (wav_path, reference_text)
        if self._error:
            raise self._error
        return self._result


@pytest.fixture(autouse=True)
def _max_words(monkeypatch):
    monkeypatch.setattr(settings, "READING_MAX_WORDS", 6)


async def test_random_excerpt_devuelve_el_texto_recortado():
    service = ReadingService(InMemoryReadingTextStore([a_text()]), assess_fn=FakeAssess())
    result = await service.random_excerpt()
    assert result["excerpt"] == "One two three. Four five six."
    assert result["word_count"] == 6
    assert result["title"] == "Daily news"
    assert result["level"] == 5
    assert result["reading_id"] == 1


async def test_catalogo_vacio_es_503():
    service = ReadingService(InMemoryReadingTextStore(), assess_fn=FakeAssess())
    with pytest.raises(ReadingError) as exc:
        await service.random_excerpt()
    assert exc.value.status == 503


async def test_assess_con_id_inexistente_es_404():
    service = ReadingService(InMemoryReadingTextStore([a_text()]), assess_fn=FakeAssess())
    with pytest.raises(ReadingError) as exc:
        await service.assess(999, b"fake wav")
    assert exc.value.status == 404


async def test_assess_usa_como_referencia_el_mismo_extracto_que_se_mostro():
    """La propiedad de la que depende todo el diseño sin caché."""
    assess = FakeAssess()
    service = ReadingService(InMemoryReadingTextStore([a_text()]), assess_fn=assess)
    shown = await service.random_excerpt()

    await service.assess(shown["reading_id"], b"fake wav")

    _wav_path, reference_text = assess.called_with
    assert reference_text == shown["excerpt"]


async def test_un_error_de_azure_conserva_su_codigo_http():
    """Sin la traducción, un 502 de Azure le llegaría al usuario como un 500 genérico."""
    assess = FakeAssess(error=SpeechError("Azure canceló la petición", status=502))
    service = ReadingService(InMemoryReadingTextStore([a_text()]), assess_fn=assess)
    with pytest.raises(ReadingError) as exc:
        await service.assess(1, b"fake wav")
    assert exc.value.status == 502


async def test_sin_voz_detectada_conserva_el_422():
    assess = FakeAssess(error=SpeechError("No se detectó voz en el audio.", status=422))
    service = ReadingService(InMemoryReadingTextStore([a_text()]), assess_fn=assess)
    with pytest.raises(ReadingError) as exc:
        await service.assess(1, b"fake wav")
    assert exc.value.status == 422


async def test_assess_devuelve_el_texto_de_referencia_para_pintar_el_diff():
    assess = FakeAssess()
    service = ReadingService(InMemoryReadingTextStore([a_text()]), assess_fn=assess)
    result = await service.assess(1, b"fake wav")
    assert result["reference_text"] == "One two three. Four five six."
    assert result["scores"]["pronunciation"] == 90.0


# --- filtro por nivel máximo ------------------------------------------------------------

async def test_random_excerpt_propaga_el_nivel_maximo():
    store = InMemoryReadingTextStore([a_text(level=7), a_text(level=4)])
    service = ReadingService(store, assess_fn=FakeAssess())
    result = await service.random_excerpt(max_level=5)
    assert result["level"] == 4


async def test_sin_textos_del_nivel_pedido_es_503_con_el_motivo():
    """Devolver uno más difícil sería ignorar lo que el usuario pidió."""
    service = ReadingService(
        InMemoryReadingTextStore([a_text(level=7)]), assess_fn=FakeAssess()
    )
    with pytest.raises(ReadingError) as exc:
        await service.random_excerpt(max_level=4)
    assert exc.value.status == 503
    assert "nivel 4" in str(exc.value)
