# Práctica de lectura — Fase 1: cimientos

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Dejar listos los tres cimientos de la práctica de lectura —la tabla `reading_texts`, el frontend servido con plantillas Jinja2, y el JavaScript común extraído a `shared.js`— sin construir todavía el scraping, los endpoints ni la pantalla nueva.

**Architecture:** La tabla se suma al DDL que ya vive duplicado en `app/storage.py` y `docker/initdb/`. El frontend deja de servirse como archivo estático suelto y pasa a plantillas: `base.html` concentra el `<head>`, los estilos y el banner; la página actual hereda de él. El JavaScript que hoy está inline y que la futura pantalla de lectura va a necesitar (identidad, cliente API, grabación WAV, render de palabras) se extrae a `static/shared.js`, desacoplándolo de los elementos del DOM propios de la conversación mediante callbacks.

**Tech Stack:** Python 3.11+, FastAPI, Jinja2, psycopg 3, Postgres 17, pytest, uv.

## Global Constraints

- Toda variable de entorno se declara y se lee **solo** en `config.py`. Ningún `os.getenv` fuera de ahí.
- Todo I/O de red usa librerías asíncronas (`httpx.AsyncClient`) y endpoints `async def`. Los SDK bloqueantes van dentro de `asyncio.to_thread`. (En esta fase no hay I/O de red nuevo, pero la regla aplica a todo lo que se agregue.)
- El DDL vive duplicado en `app/storage.py` (`_SCHEMA`) y `docker/initdb/*.sql`. Todo cambio de esquema toca **ambos** o divergen.
- `psycopg` ejecuta **una sentencia por llamada a `execute()`**: cada `CREATE TABLE` y cada `CREATE INDEX` es un elemento separado de la tupla `_SCHEMA`.
- Los tests corren con `uv run pytest` desde la raíz del repo y **no tocan la red ni una BD viva**.
- Los comentarios del código se escriben en español, explicando el *por qué*, siguiendo el estilo de los módulos existentes.
- Fuera de alcance en esta fase: scraping de Engoo, `reading_starts`, endpoints `/reading/*`, pantalla de lectura, `assess_scripted`. No los implementes aunque el spec los describa.

**Spec de referencia:** `docs/superpowers/specs/2026-08-06-practica-lectura-design.md`

---

## File Structure

| Archivo | Responsabilidad | Acción |
|---|---|---|
| `app/storage.py` | DDL del esquema de `app/` | Modificar: sumar `reading_texts` + índice a `_SCHEMA` |
| `docker/initdb/04-reading-texts.sql` | Misma DDL para el init del contenedor | Crear |
| `test_app_reading_texts.py` | Verifica que el esquema y el `.sql` coinciden | Crear |
| `app/web/templates/base.html` | Esqueleto común: `<head>`, banner, bloques | Crear |
| `app/web/templates/index.html` | Página de conversación; hereda de `base.html` | Crear (migrada desde `app/web/index.html`) |
| `app/web/static/app.css` | Estilos comunes | Crear (movidos desde el `<style>` inline) |
| `app/web/static/shared.js` | JS reutilizable: identidad, API, grabación, render de palabras | Crear |
| `app/cmd/server.py` | Montaje de estáticos y render de plantillas | Modificar: líneas 41 y 332-334 |
| `test_app_web.py` | Smoke tests de que la página y los estáticos se sirven | Crear |
| `pyproject.toml` | Dependencias | Modificar: sumar `jinja2` |
| `app/web/index.html` | Página estática original | Borrar al final de la Task 2 |

---

## Task 1: Tabla `reading_texts`

**Files:**
- Modify: `app/storage.py:20-63` (la tupla `_SCHEMA`)
- Create: `docker/initdb/04-reading-texts.sql`
- Test: `test_app_reading_texts.py`

**Interfaces:**
- Consumes: nada.
- Produces: la tabla `reading_texts` con columnas `id, created_at, updated_at, source, source_url, title, level, category, published_at, body`. La fase 2 la consumirá desde `app/reading/repository.py` con `INSERT ... ON CONFLICT (source_url) DO UPDATE` y un `SELECT ... ORDER BY random() LIMIT 1`.

- [ ] **Step 1: Escribir el test que falla**

Crear `test_app_reading_texts.py`:

