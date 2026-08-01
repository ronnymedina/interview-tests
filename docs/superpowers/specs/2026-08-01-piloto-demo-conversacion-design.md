# Piloto demo de conversación (app/) — diseño

Fecha: 2026-08-01

## Objetivo

Convertir el módulo migrado `app/` en un **piloto demo público** para medir interés real:
cuánto cuesta un usuario y una conversación, y qué opina la gente. No hay registro; cada
navegador se identifica con un UUID. El valor central es la **evaluación de pronunciación
de Azure** al final (scores + palabras a mejorar con botón de sonido), igual que en el
legacy, sobre una conversación guiada por Gemini de **5 preguntas fijas**.

Prioridades del piloto: (1) no desangrarse en costo, (2) medir costo por usuario/conversación,
(3) UX limpia y rápida, (4) recoger feedback.

## Alcance y decisiones tomadas

- **Identidad:** UUID generado con `crypto.randomUUID()` en el primer ingreso, guardado en
  `localStorage`, enviado en cada request como header `X-User-Id`. No hay registro ni login.
  Limitación aceptada: es evadible (incógnito / borrar datos). Suficiente para un demo; se
  documenta, no se blinda.
- **Cuota por usuario:** 3 conversaciones **de por vida** por `X-User-Id`. Al agotarlas, la UI
  muestra un mensaje de límite alcanzado (no es el mismo banner que el corte global).
- **Límite de costo (dos niveles):**
  - Presupuesto **diario de $3 USD**: al superarlo, la app entra en pausa hasta el día siguiente
    (se rehabilita solo al cambiar la fecha; sin trabajo manual).
  - Tope **total de $10 USD**: al alcanzarlo, la app queda en pausa hasta intervención manual.
  - **Mismo banner neutro** para ambos: "En pausa por el momento". Sin mensajes de "vuelve
    mañana".
- **Medición de costo:** tokens reales de Gemini (de `usage_metadata`) × tarifa configurable, y
  duración de audio de Azure × tarifa configurable. Todo se persiste como eventos y el costo se
  obtiene sumando, no con contadores mutables.
- **Transcripción y scoring (Opción 2 = navegador + Azure diferido):** el navegador transcribe
  cada respuesta (mueve la conversación rápido, mueve a Gemini). El WAV de cada respuesta se
  manda y **Azure lo puntúa en segundo plano** sin bloquear el turno. Los scores se **agregan y
  se muestran solo en la pantalla final**.
- **Límite de 30 s por respuesta:** la grabación del navegador se corta automáticamente a los 30
  segundos (con contador visible). Recorta gasto de Azure (se cobra por duración), baja latencia
  y acorta los tokens que ve Gemini.
- **La conversación NO se persiste:** a diferencia del legacy (`save_conversation`), el
  contenido y los scores de la conversación no se guardan. Sí se persisten las tres cosas
  operativas: `usage_events`, `conversation_starts`, `pilot_feedback`.
- **Feedback final = igual que el legacy actual:** scores de pronunciación + palabras con su
  pista de pronunciación y **botón de sonido** (clic → suena la palabra vía TTS del navegador) +
  feedback de contenido de Gemini en Markdown + frases (original → sugerencia).
- **Feedback del usuario:** al terminar, formulario con like/dislike, estrellas 1–5, caja de
  texto libre, y "¿te interesarían más funciones? ¿cuáles?". Se guarda en `pilot_feedback`.
- **Configuraciones guardadas:** se **quitan del frontend** (el piloto no las usa). Los endpoints
  `/conversation/configs/*` se dejan en backend por ahora (testeados, no estorban), marcados como
  no usados en el piloto.
- **Diseño visual:** reescritura del frontend como **stepper de 3 pasos**, estética boutique
  elegante sobre base blanco/crema cálida. Acento **dorado champagne apagado** (mate, no
  brillante) para botones, borde del óvalo y detalles activos; texto gris carbón. Tipografía
  con **serif de display** para títulos y preguntas + **sans limpio** para cuerpo y botones.
  Espaciado generoso, esquinas suaves, sombras muy sutiles. Responsabilidades separadas en el JS.

## Arquitectura

### Backend — nuevo módulo `app/speech/` (migración limpia de Azure)

Responsabilidades separadas, una por archivo (mismo criterio que el legacy):

- `app/speech/azure_client.py` — **único** punto que habla con el SDK de Azure (equivalente a
  `azure_speech.py` de la raíz). Recibe credenciales ya tipadas desde `config`, corre el
  reconocimiento continuo con Pronunciation Assessment, devuelve datos crudos. Sin lógica de
  negocio.
- `app/speech/assessment.py` — lógica de `assess_unscripted`: normaliza, marca mispronunciations
  (accuracy < 60), calcula accuracy/fluidez/prosodia y arma las palabras con su accuracy. No toca
  el SDK. Devuelve además la **duración de audio** (para el costo).
