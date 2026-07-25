# Palabras para practicar (salida estructurada Pydantic) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que el turno final devuelva, además del feedback en prosa, una lista estructurada de palabras a practicar (word + pista de pronunciación), y que el frontend la muestre y permita escuchar cada palabra con el TTS del navegador.

**Architecture:** El nodo `finalize` del grafo usa `llm.with_structured_output(FeedbackReport)` (Gemini vía langchain_google_genai) para devolver un objeto Pydantic con `feedback` (prosa) y `words` (lista). `conversation.answer` expone `practice_words` en el `final`; el endpoint lo pasa a la respuesta. El frontend renderiza la lista bajo el feedback, cada palabra clickeable → `speak(word)`.

**Tech Stack:** LangGraph + Gemini, Pydantic, FastAPI, JavaScript vanilla + Web Speech (TTS), pytest.

## Global Constraints

- Python `>=3.11`. Variables de entorno SOLO en `config.py`.
- Sin persistencia de las palabras del LLM: `db.save_conversation(...)` NO cambia.
- Mensajes al usuario en español.
- TDD para el backend. Frontend sin arnés JS: `node --check app.js` + `uv run pytest` verde + walkthrough manual.
- Comandos: `uv run pytest` desde `review-ingles/`. `node` en `/opt/homebrew/bin/node`.
- La pista (`hint`) puede venir vacía; en ese caso el frontend muestra solo la palabra.

---

### Task 1: Esquema Pydantic + `finalize` estructurado (`conversation.py`)

**Files:**
- Modify: `conversation.py`
- Test: `test_conversation.py`

**Interfaces:**
- Produces:
  - `conversation.PracticeWord` (Pydantic): campos `word: str`, `hint: str`.
  - `conversation.FeedbackReport` (Pydantic): campos `feedback: str`, `words: list[PracticeWord]`.
  - `conversation.answer(...)` — el dict `final` gana la clave `practice_words: list[dict]` (cada dict `{"word": str, "hint": str}`).
- Consumes: cualquier `llm` con `.invoke(messages).content` y `.with_structured_output(schema).invoke(messages) -> schema`.

- [ ] **Step 1: Actualizar los dobles de LLM en los tests (rojo)**

En `test_conversation.py`, reemplaza las clases `FakeLLM`, `GeminiLikeLLM` y `BlockContentLLM` por estas (añaden `with_structured_output` y unifican el atributo `_replies`):

```python
class FakeLLM:
    """Doble del cliente Gemini: devuelve respuestas predefinidas en orden."""

    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        return AIMessage(self._replies.pop(0))

    def with_structured_output(self, schema):
        return _StructuredFake(self._replies, schema)


class GeminiLikeLLM(FakeLLM):
    """Como FakeLLM pero exige al menos un turno humano, igual que Gemini."""

    def invoke(self, messages):
        if not any(isinstance(m, HumanMessage) for m in messages):
            raise ValueError("contents are required.")
        return super().invoke(messages)


class BlockContentLLM:
    """Doble que devuelve contenido en bloques, como a veces hace Gemini."""

    def __init__(self, replies):
        self._replies = list(replies)

    def invoke(self, messages):
        text = self._replies.pop(0)
        return AIMessage([{"type": "text", "text": text, "extras": {"signature": "x"}}])

    def with_structured_output(self, schema):
        return _StructuredFake(self._replies, schema)


class _StructuredFake:
    """Doble de llm.with_structured_output: coerce el siguiente reply al schema.

    string  -> schema(feedback=<str>, words=[])   (compat con tests que pasan texto)
    dict    -> schema(**reply)
    schema  -> tal cual
    """

    def __init__(self, replies, schema):
        self._replies = replies
        self._schema = schema

    def invoke(self, messages):
        reply = self._replies.pop(0)
        if isinstance(reply, self._schema):
            return reply
        if isinstance(reply, dict):
            return self._schema(**reply)
        return self._schema(feedback=str(reply), words=[])
```

