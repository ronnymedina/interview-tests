# Frontend nuevo — stepper crema/dorado + óvalo tutor (Fase 5) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reescribir `app/web/index.html` como un demo de práctica de inglés en **stepper de 3 pasos** con estética boutique (base crema, acento dorado champagne, display serif Fraunces + cuerpo sans), identidad por navegador (`X-User-Id`), grabación de audio WAV + transcripción del navegador enviadas al backend multipart, un **óvalo tutor** que se anima con la voz del agente, contador de 30 s, pantalla final con feedback + scores de Azure + palabras con sonido, formulario de feedback, y banner de pausa/cuota.

**Architecture:** Un único archivo `app/web/index.html` (HTML + CSS + JS inline, como el actual). El JS se organiza por responsabilidades separadas en módulos-objeto dentro del mismo `<script>`: `Identity` (UUID en localStorage), `Api` (fetch con header `X-User-Id`), `Tts` (voz + eventos de habla), `Oval` (estados de animación), `Recorder` (AudioContext→WAV + reconocimiento), `Stepper` (control de pasos), y el orquestador que los une. No hay build step; se sirve estático desde `app/cmd/server.py` (que ya monta `app/web/`).

**Tech Stack:** HTML5, CSS (custom properties, keyframes), JavaScript vanilla (Web Speech API `speechSynthesis` + `SpeechRecognition`, `AudioContext`/`getUserMedia` para WAV, `fetch` multipart, `localStorage`, `crypto.randomUUID`). Fuente display **Fraunces** vía Google Fonts (con fallback serif). Sin frameworks.

## Global Constraints

- Esta fase reescribe SOLO `app/web/index.html`. No toca el backend (`app/cmd/server.py` ni módulos `app/*`). Los endpoints que consume ya existen: `POST /conversation/start` (JSON, header `X-User-Id`), `POST /conversation/answer` (multipart: `conversation_id`, `transcript`, `audio`), `POST /feedback` (JSON, header `X-User-Id`).
- **Identidad:** al primer ingreso se genera `crypto.randomUUID()`, se guarda en `localStorage` bajo la clave `pilot_user_id`, y se envía en TODA request como header `X-User-Id`. Nunca se pide login.
- **Sin configuraciones guardadas:** se elimina todo el CRUD de `/conversation/configs` del frontend actual. El Paso 2 es un único textarea (pegar contexto) con opción de dictar.
- **`/conversation/answer` es multipart**, no JSON: se envía `conversation_id` (texto), `transcript` (texto del navegador) y `audio` (Blob WAV). El WAV se genera con `AudioContext` (PCM 16-bit mono) + `encodeWav`.
- **Óvalo tutor — 3 estados**, la animación memorable de la página: *reposo* (respira lento), *agente hablando* (pulsa con `SpeechSynthesis`: latido por `onboundary`, glow dorado, arranca en `onstart`, para en `onend`), *alumno grabando* (anillo tenue neutro + contador de 30 s). El óvalo se anima con la voz del AGENTE, no del alumno.
- **Límite de 30 s** por respuesta: la grabación se corta sola a los 30 s (contador visible). El corte a 30 s y el clic en "Detener" hacen lo mismo: cierran el turno y envían audio+transcript.
- **Banner de pausa / cuota:** si un request devuelve `429` con `detail.reason === "paused"` → banner neutro "En pausa por el momento" y se bloquea el inicio. Si `reason === "quota"` → mensaje de límite del usuario ("Alcanzaste el máximo de conversaciones de la demo"). No mezclar los dos mensajes.
- **Degradación:** si el backend responde el resultado final con `pronunciation: null` (sin Azure), la pantalla final NO muestra el bloque de scores, pero sí el feedback de Gemini, palabras y frases.
- **Paleta (exacta):** `--cream #FAF6EF`, `--ivory #FFFDF8`, `--ink #2E2A26`, `--gold #B8963F`, `--gold-soft #EADFC4`, `--muted #8A8278`, `--sage #6E8B6A` (solo para scores altos). Display: `"Fraunces", Georgia, serif`. Cuerpo: `system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`.
- **Piso de calidad:** responsive a móvil (columna única ~600px), foco de teclado visible, `prefers-reduced-motion` respetado (el óvalo no pulsa si el usuario lo pidió). Copia en español, sentence case, verbos activos.
- **Verificación (no es TDD; es UI):** cada tarea termina extrayendo el `<script>` a un archivo temporal y corriendo `node --check` (sintaxis), y una **QA en navegador** con Claude in Chrome contra el checklist de la tarea. La app se levanta según el README/compose del proyecto; si no hay backend vivo, se verifica el render/flujo con stubs de `fetch` documentados en el checklist.

---

### Task 1: Sistema de diseño + shell del stepper + identidad + cliente API + Paso 1 (Voz)

**Files:**
- Modify: `app/web/index.html` (reescritura completa; esta task deja el andamiaje + Paso 1 funcional, los pasos 2–3 y final como secciones ocultas vacías que se llenan en tasks siguientes)

**Interfaces (JS, dentro del `<script>`):**
- Produces:
  - `Identity.get() -> string` (UUID de `localStorage.pilot_user_id`; lo crea si falta).
  - `Api.request(method, path, {json, form}) -> Promise<any>` — agrega `X-User-Id`; lanza `ApiError(status, reason, message)` en no-2xx.
  - `Stepper.go(name)` — muestra el paso `name` ("voice"|"context"|"talk"|"final"), actualiza el indicador de progreso.
  - `Tts.load()`, `Tts.speak(text, {onstart, onboundary, onend})`, poblado del `<select>` de voces + rate en `localStorage`.