- `app/speech/scoring.py` — cola en segundo plano por conversación (`enqueue`/`collect`/
  `aggregate`), con `ThreadPoolExecutor`. Encola el WAV de cada turno, agrega scores y concatena
  palabras al final. Vive en memoria del proceso (consistente con el checkpointer del grafo).
- `app/speech/service.py` (o `__init__.py`) — expone un `SpeechService` que se inyecta en el
  composition root, igual que `ConversationService`. Si falta `AZURE_SPEECH_KEY`, degrada
  (endpoints devuelven 503 / se omite el scoring), sin tumbar el servidor.

### Backend — nuevo módulo `app/limits/` (cuota + presupuesto)

- Registra eventos de uso y decide si la app puede atender un request nuevo.
- `usage_events`: fuente de verdad del costo. Se inserta una fila por cada llamada facturable.
- `conversation_starts`: una fila por conversación iniciada (para la cuota por usuario).
- Consultas: costo del día (`WHERE created_at::date = today`), costo total, y nº de
  conversaciones por `user_id`. Sin contadores mutables que se desincronicen.
- Un `LimitsService` inyectado expone: `check_can_start(user_id) -> Decision` (permite / cuota
  agotada / pausa diaria / pausa total) y helpers para registrar uso.

### Backend — feedback (`app/feedback/`)

- Tabla `pilot_feedback` + un `FeedbackRepository` y un endpoint `POST /feedback`.

### Endpoints (cambios en `app/cmd/server.py`)

- `POST /conversation/start` — ahora, **antes** de arrancar, consulta `LimitsService.check_can_start`
  con el `X-User-Id`. Si no puede: 429 con un motivo tipado (`quota` | `paused`) para que el
  frontend muestre el mensaje o banner correcto. Si puede: registra `conversation_starts`,
  sintetiza el contexto, registra el `usage_event` de la síntesis (tokens Gemini) y devuelve la
  1ª pregunta.
- `POST /conversation/answer` — cambia de recibir texto a recibir **multipart**: `conversation_id`,
  `audio` (WAV), `transcript` (del navegador). Encola el WAV en `app/speech/scoring` (no espera),
  inyecta el `transcript` al grafo para obtener la siguiente pregunta, y registra el `usage_event`
  de esa pregunta (tokens Gemini). En la **última** respuesta: obtiene el feedback de Gemini
  (registra su `usage_event`), llama a `scoring.collect` + `aggregate` para los scores/palabras de
  Azure (registra un `usage_event` de Azure por la duración total del audio evaluado) y devuelve el
  resultado final combinado. **No** persiste la conversación.
- `POST /feedback` — guarda el formulario en `pilot_feedback` con el `X-User-Id`.
- `/conversation/configs/*` — se quedan pero salen del frontend.

### Config (`config.py`)

Nuevas constantes (respetando "todas las env viven aquí"):

- `GEMINI_PRICE_INPUT_PER_1K`, `GEMINI_PRICE_OUTPUT_PER_1K`
- `AZURE_SPEECH_PRICE_PER_SECOND` (o por hora, normalizado a segundo)
- `DAILY_BUDGET_USD` (default 3.0), `TOTAL_BUDGET_USD` (default 10.0)
- `USER_CONVERSATION_QUOTA` (default 3)
- `MAX_ANSWER_SECONDS` (default 30) — expuesto al frontend si conviene
- `MAX_QUESTIONS` (default 5) — fijo del piloto

### Frontend — `app/web/index.html` reescrito

Stepper de 3 pasos, JS con responsabilidades separadas (identidad, TTS, grabación WAV, cliente
API, control del stepper, animación del óvalo). Estética boutique: base blanco/crema cálida,
acento dorado champagne apagado, texto gris carbón, serif de display en títulos + sans en cuerpo.

- **Paso 1 — Voz:** elegir voz (en-*) + velocidad para el TTS que lee las preguntas. Se guarda en
  `localStorage`; si ya existe, se salta este paso al volver.
- **Paso 2 — Contexto:** un único textarea (pegar) con opción de dictar por voz. Sin lista de
  conversaciones guardadas.
- **Paso 3 — Conversación:** un **óvalo** dorado que **se anima/pulsa solo cuando habla el
  agente** (mientras el TTS del navegador lee la pregunta), enganchado a los eventos
  `onstart`/`onend`/`onboundary` de `SpeechSynthesis`; se detiene cuando el agente termina.
  Mientras el alumno graba su respuesta el óvalo queda en estado quieto/neutro (anillo tenue de
  "grabando" + contador), para dejar claro de quién es el turno. Dos botones (hablar / detener);
  **contador de 30 s** que corta solo; 5 preguntas fijas. Cada respuesta: graba WAV (AudioContext →
  PCM 16-bit mono, `encodeWav`) **y** transcribe con `webkitSpeechRecognition`; al detener (o a los
  30 s) manda ambos a `/conversation/answer`.