Luego, en `test_full_flow_reaches_feedback`, añade al final la aserción de que la lista viene vacía cuando el LLM devuelve texto plano:

```python
    assert "scores" not in r2["final"]
    assert r2["final"]["practice_words"] == []
```

Y añade un test nuevo del camino estructurado:

```python
def test_final_returns_structured_practice_words():
    report = conversation.FeedbackReport(
        feedback="Bien hecho.",
        words=[
            conversation.PracticeWord(word="worked", hint="-ed → /t/"),
            conversation.PracticeWord(word="enjoyed", hint="-ed → /d/"),
        ],
    )
    graph = conversation.build_graph(FakeLLM(["Q1", report]))
    conversation_id, _ = conversation.start("Roleplay", 1, graph=graph)
    result = conversation.answer(conversation_id, "hi", graph=graph)
    assert result["final"]["content_feedback"] == "Bien hecho."
    assert result["final"]["practice_words"] == [
        {"word": "worked", "hint": "-ed → /t/"},
        {"word": "enjoyed", "hint": "-ed → /d/"},
    ]
```

- [ ] **Step 2: Correr y ver que falla**

Run: `uv run pytest test_conversation.py -v`
Expected: FAIL — `AttributeError: module 'conversation' has no attribute 'FeedbackReport'` (y el test nuevo no colecta/ falla).

- [ ] **Step 3: Importar Pydantic y definir el esquema**

En `conversation.py`, añade el import (junto a los otros imports de arriba):

```python
from pydantic import BaseModel, Field
```

Y define el esquema justo después de la clase `ConversationError` (antes de `class State`):

```python
class PracticeWord(BaseModel):
    word: str = Field(
        description="English word the learner should practice (mispronounced or recommended)"
    )
    hint: str = Field(
        description="Short pronunciation hint, e.g. '-ed -> /t/'. Empty string if none."
    )


class FeedbackReport(BaseModel):
    feedback: str = Field(
        description="Brief feedback in Spanish, 4-6 sentences, on grammar, vocabulary and how to improve"
    )
    words: list[PracticeWord] = Field(
        default_factory=list,
        description="Up to 10 words to practice, each with a pronunciation hint",
    )
```

- [ ] **Step 4: Añadir `practice_words` al `State`**

En `conversation.py`, reemplaza la clase `State` por:

```python
class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    system_prompt: str
    max_questions: int
    questions_asked: int
    content_feedback: str
    practice_words: list[dict]
    finished: bool
```

- [ ] **Step 5: Inicializar `practice_words` en `start`**

En `start`, en el dict que se pasa a `graph.invoke`, añade la clave (después de `"content_feedback": ""`):

```python
            "content_feedback": "",
            "practice_words": [],
```

- [ ] **Step 6: Nuevo `_FEEDBACK_INSTRUCTION` y `finalize` estructurado**

En `conversation.py`, reemplaza `_FEEDBACK_INSTRUCTION` por:

```python
_FEEDBACK_INSTRUCTION = (
    "The practice is over. Produce a FeedbackReport. In 'feedback', write brief feedback in "
    "Spanish (4-6 sentences) on the learner's English across the whole conversation: grammar, "
    "vocabulary and how to improve. In 'words', list up to 10 English words the learner should "
    "practice (mispronounced or worth improving), each with a short pronunciation 'hint' "
    "(e.g. '-ed -> /t/'); use an empty string for 'hint' when there is no useful cue."
)
```

Y reemplaza la función `finalize` (dentro de `build_graph`) por:

```python
    def finalize(state: State) -> dict:
        report = llm.with_structured_output(FeedbackReport).invoke(
            state["messages"] + [HumanMessage(_FEEDBACK_INSTRUCTION)]
        )
        return {
            "finished": True,
            "content_feedback": report.feedback,
            "practice_words": [word.model_dump() for word in report.words],
        }
```

- [ ] **Step 7: Exponer `practice_words` en `answer`**

En `conversation.py`, en la función `answer`, reemplaza el bloque `if result["finished"]:` por:

