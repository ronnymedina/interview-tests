# Modalidad de conversación (LangGraph + Gemini Flash) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Agregar una modalidad de práctica conversacional a `review-ingles`: un LLM (Gemini Flash vía LangGraph) hace N preguntas en inglés según un system prompt configurable; el usuario responde por voz, cada respuesta se evalúa con Azure sin texto de referencia, y al final se muestra y guarda un scoring de pronunciación agregado más feedback de contenido.

**Architecture:** Un grafo de LangGraph con checkpointer en memoria (`InMemorySaver`) mantiene el estado de cada conversación por `thread_id`. Cada turno del usuario llega por HTTP: el endpoint corre Azure en modo *unscripted* (`reference_text=""`), inyecta el texto reconocido como mensaje humano en el grafo y este produce la siguiente pregunta o, al alcanzar el número fijo de preguntas, el feedback de contenido. Solo se persiste el resultado final en SQLite.

**Tech Stack:** FastAPI, LangGraph, langchain-google-genai (Gemini), Azure Speech (ya integrado), SQLite, JS vanilla en el frontend, pytest.

## Global Constraints

- Python `>=3.11` (ver `pyproject.toml`).
- Todas las variables de entorno se leen **únicamente en `config.py`**; el resto del código importa constantes ya tipadas. Ningún `os.getenv` fuera de `config.py`.
- Mensajes de error orientados al usuario en español, como HTTPException con `detail` string (patrón actual).
- No modificar la función `speech.assess()` existente (la práctica con referencia sigue igual).
- TDD: test que falla → implementación mínima → test pasa → commit. Commits frecuentes.
- Comandos de test se corren con `uv run pytest` desde `review-ingles/`.
- El frontend de este proyecto no tiene arnés de pruebas JS; las tareas de UI se validan manualmente (igual que el resto del proyecto).

---

### Task 1: Dependencias, config y `.env.example`

**Files:**
- Modify: `pyproject.toml`
- Modify: `config.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: `config.GEMINI_API_KEY: str`, `config.GEMINI_MODEL: str`.

- [ ] **Step 1: Añadir dependencias**

En `pyproject.toml`, agrega a `dependencies` (después de `azure-cognitiveservices-speech>=1.40`):

```toml
    "langgraph>=0.2",
    "langchain-google-genai>=2.0",
```

- [ ] **Step 2: Instalar**

Run: `uv sync`
Expected: instala `langgraph` y `langchain-google-genai` sin error.

- [ ] **Step 3: Exponer las variables en `config.py`**

Añade al final de `config.py` (antes de nada más es indiferente; mantener el estilo):

```python
# Credenciales de Gemini para la modalidad de conversacion. Sin la key el servidor
# arranca igual, pero el primer intento de conversacion devuelve un error explicativo.
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
```

- [ ] **Step 4: Documentar en `.env.example`**

Añade al final de `.env.example`:

```
# Gemini (modalidad de conversacion). Consigue una key en https://aistudio.google.com/apikey
GEMINI_API_KEY=
# Modelo de Gemini a usar (opcional; por defecto gemini-2.5-flash)
GEMINI_MODEL=gemini-2.5-flash
```

- [ ] **Step 5: Verificar que config importa**

Run: `uv run python -c "import config; print(config.GEMINI_MODEL)"`
Expected: imprime `gemini-2.5-flash`.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock config.py .env.example
git commit -m "feat: dependencias y config para la modalidad de conversacion"
```

---

### Task 2: Evaluación de pronunciación sin referencia (`speech.assess_unscripted`)

**Files:**
- Modify: `azure_speech.py:37-67` (método `recognize`)
- Modify: `speech.py`
- Test: `test_speech.py`

**Interfaces:**
- Consumes: `AzureSpeechClient.recognize(wav_path, reference_text)` (ya existe), `speech.SpeechError`.
- Produces: `speech.assess_unscripted(wav_path: str, client: AzureSpeechClient | None = None) -> dict`. Devuelve el mismo shape que `speech.assess`: `{"recognized_text": str, "scores": {"pronunciation", "accuracy", "fluency", "completeness", "prosody"}, "words": [ {"word","accuracy","error_type","phonemes"} ]}`. En modo unscripted `completeness` es siempre `None`.

- [ ] **Step 1: Test — se llama a Azure con referencia vacía y sin completeness**

Añade a `test_speech.py`:

```python
def test_unscripted_passes_empty_reference():
    state = make_state([rec_word("hello", 95.0)], ["hello"], durations=[500000], end=600000)
    client = FakeClient(state)
    speech.assess_unscripted("a.wav", client=client)
    # Sin texto de referencia: se pasa cadena vacia al wrapper.
    assert client.called_with == ("a.wav", "")


def test_unscripted_scores_have_no_completeness():
    state = make_state([rec_word("hello", 90.0), rec_word("world", 80.0)],
                       ["hello world"], durations=[500000, 400000], end=1_000_000)
    result = speech.assess_unscripted("a.wav", client=FakeClient(state))
    assert result["scores"]["completeness"] is None
    assert result["scores"]["accuracy"] == 85.0
    assert result["recognized_text"] == "hello world"
```

- [ ] **Step 2: Correr y ver que falla**

Run: `uv run pytest test_speech.py::test_unscripted_passes_empty_reference test_speech.py::test_unscripted_scores_have_no_completeness -v`
Expected: FAIL con `AttributeError: module 'speech' has no attribute 'assess_unscripted'`.

- [ ] **Step 3: Ajustar `azure_speech.recognize` para desactivar miscue sin referencia**

En `azure_speech.py`, dentro de `recognize`, cambia la construcción de `PronunciationAssessmentConfig`:

