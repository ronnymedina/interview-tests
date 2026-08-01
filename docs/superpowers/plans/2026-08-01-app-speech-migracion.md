# Migración de `app/speech/` (Azure Pronunciation Assessment) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrar la evaluación de pronunciación de habla libre (Azure) del código legacy de la raíz a un módulo modular `app/speech/`, con responsabilidades separadas y tests, sin tocar todavía endpoints ni frontend.

**Architecture:** Tres capas: `azure_client.py` (único que habla con el SDK de Azure), `assessment.py` (lógica de negocio pura: normaliza scores y arma palabras, sin SDK), `scoring.py` (cola en segundo plano por conversación). Un `SpeechService` inyectable las compone y se construye desde `config`. Nada bloquea el turno de la conversación: el scoring corre en un `ThreadPoolExecutor` y se agrega al final.

**Tech Stack:** Python 3.11+, `azure-cognitiveservices-speech`, `pytest`, `uv`.

## Global Constraints

- Todas las variables de entorno se leen SOLO en `config.py`; el resto recibe valores ya tipados. Nada de `os.getenv` disperso.
- Esta fase es la de `app/speech/`: no se modifican endpoints (`app/cmd/server.py`), ni el grafo, ni el frontend. Solo se crea el módulo y sus tests.
- El módulo solo migra el modo **unscripted** (habla libre, sin texto de referencia). El modo con referencia del legacy (lectura) queda fuera de alcance del piloto.
- El resultado de la evaluación DEBE incluir `audio_seconds` (duración del audio evaluado) además de lo del legacy, porque una fase posterior lo usa para calcular el costo de Azure.
- Tests en la raíz del repo, nombrados `test_app_speech_*.py`, siguiendo el patrón de `test_app_conversation_service.py` y `test_speech.py`.
- Comando de tests: `uv run pytest <archivo> -v`.
- Ticks de Azure: los offsets/duraciones vienen en unidades de 100 ns → 1 segundo = 10_000_000 ticks.

---

### Task 1: `azure_client.py` + `assessment.py` (evaluación unscripted con cliente falso)

**Files:**
- Create: `app/speech/__init__.py` (vacío por ahora; se llena en Task 3)
- Create: `app/speech/azure_client.py`
- Create: `app/speech/assessment.py`
- Test: `test_app_speech_assessment.py`

**Interfaces:**
- Produces:
  - `app.speech.azure_client.AzureSpeechClient(key: str, region: str, language: str)` con
    `recognize(wav_path: str, reference_text: str) -> dict` y estático
    `word_to_dict(word) -> dict`.
  - `app.speech.azure_client.AzureSpeechError(Exception)`.
  - `app.speech.assessment.SpeechError(Exception)` con atributo `status: int`.
  - `app.speech.assessment.assess_unscripted(wav_path: str, client=None) -> dict` que devuelve
    `{"recognized_text": str, "scores": {"pronunciation","accuracy","fluency","completeness","prosody"}, "words": list[dict], "audio_seconds": float}`.

- [ ] **Step 1: Crear el wrapper del SDK `app/speech/azure_client.py`**