```python
    if result["finished"]:
        return {
            "final": {
                "content_feedback": result["content_feedback"],
                "system_prompt": result["system_prompt"],
                "questions_asked": result["questions_asked"],
                "practice_words": result["practice_words"],
            }
        }
    return {"question": result["messages"][-1].content}
```

- [ ] **Step 8: Correr los tests**

Run: `uv run pytest test_conversation.py -v`
Expected: PASS todos (incluido `test_final_returns_structured_practice_words` y el flujo con fallback de string).

- [ ] **Step 9: Commit**

```bash
git add conversation.py test_conversation.py
git commit -m "feat: finalize devuelve palabras a practicar con salida estructurada Pydantic"
```

---

### Task 2: Pasar `practice_words` en el endpoint (`main.py`)

**Files:**
- Modify: `main.py`
- Test: `test_api.py`

**Interfaces:**
- Consumes: `conversation.answer(...)` cuyo `final` incluye `practice_words: list[dict]`.
- Produces (HTTP): la respuesta final del `POST /conversation/{id}/answer` gana `final.practice_words`.

- [ ] **Step 1: Actualizar el test final (rojo)**

En `test_api.py`, en `test_conversation_answer_final_aggregates_and_saves`, añade `practice_words` al `final_payload` y una aserción. El `final_payload` y las aserciones quedan así:

```python
    final_payload = {
        "final": {
            "content_feedback": "Buen intento.",
            "system_prompt": "Roleplay",
            "questions_asked": 1,
            "practice_words": [{"word": "worked", "hint": "-ed → /t/"}],
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
    # Las palabras a practicar viajan tal cual desde conversation.answer.
    assert body["final"]["practice_words"] == [{"word": "worked", "hint": "-ed → /t/"}]

    saved = db.list_conversations()
    assert len(saved) == 1
    assert saved[0]["system_prompt"] == "Roleplay"
    assert saved[0]["pronunciation_score"] == 85.0
    # Las palabras del scoring alimentaron el banco.
    assert [s["word"] for s in db.list_word_stats()] == ["hello"]
```

- [ ] **Step 2: Correr y ver que falla**

Run: `uv run pytest test_api.py -k final_aggregates -v`
Expected: FAIL con `KeyError: 'practice_words'` (la respuesta aún no incluye la clave).

- [ ] **Step 3: Añadir `practice_words` a la respuesta final**

En `main.py`, en `conversation_answer`, reemplaza la línea que arma `response["final"]` por:

```python
        response["final"] = {
            "scores": scores,
            "content_feedback": final["content_feedback"],
            "practice_words": final["practice_words"],
        }
```

(La llamada a `db.save_conversation(...)` no cambia: las palabras del LLM no se persisten.)

- [ ] **Step 4: Correr los tests de la API**

Run: `uv run pytest test_api.py -v`
Expected: PASS todos.

- [ ] **Step 5: Correr toda la suite**

Run: `uv run pytest -v`
Expected: PASS todo.

- [ ] **Step 6: Commit**

```bash
git add main.py test_api.py
git commit -m "feat: el endpoint expone practice_words en el resultado final"
```

---

### Task 3: Lista de palabras en el frontend (`index.html`, `app.js`, `style.css`)

**Files:**
- Modify: `index.html`
- Modify: `app.js`
- Modify: `style.css`

**Interfaces:**
- Consumes (HTTP): `data.final.practice_words: [{word, hint}]`.
- Reutiliza de `app.js`: `speak()` (ya fuerza `en-US`), `els`, `renderScoreCards`.

Sin arnés de tests JS. Verificación: `node --check app.js`, `uv run pytest` verde, walkthrough manual.

- [ ] **Step 1: Bloque de palabras en `index.html`**

En `index.html`, dentro de `#conv-final`, después de `<p id="conv-feedback" ...></p>` y antes del `div.controls`, añade:

```html
          <div id="conv-practice-words-block" class="hidden">
            <h2>Palabras para practicar</h2>
            <p class="hint">Haz clic en una palabra para escucharla.</p>
            <div id="conv-practice-words" class="practice-words"></div>
          </div>
```