- [ ] **Step 1: Reescribir `app/web/index.html` — `<head>`, tokens CSS y tipografía**

Reemplazar TODO el archivo. Empezar por el head con la fuente y los tokens:

```html
<!doctype html>
<html lang="es">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Practica tu inglés hablado</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600&display=swap"
      rel="stylesheet"
    />
    <style>
      :root {
        --cream: #faf6ef; --ivory: #fffdf8; --ink: #2e2a26;
        --gold: #b8963f; --gold-soft: #eadfc4; --muted: #8a8278; --sage: #6e8b6a;
        --serif: "Fraunces", Georgia, "Times New Roman", serif;
        --sans: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
        --radius: 16px; --shadow: 0 1px 2px rgba(46,42,38,.04), 0 8px 24px rgba(46,42,38,.06);
      }
      * { box-sizing: border-box; }
      body {
        margin: 0; background: var(--cream); color: var(--ink);
        font-family: var(--sans); line-height: 1.55;
        -webkit-font-smoothing: antialiased;
      }
      main { max-width: 620px; margin: 0 auto; padding: 40px 20px 80px; }
      h1, h2, .question { font-family: var(--serif); font-weight: 600; letter-spacing: -.01em; }
      h1 { font-size: 1.9rem; margin: 0 0 6px; }
      h2 { font-size: 1.35rem; margin: 0 0 6px; }
      .lead { color: var(--muted); margin: 0 0 28px; font-size: 1.02rem; }
      .card {
        background: var(--ivory); border: 1px solid var(--gold-soft);
        border-radius: var(--radius); padding: 28px; box-shadow: var(--shadow);
      }
      label { display: block; font-weight: 600; font-size: .9rem; margin: 18px 0 6px; }
      input, textarea, select {
        width: 100%; padding: 11px 13px; border: 1px solid var(--gold-soft);
        border-radius: 10px; font: inherit; background: #fff; color: var(--ink);
      }
      textarea { resize: vertical; min-height: 120px; }
      input:focus, textarea:focus, select:focus, button:focus-visible {
        outline: 2px solid var(--gold); outline-offset: 2px;
      }
      .row { display: flex; gap: 12px; flex-wrap: wrap; align-items: center; margin-top: 20px; }
      button {
        font: inherit; font-weight: 600; padding: 12px 22px; border-radius: 10px;
        border: 1px solid transparent; background: var(--gold); color: #fff; cursor: pointer;
        transition: filter .15s ease, transform .05s ease;
      }
      button:hover { filter: brightness(1.06); }
      button:active { transform: translateY(1px); }
      button:disabled { opacity: .45; cursor: not-allowed; }
      button.ghost { background: transparent; border-color: var(--gold-soft); color: var(--ink); }
      button.small { padding: 7px 14px; font-size: .85rem; }
      .status { color: var(--muted); font-size: .92rem; }
      .error { color: #b4402f; font-size: .92rem; margin-top: 12px; }
      .hidden { display: none !important; }
      .muted { color: var(--muted); font-size: .88rem; }
      @media (prefers-reduced-motion: reduce) { * { animation: none !important; } }
    </style>
  </head>
```

- [ ] **Step 2: `<body>` — indicador de progreso + secciones del stepper (banner, voz, contexto, talk, final)**

```html
  <body>
    <main>
      <!-- Banner de pausa / cuota (oculto por defecto) -->
      <div id="banner" class="card hidden" role="status" style="text-align:center; border-color:#e2c9a0">
        <h2 id="banner-title"></h2>
        <p id="banner-text" class="lead" style="margin:8px 0 0"></p>
      </div>

      <div id="app">
        <!-- Progreso -->
        <div id="progress" class="progress" aria-hidden="true">
          <span data-step="voice"></span><i></i>
          <span data-step="context"></span><i></i>
          <span data-step="talk"></span>
        </div>

        <!-- Paso 1: Voz -->
        <section id="step-voice" class="card step">
          <h2>La voz de tu tutor</h2>
          <p class="lead">Elige quién te lee las preguntas y a qué ritmo.</p>
          <label for="voice">Voz</label>
          <select id="voice"></select>
          <label for="rate">Ritmo: <span id="rate-value">0.95</span>×</label>
          <input id="rate" type="range" min="0.5" max="1.3" step="0.05" value="0.95" />
          <div class="row">
            <button id="voice-test" type="button" class="ghost small">Probar voz</button>
            <button id="voice-next" type="button">Continuar</button>
          </div>
        </section>

        <!-- Paso 2: Contexto (se llena en Task 2) -->
        <section id="step-context" class="card step hidden"></section>

        <!-- Paso 3: Práctica (se llena en Task 2/3) -->
        <section id="step-talk" class="card step hidden"></section>

        <!-- Pantalla final (se llena en Task 4) -->
        <section id="step-final" class="step hidden"></section>
      </div>
    </main>
    <script>
    // (Steps 3–6 de esta task)
    </script>
  </body>
</html>
```

Y el CSS del indicador de progreso (agregar al `<style>`):

```css
      .progress { display: flex; align-items: center; justify-content: center; gap: 10px; margin-bottom: 26px; }
      .progress span { width: 10px; height: 10px; border-radius: 50%; background: var(--gold-soft); }
      .progress span.done { background: var(--gold); }
      .progress span.active { background: var(--gold); box-shadow: 0 0 0 4px rgba(184,150,63,.18); }
      .progress i { width: 26px; height: 1px; background: var(--gold-soft); }
```

- [ ] **Step 3: JS — módulos `Identity` y `Api` (con `X-User-Id`)**

Dentro del `<script>`:

