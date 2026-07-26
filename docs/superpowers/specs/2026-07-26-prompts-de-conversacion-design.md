# Prompts de conversación (generación con LLM + persistencia reutilizable) — Design

## Problema

Hoy, para iniciar una conversación hay que **escribir a mano el escenario (system prompt)**
cada vez, en un textarea libre dentro de la vista Conversación. El escenario no se guarda ni
se puede reutilizar: cada práctica arranca de cero. Además, redactar un buen escenario en
inglés desde una intención vaga ("quiero practicar una entrevista backend") es trabajo manual
repetitivo.

## Objetivo

1. **Generar el escenario con un LLM**: el usuario escribe (o dicta por voz) un **contexto**
   libre —intención + material que quiera pegar, p. ej. su CV— y con un botón el LLM lo expande
   a un **escenario en inglés** que después puede **editar a mano**.
2. **Guardar y reutilizar** esos escenarios como **prompts de conversación** con nombre,
   persistidos en la base de datos, para elegirlos en futuras conversaciones sin reescribirlos.

Espeja un patrón que el proyecto ya usa: **Textos** *gestiona* y **Practicar** solo *elige de
una lista*. Acá: una pantalla **Prompt de conversación** *genera/gestiona* los prompts, y la
pantalla **Conversación** solo los *elige y usa*.

## Alcance

- Backend: `db.py` (tabla + CRUD), `conversation.py` (generación con Gemini), `main.py`
  (endpoints).
- Frontend: `index.html`, `app.js`, `style.css`.
- Tests: `test_db.py`, `test_conversation.py`, `test_api.py`.
- **Sin variables de entorno nuevas**: reutiliza `GEMINI_API_KEY` / `GEMINI_MODEL` de
  `config.py`.

## No-objetivos (v1)

- No se persiste el turno-a-turno de la conversación (sigue guardándose solo el resultado final,
  como hoy).
- No se leen archivos ni carpetas: el contexto es texto que el usuario escribe o dicta.
- No se engancha la tabla `texts` como fuente de contenido.
- El prompt guarda **solo el escenario final** (nombre + texto); el contexto crudo (CV, etc.) es
  transitorio y se descarta tras generar.
- Sin `max_questions` por prompt (sigue siendo un campo aparte en Conversación, default 5), sin
  categorías ni búsqueda de prompts.
- En la vista **Conversación no se tipea/edita ad-hoc**: para usar un prompt hay que guardarlo
  primero (igual que hay que guardar un texto antes de practicarlo).

## Modelo de datos (`db.py`)

Tabla nueva, agregada al `SCHEMA` existente (idempotente vía `CREATE TABLE IF NOT EXISTS`; al
ser tabla nueva no requiere lógica de migración/drop):

```sql
CREATE TABLE IF NOT EXISTS conversation_prompts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    name          TEXT NOT NULL,
    system_prompt TEXT NOT NULL
);
```

CRUD calcado del de `texts`:

- `create_conversation_prompt(name, system_prompt) -> int`
- `get_conversation_prompt(prompt_id) -> dict | None`
- `list_conversation_prompts() -> list[dict]` (orden `id DESC`)
- `update_conversation_prompt(prompt_id, name, system_prompt) -> None`
- `delete_conversation_prompt(prompt_id) -> None`

`created_at`/`updated_at` en ISO UTC con `timespec="seconds"`, igual que `texts`.

## Generación del prompt (`conversation.py`)

Se respeta el invariante del proyecto: **`conversation.py` es el único módulo que habla con
Gemini**. La generación es una llamada LLM simple (sin grafo).

- **Refactor menor**: extraer `_get_llm()` perezoso que construye `ChatGoogleGenerativeAI` una
  sola vez (con el mismo chequeo de `GEMINI_API_KEY` que hoy hace `_get_graph`). `_get_graph`
  pasa a usar `_get_llm()`, de modo que grafo y generador comparten cliente.