- [ ] **Step 2: Registrar los elementos en `els`**

En el objeto `els` de `app.js`, junto a `convFeedback`, añade:

```javascript
  convPracticeWordsBlock: document.getElementById("conv-practice-words-block"),
  convPracticeWords: document.getElementById("conv-practice-words"),
```

- [ ] **Step 3: Función que renderiza las palabras**

En `app.js`, junto a `renderScoreCards` (en el bloque de conversación), añade:

```javascript
// Renderiza las palabras a practicar como chips clickeables; cada click las reproduce
// con el TTS del navegador (voz en-US). Oculta el bloque si no hay palabras.
function renderPracticeWords(words) {
  const list = words || [];
  els.convPracticeWords.innerHTML = "";
  els.convPracticeWordsBlock.classList.toggle("hidden", list.length === 0);
  for (const item of list) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "practice-word";
    chip.textContent = item.hint ? `${item.word}: ${item.hint}` : item.word;
    chip.title = "Escuchar";
    chip.addEventListener("click", () => speak(item.word));
    els.convPracticeWords.appendChild(chip);
  }
}
```

- [ ] **Step 4: Llamar al render en el resultado final**

En `app.js`, en `sendConversationAnswer`, dentro de la rama `if (data.final) {`, después de `els.convFeedback.textContent = data.final.content_feedback;`, añade:

```javascript
    renderPracticeWords(data.final.practice_words);
```

- [ ] **Step 5: Estilo de los chips en `style.css`**

Añade al final de `style.css`:

```css
.practice-words {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
  margin-top: 0.5rem;
}

.practice-word {
  cursor: pointer;
}
```

- [ ] **Step 6: Verificación automática**

Run: `/opt/homebrew/bin/node --check app.js`
Expected: sin errores de sintaxis.

Run: `uv run pytest`
Expected: verde (solo el warning preexistente de Starlette).

- [ ] **Step 7: Verificación de integración con Gemini (real)**

Con `GEMINI_API_KEY` en `.env`, corre un smoke test de que `with_structured_output` devuelve el schema poblado:

```bash
uv run python -c "
import conversation
from langchain_google_genai import ChatGoogleGenerativeAI
import config
llm = ChatGoogleGenerativeAI(model=config.GEMINI_MODEL, google_api_key=config.GEMINI_API_KEY)
from langchain_core.messages import HumanMessage
r = llm.with_structured_output(conversation.FeedbackReport).invoke([
    HumanMessage('The learner said: I work at 4 months and I finish my task. Give the FeedbackReport.')
])
print(type(r).__name__, '|', r.feedback[:60], '|', [(w.word, w.hint) for w in r.words])
"
```
Expected: imprime `FeedbackReport` con un `feedback` en español y una lista de `words` (word, hint). Si falla por cuota/red, reintentar; si el modelo no soporta structured output, detenerse y avisar (no seguir).

- [ ] **Step 8: Walkthrough manual**

Chrome con `AZURE_SPEECH_KEY` + `GEMINI_API_KEY`, server levantado (`uv run python main.py`):

1. Conversación corta hablando en inglés con errores de pasado (verbos sin `-ed`).
2. Al terminar, bajo el feedback aparece "Palabras para practicar" con `word: hint`.
3. Click en una palabra → se escucha en inglés.
4. Si la lista viene vacía, el bloque no aparece.
5. Pestañas Practicar y Banco de palabras intactas.

- [ ] **Step 9: Commit**

```bash
git add index.html app.js style.css
git commit -m "feat: lista de palabras para practicar escuchables en el resultado de la conversacion"
```

---

## Notas

- `practice_words` NO se persiste en la BD en esta versión (queda para una futura, junto con practicarlas por separado y medir progreso).
- El `hint` puede ser vacío: el chip muestra solo la palabra; el click siempre reproduce `word`.
- El aplanado de bloques (`_content_text`) sigue aplicando solo al nodo `ask` (preguntas); el feedback ya llega como string desde el schema.
