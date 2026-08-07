# Pulido de lectura, voces compartidas y filtro por nivel — Implementation Plan

> **Estado: ejecutado.** Todas las tareas están implementadas y commiteadas en `feature/reading-fase2`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Arreglar el 🔊 de las palabras en lectura, recuperar los párrafos del texto de referencia, sustituir el selector de voz por tres botones, quitar las menciones al proveedor y permitir pedir un texto de nivel máximo N.

**Architecture:** El TTS deja de estar atado al DOM de la conversación: se muda a `shared.js` y pide la voz y el ritmo a un módulo nuevo, `prefs.js`, único lugar que sabe dónde se guardan las preferencias. `make_excerpt` pasa de reconstruir el texto a cortarlo, con lo que conserva los saltos de párrafo del original. El filtro por nivel viaja como query param hasta un `WHERE level <= %s`.

**Tech Stack:** Python 3.11+, FastAPI, psycopg 3 (async), Jinja2, JS sin framework, pytest + Hypothesis.

**Spec:** [docs/superpowers/specs/2026-08-06-pulido-lectura-y-voces-design.md](../specs/2026-08-06-pulido-lectura-y-voces-design.md)

## Global Constraints

- **Toda variable de entorno se declara y se lee SOLO en `config.py`.**
- **Ningún test toca la red ni levanta una base de datos.**
- **Los tests viven en la raíz del repo** y se corren con `uv run pytest`.
- **`shared.js` no referencia ids del DOM propios de una página** (regla escrita en su cabecera). Lo que necesite tocar la UI de una modalidad entra por callback o por `Prefs`.
- **`prefs.js` es el único archivo que menciona `localStorage`.** Ni `shared.js` ni las páginas leen o escriben ahí directamente.
- **Ningún texto visible para el usuario nombra al proveedor** (Azure, Gemini, Google Cloud). Los comentarios de código sí pueden nombrarlo.
- **Esta versión funciona solo en Google Chrome en computadora.** No se implementan fallbacks para otros navegadores.
- **Los docstrings y comentarios van en español**, explicando el porqué.
- Nombres exactos de las voces: `Google US English`, `Google UK English Female`, `Google UK English Male`.
- Claves de preferencias: `pilot_voice` (nombre de la voz), `pilot_rate`, `pilot_max_level`.

## File Structure

| Archivo | Responsabilidad | Task |
|---|---|---|
| `app/reading/excerpt.py` | **Modificar.** `make_excerpt` corta en vez de reconstruir | 1 |
| `app/reading/repository.py` | **Modificar.** `random(max_level)` en el `Protocol` y en Postgres | 2 |
| `app/reading/service.py` | **Modificar.** `random_excerpt(max_level)` y su mensaje de 503 | 2 |
| `app/cmd/server.py` | **Modificar.** `max_level` como query param validado | 3 |
| `app/web/static/prefs.js` | **Crear.** Único lugar que sabe dónde viven las preferencias | 4 |
| `app/web/static/shared.js` | **Modificar.** Recibe `Tts`, sin dependencias del DOM | 4 |
| `app/web/templates/base.html` | **Modificar.** Carga `prefs.js` antes que `shared.js` | 4 |
| `app/web/templates/index.html` | **Modificar.** Tres botones de voz; pierde su `Tts` local | 5 |
| `app/web/templates/reading.html` | **Modificar.** Título, meta y controles dentro del panel | 6 |
| `app/web/static/reading.js` | **Modificar.** Párrafos, escuchar/detener, 🔊, nivel | 6 |
| `app/web/static/app.css` | **Modificar.** Botones de voz y cabecera del panel | 5, 6 |

Orden: 1, 2 y 3 son backend y van seguidas (3 depende de 2). La 4 es el cimiento del frontend; 5 y 6 dependen de ella y son independientes entre sí.

---

### Task 1: `make_excerpt` conserva el texto original

Hoy la función parte el cuerpo en oraciones y las vuelve a pegar con un espacio, lo que borra los saltos de párrafo del artículo. Pasa a calcular **dónde** cortar y devolver ese prefijo, con lo que el texto sale intacto.

**Files:**
- Modify: `app/reading/excerpt.py`
- Test: `test_app_reading_excerpt.py`

**Interfaces:**
- Consumes: nada.
- Produces: `make_excerpt(body: str, max_words: int) -> str` — misma firma que hoy. Nueva garantía: el resultado es siempre un prefijo literal de `body.strip()`.

- [x] **Step 1: Escribir los tests que fallan**

Añadir a `test_app_reading_excerpt.py`:

```python
def test_conserva_los_saltos_de_parrafo():
    """Los artículos de Engoo vienen con párrafos; el extracto no debe aplanarlos."""
    body = "One two three.\n\nFour five six.\n\nSeven eight nine."
    assert make_excerpt(body, 7) == "One two three.\n\nFour five six."


def test_conserva_los_espacios_dobles_del_original():
    body = "One  two three. Four five six. Seven eight."
    assert make_excerpt(body, 6) == "One  two three. Four five six."


def test_corte_por_palabras_tambien_conserva_los_espacios():
    """Cuando ni la primera oración cabe, el recorte sigue siendo texto literal."""
    body = "One  two three four five."
    assert make_excerpt(body, 3) == "One  two three"


@given(
    body=st.text(min_size=0, max_size=500),
    max_words=st.integers(min_value=1, max_value=50),
)
def test_el_extracto_es_un_prefijo_literal_del_cuerpo(body, max_words):
    """La garantía de la que dependen las demás: no se pierde ni un espacio ni un salto."""
    assert body.strip().startswith(make_excerpt(body, max_words))
```