```python
"""Verifica el DDL de reading_texts: que esté en el esquema de código y que el .sql del
contenedor no haya divergido. El DDL vive duplicado a propósito (app/storage.py para uso
standalone, docker/initdb para el arranque del contenedor); estos tests son la red que
detecta que uno de los dos se quedó atrás."""

from pathlib import Path

from app.storage import _SCHEMA

_INITDB_SQL = Path(__file__).parent / "docker" / "initdb" / "04-reading-texts.sql"

# Columnas que la fase 2 necesita para ingerir y servir textos.
_COLUMNS = (
    "created_at",
    "updated_at",
    "source",
    "source_url",
    "title",
    "level",
    "category",
    "published_at",
    "body",
)


def test_schema_includes_reading_texts():
    schema_sql = " ".join(_SCHEMA)
    assert "reading_texts" in schema_sql
    for column in _COLUMNS:
        assert column in schema_sql, f"falta la columna {column}"


def test_source_url_is_unique():
    """La unicidad de source_url es lo que hace idempotente al job de ingesta."""
    schema_sql = " ".join(_SCHEMA)
    assert "source_url   TEXT NOT NULL UNIQUE" in schema_sql


def test_level_is_nullable():
    """level debe admitir NULL: 'no sé el nivel' y 'nivel 0' son cosas distintas."""
    schema_sql = " ".join(_SCHEMA)
    assert "level        INTEGER," in schema_sql


def test_schema_has_index_as_separate_statement():
    """psycopg ejecuta una sentencia por execute(): el índice va en su propio elemento."""
    index_statements = [s for s in _SCHEMA if "CREATE INDEX" in s]
    assert len(index_statements) == 1
    assert "reading_texts_level_idx" in index_statements[0]


def test_initdb_sql_matches_schema():
    sql = _INITDB_SQL.read_text()
    assert "CREATE TABLE IF NOT EXISTS reading_texts" in sql
    assert "reading_texts_level_idx" in sql
    for column in _COLUMNS:
        assert column in sql, f"falta la columna {column} en el .sql del contenedor"
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `uv run pytest test_app_reading_texts.py -v`
Expected: FAIL — `assert "reading_texts" in schema_sql` falla, y `test_initdb_sql_matches_schema` falla con `FileNotFoundError`.

- [ ] **Step 3: Agregar la tabla a `_SCHEMA`**

En `app/storage.py`, dentro de la tupla `_SCHEMA`, después del bloque de `pilot_feedback` y antes del `)` que la cierra, agregar estos dos elementos:

```python
    """
    CREATE TABLE IF NOT EXISTS reading_texts (
        id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        source       TEXT NOT NULL,
        source_url   TEXT NOT NULL UNIQUE,
        title        TEXT NOT NULL,
        level        INTEGER,
        category     TEXT NOT NULL DEFAULT '',
        published_at TEXT NOT NULL DEFAULT '',
        body         TEXT NOT NULL
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS reading_texts_level_idx ON reading_texts (level);
    """,
```

- [ ] **Step 4: Crear el `.sql` del contenedor**

Crear `docker/initdb/04-reading-texts.sql`:

```sql
-- Catálogo de textos de lectura (app/reading). Se puebla con un job de ingesta desde
-- fuentes externas; acá solo se crea la estructura.
-- Postgres ejecuta los .sql de docker-entrypoint-initdb.d una sola vez, al crear el volumen.
-- Debe coincidir con el DDL de PostgresStorage.init_schema() (app/storage.py).

CREATE TABLE IF NOT EXISTS reading_texts (
    id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    source       TEXT NOT NULL,            -- qué scraper lo trajo, p.ej. 'engoo'
    source_url   TEXT NOT NULL UNIQUE,     -- clave natural: hace idempotente la ingesta
    title        TEXT NOT NULL,
    level        INTEGER,                  -- 1..9 en Engoo; NULL si la fuente no lo informa
    category     TEXT NOT NULL DEFAULT '',
    published_at TEXT NOT NULL DEFAULT '', -- fecha tal como la publica la fuente
    body         TEXT NOT NULL             -- artículo COMPLETO e intacto
);

-- El filtro por rango de nivel es la consulta principal al servir un texto al azar.
CREATE INDEX IF NOT EXISTS reading_texts_level_idx ON reading_texts (level);
```

- [ ] **Step 5: Correr los tests para verificar que pasan**

Run: `uv run pytest test_app_reading_texts.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Verificar que no se rompió nada**

