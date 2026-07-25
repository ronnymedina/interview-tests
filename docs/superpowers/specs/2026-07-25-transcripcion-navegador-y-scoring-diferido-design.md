# Diseño: Transcripción por navegador + scoring de pronunciación diferido

Fecha: 2026-07-25
Proyecto: `review-ingles`
Incremento sobre: `2026-07-24-conversacion-langgraph-gemini-design.md`

## Objetivo

Aligerar la espera durante la conversación. Hoy, al terminar de hablar, el turno espera a
que Azure haga transcripción + evaluación de pronunciación (una sola llamada, síncrona)
antes de continuar. Queremos que la conversación fluya: la transcripción alimenta a Gemini
de inmediato y la **evaluación de pronunciación se difiere**.

Además, para poder **comparar** la calidad de transcripción, se ofrece un **toggle** entre
dos fuentes de transcripción, y se **muestra siempre lo que captó el micrófono** por turno.

## Decisiones (brainstorming)

- **Toggle de fuente de transcripción**, persistente en el navegador (como los ajustes de
  TTS), elegible por conversación:
  - **Navegador (Web Speech API `SpeechRecognition`)**: transcribe en vivo, gratis, sin
    round-trip. El audio grabado se encola para que Azure lo puntúe **en segundo plano**;
    los scores se agregan al final.
  - **Azure (comportamiento actual)**: `speech.assess_unscripted` síncrono por turno
    (texto + scores juntos), con scores por turno visibles.
- **Mostrar "lo que captó el micrófono"** por turno: la transcripción de la fuente activa,
  como resumen visual de lo que se entendió o no.
- **Scoring en segundo plano, por turno** (modo navegador): al encolar el audio se lanza su
  evaluación de pronunciación en un worker; la conversación no espera. Al finalizar se
  espera lo pendiente y se agrega.
- **Persistencia**: sin cambios — solo el resultado final (scores agregados + feedback).
- La **pronunciación siempre la mide Azure** sobre el audio real, en ambos modos; el toggle
  solo cambia de dónde sale el texto que alimenta a Gemini (y si el scoring es síncrono o
  diferido).

## Arquitectura

### Nuevo: `scoring.py` — store de resultados de pronunciación por conversación

Aísla la cola/acumulación de resultados de `assess_unscripted`, indexada por
`conversation_id`.

- `ThreadPoolExecutor` compartido + un registro `{conversation_id: [Future]}` con lock.
- `enqueue(conversation_id, audio_bytes) -> Future`: escribe un WAV temporal, corre
  `speech.assess_unscripted` en un worker (lo borra en `finally`), guarda el Future en el
  registro y lo devuelve. Una respuesta que falle (sin voz / error de Azure) resuelve a
  `None` para no romper el resultado final.
- `collect(conversation_id) -> list[dict]`: saca los Futures de esa conversación, espera sus
  resultados y devuelve los que no son `None`.
- `aggregate(results) -> tuple[dict, list[dict]]`: promedia los `scores`
  (pronunciation/accuracy/fluency/prosody, ignorando `None`) y concatena las `words` de
  todos los turnos.

Uso por modo:
- **Navegador**: el endpoint llama `enqueue` y no espera (background).
- **Azure**: el endpoint llama `enqueue` y hace `future.result()` de inmediato para mostrar
  los scores de ese turno; el Future queda igualmente en el registro para el agregado final.

### Backend: transcripción

- Modo **navegador**: el texto llega desde el cliente (campo `transcript`); el backend NO
  transcribe.
- Modo **Azure**: el texto sale del resultado de `assess_unscripted` (el `recognized_text`).

No se agrega `speech.transcribe`: en modo navegador el texto lo da el cliente, y en modo
Azure se reutiliza `assess_unscripted`.

### Cambios en el grafo (`conversation.py`)

- Se quitan `per_turn_scores` y `per_turn_words` del `State` (el scoring ya no vive en el
  grafo). `answer(conversation_id, recognized_text, graph=None)` pierde los parámetros de
  score/words.
- El payload `final` de `answer` deja de traer `scores`/`words`; conserva `content_feedback`,
  `system_prompt`, `questions_asked`. El endpoint completa `scores`/`words` desde
  `scoring.collect` + `scoring.aggregate`.
- `aggregate_scores` se mueve a `scoring.py` (o se reimplementa allí); se elimina de
  `conversation.py` si queda sin uso.

### Endpoint `/conversation/{id}/answer`

Multipart: `audio` (siempre), `mode` (`browser`|`azure`), `transcript` (requerido si
`mode=browser`).

1. `conversation.exists(id)` (barato) → 404 si no existe.
2. Lee el audio (400 si vacío).
3. Según modo:
   - **browser**: `text = transcript` (400 si vacío); `scoring.enqueue(id, audio_bytes)`
     (background, no espera); `turn_scores = None`.
   - **azure**: `future = scoring.enqueue(id, audio_bytes)`; `result = future.result()`;
     `text = result["recognized_text"]`; `turn_scores = result["scores"]`. Si Azure no
     detectó voz (result `None`), 422 para reintentar.
4. `result = conversation.answer(id, text)` (Gemini) → siguiente pregunta o final.
5. Respuesta intermedia: `{recognized_text, turn_scores, next_question}` (`turn_scores`
   es `null` en modo navegador).
6. Turno final: `results = scoring.collect(id)`; `scores, words = scoring.aggregate(results)`;
   `db.save_conversation(system_prompt, questions_asked, scores, content_feedback, words)`;
   respuesta `{recognized_text, turn_scores, final: {scores, content_feedback}}`.

### Frontend (vista Conversación)

- **Toggle de transcripción** (Navegador / Azure), persistido en `localStorage`. Si el
  navegador no soporta `SpeechRecognition`, se deshabilita la opción Navegador con una nota
  y se usa Azure.
- **Modo navegador**: al grabar, se inicia también `SpeechRecognition` sobre el micrófono
  (en paralelo a la grabación del WAV). Al parar, se toma la transcripción final y se envía
  `mode=browser` + `transcript` + `audio`. No se muestran scores por turno.
- **Modo Azure**: como hoy — se envía `mode=azure` + `audio`; el backend transcribe y puntúa;
  se muestran los scores por turno.
- **Siempre** se muestra "lo que captó el micrófono" (`recognized_text`) del turno.
- Estado: "Transcribiendo..." (navegador) / "Evaluando con Azure..." (azure).
- Resultado final (scores agregados + feedback): sin cambios.

## Trade-offs / límites

- Modo navegador: la transcripción que ve Gemini puede diferir de Azure (STT del navegador),
  pero la pronunciación la mide Azure sobre el audio, así que el score no depende de ella.
- `SpeechRecognition`: Chrome/Edge/Safari reciente sí; Firefox no. Requiere conexión.
- El store de scoring vive en memoria del proceso (consistente con el `InMemorySaver` del
  grafo); si el proceso se reinicia se pierde el progreso de esa conversación.
- Correr `SpeechRecognition` + grabación del WAV a la vez sobre el mismo micrófono funciona
  en Chrome; es el escenario asumido.

## Fuera de alcance (YAGNI)

- Mostrar a la vez la transcripción del navegador Y la de Azure para diff explícito (solo se
  muestra la de la fuente activa).
- Reintentos automáticos de los scorings en background que fallaron (se descartan).
- Persistir el turno-a-turno o las transcripciones individuales.
