# Palabras para practicar (salida estructurada del LLM) — Design

## Problema

Al terminar la conversación, el feedback del LLM llega como un único párrafo de texto que
mezcla el resumen general, una lista de pronunciación (`Worked: /t/`) y correcciones de
expresión. La lista de palabras a practicar queda embebida en prosa: no se puede renderizar
aparte ni reutilizar (escucharlas, guardarlas, medir progreso más adelante).

## Objetivo

Que el turno final devuelva, **además del feedback en prosa**, una **lista estructurada de
palabras a practicar** (las mal pronunciadas o recomendadas), cada una con una pista corta de
pronunciación. El frontend muestra esa lista aparte y permite **escuchar cada palabra** con el
TTS del navegador.

Esta versión solo muestra y reproduce las palabras. La persistencia (guardarlas, practicarlas
por separado, medir mejora) queda para una versión futura y NO entra acá.

## Alcance

- Backend: `conversation.py` (esquema + nodo `finalize` + `State` + `answer`), `main.py`
  (respuesta del endpoint).
- Frontend: `index.html`, `app.js`, `style.css`.
- Tests: `test_conversation.py`, `test_api.py`.
- **Sin persistencia**: `db.save_conversation` no cambia; las palabras del LLM no se guardan.

## Forma del dato

Cada palabra:

```json
{ "word": "worked", "hint": "-ed → /t/" }
```

- `word`: palabra en inglés a practicar (mal pronunciada o recomendada).
- `hint`: pista corta de pronunciación (p. ej. `-ed → /t/`, `/tæsk/`). Puede quedar vacía si
  el LLM no tiene una pista específica.

## Enfoque: salida estructurada con Pydantic

Se usa `llm.with_structured_output(FeedbackReport)` (soportado por `langchain_google_genai`
para Gemini), **solo en el nodo `finalize`**. El nodo `ask` sigue devolviendo texto plano para
las preguntas (con el aplanado de bloques `_content_text` que ya existe).

Esquema (en `conversation.py`):

```python
from pydantic import BaseModel, Field

class PracticeWord(BaseModel):
    word: str = Field(description="English word the learner should practice (mispronounced or recommended)")
    hint: str = Field(description="Short pronunciation hint, e.g. '-ed → /t/'. Empty string if none.")

class FeedbackReport(BaseModel):
    feedback: str = Field(description="Brief feedback in Spanish, 4-6 sentences, on grammar/vocabulary/how to improve")
    words: list[PracticeWord] = Field(description="Up to 10 words to practice, each with a hint")
```

`finalize`:

```python
def finalize(state: State) -> dict:
    report = llm.with_structured_output(FeedbackReport).invoke(
        state["messages"] + [HumanMessage(_FEEDBACK_INSTRUCTION)]
    )
    return {
        "finished": True,
        "content_feedback": report.feedback,
        "practice_words": [w.model_dump() for w in report.words],
    }
```

El nuevo `_FEEDBACK_INSTRUCTION` pide: feedback breve en español (4-6 frases) sobre gramática,
vocabulario y cómo mejorar, y una lista de hasta 10 palabras a practicar (mal pronunciadas o
recomendadas), cada una con una pista corta de pronunciación (vacía si no aplica).

### Alternativas descartadas

- **Una llamada que devuelve JSON como texto + parseo defensivo**: evita cambiar la interfaz
  del `llm`, pero es menos type-safe; el usuario pidió Pydantic.
- **Dos llamadas (prosa + extracción)**: duplica latencia/costo en el turno final.

## Contrato del backend

- `State` gana `practice_words: list[dict]`. En `start` se inicializa a `[]`.
- `conversation.answer` — el dict `final` gana `practice_words`:
  ```python
  return {"final": {
      "content_feedback": result["content_feedback"],
      "system_prompt": result["system_prompt"],
      "questions_asked": result["questions_asked"],
      "practice_words": result["practice_words"],
  }}
  ```
- `main.py` — la respuesta final del endpoint pasa `practice_words` tal cual:
  ```python
  response["final"] = {
      "scores": scores,
      "content_feedback": final["content_feedback"],
      "practice_words": final["practice_words"],
  }
  ```
  `db.save_conversation(...)` no cambia (no se persisten estas palabras).

## Test doubles

`FakeLLM` (en `test_conversation.py`) gana `with_structured_output(schema)`, que devuelve un
wrapper cuyo `.invoke(messages)` toma el siguiente reply y lo coerciona al schema:

- si el reply ya es una instancia del schema → se devuelve tal cual;
- si es un `dict` → `schema(**reply)`;
- si es un `str` → `schema(feedback=reply, words=[])`.

Así los tests actuales que pasan `"FEEDBACK"` (string) siguen verdes (feedback = "FEEDBACK",
`practice_words == []`), y los tests nuevos pasan un `FeedbackReport`/dict con palabras.

`GeminiLikeLLM` hereda el comportamiento. `BlockContentLLM` (que prueba el aplanado de bloques)
se mantiene para el nodo `ask`; su reply de feedback ya no necesita bloques porque el feedback
viene estructurado — se ajusta ese test para que el aplanado se verifique solo en la pregunta.

## Frontend

- `index.html`: dentro de `#conv-final`, después del `#conv-feedback`, un bloque nuevo:
  un encabezado "Palabras para practicar" y un contenedor `#conv-practice-words`.
- `app.js`:
  - registrar `els.convPracticeWords` (y el encabezado si se oculta cuando la lista está vacía).
  - en `sendConversationAnswer`, rama `data.final`, renderizar la lista: por cada
    `{word, hint}`, un elemento clickeable que muestra `word` y, si hay `hint`, `: hint`; al
    hacer click llama `speak(word)` (que ya fuerza `en-US`).
  - si `practice_words` está vacío, ocultar el bloque.
- `style.css`: estilo de la lista como chips/botones clickeables.

## Testing

TDD para el backend:

- `test_conversation.py`:
  - `finalize` con un `FeedbackReport` de dos palabras → `answer(...)["final"]["practice_words"]`
    tiene esas dos palabras (word+hint).
  - fallback: reply string `"FEEDBACK"` → `content_feedback == "FEEDBACK"` y
    `practice_words == []` (los tests existentes cubren esto).
- `test_api.py`:
  - la respuesta final del endpoint incluye `practice_words` (pass-through desde el `final`
    mockeado de `conversation.answer`).

Sin arnés de tests JS: `node --check app.js`, `uv run pytest` verde, y walkthrough manual.

## Verificación de integración (Gemini)

Como `with_structured_output` es una integración real con Gemini, el plan incluye un chequeo
(además de los tests con dobles) de que `ChatGoogleGenerativeAI(...).with_structured_output(FeedbackReport)`
existe y de que una llamada real devuelve una instancia de `FeedbackReport` con `words`
poblado — a correr manualmente con `GEMINI_API_KEY` en el walkthrough.

## Verificación manual (walkthrough)

Chrome con `AZURE_SPEECH_KEY` + `GEMINI_API_KEY`:

1. Iniciar y completar una conversación corta hablando en inglés con algún error de
   pronunciación evidente (p. ej. verbos en pasado sin `-ed`).
2. Al terminar, bajo el feedback aparece "Palabras para practicar" con la lista `word: hint`.
3. Click en una palabra → se escucha en inglés (voz del navegador).
4. Si la lista viene vacía, el bloque no se muestra.
5. Las pestañas Practicar y Banco de palabras siguen intactas.