Run: `uv run pytest -q`
Expected: PASS — misma cantidad de tests que antes, más los 5 nuevos.

- [ ] **Step 7: Verificar contra un Postgres real**

Run: `docker compose down -v && docker compose up -d db && sleep 8 && docker compose exec -T db psql -U review -d interview_ingles -c "\d reading_texts"`
Expected: la tabla se lista con las 10 columnas y el índice `reading_texts_level_idx`.

Nota: `down -v` borra el volumen. Es necesario porque Postgres solo corre los scripts de `initdb` al crear el volumen por primera vez; si ya existía, el `.sql` nuevo se ignora.

- [ ] **Step 8: Commit**

```bash
git add app/storage.py docker/initdb/04-reading-texts.sql test_app_reading_texts.py
git commit -m "feat(reading): tabla reading_texts para el catálogo de textos"
```

---

## Task 2: Frontend con plantillas Jinja2

**Files:**
- Modify: `pyproject.toml:6-16` (dependencias)
- Create: `app/web/templates/base.html`, `app/web/templates/index.html`, `app/web/static/app.css`
- Modify: `app/cmd/server.py:41` y `app/cmd/server.py:332-334`
- Delete: `app/web/index.html`
- Test: `test_app_web.py`

**Interfaces:**
- Consumes: nada de la Task 1.
- Produces: `templates/base.html` con los bloques `{% block title %}`, `{% block head %}`, `{% block content %}` y `{% block scripts %}`; los estáticos servidos bajo `/static`; y en `app/cmd/server.py` el objeto `_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))`. La Task 3 y la fase 2 crean páginas nuevas con `{% extends "base.html" %}`.

- [ ] **Step 1: Agregar la dependencia**

En `pyproject.toml`, dentro de `[project].dependencies`, agregar `"jinja2>=3.1",` después de `"python-dotenv>=1.0",`.

Run: `uv sync`
Expected: instala jinja2 y actualiza `uv.lock`.

- [ ] **Step 2: Escribir el test que falla**

Crear `test_app_web.py`:

```python
"""Smoke tests del frontend servido por plantillas.

No validan el diseño (eso se mira en el navegador); validan el contrato de que la página
se renderiza, hereda del base y los estáticos se sirven desde /static. Sin esto, un error
de ruta en las plantillas solo aparecería en producción."""

from fastapi.testclient import TestClient

from app.cmd import server


def _client() -> TestClient:
    return TestClient(server.app)


def test_index_renders():
    response = _client().get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


def test_index_extends_base():
    """El banner vive en base.html: si aparece en la página, la herencia funcionó."""
    body = _client().get("/").text
    assert 'id="banner"' in body
    assert 'id="step-voice"' in body


def test_index_links_shared_stylesheet():
    body = _client().get("/").text
    assert "/static/app.css" in body


def test_stylesheet_is_served():
    response = _client().get("/static/app.css")
    assert response.status_code == 200
    assert "--cream" in response.text
```

- [ ] **Step 3: Correr el test para verificar que falla**

Run: `uv run pytest test_app_web.py -v`
Expected: FAIL — `test_index_links_shared_stylesheet` y `test_stylesheet_is_served` fallan (hoy el CSS está inline y no existe `/static`).

- [ ] **Step 4: Extraer el CSS**

Crear `app/web/static/app.css` con el contenido de `app/web/index.html` líneas **7 a 147** (el interior del `<style>`, sin las etiquetas `<style>`/`</style>`), sin cambios en las reglas. Quitar la indentación sobrante de 6 espacios para que el archivo quede a nivel raíz.

- [ ] **Step 5: Crear `base.html`**

Crear `app/web/templates/base.html`:

```html
<!doctype html>
<html lang="es">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{% block title %}Practica tu inglés{% endblock %}</title>
    <link rel="stylesheet" href="/static/app.css" />
    {% block head %}{% endblock %}
  </head>
  <body>
    <main>
      {# Banner de pausa/cuota: común a todas las modalidades, lo llena showBanner(). #}
      <div id="banner" class="card hidden" role="status" style="text-align:center; border-color:#e2c9a0">
        <h2 id="banner-title"></h2>
        <p id="banner-text" class="lead" style="margin:8px 0 0"></p>
      </div>

      <div id="app">
        {% block content %}{% endblock %}
      </div>
    </main>
    {% block scripts %}{% endblock %}
  </body>
</html>
```

