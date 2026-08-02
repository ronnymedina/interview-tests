# Endpoints con límites + audio (Fase 3) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cablear en el composition root (`app/cmd/server.py`) el `LimitsService` (Fase 2) y el `SpeechService` (Fase 1), y cambiar los endpoints de conversación para: (a) `/conversation/start` chequee la cuota/presupuesto antes de arrancar y registre el uso de Gemini; (b) `/conversation/answer` reciba **multipart** (audio WAV + transcript), encole el audio para el scoring de Azure en segundo plano, registre el uso, y en el turno final combine el feedback de Gemini con la evaluación de pronunciación. No se toca el módulo `app/conversation/` ni el grafo ni el frontend.

**Architecture:** Todo el cambio vive en `app/cmd/server.py`. El `LimitsService` y el `SpeechService` se construyen UNA vez al arranque y se inyectan por `Depends`. La identidad del usuario llega por header `X-User-Id` (dependencia `get_user_id`). Los tokens reales de Gemini se capturan a nivel del endpoint con `get_usage_metadata_callback()` de langchain_core (envuelve la llamada al servicio; el módulo de conversación no se entera), y se registran como `usage_events` vía el `LimitsService`. El scoring de Azure NO bloquea el turno: se encola el WAV con `SpeechService.score_answer` y se agrega al final con `final_pronunciation`.

**Tech Stack:** Python 3.11+, FastAPI (`Form`/`File`/`UploadFile`/`Header`), `python-multipart` (ya instalado), langchain_core 1.5.1 (`get_usage_metadata_callback`), `pytest` + `fastapi.testclient`, `uv`.

## Global Constraints

- Todas las variables de entorno se leen SOLO en `config.py`; el resto recibe valores ya tipados. Nada de `os.getenv` disperso. (Las constantes de precio/cuota/límites ya existen desde la Fase 2.)
- Esta fase modifica SOLO `app/cmd/server.py` (y agrega su archivo de tests + actualiza `.env.example`). **No** se toca `app/conversation/` (ni el grafo, ni el servicio, ni los esquemas), **ni** `app/speech/`, **ni** `app/limits/`, **ni** el frontend. Si algo parece exigir tocarlos, es señal de replantear: reportar como DONE_WITH_CONCERNS o preguntar.
- Identidad: header `X-User-Id` obligatorio en `/conversation/start` y `/conversation/answer`. Si falta o viene vacío → 400.
- `check_can_start` se consulta ANTES de arrancar en `/start`. Si no permite → **429** con `detail={"reason": "quota" | "paused"}`. Postgres caído (la consulta lanza excepción) → decisión **conservadora**: cortar como `paused` (429), no arrancar.
- El costo se mide con tokens reales (`usage_metadata` de Gemini) y segundos de audio de Azure, registrados como `usage_events` vía `LimitsService.record_gemini_usage` / `record_azure_usage` (que ya calculan el costo). Nunca contadores mutables.
- Degradación de Azure: si `build_speech_service()` devolvió `None` (falta `AZURE_SPEECH_KEY`), la conversación funciona igual; se omite el `score_answer` y la pantalla final trae `pronunciation: null`. El `LimitsService` NO degrada (siempre se construye; la caída de Postgres se maneja como arriba).
- `kind` de los `usage_events`: `/start` → `"synthesis"` (agrega la síntesis + la 1ª pregunta que produce `service.start`); `/answer` turno no-final → `"question"`; `/answer` turno final → `"feedback"`; Azure → `"assessment"`.
- La conversación NO se persiste (igual que la Fase 1/2): solo se registran `conversation_starts` y `usage_events`.
- Tests en la raíz, nombrados `test_app_server_*.py`. Se prueban los endpoints con `fastapi.testclient.TestClient` y `app.dependency_overrides` inyectando dobles de los servicios (sin red, sin Postgres, sin LLM). Comando: `uv run pytest <archivo> -v`.

---

### Task 1: Composition root + `X-User-Id` + `/conversation/start` con límites y uso

**Files:**
- Modify: `app/cmd/server.py` (wiring de limits/speech, dependencia `get_user_id`, helper `_gemini_tokens`, reescritura de `/conversation/start`)
- Modify: `.env.example` (listar las env del piloto de la Fase 2, todas opcionales)
- Test: `test_app_server_start.py`