```python
        pron_config = speechsdk.PronunciationAssessmentConfig(
            reference_text=reference_text,
            grading_system=speechsdk.PronunciationAssessmentGradingSystem.HundredMark,
            granularity=speechsdk.PronunciationAssessmentGranularity.Phoneme,
            # Sin texto de referencia (modo unscripted) no hay omisiones/inserciones que
            # comparar: el miscue solo tiene sentido con referencia.
            enable_miscue=bool(reference_text),
        )
```

- [ ] **Step 4: Implementar `assess_unscripted` en `speech.py`**

Añade a `speech.py` (después de `assess`):

```python
def assess_unscripted(wav_path: str, client: AzureSpeechClient | None = None) -> dict:
    """Evalua la pronunciacion de un WAV SIN texto de referencia.

    Se usa en la conversacion: el usuario habla libremente y no hay un texto previo que
    comparar. Azure reconoce lo dicho y puntua accuracy/fluency/prosody; no hay
    completeness (requiere referencia). El texto reconocido sirve ademas como la
    transcripcion de lo que dijo el usuario.
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
        raise SpeechError(f"Azure cancelo la peticion: {error}", status=502)

    if not state["words"]:
        raise SpeechError(
            "No se detecto voz en el audio. Revisa el microfono e intenta de nuevo.",
            status=422,
        )

    return _aggregate_unscripted(state)


def _aggregate_unscripted(state: dict) -> dict:
    """Combina los segmentos en un resultado sin referencia (sin completeness ni miscue)."""
    words = list(state["words"])

    # Accuracy por debajo de 60 sin otro error = mala pronunciacion (misma regla que assess).
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

    # El peor score pesa mas (misma idea que la formula oficial), pero sin completeness.
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
    }
```

- [ ] **Step 5: Correr los dos tests y ver que pasan**

Run: `uv run pytest test_speech.py::test_unscripted_passes_empty_reference test_speech.py::test_unscripted_scores_have_no_completeness -v`
Expected: PASS ambos.

- [ ] **Step 6: Test — errores (mispronunciation, sin voz, sin key, cancelado)**

Añade a `test_speech.py`:

```python
def test_unscripted_mispronunciation_below_60():
    state = make_state([rec_word("hello", 40.0)], ["hello"], durations=[500000], end=600000)
    result = speech.assess_unscripted("a.wav", client=FakeClient(state))
    assert result["words"][0]["error_type"] == "Mispronunciation"


def test_unscripted_no_speech_raises_422():
    with pytest.raises(speech.SpeechError) as error:
        speech.assess_unscripted("a.wav", client=FakeClient(make_state([], [])))
    assert error.value.status == 422


def test_unscripted_missing_key_raises_500(monkeypatch):
    monkeypatch.setattr(config, "AZURE_SPEECH_KEY", "")
    with pytest.raises(speech.SpeechError) as error:
        speech.assess_unscripted("a.wav", client=FakeClient(make_state([], [])))
    assert error.value.status == 500


def test_unscripted_cancel_translated_to_502():
    client = FakeClient(error=AzureSpeechError("boom"))
    with pytest.raises(speech.SpeechError) as error:
        speech.assess_unscripted("a.wav", client=client)
    assert error.value.status == 502
```

- [ ] **Step 7: Correr todo el archivo**

Run: `uv run pytest test_speech.py -v`
Expected: PASS todos (los viejos y los nuevos).

- [ ] **Step 8: Commit**

```bash
git add azure_speech.py speech.py test_speech.py
git commit -m "feat: assess_unscripted para evaluar pronunciacion sin texto de referencia"
```

---

### Task 3: Persistencia — tabla `conversations` y banco de palabras compartido

**Files:**
- Modify: `db.py`
- Test: `test_db.py`

**Interfaces:**
- Consumes: `config.DB_PATH`, `_connect()`, `_save_words()` (se refactoriza).
- Produces:
  - `db.save_conversation(system_prompt: str, questions_asked: int, scores: dict, content_feedback: str, words: list[dict]) -> int`. `scores` tiene claves `pronunciation`, `accuracy`, `fluency`, `prosody`. `words` es la lista acumulada de todos los turnos (mismo shape que `result["words"]`).
  - `db.list_conversations(limit: int = 20) -> list[dict]`.

- [ ] **Step 1: Test — guardar una conversación y leerla**

Añade a `test_db.py`:

```python
def test_save_and_list_conversation(temp_db):
    scores = {"pronunciation": 82.0, "accuracy": 85.0, "fluency": 80.0, "prosody": 78.0}
    words = [
        {"word": "Yesterday", "error_type": "None", "accuracy": 90.0, "phonemes": []},
        {"word": "worked", "error_type": "Mispronunciation", "accuracy": 55.0, "phonemes": []},
    ]
    cid = db.save_conversation("Roleplay sobre trabajo", 3, scores, "Buen vocabulario.", words)
    listed = db.list_conversations()
    assert len(listed) == 1
    assert listed[0]["id"] == cid
    assert listed[0]["system_prompt"] == "Roleplay sobre trabajo"
    assert listed[0]["questions_asked"] == 3
    assert listed[0]["pronunciation_score"] == 82.0
    assert listed[0]["content_feedback"] == "Buen vocabulario."


def test_conversation_words_feed_word_bank(temp_db):
    scores = {"pronunciation": 82.0, "accuracy": 85.0, "fluency": 80.0, "prosody": 78.0}
    words = [{"word": "Yesterday", "error_type": "None", "accuracy": 90.0, "phonemes": []}]
    db.save_conversation("Roleplay", 1, scores, "ok", words)
    stats = db.list_word_stats()
    assert [s["word"] for s in stats] == ["yesterday"]
    assert stats[0]["avg_accuracy"] == 90.0
```