- [x] **Step 2: Correr los tests y verificar que fallan**

Run: `uv run pytest test_app_reading_excerpt.py -q`
Expected: FAIL — los tres casos concretos devuelven el texto aplanado, y la propiedad falla en cuanto Hypothesis encuentra un cuerpo con espacios repetidos.

- [x] **Step 3: Reescribir `make_excerpt`**

Reemplazar el cuerpo de la función en `app/reading/excerpt.py` (la constante `_SENTENCE_END` y el docstring del módulo se quedan igual):

```python
def make_excerpt(body: str, max_words: int) -> str:
    """Devuelve el fragmento inicial de `body` que no pasa de `max_words` palabras.

    Corta en el último límite de oración que quepa, para que el usuario lea algo con sentido
    y no una frase truncada a media idea. Si ni la primera oración cabe, corta tras la última
    palabra completa que entre: un extracto algo abrupto es mejor que uno vacío.

    Devuelve siempre un PREFIJO LITERAL del cuerpo, nunca un texto reconstruido. Esa es la
    diferencia que conserva los saltos de párrafo del artículo: partir en oraciones y volver
    a unirlas con un espacio los borraba todos.
    """
    words = body.split()
    if not words:
        return ""
    if len(words) <= max_words:
        return body.strip()

    text = body.strip()

    # Se avanza oración a oración guardando la última posición de corte que cabe. `cut` es un
    # índice dentro de `text`, no un texto acumulado: por eso lo que hay entre oraciones
    # (espacios, saltos de línea, párrafos en blanco) sobrevive tal cual.
    cut = 0
    count = 0
    start = 0
    for separator in _SENTENCE_END.finditer(text):
        sentence_words = len(text[start : separator.start()].split())
        if count + sentence_words > max_words:
            break
        count += sentence_words
        cut = separator.start()
        start = separator.end()

    if cut:
        return text[:cut]

    # Ni la primera oración cabe. Se corta tras la última palabra completa que entra, otra
    # vez por posición, para no perder los espacios interiores.
    end = 0
    for index, word in enumerate(re.finditer(r"\S+", text)):
        if index == max_words:
            break
        end = word.end()
    return text[:end]
```

- [x] **Step 4: Correr los tests y verificar que pasan**

Run: `uv run pytest test_app_reading_excerpt.py -q`
Expected: PASS, 12 tests. Los 8 anteriores siguen valiendo — en particular el de determinismo, del que depende que no haga falta caché del extracto.

- [x] **Step 5: Correr la suite completa**

Run: `uv run pytest -q`
Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add app/reading/excerpt.py test_app_reading_excerpt.py
git commit -m "fix(reading): el extracto conserva los parrafos del articulo original"
```

---

### Task 2: Filtro por nivel en el repositorio y el servicio

**Files:**
- Modify: `app/reading/repository.py`
- Modify: `app/reading/service.py`
- Test: `test_app_reading_repository.py`, `test_app_reading_service.py`

**Interfaces:**
- Consumes: `StoredReadingText` y `ReadingTextStore` de `app/reading/repository.py`; `ReadingError` de `app/reading/service.py`.
- Produces:
  - `ReadingTextStore.random(max_level: int | None = None) -> StoredReadingText | None`
  - `ReadingService.random_excerpt(max_level: int | None = None) -> dict`
  - `InMemoryReadingTextStore.random(max_level=None)` en `test_app_reading_repository.py`, que consumen los tests del servicio.

- [x] **Step 1: Escribir los tests que fallan**

En `test_app_reading_repository.py`, cambiar la firma del doble y añadir sus casos.

Reemplazar el método `random` de `InMemoryReadingTextStore` por:

```python
    async def random(self, max_level=None):
        for reading_id, text in self._rows.items():
            if max_level is None:
                return StoredReadingText(id=reading_id, text=text)
            # Un texto sin nivel podría ser más difícil de lo pedido: no entra al filtrar.
            if text.level is not None and text.level <= max_level:
                return StoredReadingText(id=reading_id, text=text)
        return None
```

Y añadir al final del archivo:

```python
def a_text_with_level(level, title="T"):
    return ReadingText(
        source="engoo", source_url=f"https://x/{title}", title=title,
        body="One two three.", level=level,
    )


async def test_random_sin_filtro_devuelve_cualquiera():
    store = InMemoryReadingTextStore([a_text_with_level(7)])
    assert (await store.random()).text.level == 7


async def test_random_respeta_el_nivel_maximo():
    store = InMemoryReadingTextStore([a_text_with_level(7), a_text_with_level(4)])
    assert (await store.random(max_level=5)).text.level == 4