```javascript
      "use strict";
      const $ = (id) => document.getElementById(id);

      // ---- Identidad: un UUID por navegador, en localStorage ----
      const Identity = {
        get() {
          let id = localStorage.getItem("pilot_user_id");
          if (!id) {
            id = crypto.randomUUID();
            localStorage.setItem("pilot_user_id", id);
          }
          return id;
        },
      };

      class ApiError extends Error {
        constructor(status, reason, message) {
          super(message);
          this.status = status;
          this.reason = reason; // 'paused' | 'quota' | null
        }
      }

      // ---- Cliente API: agrega X-User-Id; normaliza errores (incl. 429 con reason) ----
      const Api = {
        async request(method, path, { json, form } = {}) {
          const headers = { "X-User-Id": Identity.get() };
          let body;
          if (json !== undefined) {
            headers["Content-Type"] = "application/json";
            body = JSON.stringify(json);
          } else if (form !== undefined) {
            body = form; // FormData: el navegador pone el multipart boundary
          }
          const res = await fetch(path, { method, headers, body });
          if (!res.ok) {
            let detail = res.statusText;
            let reason = null;
            try {
              const data = await res.json();
              if (data && typeof data.detail === "object" && data.detail) {
                reason = data.detail.reason || null;
                detail = reason || res.statusText;
              } else if (data && data.detail) {
                detail = data.detail;
              }
            } catch (_) {}
            throw new ApiError(res.status, reason, typeof detail === "string" ? detail : JSON.stringify(detail));
          }
          return res.status === 204 ? null : res.json();
        },
      };
```

- [ ] **Step 4: JS — módulo `Stepper` (control de pasos + progreso)**

```javascript
      // ---- Stepper: muestra un paso y actualiza el indicador de progreso ----
      const STEPS = ["voice", "context", "talk"];
      const Stepper = {
        go(name) {
          for (const s of ["voice", "context", "talk", "final"]) {
            $("step-" + s).classList.toggle("hidden", s !== name);
          }
          // El progreso solo cubre los 3 pasos del flujo (no la pantalla final).
          const idx = STEPS.indexOf(name);
          document.querySelectorAll("#progress span").forEach((dot) => {
            const i = STEPS.indexOf(dot.dataset.step);
            dot.classList.toggle("done", idx >= 0 && i < idx);
            dot.classList.toggle("active", idx >= 0 && i === idx);
          });
          $("progress").classList.toggle("hidden", name === "final");
          window.scrollTo({ top: 0, behavior: "smooth" });
        },
      };
```

- [ ] **Step 5: JS — módulo `Tts` (voz + rate persistido + callbacks de habla)**

```javascript
      // ---- TTS: voces en inglés, rate en localStorage, callbacks para animar el óvalo ----
      const Tts = {
        voices: [],
        load() {
          this.voices = speechSynthesis.getVoices().filter((v) => v.lang.startsWith("en"));
          const sel = $("voice");
          const saved = localStorage.getItem("pilot_voice");
          sel.innerHTML = "";
          this.voices.forEach((v, i) => {
            const opt = document.createElement("option");
            opt.value = String(i);
            opt.textContent = `${v.name} (${v.lang})`;
            sel.appendChild(opt);
          });
          if (saved !== null && this.voices[Number(saved)]) sel.value = saved;
          const rate = localStorage.getItem("pilot_rate");
          if (rate) { $("rate").value = rate; $("rate-value").textContent = Number(rate).toFixed(2); }
        },
        speak(text, { onstart, onboundary, onend } = {}) {
          if (!text) { onend && onend(); return; }
          speechSynthesis.cancel();
          const u = new SpeechSynthesisUtterance(text);
          const v = this.voices[Number($("voice").value)] || null;
          if (v) u.voice = v;
          u.lang = v ? v.lang : "en-US";
          u.rate = Number($("rate").value);
          if (onstart) u.onstart = onstart;
          if (onboundary) u.onboundary = onboundary;
          u.onend = () => onend && onend();
          speechSynthesis.speak(u);
        },
      };
```

- [ ] **Step 6: JS — orquestación del Paso 1 (Voz) + arranque**

```javascript
      // ---- Paso 1: Voz ----
      $("rate").addEventListener("input", () => {
        const v = Number($("rate").value);
        $("rate-value").textContent = v.toFixed(2);
        localStorage.setItem("pilot_rate", String(v));
      });
      $("voice").addEventListener("change", () =>
        localStorage.setItem("pilot_voice", $("voice").value)
      );
      $("voice-test").addEventListener("click", () =>
        Tts.speak("Hi! Let's practice English together. Ready when you are.")
      );
      $("voice-next").addEventListener("click", () => Stepper.go("context"));

      // ---- init ----
      Tts.load();
      speechSynthesis.onvoiceschanged = () => Tts.load();
      Stepper.go("voice");
```

- [ ] **Step 7: Verificar sintaxis del JS**

Run: `` sed -n '/<script>/,/<\/script>/p' app/web/index.html | sed '1d;$d' > "$CLAUDE_JOB_DIR/tmp/frontend.js" && node --check "$CLAUDE_JOB_DIR/tmp/frontend.js" ``
Expected: sin salida (sintaxis OK). Si `node` no está, usar `python -c "import esprima"` no aplica; en su defecto, revisar el balance de llaves a ojo y confiar en la QA de navegador.

- [ ] **Step 8: QA en navegador (Claude in Chrome)**

Levantar la app (según el compose/README del proyecto) y abrir la raíz. Verificar:
- Se ve el indicador de progreso con el primer punto activo y el Paso 1 "La voz de tu tutor".
- El `<select>` de voces se llena con voces en inglés; mover el rate actualiza el número y persiste al recargar.
- "Probar voz" reproduce el TTS. "Continuar" pasa al Paso 2 (aún vacío) y avanza el progreso.
- En `localStorage` existe `pilot_user_id` (UUID). Estética: fondo crema, tarjeta ivory, título en serif Fraunces, botón dorado, foco visible al tabular.
- Responsive: a ~360px de ancho no hay scroll horizontal.