- **`generate_system_prompt(context: str, llm=None) -> str`**:
  - valida `context` no vacío (si vacío → `ConversationError(status=400)`);
  - invoca el LLM con `_GENERATE_INSTRUCTION + context`;
  - aplana la respuesta con el `_content_text` que ya existe (Gemini puede devolver bloques);
  - devuelve el escenario como string plano;
  - `llm=` inyectable para tests (mismo estilo que `graph=` en `start`/`answer`).

- **`_GENERATE_INSTRUCTION`** (en inglés, texto plano — no salida estructurada): instruye al LLM
  a convertir el contexto del alumno en un **escenario** conciso (2-5 frases) que describa sobre
  qué debe preguntar y evaluar el compañero de práctica, dirigido en segunda persona a ese
  compañero, en inglés, **devolviendo solo el escenario, sin preámbulo**. El escenario generado
  es exactamente lo que hoy va en el campo "escenario": al iniciar la conversación se sigue
  envolviendo con `_ASK_INSTRUCTION`. No se toca el flujo de la conversación.

## Endpoints (`main.py`)

Agrupados bajo el namespace `/conversation` que ya existe (junto a `/conversation/start` y
`/conversation/{id}/answer`). Validación en español, estilo `_clean_text`.

- `POST /conversation/prompt/generate` — body `{ "context": str }` → `{ "system_prompt": str }`.
  Valida `context` no vacío (400). Llama `conversation.generate_system_prompt`; mapea
  `ConversationError` a `HTTPException(error.status, str(error))`.
- `GET /conversation/prompts` → lista de prompts (`db.list_conversation_prompts`).
- `POST /conversation/prompts` — body `{ "name": str, "system_prompt": str }` → prompt creado.
  Valida ambos no vacíos (400).
- `PUT /conversation/prompts/{prompt_id}` — actualiza; 404 si no existe; valida ambos no vacíos.
- `DELETE /conversation/prompts/{prompt_id}` — borra; 404 si no existe; `{ "ok": true }`.

Modelos Pydantic: `ConversationPromptGenerateIn { context }`, `ConversationPromptIn
{ name, system_prompt }`.

`POST /conversation/start` **no cambia** su contrato: sigue recibiendo `system_prompt` +
`max_questions`. El frontend le pasa el `system_prompt` del prompt elegido.

## Frontend

### Nueva pantalla "Prompt de conversación"

Nuevo botón en el menú (`data-view="conv-prompts"`, junto a "Textos") y una `section
#view-conv-prompts`. Contiene:

- **Cuadro de contexto/intención**: `textarea #cp-context` + botón `🎤 Dictar`
  (`#cp-dictate`) + botón `✨ Generar` (`#cp-generate`).
- **Escenario editable**: `textarea #cp-prompt` (se rellena con lo que devuelve Generar, editable
  a mano).
- **Nombre** (`input #cp-name`) + botón `Guardar` (`#cp-save`). Guardar hace POST (prompt nuevo)
  o PUT (si hay uno en edición); un `hidden #cp-id` lleva el id en edición.
- **Tabla de prompts guardados** (`#conv-prompts tbody`) con columnas Nombre / (preview del
  escenario, truncado) / acciones **Editar** / **Borrar**, igual que la tabla de Textos.

Dictado: reutiliza `SpeechRecognition` del navegador (Web Speech API, gratis, sin backend) —el
mismo mecanismo que ya usa el modo "browser" de la conversación—. Un botón toggle que arranca/
para el reconocimiento y **agrega** las transcripciones finales a `#cp-context`. Si el navegador
no soporta `SpeechRecognition` (Firefox), el botón se desactiva y el usuario tipea (mismo
tratamiento que ya se hace con la fuente de transcripción).

### Pantalla "Conversación" (se simplifica)

- Se **reemplaza** el `textarea #conv-prompt` por un **selector** `select #conv-prompt-select`
  poblado con los prompts guardados (`GET /conversation/prompts`).