```python
"""Adaptador del SDK de Azure Speech (Pronunciation Assessment) para el módulo app/.

Único punto que habla con el SDK: configura, corre el reconocimiento continuo y devuelve
datos crudos. No hace lógica de negocio (esa vive en assessment.py). Migrado del legacy
azure_speech.py; se conserva solo lo que usa el modo unscripted del piloto.
"""

import json
import threading

import azure.cognitiveservices.speech as speechsdk

# Azure entrega tiempos en unidades de 100 ns. Cada palabra suma este colchón de duración,
# igual que el sample oficial, para el cálculo de fluidez de assessment.py.
_TICK_PADDING = 100000


class AzureSpeechError(Exception):
    """Azure canceló la petición. El mensaje trae el motivo que reportó el servicio."""


class AzureSpeechClient:
    """Cliente delgado sobre el SDK de Azure para evaluar pronunciación.

    Recibe las credenciales ya tipadas (no lee variables de entorno) y expone `recognize()`,
    que corre la evaluación sobre un WAV y devuelve datos crudos.
    """

    def __init__(self, key: str, region: str, language: str):
        self._key = key
        self._region = region
        self._language = language

    def recognize(self, wav_path: str, reference_text: str) -> dict:
        """Corre el pronunciation assessment sobre un WAV y devuelve los datos crudos.

        Devuelve un dict con: `words`, `prosody_scores`, `durations`, `texts`, `start_offset`
        y `end_offset`. Lanza `AzureSpeechError` si Azure cancela.
        """
        speech_config = speechsdk.SpeechConfig(subscription=self._key, region=self._region)
        speech_config.set_property(
            speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs, "1500"
        )
        audio_config = speechsdk.audio.AudioConfig(filename=wav_path)

        pron_config = speechsdk.PronunciationAssessmentConfig(
            reference_text=reference_text,
            grading_system=speechsdk.PronunciationAssessmentGradingSystem.HundredMark,
            granularity=speechsdk.PronunciationAssessmentGranularity.Phoneme,
            enable_miscue=bool(reference_text),
        )
        pron_config.enable_prosody_assessment()
        pron_config.phoneme_alphabet = "IPA"

        recognizer = speechsdk.SpeechRecognizer(
            speech_config=speech_config,
            language=self._language,
            audio_config=audio_config,
        )
        pron_config.apply_to(recognizer)

        return self._run_continuous(recognizer)

    @staticmethod
    def _run_continuous(recognizer: "speechsdk.SpeechRecognizer") -> dict:
        """Corre el reconocimiento continuo y junta los resultados de todos los segmentos."""
        done = threading.Event()
        state = {
            "words": [],
            "prosody_scores": [],
            "durations": [],
            "texts": [],
            "start_offset": 0,
            "end_offset": 0,
            "cancel_error": None,
        }

        def on_recognized(evt: "speechsdk.SpeechRecognitionEventArgs") -> None:
            result = speechsdk.PronunciationAssessmentResult(evt.result)
            state["words"].extend(result.words)
            if result.prosody_score is not None:
                state["prosody_scores"].append(result.prosody_score)
            if evt.result.text:
                state["texts"].append(evt.result.text)

            raw = evt.result.properties.get(
                speechsdk.PropertyId.SpeechServiceResponse_JsonResult
            )
            words_json = json.loads(raw)["NBest"][0]["Words"]
            state["durations"].extend(
                int(w["Duration"]) + _TICK_PADDING
                for w in words_json
                if w["PronunciationAssessment"]["ErrorType"] == "None"
            )
            if state["start_offset"] == 0:
                state["start_offset"] = words_json[0]["Offset"]
            last = words_json[-1]
            state["end_offset"] = last["Offset"] + last["Duration"] + _TICK_PADDING

        def on_canceled(evt: "speechsdk.SpeechRecognitionCanceledEventArgs") -> None:
            details = evt.cancellation_details
            if details.reason == speechsdk.CancellationReason.Error:
                state["cancel_error"] = details.error_details or "sin detalle"
            done.set()

        recognizer.recognized.connect(on_recognized)
        recognizer.session_stopped.connect(lambda evt: done.set())
        recognizer.canceled.connect(on_canceled)

        recognizer.start_continuous_recognition()
        done.wait()
        recognizer.stop_continuous_recognition()

        if state["cancel_error"]:
            raise AzureSpeechError(state["cancel_error"])
        del state["cancel_error"]
        return state

    @staticmethod
    def word_to_dict(word: "speechsdk.PronunciationAssessmentWordResult") -> dict:
        """Convierte una palabra del SDK al dict plano que consume la página."""
        try:
            phonemes = [
                {"phoneme": ph.phoneme, "accuracy": ph.accuracy_score}
                for ph in (word.phonemes or [])
            ]
        except AttributeError:
            phonemes = []
        return {
            "word": word.word,
            "accuracy": word.accuracy_score,
            "error_type": word.error_type,
            "phonemes": phonemes,
        }
```

- [ ] **Step 2: Crear el paquete vacío `app/speech/__init__.py`**

```python
```

(Archivo vacío por ahora; en Task 3 exporta el servicio.)

- [ ] **Step 3: Escribir los tests que fallan `test_app_speech_assessment.py`**