- [ ] **Step 9: Commit**

```bash
git add app/web/index.html
git commit -m "feat(web): shell del stepper + tokens crema/dorado + identidad + cliente API + Paso Voz"
```

---

### Task 2: Paso 2 (Contexto) + shell del Paso 3 + óvalo tutor con animación de voz

**Files:**
- Modify: `app/web/index.html` (llena `#step-context` y `#step-talk`; agrega CSS del óvalo y el módulo `Oval`; conecta el dictado del contexto)

**Interfaces:**
- Consumes: `Stepper`, `Tts`, `Identity`.
- Produces:
  - `Oval.idle()`, `Oval.speaking()`, `Oval.pulse()`, `Oval.recording()`, `Oval.quiet()` — cambian el estado visual del óvalo.
  - Contenido del Paso 2 (textarea `#ctx-content` + botón dictar) y del Paso 3 (óvalo, pregunta, botones hablar/detener, contador).

- [ ] **Step 1: CSS del óvalo tutor (agregar al `<style>`)**

```css
      .stage { display: flex; flex-direction: column; align-items: center; gap: 22px; padding: 8px 0 4px; }
      .oval {
        width: 132px; height: 168px; border-radius: 50%;
        background: radial-gradient(ellipse at 50% 38%, #d9bd77, var(--gold));
        box-shadow: 0 10px 30px rgba(184,150,63,.28);
        animation: breathe 4.5s ease-in-out infinite;
        transition: transform .12s ease, box-shadow .3s ease, filter .3s ease;
      }
      .oval.speaking { box-shadow: 0 0 0 10px rgba(184,150,63,.12), 0 12px 34px rgba(184,150,63,.4); }
      .oval.beat { transform: scale(1.06); }
      .oval.recording {
        background: var(--ivory); border: 2px solid var(--gold-soft);
        box-shadow: 0 0 0 8px rgba(110,139,106,.12); animation: ring 1.8s ease-in-out infinite;
      }
      @keyframes breathe { 0%,100% { transform: scale(1); } 50% { transform: scale(1.03); } }
      @keyframes ring { 0%,100% { box-shadow: 0 0 0 6px rgba(110,139,106,.10); } 50% { box-shadow: 0 0 0 12px rgba(110,139,106,.18); } }
      .counter { font-family: var(--serif); font-size: 1.1rem; color: var(--muted); min-height: 1.4em; }
```

- [ ] **Step 2: Módulo `Oval` (JS)**

```javascript
      // ---- Óvalo tutor: reposo / hablando (pulsa con la voz) / grabando ----
      const Oval = {
        el: null,
        init() { this.el = $("oval"); },
        idle() { this.el.className = "oval"; },
        speaking() { this.el.className = "oval speaking"; },
        pulse() {
          // Un latido por cada límite de palabra del TTS (onboundary).
          this.el.classList.add("beat");
          setTimeout(() => this.el && this.el.classList.remove("beat"), 130);
        },
        recording() { this.el.className = "oval recording"; },
      };
```

- [ ] **Step 3: Contenido del Paso 2 (Contexto) — HTML inyectado o markup directo**

Poner este markup como innerHTML de `#step-context` (o escribirlo directo en el HTML de esa sección):

```html
        <h2>¿Sobre qué quieres hablar?</h2>
        <p class="lead">Pega tu CV, un texto o el tema a practicar y qué te gustaría mejorar. El tutor hará 5 preguntas basadas en esto.</p>
        <label for="ctx-content">Tu contexto</label>
        <textarea id="ctx-content" rows="6" placeholder="Ej: Soy desarrollador y tengo una entrevista en inglés. Quiero practicar hablar sobre mi experiencia y mejorar mi pronunciación."></textarea>
        <div class="row">
          <button id="ctx-dictate" type="button" class="ghost small">Dictar por voz</button>
          <span id="ctx-status" class="status"></span>
        </div>
        <div class="row">
          <button id="ctx-back" type="button" class="ghost">Atrás</button>
          <button id="ctx-start" type="button">Empezar la práctica</button>
          <span id="ctx-error" class="error hidden"></span>
        </div>
```

- [ ] **Step 4: Contenido del Paso 3 (Práctica) — shell con óvalo**

Markup de `#step-talk`:

```html
        <div class="stage">
          <div id="oval" class="oval"></div>
          <div id="counter" class="counter"></div>
        </div>
        <p id="question" class="question" style="text-align:center; font-size:1.3rem; margin:10px 0 0"></p>
        <p id="heard" class="muted" style="text-align:center; min-height:1.2em"></p>
        <div class="row" style="justify-content:center">
          <button id="repeat" type="button" class="ghost small">Repetir pregunta</button>
          <button id="talk-btn" type="button">Responder</button>
        </div>
        <div id="talk-error" class="error hidden" style="text-align:center"></div>
```

- [ ] **Step 5: Dictado del contexto (reutiliza `SpeechRecognition`) + navegación del Paso 2**