**Interfaces:**
- Consumes:
  - `app.limits.build_limits_service(storage) -> LimitsService`, con `LimitsService.check_can_start(user_id) -> Decision` (`.allowed: bool`, `.reason: str | None`), `record_conversation_start(user_id, conversation_id)`, `record_gemini_usage(user_id, conversation_id, kind, input_tokens, output_tokens) -> float`.
  - `app.speech.build_speech_service() -> SpeechService | None`.
  - `app.conversation.ConversationService.start(user_context, max_questions) -> tuple[str, str]`.
  - `langchain_core.callbacks.get_usage_metadata_callback()` (context manager; `.usage_metadata -> dict[str, dict]`).
- Produces (para Task 2 y el frontend):
  - Dependencias FastAPI: `get_user_id() -> str`, `get_limits_service() -> LimitsService`, `get_speech_service() -> SpeechService | None`.
  - Helper `_gemini_tokens(callback) -> tuple[int, int]` (suma input/output tokens de todos los modelos).
  - `POST /conversation/start` (header `X-User-Id`, body `StartRequest`) → `200 {"conversation_id","question"}` | `429 {"detail":{"reason":...}}` | `400` (sin user id) | `503` (sin Gemini).

- [ ] **Step 1: Escribir los tests que fallan `test_app_server_start.py`**

```python
"""Tests del endpoint /conversation/start: límites, registro de uso e identidad de usuario.

Se inyectan dobles de los servicios vía app.dependency_overrides (sin red, sin Postgres, sin
LLM). Con dobles no hay usage_metadata real, así que los tokens registrados son 0; lo que se
verifica es el CABLEADO: que se consulte la cuota, se registre el inicio y el usage_event.
"""

import pytest
from fastapi.testclient import TestClient

from app.cmd import server
from app.limits.model import Decision, DecisionKind


class FakeConversationService:
    def __init__(self):
        self.started_with = None

    def start(self, user_context, max_questions):
        self.started_with = (user_context, max_questions)
        return "conv-123", "What's your name?"


class FakeLimits:
    def __init__(self, decision=Decision(DecisionKind.ALLOW), raises=False):
        self._decision = decision
        self._raises = raises
        self.starts = []
        self.gemini = []

    def check_can_start(self, user_id):
        if self._raises:
            raise RuntimeError("db down")
        return self._decision

    def record_conversation_start(self, user_id, conversation_id):
        self.starts.append((user_id, conversation_id))

    def record_gemini_usage(self, user_id, conversation_id, kind, input_tokens, output_tokens):
        self.gemini.append((user_id, conversation_id, kind, input_tokens, output_tokens))
        return 0.0


@pytest.fixture
def client_with(monkeypatch):
    """Devuelve una fábrica que arma el TestClient con dobles inyectados."""

    def _make(conversation=None, limits=None):
        conversation = conversation or FakeConversationService()
        limits = limits or FakeLimits()
        server.app.dependency_overrides[server.get_conversation_service] = lambda: conversation
        server.app.dependency_overrides[server.get_limits_service] = lambda: limits
        return TestClient(server.app), conversation, limits

    yield _make
    server.app.dependency_overrides.clear()


def test_start_requires_user_id(client_with):
    client, _, _ = client_with()
    resp = client.post("/conversation/start", json={"user_context": "hola"})
    assert resp.status_code == 400


def test_start_allows_and_records(client_with):
    client, conversation, limits = client_with()
    resp = client.post(
        "/conversation/start",
        json={"user_context": "practicar para entrevista"},
        headers={"X-User-Id": "u1"},
    )
    assert resp.status_code == 200
    assert resp.json() == {"conversation_id": "conv-123", "question": "What's your name?"}
    # cableado: se registró el inicio y un usage_event de Gemini con kind 'synthesis'.
    assert limits.starts == [("u1", "conv-123")]
    assert len(limits.gemini) == 1
    assert limits.gemini[0][2] == "synthesis"


def test_start_blocked_by_quota_returns_429(client_with):
    limits = FakeLimits(decision=Decision(DecisionKind.QUOTA))
    client, _, _ = client_with(limits=limits)
    resp = client.post(
        "/conversation/start", json={"user_context": "x"}, headers={"X-User-Id": "u1"}
    )
    assert resp.status_code == 429
    assert resp.json()["detail"] == {"reason": "quota"}
    assert limits.starts == []  # no arrancó


def test_start_blocked_by_pause_returns_429(client_with):
    limits = FakeLimits(decision=Decision(DecisionKind.PAUSED_TOTAL))
    client, _, _ = client_with(limits=limits)
    resp = client.post(
        "/conversation/start", json={"user_context": "x"}, headers={"X-User-Id": "u1"}
    )
    assert resp.status_code == 429
    assert resp.json()["detail"] == {"reason": "paused"}


def test_start_db_down_cuts_conservative_as_paused(client_with):
    limits = FakeLimits(raises=True)
    client, _, _ = client_with(limits=limits)
    resp = client.post(
        "/conversation/start", json={"user_context": "x"}, headers={"X-User-Id": "u1"}
    )
    assert resp.status_code == 429
    assert resp.json()["detail"] == {"reason": "paused"}
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `uv run pytest test_app_server_start.py -v`
Expected: FAIL — al importar/usar, `AttributeError: module 'app.cmd.server' has no attribute 'get_limits_service'` (aún no existe la dependencia), o los asserts de 400/429 fallan porque el endpoint todavía no chequea nada.

- [ ] **Step 3: Cablear servicios y dependencias en `app/cmd/server.py`**

En la zona de imports, agregar:

```python
from fastapi import Depends, FastAPI, Header, HTTPException
from langchain_core.callbacks import get_usage_metadata_callback