```python
"""Caracteriza assess_unscripted del módulo app/speech con un cliente Azure falso (sin red)."""

import azure.cognitiveservices.speech as speechsdk
import pytest

import config
from app.speech import assessment
from app.speech.azure_client import AzureSpeechError


def rec_word(word, accuracy, error="None"):
    """Un objeto-palabra del SDK como los que devuelve el reconocimiento real."""
    return speechsdk.PronunciationAssessmentWordResult(
        {"Word": word, "PronunciationAssessment": {"ErrorType": error, "AccuracyScore": accuracy}}
    )


def make_state(words, texts, *, durations=None, start=1000, end=1_000_000, prosody=None):
    return {
        "words": words,
        "prosody_scores": prosody or [],
        "durations": durations or [],
        "texts": texts,
        "start_offset": start,
        "end_offset": end,
    }


class FakeClient:
    """Doble de AzureSpeechClient: devuelve un state fijo o lanza un error."""

    def __init__(self, state=None, error=None):
        self._state = state
        self._error = error
        self.called_with = None

    def recognize(self, wav_path, reference_text):
        self.called_with = (wav_path, reference_text)
        if self._error:
            raise self._error
        return self._state


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    """assess_unscripted exige una key; en los tests basta una cualquiera."""
    monkeypatch.setattr(config, "AZURE_SPEECH_KEY", "test-key")


def test_unscripted_passes_empty_reference():
    state = make_state([rec_word("hello", 95.0)], ["hello"], durations=[500000], end=600000)
    client = FakeClient(state)
    assessment.assess_unscripted("a.wav", client=client)
    assert client.called_with == ("a.wav", "")


def test_unscripted_scores_have_no_completeness():
    state = make_state([rec_word("hello", 90.0), rec_word("world", 80.0)],
                       ["hello world"], durations=[500000, 400000], end=1_000_000)
    result = assessment.assess_unscripted("a.wav", client=FakeClient(state))
    assert result["scores"]["completeness"] is None
    assert result["scores"]["accuracy"] == 85.0
    assert result["recognized_text"] == "hello world"


def test_unscripted_reports_audio_seconds():
    # start=1000, end=10_000_000 ticks -> (10_000_000 - 1000)/10_000_000 ≈ 0.9999 s.
    state = make_state([rec_word("hello", 90.0)], ["hello"], durations=[500000],
                       start=1000, end=10_000_000)
    result = assessment.assess_unscripted("a.wav", client=FakeClient(state))
    assert result["audio_seconds"] == pytest.approx(0.9999, abs=1e-3)


def test_unscripted_mispronunciation_below_60():
    state = make_state([rec_word("hello", 40.0)], ["hello"], durations=[500000], end=600000)
    result = assessment.assess_unscripted("a.wav", client=FakeClient(state))
    assert result["words"][0]["error_type"] == "Mispronunciation"


def test_unscripted_with_prosody_averages_and_scores():
    state = make_state(
        [rec_word("hello", 90.0), rec_word("world", 80.0)],
        ["hello world"],
        durations=[500000, 400000],
        end=1_000_000,
        prosody=[70.0, 90.0],
    )
    result = assessment.assess_unscripted("a.wav", client=FakeClient(state))
    assert result["scores"]["prosody"] == 80.0
    assert result["scores"]["pronunciation"] is not None


def test_unscripted_no_speech_raises_422():
    with pytest.raises(assessment.SpeechError) as error:
        assessment.assess_unscripted("a.wav", client=FakeClient(make_state([], [])))
    assert error.value.status == 422


def test_unscripted_missing_key_raises_500(monkeypatch):
    monkeypatch.setattr(config, "AZURE_SPEECH_KEY", "")
    with pytest.raises(assessment.SpeechError) as error:
        assessment.assess_unscripted("a.wav", client=FakeClient(make_state([], [])))
    assert error.value.status == 500


def test_unscripted_cancel_translated_to_502():
    client = FakeClient(error=AzureSpeechError("boom"))
    with pytest.raises(assessment.SpeechError) as error:
        assessment.assess_unscripted("a.wav", client=client)
    assert error.value.status == 502
    assert "boom" in str(error.value)
```

- [ ] **Step 4: Correr los tests y verificar que fallan**

Run: `uv run pytest test_app_speech_assessment.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.speech.assessment'`.

- [ ] **Step 5: Implementar `app/speech/assessment.py`**