async def test_random_excluye_los_textos_sin_nivel_al_filtrar():
    """'No sé el nivel' no es 'nivel fácil': podría ser un 8."""
    store = InMemoryReadingTextStore([a_text_with_level(None)])
    assert await store.random(max_level=5) is None


async def test_random_incluye_los_textos_sin_nivel_si_no_hay_filtro():
    store = InMemoryReadingTextStore([a_text_with_level(None)])
    assert (await store.random()) is not None
```

En `test_app_reading_service.py`, añadir:

```python
async def test_random_excerpt_propaga_el_nivel_maximo():
    store = InMemoryReadingTextStore([a_text(level=7), a_text(level=4)])
    service = ReadingService(store, assess_fn=FakeAssess())
    result = await service.random_excerpt(max_level=5)
    assert result["level"] == 4


async def test_sin_textos_del_nivel_pedido_es_503_con_el_motivo():
    """Devolver uno más difícil sería ignorar lo que el usuario pidió."""
    service = ReadingService(
        InMemoryReadingTextStore([a_text(level=7)]), assess_fn=FakeAssess()
    )
    with pytest.raises(ReadingError) as exc:
        await service.random_excerpt(max_level=4)
    assert exc.value.status == 503
    assert "nivel 4" in str(exc.value)
```

- [x] **Step 2: Correr los tests y verificar que fallan**

Run: `uv run pytest test_app_reading_repository.py test_app_reading_service.py -q`
Expected: FAIL con `TypeError: random() got an unexpected keyword argument 'max_level'` en el adaptador real, y con el 503 sin el texto esperado.

- [x] **Step 3: Añadir el filtro al repositorio**

En `app/reading/repository.py`, cambiar la firma en el `Protocol`:

```python
    async def random(self, max_level: int | None = None) -> StoredReadingText | None:
        """Un texto al azar del catálogo, o None si no hay ninguno que sirva.

        `max_level` es un tope, no un nivel exacto: pedir 5 puede devolver un 4. Los textos
        sin nivel quedan fuera al filtrar, porque "no sé el nivel" podría ser un 8.
        """
        ...
```

Y en `PostgresReadingTextStore`:

```python
    async def random(self, max_level: int | None = None) -> StoredReadingText | None:
        """Una fila al azar, opcionalmente limitada por dificultad.

        `ORDER BY random()` escanea la tabla entera, lo que sería un problema con millones de
        filas pero es irrelevante con las decenas o pocos cientos que produce la ingesta. La
        alternativa (contar y elegir un offset) cuesta dos viajes y se desincroniza si la
        ingesta inserta entre medio. Si el catálogo creciera de verdad, esto pasa a
        TABLESAMPLE.

        `level <= %s` descarta también las filas con `level IS NULL`, que es lo que queremos:
        un texto de dificultad desconocida no cumple "5 o menos". El índice
        `reading_texts_level_idx` es el que sirve a esta comparación.
        """
        where = "" if max_level is None else "WHERE level <= %s"
        params = () if max_level is None else (max_level,)
        async with self._storage.connect() as conn:
            row = await (
                await conn.execute(
                    f"SELECT {self._COLUMNS} FROM reading_texts {where} "
                    "ORDER BY random() LIMIT 1",
                    params,
                )
            ).fetchone()
        return None if row is None else self._to_stored(row)
```

- [x] **Step 4: Propagar en el servicio**

En `app/reading/service.py`, reemplazar `random_excerpt`:

```python
    async def random_excerpt(self, max_level: int | None = None) -> dict:
        """Un texto al azar del catálogo, ya recortado al fragmento que se lee en voz alta.

        `max_level` limita la dificultad. Si no hay ninguno que cumpla, se corta con 503 en
        vez de devolver uno más difícil: dar un nivel 7 a quien pidió "4 o menos" sería
        ignorar exactamente lo que pidió.
        """
        stored = await self._store.random(max_level)
        if stored is None:
            if max_level is not None:
                raise ReadingError(
                    f"No hay textos de nivel {max_level} o menos en el catálogo. "
                    "Prueba subiendo el nivel máximo.",
                    status=503,
                )
            raise ReadingError(
                "Todavía no hay textos para leer. Corre la ingesta del catálogo "
                "(`python -m app.reading.ingest`) e intenta de nuevo.",
                status=503,
            )
        excerpt = make_excerpt(stored.text.body, settings.READING_MAX_WORDS)
        return {
            "reading_id": stored.id,
            "title": stored.text.title,
            "level": stored.text.level,
            "source_url": stored.text.source_url,
            "excerpt": excerpt,
            "word_count": len(excerpt.split()),
        }