from app.limits import LimitsService, build_limits_service
from app.speech import SpeechService, build_speech_service
```

(La línea `from fastapi import Depends, FastAPI, HTTPException` ya existe: reemplazarla por la de arriba que añade `Header`. `from fastapi.staticfiles import StaticFiles` se conserva.)

Debajo de la construcción de `_repository` (después de `_repository = ConversationRepository(_storage)`), agregar la construcción de los servicios nuevos:

```python
# LimitsService: SIEMPRE se construye (la cuota/presupuesto son parte del piloto). Comparte el
# mismo almacenamiento perezoso; si Postgres está caído, la consulta falla al ejecutarse y el
# endpoint corta conservador.
_limits_service = build_limits_service(_storage)

# SpeechService: puede ser None si falta AZURE_SPEECH_KEY. En ese caso la conversación funciona
# igual (transcripción del navegador + feedback de Gemini) y se omite el scoring de Azure.
_speech_service = build_speech_service()
if _speech_service is None:
    logger.info("AZURE_SPEECH_KEY ausente: scoring de pronunciación deshabilitado.")
```

Agregar las dependencias FastAPI (junto a `get_conversation_service` / `get_repository`):

```python
def get_limits_service() -> LimitsService:
    """Dependencia FastAPI: entrega el servicio de límites (cuota + presupuesto)."""
    return _limits_service


def get_speech_service() -> "SpeechService | None":
    """Dependencia FastAPI: entrega el servicio de pronunciación, o None si Azure no está."""
    return _speech_service


def get_user_id(x_user_id: str = Header(default="")) -> str:
    """Identidad del navegador (header X-User-Id). Obligatoria; 400 si falta o viene vacía."""
    user_id = x_user_id.strip()
    if not user_id:
        raise HTTPException(status_code=400, detail="Falta el header X-User-Id.")
    return user_id


def _gemini_tokens(callback) -> tuple[int, int]:
    """Suma input/output tokens capturados por get_usage_metadata_callback (por todos los modelos)."""
    input_tokens = output_tokens = 0
    for usage in callback.usage_metadata.values():
        input_tokens += usage.get("input_tokens", 0)
        output_tokens += usage.get("output_tokens", 0)
    return input_tokens, output_tokens