- [ ] **Step 2: Correr y ver que falla**

Run: `uv run pytest test_db.py::test_save_and_list_conversation -v`
Expected: FAIL con `AttributeError: module 'db' has no attribute 'save_conversation'`.

- [ ] **Step 3: Actualizar el esquema y el reset de tablas legacy**

En `db.py`, reemplaza el bloque `word_scores` de `SCHEMA` (líneas 36-44) por:

```python
-- Una fila por palabra, tanto de intentos de lectura como de conversaciones, para el
-- historial por palabra agregado entre todas las practicas.
CREATE TABLE IF NOT EXISTS word_scores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id      INTEGER,         -- set en intentos de lectura; NULL en conversaciones
    conversation_id INTEGER,         -- set en conversaciones; NULL en intentos
    created_at      TEXT NOT NULL,
    word            TEXT NOT NULL,   -- en minuscula, para agrupar
    accuracy        REAL,            -- NULL si la palabra se omitio (no se pronuncio)
    error_type      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_word_scores_word ON word_scores (word);

-- Resultado final de cada conversacion (no se guarda el turno-a-turno).
CREATE TABLE IF NOT EXISTS conversations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at          TEXT NOT NULL,
    system_prompt       TEXT NOT NULL,
    questions_asked     INTEGER NOT NULL,
    pronunciation_score REAL,
    accuracy_score      REAL,
    fluency_score       REAL,
    prosody_score       REAL,
    content_feedback    TEXT NOT NULL
);
```

En `_drop_legacy_tables`, añade al final (mismo espíritu de "reset de una sola vez, sin migración" que ya usa el proyecto):

```python
    # word_scores gano la columna conversation_id: si existe una version vieja sin ella,
    # se descarta y se recrea (se pierde el historial por palabra, no hay migracion).
    ws_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'word_scores'"
    ).fetchone()
    if ws_exists:
        ws_columns = {row["name"] for row in conn.execute("PRAGMA table_info(word_scores)")}
        if "conversation_id" not in ws_columns:
            conn.executescript("DROP TABLE IF EXISTS word_scores;")
```

- [ ] **Step 4: Refactorizar `_save_words` para aceptar origen (intento o conversación)**

Reemplaza `_save_words` (líneas 176-192) por:

```python
def _save_words(
    conn,
    created_at: str,
    words: list[dict],
    *,
    attempt_id: int | None = None,
    conversation_id: int | None = None,
) -> None:
    """Guarda cada palabra en word_scores para el banco de palabras.

    Se usa tanto para intentos de lectura (`attempt_id`) como para conversaciones
    (`conversation_id`); exactamente uno de los dos viene informado. Las inserciones
    (palabras dichas que no tocaban) se ignoran; las omisiones se guardan con accuracy NULL.
    """
    rows = []
    for word in words:
        if word["error_type"] == "Insertion":
            continue
        accuracy = None if word["error_type"] == "Omission" else word["accuracy"]
        rows.append(
            (attempt_id, conversation_id, created_at, word["word"].lower(), accuracy, word["error_type"])
        )
    conn.executemany(
        "INSERT INTO word_scores (attempt_id, conversation_id, created_at, word, accuracy, error_type) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        rows,
    )
```

Actualiza la llamada dentro de `save_attempt` (línea 172) de:

```python
        _save_words(conn, attempt_id, now, result["words"])
```

a:

```python
        _save_words(conn, now, result["words"], attempt_id=attempt_id)
```

- [ ] **Step 5: Implementar `save_conversation` y `list_conversations`**

Añade a `db.py` (después de `save_attempt`, antes de `list_attempts`):

```python
def save_conversation(
    system_prompt: str,
    questions_asked: int,
    scores: dict,
    content_feedback: str,
    words: list[dict],
) -> int:
    """Guarda el resultado final de una conversacion y alimenta el banco de palabras.

    `scores` trae pronunciation/accuracy/fluency/prosody agregados; `words` es la lista
    acumulada de todas las respuestas del usuario (mismo shape que result["words"]).
    """
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as conn:
        cursor = conn.execute(
            """
            INSERT INTO conversations (
                created_at, system_prompt, questions_asked,
                pronunciation_score, accuracy_score, fluency_score,
                prosody_score, content_feedback
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                system_prompt,
                questions_asked,
                scores["pronunciation"],
                scores["accuracy"],
                scores["fluency"],
                scores["prosody"],
                content_feedback,
            ),
        )
        conversation_id = cursor.lastrowid or 0
        _save_words(conn, now, words, conversation_id=conversation_id)
        return conversation_id


def list_conversations(limit: int = 20) -> list[dict]:
    """Cabeceras de las ultimas conversaciones guardadas."""
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT id, created_at, system_prompt, questions_asked,
                   pronunciation_score, accuracy_score, fluency_score,
                   prosody_score, content_feedback
            FROM conversations
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]
```

- [ ] **Step 6: Correr los tests de db**

Run: `uv run pytest test_db.py -v`
Expected: PASS todos (los viejos siguen verdes porque `save_attempt` sigue funcionando; los nuevos también).

- [ ] **Step 7: Commit**

```bash
git add db.py test_db.py
git commit -m "feat: persistencia de conversaciones y banco de palabras compartido"
```

---

### Task 4: El grafo de conversación (`conversation.py`)

**Files:**
- Create: `conversation.py`
- Test: `test_conversation.py`