- [ ] **Step 6: Crear `index.html` como plantilla**

Crear `app/web/templates/index.html`:

```html
{% extends "base.html" %}

{% block title %}Practica tu inglés hablado{% endblock %}

{% block content %}
{# Contenido de app/web/index.html líneas 159-272: el interior del <div id="app">,
   SIN el <div id="app"> ni su cierre (ya vienen del base). #}
{% endblock %}

{% block scripts %}
<script>
{# Contenido de app/web/index.html líneas 276-926: el interior del <script>,
   SIN las etiquetas <script>/</script>. #}
</script>
{% endblock %}
```

Reemplazá cada comentario `{# ... #}` por el contenido real indicado, copiado **verbatim** desde `app/web/index.html`. El bloque `<div id="banner">` (líneas 153-156) y el `<div id="app">` (línea 158) **no** se copian: ya están en `base.html`.

- [ ] **Step 7: Cablear las plantillas en el servidor**

En `app/cmd/server.py`, reemplazar la línea 41:

```python
_WEB_DIR = Path(__file__).resolve().parent.parent / "web"
_TEMPLATES_DIR = _WEB_DIR / "templates"
_STATIC_DIR = _WEB_DIR / "static"

_templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
```

Agregar los imports que faltan, junto a los que ya están:

```python
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
```

Reemplazar el bloque final (líneas 332-334):

```python
# --- frontend ------------------------------------------------------------------------
# Los estáticos van bajo /static (no en la raíz) para no tapar las rutas de la API, y cada
# página es un endpoint que renderiza su plantilla.

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    """Sirve la página de la conversación."""
    return _templates.TemplateResponse(request, "index.html")
```

- [ ] **Step 8: Borrar la página estática vieja**

Run: `git rm app/web/index.html`
Expected: el archivo desaparece; su contenido ya vive repartido entre `templates/` y `static/app.css`.

- [ ] **Step 9: Correr los tests**

Run: `uv run pytest test_app_web.py -v`
Expected: PASS (4 tests).

- [ ] **Step 10: Verificar que no se rompió la suite**

Run: `uv run pytest -q`
Expected: PASS. Prestá atención a `test_app_server_start.py` y `test_app_ratelimit.py`, que usan `TestClient` sobre el mismo `app` y podrían depender del mount viejo.

- [ ] **Step 11: Verificar en el navegador**

Run: `docker compose up -d --build`, después abrir `http://localhost:8000`.
Expected: la página se ve **idéntica** a antes (mismos estilos, mismo wizard). Recorré los tres pasos: elegir voz → escribir contexto → llegar a la pantalla de hablar. En la consola del navegador no debe haber errores 404 de `/static/app.css`.

- [ ] **Step 12: Commit**

```bash
git add pyproject.toml uv.lock app/web/templates app/web/static app/cmd/server.py test_app_web.py
git commit -m "refactor(web): servir el frontend con plantillas Jinja2 y estáticos en /static"
```

---

## Task 3: Extraer el JavaScript común a `shared.js`

**Files:**
- Create: `app/web/static/shared.js`
- Modify: `app/web/templates/base.html` (sumar el `<script src>`), `app/web/templates/index.html` (quitar lo extraído y adaptar el uso del grabador)
- Test: `test_app_web.py` (sumar dos casos)

**Interfaces:**
- Consumes: `templates/base.html` y `templates/index.html` de la Task 2; el mount `/static` de la Task 2.
- Produces, como globales de `shared.js`:
  - `$(id)` → `HTMLElement`
  - `Identity.get()` → `string` (UUID persistido en `localStorage`)
  - `class ApiError extends Error` con `.status: number` y `.reason: string|null`
  - `Api.request(method, path, {json, form}) → Promise<any>`
  - `encodeWav(samples: Float32Array, sampleRate: number) → Blob`
  - `createRecorder({maxSeconds, lang, onLevel, onTranscript, onTick, onStart, onStop}) → {start(onDone), stop()}`
  - `showBanner(reason: string|null)`
  - `scoreClass(score) → string`, `formatScore(score) → string|number`, `renderWord(word, speak) → HTMLElement`

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `test_app_web.py`:

