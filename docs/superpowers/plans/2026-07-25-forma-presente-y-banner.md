# Forma en presente + banner de audio — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que cada palabra a practicar incluya (cuando aplica) su forma en presente, con ambas formas escuchables por separado, y que un banner arriba de la lista indique que las palabras suenan al clickearlas.

**Architecture:** `PracticeWord` (Pydantic) gana un campo `present` opcional; el LLM lo llena solo para verbos. El campo viaja dentro de cada dict de `practice_words` sin tocar `finalize`/`answer`/endpoint. El frontend renderiza cada ítem como `presente → pasado` (o solo la palabra), cada forma un botón que reproduce esa forma con `speak()`, más un banner de audio.

**Tech Stack:** LangGraph + Gemini, Pydantic, FastAPI, JavaScript vanilla + Web Speech (TTS), pytest.

## Global Constraints

- Python `>=3.11`. Variables de entorno SOLO en `config.py`.
- Sin persistencia de las palabras del LLM (`db.save_conversation` no cambia).
- Endpoint (`main.py`) SIN cambios: `practice_words` ya viaja tal cual.
- Mensajes al usuario en español.
- TDD para el backend. Frontend sin arnés JS: `node --check app.js` + `uv run pytest` verde + walkthrough manual.
- Comandos: `uv run pytest` desde `review-ingles/`. `node` en `/opt/homebrew/bin/node`.
- `present` vacío cuando no aplica (sustantivos, etc.); el frontend muestra solo la palabra.

---

### Task 1: Campo `present` en `PracticeWord` (`conversation.py`)

**Files:**
- Modify: `conversation.py`
- Test: `test_conversation.py`

**Interfaces:**
- Produces (cambia): `conversation.PracticeWord` gana `present: str` (default `""`). Los dicts de `practice_words` pasan a `{"word": str, "present": str, "hint": str}`.

- [ ] **Step 1: Actualizar el test estructurado (rojo)**

En `test_conversation.py`, reemplaza `test_final_returns_structured_practice_words` por:

```python
def test_final_returns_structured_practice_words():
    report = conversation.FeedbackReport(
        feedback="Bien hecho.",
        words=[
            conversation.PracticeWord(word="worked", present="work", hint="-ed → /t/"),
            conversation.PracticeWord(word="task", hint="/tæsk/"),  # sin present
        ],
    )
    graph = conversation.build_graph(FakeLLM(["Q1", report]))
    conversation_id, _ = conversation.start("Roleplay", 1, graph=graph)
    result = conversation.answer(conversation_id, "hi", graph=graph)
    assert result["final"]["content_feedback"] == "Bien hecho."
    assert result["final"]["practice_words"] == [
        {"word": "worked", "present": "work", "hint": "-ed → /t/"},
        {"word": "task", "present": "", "hint": "/tæsk/"},
    ]
```

- [ ] **Step 2: Correr y ver que falla**

Run: `uv run pytest test_conversation.py::test_final_returns_structured_practice_words -v`
Expected: FAIL — el dict resultante no tiene la clave `present` (o `PracticeWord` no acepta `present`).

- [ ] **Step 3: Añadir `present` a `PracticeWord`**

En `conversation.py`, reemplaza la clase `PracticeWord` por:

```python
class PracticeWord(BaseModel):
    word: str = Field(
        description="English word the learner should practice (mispronounced or recommended)"
    )
    present: str = Field(
        default="",
        description="Present/base form when the word is a verb (esp. past tense), e.g. 'work' for 'worked'. Empty string when it does not apply (nouns, etc.).",
    )
    hint: str = Field(
        description="Short pronunciation hint, e.g. '-ed -> /t/'. Empty string if none."
    )
```

- [ ] **Step 4: Pedir la forma en presente en el prompt**

En `conversation.py`, reemplaza `_FEEDBACK_INSTRUCTION` por:

```python
_FEEDBACK_INSTRUCTION = (
    "The practice is over. Produce a FeedbackReport. In 'feedback', write brief feedback in "
    "Spanish (4-6 sentences) on the learner's English across the whole conversation: grammar, "
    "vocabulary and how to improve. In 'words', list up to 10 English words the learner should "
    "practice (mispronounced or worth improving). For each word: 'hint' is a short pronunciation "
    "cue (e.g. '-ed -> /t/'), empty string if none; 'present' is the present/base form when the "
    "word is a verb (especially a past-tense verb, e.g. 'work' for 'worked'), empty string when "
    "it does not apply (nouns, etc.)."
)
```

- [ ] **Step 5: Correr los tests**

Run: `uv run pytest test_conversation.py -v`
Expected: PASS todos (el test nuevo y los previos; `present` tiene default `""`).

- [ ] **Step 6: Correr toda la suite**

Run: `uv run pytest`
Expected: PASS todo (solo warning de Starlette).