```python
"""Lógica de evaluación de pronunciación de habla libre (unscripted).

Pide a Azure la evaluación a través de `AzureSpeechClient` y transforma el resultado crudo
en el dict normalizado que consume la página. No habla directamente con el SDK: toda la
conexión vive en azure_client.py. Migrado del legacy speech.py (solo el modo unscripted),
con un campo extra `audio_seconds` para el cálculo de costo de Azure.
"""

import config
from app.speech.azure_client import AzureSpeechClient, AzureSpeechError

# 1 segundo = 10_000_000 unidades de 100 ns (ticks) de Azure.
_TICKS_PER_SECOND = 10_000_000


class SpeechError(Exception):
    """Error pensado para mostrarse tal cual al usuario. `status` es el código HTTP."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


def assess_unscripted(wav_path: str, client: AzureSpeechClient | None = None) -> dict:
    """Evalúa la pronunciación de un WAV SIN texto de referencia (habla libre).

    Azure reconoce lo dicho y puntúa accuracy/fluency/prosody; no hay completeness (requiere
    referencia). El texto reconocido sirve además como la transcripción de lo que dijo el
    usuario. `client` permite inyectar un doble en los tests.
    """
    if not config.AZURE_SPEECH_KEY:
        raise SpeechError(
            "Falta AZURE_SPEECH_KEY en el archivo .env. Copia .env.example a .env "
            "y pon tu clave de Azure.",
            status=500,
        )

    if client is None:
        client = AzureSpeechClient(
            config.AZURE_SPEECH_KEY, config.AZURE_SPEECH_REGION, config.SPEECH_LANGUAGE
        )

    try:
        state = client.recognize(wav_path, "")
    except AzureSpeechError as error:
        raise SpeechError(f"Azure canceló la petición: {error}", status=502)

    if not state["words"]:
        raise SpeechError(
            "No se detectó voz en el audio. Revisa el micrófono e intenta de nuevo.",
            status=422,
        )

    return _aggregate_unscripted(state)


def _aggregate_unscripted(state: dict) -> dict:
    """Combina los segmentos en un resultado sin referencia (sin completeness ni miscue)."""
    words = list(state["words"])

    # Accuracy por debajo de 60 sin otro error = mala pronunciación.
    for word in words:
        if word.error_type == "None" and word.accuracy_score < 60:
            word._error_type = "Mispronunciation"

    accuracy = sum(w.accuracy_score for w in words) / len(words)

    prosody = (
        sum(state["prosody_scores"]) / len(state["prosody_scores"])
        if state["prosody_scores"]
        else None
    )

    span = state["end_offset"] - state["start_offset"]
    fluency = sum(state["durations"]) / span * 100 if span > 0 else 0.0

    if prosody is not None:
        ordered = sorted([accuracy, fluency, prosody])
        pronunciation = ordered[0] * 0.6 + ordered[1] * 0.2 + ordered[2] * 0.2
    else:
        ordered = sorted([accuracy, fluency])
        pronunciation = ordered[0] * 0.6 + ordered[1] * 0.4

    return {
        "recognized_text": " ".join(state["texts"]),
        "scores": {
            "pronunciation": round(pronunciation, 1),
            "accuracy": round(accuracy, 1),
            "fluency": round(fluency, 1),
            "completeness": None,
            "prosody": round(prosody, 1) if prosody is not None else None,
        },
        "words": [AzureSpeechClient.word_to_dict(w) for w in words],
        "audio_seconds": round(max(0, span) / _TICKS_PER_SECOND, 3),
    }
```

- [ ] **Step 6: Correr los tests y verificar que pasan**

Run: `uv run pytest test_app_speech_assessment.py -v`
Expected: PASS (8 tests).

- [ ] **Step 7: Commit**

```bash
git add app/speech/__init__.py app/speech/azure_client.py app/speech/assessment.py test_app_speech_assessment.py
git commit -m "feat(app/speech): migrar evaluacion unscripted de Azure con audio_seconds"
```

---

### Task 2: `scoring.py` (cola en segundo plano por conversación)

**Files:**
- Create: `app/speech/scoring.py`
- Test: `test_app_speech_scoring.py`