```python
def test_shared_script_is_served():
    response = _client().get("/static/shared.js")
    assert response.status_code == 200
    assert "createRecorder" in response.text
    assert "encodeWav" in response.text


def test_index_loads_shared_script():
    assert "/static/shared.js" in _client().get("/").text
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `uv run pytest test_app_web.py -v`
Expected: FAIL — 404 en `/static/shared.js`.

- [ ] **Step 3: Crear `shared.js` con lo que se mueve sin cambios**

Crear `app/web/static/shared.js` empezando por este encabezado y los bloques copiados **verbatim** desde `app/web/templates/index.html` (que los heredó de las líneas indicadas del `index.html` original):

```javascript
"use strict";
// Utilidades compartidas por todas las modalidades (conversación, lectura, …).
// Regla: acá NO se referencian ids del DOM propios de una página. Todo lo que necesite
// tocar la UI de una modalidad entra por callback, así este archivo sirve a cualquiera.
```

Copiar a continuación, sin modificar:

- `$`, `Identity` — líneas 277-288 del `index.html` original
- `class ApiError` — líneas 290-297
- `Api` — líneas 299-327
- `floatTo16BitPCM` y `encodeWav` — líneas 480-497
- `scoreClass`, `formatScore`, `wordClass`, `wordTitle` — líneas 756-779

- [ ] **Step 4: Agregar el grabador desacoplado**

El `Recorder` actual (líneas 499-575) llama directo a `Oval`, `$("heard")` y `$("counter")`, que son de la pantalla de conversación. Agregar en su lugar esta fábrica a `shared.js`:

```javascript
// ---- Grabación: WAV PCM 16-bit mono vía AudioContext, en paralelo al reconocimiento ----
// Es una fábrica y no un singleton porque cada página decide su duración máxima, su idioma
// y qué hacer con el nivel de voz, el parcial reconocido y el segundero. Sin callbacks no
// toca el DOM: así la misma grabación sirve a la conversación y a la lectura.
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

function createRecorder({
  maxSeconds = 30,
  lang = "en-US",
  onLevel = () => {},
  onTranscript = () => {},
  onTick = () => {},
  onStart = () => {},
  onStop = () => {},
} = {}) {
  return {
    audioCtx: null, source: null, processor: null, stream: null,
    chunks: [], sampleRate: 16000, recognition: null, transcript: "",
    timerId: null, secondsLeft: maxSeconds, onDone: null,
    _stopping: false, _recording: false,

    async start(onDone) {
      this._stopping = false;
      this.onDone = onDone; this.chunks = []; this.transcript = "";
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      this.sampleRate = this.audioCtx.sampleRate;
      this.source = this.audioCtx.createMediaStreamSource(this.stream);
      this.processor = this.audioCtx.createScriptProcessor(4096, 1, 1);
      this.processor.onaudioprocess = (e) => {
        const data = e.inputBuffer.getChannelData(0);
        this.chunks.push(new Float32Array(data));
        // Nivel de voz (RMS) del buffer, para que la página anime lo que quiera.
        let sum = 0;
        for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
        onLevel(Math.sqrt(sum / data.length));
      };
      this.source.connect(this.processor);
      this.processor.connect(this.audioCtx.destination);
      this._startRecognition();
      this._startTimer();
      onStart();
    },

    _startRecognition() {
      if (!SR) return; // sin reconocimiento se envía audio con transcript vacío -> el backend valida
      const rec = new SR();
      rec.lang = lang; rec.continuous = true; rec.interimResults = true;
      let acc = "";
      rec.onresult = (e) => {
        let interim = "";
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const t = e.results[i][0].transcript;
          if (e.results[i].isFinal) acc += t + " "; else interim += t;
        }
        this.transcript = acc.trim();
        onTranscript((acc + interim).trim());
      };
      rec.onend = () => { if (this._recording) { try { rec.start(); } catch (_) {} } };
      rec.onerror = () => {};
      this.recognition = rec; this._recording = true;
      try { rec.start(); } catch (_) {}
    },

    _startTimer() {
      this.secondsLeft = maxSeconds;
      onTick(this.secondsLeft);
      this.timerId = setInterval(() => {
        this.secondsLeft -= 1;
        onTick(this.secondsLeft);
        if (this.secondsLeft <= 0) this.stop();
      }, 1000);
    },

    async stop() {
      if (this._stopping || !this.audioCtx) return;
      this._stopping = true;
      clearInterval(this.timerId); this.timerId = null;
      this._recording = false;
      onTick(null); // null = se terminó, la página limpia su contador
      try { this.recognition && this.recognition.stop(); } catch (_) {}
      this.processor.disconnect(); this.source.disconnect();
      this.stream.getTracks().forEach((t) => t.stop());
      // Aplanar chunks a un solo Float32Array.
      const len = this.chunks.reduce((n, c) => n + c.length, 0);
      const samples = new Float32Array(len);
      let off = 0; for (const c of this.chunks) { samples.set(c, off); off += c.length; }
      await this.audioCtx.close(); this.audioCtx = null;
      const wav = encodeWav(samples, this.sampleRate);
      onStop();
      this.onDone && this.onDone(wav, this.transcript);
    },
  };
}
```

- [ ] **Step 5: Agregar el banner y el render de palabras**

Seguir en `shared.js` con estas dos piezas. `showBanner` es igual al original (líneas 578-591) porque `#banner` y `#app` ahora viven en `base.html`, o sea que existen en toda página:

```javascript
// ---- Banner de pausa / cuota (los ids viven en base.html: sirven a cualquier página) ----
function showBanner(reason) {
  $("app").classList.add("hidden");
  $("banner").classList.remove("hidden");
  if (reason === "quota") {
    $("banner-title").textContent = "Llegaste al límite de la demo";
    $("banner-text").textContent = "Ya usaste tus conversaciones de práctica. ¡Gracias por probarla!";
  } else if (reason === "rate_limited") {
    $("banner-title").textContent = "Demasiados intentos seguidos";
    $("banner-text").textContent = "Vas muy rápido. Espera un momento y recarga la página para continuar.";
  } else {
    $("banner-title").textContent = "En pausa por el momento";
    $("banner-text").textContent = "La demo está descansando. Vuelve a intentarlo más tarde.";
  }
}
```

`renderWord` es el original (líneas 780-828) con un solo cambio: recibe `speak` como parámetro en vez de llamar a `Tts`, porque el TTS depende de los controles de voz de cada página:

```javascript
// Cada palabra se colorea por su accuracy, con los sonidos (IPA) visibles y un detalle
// expandible con el score de cada fonema. `speak` se inyecta: quién pronuncia la palabra
// depende de los controles de voz de cada página.
function renderWord(word, speak) {
  const wrapper = document.createElement("span");
  wrapper.className = "word-wrapper";

  const button = document.createElement("button");
  button.type = "button";
  button.className = `word ${wordClass(word)}`;
  button.textContent = word.word;
  button.title = wordTitle(word);

  const listen = document.createElement("button");
  listen.type = "button"; listen.className = "speak";
  listen.textContent = "🔊"; listen.title = "Escuchar";
  listen.setAttribute("aria-label", `Escuchar ${word.word}`);
  listen.addEventListener("click", () => speak(word.word));

  const head = document.createElement("div");
  head.className = "word-head";
  head.append(button, listen);

  // Los sonidos (IPA) en orden, cada uno coloreado por su score: se ve QUÉ parte falló.
  const ipa = document.createElement("div");
  ipa.className = "ipa";
  for (const phoneme of word.phonemes || []) {
    const sound = document.createElement("span");
    sound.className = `sound ${scoreClass(phoneme.accuracy)}`;
    sound.textContent = phoneme.phoneme;
    sound.title = `${phoneme.phoneme}: ${formatScore(phoneme.accuracy)}`;
    ipa.appendChild(sound);
  }

  // Detalle con el número exacto de cada sonido, al hacer clic en la palabra.
  const detail = document.createElement("div");
  detail.className = "phonemes hidden";
  if (!word.phonemes || word.phonemes.length === 0) {
    detail.textContent = "Sin detalle de sonidos.";
  } else {
    for (const phoneme of word.phonemes) {
      const chip = document.createElement("span");
      chip.className = `phoneme ${scoreClass(phoneme.accuracy)}`;
      chip.textContent = `${phoneme.phoneme} ${formatScore(phoneme.accuracy)}`;
      detail.appendChild(chip);
    }
  }

  button.addEventListener("click", () => detail.classList.toggle("hidden"));
  wrapper.append(head, ipa, detail);
  return wrapper;
}
```

- [ ] **Step 6: Cargar `shared.js` desde `base.html`**

En `app/web/templates/base.html`, reemplazar la línea `{% block scripts %}{% endblock %}` por:

```html
    <script src="/static/shared.js"></script>
    {% block scripts %}{% endblock %}
```

Va **antes** del bloque para que las páginas puedan usar sus globales.

- [ ] **Step 7: Adaptar `index.html` a lo extraído**

En el `<script>` de `app/web/templates/index.html`:

1. **Borrar** los bloques que ahora viven en `shared.js`: `"use strict";`, `$`, `Identity`, `ApiError`, `Api`, `SR`, `floatTo16BitPCM`, `encodeWav`, el objeto `Recorder` completo, `showBanner`, `scoreClass`, `formatScore`, `wordClass`, `wordTitle` y `renderWord`.

2. **Reemplazar** el `Recorder` borrado por esta construcción, ubicándola donde estaba el objeto original:

```javascript
      // El grabador es compartido; acá se le dice a qué elementos de ESTA página responde.
      const Recorder = createRecorder({
        maxSeconds: 30,
        lang: "en-US",
        onLevel: (rms) => Oval.level(rms),
        onTranscript: (text) => { $("heard").textContent = text; },
        onTick: (secondsLeft) => {
          $("counter").textContent =
            secondsLeft === null ? "" : "0:" + String(secondsLeft).padStart(2, "0");
        },
        onStart: () => Oval.recording(),
        onStop: () => Oval.idle(),
      });
```

3. **Corregir** la llamada a `renderWord` dentro de `renderPronunciation` (línea 832 del original), que ahora necesita el segundo argumento:

```javascript
        words.forEach((w) => el.appendChild(renderWord(w, (t) => Tts.speak(t))));
```

- [ ] **Step 8: Correr los tests**

Run: `uv run pytest test_app_web.py -v`
Expected: PASS (6 tests).

- [ ] **Step 9: Verificar la suite completa**

Run: `uv run pytest -q`
Expected: PASS, sin regresiones.

- [ ] **Step 10: Verificar en el navegador — este paso es el que importa**

Los tests de Python solo comprueban que los archivos se sirven; que el JavaScript funcione se verifica a mano. Run: `docker compose up -d --build`, abrir `http://localhost:8000` en Chrome y recorrer el flujo completo:

1. La consola del navegador no muestra errores (especialmente `createRecorder is not defined` o 404 de `/static/shared.js`).
2. Elegir voz y tocar "Probar voz": se escucha.
3. Escribir un contexto y empezar la práctica: aparece la primera pregunta y se escucha.
4. Tocar "Responder" y hablar: el óvalo pulsa con la voz (`onLevel`), el contador baja desde 0:30 (`onTick`), y debajo aparece lo que vas diciendo (`onTranscript`).
5. Tocar "Detener": se envía y llega la siguiente pregunta.
6. Terminar la conversación: en el review, las palabras aparecen coloreadas y el botón 🔊 de una palabra la pronuncia (esto valida el `speak` inyectado en `renderWord`).

Si algo de esto falla, el problema está en el desacople de los callbacks del Step 7, no en el backend.

- [ ] **Step 11: Commit**

```bash
git add app/web/static/shared.js app/web/templates test_app_web.py
git commit -m "refactor(web): extraer a shared.js el JS común (identidad, API, grabación, palabras)"
```

---

## Verificación final de la fase

- [ ] `uv run pytest -q` pasa entero.
- [ ] `docker compose down -v && docker compose up -d --build` levanta, la tabla `reading_texts` existe, y la conversación funciona igual que antes de la fase.
- [ ] Se puede insertar un texto a mano y leerlo, que es lo que habilita esta fase:

```bash
docker compose exec -T db psql -U review -d interview_ingles -c \
  "INSERT INTO reading_texts (source, source_url, title, level, category, body)
   VALUES ('manual', 'https://example.com/prueba', 'Texto de prueba', 5, 'Test',
           'This is a short sample text to read aloud.');"

docker compose exec -T db psql -U review -d interview_ingles -c \
  "SELECT id, source, level, title FROM reading_texts;"
```

## Lo que queda para la fase 2

Script de ingesta desde Engoo (`app/reading/sources/engoo.py` con `httpx.AsyncClient`), job periódico, tabla `reading_starts`, `excerpt.py`, endpoints `/reading/random` y `/reading/assess`, `templates/reading.html`, y `assess_scripted` en `app/speech/assessment.py`. Todo está descrito en el spec.