```javascript
      // ---- Paso 2: dictado opcional del contexto + navegación ----
      const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
      $("ctx-back") && $("ctx-back").addEventListener("click", () => Stepper.go("voice"));
      $("ctx-dictate") && $("ctx-dictate").addEventListener("click", () => {
        if (!SR) { $("ctx-status").textContent = "Tu navegador no permite dictar (usa Chrome)."; return; }
        const rec = new SR();
        rec.lang = "es-ES"; rec.interimResults = false; rec.continuous = true;
        const box = $("ctx-content");
        $("ctx-status").textContent = "Escuchando… habla y para cuando termines.";
        rec.onresult = (e) => {
          for (let i = e.resultIndex; i < e.results.length; i++)
            if (e.results[i].isFinal) box.value += (box.value ? " " : "") + e.results[i][0].transcript;
        };
        rec.onend = () => { $("ctx-status").textContent = ""; };
        rec.onerror = () => { $("ctx-status").textContent = ""; };
        rec.start();
      });
```

(El botón "Empezar la práctica" (`#ctx-start`) se conecta en la Task 3, que trae el flujo de `/start`.)

- [ ] **Step 6: Enganchar el óvalo a la voz del agente en `Tts` — helper `speakAsTutor`**

```javascript
      // Habla una pregunta como el tutor: el óvalo pulsa mientras dura la voz.
      function speakAsTutor(text) {
        Oval.speaking();
        Tts.speak(text, {
          onboundary: () => Oval.pulse(),
          onend: () => Oval.idle(),
        });
      }
```

- [ ] **Step 7: `Oval.init()` en el arranque**

Agregar `Oval.init();` en la sección `// ---- init ----` (después de `Tts.load()`), y una demostración temporal: al entrar al Paso 3 se verá en reposo. (El flujo real que llama a `speakAsTutor` llega en la Task 3.)

- [ ] **Step 8: Verificar sintaxis**

Run: `` sed -n '/<script>/,/<\/script>/p' app/web/index.html | sed '1d;$d' > "$CLAUDE_JOB_DIR/tmp/frontend.js" && node --check "$CLAUDE_JOB_DIR/tmp/frontend.js" ``
Expected: sin salida.

- [ ] **Step 9: QA en navegador**

- Paso 2: textarea de contexto se ve; "Dictar por voz" pide permiso de micrófono y agrega texto; "Atrás" vuelve al Paso 1.
- Forzar mostrar el Paso 3 (en consola: `Stepper.go('talk')`): el óvalo dorado respira (reposo). En consola: `Oval.recording()` lo pasa a anillo neutro; `speakAsTutor('Hello, how are you today?')` lo hace pulsar mientras habla y volver a reposo al terminar.
- Con `prefers-reduced-motion` activo (DevTools → Rendering), el óvalo no anima.

- [ ] **Step 10: Commit**

```bash
git add app/web/index.html
git commit -m "feat(web): Paso Contexto + shell del Paso Practica + ovalo tutor animado con la voz"
```

---

### Task 3: Lógica del Paso 3 — grabación WAV + reconocimiento + 30 s + `/start` y `/answer`

**Files:**
- Modify: `app/web/index.html` (módulo `Recorder`, flujo de `/conversation/start` con banner de pausa/cuota, y `/conversation/answer` multipart; contador de 30 s)

**Interfaces:**
- Consumes: `Api`, `Oval`, `Tts`/`speakAsTutor`, `Stepper`, `Identity`.
- Produces:
  - `Recorder.start()` / `Recorder.stop()` — graba WAV (AudioContext) + transcript (SpeechRecognition) en paralelo; a los 30 s se auto-detiene.
  - `encodeWav(samples, sampleRate) -> Blob` (PCM 16-bit mono).
  - Flujo: `beginConversation()` (POST /start) y `sendAnswer(wavBlob, transcript)` (POST /answer multipart).
  - `showBanner(reason)` para 429.

- [ ] **Step 1: `encodeWav` + captura de audio (AudioContext) en el módulo `Recorder`**

```javascript
      // ---- Grabación: WAV PCM 16-bit mono vía AudioContext, en paralelo al reconocimiento ----
      function floatTo16BitPCM(view, offset, input) {
        for (let i = 0; i < input.length; i++, offset += 2) {
          const s = Math.max(-1, Math.min(1, input[i]));
          view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
        }
      }
      function encodeWav(samples, sampleRate) {
        const buffer = new ArrayBuffer(44 + samples.length * 2);
        const view = new DataView(buffer);
        const writeStr = (off, str) => { for (let i = 0; i < str.length; i++) view.setUint8(off + i, str.charCodeAt(i)); };
        writeStr(0, "RIFF"); view.setUint32(4, 36 + samples.length * 2, true); writeStr(8, "WAVE");
        writeStr(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
        view.setUint16(22, 1, true); view.setUint32(24, sampleRate, true);
        view.setUint32(28, sampleRate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
        writeStr(36, "data"); view.setUint32(40, samples.length * 2, true);
        floatTo16BitPCM(view, 44, samples);
        return new Blob([view], { type: "audio/wav" });
      }

      const Recorder = {
        audioCtx: null, source: null, processor: null, stream: null,
        chunks: [], sampleRate: 16000, recognition: null, transcript: "",
        timerId: null, secondsLeft: 30, onDone: null,

        async start(onDone) {
          this.onDone = onDone; this.chunks = []; this.transcript = "";
          this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
          this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
          this.sampleRate = this.audioCtx.sampleRate;
          this.source = this.audioCtx.createMediaStreamSource(this.stream);
          this.processor = this.audioCtx.createScriptProcessor(4096, 1, 1);
          this.processor.onaudioprocess = (e) => {
            this.chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
          };
          this.source.connect(this.processor);
          this.processor.connect(this.audioCtx.destination);
          this._startRecognition();
          this._startTimer();
          Oval.recording();
        },

        _startRecognition() {
          if (!SR) return; // sin reconocimiento se envía audio con transcript vacío -> el backend valida
          const rec = new SR();
          rec.lang = "en-US"; rec.continuous = true; rec.interimResults = true;
          let acc = "";
          rec.onresult = (e) => {
            let interim = "";
            for (let i = e.resultIndex; i < e.results.length; i++) {
              const t = e.results[i][0].transcript;
              if (e.results[i].isFinal) acc += t + " "; else interim += t;
            }
            this.transcript = acc.trim();
            $("heard").textContent = (acc + interim).trim();
          };
          rec.onend = () => { if (this._recording) { try { rec.start(); } catch (_) {} } };
          rec.onerror = () => {};
          this.recognition = rec; this._recording = true;
          try { rec.start(); } catch (_) {}
        },

        _startTimer() {
          this.secondsLeft = 30;
          $("counter").textContent = "0:30";
          this.timerId = setInterval(() => {
            this.secondsLeft -= 1;
            $("counter").textContent = "0:" + String(this.secondsLeft).padStart(2, "0");
            if (this.secondsLeft <= 0) this.stop();
          }, 1000);
        },

        async stop() {
          if (!this.audioCtx) return;
          clearInterval(this.timerId); this.timerId = null;
          this._recording = false;
          $("counter").textContent = "";
          try { this.recognition && this.recognition.stop(); } catch (_) {}
          this.processor.disconnect(); this.source.disconnect();
          this.stream.getTracks().forEach((t) => t.stop());
          // Aplanar chunks a un solo Float32Array.
          const len = this.chunks.reduce((n, c) => n + c.length, 0);
          const samples = new Float32Array(len);
          let off = 0; for (const c of this.chunks) { samples.set(c, off); off += c.length; }
          await this.audioCtx.close(); this.audioCtx = null;
          const wav = encodeWav(samples, this.sampleRate);
          Oval.idle();
          this.onDone && this.onDone(wav, this.transcript);
        },
      };
```