**Interfaces:**
- Consumes: `config.GEMINI_API_KEY`, `config.GEMINI_MODEL`.
- Produces:
  - `conversation.ConversationError(Exception)` con atributo `.status: int`.
  - `conversation.build_graph(llm) -> CompiledGraph`. `llm` es cualquier objeto con `.invoke(messages) -> obj` donde `obj.content` es un `str` (permite inyectar un doble en tests).
  - `conversation.start(system_prompt: str, max_questions: int, graph=None) -> tuple[str, str]` → `(conversation_id, primera_pregunta)`.
  - `conversation.answer(conversation_id: str, recognized_text: str, turn_scores: dict, turn_words: list[dict], graph=None) -> dict`. Devuelve `{"question": str}` en un turno intermedio, o `{"final": {"scores": dict, "content_feedback": str, "system_prompt": str, "questions_asked": int, "words": list[dict]}}` en el último.
  - `conversation.aggregate_scores(per_turn_scores: list[dict]) -> dict` con claves `pronunciation`, `accuracy`, `fluency`, `prosody`.

- [ ] **Step 1: Test — arranque hace la primera pregunta**

Crea `test_conversation.py`:

```python
"""Tests del grafo de conversacion con un LLM falso (sin red)."""

import pytest
from langchain_core.messages import AIMessage

import conversation


class FakeLLM:
    """Doble del cliente Gemini: devuelve respuestas predefinidas en orden."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        return AIMessage(self._replies.pop(0))


def _scores(pronunciation):
    return {
        "pronunciation": pronunciation,
        "accuracy": pronunciation,
        "fluency": pronunciation,
        "prosody": pronunciation,
    }


def test_start_asks_first_question():
    graph = conversation.build_graph(FakeLLM(["What did you do yesterday?"]))
    conversation_id, question = conversation.start("Roleplay sobre trabajo", 2, graph=graph)
    assert isinstance(conversation_id, str) and conversation_id
    assert question == "What did you do yesterday?"
```

- [ ] **Step 2: Correr y ver que falla**

Run: `uv run pytest test_conversation.py::test_start_asks_first_question -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'conversation'`.

- [ ] **Step 3: Implementar `conversation.py`**

Crea `conversation.py`:

```python
"""Grafo de conversacion con LangGraph + Gemini.

Este archivo es el UNICO punto que habla con LangGraph y con Gemini (analogo a como
azure_speech.py aisla Azure). Mantiene el estado de cada conversacion en memoria mediante
el checkpointer de LangGraph, indexado por conversation_id (el thread_id del grafo).

El turno del usuario (audio -> Azure -> texto reconocido) ocurre fuera del grafo, en el
endpoint HTTP; aqui solo entra el texto ya reconocido como mensaje humano.
"""

import operator
import uuid
from typing import Annotated, TypedDict

from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages

import config

# Instruccion interna que envuelve al system prompt del usuario. Fija el formato (una
# pregunta por turno) sin pisar el escenario que define el usuario.
_ASK_INSTRUCTION = (
    "You are a spoken English practice partner. Follow the scenario described below. "
    "Ask exactly ONE short, natural question in English per turn, then stop and wait for "
    "the learner's spoken answer. Never answer on the learner's behalf. Scenario:\n\n"
)

# Instruccion para el feedback final de contenido.
_FEEDBACK_INSTRUCTION = (
    "The practice is over. In Spanish, give the learner brief feedback (4-6 sentences) on "
    "their English across the whole conversation: grammar, vocabulary and how to improve."
)


class ConversationError(Exception):
    """Error pensado para mostrarse al usuario. `status` es el codigo HTTP."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    system_prompt: str
    max_questions: int
    questions_asked: int
    per_turn_scores: Annotated[list[dict], operator.add]
    per_turn_words: Annotated[list[dict], operator.add]
    content_feedback: str


def build_graph(llm):
    """Construye y compila el grafo con un checkpointer en memoria.

    `llm` es cualquier objeto con `.invoke(messages).content -> str`.
    En cada invocacion corre exactamente un nodo (ask o finalize) y termina; el estado
    persiste por thread_id entre invocaciones.
    """

    def route(state: State) -> str:
        return "finalize" if state["questions_asked"] >= state["max_questions"] else "ask"

    def ask(state: State) -> dict:
        question = llm.invoke(state["messages"]).content
        return {
            "messages": [AIMessage(question)],
            "questions_asked": state["questions_asked"] + 1,
        }

    def finalize(state: State) -> dict:
        feedback = llm.invoke(
            state["messages"] + [HumanMessage(_FEEDBACK_INSTRUCTION)]
        ).content
        return {"content_feedback": feedback}

    graph = StateGraph(State)
    graph.add_node("ask", ask)
    graph.add_node("finalize", finalize)
    graph.add_conditional_edges(START, route, {"ask": "ask", "finalize": "finalize"})
    graph.add_edge("ask", END)
    graph.add_edge("finalize", END)
    return graph.compile(checkpointer=InMemorySaver())


# Grafo real (Gemini), construido una sola vez. Los tests usan build_graph con un doble.
_graph = None


def _get_graph():
    global _graph
    if _graph is None:
        if not config.GEMINI_API_KEY:
            raise ConversationError(
                "Falta GEMINI_API_KEY en el archivo .env. Copia .env.example a .env "
                "y pon tu clave de Gemini.",
                status=500,
            )
        from langchain_google_genai import ChatGoogleGenerativeAI

        llm = ChatGoogleGenerativeAI(
            model=config.GEMINI_MODEL, google_api_key=config.GEMINI_API_KEY
        )
        _graph = build_graph(llm)
    return _graph


def _config(conversation_id: str) -> dict:
    return {"configurable": {"thread_id": conversation_id}}


def start(system_prompt: str, max_questions: int, graph=None) -> tuple[str, str]:
    """Crea una conversacion nueva y devuelve (conversation_id, primera_pregunta)."""
    graph = graph or _get_graph()
    conversation_id = uuid.uuid4().hex
    result = graph.invoke(
        {
            "messages": [SystemMessage(_ASK_INSTRUCTION + system_prompt)],
            "system_prompt": system_prompt,
            "max_questions": max_questions,
            "questions_asked": 0,
            "per_turn_scores": [],
            "per_turn_words": [],
            "content_feedback": "",
        },
        _config(conversation_id),
    )
    return conversation_id, result["messages"][-1].content


def answer(
    conversation_id: str,
    recognized_text: str,
    turn_scores: dict,
    turn_words: list[dict],
    graph=None,
) -> dict:
    """Inyecta la respuesta del usuario y devuelve la siguiente pregunta o el resultado final."""
    graph = graph or _get_graph()
    cfg = _config(conversation_id)

    # Conversacion desconocida (proceso reiniciado o id invalido): el checkpointer no tiene
    # estado para ese thread_id.
    if not graph.get_state(cfg).values:
        raise ConversationError("La conversacion no existe o expiro.", status=404)

    result = graph.invoke(
        {
            "messages": [HumanMessage(recognized_text)],
            "per_turn_scores": [turn_scores],
            "per_turn_words": list(turn_words),
        },
        cfg,
    )

    if result["content_feedback"]:
        return {
            "final": {
                "scores": aggregate_scores(result["per_turn_scores"]),
                "content_feedback": result["content_feedback"],
                "system_prompt": result["system_prompt"],
                "questions_asked": result["questions_asked"],
                "words": result["per_turn_words"],
            }
        }
    return {"question": result["messages"][-1].content}


def aggregate_scores(per_turn_scores: list[dict]) -> dict:
    """Promedia los scores de todos los turnos. Ignora None (ej. prosody no soportada)."""

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

- [ ] **Step 4: Correr el test de arranque**

Run: `uv run pytest test_conversation.py::test_start_asks_first_question -v`
Expected: PASS.

- [ ] **Step 5: Test — flujo completo llega al feedback, y conversación desconocida da 404**

Añade a `test_conversation.py`:

```python
def test_full_flow_reaches_feedback():
    graph = conversation.build_graph(FakeLLM(["Q1", "Q2", "FEEDBACK"]))
    conversation_id, q1 = conversation.start("Roleplay", 2, graph=graph)
    assert q1 == "Q1"

    r1 = conversation.answer(conversation_id, "answer one", _scores(80.0), [], graph=graph)
    assert r1 == {"question": "Q2"}

    r2 = conversation.answer(conversation_id, "answer two", _scores(90.0), [], graph=graph)
    assert "final" in r2
    assert r2["final"]["content_feedback"] == "FEEDBACK"
    assert r2["final"]["questions_asked"] == 2
    assert r2["final"]["scores"]["pronunciation"] == 85.0