- Si no hay prompts, se muestra un aviso `#conv-no-prompts` *"No tienes prompts. Créalos en la
  pestaña Prompt de conversación"* con un enlace que hace `switchView("conv-prompts")` —idéntico
  al patrón de `#no-texts` en Practicar—, y se deshabilita `Empezar`.
- `Nº de preguntas` y `Fuente de transcripción` quedan igual.
- `startConversation()` toma el `system_prompt` del prompt seleccionado (de los datos ya
  cargados) y lo manda a `POST /conversation/start` tal como hoy. El resto del flujo (preguntas
  por voz, scoring por turno, feedback final) queda intacto.

### `app.js`

- Registrar los nuevos `els.*`.
- `loadConversationPrompts()`: `GET /conversation/prompts`, guarda en un `conversationPromptsData`
  (para reusar sin re-pedir), puebla la tabla de la pantalla de prompts y el `select` de
  Conversación (conservando la selección si sigue existiendo, como hace `renderTextSelect`).
  Se llama al arranque y tras cada create/update/delete.
- Dictado: `startPromptDictation()` / `stopPromptDictation()` reusando el patrón de
  `startBrowserRecognition` (append a `#cp-context`).
- `generateConversationPrompt()`: `POST /conversation/prompt/generate` con `{context}`, deshabilita
  el botón mientras corre, rellena `#cp-prompt`, y enruta errores a un `#cp-error`.
- Handlers de guardar (POST/PUT), editar (precarga el form desde una fila), borrar (con `confirm`,
  como `deleteText`).

### `style.css`

Reutiliza estilos existentes (`.view`, `.text-form`, tablas, `.controls`, `.hint`, `.error`).
Ajustes mínimos si hacen falta para el cuadro de contexto y el botón de dictado.

## Testing

TDD para el backend.

- `test_db.py`: CRUD de `conversation_prompts` (create → get/list → update → delete),
  incluyendo `list` vacío y orden `id DESC`.
- `test_conversation.py`:
  - `generate_system_prompt("Practicar entrevista backend", llm=FakeLLM(["<escenario>"]))`
    devuelve el escenario;
  - contexto vacío → `ConversationError(status=400)` sin invocar el LLM;
  - aplanado de bloques: con un doble estilo `BlockContentLLM`, el resultado sale como string
    plano.
    (`FakeLLM` ya expone `.invoke`; alcanza para esta función que no usa grafo.)
- `test_api.py`:
  - CRUD `/conversation/prompts`: crear y listar, actualizar (`PUT`), borrar (`DELETE`),
    validaciones (nombre/prompt vacío → 400; id inexistente en PUT/DELETE → 404);
  - `/conversation/prompt/generate` con `conversation.generate_system_prompt` monkeypatcheado
    → 200 y `{system_prompt}`; contexto vacío → 400.

Sin arnés de tests JS: `node --check app.js`, `uv run pytest` verde, y walkthrough manual.

## Verificación manual (walkthrough)

Chrome con `GEMINI_API_KEY` (y `AZURE_SPEECH_KEY` para el modo azure):

1. **Pantalla Prompt de conversación**: escribir un contexto ("Practicar entrevista para backend,
   evalúa vocabulario técnico") y/o **dictarlo por voz** → 🔊 el texto aparece en el cuadro.
2. `✨ Generar` → aparece un escenario en inglés en el textarea editable; editarlo a mano.
3. Poner un nombre → `Guardar` → aparece en la tabla de prompts.
4. Editar y Borrar desde la tabla funcionan.
5. **Pantalla Conversación**: el selector muestra el prompt guardado; con la base vacía se ve el
   aviso "No tienes prompts…" y `Empezar` deshabilitado.
6. Elegir el prompt + Nº de preguntas + Fuente → `Empezar` → la conversación arranca con ese
   escenario y el flujo de voz/scoring/feedback funciona igual que hoy.
7. Las pestañas Practicar, Textos, Banco de palabras e Historial siguen intactas.