Nota: `createScriptProcessor` está deprecado pero es el camino más simple y con mejor soporte para capturar PCM sin un AudioWorklet aparte; suficiente para el piloto.

- [ ] **Step 2: Banner de pausa / cuota**

```javascript
      function showBanner(reason) {
        $("app").classList.add("hidden");
        $("banner").classList.remove("hidden");
        if (reason === "quota") {
          $("banner-title").textContent = "Llegaste al límite de la demo";
          $("banner-text").textContent = "Ya usaste tus conversaciones de práctica. ¡Gracias por probarla!";
        } else {
          $("banner-title").textContent = "En pausa por el momento";
          $("banner-text").textContent = "La demo está descansando. Vuelve a intentarlo más tarde.";
        }
      }
```

- [ ] **Step 3: Iniciar conversación (POST /start) — conecta `#ctx-start`**

```javascript
      let conversationId = null;

      $("ctx-start") && $("ctx-start").addEventListener("click", async () => {
        const err = $("ctx-error");
        err.classList.add("hidden");
        const user_context = $("ctx-content").value.trim();
        if (!user_context) { err.textContent = "Escribe un contexto para empezar."; err.classList.remove("hidden"); return; }
        const btn = $("ctx-start"); btn.disabled = true; btn.textContent = "Preparando…";
        try {
          const data = await Api.request("POST", "/conversation/start", { json: { user_context } });
          conversationId = data.conversation_id;
          Stepper.go("talk");
          setQuestion(data.question);
        } catch (e) {
          if (e instanceof ApiError && e.status === 429) { showBanner(e.reason); return; }
          err.textContent = e.message; err.classList.remove("hidden");
        } finally {
          btn.disabled = false; btn.textContent = "Empezar la práctica";
        }
      });

      function setQuestion(text) {
        $("question").textContent = text;
        $("heard").textContent = "";
        speakAsTutor(text);
      }
      $("repeat").addEventListener("click", () => speakAsTutor($("question").textContent));
```

- [ ] **Step 4: Responder (grabar → enviar multipart a /answer) — conecta `#talk-btn`**

```javascript
      let recording = false;
      $("talk-btn").addEventListener("click", async () => {
        const btn = $("talk-btn");
        if (recording) { recording = false; btn.disabled = true; await Recorder.stop(); return; }
        $("talk-error").classList.add("hidden");
        try {
          await Recorder.start(sendAnswer);
          recording = true; btn.textContent = "Detener";
        } catch (_) {
          $("talk-error").textContent = "No pudimos usar el micrófono. Revisa los permisos.";
          $("talk-error").classList.remove("hidden");
        }
      });

      async function sendAnswer(wavBlob, transcript) {
        const btn = $("talk-btn");
        btn.textContent = "Responder"; btn.disabled = false; recording = false;
        $("heard").textContent = "";
        const form = new FormData();
        form.append("conversation_id", conversationId);
        form.append("transcript", transcript || "");
        form.append("audio", wavBlob, "answer.wav");
        try {
          const data = await Api.request("POST", "/conversation/answer", { form });
          if (data.final) showFinal(data.final);   // showFinal llega en la Task 4
          else setQuestion(data.question);
        } catch (e) {
          if (e instanceof ApiError && e.status === 429) { showBanner(e.reason); return; }
          $("talk-error").textContent = e.message;
          $("talk-error").classList.remove("hidden");
        }
      }
```

(En esta task, `showFinal` puede no existir aún; dejar una definición temporal `function showFinal(f){ console.log('final', f); }` que la Task 4 reemplaza. Documentarlo en el commit.)

- [ ] **Step 5: Verificar sintaxis**

Run: `` sed -n '/<script>/,/<\/script>/p' app/web/index.html | sed '1d;$d' > "$CLAUDE_JOB_DIR/tmp/frontend.js" && node --check "$CLAUDE_JOB_DIR/tmp/frontend.js" ``
Expected: sin salida.

- [ ] **Step 6: QA en navegador (con backend vivo si se puede; si no, stub de `fetch`)**