def test_words_accumulate_across_turns():
    graph = conversation.build_graph(FakeLLM(["Q1", "FEEDBACK"]))
    words_turn = [{"word": "hello", "error_type": "None", "accuracy": 90.0, "phonemes": []}]
    conversation_id, _ = conversation.start("Roleplay", 1, graph=graph)
    result = conversation.answer(conversation_id, "hello", _scores(90.0), words_turn, graph=graph)
    assert result["final"]["words"] == words_turn


def test_answer_unknown_conversation_raises_404():
    graph = conversation.build_graph(FakeLLM([]))
    with pytest.raises(conversation.ConversationError) as error:
        conversation.answer("does-not-exist", "hi", _scores(80.0), [], graph=graph)
    assert error.value.status == 404
```

- [ ] **Step 6: Correr todo el archivo**

Run: `uv run pytest test_conversation.py -v`
Expected: PASS todos.

- [ ] **Step 7: Commit**

```bash
git add conversation.py test_conversation.py
git commit -m "feat: grafo de conversacion con LangGraph y Gemini"
```

---

### Task 5: Endpoints de conversación (`main.py`)

**Files:**
- Modify: `main.py`
- Modify: `conftest.py` (helper de resultado unscripted)
- Test: `test_api.py`

**Interfaces:**
- Consumes: `speech.assess_unscripted`, `conversation.start`, `conversation.answer`, `conversation.ConversationError`, `db.save_conversation`.
- Produces (HTTP):
  - `POST /conversation/start` body JSON `{system_prompt: str, max_questions: int = 5}` → `{conversation_id, question}`.
  - `POST /conversation/{conversation_id}/answer` multipart `audio` → intermedio `{recognized_text, turn_scores, words, next_question}` o final `{recognized_text, turn_scores, words, final}`.

- [ ] **Step 1: Helper de resultado unscripted en `conftest.py`**

Añade a `conftest.py`:

```python
def make_unscripted_result(recognized="hello world", pronunciation=85.0):
    """Un result de speech.assess_unscripted() minimo (sin completeness)."""
    return {
        "recognized_text": recognized,
        "scores": {
            "pronunciation": pronunciation,
            "accuracy": 88.0,
            "fluency": 80.0,
            "completeness": None,
            "prosody": 70.0,
        },
        "words": [
            {"word": "hello", "error_type": "None", "accuracy": 95.0, "phonemes": []},
        ],
    }
```

- [ ] **Step 2: Test — start valida y devuelve pregunta**

Añade a `test_api.py` (importa `conversation` arriba: `import conversation`):

```python
def test_conversation_start_returns_question(client, monkeypatch):
    monkeypatch.setattr(conversation, "start", lambda prompt, max_q: ("cid-1", "First question?"))
    resp = client.post("/conversation/start", json={"system_prompt": "Roleplay", "max_questions": 3})
    assert resp.status_code == 200
    assert resp.json() == {"conversation_id": "cid-1", "question": "First question?"}