- **Pantalla final:** feedback de Gemini (Markdown) + scores de Azure + palabras con botón de
  sonido + frases. Debajo, el **formulario de feedback**. Botón "volver a empezar".
- **Banner de pausa:** si algún request devuelve `paused`, se muestra el banner neutro "En pausa
  por el momento" y se bloquea el inicio. Si devuelve `quota`, mensaje de límite del usuario.

## Flujo de datos (una conversación)

1. Entrada → si no hay UUID en `localStorage`, se crea. Paso 1 (voz) si no está guardada.
2. Paso 2 → contexto. "Empezar" → `POST /conversation/start` (X-User-Id).
   - Backend: `check_can_start` → registra `conversation_starts` → síntesis (usage_event Gemini)
     → 1ª pregunta.
3. Por cada respuesta (hasta 5): navegador graba WAV + transcript (≤30 s) →
   `POST /conversation/answer`.
   - Backend: `scoring.enqueue(wav)` (background Azure), `graph.answer(transcript)` →
     siguiente pregunta (usage_event Gemini).
4. En la 5ª: `finalize` (usage_event Gemini) + `scoring.collect/aggregate` (usage_event Azure por
   duración) → respuesta final combinada. **Nada se guarda de la conversación.**
5. Pantalla final → formulario → `POST /feedback` → `pilot_feedback`.

## Modelo de datos (Postgres, junto a `conversation_configs`)

```sql
CREATE TABLE IF NOT EXISTS usage_events (
    id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id         TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    provider        TEXT NOT NULL,          -- 'gemini' | 'azure'
    kind            TEXT NOT NULL,          -- 'synthesis' | 'question' | 'feedback' | 'assessment'
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    audio_seconds   REAL NOT NULL DEFAULT 0,
    cost_usd        NUMERIC(10,6) NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS conversation_starts (
    id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id         TEXT NOT NULL,
    conversation_id TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pilot_feedback (
    id            INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id       TEXT NOT NULL,
    liked         BOOLEAN,                  -- like / dislike
    rating        INTEGER,                  -- 1..5
    comment       TEXT NOT NULL DEFAULT '',
    wants_more    BOOLEAN,                  -- ¿te interesarían más funciones?
    suggestions   TEXT NOT NULL DEFAULT ''  -- cuáles
);
```

El DDL se agrega tanto a `app/storage.py` (uso standalone) como al init de Postgres del
docker-compose, coherente entre ambos.

## Manejo de errores y degradación

- Sin `AZURE_SPEECH_KEY`: la conversación funciona igual (transcripción del navegador + feedback de
  Gemini); el scoring de Azure se omite y la pantalla final no muestra scores. Se registra en log.
- Sin `GEMINI_API_KEY`: endpoints de conversación en 503 (ya existe).
- Postgres caído: `check_can_start` falla → decisión conservadora. Para un piloto que cuida costo,
  si no se puede verificar el presupuesto/cuota, **se corta** (pausa) en vez de arriesgar gasto.
- Audio sin voz o Azure cancela un turno: se descarta ese turno del scoring (como el legacy), no
  rompe el resultado final.
- Corte a 30 s: el navegador detiene la grabación y envía lo capturado.

## Testing

Siguiendo el stack ya instalado (pytest, hypothesis, mypy):

- `app/speech/assessment.py`: agregación de scores y detección de mispronunciation con dobles del
  cliente Azure (sin red).
- `app/speech/scoring.py`: enqueue/collect/aggregate con un `assess` falso.
- `app/limits/`: cálculo de costo, presupuesto diario/total y cuota por usuario con datos sembrados
  en una BD de prueba.
- Endpoints: `check_can_start` retorna la decisión correcta (permite / cuota / pausa) y
  `/conversation/answer` encola + avanza el grafo, con dobles.
- `POST /feedback`: persiste y valida rangos (rating 1..5).

## Orden de construcción sugerido (para el plan)

1. Migrar `app/speech/` (azure_client + assessment + scoring) con tests, sin tocar endpoints.
2. Tablas + `app/limits/` (usage_events, conversation_starts) y medición de costo Gemini.
3. Cambiar `/conversation/start` y `/conversation/answer` (multipart + audio + límites + uso).
4. `app/feedback/` + `POST /feedback` + tabla.
5. Frontend nuevo (stepper, óvalo animado con la voz del agente, 30 s, pantalla final, formulario, banner de pausa).

## Fuera de alcance (YAGNI en el piloto)

- Persistir el contenido/scores de la conversación.
- Historial, banco de palabras, textos de lectura del legacy.
- Recarga de créditos / pagos.
- Blindaje anti-evasión del UUID.
- Score de pronunciación por turno en pantalla (solo agregado final).