Con backend (Gemini + idealmente Azure) o con un stub que devuelva `{conversation_id, question}` y luego `{question}`/`{final}`:
- "Empezar la práctica" con contexto pasa al Paso 3 y el óvalo pulsa mientras lee la 1ª pregunta.
- "Responder" pide micrófono, el óvalo pasa a anillo, el contador baja desde 0:30; "Detener" (o llegar a 0) manda la respuesta y llega la siguiente pregunta.
- El request a `/conversation/answer` va como `multipart/form-data` con `audio` (Blob wav), `transcript`, `conversation_id` (verificar en la pestaña Network) y lleva el header `X-User-Id`.
- Stub que responda 429 `{"detail":{"reason":"paused"}}` en `/start` → aparece el banner "En pausa por el momento"; con `reason:"quota"` → mensaje de límite.

- [ ] **Step 7: Commit**

```bash
git add app/web/index.html
git commit -m "feat(web): grabacion WAV + contador 30s + /start y /answer multipart + banner pausa/cuota"
```

---

### Task 4: Pantalla final — feedback + scores de Azure + palabras + frases + formulario de feedback

**Files:**
- Modify: `app/web/index.html` (contenido de `#step-final`, `showFinal`, render de scores/palabras/frases, formulario de feedback → POST /feedback, reiniciar)

**Interfaces:**
- Consumes: `Api`, `Tts`, `Stepper`.
- Produces: `showFinal(final)` (reemplaza el temporal), envío del formulario a `POST /feedback`.

- [ ] **Step 1: Markup de `#step-final`**

```html
        <h1>Tu resultado</h1>
        <div id="scores" class="scores hidden"></div>
        <div id="feedback" class="prose"></div>

        <div id="words-block" class="hidden">
          <h2 style="margin-top:26px">Palabras para practicar</h2>
          <p class="muted">Toca una palabra para escucharla.</p>
          <div id="words"></div>
        </div>

        <div id="phrases-block" class="hidden">
          <h2 style="margin-top:26px">Frases más naturales</h2>
          <div id="phrases"></div>
        </div>

        <section class="card" style="margin-top:28px">
          <h2>¿Qué te pareció?</h2>
          <div class="row" id="fb-like" style="gap:8px">
            <button type="button" class="ghost small" data-like="true">👍 Me gustó</button>
            <button type="button" class="ghost small" data-like="false">👎 No mucho</button>
          </div>
          <label>Del 1 al 5</label>
          <div class="row" id="fb-stars" style="gap:6px; margin-top:6px"></div>
          <label for="fb-comment">Comentario (opcional)</label>
          <textarea id="fb-comment" rows="3" placeholder="¿Qué mejorarías?"></textarea>
          <label>¿Te interesarían más funciones?</label>
          <div class="row" id="fb-more" style="gap:8px">
            <button type="button" class="ghost small" data-more="true">Sí</button>
            <button type="button" class="ghost small" data-more="false">No</button>
          </div>
          <label for="fb-suggestions">¿Cuáles?</label>
          <input id="fb-suggestions" type="text" placeholder="Ej: ejercicios de gramática" />
          <div class="row">
            <button id="fb-send" type="button">Enviar feedback</button>
            <span id="fb-status" class="status"></span>
          </div>
        </section>

        <div class="row" style="justify-content:center; margin-top:26px">
          <button id="restart" type="button" class="ghost">Practicar de nuevo</button>
        </div>
```

- [ ] **Step 2: CSS de scores/palabras/frases/prose (agregar al `<style>`)**

```css
      .scores { display: flex; flex-wrap: wrap; gap: 12px; margin: 8px 0 22px; }
      .score { flex: 1 1 90px; text-align: center; background: var(--ivory); border: 1px solid var(--gold-soft); border-radius: 12px; padding: 14px 8px; }
      .score b { font-family: var(--serif); font-size: 1.6rem; display: block; }
      .score.high b { color: var(--sage); }
      .score small { color: var(--muted); }
      .prose { white-space: pre-wrap; }
      .pill { display: inline-block; margin: 4px 8px 0 0; padding: 8px 14px; border-radius: 999px; border: 1px solid var(--gold-soft); background: var(--ivory); color: var(--ink); cursor: pointer; font-size: .92rem; }
      .phrase { margin: 10px 0; padding-left: 14px; border-left: 3px solid var(--gold); }
      .phrase del { color: #b4402f; text-decoration: line-through; } .phrase ins { color: var(--sage); text-decoration: none; }
      button.on { background: var(--gold); color: #fff; border-color: var(--gold); }
```

- [ ] **Step 3: `showFinal` — feedback + scores (Azure) + palabras + frases**