```

- [ ] **Step 4: Reescribir el endpoint `/conversation/start` en `app/cmd/server.py`**

Reemplazar la función `conversation_start` existente por:

```python
@app.post("/conversation/start")
def conversation_start(
    payload: conversation.StartRequest,
    user_id: str = Depends(get_user_id),
    service: ConversationService = Depends(get_conversation_service),
    limits: LimitsService = Depends(get_limits_service),
) -> dict:
    """Arranca una conversación si el usuario tiene cuota y el presupuesto lo permite.

    Chequea límites ANTES de gastar; si no puede, corta con 429 y un motivo tipado. Si puede,
    sintetiza el contexto y devuelve la 1ª pregunta (por dentro de `service.start`), registra el
    inicio para la cuota y el uso de Gemini (tokens reales capturados alrededor de la llamada).
    """
    try:
        decision = limits.check_can_start(user_id)
    except Exception:
        logger.exception("check_can_start falló (¿Postgres?); se corta conservador como 'paused'.")
        raise HTTPException(status_code=429, detail={"reason": "paused"})

    if not decision.allowed:
        raise HTTPException(status_code=429, detail={"reason": decision.reason})

    try:
        with get_usage_metadata_callback() as callback:
            conversation_id, question = service.start(payload.user_context, payload.max_questions)
    except ConversationError as error:
        raise HTTPException(status_code=error.status, detail=str(error))

    limits.record_conversation_start(user_id, conversation_id)
    input_tokens, output_tokens = _gemini_tokens(callback)
    limits.record_gemini_usage(user_id, conversation_id, "synthesis", input_tokens, output_tokens)

    return {"conversation_id": conversation_id, "question": question}
```

- [ ] **Step 5: Actualizar `.env.example`**

Agregar al final de `.env.example` (todas opcionales; hay defaults en `config.py`):

```bash

# --- Piloto demo: tarifas, presupuesto y cuota (opcionales; defaults en config.py) ---
GEMINI_PRICE_INPUT_PER_1K=0.0003
GEMINI_PRICE_OUTPUT_PER_1K=0.0025
AZURE_SPEECH_PRICE_PER_SECOND=0.000278
DAILY_BUDGET_USD=3.0
TOTAL_BUDGET_USD=10.0
USER_CONVERSATION_QUOTA=3
MAX_ANSWER_SECONDS=30
MAX_QUESTIONS=5
```

- [ ] **Step 6: Correr los tests y verificar que pasan**

Run: `uv run pytest test_app_server_start.py -v`
Expected: PASS (5 tests).

- [ ] **Step 7: Verificar que la suite completa sigue verde (cambió el server)**

Run: `uv run pytest -q`
Expected: PASS (los tests legacy del server root `main.py` no se ven afectados; solo cambió `app/cmd/server.py`).

- [ ] **Step 8: Commit**

```bash
git add app/cmd/server.py .env.example test_app_server_start.py
git commit -m "feat(app/server): /conversation/start con limites (429) + registro de uso Gemini"
```

---

### Task 2: `/conversation/answer` multipart (audio + transcript) con scoring y merge final

**Files:**
- Modify: `app/cmd/server.py` (reescritura de `/conversation/answer` a multipart)
- Test: `test_app_server_answer.py`

**Interfaces:**
- Consumes (de Task 1): `get_user_id`, `get_limits_service`, `get_speech_service`, `_gemini_tokens`, `get_usage_metadata_callback`.
  - `ConversationService.answer(conversation_id, recognized_text) -> dict` que devuelve `{"question": str}` (turno normal) o `{"final": {...}}` (turno final).
  - `SpeechService.score_answer(conversation_id, audio_bytes) -> None` (encola, no espera) y `final_pronunciation(conversation_id) -> dict` (`{"scores","words","audio_seconds"}`).
  - `LimitsService.record_gemini_usage(...)`, `record_azure_usage(user_id, conversation_id, audio_seconds) -> float`.
- Produces (para el frontend):
  - `POST /conversation/answer` multipart (`conversation_id`, `transcript` como `Form`; `audio` como `UploadFile`; header `X-User-Id`) → `200 {"question": str}` en turnos normales, o `200 {"final": {..., "pronunciation": {...} | null}}` en el último. `422` si `transcript` vacío; `404/409` de la conversación; `400` sin user id.

- [ ] **Step 1: Escribir los tests que fallan `test_app_server_answer.py`**

```python
"""Tests del endpoint /conversation/answer (multipart): scoring encolado, uso y merge final.

Dobles inyectados vía dependency_overrides. El audio es un WAV de bytes arbitrarios (el doble de
speech no lo procesa). Se verifica el cableado: encolar el audio, registrar uso, y en el turno
final combinar el feedback de Gemini con la evaluación de pronunciación.
"""

import io

import pytest
from fastapi.testclient import TestClient

from app.cmd import server


class FakeConversationService:
    def __init__(self, result):
        self._result = result
        self.answered_with = None

    def answer(self, conversation_id, recognized_text):
        self.answered_with = (conversation_id, recognized_text)
        return self._result