```

- [x] **Step 5: Correr los tests y verificar que pasan**

Run: `uv run pytest test_app_reading_repository.py test_app_reading_service.py -q`
Expected: PASS, 9 + 9 tests.

Si `test_app_reading_service.py` falla porque su helper `a_text` no acepta `level`, revisar su definición: ya tiene `level=5` como parámetro con default, así que `a_text(level=7)` funciona sin tocarla.

- [x] **Step 6: Correr la suite completa**

Run: `uv run pytest -q`
Expected: PASS.

- [x] **Step 7: Commit**

```bash
git add app/reading/ test_app_reading_repository.py test_app_reading_service.py
git commit -m "feat(reading): filtro por nivel maximo en el catalogo"
```

---

### Task 3: `max_level` en el endpoint

**Files:**
- Modify: `app/cmd/server.py`
- Test: `test_app_server_reading.py`

**Interfaces:**
- Consumes: `ReadingService.random_excerpt(max_level)` (Task 2); `get_reading_service` y `FakeReadingService` de `test_app_server_reading.py`.
- Produces: `GET /reading/random?max_level=N`, con `N` entero de 1 a 10.

- [x] **Step 1: Escribir los tests que fallan**

En `test_app_server_reading.py`, la clase `FakeReadingService` necesita registrar el parámetro. Reemplazar su `random_excerpt` por:

```python
    async def random_excerpt(self, max_level=None):
        self.asked_max_level = max_level
        if self._error:
            raise self._error
        return self._random
```

y añadir `self.asked_max_level = None` al final de su `__init__`.

Luego añadir los tests:

```python
def test_random_pasa_el_nivel_maximo_al_servicio(client):
    service = FakeReadingService()
    app.dependency_overrides[get_reading_service] = lambda: service
    app.dependency_overrides[get_limits_service] = lambda: FakeLimits()

    client.get("/reading/random?max_level=5", headers=HEADERS)

    assert service.asked_max_level == 5


def test_random_sin_nivel_no_filtra(client):
    service = FakeReadingService()
    app.dependency_overrides[get_reading_service] = lambda: service
    app.dependency_overrides[get_limits_service] = lambda: FakeLimits()

    client.get("/reading/random", headers=HEADERS)

    assert service.asked_max_level is None


def test_un_nivel_maximo_invalido_es_422(client):
    app.dependency_overrides[get_reading_service] = lambda: FakeReadingService()
    app.dependency_overrides[get_limits_service] = lambda: FakeLimits()

    assert client.get("/reading/random?max_level=0", headers=HEADERS).status_code == 422
    assert client.get("/reading/random?max_level=99", headers=HEADERS).status_code == 422
    assert client.get("/reading/random?max_level=x", headers=HEADERS).status_code == 422


def test_sin_textos_del_nivel_pedido_es_503(client):
    app.dependency_overrides[get_reading_service] = lambda: FakeReadingService(
        error=ReadingError("No hay textos de nivel 4 o menos", status=503)
    )
    app.dependency_overrides[get_limits_service] = lambda: FakeLimits()

    res = client.get("/reading/random?max_level=4", headers=HEADERS)

    assert res.status_code == 503
    assert "nivel 4" in res.json()["detail"]
```

- [x] **Step 2: Correr los tests y verificar que fallan**

Run: `uv run pytest test_app_server_reading.py -q`
Expected: FAIL — `asked_max_level` queda en `None` cuando se pidió 5, y `max_level=0` devuelve 200 en vez de 422.

- [x] **Step 3: Añadir el query param**

En `app/cmd/server.py`, agregar `Query` al import de `fastapi`:

```python
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile
```

Y cambiar la firma y la llamada de `reading_random`:

```python
@app.get("/reading/random")
async def reading_random(
    max_level: int | None = Query(
        default=None,
        ge=1,
        le=10,
        description="Tope de dificultad. Sin él, cualquier texto del catálogo.",
    ),
    user_id: str = Depends(get_user_id),
    reading: ReadingService = Depends(get_reading_service),
    limits: LimitsService = Depends(get_limits_service),
) -> dict:
```

y dentro, la última llamada:

```python
    try:
        return await reading.random_excerpt(max_level)
    except ReadingError as error:
        raise HTTPException(status_code=error.status, detail=str(error))
```

Las cotas `ge`/`le` son lo que hace que FastAPI devuelva 422 solo con declararlas; no hace falta validar a mano.

- [x] **Step 4: Correr los tests y verificar que pasan**

Run: `uv run pytest test_app_server_reading.py -q`
Expected: PASS, 16 tests.

- [x] **Step 5: Correr la suite completa**

Run: `uv run pytest -q`
Expected: PASS.

- [x] **Step 6: Commit**

```bash
git add app/cmd/server.py test_app_server_reading.py
git commit -m "feat(reading): max_level como query param de /reading/random"
```

---

### Task 4: `prefs.js` y `Tts` compartido

El cimiento del frontend. Sin esto, la pantalla de lectura no puede pronunciar nada.

**Files:**
- Create: `app/web/static/prefs.js`
- Modify: `app/web/static/shared.js`
- Modify: `app/web/templates/base.html`

**Interfaces:**
- Consumes: nada.
- Produces, disponibles en cualquier página:
  - `Prefs.voiceName() -> string`, `Prefs.setVoiceName(name: string)`
  - `Prefs.rate() -> number`, `Prefs.setRate(value: number)`
  - `Prefs.maxLevel() -> number`, `Prefs.setMaxLevel(level: number)`
  - `Tts.load()` — carga la lista de voces del navegador
  - `Tts.speak(text, {onstart, onboundary, onend})` — habla con la voz y el ritmo de `Prefs`
  - `Tts.stop()` — corta lo que esté sonando

- [x] **Step 1: Crear `prefs.js`**

```javascript
"use strict";
// Único lugar que sabe DÓNDE se guardan las preferencias del usuario.
//
// Hoy es localStorage. Si mañana pasan a la base de datos detrás de un endpoint, solo cambia
// este archivo: ni Tts, ni la conversación, ni la lectura se enteran. Por eso nadie más en el
// frontend menciona localStorage.

