# Transcripción por navegador + scoring diferido — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que la conversación no espere la evaluación de pronunciación de Azure entre preguntas: la transcripción alimenta a Gemini de inmediato (desde el navegador o desde Azure, elegible con un toggle) y el scoring de pronunciación corre en segundo plano, agregándose al final. Mostrar siempre lo que captó el micrófono.

**Architecture:** Un store en memoria (`scoring.py`) con un `ThreadPoolExecutor` acumula los resultados de `speech.assess_unscripted` por `conversation_id`. El endpoint `/conversation/{id}/answer` recibe `mode` (`browser`|`azure`): en `browser` toma el texto del cliente y encola el audio sin esperar; en `azure` encola y espera el resultado del turno para mostrar scores. El scoring del grafo (`per_turn_scores`/`per_turn_words`) se elimina; el agregado final sale de `scoring.collect`+`scoring.aggregate`.

**Tech Stack:** FastAPI, LangGraph/Gemini (ya integrados), Azure Speech, `concurrent.futures.ThreadPoolExecutor`, Web Speech API (`SpeechRecognition`) en el navegador, pytest.

## Global Constraints

- Python `>=3.11`.
- Variables de entorno SOLO en `config.py` (ningún `os.getenv` fuera). `scoring.py` no lee env.
- Mensajes de error al usuario en español, vía `HTTPException(detail=...)` o `ConversationError`.
- La pronunciación siempre la mide `speech.assess_unscripted` (Azure) sobre el audio real, en ambos modos. El toggle solo cambia la fuente del texto que alimenta a Gemini y si el score del turno es síncrono (azure) o diferido (browser).
- Persistencia sin cambios: solo el resultado final (`db.save_conversation`).
- TDD para el backend. El frontend no tiene arnés de tests JS: se valida con `node --check` + walkthrough manual.
- Comandos: `uv run pytest` desde `review-ingles/`. `node` está en `/opt/homebrew/bin/node`.

---

### Task 1: `scoring.py` — store de scoring en segundo plano

**Files:**
- Create: `scoring.py`
- Test: `test_scoring.py`
- Modify: `conftest.py` (fixture de aislamiento del store)

**Interfaces:**
- Consumes: `speech.assess_unscripted(wav_path) -> dict`, `speech.SpeechError`.
- Produces:
  - `scoring.enqueue(conversation_id: str, audio_bytes: bytes) -> concurrent.futures.Future`
  - `scoring.collect(conversation_id: str) -> list[dict]` (resultados de `assess_unscripted`, sin los `None`)
  - `scoring.aggregate(results: list[dict]) -> tuple[dict, list[dict]]` → `(scores, words)` donde `scores` tiene claves `pronunciation/accuracy/fluency/prosody`.
  - Interno: `scoring._pending: dict[str, list[Future]]` (para aislar en tests).

- [ ] **Step 1: Escribir los tests que fallan**

Crea `test_scoring.py`:

```python
"""Tests del store de scoring en segundo plano (sin red: se mockea Azure)."""

import scoring
import speech


def _result(pronunciation, words):
    return {
        "recognized_text": "hello",
        "scores": {
            "pronunciation": pronunciation,
            "accuracy": pronunciation,
            "fluency": pronunciation,
            "completeness": None,
            "prosody": pronunciation,
        },
        "words": words,
    }


def test_enqueue_and_collect_returns_results(monkeypatch):
    monkeypatch.setattr(speech, "assess_unscripted", lambda wav_path: _result(80.0, []))
    scoring.enqueue("c1", b"audio-a")
    scoring.enqueue("c1", b"audio-b")
    results = scoring.collect("c1")
    assert len(results) == 2
    # collect vacia la conversacion: una segunda llamada no repite.
    assert scoring.collect("c1") == []


def test_failed_assessment_is_dropped(monkeypatch):
    def boom(wav_path):
        raise speech.SpeechError("no voz", status=422)

    monkeypatch.setattr(speech, "assess_unscripted", boom)
    scoring.enqueue("c2", b"audio")
    assert scoring.collect("c2") == []


def test_collect_unknown_conversation_is_empty():
    assert scoring.collect("nope") == []


def test_aggregate_averages_scores_and_concatenates_words():
    words_a = [{"word": "hello", "error_type": "None", "accuracy": 90.0, "phonemes": []}]
    words_b = [{"word": "world", "error_type": "None", "accuracy": 70.0, "phonemes": []}]
    scores, words = scoring.aggregate([_result(80.0, words_a), _result(90.0, words_b)])
    assert scores["pronunciation"] == 85.0
    assert [w["word"] for w in words] == ["hello", "world"]


def test_aggregate_ignores_none_scores():
    a = _result(80.0, [])
    a["scores"]["prosody"] = None
    b = _result(90.0, [])
    scores, _ = scoring.aggregate([a, b])
    assert scores["prosody"] == 90.0  # el None se ignora en el promedio
```