- [ ] **Step 7: Commit**

```bash
git add conversation.py test_conversation.py
git commit -m "feat: PracticeWord incluye la forma en presente del verbo"
```

---

### Task 2: Banner de audio + formas presente/pasado en el frontend

**Files:**
- Modify: `index.html`
- Modify: `app.js`
- Modify: `style.css`

**Interfaces:**
- Consumes (HTTP): `data.final.practice_words: [{word, present, hint}]`.
- Reutiliza de `app.js`: `speak()` (fuerza `en-US`), `els.convPracticeWords`, `els.convPracticeWordsBlock`.

Sin arnés de tests JS. Verificación: `node --check app.js`, `uv run pytest` verde, walkthrough manual.

- [ ] **Step 1: Banner en `index.html`**

En `index.html`, dentro de `#conv-practice-words-block`, reemplaza el `<p class="hint">...</p>` por el banner:

```html
          <div id="conv-practice-words-block" class="hidden">
            <h2>Palabras para practicar</h2>
            <div class="audio-banner">🔊 Haz clic en cualquier palabra para escuchar su pronunciación.</div>
            <div id="conv-practice-words" class="practice-words"></div>
          </div>
```

- [ ] **Step 2: Reescribir `renderPracticeWords` + helper de botón**

En `app.js`, reemplaza la función `renderPracticeWords` completa por:

```javascript
// Un boton que reproduce una forma de la palabra con el TTS del navegador (voz en-US).
function makeWordButton(text) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "word-audio";
  button.textContent = text;
  button.title = "Escuchar";
  button.addEventListener("click", () => speak(text));
  return button;
}

// Renderiza las palabras a practicar. Cada verbo muestra "presente -> pasado" con ambas
// formas escuchables por separado; las no-verbos van solas. Oculta el bloque si no hay nada.
function renderPracticeWords(words) {
  const list = words || [];
  els.convPracticeWords.innerHTML = "";
  els.convPracticeWordsBlock.classList.toggle("hidden", list.length === 0);
  for (const item of list) {
    const row = document.createElement("div");
    row.className = "practice-word";

    if (item.present) {
      row.appendChild(makeWordButton(item.present));
      const arrow = document.createElement("span");
      arrow.className = "practice-arrow";
      arrow.textContent = "→";
      row.appendChild(arrow);
    }
    row.appendChild(makeWordButton(item.word));

    if (item.hint) {
      const hint = document.createElement("span");
      hint.className = "practice-hint";
      hint.textContent = item.hint;
      row.appendChild(hint);
    }
    els.convPracticeWords.appendChild(row);
  }
}
```

(La llamada `renderPracticeWords(data.final.practice_words);` dentro de `sendConversationAnswer` no cambia.)

- [ ] **Step 3: Estilos en `style.css`**

En `style.css`, reemplaza el bloque actual de `.practice-words` / `.practice-word` por:

```css
.practice-words {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  margin-top: 0.5rem;
}

.practice-word {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.word-audio {
  padding: 0.2rem 0.6rem;
  background: #fff;
  color: #1d4ed8;
  border: 1px solid var(--border);
  border-radius: 6px;
}

.word-audio:hover {
  background: #eff6ff;
}

.practice-arrow {
  opacity: 0.6;
}

.practice-hint {
  opacity: 0.8;
  font-style: italic;
}

.audio-banner {
  margin: 0.5rem 0;
  padding: 0.5rem 0.75rem;
  border-radius: 6px;
  background: rgba(37, 99, 235, 0.1);
  border: 1px solid rgba(37, 99, 235, 0.3);
}
```

- [ ] **Step 4: Verificación automática**

Run: `/opt/homebrew/bin/node --check app.js`
Expected: sin errores de sintaxis.

Run: `uv run pytest`
Expected: verde (solo warning de Starlette).

- [ ] **Step 5: Walkthrough manual**

Chrome con `AZURE_SPEECH_KEY` + `GEMINI_API_KEY`, server levantado:

1. Conversación corta con verbos en pasado mal pronunciados.
2. En el resultado, arriba de las palabras se ve el banner de audio.
3. Los verbos muestran `presente → pasado`; clickear cada forma reproduce **esa** forma
   (comparás `work` vs `worked`).
4. Palabras que no son verbos aparecen solas (sin flecha ni forma presente).
5. Lista vacía → el bloque no aparece.

- [ ] **Step 6: Commit**

```bash
git add index.html app.js style.css
git commit -m "feat: banner de audio y formas presente/pasado escuchables en palabras para practicar"
```

---

## Notas

- El endpoint no cambia: el campo `present` viaja dentro de cada dict de `practice_words`.
- `speak()` ya fuerza `en-US`, así que ambas formas suenan en inglés sin cambios.
- Sin persistencia (queda para una versión futura).
