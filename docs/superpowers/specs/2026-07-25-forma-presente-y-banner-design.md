# Forma en presente + banner de audio en "Palabras para practicar" — Design

## Problema

En la lista de "Palabras para practicar" del resultado de la conversación:

1. Cada palabra viene sola (a menudo un verbo en pasado, ej. `worked`). Falta la forma en
   presente (`work`) para comparar cómo se pronuncia cada una y notar la diferencia.
2. No hay una señal visual clara de que las palabras se pueden clickear para escucharlas
   (solo un `hint` de texto plano que pasa desapercibido).

## Objetivo

- Que cada palabra a practicar incluya, **cuando aplica** (verbos, sobre todo en pasado), su
  forma en presente/base, y que ambas formas se puedan **escuchar por separado** para
  comparar la pronunciación.
- Un **banner** visible arriba de la lista que indique que las palabras suenan al clickearlas.

## Alcance

- Backend: `conversation.py` (campo nuevo en `PracticeWord` + instrucción del LLM).
- Frontend: `index.html`, `app.js`, `style.css`.
- Tests: `test_conversation.py`.
- Endpoint (`main.py`): **sin cambios** — ya pasa `practice_words` tal cual; el campo nuevo
  viaja dentro de cada dict.
- Sin persistencia (igual que la versión anterior).

## Forma del dato

`PracticeWord` gana `present`:

```json
{ "word": "worked", "present": "work", "hint": "-ed → /t/" }
```

- `word`: palabra a practicar (a menudo pasado).
- `present`: forma en presente/base **solo cuando aplica** (verbos). String vacío para
  sustantivos u otras palabras donde no tiene sentido (ej. `task`, `months`, `for`).
- `hint`: pista corta de pronunciación (puede ser vacía).

## Backend (`conversation.py`)

`PracticeWord` pasa a:

```python
class PracticeWord(BaseModel):
    word: str = Field(
        description="English word the learner should practice (mispronounced or recommended)"
    )
    present: str = Field(
        default="",
        description="Present/base form of the word when it is a verb (esp. a past-tense verb), e.g. 'work' for 'worked'. Empty string when it does not apply (nouns, etc.).",
    )
    hint: str = Field(
        description="Short pronunciation hint, e.g. '-ed -> /t/'. Empty string if none."
    )
```

El `_FEEDBACK_INSTRUCTION` agrega la indicación de `present`: para cada palabra, si es un
verbo (especialmente en pasado), incluir su forma en presente en `present`; usar string vacío
cuando no aplique.

`FeedbackReport`, `finalize` (`word.model_dump()`), `State`, `answer` y el endpoint no
cambian su forma: el nuevo campo aparece dentro de cada dict de `practice_words`
automáticamente.

## Frontend

### Banner (index.html + style.css)

Dentro de `#conv-practice-words-block`, reemplazar el `<p class="hint">...</p>` actual por un
banner con estilo (callout) que indique que las palabras suenan:

```html
          <div id="conv-practice-words-block" class="hidden">
            <h2>Palabras para practicar</h2>
            <div class="audio-banner">🔊 Haz clic en cualquier palabra para escuchar su pronunciación.</div>
            <div id="conv-practice-words" class="practice-words"></div>
          </div>
```

`style.css`: `.audio-banner` como callout (fondo suave, padding, borde redondeado).

### Render (app.js)

`renderPracticeWords(words)` cambia para renderizar, por cada ítem:

- Un contenedor de fila (`.practice-word`).
- Si `item.present` no está vacío: un botón para `present`, un separador `→`, y un botón para
  `word`. Cada botón reproduce **su** forma: `speak(item.present)` / `speak(item.word)`.
- Si `item.present` está vacío: solo un botón para `word` → `speak(item.word)`.
- Si `item.hint` no está vacío: un texto con la pista al lado.

Cada forma clickeable es un `<button>` (rol claro de "clickeable"); el banner de arriba
comunica que suenan. El bloque se oculta si la lista viene vacía (sin cambios).

## Tests (`test_conversation.py`)

- Actualizar `test_final_returns_structured_practice_words` para incluir `present` y verificar
  que viaja en `practice_words`:
  ```python
  words=[
      conversation.PracticeWord(word="worked", present="work", hint="-ed → /t/"),
      conversation.PracticeWord(word="task", hint="/tæsk/"),  # sin present
  ]
  ...
  assert result["final"]["practice_words"] == [
      {"word": "worked", "present": "work", "hint": "-ed → /t/"},
      {"word": "task", "present": "", "hint": "/tæsk/"},
  ]
  ```
- Los demás tests siguen verdes: `present` tiene default `""`, y el fallback de string
  (`FeedbackReport(feedback=<str>, words=[])`) no cambia.

Frontend sin arnés JS: `node --check app.js`, `uv run pytest` verde, walkthrough manual.

## Verificación manual

Chrome con `AZURE_SPEECH_KEY` + `GEMINI_API_KEY`:

1. Conversación corta con verbos en pasado mal pronunciados.
2. En el resultado, arriba de las palabras se ve el banner de audio.
3. Los verbos muestran `presente → pasado`; clickear cada forma reproduce **esa** forma
   (comparás `work` vs `worked`).
4. Palabras que no son verbos aparecen solas (sin flecha ni forma presente).
5. Lista vacía → el bloque no aparece.

## Alternativas descartadas

- **Ícono 🔊 por palabra** en vez del banner: el usuario prefirió un banner arriba.
- **Forzar `present` siempre**: para sustantivos no tiene sentido y el LLM inventaría; se deja
  vacío cuando no aplica.