def test_conversation_start_empty_prompt_rejected(client):
    resp = client.post("/conversation/start", json={"system_prompt": "   ", "max_questions": 3})
    assert resp.status_code == 400


def test_conversation_start_bad_max_rejected(client):
    resp = client.post("/conversation/start", json={"system_prompt": "Roleplay", "max_questions": 0})
    assert resp.status_code == 400
```

- [ ] **Step 3: Correr y ver que falla**

Run: `uv run pytest test_api.py::test_conversation_start_returns_question -v`
Expected: FAIL con 404/405 (la ruta no existe todavía).

- [ ] **Step 4: Implementar los endpoints en `main.py`**

Añade el import arriba, junto a los otros:

```python
import conversation
```

Añade el modelo de entrada junto a `TextIn`:

```python
class ConversationStartIn(BaseModel):
    system_prompt: str
    max_questions: int = 5
```

Añade los endpoints (después de `assess`, antes de `history`):

```python
@app.post("/conversation/start")
def conversation_start(payload: ConversationStartIn) -> dict:
    prompt = payload.system_prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="El system prompt esta vacio.")
    if not (1 <= payload.max_questions <= 20):
        raise HTTPException(
            status_code=400, detail="El numero de preguntas debe estar entre 1 y 20."
        )
    try:
        conversation_id, question = conversation.start(prompt, payload.max_questions)
    except conversation.ConversationError as error:
        raise HTTPException(status_code=error.status, detail=str(error))
    return {"conversation_id": conversation_id, "question": question}


@app.post("/conversation/{conversation_id}/answer")
async def conversation_answer(conversation_id: str, audio: UploadFile) -> JSONResponse:
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="No llego audio.")

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio_bytes)
        wav_path = tmp.name

    try:
        assessment = await run_in_threadpool(speech.assess_unscripted, wav_path)
    except speech.SpeechError as error:
        raise HTTPException(status_code=error.status, detail=str(error))
    finally:
        os.unlink(wav_path)

    try:
        result = await run_in_threadpool(
            conversation.answer,
            conversation_id,
            assessment["recognized_text"],
            assessment["scores"],
            assessment["words"],
        )
    except conversation.ConversationError as error:
        raise HTTPException(status_code=error.status, detail=str(error))

    response = {
        "recognized_text": assessment["recognized_text"],
        "turn_scores": assessment["scores"],
        "words": assessment["words"],
    }
    if "final" in result:
        final = result["final"]
        db.save_conversation(
            final["system_prompt"],
            final["questions_asked"],
            final["scores"],
            final["content_feedback"],
            final["words"],
        )
        response["final"] = final
    else:
        response["next_question"] = result["question"]
    return JSONResponse(response)