**Interfaces:**
- Consumes: el dict de `assess_unscripted` (con `scores`, `words`, `audio_seconds`).
- Produces:
  - `app.speech.scoring.TurnScoring(assess_fn: Callable[[bytes], dict | None])` con:
    - `enqueue(conversation_id: str, audio_bytes: bytes) -> Future`
    - `collect(conversation_id: str) -> list[dict]`
    - `aggregate(results: list[dict]) -> dict` que devuelve
      `{"scores": {...}, "words": list[dict], "audio_seconds": float}`.

- [ ] **Step 1: Escribir los tests que fallan `test_app_speech_scoring.py`**

```python
"""Tests de la cola de scoring por conversación con una función de evaluación falsa."""

from app.speech.scoring import TurnScoring


def fake_result(pron, acc, fluency, prosody, words, seconds):
    return {
        "recognized_text": "x",
        "scores": {
            "pronunciation": pron,
            "accuracy": acc,
            "fluency": fluency,
            "completeness": None,
            "prosody": prosody,
        },
        "words": words,
        "audio_seconds": seconds,
    }


def test_enqueue_and_collect_returns_all_non_none_results():
    results = iter([
        fake_result(80, 80, 80, 70, [{"word": "a"}], 2.0),
        None,  # un turno sin voz se descarta
        fake_result(90, 90, 90, 90, [{"word": "b"}], 3.0),
    ])
    scoring = TurnScoring(assess_fn=lambda audio: next(results))

    scoring.enqueue("c1", b"111")
    scoring.enqueue("c1", b"222")
    scoring.enqueue("c1", b"333")
    collected = scoring.collect("c1")

    assert len(collected) == 2  # el None se descartó
    # collect vacía la conversación: un segundo collect no trae nada.
    assert scoring.collect("c1") == []


def test_aggregate_averages_scores_and_concatenates_words_and_seconds():
    scoring = TurnScoring(assess_fn=lambda audio: None)
    results = [
        fake_result(80, 80, 80, 70, [{"word": "a"}], 2.0),
        fake_result(90, 90, 90, 90, [{"word": "b"}], 3.0),
    ]
    agg = scoring.aggregate(results)

    assert agg["scores"]["pronunciation"] == 85.0
    assert agg["scores"]["prosody"] == 80.0
    assert [w["word"] for w in agg["words"]] == ["a", "b"]
    assert agg["audio_seconds"] == 5.0


def test_aggregate_ignores_none_prosody_in_average():
    scoring = TurnScoring(assess_fn=lambda audio: None)
    results = [
        fake_result(80, 80, 80, None, [], 1.0),
        fake_result(90, 90, 90, 60, [], 1.0),
    ]
    agg = scoring.aggregate(results)
    assert agg["scores"]["prosody"] == 60.0  # solo el turno con prosody cuenta


def test_aggregate_empty_results_gives_none_scores_and_zero_seconds():
    scoring = TurnScoring(assess_fn=lambda audio: None)
    agg = scoring.aggregate([])
    assert agg["scores"]["pronunciation"] is None
    assert agg["words"] == []
    assert agg["audio_seconds"] == 0.0
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `uv run pytest test_app_speech_scoring.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.speech.scoring'`.

- [ ] **Step 3: Implementar `app/speech/scoring.py`**

