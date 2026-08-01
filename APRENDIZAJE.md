# Roadmap de aprendizaje — LangChain / LangGraph / LangSmith

Temas para aprender **aplicándolos a este proyecto** (`review-ingles`), pensados para una
posición de trabajo con LangGraph. Cada punto es autocontenido: se puede abordar en un chat
nuevo. Marca el checkbox cuando lo termines.

> Cómo usar este archivo: en un chat nuevo, pega el punto que quieras hacer y di
> "trabajemos este punto del roadmap". El chat tiene el contexto del proyecto abajo.

---

## Contexto del proyecto (para orientar un chat nuevo)

App de práctica de inglés hablado. Dos partes:

- **Legacy (lo que corre hoy)**: `main.py` (FastAPI) + `conversation.py` (grafo) + `db.py`
  (SQLite) + `scoring.py` + `speech.py` (Azure). Es lo que está en producción.
- **Migración en curso (`app/`)**: módulo nuevo y más limpio. Estructura:
  - `app/conversation/graph.py` — grafo LangGraph: nodos `ask`/`finalize`, `State`,
    `FeedbackReport` (feedback Markdown libre + `words` + `phrases`), `initial_state`.
  - `app/conversation/service.py` — `ConversationService` (inyección de dependencias),
    `build_llm`, `build_service`.
  - `app/conversation/synthesizer.py` — sintetiza el brief del alumno (formato fijo
    `### Puntos` + `### Contexto`).
  - `app/conversation/schemas.py` — validación de entrada con Pydantic (sin `if`s).
  - `app/conversation/repository.py` + `model.py` — CRUD de `conversation_configs` (SQLite).
  - `app/storage.py` — `SqliteStorage` (conexiones inyectadas).
  - `app/cmd/server.py` — servidor nuevo (aún NO es el entrypoint real).
  - `config.py` — ÚNICO lugar donde se leen variables de entorno.

**Decisiones de diseño ya tomadas** (no re-litigar):
- El brief del alumno entra como primer `HumanMessage`; las reglas fijas van en el
  `SystemMessage`. Sin "kickoff" artificial.
- El feedback final es Markdown libre + `words`/`phrases` estructurados (JSON vía
  `with_structured_output`).
- El servicio recibe el grafo por constructor (DI); el grafo se arma una vez al arranque.

**Estado de la migración (pendiente, aparte del aprendizaje):**
- [ ] Cablear `app/cmd/server.py` como entrypoint real.
- [ ] Migrar el endpoint `/answer` (depende de `scoring`/`speech`/`db`).
- [ ] Migrar el CRUD de prompts.
- [ ] Persistir `practice_phrases` (campo nuevo) cuando se migre el guardado.
- [ ] Tests del módulo `app/conversation/`.

---

## Prioridad alta (lo más típico en entrevistas)

### 1. `init_chat_model` — modelo agnóstico de proveedor
- [x] Hecho
- **Qué es**: en vez de instanciar `ChatGoogleGenerativeAI` a mano, usar
  `from langchain.chat_models import init_chat_model` para elegir el modelo por string
  (`"google_genai:gemini-2.5-flash"`) o `model_provider`. Cambiar de proveedor = cambiar
  config, no código.
- **Dónde en el proyecto**: `app/conversation/service.py` → función `build_llm`.
- **Qué hacer**:
  - Reemplazar la instanciación manual por `init_chat_model`.
  - Centralizar el string del modelo/proveedor en `config.py` (respetar la convención de
    env centralizado). Ojo con cómo se pasa el `api_key` según el proveedor.
- **Verificar en doc oficial (Context7)**: firma de `init_chat_model`, cómo pasar la
  API key para `google_genai`, y el modo "configurable" (cambiar modelo en runtime).
- **Por qué (entrevista)**: muestra que sabes desacoplar del proveedor; se pregunta mucho.

### 2. Checkpointer persistente (SQLite → Postgres)
- [ ] Hecho
- **Qué es**: hoy el grafo usa `InMemorySaver` → el estado de cada conversación vive en
  memoria y se pierde al reiniciar o entre workers. Un checkpointer persistente guarda el
  estado (mensajes, `thread_id`) en una BD real.
- **Ojo (confusión común)**: el SQLite actual (`SqliteStorage`) es solo para las **configs**
  (`conversation_configs`), NO para el estado del grafo. Son dos persistencias distintas.
- **Dónde en el proyecto**: `app/conversation/graph.py` → `build_graph(..., checkpointer)`;
  se inyecta desde `build_service` en `service.py`.