class FakeLimits:
    def __init__(self):
        self.gemini = []
        self.azure = []

    def record_gemini_usage(self, user_id, conversation_id, kind, input_tokens, output_tokens):
        self.gemini.append((user_id, conversation_id, kind, input_tokens, output_tokens))
        return 0.0

    def record_azure_usage(self, user_id, conversation_id, audio_seconds):
        self.azure.append((user_id, conversation_id, audio_seconds))
        return 0.0


class FakeSpeech:
    def __init__(self, pronunciation=None):
        self._pronunciation = pronunciation or {
            "scores": {"pronunciation": 80.0}, "words": [], "audio_seconds": 4.0
        }
        self.enqueued = []

    def score_answer(self, conversation_id, audio_bytes):
        self.enqueued.append((conversation_id, audio_bytes))

    def final_pronunciation(self, conversation_id):
        return self._pronunciation


def _post_answer(client, *, conversation_id="c1", transcript="hello world", audio=b"RIFFfake"):
    return client.post(
        "/conversation/answer",
        data={"conversation_id": conversation_id, "transcript": transcript},
        files={"audio": ("answer.wav", io.BytesIO(audio), "audio/wav")},
        headers={"X-User-Id": "u1"},
    )


@pytest.fixture
def client_with():
    def _make(result, speech=None, limits=None):
        conversation = FakeConversationService(result)
        limits = limits or FakeLimits()
        speech = speech  # None => sin Azure
        server.app.dependency_overrides[server.get_conversation_service] = lambda: conversation
        server.app.dependency_overrides[server.get_limits_service] = lambda: limits
        server.app.dependency_overrides[server.get_speech_service] = lambda: speech
        return TestClient(server.app), conversation, limits, speech

    yield _make
    server.app.dependency_overrides.clear()


def test_answer_requires_user_id(client_with):
    client, *_ = client_with({"question": "next?"}, speech=FakeSpeech())
    resp = client.post(
        "/conversation/answer",
        data={"conversation_id": "c1", "transcript": "hi"},
        files={"audio": ("a.wav", io.BytesIO(b"x"), "audio/wav")},
    )
    assert resp.status_code == 400


def test_answer_normal_turn_enqueues_audio_and_returns_question(client_with):
    speech = FakeSpeech()
    client, conversation, limits, _ = client_with({"question": "And then?"}, speech=speech)
    resp = _post_answer(client)
    assert resp.status_code == 200
    assert resp.json() == {"question": "And then?"}
    assert speech.enqueued == [("c1", b"RIFFfake")]        # audio encolado
    assert conversation.answered_with == ("c1", "hello world")  # transcript al grafo
    assert limits.gemini[0][2] == "question"               # usage_event kind 'question'
    assert limits.azure == []                              # sin Azure en turno normal


def test_answer_final_turn_merges_pronunciation(client_with):
    final = {"final": {"content_feedback": "bien", "practice_words": []}}
    speech = FakeSpeech(pronunciation={"scores": {"pronunciation": 90.0}, "words": [], "audio_seconds": 6.0})
    client, _, limits, _ = client_with(final, speech=speech)
    resp = _post_answer(client, transcript="that is all")
    assert resp.status_code == 200
    body = resp.json()
    assert body["final"]["pronunciation"] == {"scores": {"pronunciation": 90.0}, "words": [], "audio_seconds": 6.0}
    assert limits.gemini[0][2] == "feedback"              # usage_event Gemini kind 'feedback'
    assert limits.azure == [("u1", "c1", 6.0)]            # usage_event Azure por duración


def test_answer_final_turn_without_azure_sets_pronunciation_null(client_with):
    final = {"final": {"content_feedback": "bien", "practice_words": []}}
    client, _, limits, _ = client_with(final, speech=None)  # sin SpeechService
    resp = _post_answer(client, transcript="done")
    assert resp.status_code == 200
    assert resp.json()["final"]["pronunciation"] is None
    assert limits.azure == []


def test_answer_empty_transcript_returns_422(client_with):
    client, *_ = client_with({"question": "x"}, speech=FakeSpeech())
    resp = _post_answer(client, transcript="   ")
    assert resp.status_code == 422
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `uv run pytest test_app_server_answer.py -v`
Expected: FAIL — el endpoint actual recibe JSON (`AnswerRequest`), no multipart, así que los POST con `data=`/`files=` responden 422 por el body esperado, o los asserts de scoring/merge fallan.