```

- [ ] **Step 5: Correr los tests de start**

Run: `uv run pytest test_api.py::test_conversation_start_returns_question test_api.py::test_conversation_start_empty_prompt_rejected test_api.py::test_conversation_start_bad_max_rejected -v`
Expected: PASS los tres.

- [ ] **Step 6: Test — answer intermedio y final (que persiste)**

Añade a `test_api.py` (importa el helper: `from conftest import make_result, make_unscripted_result`):

```python
def test_conversation_answer_intermediate(client, monkeypatch):
    monkeypatch.setattr(speech, "assess_unscripted", lambda wav_path: make_unscripted_result())
    monkeypatch.setattr(
        conversation, "answer",
        lambda cid, text, scores, words: {"question": "Next question?"},
    )
    resp = client.post(
        "/conversation/cid-1/answer",
        files={"audio": ("r.wav", b"fake-audio", "audio/wav")},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["next_question"] == "Next question?"
    assert body["recognized_text"] == "hello world"
    assert body["turn_scores"]["completeness"] is None


def test_conversation_answer_final_is_saved(client, monkeypatch):
    monkeypatch.setattr(speech, "assess_unscripted", lambda wav_path: make_unscripted_result())
    final_payload = {
        "final": {
            "scores": {"pronunciation": 84.0, "accuracy": 88.0, "fluency": 80.0, "prosody": 70.0},
            "content_feedback": "Buen intento.",
            "system_prompt": "Roleplay",
            "questions_asked": 2,
            "words": [{"word": "hello", "error_type": "None", "accuracy": 95.0, "phonemes": []}],
        }
    }
    monkeypatch.setattr(conversation, "answer", lambda cid, text, scores, words: final_payload)

    resp = client.post(
        "/conversation/cid-1/answer",
        files={"audio": ("r.wav", b"fake-audio", "audio/wav")},
    )
    assert resp.status_code == 200
    assert resp.json()["final"]["content_feedback"] == "Buen intento."

    saved = db.list_conversations()
    assert len(saved) == 1
    assert saved[0]["system_prompt"] == "Roleplay"
    assert saved[0]["pronunciation_score"] == 84.0
    # Las palabras alimentaron el banco.
    assert [s["word"] for s in db.list_word_stats()] == ["hello"]
```

- [ ] **Step 7: Correr todo `test_api.py`**

Run: `uv run pytest test_api.py -v`
Expected: PASS todos.

- [ ] **Step 8: Correr toda la suite**

Run: `uv run pytest -v`
Expected: PASS todos los archivos.

- [ ] **Step 9: Commit**

```bash
git add main.py conftest.py test_api.py
git commit -m "feat: endpoints de conversacion (start y answer)"
```

---

### Task 6: Vista "Conversación" en el frontend

**Files:**
- Modify: `index.html`
- Modify: `app.js`
- Modify: `style.css`

**Interfaces:**
- Consumes (HTTP): `POST /conversation/start`, `POST /conversation/{id}/answer`.
- Reutiliza de `app.js`: `speak()`, `encodeWav()`, `startRecording`/`stopRecording` (se generaliza el destino del audio), `switchView()`, `escapeHtml()`, `formatScore()`, `scoreClass()`, `formatDetail()`.

Nota: no hay arnés de pruebas JS en el proyecto; esta tarea se valida manualmente corriendo el servidor.

- [ ] **Step 1: Añadir el botón de menú y la sección en `index.html`**

En `<nav class="menu">` añade un botón después de "Practicar":

```html
        <button type="button" data-view="conversation">Conversacion</button>
```

Añade la sección nueva después de `</section>` de la vista practice (antes de la vista texts):

```html
      <!-- Vista: conversacion con el LLM -->
      <section id="view-conversation" class="view hidden">
        <p class="sub">
          Define un escenario, el asistente te hara preguntas en ingles (las escuchas y las
          lees), tu respondes hablando y al final ves tu pronunciacion y un feedback.
        </p>

        <!-- Configuracion inicial -->
        <div id="conv-setup">
          <label for="conv-prompt">Escenario (system prompt)</label>
          <textarea id="conv-prompt" rows="4"
            placeholder="Hazme preguntas en ingles sobre mi experiencia de trabajo, en pasado."></textarea>

          <label for="conv-questions">Numero de preguntas (1-20)</label>
          <input id="conv-questions" type="number" min="1" max="20" value="5" />

          <div class="controls">
            <button id="conv-start" type="button">Empezar</button>
            <span id="conv-setup-error" class="error hidden"></span>
          </div>
        </div>

        <!-- Conversacion en curso -->
        <div id="conv-active" class="hidden">
          <div class="reference-block">
            <button id="conv-listen" type="button" class="secondary small">🔊 Repetir</button>
            <p id="conv-question" class="reference-text"></p>
          </div>

          <div class="controls">
            <button id="conv-record" type="button">Responder</button>
            <span id="conv-status" class="status"></span>
          </div>

          <div id="conv-turn" class="hidden">
            <div id="conv-turn-scores" class="scores"></div>
            <p class="hint">Lo que Azure escucho:</p>
            <p id="conv-recognized" class="recognized"></p>
          </div>

          <div id="conv-error" class="error hidden"></div>
        </div>

        <!-- Resultado final -->
        <div id="conv-final" class="hidden">
          <h2>Resultado de la conversacion</h2>
          <div id="conv-final-scores" class="scores"></div>
          <h2>Feedback</h2>
          <p id="conv-feedback" class="recognized"></p>
          <div class="controls">
            <button id="conv-restart" type="button">Nueva conversacion</button>
          </div>
        </div>
      </section>
```

- [ ] **Step 2: Generalizar la grabación en `app.js` para que sirva a la conversación**

La grabación actual está atada a la vista de práctica (revisa `startRecording` en `app.js:114`, que valida `els.textSelect.value`, y `stopRecording` en `app.js:166`, que llama a `sendForAssessment`). Para reutilizarla sin romper la práctica, añade un "sink" configurable.

Cerca de `let state = "idle";` (app.js:49), añade:

```javascript
// A donde va el audio al parar de grabar. Por defecto, la evaluacion de un texto.
// La vista de conversacion lo cambia a su propio manejador.
let recordSink = null;
```

En `startRecording` (app.js:114-119), reemplaza la guarda inicial:

```javascript
async function startRecording() {
  clearError();
  if (!recordSink && !els.textSelect.value) {
    showError("Elige primero un texto para practicar.");
    return;
  }
```

En `stopRecording` (app.js:178-183), reemplaza el envío:

```javascript
  setState("sending");
  try {
    const wavBlob = encodeWav(recorded, sampleRate);
    if (recordSink) await recordSink(wavBlob);
    else await sendForAssessment(wavBlob);
  } finally {
    setState("idle");
  }
```

- [ ] **Step 3: Añadir los elementos nuevos al objeto `els`**

En el objeto `els` (app.js:7-38), añade:

```javascript
  convSetup: document.getElementById("conv-setup"),
  convPrompt: document.getElementById("conv-prompt"),
  convQuestions: document.getElementById("conv-questions"),
  convStart: document.getElementById("conv-start"),
  convSetupError: document.getElementById("conv-setup-error"),
  convActive: document.getElementById("conv-active"),
  convListen: document.getElementById("conv-listen"),
  convQuestion: document.getElementById("conv-question"),
  convRecord: document.getElementById("conv-record"),
  convStatus: document.getElementById("conv-status"),
  convTurn: document.getElementById("conv-turn"),
  convTurnScores: document.getElementById("conv-turn-scores"),
  convRecognized: document.getElementById("conv-recognized"),
  convError: document.getElementById("conv-error"),
  convFinal: document.getElementById("conv-final"),
  convFinalScores: document.getElementById("conv-final-scores"),
  convFeedback: document.getElementById("conv-feedback"),
  convRestart: document.getElementById("conv-restart"),
```

- [ ] **Step 4: Implementar la lógica de la conversación en `app.js`**

Añade este bloque cerca del final, antes de "--- arranque ---" (app.js:636):

```javascript
// --- conversacion ------------------------------------------------------------

let conversationId = null;

function showConvError(message) {
  els.convError.textContent = message;
  els.convError.classList.remove("hidden");
}

// Pinta un set de scores (mismo formato que la practica) en un contenedor dado.
function renderScoreCards(container, scores) {
  container.innerHTML = "";
  for (const [key, label] of Object.entries(SCORE_LABELS)) {
    const value = scores[key];
    if (value === null || value === undefined) continue;
    const card = document.createElement("div");
    card.className = `card ${scoreClass(value)}`;
    card.innerHTML = `<span class="value">${formatScore(value)}</span><span class="label">${label}</span>`;
    container.appendChild(card);
  }
}

// Muestra una pregunta nueva: la escribe y la habla.
function showQuestion(question) {
  els.convQuestion.textContent = question;
  els.convTurn.classList.add("hidden");
  speak(question);
}

async function startConversation() {
  els.convSetupError.classList.add("hidden");
  const systemPrompt = els.convPrompt.value.trim();
  const maxQuestions = Number(els.convQuestions.value);
  if (!systemPrompt) {
    els.convSetupError.textContent = "Escribe un escenario.";
    els.convSetupError.classList.remove("hidden");
    return;
  }

  els.convStart.disabled = true;
  let response;
  try {
    response = await fetch("/conversation/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ system_prompt: systemPrompt, max_questions: maxQuestions }),
    });
  } catch (err) {
    els.convStart.disabled = false;
    els.convSetupError.textContent = "No se pudo contactar al servidor: " + err.message;
    els.convSetupError.classList.remove("hidden");
    return;
  }
  els.convStart.disabled = false;

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    els.convSetupError.textContent =
      formatDetail(body.detail) || `El servidor respondio ${response.status}.`;
    els.convSetupError.classList.remove("hidden");
    return;
  }

  const data = await response.json();
  conversationId = data.conversation_id;
  els.convSetup.classList.add("hidden");
  els.convFinal.classList.add("hidden");
  els.convActive.classList.remove("hidden");
  showQuestion(data.question);
}