```javascript
      const SCORE_LABELS = { pronunciation: "Pronunciación", accuracy: "Precisión", fluency: "Fluidez", prosody: "Prosodia" };

      function showFinal(final) {
        Stepper.go("final");
        $("feedback").textContent = final.content_feedback || "";

        // Scores de Azure (pueden faltar: pronunciation === null).
        const scoresEl = $("scores"); scoresEl.innerHTML = "";
        const pron = final.pronunciation;
        if (pron && pron.scores) {
          Object.entries(SCORE_LABELS).forEach(([key, label]) => {
            const val = pron.scores[key];
            if (val == null) return;
            const div = document.createElement("div");
            div.className = "score" + (val >= 80 ? " high" : "");
            div.innerHTML = `<b>${Math.round(val)}</b><small>${label}</small>`;
            scoresEl.appendChild(div);
          });
          scoresEl.classList.remove("hidden");
        } else {
          scoresEl.classList.add("hidden");
        }

        renderWords(final.practice_words || []);
        renderPhrases(final.practice_phrases || []);
      }

      function renderWords(words) {
        const block = $("words-block"), el = $("words"); el.innerHTML = "";
        if (!words.length) { block.classList.add("hidden"); return; }
        words.forEach((w) => {
          const b = document.createElement("button");
          b.className = "pill";
          b.textContent = w.hint ? `${w.word} · ${w.hint}` : w.word;
          b.onclick = () => Tts.speak(w.present || w.word);
          el.appendChild(b);
        });
        block.classList.remove("hidden");
      }

      function renderPhrases(phrases) {
        const block = $("phrases-block"), el = $("phrases"); el.innerHTML = "";
        if (!phrases.length) { block.classList.add("hidden"); return; }
        phrases.forEach((p) => {
          const div = document.createElement("div"); div.className = "phrase";
          const line = document.createElement("div");
          const del = document.createElement("del"); del.textContent = p.original;
          const ins = document.createElement("ins"); ins.textContent = " → " + p.suggestion;
          line.append(del, ins); div.appendChild(line);
          if (p.note) { const n = document.createElement("div"); n.className = "muted"; n.textContent = p.note; div.appendChild(n); }
          el.appendChild(div);
        });
        block.classList.remove("hidden");
      }
```

- [ ] **Step 4: Formulario de feedback (toggles + POST /feedback) + reiniciar**

```javascript
      // ---- Formulario de feedback ----
      const fb = { liked: null, rating: null, wants_more: null };

      function wireToggle(containerId, attr, key) {
        const box = $(containerId);
        box.querySelectorAll("button").forEach((btn) => {
          btn.addEventListener("click", () => {
            const val = btn.getAttribute(attr) === "true";
            fb[key] = val;
            box.querySelectorAll("button").forEach((b) => b.classList.remove("on"));
            btn.classList.add("on");
          });
        });
      }
      wireToggle("fb-like", "data-like", "liked");
      wireToggle("fb-more", "data-more", "wants_more");

      // Estrellas 1..5
      const starsEl = $("fb-stars");
      for (let i = 1; i <= 5; i++) {
        const b = document.createElement("button");
        b.type = "button"; b.className = "ghost small"; b.textContent = "★"; b.dataset.v = String(i);
        b.addEventListener("click", () => {
          fb.rating = i;
          starsEl.querySelectorAll("button").forEach((s) => s.classList.toggle("on", Number(s.dataset.v) <= i));
        });
        starsEl.appendChild(b);
      }

      $("fb-send").addEventListener("click", async () => {
        const status = $("fb-status"); status.textContent = "Enviando…";
        try {
          await Api.request("POST", "/feedback", { json: {
            liked: fb.liked, rating: fb.rating, wants_more: fb.wants_more,
            comment: $("fb-comment").value.trim(), suggestions: $("fb-suggestions").value.trim(),
          }});
          status.textContent = "¡Gracias! 🙏";
          $("fb-send").disabled = true;
        } catch (e) { status.textContent = "No se pudo enviar: " + e.message; }
      });

      $("restart").addEventListener("click", () => {
        conversationId = null;
        $("ctx-content").value = "";
        Stepper.go("context");
      });
```

- [ ] **Step 5: Verificar sintaxis**

Run: `` sed -n '/<script>/,/<\/script>/p' app/web/index.html | sed '1d;$d' > "$CLAUDE_JOB_DIR/tmp/frontend.js" && node --check "$CLAUDE_JOB_DIR/tmp/frontend.js" ``
Expected: sin salida.

- [ ] **Step 6: QA en navegador — flujo completo**

Con backend vivo (o stub de `/answer` que devuelva un `final` con `pronunciation.scores`, `practice_words`, `practice_phrases`):
- Al terminar las 5 preguntas aparece la pantalla final: título serif, tarjetas de score (Azure) con el número grande, feedback en Markdown-ish (texto), palabras como pills que suenan al tocarlas, frases con original→sugerencia.
- Si `pronunciation` es `null`, NO aparece el bloque de scores pero sí el resto.
- Formulario: like/dislike y "¿más funciones?" marcan un botón (estado `.on`); estrellas se llenan hasta la elegida; "Enviar feedback" hace `POST /feedback` con `X-User-Id` (verificar en Network) y muestra "¡Gracias!".
- "Practicar de nuevo" vuelve al Paso 2 con el contexto limpio (misma identidad; la cuota se consume en el backend).

- [ ] **Step 7: Commit**

```bash
git add app/web/index.html
git commit -m "feat(web): pantalla final (feedback + scores Azure + palabras + frases) + formulario de feedback"
```

---

## Notas para el que ejecute

- Es un solo archivo (`app/web/index.html`), servido estático por `app/cmd/server.py` (ya montado). No hay build.
- No se testea con pytest (es frontend): la verificación es `node --check` del script extraído + QA en navegador. Si Claude in Chrome no puede levantar el backend, usar stubs de `fetch` (documentados en cada checklist) para validar render y flujo; dejar constancia en el reporte de qué se verificó con backend real y qué con stub.
- `createScriptProcessor` está deprecado pero es lo más simple y compatible para capturar PCM; migrar a `AudioWorklet` es una mejora futura, no del piloto.
- La **cuota** se aplica en el backend (3 conversaciones por `X-User-Id`); "Practicar de nuevo" consume una nueva. Al agotarse, `/start` devuelve 429 `quota` y se ve el mensaje de límite.
- Fraunces se carga de Google Fonts con `display=swap` y fallback a Georgia/serif: si no hay red, la página se ve con el fallback serif sin romperse.
- Con esto el piloto queda completo end-to-end: identidad → límites → conversación con audio → scoring de Azure → feedback → formulario.