- [ ] **Step 3: Reescribir el endpoint `/conversation/answer` en `app/cmd/server.py`**

Añadir `File`, `Form`, `UploadFile` al import de fastapi (la línea queda
`from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile`).

Reemplazar la función `conversation_answer` existente por:

```python
@app.post("/conversation/answer")
def conversation_answer(
    conversation_id: str = Form(...),
    transcript: str = Form(...),
    audio: UploadFile = File(...),
    user_id: str = Depends(get_user_id),
    service: ConversationService = Depends(get_conversation_service),
    limits: LimitsService = Depends(get_limits_service),
    speech: "SpeechService | None" = Depends(get_speech_service),
) -> dict:
    """Procesa una respuesta: encola el audio para Azure (no espera) y avanza el grafo.

    Recibe multipart: el `transcript` del navegador (mueve la conversación rápido) y el `audio`
    WAV (lo puntúa Azure en segundo plano). En el turno final combina el feedback de Gemini con
    la evaluación de pronunciación agregada. Registra el uso de Gemini en cada turno y el de
    Azure una vez, al final, por la duración total.
    """
    text = transcript.strip()
    if not text:
        raise HTTPException(status_code=422, detail="La respuesta está vacía.")

    # Encola el WAV para el scoring en segundo plano ANTES de llamar al grafo (no bloquea).
    if speech is not None:
        speech.score_answer(conversation_id, audio.file.read())

    try:
        with get_usage_metadata_callback() as callback:
            result = service.answer(conversation_id, text)
    except ConversationError as error:
        raise HTTPException(status_code=error.status, detail=str(error))

    input_tokens, output_tokens = _gemini_tokens(callback)
    is_final = "final" in result

    limits.record_gemini_usage(
        user_id, conversation_id, "feedback" if is_final else "question",
        input_tokens, output_tokens,
    )

    if is_final:
        pronunciation = None
        if speech is not None:
            pronunciation = speech.final_pronunciation(conversation_id)
            limits.record_azure_usage(user_id, conversation_id, pronunciation["audio_seconds"])
        result["final"]["pronunciation"] = pronunciation

    return result
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `uv run pytest test_app_server_answer.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Correr toda la suite del server + verificación completa**

Run: `uv run pytest test_app_server_start.py test_app_server_answer.py -v`
Expected: PASS (10 tests en total).

Run: `uv run pytest -q`
Expected: PASS (suite completa; los endpoints legacy del root `main.py` no cambian).

- [ ] **Step 6: Commit**

```bash
git add app/cmd/server.py test_app_server_answer.py
git commit -m "feat(app/server): /conversation/answer multipart (audio+transcript) con scoring y merge final"
```

---

## Notas para el que ejecute

- **Captura de tokens:** `get_usage_metadata_callback()` usa contextvars, así que envolver la llamada al servicio en el endpoint captura los tokens de TODAS las llamadas al LLM que ocurran por dentro (síntesis + pregunta en `/start`; pregunta o feedback en `/answer`), sin tocar `app/conversation/`. Con dobles en los tests no hay `usage_metadata` real → tokens 0; eso es esperado (el cálculo de costo ya está probado en la Fase 2; acá se prueba el cableado).
- **`conversation_starts` sin unicidad (hallazgo de la Fase 2):** `/start` genera un `conversation_id` fresco y registra UN inicio por conversación, así que en el flujo normal no hay doble cobro de cuota. Queda un TOCTOU teórico (dos `start` concurrentes del mismo usuario podrían pasar ambos el `check_can_start` antes de registrar) aceptable para el piloto; si se quisiera blindar, va un `UNIQUE(conversation_id)` + contar por usuario en una fase de endurecimiento, no acá.
- **Orden en `/start`:** se consulta `check_can_start` (que cuenta los inicios PREVIOS) → se arranca → se registra el inicio → se registra el uso. Registrar después de arrancar es correcto: la cuota de N permite exactamente N arranques.
- **Fase 4 (feedback) y Fase 5 (frontend)** son planes aparte. El frontend nuevo consumirá este `/conversation/answer` multipart y el `pronunciation` del resultado final.
- No se agrega fixture de Postgres: los tests de endpoint inyectan dobles de `LimitsService`/`SpeechService`/`ConversationService` vía `app.dependency_overrides`, sin red ni BD.