- **Qué hacer**:
  - Paso intermedio: `SqliteSaver` (reusa el SQLite que ya tienes).
  - Producción: `PostgresSaver` (para varios workers / autoescalado).
  - Pasar el saver a `build_graph` en lugar del `InMemorySaver` por defecto.
- **Verificar en doc oficial (Context7)**: import exacto de `SqliteSaver`/`PostgresSaver`,
  setup (context manager, `.setup()` para crear tablas), sync vs async.
- **Por qué (entrevista)**: la persistencia de estado es EL tema de LangGraph en serio.

### 3. LangSmith — observabilidad
- [x] Hecho (activación por env + proyecto `review-ingles`; falta el "extra" de datasets/evals → punto 5)
- **Qué es**: trazas automáticas de cada `llm.invoke` y corrida del grafo (mensajes exactos
  a Gemini, tokens, latencia, costo). Se activa por variables de entorno, sin tocar código.
- **Qué hacer**:
  - Cuenta en smith.langchain.com → API key.
  - `.env`: `LANGSMITH_TRACING=true`, `LANGSMITH_API_KEY=...`, `LANGSMITH_PROJECT=review-ingles`.
  - Declarar las constantes en `config.py` (convención de env centralizado).
  - Correr el server (legacy o nuevo) con una `GEMINI_API_KEY` real y mirar las trazas.
- **Extra a explorar dentro de LangSmith**: **datasets + evaluación offline** (correr casos
  guardados y medir si un cambio de prompt mejora). Esto es lo que separa a alguien que
  "arma un chatbot" de alguien que opera LLMs en serio.
- **Por qué (entrevista)**: observabilidad y evals son diferenciadores fuertes.

---

## Prioridad media (profundizar lo que ya tocaste)

### 4. Streaming
- [ ] Hecho
- **Qué es**: emitir tokens/actualizaciones del grafo en vivo (`.stream()` / `astream`)
  en lugar de esperar la respuesta completa.
- **Dónde**: nodo `ask` / endpoints. Requiere endpoint que soporte streaming (SSE).
- **Por qué (entrevista)**: UX de chat en tiempo real; se pide seguido.

### 5. Evals con LangSmith (ampliación del punto 3)
- [ ] Hecho
- **Qué hacer**: crear un dataset con briefs de ejemplo + respuestas, y evaluar la calidad
  del feedback o de las preguntas cuando cambias el prompt. LLM-as-judge.
- **Por qué (entrevista)**: medir en vez de "probar a ojo".

### 6. Manejo de errores, reintentos y costo
- [ ] Hecho
- **Qué es**: reintentos ante fallos del LLM, límites de tokens, control de costo, timeouts.
- **Dónde**: `service.py` / `graph.py`. Ligado a lo que LangSmith te muestra de tokens/costo.

---

## Prioridad de exploración (temas nuevos para ti)

### 7. Subgrafos y patrones multi-agente
- [ ] Hecho
- **Qué es**: componer varios grafos/agentes (p. ej. un agente que pregunta y otro que
  evalúa), o subgrafos reutilizables.
- **Idea aplicada al proyecto**: separar el "tutor que conversa" del "evaluador que da
  feedback" como agentes distintos, en vez de un solo grafo con `ask`/`finalize`.
- **Por qué (entrevista)**: "multi-agent" es la palabra de moda; conviene tener una demo.

### 8. Human-in-the-loop
- [ ] Hecho
- **Qué es**: pausar el grafo para intervención humana (aprobar/editar) y reanudar usando
  el checkpointer. Requiere persistencia (punto 2).
- **Por qué (entrevista)**: patrón clave en agentes de producción.

---

## Ya lo tienes (para mencionar en la entrevista, no hace falta reaprender)

- Estado con reducers (`add_messages`).
- Ruteo condicional (`conditional_edges`).
- Salida estructurada (`with_structured_output` → `FeedbackReport`).
- Checkpointers y persistencia por `thread_id` (entendido a fondo, falta el saver persistente).
- Guardrails / anti prompt-injection (system prompt con precedencia sobre el brief).
- Inyección de dependencias y testeo con dobles del LLM/grafo.
- Validación con Pydantic en la capa de entrada.

---

## Orden sugerido

1. `init_chat_model` (rápido, alto impacto) → punto 1
2. LangSmith (activarlo ya, para ver todo lo demás) → punto 3
3. Checkpointer persistente → punto 2
4. Evals → punto 5
5. Streaming → punto 4
6. Multi-agente / human-in-the-loop → puntos 7 y 8