- [ ] **Step 2: Correr y ver que falla**

Run: `uv run pytest test_scoring.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'scoring'`.

- [ ] **Step 3: Implementar `scoring.py`**

Crea `scoring.py`:

```python
"""Cola en memoria para evaluar la pronunciacion de las respuestas en segundo plano.

Aisla la acumulacion de resultados de speech.assess_unscripted por conversacion. En modo
navegador el endpoint encola el audio y no espera; en modo Azure espera el resultado del
turno para mostrar su score, pero igual queda acumulado para el agregado final. Todo vive
en memoria del proceso (consistente con el checkpointer del grafo).
"""

import os
import tempfile
import threading
from concurrent.futures import Future, ThreadPoolExecutor

import speech

_executor = ThreadPoolExecutor(max_workers=4)
_lock = threading.Lock()
_pending: dict[str, list[Future]] = {}


def _assess(audio_bytes: bytes) -> dict | None:
    """Evalua un WAV; devuelve el result de assess_unscripted o None si Azure fallo.

    Una respuesta sin voz o un error de Azure no debe romper el resultado final: se
    descarta ese turno del scoring.
    """
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio_bytes)
        wav_path = tmp.name
    try:
        return speech.assess_unscripted(wav_path)
    except speech.SpeechError:
        return None
    finally:
        os.unlink(wav_path)


def enqueue(conversation_id: str, audio_bytes: bytes) -> Future:
    """Lanza la evaluacion del audio en segundo plano y la registra en la conversacion."""
    future = _executor.submit(_assess, audio_bytes)
    with _lock:
        _pending.setdefault(conversation_id, []).append(future)
    return future


def collect(conversation_id: str) -> list[dict]:
    """Espera y devuelve los resultados de todos los turnos encolados (descarta los None)."""
    with _lock:
        futures = _pending.pop(conversation_id, [])
    results = [future.result() for future in futures]
    return [result for result in results if result is not None]


def aggregate(results: list[dict]) -> tuple[dict, list[dict]]:
    """Promedia los scores de todos los turnos y concatena sus palabras."""
    scores = _aggregate_scores([result["scores"] for result in results])
    words = [word for result in results for word in result["words"]]
    return scores, words


def _aggregate_scores(per_turn_scores: list[dict]) -> dict:
    """Promedia por dimension, ignorando None (ej. prosody no soportada)."""

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

- [ ] **Step 4: Aislar el store entre tests (`conftest.py`)**

Añade a `conftest.py` una fixture autouse que limpia el store del scoring, para que los futures de un test no se filtren a otro:

```python
@pytest.fixture(autouse=True)
def _clear_scoring():
    import scoring

    scoring._pending.clear()
    yield
    scoring._pending.clear()
```

(`conftest.py` ya importa `pytest`.)

- [ ] **Step 5: Correr los tests**

Run: `uv run pytest test_scoring.py -v`
Expected: PASS los 5.

- [ ] **Step 6: Commit**

```bash
git add scoring.py test_scoring.py conftest.py
git commit -m "feat: store de scoring de pronunciacion en segundo plano"
```

---

### Task 2: Sacar el scoring del grafo (`conversation.py`)

**Files:**
- Modify: `conversation.py`
- Test: `test_conversation.py`

**Interfaces:**
- Produces (cambia): `conversation.answer(conversation_id: str, recognized_text: str, graph=None) -> dict`. Devuelve `{"question": str}` o `{"final": {"content_feedback": str, "system_prompt": str, "questions_asked": int}}` (SIN `scores` ni `words`).
- Se elimina `conversation.aggregate_scores` (ahora vive en `scoring.py`).
- `State` pierde `per_turn_scores` y `per_turn_words`.

- [ ] **Step 1: Actualizar los tests primero (rojo)**

En `test_conversation.py`:

1. Borra la función `_scores` (líneas 49-55) — ya no se usa.
2. Borra por completo `test_words_accumulate_across_turns` (el scoring ya no vive en el grafo; se cubre en `test_scoring.py` y `test_api.py`).
3. Reemplaza `test_block_content_is_flattened_to_string` por:

```python
def test_block_content_is_flattened_to_string():
    # Reproduce el bug "[object Object]": Gemini puede devolver contenido en bloques.
    # La pregunta y el feedback deben salir como strings planos.
    graph = conversation.build_graph(BlockContentLLM(["Q1", "FEEDBACK"]))
    conversation_id, q1 = conversation.start("Roleplay", 1, graph=graph)
    assert q1 == "Q1"
    result = conversation.answer(conversation_id, "hi", graph=graph)
    assert result["final"]["content_feedback"] == "FEEDBACK"
