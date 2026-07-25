# Diseño: Modalidad de conversación con LangGraph + Gemini Flash

Fecha: 2026-07-24
Proyecto: `review-ingles`

## Objetivo

Agregar una nueva modalidad de práctica *conversacional* (role-play en inglés) al app
`review-ingles`. El usuario define un system prompt (ej. "hazme preguntas en inglés sobre
mi experiencia laboral en pasado"); un LLM (Gemini Flash, orquestado con LangGraph) conduce
una conversación de un número fijo de preguntas. Cada pregunta se muestra en texto y se
reproduce por audio (TTS del navegador). El usuario responde hablando en inglés; ese audio
se evalúa con Azure Pronunciation Assessment **sin texto de referencia**, y el texto
reconocido se usa como su respuesta para que el LLM continúe. Al final se muestra y se
guarda un scoring de pronunciación agregado más feedback de contenido del LLM.

Meta secundaria explícita: **evaluar la integración de LangGraph** como forma de conectar
modelos de IA en este proyecto.

## Decisiones tomadas (brainstorming)

- **Ubicación:** nueva vista dentro de `review-ingles`, reutilizando backend FastAPI,
  grabación de audio, Azure, `config.py` y la BD. No es un proyecto separado.
- **Fin de sesión:** número fijo de preguntas, configurable desde la UI al iniciar.
- **Scoring final incluye:** pronunciación agregada (Azure), alimentar el banco de palabras
  existente con las palabras de cada turno, y feedback de contenido (gramática/vocabulario)
  generado por Gemini.
- **Persistencia:** solo el resultado final. El turno-a-turno vive en memoria durante la
  sesión; al terminar se guarda un único registro con el scoring y el feedback.
- **TTS:** el del navegador (Web Speech API, `speak()`), gratis y ya implementado. No Azure TTS.
- **System prompt y nº de preguntas:** se configuran al inicio de cada conversación desde la UI.

## El punto técnico clave: Azure sin referencia

El flujo actual (`speech.assess`) evalúa pronunciación **contra un texto de referencia
conocido**. En la conversación no hay referencia: el usuario habla libremente y puede
equivocarse. Azure Pronunciation Assessment soporta un modo *unscripted*: se pasa
`reference_text=""` y `enable_miscue=False`. Azure reconoce lo dicho y devuelve
**accuracy, fluency y prosody**; no hay *completeness* (requiere referencia) ni
omisiones/inserciones (requieren miscue).

Consecuencias:

- El **texto reconocido** por Azure es a la vez la transcripción que se le pasa a Gemini.
  Una sola llamada a Azure da scoring + transcripción; no se necesita un STT aparte.
- Se agrega una función nueva `assess_unscripted(wav_path)` en `speech.py`. **No se modifica
  la `assess()` actual** (la práctica con referencia sigue igual).
- El overall de pronunciación sin referencia se calcula sobre 3 dimensiones
  (accuracy, fluency, prosody), sin completeness.

## Arquitectura

Archivos nuevos:

- `conversation.py` — construye el grafo de LangGraph y el cliente de Gemini. Único lugar
  que habla con LangGraph/Gemini (análogo a como `azure_speech.py` aísla Azure).

Archivos modificados:

- `speech.py` — nueva `assess_unscripted(wav_path)`.
- `config.py` — nuevas env `GEMINI_API_KEY`, `GEMINI_MODEL`.
- `db.py` — nueva tabla `conversations` + helpers (`save_conversation`, `list_conversations`).
- `main.py` — nuevos endpoints de conversación.
- `index.html`, `app.js`, `style.css` — nueva vista "Conversación".

### Grafo de LangGraph

Estado del grafo:

- `system_prompt: str`
- `messages: list` (historial de la conversación; mensajes system/human/ai)
- `questions_asked: int`
- `max_questions: int`
- `per_turn_scores: list[dict]` (accuracy/fluency/prosody por turno)

Nodos:

- **`ask`**: Gemini genera la siguiente pregunta a partir del system prompt + historial;
  incrementa `questions_asked`; añade el mensaje AI.
- **`decide`** (condicional): si `questions_asked >= max_questions` → `finalize`; si no,
  espera el siguiente turno del usuario (que llega por HTTP) y vuelve a `ask`.
- **`finalize`**: Gemini genera el feedback de contenido (gramática/vocabulario) sobre las
  respuestas del usuario.

Estado en memoria del servidor mediante un **checkpointer** de LangGraph (`MemorySaver`)
con `thread_id = conversation_id`. Vive durante la sesión del proceso; el turno-a-turno no
se persiste en BD.

El turno del usuario (audio → Azure → texto reconocido) ocurre **fuera del grafo**, en el
endpoint HTTP: el endpoint corre Azure, obtiene texto + scores, inyecta el texto reconocido
como mensaje humano en el grafo y guarda los scores del turno en `per_turn_scores`.

### Cliente Gemini

`ChatGoogleGenerativeAI` de `langchain-google-genai`, modelo desde `config.GEMINI_MODEL`
(default `gemini-2.5-flash`), API key desde `config.GEMINI_API_KEY`. Si falta la key, el
primer intento devuelve un error explicativo en español (mismo patrón que Azure).

## Endpoints

- `POST /conversation/start` — body `{system_prompt, max_questions}`. Valida entradas
  (prompt no vacío; `max_questions` en un rango razonable, ej. 1–20). Crea el thread, corre
  el grafo hasta la primera pregunta. Responde `{conversation_id, question}`.
- `POST /conversation/{id}/answer` — `multipart` con el audio WAV. Corre
  `assess_unscripted`, inyecta el texto reconocido al grafo. Si aún faltan preguntas:
  responde `{recognized_text, turn_scores, next_question}`. Si fue la última: corre
  `finalize`, agrega el scoring, alimenta el banco de palabras, guarda el registro final y
  responde `{recognized_text, turn_scores, final}` donde `final` trae el scoring agregado y
  el feedback de contenido.

Errores de Azure/Gemini se mapean a HTTPException con mensaje en español, igual que hoy.

## Datos

Tabla nueva `conversations`:

- `id` (PK), `created_at`
- `system_prompt`
- `questions_asked`
- `avg_accuracy`, `avg_fluency`, `avg_prosody`, `avg_pronunciation`
- `content_feedback` (texto de Gemini)

Las palabras reconocidas en cada turno se insertan en el banco de palabras existente
(mismo mecanismo que `save_attempt` usa hoy para el historial por palabra), para que la
conversación también alimente la práctica por palabra.

## UI (vista "Conversación")

- Formulario inicial: `textarea` para el system prompt + input numérico para nº de
  preguntas + botón "Empezar".
- Durante la charla: se muestra la pregunta en texto y se reproduce con `speak()` (TTS del
  navegador). Botón Grabar/Parar (reutiliza la grabación WAV 16 kHz mono actual) para
  responder. Tras cada respuesta: mini-scoring del turno + siguiente pregunta.
- Al final: scoring agregado de pronunciación + feedback de contenido de Gemini.

## Config y dependencias

- `config.py`: `GEMINI_API_KEY` (default `""`), `GEMINI_MODEL` (default `gemini-2.5-flash`).
  Único lugar donde se leen env, según la convención del proyecto.
- Dependencias nuevas: `langgraph`, `langchain-google-genai`.
- `.env.example` documenta las nuevas variables.

## Pruebas

- `assess_unscripted`: test con un doble de `AzureSpeechClient` (como los tests actuales de
  `speech`), verificando que arma scores sin referencia y sin completeness.
- Grafo de conversación: test con un LLM falso (fake/stub) que verifica el flujo ask →
  answer → ask → finalize y el conteo de preguntas.
- Endpoints: tests de API (como `test_api.py`) con Azure y Gemini mockeados, cubriendo
  start, answer intermedio y answer final.

## Fuera de alcance (YAGNI)

- Navegar/reabrir conversaciones pasadas (solo se guarda el resultado final).
- Azure TTS (se usa el del navegador).
- Que el LLM decida cuándo terminar (nº de preguntas fijo).
- Streaming de la respuesta del LLM.