```python
"""Cola en segundo plano para evaluar la pronunciación de las respuestas por conversación.

Aísla la acumulación de resultados de la evaluación por conversación: el endpoint encola el
audio de cada turno y NO espera; al final se recogen y agregan. Todo vive en memoria del
proceso (consistente con el checkpointer del grafo). Migrado del legacy scoring.py, ahora
como clase inyectable (recibe la función de evaluación) en vez de módulo global.
"""

import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor


class TurnScoring:
    """Acumula la evaluación de cada respuesta en segundo plano y la agrega al final.

    Recibe `assess_fn`, que evalúa unos bytes de audio y devuelve el dict de la evaluación o
    None si no se pudo (sin voz, error de Azure): ese turno se descarta sin romper el total.
    """

    def __init__(self, assess_fn: Callable[[bytes], dict | None], max_workers: int = 4) -> None:
        self._assess_fn = assess_fn
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._lock = threading.Lock()
        self._pending: dict[str, list[Future]] = {}

    def enqueue(self, conversation_id: str, audio_bytes: bytes) -> Future:
        """Lanza la evaluación del audio en segundo plano y la registra en la conversación."""
        future = self._executor.submit(self._assess_fn, audio_bytes)
        with self._lock:
            self._pending.setdefault(conversation_id, []).append(future)
        return future

    def collect(self, conversation_id: str) -> list[dict]:
        """Espera y devuelve los resultados de todos los turnos encolados (descarta los None)."""
        with self._lock:
            futures = self._pending.pop(conversation_id, [])
        results = [future.result() for future in futures]
        return [result for result in results if result is not None]

    def aggregate(self, results: list[dict]) -> dict:
        """Promedia los scores de todos los turnos, concatena palabras y suma la duración."""
        scores = self._aggregate_scores([result["scores"] for result in results])
        words = [word for result in results for word in result["words"]]
        audio_seconds = round(sum(result["audio_seconds"] for result in results), 3)
        return {"scores": scores, "words": words, "audio_seconds": audio_seconds}

    @staticmethod
    def _aggregate_scores(per_turn_scores: list[dict]) -> dict:
        """Promedia por dimensión, ignorando None (ej. prosody no soportada)."""

        def avg(key: str):
            values = [s[key] for s in per_turn_scores if s.get(key) is not None]
            return round(sum(values) / len(values), 1) if values else None

        return {
            "pronunciation": avg("pronunciation"),
            "accuracy": avg("accuracy"),
            "fluency": avg("fluency"),
            "prosody": avg("prosody"),
        }
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `uv run pytest test_app_speech_scoring.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add app/speech/scoring.py test_app_speech_scoring.py
git commit -m "feat(app/speech): cola de scoring por conversacion (inyectable, con audio_seconds)"
```

---

### Task 3: `SpeechService` + construcción desde config e inyección

**Files:**
- Create: `app/speech/service.py`
- Modify: `app/speech/__init__.py` (exporta la API pública del módulo)
- Test: `test_app_speech_service.py`

**Interfaces:**
- Consumes: `AzureSpeechClient`, `assess_unscripted`, `TurnScoring`, `config`.
- Produces:
  - `app.speech.SpeechService` con:
    - `score_answer(conversation_id: str, audio_bytes: bytes) -> None` (encola, no espera).
    - `final_pronunciation(conversation_id: str) -> dict` → `{"scores": {...}, "words": [...], "audio_seconds": float}`.
  - `app.speech.build_speech_service() -> SpeechService | None` (None si falta `AZURE_SPEECH_KEY`, para degradar como el servicio de conversación).
  - Reexporta `SpeechError`.

- [ ] **Step 1: Escribir los tests que fallan `test_app_speech_service.py`**

```python
"""Tests del SpeechService: construcción desde config e integración cola+agregación."""

import config
from app.speech import SpeechService, build_speech_service


def fake_result(seconds, words):
    return {
        "recognized_text": "x",
        "scores": {
            "pronunciation": 80.0,
            "accuracy": 80.0,
            "fluency": 80.0,
            "completeness": None,
            "prosody": None,
        },
        "words": words,
        "audio_seconds": seconds,
    }


def test_build_returns_none_without_key(monkeypatch):
    monkeypatch.setattr(config, "AZURE_SPEECH_KEY", "")
    assert build_speech_service() is None


def test_build_returns_service_with_key(monkeypatch):
    monkeypatch.setattr(config, "AZURE_SPEECH_KEY", "test-key")
    service = build_speech_service()
    assert isinstance(service, SpeechService)


def test_score_answer_then_final_pronunciation_aggregates():
    # Inyectamos una función de evaluación falsa vía el constructor (sin red).
    results = iter([fake_result(2.0, [{"word": "a"}]), fake_result(3.0, [{"word": "b"}])])
    service = SpeechService(assess_fn=lambda audio: next(results))

    service.score_answer("c1", b"111")
    service.score_answer("c1", b"222")
    final = service.final_pronunciation("c1")

    assert final["audio_seconds"] == 5.0
    assert [w["word"] for w in final["words"]] == ["a", "b"]
    assert final["scores"]["pronunciation"] == 80.0
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `uv run pytest test_app_speech_service.py -v`
Expected: FAIL con `ImportError: cannot import name 'SpeechService' from 'app.speech'`.

- [ ] **Step 3: Implementar `app/speech/service.py`**