```

4. Reemplaza `test_full_flow_reaches_feedback` por:

```python
def test_full_flow_reaches_feedback():
    graph = conversation.build_graph(FakeLLM(["Q1", "Q2", "FEEDBACK"]))
    conversation_id, q1 = conversation.start("Roleplay", 2, graph=graph)
    assert q1 == "Q1"

    r1 = conversation.answer(conversation_id, "answer one", graph=graph)
    assert r1 == {"question": "Q2"}

    r2 = conversation.answer(conversation_id, "answer two", graph=graph)
    assert "final" in r2
    assert r2["final"]["content_feedback"] == "FEEDBACK"
    assert r2["final"]["questions_asked"] == 2
    assert r2["final"]["system_prompt"] == "Roleplay"
    assert "scores" not in r2["final"]
```

5. En `test_answer_unknown_conversation_raises_404`, cambia la llamada a:

```python
        conversation.answer("does-not-exist", "hi", graph=graph)
```

6. Reemplaza `test_answer_after_finished_raises_409_and_does_not_reinvoke_graph` por:

```python
def test_answer_after_finished_raises_409_and_does_not_reinvoke_graph():
    graph = conversation.build_graph(FakeLLM(["Q1", "Q2", "FEEDBACK"]))
    conversation_id, _ = conversation.start("Roleplay", 2, graph=graph)
    conversation.answer(conversation_id, "answer one", graph=graph)
    result = conversation.answer(conversation_id, "answer two", graph=graph)
    assert "final" in result

    # La conversacion ya termino: llamar answer() de nuevo no debe re-invocar el grafo
    # (el FakeLLM no tiene mas respuestas) y debe devolver 409 en su lugar.
    with pytest.raises(conversation.ConversationError) as error:
        conversation.answer(conversation_id, "answer three", graph=graph)
    assert error.value.status == 409
```

- [ ] **Step 2: Correr y ver que falla**

Run: `uv run pytest test_conversation.py -v`
Expected: FAIL (answer() aún exige `turn_scores`/`turn_words`; los tests llaman con la firma nueva).

- [ ] **Step 3: Quitar los campos de scoring del `State`**

En `conversation.py`, reemplaza la clase `State` (líneas 50-58) por:

```python
class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    system_prompt: str
    max_questions: int
    questions_asked: int
    content_feedback: str
    finished: bool
```

`operator` deja de usarse: borra `import operator` (línea 11).

- [ ] **Step 4: Quitar la inicialización de scoring en `start`**

En `start` (el dict que se pasa a `graph.invoke`), borra estas dos líneas:

```python
            "per_turn_scores": [],
            "per_turn_words": [],
```

- [ ] **Step 5: Simplificar `answer`**

Reemplaza la función `answer` completa por:

```python
def answer(conversation_id: str, recognized_text: str, graph=None) -> dict:
    """Inyecta la respuesta del usuario y devuelve la siguiente pregunta o el resultado final.

    El scoring de pronunciacion ya no vive en el grafo: se acumula aparte (scoring.py) y el
    endpoint lo agrega al finalizar.
    """
    graph = graph or _get_graph()
    cfg = _config(conversation_id)

    # Conversacion desconocida (proceso reiniciado o id invalido).
    state_values = graph.get_state(cfg).values
    if not state_values:
        raise ConversationError("La conversacion no existe o expiro.", status=404)

    # Conversacion ya finalizada: no re-invocar el grafo (evitaria otra llamada a Gemini y
    # un segundo guardado en la BD).
    if state_values.get("finished"):
        raise ConversationError("La conversacion ya termino.", status=409)

    result = graph.invoke({"messages": [HumanMessage(recognized_text)]}, cfg)

    if result["finished"]:
        return {
            "final": {
                "content_feedback": result["content_feedback"],
                "system_prompt": result["system_prompt"],
                "questions_asked": result["questions_asked"],
            }
        }
    return {"question": result["messages"][-1].content}
