# Transcripción visible por turno — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que la transcripción de la respuesta del usuario (fuente navegador o Azure) quede visible al parar de grabar y persista mientras lee la siguiente pregunta, hasta que arranque a grabar el próximo turno.

**Architecture:** Cambio solo de frontend en `app.js`. Hoy `showQuestion()` oculta `#conv-turn` justo después de que `sendConversationAnswer` lo muestra, así que la transcripción intermedia desaparece al instante. Se invierte la responsabilidad: mostrar una pregunta ya no oculta la transcripción; la transcripción se limpia recién al iniciar la grabación del siguiente turno.

**Tech Stack:** JavaScript vanilla (navegador), Web Speech API + Azure ya integrados. Verificación con `node --check` + `uv run pytest` + walkthrough manual (no hay arnés de tests JS).

## Global Constraints

- Sin cambios de backend (`main.py`, `scoring.py`, `conversation.py`) ni de la firma del endpoint.
- Sin cambios en los tests de Python; deben seguir verdes.
- No hay arnés de tests JS: se valida con `node --check app.js`, `uv run pytest`, e inspección manual.
- Mensajes al usuario en español.
- `node` está en `/opt/homebrew/bin/node`. Comandos de test: `uv run pytest` desde `review-ingles/`.

---

### Task 1: Persistir la transcripción del turno hasta el siguiente turno (`app.js`)

**Files:**
- Modify: `app.js` (funciones `showQuestion`, `startConversation`, `sendConversationAnswer`, y el handler de click de `els.convRecord`)

**Interfaces:**
- Consumes (ya existen en `app.js`): `els.convTurn` (el `<div id="conv-turn">`), `els.convRecognized`, `els.convTurnScores`, `state` (`"idle" | "recording" | "sending"`), `startRecording()`, `stopRecording()`, `recordSink`, `convSettings.source`, `startBrowserRecognition()`, `stopBrowserRecognition()`, `renderScoreCards()`, `speak()`, `showConvError()`, `formatDetail()`, `loadWordBank()`.
- Produces: sin nuevas funciones ni exports; solo cambia el comportamiento de visibilidad de `#conv-turn`.

No hay test automatizado (frontend sin arnés). La verificación es `node --check`, `uv run pytest` verde y walkthrough manual, en los pasos finales.

- [ ] **Step 1: Que `showQuestion` NO oculte la transcripción**

En `app.js`, en la función `showQuestion`, borra la línea que oculta `#conv-turn`. Queda así:

```javascript
// Muestra una pregunta nueva: la escribe y la habla.
function showQuestion(question) {
  els.convQuestion.textContent = question;
  speak(question);
}
```

(Antes tenía `els.convTurn.classList.add("hidden");` entre esas dos líneas; esa es la línea que se elimina.)

- [ ] **Step 2: Ocultar la transcripción vieja al iniciar la grabación del turno**

En `app.js`, en el handler `els.convRecord.addEventListener("click", async () => { ... })`, dentro de la rama `if (state === "idle")`, después de fijar `recordSink` y ANTES de arrancar el reconocimiento/grabación, oculta `#conv-turn`. La rama `idle` completa queda así:

```javascript
  if (state === "idle") {
    recordSink = sendConversationAnswer;
    els.convTurn.classList.add("hidden"); // limpia la transcripcion del turno anterior
    if (convSettings.source === "browser") startBrowserRecognition();
    await startRecording();
    if (state === "recording") {
      els.convRecord.textContent = "Parar";
      els.convStatus.textContent = "Grabando... responde ahora.";
    } else {
      // startRecording no arranco (permiso denegado, etc.). El error ya quedo visible
      // en convError; solo falta que el boton/estado no mientan.
      if (convSettings.source === "browser") stopBrowserRecognition();
      els.convRecord.textContent = "Responder";
      els.convStatus.textContent = "";
      recordSink = null;
    }
  } else if (state === "recording") {
```

(El resto del handler —la rama `else if (state === "recording")`— no se toca.)

- [ ] **Step 3: Ocultar la transcripción al arrancar una conversación nueva**

En `app.js`, en la función `startConversation`, después de mostrar la conversación activa y antes/junto a `showQuestion(data.question)`, oculta `#conv-turn` para no arrastrar la transcripción de una conversación anterior. El final de `startConversation` queda así:

```javascript
  const data = await response.json();
  conversationId = data.conversation_id;
  els.convSetup.classList.add("hidden");
  els.convFinal.classList.add("hidden");
  els.convActive.classList.remove("hidden");
  els.convTurn.classList.add("hidden"); // sin transcripcion arrastrada de otra conversacion
  showQuestion(data.question);
}
```

- [ ] **Step 4: Mensaje claro cuando la fuente no captó voz**

En `app.js`, en `sendConversationAnswer`, cambia el fallback de vacío. Reemplaza:

```javascript
  els.convRecognized.textContent = data.recognized_text || "(vacio)";
```

por:

```javascript
  els.convRecognized.textContent =
    data.recognized_text || "(la API no captó tu voz correctamente)";
```

- [ ] **Step 5: Verificar sintaxis JS**

Run: `/opt/homebrew/bin/node --check app.js`
Expected: sin salida (exit 0), sin errores de sintaxis.

- [ ] **Step 6: Verificar que el backend sigue intacto**

Run: `uv run pytest` desde `review-ingles/`
Expected: PASS todo (solo el warning preexistente de Starlette). Los tests de Python no cambian.

- [ ] **Step 7: Walkthrough manual**

Requiere Chrome con `AZURE_SPEECH_KEY` + `GEMINI_API_KEY` en `.env`. Levanta el server (`uv run python main.py`) y abre `http://127.0.0.1:<PORT>`.

1. Pestaña Conversación → fuente "Navegador" → escenario + al menos 2 preguntas → Empezar.
2. Responder hablando → al Parar, aparece "Lo que se escuchó: …" con la transcripción del navegador.
3. Suena la siguiente pregunta y **la transcripción del turno anterior SIGUE visible** debajo.
4. Apretar "Responder" de nuevo → la transcripción anterior **desaparece** al arrancar a grabar.
5. Cambiar la fuente a "Azure" en otra conversación → además del texto se ve el score del turno.
6. Responder sin hablar (silencio/ruido) → se muestra "(la API no captó tu voz correctamente)".
7. Terminar las N preguntas → el último turno queda visible junto al resultado final; el banco de palabras se refresca.
8. La pestaña "Practicar" sigue intacta.

- [ ] **Step 8: Commit**

```bash
git add app.js
git commit -m "fix: la transcripcion del turno persiste hasta el siguiente turno"
```

---

## Notas

- El cambio es puramente de visibilidad de `#conv-turn`; el marcado en `index.html` ya deja la pregunta arriba y `#conv-turn` debajo, así que la pregunta nueva y la transcripción anterior conviven sin tocar el HTML.
- El score del turno (`#conv-turn-scores`) sigue apareciendo solo en modo Azure, como hoy: en modo navegador `data.turn_scores` es `null` y `sendConversationAnswer` limpia el contenedor.