// Sink de grabacion para la conversacion: manda el audio de la respuesta al servidor.
async function sendConversationAnswer(wavBlob) {
  els.convError.classList.add("hidden");
  const form = new FormData();
  form.append("audio", wavBlob, "answer.wav");

  let response;
  try {
    response = await fetch(`/conversation/${conversationId}/answer`, {
      method: "POST",
      body: form,
    });
  } catch (err) {
    showConvError("No se pudo contactar al servidor: " + err.message);
    return;
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    showConvError(formatDetail(body.detail) || `El servidor respondio ${response.status}.`);
    return;
  }

  const data = await response.json();
  renderScoreCards(els.convTurnScores, data.turn_scores);
  els.convRecognized.textContent = data.recognized_text || "(vacio)";
  els.convTurn.classList.remove("hidden");

  if (data.final) {
    renderScoreCards(els.convFinalScores, data.final.scores);
    els.convFeedback.textContent = data.final.content_feedback;
    els.convActive.classList.add("hidden");
    els.convFinal.classList.remove("hidden");
    conversationId = null;
    loadWordBank();
  } else {
    showQuestion(data.next_question);
  }
}

// Al entrar/salir de la vista conversacion, se conecta/desconecta el sink de grabacion y
// se reusan los botones de grabar. La vista tiene su propio boton, que delega en el flujo
// comun de grabacion apuntando al sink de conversacion.
els.convStart.addEventListener("click", startConversation);
els.convListen.addEventListener("click", () => speak(els.convQuestion.textContent));
els.convRecord.addEventListener("click", () => {
  if (state === "idle") {
    recordSink = sendConversationAnswer;
    startRecording();
    els.convRecord.textContent = "Parar";
    els.convStatus.textContent = "Grabando... responde ahora.";
  } else if (state === "recording") {
    stopRecording();
    els.convRecord.textContent = "Responder";
    els.convStatus.textContent = "Evaluando...";
  }
});
els.convRestart.addEventListener("click", () => {
  els.convFinal.classList.add("hidden");
  els.convSetup.classList.remove("hidden");
});
```

- [ ] **Step 5: Resetear el sink al cambiar de vista**

En `switchView` (app.js:645-652), al final de la función añade:

```javascript
  // Fuera de la conversacion, la grabacion vuelve a su destino por defecto.
  if (name !== "conversation") recordSink = null;
```

- [ ] **Step 6: Estilos mínimos en `style.css`**

Añade al final de `style.css`:

```css
#conv-setup textarea,
#conv-setup input[type="number"] {
  width: 100%;
  box-sizing: border-box;
}

#conv-question {
  min-height: 1.5em;
}
```

- [ ] **Step 7: Verificación manual**

Requiere `AZURE_SPEECH_KEY` y `GEMINI_API_KEY` en `.env`.

Run: `uv run python main.py`
Luego abre `http://127.0.0.1:8000`, entra a la pestaña "Conversacion" y comprueba:
1. Escribes un escenario, pones 2 preguntas, "Empezar" → aparece y se escucha la primera pregunta.
2. "Responder" graba; al "Parar" se ve el mini-scoring del turno + "lo que Azure escucho" y suena la 2ª pregunta.
3. Tras responder la 2ª → aparece el resultado final (scores agregados + feedback) y el banco de palabras se refresca.
4. "Nueva conversacion" vuelve al formulario inicial.
5. La pestaña "Practicar" sigue funcionando igual que antes (grabar y evaluar un texto).

- [ ] **Step 8: Commit**

```bash
git add index.html app.js style.css
git commit -m "feat: vista de conversacion en el frontend"
```

---

## Notas y limitaciones (por diseño)

- El estado de las conversaciones en curso vive en memoria del proceso (`InMemorySaver`). Si el servidor se reinicia a mitad de una conversación, se pierde y el siguiente `answer` devuelve 404. Asumido: uvicorn de un solo worker en desarrollo.
- Solo se persiste el resultado final; no hay vista para reabrir conversaciones pasadas (YAGNI). `db.list_conversations` existe para verificación/uso futuro.
- TTS y grabación siguen siendo del navegador (gratis, ya existentes); no se usa Azure TTS.