```python
"""Servicio de evaluación de pronunciación como unidad inyectable.

Compone la cola de scoring (`TurnScoring`) con la función de evaluación de Azure. El
endpoint encola el audio de cada respuesta con `score_answer` (no espera) y pide el agregado
al final con `final_pronunciation`. La construcción real (`build_speech_service`) lee la
config y arma un cliente de Azure; en tests se inyecta una `assess_fn` falsa.
"""

import os
import tempfile
from collections.abc import Callable

import config
from app.speech.assessment import SpeechError, assess_unscripted
from app.speech.azure_client import AzureSpeechClient
from app.speech.scoring import TurnScoring

__all__ = ["SpeechService", "SpeechError", "build_speech_service"]


class SpeechService:
    """Orquesta la evaluación diferida de pronunciación por conversación."""

    def __init__(self, assess_fn: Callable[[bytes], dict | None]) -> None:
        self._scoring = TurnScoring(assess_fn=assess_fn)

    def score_answer(self, conversation_id: str, audio_bytes: bytes) -> None:
        """Encola la evaluación del audio de una respuesta en segundo plano (no espera)."""
        self._scoring.enqueue(conversation_id, audio_bytes)

    def final_pronunciation(self, conversation_id: str) -> dict:
        """Recoge y agrega los scores/palabras/segundos de todos los turnos de la conversación."""
        results = self._scoring.collect(conversation_id)
        return self._scoring.aggregate(results)


def _assess_with_client(client: AzureSpeechClient) -> Callable[[bytes], dict | None]:
    """Devuelve una assess_fn que escribe el audio a un WAV temporal y llama a Azure.

    Un turno sin voz o un error de Azure no debe romper el resultado final: se descarta ese
    turno devolviendo None.
    """

    def assess(audio_bytes: bytes) -> dict | None:
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            wav_path = tmp.name
        try:
            return assess_unscripted(wav_path, client=client)
        except SpeechError:
            return None
        finally:
            os.unlink(wav_path)

    return assess


def build_speech_service() -> SpeechService | None:
    """Arma el servicio desde config; devuelve None si falta la clave de Azure (degradación).

    Así la conversación funciona igual sin Azure (transcripción del navegador + feedback de
    Gemini); solo se omite el scoring de pronunciación.
    """
    if not config.AZURE_SPEECH_KEY:
        return None
    client = AzureSpeechClient(
        config.AZURE_SPEECH_KEY, config.AZURE_SPEECH_REGION, config.SPEECH_LANGUAGE
    )
    return SpeechService(assess_fn=_assess_with_client(client))
```

- [ ] **Step 4: Exportar la API pública en `app/speech/__init__.py`**

```python
"""Módulo de evaluación de pronunciación (Azure) del piloto.

Expone el servicio inyectable y su construcción desde config. La conexión con el SDK vive en
azure_client.py; la lógica de scoring en assessment.py y scoring.py.
"""

from app.speech.assessment import SpeechError
from app.speech.service import SpeechService, build_speech_service

__all__ = ["SpeechService", "SpeechError", "build_speech_service"]
```

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run: `uv run pytest test_app_speech_service.py -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Correr toda la suite del módulo para verificar que nada se rompió**

Run: `uv run pytest test_app_speech_assessment.py test_app_speech_scoring.py test_app_speech_service.py -v`
Expected: PASS (15 tests en total).

- [ ] **Step 7: Commit**

```bash
git add app/speech/service.py app/speech/__init__.py test_app_speech_service.py
git commit -m "feat(app/speech): SpeechService inyectable + build_speech_service desde config"
```

---

## Notas para el que ejecute

- No se toca `app/cmd/server.py` en esta fase; la inyección del `SpeechService` en el
  composition root y el cambio del endpoint `/conversation/answer` a multipart van en la
  **Fase 3** del spec (`docs/superpowers/specs/2026-08-01-piloto-demo-conversacion-design.md`).
- `_TICK_PADDING` (azure_client) y `_TICKS_PER_SECOND` (assessment) describen la misma unidad
  (100 ns); el primero es el colchón por palabra del sample oficial, el segundo convierte a
  segundos. No se consolidan porque viven en capas distintas (SDK vs. negocio).
- La duración `audio_seconds` sale del span reconocido por Azure, no del tamaño del WAV: es
  lo que efectivamente se procesó, que es lo que factura Azure.