const VOICES = [
  { name: "Google US English", label: "🇺🇸 US" },
  { name: "Google UK English Female", label: "🇬🇧 UK F" },
  { name: "Google UK English Male", label: "🇬🇧 UK M" },
];

const Prefs = {
  // Se guarda el NOMBRE de la voz, no su posición en la lista del navegador: un índice
  // apuntaría a otra voz si cambiara el orden de las voces instaladas, y no significaría
  // nada si algún día esto viajara a un endpoint.
  voiceName() {
    return localStorage.getItem("pilot_voice") || VOICES[0].name;
  },
  setVoiceName(name) {
    localStorage.setItem("pilot_voice", name);
  },

  rate() {
    return Number(localStorage.getItem("pilot_rate")) || 0.95;
  },
  setRate(value) {
    localStorage.setItem("pilot_rate", String(value));
  },

  // Tope de dificultad de los textos de lectura. 7 es el máximo que ingiere el catálogo,
  // así que por defecto no filtra nada.
  maxLevel() {
    return Number(localStorage.getItem("pilot_max_level")) || 7;
  },
  setMaxLevel(level) {
    localStorage.setItem("pilot_max_level", String(level));
  },
};
```

- [x] **Step 2: Mover `Tts` a `shared.js`**

Añadir a `app/web/static/shared.js`, después del bloque del banner:

```javascript
// ---- TTS (text to speech): la voz que lee un texto en voz alta ----
// Vive acá porque lo usan las dos modalidades: el tutor que lee las preguntas y el 🔊 de
// cada palabra. No mira la pantalla: la voz y el ritmo se los pide a Prefs, así funciona
// igual en una página con controles de voz y en una sin ellos.
const Tts = {
  voices: [],

  load() {
    this.voices = speechSynthesis.getVoices().filter((v) => v.lang.startsWith("en"));
  },

  speak(text, { onstart, onboundary, onend } = {}) {
    if (!text) { onend && onend(); return; }
    speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    const voice = this.voices.find((v) => v.name === Prefs.voiceName()) || null;
    if (voice) utterance.voice = voice;
    utterance.lang = voice ? voice.lang : "en-US";
    utterance.rate = Prefs.rate();
    if (onstart) utterance.onstart = onstart;
    if (onboundary) utterance.onboundary = onboundary;
    utterance.onend = () => onend && onend();
    speechSynthesis.speak(utterance);
  },

  // Corta lo que esté sonando. `speak` ya cancela lo anterior, pero esto hace falta para
  // parar sin empezar nada nuevo (el botón Detener, o al abrir el micrófono).
  stop() {
    speechSynthesis.cancel();
  },
};
```

- [x] **Step 3: Cargar `prefs.js` antes que `shared.js`**

En `app/web/templates/base.html`, sustituir la línea del script por:

```html
    {# prefs.js va primero: shared.js usa Prefs para saber con qué voz hablar. #}
    <script src="/static/prefs.js"></script>
    <script src="/static/shared.js"></script>
```

- [x] **Step 4: Borrar el `Tts` local de `index.html`**

Este paso va acá y no en la Task 5 para que ningún commit deje la app rota. `index.html` declara su propio `const Tts = {...}` en el mismo ámbito global que `shared.js`, así que si se dejara, Chrome abortaría el script entero con `SyntaxError: Identifier 'Tts' has already been declared`.

En el `<script>` de `app/web/templates/index.html`, **borrar entero** el bloque `const Tts = { ... };` — desde el comentario `// ---- TTS: voces en inglés...` hasta el `};` que lo cierra.

Estado intermedio, esperado y funcional: el `<select id="voice">` sigue en la página y sigue guardando un índice numérico en `pilot_voice`. Como `Prefs.voiceName()` ahora busca por nombre, ese número no coincide con ninguna voz y se usa `Google US English`. O sea: el selector deja de tener efecto hasta que la Task 5 lo sustituya por los botones. Nada se rompe, solo se queda en la voz por defecto.

- [x] **Step 5: Verificar en Chrome**

Run: `uv run uvicorn app.cmd.server:app --port 8123` y abrir `http://localhost:8123/` con la consola abierta.

Comprobar:
- La consola no tiene errores.
- "Probar voz" suena (con la voz por defecto).
- El slider de ritmo sigue cambiando el número en pantalla.

- [x] **Step 6: Correr la suite completa**

Run: `uv run pytest -q`
Expected: PASS. El backend no cambia; esto solo confirma que no se tocó nada de Python.

- [x] **Step 7: Commit**

```bash
git add app/web/static/prefs.js app/web/static/shared.js app/web/templates/base.html app/web/templates/index.html
git commit -m "refactor(web): Tts a shared.js, con las preferencias en prefs.js"
```

---

### Task 5: Tres botones de voz en la conversación

**Files:**
- Modify: `app/web/templates/index.html`
- Modify: `app/web/static/app.css`

**Interfaces:**
- Consumes: `Prefs`, `Tts` (Task 4); `VOICES` de `prefs.js`.
- Produces: nada que otras tareas consuman.

- [x] **Step 1: Sustituir el selector por los botones**

En `app/web/templates/index.html`, reemplazar estas cuatro líneas de la sección `#step-voice`:

```html
  <label for="voice">Voz</label>
  <select id="voice"></select>
  <label for="rate">Ritmo: <span id="rate-value">0.95</span>×</label>
```

por:

```html
  <label>Voz</label>
  <div id="voice-buttons" class="voice-picker"></div>
  <label for="rate">Ritmo: <span id="rate-value">0.95</span>×</label>
```

Y cambiar el aviso de recomendación a requisito, en la línea del `<p class="notice">`:

```html
  <p class="notice"><span class="ico">💡</span><span>Esta versión funciona solo en <strong>Google Chrome</strong> en computadora: las voces y el dictado por voz dependen de él.</span></p>
```

- [x] **Step 2: Pintar los botones**

El `Tts` local ya se borró en la Task 4. Sustituir el bloque de listeners del paso 1 (el que empieza en `// ---- Paso 1: Voz ----`) por:

```javascript
// ---- Paso 1: Voz ----
// Los botones solo ESCRIBEN la preferencia; quién habla y con qué voz lo resuelve Tts.
function renderVoiceButtons() {
  const box = $("voice-buttons");
  box.innerHTML = "";
  for (const voice of VOICES) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "small" + (voice.name === Prefs.voiceName() ? " on" : "");
    button.textContent = voice.label;
    button.title = voice.name;
    button.addEventListener("click", () => {
      Prefs.setVoiceName(voice.name);
      renderVoiceButtons();
      Tts.speak("Hi! Let's practice English together.");
    });
    box.appendChild(button);
  }
}

$("rate").addEventListener("input", () => {
  const value = Number($("rate").value);
  $("rate-value").textContent = value.toFixed(2);
  Prefs.setRate(value);
});
$("voice-test").addEventListener("click", () =>
  Tts.speak("Hi! Let's practice English together. Ready when you are.")
);
$("voice-next").addEventListener("click", () => Stepper.go("context"));
```

En el bloque `// ---- init ----` del final, sustituir las dos primeras líneas:

```javascript
Tts.load();
speechSynthesis.onvoiceschanged = () => Tts.load();
```

por:

```javascript
Tts.load();
renderVoiceButtons();
$("rate").value = Prefs.rate();
$("rate-value").textContent = Prefs.rate().toFixed(2);
speechSynthesis.onvoiceschanged = () => Tts.load();
```

- [x] **Step 3: Quitar la mención al proveedor**

En `index.html`, en el bloque `#pron-block`, cambiar:

```html
    <p class="muted">Cada sonido va coloreado por su score de Azure. Toca una palabra para ver el detalle, o 🔊 para escucharla.</p>
```

por:

```html
    <p class="muted">Cada sonido va coloreado por su score. Toca una palabra para ver el detalle, o 🔊 para escucharla.</p>
```

- [x] **Step 4: Estilar los botones**

Añadir a `app/web/static/app.css`:

```css
/* Selector de voz: tres botones en vez de un <select>. El activo usa .on, que ya existe. */
.voice-picker { display: flex; gap: 8px; flex-wrap: wrap; }
.voice-picker button { background: transparent; border-color: var(--gold-soft); color: var(--ink); }
.voice-picker button.on { background: var(--gold-deep); border-color: var(--gold-deep); color: #fff; }
```

- [x] **Step 5: Verificar en Chrome**

Run: `uv run uvicorn app.cmd.server:app --port 8123` y abrir `http://localhost:8123/`.

Comprobar, uno por uno:
- La consola no tiene errores.
- Se ven tres botones: 🇺🇸 US, 🇬🇧 UK F, 🇬🇧 UK M, con uno resaltado.
- Al hacer clic en otro, se resalta ese y suena una frase con esa voz.
- Al recargar, sigue resaltado el que elegiste.
- El slider de ritmo cambia el número y sobrevive a recargar.
- "Probar voz" suena con la voz elegida.
- En la pantalla final ya no aparece la palabra "Azure".

- [x] **Step 6: Commit**

```bash
git add app/web/templates/index.html app/web/static/app.css
git commit -m "feat(web): tres botones de voz y sin menciones al proveedor"
```

---

### Task 6: El panel de lectura

**Files:**
- Modify: `app/web/templates/reading.html`
- Modify: `app/web/static/reading.js`
- Modify: `app/web/static/app.css`

**Interfaces:**
- Consumes: `Prefs`, `Tts` (Task 4); `GET /reading/random?max_level=N` (Task 3); de `shared.js`: `$`, `Api`, `createRecorder`, `showBanner`, `renderWord`, `scoreClass`, `formatScore`.
- Produces: nada que otras tareas consuman.

- [x] **Step 1: Reescribir la plantilla**

Sustituir el bloque `content` de `app/web/templates/reading.html` por:

```html
{% block content %}
  <header>
    <h1>Lectura en voz alta</h1>
    <p class="lead">Lee el texto en voz alta. Al terminar te decimos qué palabras fallaste.</p>
  </header>

  {# Fila de scores: sólo aparece en el estado de review. #}
  <div id="reading-scores" class="scores hidden"></div>

  <div class="split">
    <section class="panel card">
      <div class="panel-head">
        <h2 id="reading-title">Cargando…</h2>
        <button id="btn-listen" type="button" class="ghost small" disabled>🔊 Escuchar</button>
      </div>
      <p class="panel-meta">
        <span id="reading-level" class="badge hidden"></span>
        <a id="reading-source" href="#" target="_blank" rel="noopener" class="hidden">Artículo original ↗</a>
      </p>
      <div id="reading-text" class="panel-body">Cargando un texto…</div>
    </section>
    <section class="panel card">
      <div class="panel-head">
        <h2 id="right-title">Lo que estás diciendo</h2>
      </div>
      <div id="reading-said" class="panel-body"></div>
    </section>
  </div>

  <div class="row">
    <button id="btn-record" type="button" disabled>Empezar a leer</button>
    <button id="btn-another" type="button" class="ghost">Otro texto</button>
    <label for="max-level" class="inline-label">Nivel máximo</label>
    <select id="max-level" class="inline-select">
      <option value="4">4</option>
      <option value="5">5</option>
      <option value="6">6</option>
      <option value="7">7</option>
    </select>
    <span id="reading-timer" class="counter"></span>
  </div>

  <p id="reading-error" class="error hidden" role="alert"></p>
{% endblock %}
```

- [x] **Step 2: Actualizar `reading.js`**

En `app/web/static/reading.js`, sustituir la función `loadText` por:

```javascript
async function loadText() {
  clearError();
  Tts.stop();
  $("btn-record").disabled = true;
  $("btn-listen").disabled = true;
  $("btn-record").textContent = "Empezar a leer";
  $("reading-text").textContent = "Cargando un texto…";
  $("reading-said").innerHTML = "";
  $("reading-said").classList.remove("pron-words");
  $("reading-scores").classList.add("hidden");
  $("right-title").textContent = "Lo que estás diciendo";

  try {
    current = await Api.request("GET", `/reading/random?max_level=${Prefs.maxLevel()}`);
  } catch (err) {
    if (err.reason) return showBanner(err.reason);
    $("reading-text").textContent = "";
    $("reading-title").textContent = "Lectura en voz alta";
    return showError(err.message);
  }

  renderExcerpt(current.excerpt);
  $("reading-title").textContent = current.title;

  const level = $("reading-level");
  if (current.level === null || current.level === undefined) {
    level.classList.add("hidden");
  } else {
    level.textContent = `Nivel ${current.level}`;
    level.classList.remove("hidden");
  }

  const source = $("reading-source");
  source.href = current.source_url;
  source.classList.remove("hidden");

  $("btn-record").disabled = false;
  $("btn-listen").disabled = false;
}

// Un <p> por párrafo: el extracto conserva los saltos del artículo original, y el HTML los
// colapsaría a un espacio si se pintara como texto plano.
function renderExcerpt(text) {
  const box = $("reading-text");
  box.innerHTML = "";
  for (const paragraph of text.split(/\n\s*\n/)) {
    if (!paragraph.trim()) continue;
    const p = document.createElement("p");
    p.textContent = paragraph.trim();
    box.appendChild(p);
  }
}
```

- [x] **Step 3: Añadir el botón de escuchar**

Añadir a `reading.js`, antes de los listeners del final:

```javascript
// ---- Escuchar el texto ----
// El mismo botón alterna entre leer y cortar, así siempre hay salida: nunca queda una voz
// sonando sin forma de pararla.
let listening = false;

function stopListening() {
  Tts.stop();
  listening = false;
  $("btn-listen").textContent = "🔊 Escuchar";
}

function toggleListen() {
  if (listening) return stopListening();
  listening = true;
  $("btn-listen").textContent = "⏹ Detener";
  Tts.speak(current.excerpt, { onend: stopListening });
}
```

- [x] **Step 4: Arreglar el 🔊 de cada palabra y cortar la voz al grabar**

En `renderReview`, sustituir la línea del callback vacío:

```javascript
  (result.words || []).forEach((word) => said.appendChild(renderWord(word, () => {})));
```

por:

```javascript
  (result.words || []).forEach((word) => said.appendChild(renderWord(word, (t) => Tts.speak(t))));
```

En la misma función, el panel izquierdo también debe conservar los párrafos. Sustituir el bloque que lo repinta:

```javascript
  const left = $("reading-text");
  left.innerHTML = "";
  (result.reference_text || current.excerpt).split(/\s+/).forEach((token) => {
    const bare = token.toLowerCase().replace(/[^a-z']/g, "");
    const span = document.createElement("span");
    span.textContent = token + " ";
    if (omitted.has(bare)) span.className = "omitted";
    left.appendChild(span);
  });
```

por:

```javascript
  const left = $("reading-text");
  left.innerHTML = "";
  for (const paragraph of (result.reference_text || current.excerpt).split(/\n\s*\n/)) {
    if (!paragraph.trim()) continue;
    const p = document.createElement("p");
    for (const token of paragraph.trim().split(/\s+/)) {
      const bare = token.toLowerCase().replace(/[^a-z']/g, "");
      const span = document.createElement("span");
      span.textContent = token + " ";
      if (omitted.has(bare)) span.className = "omitted";
      p.appendChild(span);
    }
    left.appendChild(p);
  }
```

En `toggleRecording`, añadir `stopListening();` justo después de `clearError();`, para que la voz se calle al abrir el micrófono.

- [x] **Step 5: Conectar el selector de nivel y los listeners**

Sustituir las tres últimas líneas del archivo:

```javascript
$("btn-record").addEventListener("click", toggleRecording);
$("btn-another").addEventListener("click", loadText);
loadText();
```

por:

```javascript
$("btn-record").addEventListener("click", toggleRecording);
$("btn-another").addEventListener("click", loadText);
$("btn-listen").addEventListener("click", toggleListen);
$("max-level").addEventListener("change", () => {
  Prefs.setMaxLevel($("max-level").value);
  loadText(); // el texto actual puede estar por encima del nuevo tope
});

Tts.load();
speechSynthesis.onvoiceschanged = () => Tts.load();
$("max-level").value = String(Prefs.maxLevel());
loadText();
```

- [x] **Step 6: Estilos**

Añadir a `app/web/static/app.css`:

```css
/* Cabecera del panel: el título del artículo y su botón de escuchar en la misma línea. */
.panel-head { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 4px; }
.panel-head h2 { font-size: 1.15rem; color: var(--ink); margin: 0; }
/* La meta va pegada al título, no suelta en el subtítulo de la página. */
.panel-meta { display: flex; align-items: center; gap: 10px; margin: 0 0 16px; font-size: .85rem; }
.panel-meta a { color: var(--muted); }
.panel-meta a:hover { color: var(--gold); }
.panel-body p { margin: 0 0 14px; }
.panel-body p:last-child { margin-bottom: 0; }
.inline-label { display: inline; font-size: .85rem; color: var(--muted); margin: 0 0 0 auto; }
.inline-select { width: auto; padding: 7px 10px; }
```

Y ajustar la regla del badge, que tenía un margen pensado para ir dentro de una frase:

```css
.badge { margin-left: 0; }
```

- [x] **Step 7: Verificar en Chrome**

Run: `uv run uvicorn app.cmd.server:app --port 8123` y abrir `http://localhost:8123/reading`.

Comprobar, uno por uno:
- La consola no tiene errores.
- El título del artículo sale dentro del panel izquierdo, en negrita, con el nivel y el enlace justo debajo.
- El texto se ve **separado en párrafos**, no como un bloque corrido.
- "🔊 Escuchar" lee el texto; el botón pasa a "⏹ Detener" y lo corta a mitad.
- Al pulsar "Otro texto" mientras suena, la voz se calla.
- Poniendo "Nivel máximo" en 4, el badge nunca muestra un número mayor que 4 al pedir textos nuevos.
- Al recargar, el nivel elegido sigue puesto.
- Tras evaluar, el 🔊 de una palabra la pronuncia.
- Tras evaluar, el panel izquierdo sigue teniendo párrafos separados y las omisiones tachadas.
- En ninguna pantalla aparece la palabra "Azure".

- [x] **Step 8: Correr la suite completa**

Run: `uv run pytest -q`
Expected: PASS.

- [x] **Step 9: Commit**

```bash
git add app/web/
git commit -m "feat(web): panel de lectura con parrafos, escuchar y filtro por nivel"
```

---

### Task 7: Documentación

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-08-06-practica-lectura-fase2-design.md`

- [x] **Step 1: Actualizar el README**

En la sección "Practica de lectura (modulo `app/`)", añadir después del párrafo del extracto:

```markdown
Puedes limitar la dificultad con el selector **Nivel maximo** de la pantalla: es un tope, no
un nivel exacto, asi que pedir 5 puede darte un 4 o un 5. Si no hay ningun texto que cumpla,
la app lo dice en vez de darte uno mas dificil.

> Esta version funciona solo en **Google Chrome** en computadora: las voces del tutor y el
> dictado por voz dependen de el.
```

- [x] **Step 2: Anotar el cambio de `make_excerpt` en el spec de la fase 2**

En `docs/superpowers/specs/2026-08-06-practica-lectura-fase2-design.md`, en la sección "Arquitectura", bajo la fila de `excerpt.py` de la tabla, añadir:

```markdown
**Actualización (pulido posterior):** `make_excerpt` devuelve un prefijo literal del cuerpo en
vez de un texto reconstruido, para conservar los saltos de párrafo del artículo. Sigue siendo
determinista, así que la decisión de no cachear el extracto se mantiene intacta. Ver
[2026-08-06-pulido-lectura-y-voces-design.md](2026-08-06-pulido-lectura-y-voces-design.md).
```

- [x] **Step 3: Commit**

```bash
git add README.md docs/
git commit -m "docs: filtro por nivel y requisito de Chrome"
```