```

- [ ] **Step 6: Borrar `aggregate_scores` de `conversation.py`**

Borra la función `aggregate_scores` completa (últimas líneas del archivo). Vive ahora en `scoring.py`.

- [ ] **Step 7: Correr los tests**

Run: `uv run pytest test_conversation.py -v`
Expected: PASS todos.

- [ ] **Step 8: Commit**

```bash
git add conversation.py test_conversation.py
git commit -m "refactor: saca el scoring del grafo; answer() solo maneja la conversacion"
```

---

### Task 3: Endpoint con modo (`main.py`)

**Files:**
- Modify: `main.py`
- Test: `test_api.py`

**Interfaces:**
- Consumes: `scoring.enqueue`, `scoring.collect`, `scoring.aggregate`, `conversation.exists`, `conversation.answer(id, text)`, `speech.SpeechError`, `db.save_conversation`.
- Produces (HTTP): `POST /conversation/{id}/answer` multipart `audio` + `mode` (`browser`|`azure`, default `azure`) + `transcript` (requerido si `mode=browser`). Respuesta intermedia `{recognized_text, turn_scores, next_question}` (`turn_scores` es `null` en `browser`); final `{recognized_text, turn_scores, final: {scores, content_feedback}}`.

- [ ] **Step 1: Actualizar los tests primero**

En `test_api.py`, reemplaza `test_conversation_answer_intermediate` y `test_conversation_answer_final_is_saved`, y añade dos tests nuevos. Deja `test_conversation_answer_unknown_id_returns_404` como está.

```python
def test_conversation_answer_azure_shows_turn_scores(client, monkeypatch):
    monkeypatch.setattr(conversation, "exists", lambda cid: True)
    monkeypatch.setattr(speech, "assess_unscripted", lambda wav_path: make_unscripted_result())
    monkeypatch.setattr(conversation, "answer", lambda cid, text: {"question": "Next question?"})
    resp = client.post(
        "/conversation/cid-1/answer",
        data={"mode": "azure"},
        files={"audio": ("r.wav", b"fake-audio", "audio/wav")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["next_question"] == "Next question?"
    assert body["recognized_text"] == "hello world"
    # En modo azure el score del turno esta presente.
    assert body["turn_scores"]["pronunciation"] == 85.0


def test_conversation_answer_browser_defers_scoring(client, monkeypatch):
    monkeypatch.setattr(conversation, "exists", lambda cid: True)
    monkeypatch.setattr(speech, "assess_unscripted", lambda wav_path: make_unscripted_result())
    monkeypatch.setattr(conversation, "answer", lambda cid, text: {"question": "Next?"})
    resp = client.post(
        "/conversation/cid-1/answer",
        data={"mode": "browser", "transcript": "I went to work"},
        files={"audio": ("r.wav", b"fake-audio", "audio/wav")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["next_question"] == "Next?"
    # El texto viene del cliente; no hay score por turno (diferido).
    assert body["recognized_text"] == "I went to work"
    assert body["turn_scores"] is None


def test_conversation_answer_browser_without_transcript_rejected(client, monkeypatch):
    monkeypatch.setattr(conversation, "exists", lambda cid: True)
    resp = client.post(
        "/conversation/cid-1/answer",
        data={"mode": "browser", "transcript": "   "},
        files={"audio": ("r.wav", b"fake-audio", "audio/wav")},
    )
    assert resp.status_code == 400


def test_conversation_answer_final_aggregates_and_saves(client, monkeypatch):
    monkeypatch.setattr(conversation, "exists", lambda cid: True)
    monkeypatch.setattr(speech, "assess_unscripted", lambda wav_path: make_unscripted_result())
    final_payload = {
        "final": {
            "content_feedback": "Buen intento.",
            "system_prompt": "Roleplay",
            "questions_asked": 1,
        }
    }
    monkeypatch.setattr(conversation, "answer", lambda cid, text: final_payload)

    resp = client.post(
        "/conversation/cid-final/answer",
        data={"mode": "azure"},
        files={"audio": ("r.wav", b"fake-audio", "audio/wav")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["final"]["content_feedback"] == "Buen intento."
    # Los scores del final salen del agregado del scoring encolado.
    assert body["final"]["scores"]["pronunciation"] == 85.0

    saved = db.list_conversations()
    assert len(saved) == 1
    assert saved[0]["system_prompt"] == "Roleplay"
    assert saved[0]["pronunciation_score"] == 85.0
    # Las palabras del scoring alimentaron el banco.
    assert [s["word"] for s in db.list_word_stats()] == ["hello"]
```

- [ ] **Step 2: Correr y ver que falla**

Run: `uv run pytest test_api.py -k conversation_answer -v`
Expected: FAIL (el endpoint aún no acepta `mode`/`transcript` ni usa `scoring`).

- [ ] **Step 3: Añadir el import de `scoring`**

En `main.py`, junto a los otros imports de módulos locales (`import conversation`, `import db`, `import speech`), añade:

```python
import scoring
```

- [ ] **Step 4: Reescribir el endpoint `conversation_answer`**

Reemplaza la función `conversation_answer` completa por:

```python
@app.post("/conversation/{conversation_id}/answer")
async def conversation_answer(
    conversation_id: str,
    audio: UploadFile,
    mode: str = Form("azure"),
    transcript: str = Form(""),
) -> JSONResponse:
    # Chequeo barato del id antes de cualquier trabajo pesado.
    try:
        conversation_exists = await run_in_threadpool(conversation.exists, conversation_id)
    except conversation.ConversationError as error:
        raise HTTPException(status_code=error.status, detail=str(error))
    if not conversation_exists:
        raise HTTPException(status_code=404, detail="La conversacion no existe o expiro.")

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="No llego audio.")

    if mode == "browser":
        # El texto lo transcribe el navegador; el audio se puntua en segundo plano.
        recognized_text = transcript.strip()
        if not recognized_text:
            raise HTTPException(status_code=400, detail="No llego la transcripcion.")
        scoring.enqueue(conversation_id, audio_bytes)
        turn_scores = None
    else:
        # Modo azure: se evalua ahora para mostrar el score del turno; el resultado igual
        # queda encolado para el agregado final.
        future = scoring.enqueue(conversation_id, audio_bytes)
        assessment = await run_in_threadpool(future.result)
        if assessment is None:
            raise HTTPException(
                status_code=422,
                detail="No se detecto voz en el audio. Revisa el microfono e intenta de nuevo.",
            )
        recognized_text = assessment["recognized_text"]
        turn_scores = assessment["scores"]

    try:
        result = await run_in_threadpool(conversation.answer, conversation_id, recognized_text)
    except conversation.ConversationError as error:
        raise HTTPException(status_code=error.status, detail=str(error))

    response = {"recognized_text": recognized_text, "turn_scores": turn_scores}
    if "final" in result:
        final = result["final"]
        scored = await run_in_threadpool(scoring.collect, conversation_id)
        scores, words = scoring.aggregate(scored)
        db.save_conversation(
            final["system_prompt"],
            final["questions_asked"],
            scores,
            final["content_feedback"],
            words,
        )
        response["final"] = {"scores": scores, "content_feedback": final["content_feedback"]}
    else:
        response["next_question"] = result["question"]
    return JSONResponse(response)
```

Nota: en modo `azure` con una sola respuesta sin voz, Azure devuelve `None` y el endpoint responde 422 para reintentar (ese turno no avanza). El scoring que falla queda descartado por `scoring.collect`.

- [ ] **Step 5: Correr los tests de la API**

Run: `uv run pytest test_api.py -v`
Expected: PASS todos (incluidos los nuevos y los viejos de `/conversation/start`).

- [ ] **Step 6: Correr toda la suite**

Run: `uv run pytest -v`
Expected: PASS todo.

- [ ] **Step 7: Commit**

```bash
git add main.py test_api.py
git commit -m "feat: endpoint de conversacion con modo navegador/azure y scoring diferido"
```

---

### Task 4: Toggle de transcripción y reconocimiento del navegador (frontend)

**Files:**
- Modify: `index.html`
- Modify: `app.js`
- Modify: `style.css`

**Interfaces:**
- Consumes (HTTP): `POST /conversation/{id}/answer` con `mode` + (si browser) `transcript`.
- Reutiliza de `app.js`: `recordSink`, `startRecording`, `stopRecording`, `renderScoreCards`, `speak`, `formatDetail`, `showConvError`, `switchView`.

Nota: sin arnés de tests JS. Verificación: `node --check app.js`, `uv run pytest` verde, e walkthrough manual.

- [ ] **Step 1: Toggle y etiqueta genérica en `index.html`**

Dentro de `#conv-setup`, después del input `conv-questions` y antes del `div.controls`, añade el selector de fuente:

```html
          <label for="conv-source">Fuente de transcripcion</label>
          <select id="conv-source">
            <option value="browser">Navegador (rapido, sin score por turno)</option>
            <option value="azure">Azure (mas lento, con score por turno)</option>
          </select>
          <p id="conv-source-note" class="hint hidden">
            Tu navegador no soporta reconocimiento de voz; se usara Azure.
          </p>
```

En `#conv-turn`, cambia la etiqueta fija de Azure por una genérica:

```html
          <div id="conv-turn" class="hidden">
            <div id="conv-turn-scores" class="scores"></div>
            <p class="hint">Lo que se escucho:</p>
            <p id="conv-recognized" class="recognized"></p>
          </div>
```

- [ ] **Step 2: Registrar los elementos nuevos en `els`**

En el objeto `els` de `app.js`, junto a los otros `conv*`, añade:

```javascript
  convSource: document.getElementById("conv-source"),
  convSourceNote: document.getElementById("conv-source-note"),
```

- [ ] **Step 3: Ajustes de fuente persistidos + detección de soporte**

Cerca de `let conversationId = null;` (inicio del bloque de conversación en `app.js`), añade:

```javascript
// Reconocimiento de voz del navegador (Web Speech API). Puede no existir (Firefox).
const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

// Fuente de transcripcion elegida, persistida en el navegador.
const convSettings = {
  source: localStorage.getItem("conv-source") || "browser",
};

let recognition = null;        // instancia activa de SpeechRecognition
let browserTranscript = "";    // texto acumulado del reconocimiento del turno
let recognitionEnded = null;   // promesa que resuelve cuando el reconocimiento termina

// Inicia el reconocimiento del navegador para el turno actual.
function startBrowserRecognition() {
  browserTranscript = "";
  recognition = new SpeechRecognition();
  recognition.lang = "en-US";
  recognition.continuous = true;
  recognition.interimResults = false;
  recognition.onresult = (event) => {
    for (let i = event.resultIndex; i < event.results.length; i++) {
      if (event.results[i].isFinal) {
        browserTranscript += event.results[i][0].transcript + " ";
      }
    }
  };
  recognitionEnded = new Promise((resolve) => {
    recognition.onend = resolve;
    recognition.onerror = resolve; // no bloquear el turno si el reconocimiento falla
  });
  recognition.start();
}

function stopBrowserRecognition() {
  if (recognition) recognition.stop();
}

// Aplica el ajuste guardado al selector y desactiva "Navegador" si no hay soporte.
function initConversationSettings() {
  if (!SpeechRecognition) {
    convSettings.source = "azure";
    const browserOption = els.convSource.querySelector('option[value="browser"]');
    if (browserOption) browserOption.disabled = true;
    els.convSourceNote.classList.remove("hidden");
  }
  els.convSource.value = convSettings.source;
  els.convSource.addEventListener("change", () => {
    convSettings.source = els.convSource.value;
    localStorage.setItem("conv-source", convSettings.source);
  });
}
```

Y llama a `initConversationSettings()` en el arranque (junto a la otra inicialización, p.ej. cerca de `initSettings()`):

```javascript
initConversationSettings();
```

- [ ] **Step 4: Enviar `mode` + `transcript` según la fuente**

Reemplaza la función `sendConversationAnswer` por:

```javascript
// Sink de grabacion para la conversacion: manda el audio (y, en modo navegador, el texto
// que transcribio el navegador) al servidor.
async function sendConversationAnswer(wavBlob) {
  els.convError.classList.add("hidden");
  const source = convSettings.source;
  const form = new FormData();
  form.append("audio", wavBlob, "answer.wav");
  form.append("mode", source);
  if (source === "browser") {
    if (recognitionEnded) await recognitionEnded; // esperar la transcripcion final
    form.append("transcript", browserTranscript.trim());
  }

  let response;
  try {
    response = await fetch(`/conversation/${conversationId}/answer`, {
      method: "POST",
      body: form,
    });
  } catch (err) {
    showConvError("No se pudo contactar al servidor: " + err.message);
    els.convStatus.textContent = "";
    return;
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    showConvError(formatDetail(body.detail) || `El servidor respondio ${response.status}.`);
    els.convStatus.textContent = "";
    return;
  }

  const data = await response.json();
  if (data.turn_scores) renderScoreCards(els.convTurnScores, data.turn_scores);
  else els.convTurnScores.innerHTML = "";
  els.convRecognized.textContent = data.recognized_text || "(vacio)";
  els.convTurn.classList.remove("hidden");

  if (data.final) {
    renderScoreCards(els.convFinalScores, data.final.scores);
    els.convFeedback.textContent = data.final.content_feedback;
    els.convActive.classList.add("hidden");
    els.convFinal.classList.remove("hidden");
    conversationId = null;
    els.convStatus.textContent = "";
    loadWordBank();
  } else {
    showQuestion(data.next_question);
    els.convStatus.textContent = "";
  }
}
```

- [ ] **Step 5: Arrancar/parar el reconocimiento en el botón de grabar**

Reemplaza el handler de `els.convRecord` por:

```javascript
els.convRecord.addEventListener("click", async () => {
  if (state === "idle") {
    recordSink = sendConversationAnswer;
    if (convSettings.source === "browser") startBrowserRecognition();
    await startRecording();
    if (state === "recording") {
      els.convRecord.textContent = "Parar";
      els.convStatus.textContent = "Grabando... responde ahora.";
    } else {
      // startRecording no arranco (permiso denegado, etc.). El error ya quedo visible
      // en convError; solo falta que el boton/estado no mientan.
      if (convSettings.source === "browser") stopBrowserRecognition();
      els.convRecord.textContent = "Responder";
      els.convStatus.textContent = "";
      recordSink = null;
    }
  } else if (state === "recording") {
    els.convRecord.textContent = "Responder";
    if (convSettings.source === "browser") stopBrowserRecognition();
    const pending = stopRecording();
    if (state === "sending") {
      els.convStatus.textContent =
        convSettings.source === "browser" ? "Transcribiendo..." : "Evaluando con Azure...";
    } else {
      els.convStatus.textContent = "";
    }
    await pending;
  }
});
```

- [ ] **Step 6: Estilo del selector (`style.css`)**

Añade al final de `style.css`:

```css
#conv-source {
  width: 100%;
  box-sizing: border-box;
}
```

- [ ] **Step 7: Verificación**

Run: `node --check app.js` → sin errores de sintaxis.
Run: `uv run pytest` → verde (solo el warning preexistente de Starlette).
Run: `uv run python -c "import main"` → OK.

Walkthrough manual (requiere `AZURE_SPEECH_KEY` + `GEMINI_API_KEY` en `.env`, Chrome):
1. Pestaña Conversacion → fuente "Navegador" → Empezar → primera pregunta suena.
2. Responder hablando → al Parar, la conversación pasa a la siguiente pregunta **sin esperar Azure**, mostrando "Lo que se escucho:" con la transcripción del navegador y sin score por turno.
3. Cambia la fuente a "Azure" en otra conversación → al responder aparece el score del turno (más lento).
4. Al terminar las N preguntas → resultado final con scores agregados + feedback; el banco de palabras se refresca.
5. La pestaña "Practicar" sigue intacta.

- [ ] **Step 8: Commit**

```bash
git add index.html app.js style.css
git commit -m "feat: toggle de transcripcion navegador/azure y reconocimiento del navegador"
```

---

## Notas y limitaciones (por diseño)

- El store de scoring vive en memoria del proceso; si el server se reinicia a mitad de una conversación se pierde el progreso (igual que el checkpointer del grafo).
- Modo navegador: la transcripción que ve Gemini puede diferir de Azure; la pronunciación la mide Azure sobre el audio real.
- `SpeechRecognition` requiere Chrome/Edge/Safari reciente (no Firefox) y conexión.
- Correr `SpeechRecognition` + grabación del WAV a la vez sobre el mismo micrófono es el escenario asumido (funciona en Chrome).
