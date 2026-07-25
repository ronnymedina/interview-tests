# Transcripción visible por turno — Design

## Problema

En la vista de Conversación, cuando el usuario responde hablando, la transcripción de lo
que dijo (fuente navegador o Azure, según el toggle) **no se ve durante la conversación**.
Solo aparece en el turno final.

Causa raíz (en `app.js`): `sendConversationAnswer` muestra la transcripción
(`els.convTurn` deja de estar `hidden`) y, en turnos intermedios, llama de inmediato a
`showQuestion(data.next_question)`, que hace `els.convTurn.classList.add("hidden")`. La
transcripción aparece y se oculta en el mismo instante en que llega la siguiente pregunta.

## Objetivo

Que al parar de grabar cada turno, el usuario **vea la transcripción de la fuente activa**
(lo que entendió la API con la que está hablando), y que esa transcripción **persista
mientras lee la siguiente pregunta**. El usuario evalúa visualmente qué tan bien transcribió
y decide con qué fuente (toggle navegador/Azure) se queda. No hay comparación automática ni
métricas: solo se corre la fuente configurada, y la "comparación" es el juicio visual del
usuario cambiando el toggle entre turnos.

Sin tiempo real: alcanza con mostrar el texto completo al parar de grabar (consistente para
navegador y Azure; Azure no puede dar texto en vivo con la arquitectura actual).

## Alcance

- **Solo frontend** (`app.js`, y un retoque menor de `index.html` si hiciera falta).
- **Sin cambios de backend** (`main.py`, `scoring.py`, `conversation.py`) ni de la firma del
  endpoint.
- **Sin cambios en los tests de Python.** No hay arnés de tests JS: se valida con
  `node --check app.js`, `uv run pytest` verde, e inspección manual.

## Comportamiento (flujo por turno)

Regla: la transcripción del último turno **persiste hasta que el usuario arranca a grabar el
siguiente turno**.

1. Suena la pregunta N.
2. El usuario aprieta "Responder", habla, y aprieta "Parar".
3. Al terminar el envío, se muestra `Lo que se escuchó: <texto>` en `#conv-turn`
   (y el score del turno en `#conv-turn-scores` solo si la fuente es Azure).
4. Llega y suena la pregunta N+1. **La transcripción del turno N queda visible** debajo de la
   pregunta nueva.
5. El usuario aprieta "Responder" para el turno N+1: **al iniciar la grabación** se oculta
   `#conv-turn` (limpia la transcripción vieja). Vuelve al paso 2.

En el turno final no hay pregunta siguiente: la transcripción del último turno queda visible
junto al resultado final, sin cambios respecto a hoy.

## Caso "sin voz"

Si la fuente activa transcribió vacío (`recognized_text` vacío), en vez del genérico
`"(vacio)"` se muestra:

> (la API no captó tu voz correctamente)

Así ese fallo también le sirve al usuario para juzgar cuál fuente anda mejor.

## Cambios concretos (en `app.js`)

1. **`showQuestion(question)`**: quitar `els.convTurn.classList.add("hidden")`. Mostrar una
   pregunta nueva ya no oculta la transcripción del turno anterior.

2. **Handler de `els.convRecord`**, rama `state === "idle"` (inicio de grabación): cuando
   `startRecording()` arrancó bien (`state === "recording"`), ocultar `#conv-turn`
   (`els.convTurn.classList.add("hidden")`) para limpiar la transcripción del turno previo
   justo cuando el usuario empieza a hablar de nuevo.

3. **`sendConversationAnswer`**: cambiar el fallback de vacío de
   `data.recognized_text || "(vacio)"` a
   `data.recognized_text || "(la API no captó tu voz correctamente)"`.

4. **`startConversation()`**: al arrancar una conversación nueva, ocultar `#conv-turn`
   (`els.convTurn.classList.add("hidden")`) para no arrastrar la transcripción de una
   conversación anterior.

El orden en `index.html` ya deja la pregunta arriba y `#conv-turn` debajo, así que la nueva
pregunta y la transcripción anterior conviven sin cambios de marcado.

## Verificación

- `node --check app.js` → sin errores de sintaxis.
- `uv run pytest` → verde (solo el warning preexistente de Starlette).
- Walkthrough manual (Chrome, con `AZURE_SPEECH_KEY` + `GEMINI_API_KEY`):
  1. Fuente "Navegador", ≥2 preguntas → responder hablando → al parar, se ve "Lo que se
     escuchó: …" y **sigue visible** cuando suena la siguiente pregunta.
  2. Al apretar "Responder" de nuevo, la transcripción anterior desaparece antes de grabar.
  3. Fuente "Azure" → además del texto se ve el score del turno.
  4. Responder sin hablar (o con ruido) → se ve "(la API no captó tu voz correctamente)".
  5. Terminar la conversación → el último turno queda visible junto al resultado final.

## Alternativas descartadas

- **Acumular un historial de todos los turnos**: más ruido visual y más código; no se pidió
  (YAGNI).
- **Ocultar la transcripción tras un timer de N segundos**: frágil y molesto si el usuario
  está leyendo.
- **Correr navegador y Azure a la vez para comparar**: explícitamente NO deseado; solo corre
  la fuente configurada.
- **Transcripción en tiempo real (palabra por palabra)**: no requerido; además sería
  inconsistente entre navegador (posible) y Azure (no).
