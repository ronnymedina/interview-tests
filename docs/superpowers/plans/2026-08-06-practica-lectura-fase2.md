# Práctica de lectura — fase 2: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que el usuario abra `/reading`, reciba un texto real del catálogo al azar, lo lea en voz alta, y Azure evalúe su pronunciación contra ese texto exacto.

**Architecture:** Se completa el módulo `app/reading/` (que hoy solo ingiere) con el recorte a extracto, la selección al azar, y un servicio que orquesta repositorio + límites + Azure. El extracto no se cachea en ninguna parte: el cliente devuelve el `reading_id` junto al audio y el servidor relee la fila y vuelve a cortar, porque `make_excerpt` es determinista. La evaluación usa el modo *scripted* de Azure (con `reference_text`), que habilita `completeness` y el miscue.

**Tech Stack:** Python 3.11+, FastAPI, psycopg 3 (async), Azure Cognitive Services Speech SDK, Jinja2, JS sin framework, pytest + Hypothesis.

**Spec:** [docs/superpowers/specs/2026-08-06-practica-lectura-fase2-design.md](../specs/2026-08-06-practica-lectura-fase2-design.md)

## Global Constraints

- **Toda variable de entorno se declara y se lee SOLO en `config.py`.** Ningún `os.getenv` fuera de ahí. El resto del código recibe valores ya tipados vía `from config import settings`.
- **Ningún test toca la red ni levanta una base de datos.** Se inyectan dobles.
- **Los tests viven en la raíz del repo**, con el prefijo `test_app_reading_*` / `test_app_speech_*`. Se corren con `uv run pytest`.
- **`app/reading` es asíncrono** (usa `AsyncPostgresStorage`). Dentro de un endpoint `async def`, todo lo bloqueante (SDK de Azure, `LimitsService`) va en `asyncio.to_thread`.
- **El DDL se escribe dos veces**: en `app/storage.py` (`_SCHEMA`) y en `docker/initdb/`. Si solo se toca una, divergen.
- **Los docstrings y comentarios van en español**, explicando el *porqué* de la decisión, siguiendo el estilo de los módulos existentes.
- Valores de configuración exactos: `READING_MAX_WORDS = 120`, `USER_READING_QUOTA = 10`, `RATE_LIMIT_READING_PER_MIN = 20`.

## File Structure

| Archivo | Responsabilidad | Task |
|---|---|---|
| `app/reading/excerpt.py` | **Crear.** `make_excerpt(body, max_words)`. Función pura, sin dependencias | 1 |
| `app/reading/repository.py` | **Modificar.** Sumar `random()` al `Protocol` y al adaptador Postgres | 2 |
| `app/storage.py` | **Modificar.** Tabla `reading_starts` en `_SCHEMA` | 3 |
| `docker/initdb/05-reading-starts.sql` | **Crear.** La misma DDL | 3 |
| `app/limits/repository.py` | **Modificar.** `add_reading_start()` y `reading_count()` en `UsageStore` | 4 |
| `app/limits/service.py` | **Modificar.** `check_can_read()` y `record_reading_start()` | 4 |
| `app/speech/azure_client.py` | **Modificar.** `make_omission_word()` (migrado del legacy) | 5 |
| `app/speech/assessment.py` | **Modificar.** `assess_scripted(wav_path, reference_text, client)` | 5 |
| `app/reading/service.py` | **Crear.** `ReadingService` con `random_excerpt()` y `assess()` | 6 |
| `app/cmd/server.py` | **Modificar.** Endpoints, dependencias, rate-limit scopes | 7, 8 |
| `app/web/templates/reading.html` | **Crear.** La pantalla dividida | 9 |
| `app/web/static/reading.js` | **Crear.** Lógica propia de la pantalla | 9 |
| `app/web/templates/base.html` | **Modificar.** Navegación entre modalidades | 9 |
| `app/web/static/app.css` | **Modificar.** Estilos del layout de dos paneles | 9 |
| `config.py` | **Modificar.** Las tres variables nuevas | 1, 4, 8 |

Orden: las tareas 1-5 son unidades independientes y sin dependencias entre sí (se pueden hacer en cualquier orden); 6 las compone; 7-8 las exponen por HTTP; 9 es el frontend.

---

### Task 1: `make_excerpt` — recorte a extracto

Corta el cuerpo de un artículo al primer límite de oración que no pase de `max_words` palabras. Es una función pura: sin BD, sin red, sin config. Se prueba con Hypothesis porque las propiedades ("nunca excede el máximo", "nunca parte una palabra") valen para *cualquier* texto, no solo para los tres ejemplos que se nos ocurran.

**Files:**
- Create: `app/reading/excerpt.py`
- Modify: `config.py` (agregar `READING_MAX_WORDS`)
- Test: `test_app_reading_excerpt.py`

**Interfaces:**
- Consumes: nada.
- Produces: `make_excerpt(body: str, max_words: int) -> str`. Devuelve `""` si `body` no tiene palabras.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `test_app_reading_excerpt.py`:

```python
"""Propiedades y casos concretos de make_excerpt (función pura, sin BD ni red)."""

from hypothesis import given, strategies as st

from app.reading.excerpt import make_excerpt


def test_corta_en_limite_de_oracion():
    body = "One two three. Four five six. Seven eight nine."
    # Con 7 palabras de tope entran las dos primeras oraciones (6 palabras);
    # la tercera las llevaría a 9, así que se descarta entera.
    assert make_excerpt(body, 7) == "One two three. Four five six."


def test_devuelve_el_cuerpo_entero_si_ya_cabe():
    body = "One two three. Four five."
    assert make_excerpt(body, 100) == body


def test_primera_oracion_mas_larga_que_el_tope_corta_por_palabras():
    body = "One two three four five six seven eight."
    # No hay ningún límite de oración que quepa: se corta en la última palabra completa.
    assert make_excerpt(body, 3) == "One two three"


def test_cuerpo_vacio_da_extracto_vacio():
    assert make_excerpt("", 10) == ""
    assert make_excerpt("   \n  ", 10) == ""


def test_respeta_signos_de_interrogacion_y_exclamacion():
    body = "Is this real? Yes it is! And more words here."
    assert make_excerpt(body, 7) == "Is this real? Yes it is!"


@given(
    body=st.text(min_size=0, max_size=500),
    max_words=st.integers(min_value=1, max_value=50),
)
def test_nunca_excede_el_maximo_de_palabras(body, max_words):
    assert len(make_excerpt(body, max_words).split()) <= max_words


@given(
    body=st.text(min_size=0, max_size=500),
    max_words=st.integers(min_value=1, max_value=50),
)
def test_todas_las_palabras_del_extracto_estan_en_el_cuerpo(body, max_words):
    """Nunca parte una palabra por la mitad ni inventa texto."""
    original = body.split()
    for word in make_excerpt(body, max_words).split():
        assert word in original


@given(
    body=st.text(min_size=1, max_size=500),
    max_words=st.integers(min_value=1, max_value=50),
)
def test_es_determinista(body, max_words):
    """Es la propiedad de la que depende que no haga falta cachear el extracto."""
    assert make_excerpt(body, max_words) == make_excerpt(body, max_words)
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `uv run pytest test_app_reading_excerpt.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.reading.excerpt'`

- [ ] **Step 3: Implementar `make_excerpt`**

Crear `app/reading/excerpt.py`:

```python
"""Recorte del artículo completo al fragmento que el usuario lee en voz alta.

Función pura a propósito: no toca la base, ni la config, ni la red. Eso es lo que permite
recalcular el extracto en la evaluación en vez de guardarlo en una caché en memoria — dado
el mismo cuerpo y el mismo tope, devuelve siempre exactamente el mismo texto, así que el
servidor puede reconstruir el texto que le mostró al usuario a partir del `reading_id`.
"""

import re

# Corta después de . ? o ! seguidos de espacio. No usamos un tokenizador de oraciones real
# (nltk, spacy) porque sería una dependencia pesada para una heurística que, si falla en una
# abreviatura ("Dr. Smith"), solo produce un extracto un poco más corto.
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def make_excerpt(body: str, max_words: int) -> str:
    """Devuelve el fragmento inicial de `body` que no pasa de `max_words` palabras.

    Corta en el último límite de oración que quepa, para que el usuario lea algo con sentido
    y no una frase truncada a media idea. Si ni la primera oración cabe, corta por palabras:
    un extracto algo abrupto es mejor que uno vacío.
    """
    words = body.split()
    if not words:
        return ""
    if len(words) <= max_words:
        return body.strip()

    excerpt = ""
    count = 0
    for sentence in _SENTENCE_END.split(body.strip()):
        sentence_words = len(sentence.split())
        if count + sentence_words > max_words:
            break
        excerpt = f"{excerpt} {sentence}".strip() if excerpt else sentence
        count += sentence_words

    if not excerpt:
        # Ni la primera oración cabe: se corta en la última palabra completa.
        return " ".join(words[:max_words])
    return excerpt
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `uv run pytest test_app_reading_excerpt.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 5: Agregar `READING_MAX_WORDS` a la config**

En `config.py`, dentro del bloque `# --- Practica de lectura`, agregar junto a las otras `READING_*`:

```python
    # Tamano del extracto que se lee en voz alta. 120 palabras son ~40-60 s de lectura:
    # suficiente para que Azure tenga senal, y corto para que el usuario no se canse.
    READING_MAX_WORDS: int = Field(default=120, gt=0)
```

- [ ] **Step 6: Correr la suite completa**

Run: `uv run pytest -q`
Expected: PASS, sin regresiones.

- [ ] **Step 7: Commit**

```bash
git add app/reading/excerpt.py test_app_reading_excerpt.py config.py
git commit -m "feat(reading): make_excerpt recorta el articulo en limite de oracion"
```

---

### Task 2: `random()` en el repositorio

El repositorio hoy solo sabe insertar y contar. Necesita entregar una fila al azar. No se cuenta primero y se elige después: `ORDER BY random() LIMIT 1` lo resuelve en una consulta.

**Files:**
- Modify: `app/reading/repository.py`
- Test: `test_app_reading_repository.py`

**Interfaces:**
- Consumes: `ReadingText` de `app/reading/model.py` (dataclass con `source`, `source_url`, `title`, `body`, `level`, `category`, `published_at` y la property `word_count`).
- Produces:
  - `ReadingTextStore.random() -> StoredReadingText | None` (nuevo método del `Protocol`)
  - `ReadingTextStore.get(reading_id: int) -> StoredReadingText | None`
  - `StoredReadingText`: dataclass congelada con `id: int` y `text: ReadingText`.

- [ ] **Step 1: Escribir el test que falla**

Crear `test_app_reading_repository.py`:

```python
"""El doble en memoria de ReadingTextStore: contrato que consumen la ingesta y el servicio.

No hay test contra Postgres real acá a propósito (la suite no levanta base); lo que se
verifica es que el doble cumpla el Protocol, para que inyectarlo en los tests del servicio
sea representativo.
"""

from app.reading.model import ReadingText
from app.reading.repository import ReadingTextStore, StoredReadingText


class InMemoryReadingTextStore:
    """Doble en memoria de ReadingTextStore. `random()` devuelve el primero, no uno al azar:
    un test que dependiera del azar sería un test que falla de vez en cuando."""

    def __init__(self, texts=None):
        self._rows = {}
        self._next_id = 1
        if texts:
            for text in texts:
                self._rows[self._next_id] = text
                self._next_id += 1

    async def upsert_many(self, texts):
        from app.reading.repository import UpsertResult
        inserted = 0
        for text in texts:
            self._rows[self._next_id] = text
            self._next_id += 1
            inserted += 1
        return UpsertResult(inserted=inserted, updated=0)

    async def count(self):
        return len(self._rows)

    async def random(self):
        if not self._rows:
            return None
        reading_id = next(iter(self._rows))
        return StoredReadingText(id=reading_id, text=self._rows[reading_id])

    async def get(self, reading_id):
        text = self._rows.get(reading_id)
        return None if text is None else StoredReadingText(id=reading_id, text=text)


def a_text(title="A title", body="One two three."):
    return ReadingText(source="engoo", source_url=f"https://x/{title}", title=title, body=body)


def test_el_doble_cumple_el_protocol():
    assert isinstance(InMemoryReadingTextStore(), ReadingTextStore)


async def test_random_devuelve_none_con_catalogo_vacio():
    assert await InMemoryReadingTextStore().random() is None


async def test_random_devuelve_id_y_texto():
    store = InMemoryReadingTextStore([a_text()])
    stored = await store.random()
    assert stored.id == 1
    assert stored.text.title == "A title"


async def test_get_devuelve_none_si_el_id_no_existe():
    assert await InMemoryReadingTextStore([a_text()]).get(999) is None


async def test_get_devuelve_el_texto_por_id():
    store = InMemoryReadingTextStore([a_text(title="Uno"), a_text(title="Dos")])
    stored = await store.get(2)
    assert stored.text.title == "Dos"
```

Los tests `async` necesitan que pytest sepa correrlos. Si `uv run pytest` reporta que se saltan corrutinas, agregar al final de `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
```

y `pytest-asyncio>=1.0` al grupo `dev` de `[dependency-groups]`, luego `uv sync`.

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `uv run pytest test_app_reading_repository.py -v`
Expected: FAIL con `ImportError: cannot import name 'StoredReadingText'`

- [ ] **Step 3: Implementar en `app/reading/repository.py`**

Agregar el import y la dataclass después de `UpsertResult`:

```python
@dataclass(frozen=True)
class StoredReadingText:
    """Un texto del catálogo junto con su id de base de datos.

    `ReadingText` no lleva id porque las fuentes producen textos que todavía no existen en la
    base. Una vez guardado, el id es lo que viaja al navegador y lo que permite recuperar el
    mismo texto al evaluar el audio, sin que el cliente mande el texto de referencia.
    """

    id: int
    text: ReadingText
```

Agregar al `Protocol ReadingTextStore`:

```python
    async def random(self) -> "StoredReadingText | None":
        """Un texto al azar del catálogo, o None si está vacío."""
        ...

    async def get(self, reading_id: int) -> "StoredReadingText | None":
        """El texto con ese id, o None si no existe."""
        ...
```

Agregar a `PostgresReadingTextStore`:

```python
    _COLUMNS = (
        "id, source, source_url, title, level, category, published_at, body"
    )

    async def random(self) -> StoredReadingText | None:
        """Una fila al azar.

        `ORDER BY random()` escanea la tabla entera, lo que sería un problema con millones de
        filas pero es irrelevante con las decenas o pocos cientos que produce la ingesta. La
        alternativa (contar y elegir un offset) cuesta dos viajes y se desincroniza si la
        ingesta inserta entre medio. Si el catálogo creciera de verdad, esto pasa a
        TABLESAMPLE.
        """
        async with self._storage.connect() as conn:
            row = await (
                await conn.execute(
                    f"SELECT {self._COLUMNS} FROM reading_texts ORDER BY random() LIMIT 1"
                )
            ).fetchone()
        return None if row is None else self._to_stored(row)

    async def get(self, reading_id: int) -> StoredReadingText | None:
        async with self._storage.connect() as conn:
            row = await (
                await conn.execute(
                    f"SELECT {self._COLUMNS} FROM reading_texts WHERE id = %s", (reading_id,)
                )
            ).fetchone()
        return None if row is None else self._to_stored(row)

    @staticmethod
    def _to_stored(row) -> StoredReadingText:
        return StoredReadingText(
            id=row["id"],
            text=ReadingText(
                source=row["source"],
                source_url=row["source_url"],
                title=row["title"],
                body=row["body"],
                level=row["level"],
                category=row["category"],
                published_at=row["published_at"],
            ),
        )
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `uv run pytest test_app_reading_repository.py -v`
Expected: PASS, 5 tests.

- [ ] **Step 5: Correr la suite completa**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/reading/repository.py test_app_reading_repository.py pyproject.toml
git commit -m "feat(reading): random() y get() en el repositorio del catalogo"
```

---

### Task 3: Tabla `reading_starts`

Espejo de `conversation_starts`. Una fila por evaluación, sin contenido: ni el audio ni el resultado se guardan. Solo sirve para contar la cuota del usuario.

**Files:**
- Modify: `app/storage.py` (dentro de `_SCHEMA`)
- Create: `docker/initdb/05-reading-starts.sql`
- Test: `test_app_reading_starts_schema.py`

**Interfaces:**
- Consumes: nada.
- Produces: la tabla `reading_starts (id, created_at, user_id, reading_id)`, consumida por Task 4.

- [ ] **Step 1: Escribir el test que falla**

Crear `test_app_reading_starts_schema.py`, siguiendo el patrón de `test_app_reading_texts.py`:

```python
"""El DDL de reading_starts está duplicado (código + init del contenedor): estos tests
existen para que no diverjan en silencio."""

from pathlib import Path

from app.storage import _SCHEMA

_SQL_FILE = Path(__file__).parent / "docker" / "initdb" / "05-reading-starts.sql"


def _statement():
    for statement in _SCHEMA:
        if "reading_starts" in statement and "CREATE TABLE" in statement:
            return statement
    raise AssertionError("reading_starts no está en _SCHEMA")


def test_schema_incluye_reading_starts():
    ddl = _statement()
    assert "user_id" in ddl
    assert "reading_id" in ddl


def test_no_guarda_contenido():
    """La cuota se cuenta sin persistir ni el audio ni el resultado del assessment."""
    ddl = _statement().lower()
    for forbidden in ("body", "excerpt", "audio", "scores", "words"):
        assert forbidden not in ddl


def test_hay_indice_por_user_id():
    """Sin él, contar la cuota escanea la tabla entera en cada evaluación."""
    assert any(
        "CREATE INDEX" in s and "reading_starts" in s and "user_id" in s for s in _SCHEMA
    )


def test_el_sql_del_contenedor_coincide_con_el_schema():
    sql = _SQL_FILE.read_text()
    assert "CREATE TABLE IF NOT EXISTS reading_starts" in sql
    assert "reading_starts_user_idx" in sql
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `uv run pytest test_app_reading_starts_schema.py -v`
Expected: FAIL con `AssertionError: reading_starts no está en _SCHEMA`

- [ ] **Step 3: Agregar el DDL en los dos sitios**

En `app/storage.py`, al final de la tupla `_SCHEMA` (después del índice de `reading_texts`):

```python
    """
    CREATE TABLE IF NOT EXISTS reading_starts (
        id         INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        user_id    TEXT NOT NULL,
        reading_id INTEGER NOT NULL
    );
    """,
    """
    CREATE INDEX IF NOT EXISTS reading_starts_user_idx ON reading_starts (user_id);
    """,
```

Crear `docker/initdb/05-reading-starts.sql`:

```sql
-- Cuota de la practica de lectura: una fila por evaluacion.
-- No guarda contenido (ni audio ni resultado del assessment), solo la contabilidad.
-- Sin FK a reading_texts a proposito: si un articulo desaparece del catalogo, borrar en
-- cascada un registro de cuota ya cobrada seria incorrecto.
CREATE TABLE IF NOT EXISTS reading_starts (
    id         INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    user_id    TEXT NOT NULL,
    reading_id INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS reading_starts_user_idx ON reading_starts (user_id);
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `uv run pytest test_app_reading_starts_schema.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add app/storage.py docker/initdb/05-reading-starts.sql test_app_reading_starts_schema.py
git commit -m "feat(reading): tabla reading_starts para la cuota de lectura"
```

---

### Task 4: Cuota de lectura en `app/limits`

La lectura no consume las conversaciones del usuario (son modalidades distintas), pero su costo de Azure sí entra al mismo presupuesto diario y total. Eso se traduce en: contador propio, presupuesto compartido.

**Files:**
- Modify: `app/limits/repository.py`
- Modify: `app/limits/service.py`
- Modify: `config.py`
- Test: `test_app_limits_service.py` (agregar casos)

**Interfaces:**
- Consumes: `Decision`, `DecisionKind` de `app/limits/model.py`; `UsageStore` de `app/limits/repository.py`.
- Produces:
  - `LimitsService.check_can_read(user_id: str) -> Decision`
  - `LimitsService.record_reading_start(user_id: str, reading_id: int) -> None`
  - `LimitsService.record_azure_usage(user_id, conversation_id, audio_seconds) -> float` — ya existe, se reutiliza pasando `str(reading_id)` como `conversation_id`.
  - `UsageStore.add_reading_start(user_id: str, reading_id: int) -> None`
  - `UsageStore.reading_count(user_id: str) -> int`

- [ ] **Step 1: Escribir los tests que fallan**

Añadir a `test_app_limits_service.py` (mirar primero cómo está definido el doble de `UsageStore` en ese archivo y extenderlo con `add_reading_start` / `reading_count`, siguiendo su estilo):

```python
def test_check_can_read_permite_dentro_de_la_cuota(monkeypatch):
    monkeypatch.setattr(settings, "USER_READING_QUOTA", 3)
    store = FakeStore(reading_starts=2)
    assert LimitsService(store).check_can_read("u1").allowed


def test_check_can_read_corta_al_llegar_a_la_cuota(monkeypatch):
    monkeypatch.setattr(settings, "USER_READING_QUOTA", 3)
    store = FakeStore(reading_starts=3)
    decision = LimitsService(store).check_can_read("u1")
    assert not decision.allowed
    assert decision.reason == "quota"


def test_la_cuota_de_lectura_es_independiente_de_la_de_conversacion(monkeypatch):
    """Leer no debe gastarte las conversaciones: son modalidades distintas."""
    monkeypatch.setattr(settings, "USER_CONVERSATION_QUOTA", 1)
    monkeypatch.setattr(settings, "USER_READING_QUOTA", 5)
    store = FakeStore(conversation_starts=1, reading_starts=0)
    service = LimitsService(store)
    assert not service.check_can_start("u1").allowed
    assert service.check_can_read("u1").allowed


def test_el_presupuesto_total_corta_la_lectura(monkeypatch):
    """El dinero sí es uno solo: si el presupuesto global está agotado, no se lee."""
    monkeypatch.setattr(settings, "TOTAL_BUDGET_USD", 1.0)
    store = FakeStore(total_cost=1.0)
    decision = LimitsService(store).check_can_read("u1")
    assert not decision.allowed
    assert decision.reason == "paused"


def test_record_reading_start_registra_la_fila():
    store = FakeStore()
    LimitsService(store).record_reading_start("u1", 42)
    assert store.reading_rows == [("u1", 42)]
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `uv run pytest test_app_limits_service.py -v`
Expected: FAIL con `AttributeError: 'LimitsService' object has no attribute 'check_can_read'`

- [ ] **Step 3: Agregar `USER_READING_QUOTA` a `config.py`**

Junto a `USER_CONVERSATION_QUOTA`:

```python
    # Evaluaciones de lectura por usuario. Contador propio: leer no debe gastar las
    # conversaciones del usuario, son modalidades distintas y mezclarlas seria confuso.
    # El presupuesto en dolares si es compartido (ver LimitsService.check_can_read).
    USER_READING_QUOTA: int = Field(default=10, gt=0)
```

- [ ] **Step 4: Extender `UsageStore` y su adaptador Postgres**

En `app/limits/repository.py`, agregar al `Protocol UsageStore`:

```python
    def add_reading_start(self, user_id: str, reading_id: int) -> None:
        """Registra una evaluación de lectura (cuenta para la cuota de lectura)."""
        ...

    def reading_count(self, user_id: str) -> int:
        """Cuántas lecturas evaluó ya este usuario."""
        ...
```

Y a `PostgresUsageStore`:

```python
    def add_reading_start(self, user_id: str, reading_id: int) -> None:
        with self._storage.connect() as conn:
            conn.execute(
                "INSERT INTO reading_starts (user_id, reading_id) VALUES (%s, %s)",
                (user_id, reading_id),
            )

    def reading_count(self, user_id: str) -> int:
        with self._storage.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM reading_starts WHERE user_id = %s",
                (user_id,),
            ).fetchone()
        assert row is not None
        return int(row["n"])
```

- [ ] **Step 5: Agregar los métodos a `LimitsService`**

En `app/limits/service.py`, después de `check_can_start`:

```python
    def check_can_read(self, user_id: str) -> Decision:
        """Decide si `user_id` puede evaluar una lectura.

        Misma precedencia que `check_can_start` (tope total → presupuesto diario → cuota),
        pero contra el contador de lecturas. El presupuesto en dólares es el mismo para las
        dos modalidades porque el dinero es uno solo; la cuota es distinta porque leer y
        conversar son prácticas separadas.
        """
        if self._store.total_cost_usd() >= settings.TOTAL_BUDGET_USD:
            return Decision(DecisionKind.PAUSED_TOTAL)
        if self._store.daily_cost_usd() >= settings.DAILY_BUDGET_USD:
            return Decision(DecisionKind.PAUSED_DAILY)
        if self._store.reading_count(user_id) >= settings.USER_READING_QUOTA:
            return Decision(DecisionKind.QUOTA)
        return Decision(DecisionKind.ALLOW)

    def record_reading_start(self, user_id: str, reading_id: int) -> None:
        """Registra una evaluación de lectura (cuenta para la cuota del usuario)."""
        self._store.add_reading_start(user_id, reading_id)
```

- [ ] **Step 6: Correr los tests y verificar que pasan**

Run: `uv run pytest test_app_limits_service.py -v`
Expected: PASS.

- [ ] **Step 7: Correr la suite completa**

Run: `uv run pytest -q`
Expected: PASS. Si `test_app_limits_repository.py` tiene un doble de `UsageStore` que ahora no cumple el `Protocol`, extenderlo con los dos métodos nuevos.

- [ ] **Step 8: Commit**

```bash
git add app/limits/ config.py test_app_limits_service.py test_app_limits_repository.py
git commit -m "feat(limits): cuota propia de lectura con presupuesto compartido"
```

---

### Task 5: `assess_scripted` — evaluación contra texto de referencia

El modo *scripted* es lo que habilita `completeness` y el miscue. Azure no marca omisiones ni inserciones en modo continuo, así que se derivan comparando lo reconocido contra el texto de referencia con `difflib`, igual que el sample oficial. Todo esto ya existe en `speech.py` de la raíz (el legacy): se migra, sumando `audio_seconds` para el cálculo de costo, que el legacy no tenía.

**Files:**
- Modify: `app/speech/azure_client.py` (agregar `make_omission_word`)
- Modify: `app/speech/assessment.py` (agregar `assess_scripted` y `_aggregate_scripted`)
- Modify: `app/speech/__init__.py` (exportar `assess_scripted`)
- Test: `test_app_speech_scripted.py`
- Reference: `speech.py:27-127` y `azure_speech.py:127-131` en la raíz del repo

**Interfaces:**
- Consumes: `AzureSpeechClient` y `AzureSpeechError` de `app/speech/azure_client.py`; `SpeechError` de `app/speech/assessment.py`.
- Produces: `assess_scripted(wav_path: str, reference_text: str, client: AzureSpeechClient | None = None) -> dict` devolviendo `{"recognized_text": str, "scores": {"pronunciation", "accuracy", "fluency", "completeness", "prosody"}, "words": [ {"word", "accuracy", "error_type", "phonemes"} ], "audio_seconds": float}`.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `test_app_speech_scripted.py`:

```python
"""Caracteriza assess_scripted con un cliente Azure falso (sin red).

Reusa los helpers de test_app_speech_assessment.py: mismo formato de `state` crudo.
"""

import pytest

from config import settings
from app.speech import assessment
from app.speech.azure_client import AzureSpeechError
from test_app_speech_assessment import FakeClient, make_state, rec_word


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setattr(settings, "AZURE_SPEECH_KEY", "test-key")


def test_manda_el_texto_de_referencia_normalizado():
    """Azure espera palabras en minúscula sin puntuación."""
    state = make_state([rec_word("hello", 95.0)], ["hello"], durations=[500000], end=600000)
    client = FakeClient(state)
    assessment.assess_scripted("a.wav", "Hello, world!", client=client)
    assert client.called_with == ("a.wav", "hello world")


def test_referencia_sin_palabras_es_error_400():
    with pytest.raises(assessment.SpeechError) as exc:
        assessment.assess_scripted("a.wav", "  ...  ", client=FakeClient(make_state([], [])))
    assert exc.value.status == 400


def test_palabra_no_dicha_se_marca_como_omision():
    state = make_state([rec_word("hello", 95.0)], ["hello"], durations=[500000], end=600000)
    result = assessment.assess_scripted("a.wav", "hello world", client=FakeClient(state))
    errors = {w["word"]: w["error_type"] for w in result["words"]}
    assert errors["world"] == "Omission"


def test_palabra_de_mas_se_marca_como_insercion():
    state = make_state(
        [rec_word("hello", 95.0), rec_word("there", 90.0), rec_word("world", 92.0)],
        ["hello there world"], durations=[300000, 300000, 300000], end=1_000_000,
    )
    result = assessment.assess_scripted("a.wav", "hello world", client=FakeClient(state))
    errors = {w["word"]: w["error_type"] for w in result["words"]}
    assert errors["there"] == "Insertion"


def test_lectura_perfecta_da_completeness_100():
    state = make_state(
        [rec_word("hello", 95.0), rec_word("world", 92.0)],
        ["hello world"], durations=[400000, 400000], end=1_000_000,
    )
    result = assessment.assess_scripted("a.wav", "hello world", client=FakeClient(state))
    assert result["scores"]["completeness"] == 100.0


def test_completeness_baja_con_omisiones():
    state = make_state([rec_word("hello", 95.0)], ["hello"], durations=[500000], end=600000)
    result = assessment.assess_scripted("a.wav", "hello world", client=FakeClient(state))
    assert result["scores"]["completeness"] == 50.0


def test_accuracy_baja_sin_otro_error_es_mispronunciation():
    state = make_state(
        [rec_word("hello", 95.0), rec_word("world", 40.0)],
        ["hello world"], durations=[400000, 400000], end=1_000_000,
    )
    result = assessment.assess_scripted("a.wav", "hello world", client=FakeClient(state))
    errors = {w["word"]: w["error_type"] for w in result["words"]}
    assert errors["world"] == "Mispronunciation"


def test_devuelve_audio_seconds_para_el_costo():
    """El legacy no lo tenía; acá hace falta para cobrar el uso de Azure."""
    state = make_state(
        [rec_word("hello", 95.0)], ["hello"], durations=[500000], start=0, end=10_000_000,
    )
    result = assessment.assess_scripted("a.wav", "hello", client=FakeClient(state))
    assert result["audio_seconds"] == 1.0


def test_azure_cancelado_es_502():
    client = FakeClient(error=AzureSpeechError("boom"))
    with pytest.raises(assessment.SpeechError) as exc:
        assessment.assess_scripted("a.wav", "hello", client=client)
    assert exc.value.status == 502


def test_sin_voz_detectada_es_422():
    client = FakeClient(make_state([], []))
    with pytest.raises(assessment.SpeechError) as exc:
        assessment.assess_scripted("a.wav", "hello", client=client)
    assert exc.value.status == 422
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `uv run pytest test_app_speech_scripted.py -v`
Expected: FAIL con `AttributeError: module 'app.speech.assessment' has no attribute 'assess_scripted'`

- [ ] **Step 3: Agregar `make_omission_word` a `AzureSpeechClient`**

En `app/speech/azure_client.py`, como `@staticmethod`, justo antes de `word_to_dict`:

```python
    @staticmethod
    def make_omission_word(text: str) -> "speechsdk.PronunciationAssessmentWordResult":
        """Crea un objeto-palabra sintético marcado como omisión (no se pronunció).

        Azure no reporta las palabras que el usuario se saltó: solo devuelve lo que oyó. Las
        omisiones se derivan comparando contra el texto de referencia, y hacen falta como
        objetos del SDK para que el resto del agregado los trate igual que a los reales.
        """
        return speechsdk.PronunciationAssessmentWordResult(
            {"Word": text, "PronunciationAssessment": {"ErrorType": "Omission"}}
        )
```

- [ ] **Step 4: Implementar `assess_scripted`**

En `app/speech/assessment.py`, agregar los imports `difflib` y `string` arriba, y estas dos funciones al final:

```python
def assess_scripted(
    wav_path: str, reference_text: str, client: AzureSpeechClient | None = None
) -> dict:
    """Evalúa un WAV CONTRA un texto de referencia (modo scripted).

    Es lo que usa la práctica de lectura. A diferencia del modo libre, acá sí hay
    `completeness` y miscue (omisiones/inserciones), que es justamente la señal que importa
    cuando el usuario lee algo escrito. `client` permite inyectar un doble en los tests.
    """
    if not settings.AZURE_SPEECH_KEY:
        raise SpeechError(
            "Falta AZURE_SPEECH_KEY en el archivo .env. Copia .env.example a .env "
            "y pon tu clave de Azure.",
            status=500,
        )

    # Azure espera la referencia en minúscula y sin puntuación; es además la forma en que
    # comparamos para detectar omisiones e inserciones.
    reference_words = [w.strip(string.punctuation) for w in reference_text.lower().split()]
    reference_words = [w for w in reference_words if w.strip()]
    if not reference_words:
        raise SpeechError("El texto de referencia no tiene palabras.", status=400)

    if client is None:
        client = AzureSpeechClient(
            settings.AZURE_SPEECH_KEY, settings.AZURE_SPEECH_REGION, settings.SPEECH_LANGUAGE
        )

    try:
        state = client.recognize(wav_path, " ".join(reference_words))
    except AzureSpeechError as error:
        raise SpeechError(f"Azure canceló la petición: {error}", status=502)

    if not state["words"]:
        raise SpeechError(
            "No se detectó voz en el audio. Revisa el micrófono e intenta de nuevo.",
            status=422,
        )

    return _aggregate_scripted(state, reference_words)


def _aggregate_scripted(state: dict, reference_words: list[str]) -> dict:
    """Combina los segmentos contra la referencia, con la lógica del sample oficial."""
    recognized = state["words"]

    # Azure no marca omisiones/inserciones en modo continuo: se derivan alineando lo
    # reconocido con el texto de referencia.
    diff = difflib.SequenceMatcher(
        None, reference_words, [w.word.lower() for w in recognized]
    )
    final_words = []
    for tag, i1, i2, j1, j2 in diff.get_opcodes():
        if tag in ("insert", "replace"):
            for word in recognized[j1:j2]:
                word._error_type = "Insertion"
                final_words.append(word)
        if tag in ("delete", "replace"):
            for word_text in reference_words[i1:i2]:
                final_words.append(AzureSpeechClient.make_omission_word(word_text))
        if tag == "equal":
            final_words.extend(recognized[j1:j2])

    # Accuracy por debajo de 60 sin otro error = mala pronunciación.
    for word in final_words:
        if word.error_type == "None" and word.accuracy_score < 60:
            word._error_type = "Mispronunciation"

    scored = [w for w in final_words if w.error_type != "Insertion"]
    accuracy = sum(w.accuracy_score for w in scored) / len(scored)

    prosody = (
        sum(state["prosody_scores"]) / len(state["prosody_scores"])
        if state["prosody_scores"]
        else None
    )

    span = state["end_offset"] - state["start_offset"]
    fluency = sum(state["durations"]) / span * 100 if span > 0 else 0.0

    correct = [w for w in final_words if w.error_type == "None"]
    completeness = min(100.0, len(correct) / len(scored) * 100) if scored else 0.0

    # Fórmula oficial: el peor score pesa más. Con prosodia son cuatro dimensiones.
    if prosody is not None:
        ordered = sorted([accuracy, prosody, completeness, fluency])
        pronunciation = ordered[0] * 0.4 + sum(ordered[1:]) * 0.2
    else:
        ordered = sorted([accuracy, fluency, completeness])
        pronunciation = ordered[0] * 0.6 + ordered[1] * 0.2 + ordered[2] * 0.2

    return {
        "recognized_text": " ".join(state["texts"]),
        "scores": {
            "pronunciation": round(pronunciation, 1),
            "accuracy": round(accuracy, 1),
            "fluency": round(fluency, 1),
            "completeness": round(completeness, 1),
            "prosody": round(prosody, 1) if prosody is not None else None,
        },
        "words": [AzureSpeechClient.word_to_dict(w) for w in final_words],
        # No estaba en el legacy: acá hace falta para cobrar el uso de Azure al presupuesto.
        "audio_seconds": round(max(0, span) / _TICKS_PER_SECOND, 3),
    }
```

- [ ] **Step 5: Exportar desde `app/speech/__init__.py`**

```python
from app.speech.assessment import SpeechError, assess_scripted
from app.speech.service import SpeechService, build_speech_service

__all__ = ["SpeechService", "SpeechError", "assess_scripted", "build_speech_service"]
```

- [ ] **Step 6: Correr los tests y verificar que pasan**

Run: `uv run pytest test_app_speech_scripted.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 7: Correr la suite completa**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/speech/ test_app_speech_scripted.py
git commit -m "feat(speech): assess_scripted evalua contra un texto de referencia"
```

---

### Task 6: `ReadingService` — la orquestación

Compone repositorio + extracto + Azure. Es donde vive la decisión central del diseño: al evaluar, el texto de referencia se **recalcula** desde la base con el `reading_id`, nunca lo manda el cliente ni se guarda en memoria.

**Files:**
- Create: `app/reading/service.py`
- Modify: `app/reading/__init__.py`
- Test: `test_app_reading_service.py`

**Interfaces:**
- Consumes: `ReadingTextStore`, `StoredReadingText` (Task 2); `make_excerpt` (Task 1); `assess_scripted` (Task 5); `ReadingText` de `app/reading/model.py`.
- Produces:
  - `ReadingError(Exception)` con atributo `.status: int`
  - `ReadingService(store, assess_fn=None)` donde `assess_fn: Callable[[str, str], dict]` recibe `(wav_path, reference_text)`
  - `async ReadingService.random_excerpt() -> dict` → `{"reading_id", "title", "level", "source_url", "excerpt", "word_count"}`
  - `async ReadingService.assess(reading_id: int, audio_bytes: bytes) -> dict` → lo que devuelve `assess_scripted` más `"reference_text"`
  - `build_reading_service(storage: AsyncPostgresStorage) -> ReadingService`

- [ ] **Step 1: Escribir los tests que fallan**

Crear `test_app_reading_service.py`:

```python
"""El servicio de lectura, con repositorio en memoria y Azure falso (sin BD ni red).

El test que más importa es el último: que el texto de referencia se recalcule desde la base
y no dependa de nada que el cliente mande ni de estado guardado en el proceso.
"""

import pytest

from config import settings
from app.reading.model import ReadingText
from app.reading.service import ReadingError, ReadingService
from test_app_reading_repository import InMemoryReadingTextStore


BODY = "One two three. Four five six. Seven eight nine. Ten eleven twelve."


def a_text(title="Daily news", body=BODY, level=5):
    return ReadingText(
        source="engoo",
        source_url="https://engoo.com/a",
        title=title,
        body=body,
        level=level,
        category="World",
        published_at="2026-08-01",
    )


class FakeAssess:
    """Doble de assess_scripted: registra con qué referencia lo llamaron."""

    def __init__(self, result=None, error=None):
        self._result = result or {"scores": {"pronunciation": 90.0}, "words": [],
                                  "recognized_text": "one two three", "audio_seconds": 3.0}
        self._error = error
        self.called_with = None

    def __call__(self, wav_path, reference_text):
        self.called_with = (wav_path, reference_text)
        if self._error:
            raise self._error
        return self._result


@pytest.fixture(autouse=True)
def _max_words(monkeypatch):
    monkeypatch.setattr(settings, "READING_MAX_WORDS", 6)


async def test_random_excerpt_devuelve_el_texto_recortado():
    service = ReadingService(InMemoryReadingTextStore([a_text()]), assess_fn=FakeAssess())
    result = await service.random_excerpt()
    assert result["excerpt"] == "One two three. Four five six."
    assert result["word_count"] == 6
    assert result["title"] == "Daily news"
    assert result["level"] == 5
    assert result["reading_id"] == 1


async def test_catalogo_vacio_es_503():
    service = ReadingService(InMemoryReadingTextStore(), assess_fn=FakeAssess())
    with pytest.raises(ReadingError) as exc:
        await service.random_excerpt()
    assert exc.value.status == 503


async def test_assess_con_id_inexistente_es_404():
    service = ReadingService(InMemoryReadingTextStore([a_text()]), assess_fn=FakeAssess())
    with pytest.raises(ReadingError) as exc:
        await service.assess(999, b"fake wav")
    assert exc.value.status == 404


async def test_assess_usa_como_referencia_el_mismo_extracto_que_se_mostro():
    """La propiedad de la que depende todo el diseño sin caché."""
    assess = FakeAssess()
    service = ReadingService(InMemoryReadingTextStore([a_text()]), assess_fn=assess)
    shown = await service.random_excerpt()

    await service.assess(shown["reading_id"], b"fake wav")

    _wav_path, reference_text = assess.called_with
    assert reference_text == shown["excerpt"]


async def test_un_error_de_azure_conserva_su_codigo_http():
    """Sin la traducción, un 502 de Azure le llegaría al usuario como un 500 genérico."""
    from app.speech.assessment import SpeechError

    assess = FakeAssess(error=SpeechError("Azure canceló la petición", status=502))
    service = ReadingService(InMemoryReadingTextStore([a_text()]), assess_fn=assess)
    with pytest.raises(ReadingError) as exc:
        await service.assess(1, b"fake wav")
    assert exc.value.status == 502


async def test_sin_voz_detectada_conserva_el_422():
    from app.speech.assessment import SpeechError

    assess = FakeAssess(error=SpeechError("No se detectó voz en el audio.", status=422))
    service = ReadingService(InMemoryReadingTextStore([a_text()]), assess_fn=assess)
    with pytest.raises(ReadingError) as exc:
        await service.assess(1, b"fake wav")
    assert exc.value.status == 422


async def test_assess_devuelve_el_texto_de_referencia_para_pintar_el_diff():
    assess = FakeAssess()
    service = ReadingService(InMemoryReadingTextStore([a_text()]), assess_fn=assess)
    result = await service.assess(1, b"fake wav")
    assert result["reference_text"] == "One two three. Four five six."
    assert result["scores"]["pronunciation"] == 90.0
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `uv run pytest test_app_reading_service.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.reading.service'`

- [ ] **Step 3: Implementar el servicio**

Crear `app/reading/service.py`:

```python
"""Orquestación de la práctica de lectura: catálogo + recorte + evaluación de Azure.

La decisión central vive acá: al evaluar, el texto de referencia se RECALCULA desde la base
a partir del `reading_id`. No lo manda el cliente (podría inventarlo y sacar 100 siempre) ni
se guarda en una caché en memoria (moriría en cada redeploy y no se compartiría entre
workers). `make_excerpt` es determinista, así que releer la fila devuelve exactamente el
mismo texto que se le mostró al usuario.
"""

import asyncio
import os
import tempfile
from collections.abc import Callable

from config import settings
from app.reading.excerpt import make_excerpt
from app.reading.repository import PostgresReadingTextStore, ReadingTextStore
from app.speech.assessment import SpeechError, assess_scripted
from app.storage import AsyncPostgresStorage


class ReadingError(Exception):
    """Error pensado para mostrarse tal cual al usuario. `status` es el código HTTP."""

    def __init__(self, message: str, status: int = 502):
        super().__init__(message)
        self.status = status


class ReadingService:
    """Entrega textos del catálogo y evalúa la lectura contra el texto entregado."""

    def __init__(
        self,
        store: ReadingTextStore,
        assess_fn: Callable[[str, str], dict] | None = None,
    ) -> None:
        self._store = store
        # Inyectable para probar sin red; en producción es assess_scripted contra Azure.
        self._assess_fn = assess_fn or assess_scripted

    async def random_excerpt(self) -> dict:
        """Un texto al azar del catálogo, ya recortado al fragmento que se lee en voz alta."""
        stored = await self._store.random()
        if stored is None:
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

    async def assess(self, reading_id: int, audio_bytes: bytes) -> dict:
        """Evalúa el audio contra el extracto de `reading_id`, releído de la base."""
        stored = await self._store.get(reading_id)
        if stored is None:
            raise ReadingError("Ese texto ya no existe en el catálogo.", status=404)

        reference_text = make_excerpt(stored.text.body, settings.READING_MAX_WORDS)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp.write(audio_bytes)
            wav_path = tmp.name
        try:
            # El SDK de Azure es bloqueante: fuera del event loop, o frena a todos los demás.
            result = await asyncio.to_thread(self._assess_fn, wav_path, reference_text)
        except SpeechError as error:
            # Se traduce en vez de dejarla salir: el endpoint sólo conoce ReadingError, y sin
            # esto un 502 de Azure o un 422 de "no se detectó voz" llegarían al usuario como
            # un 500 genérico.
            raise ReadingError(str(error), status=error.status)
        finally:
            os.unlink(wav_path)

        # Viaja de vuelta para que la página pinte las omisiones sobre el texto real sin
        # tener que confiar en la copia que tenga el navegador.
        result["reference_text"] = reference_text
        return result


def build_reading_service(storage: AsyncPostgresStorage) -> ReadingService:
    """Arma el servicio con el repositorio Postgres real. Se llama una vez, en el servidor."""
    return ReadingService(PostgresReadingTextStore(storage))
```

- [ ] **Step 4: Exportar desde `app/reading/__init__.py`**

Reemplazar las últimas dos líneas por:

```python
from app.reading.model import ReadingText
from app.reading.service import ReadingError, ReadingService, build_reading_service

__all__ = ["ReadingText", "ReadingError", "ReadingService", "build_reading_service"]
```

Y actualizar el docstring del módulo: ya no cubre "solo la ingesta". Reemplazar el segundo párrafo por:

```
El flujo tiene dos mitades: `sources/` (obtiene) → `ingest` (orquesta) → `repository`
(persiste), que `scheduler` repite cada N horas; y `service` → `excerpt` + `app/speech`, que
sirve un texto al azar y evalúa la lectura contra él.
```

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run: `uv run pytest test_app_reading_service.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 6: Correr la suite completa**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/reading/service.py app/reading/__init__.py test_app_reading_service.py
git commit -m "feat(reading): ReadingService sirve extractos y evalua contra ellos"
```

---

### Task 7: Endpoint `GET /reading/random`

Primer endpoint asíncrono del servidor. Consulta los límites para avisar temprano si el presupuesto está agotado, pero **no consume cuota**: pedir texto no cuesta dinero.

**Files:**
- Modify: `app/cmd/server.py`
- Test: `test_app_server_reading.py`

**Interfaces:**
- Consumes: `build_reading_service`, `ReadingService`, `ReadingError` (Task 6); `LimitsService.check_can_read` (Task 4); `AsyncPostgresStorage` de `app/storage.py`.
- Produces: dependencias `get_reading_service()` y el módulo-level `_reading_service`, que Task 8 reutiliza.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `test_app_server_reading.py`:

```python
"""Los endpoints de lectura con servicios falsos inyectados por dependency_overrides."""

import pytest
from fastapi.testclient import TestClient

from app.cmd.server import app, get_limits_service, get_reading_service
from app.limits.model import Decision, DecisionKind
from app.reading.service import ReadingError

HEADERS = {"X-User-Id": "u1"}

SAMPLE = {
    "reading_id": 7,
    "title": "Daily news",
    "level": 5,
    "source_url": "https://engoo.com/a",
    "excerpt": "One two three.",
    "word_count": 3,
}


class FakeReadingService:
    def __init__(self, random_result=None, assess_result=None, error=None):
        self._random = random_result or SAMPLE
        self._assess = assess_result or {"scores": {}, "words": [], "reference_text": "x"}
        self._error = error
        self.assessed = None

    async def random_excerpt(self):
        if self._error:
            raise self._error
        return self._random

    async def assess(self, reading_id, audio_bytes):
        if self._error:
            raise self._error
        self.assessed = (reading_id, audio_bytes)
        return self._assess


class FakeLimits:
    def __init__(self, decision=None):
        self._decision = decision or Decision(DecisionKind.ALLOW)
        self.reading_starts = []
        self.azure_usage = []

    def check_can_read(self, user_id):
        return self._decision

    def record_reading_start(self, user_id, reading_id):
        self.reading_starts.append((user_id, reading_id))

    def record_azure_usage(self, user_id, conversation_id, audio_seconds):
        self.azure_usage.append((user_id, conversation_id, audio_seconds))
        return 0.01


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_random_devuelve_el_extracto(client):
    app.dependency_overrides[get_reading_service] = lambda: FakeReadingService()
    app.dependency_overrides[get_limits_service] = lambda: FakeLimits()

    res = client.get("/reading/random", headers=HEADERS)

    assert res.status_code == 200
    assert res.json() == SAMPLE


def test_random_no_consume_cuota(client):
    """Pedir texto no cuesta dinero: la cuota se cobra al evaluar."""
    limits = FakeLimits()
    app.dependency_overrides[get_reading_service] = lambda: FakeReadingService()
    app.dependency_overrides[get_limits_service] = lambda: limits

    client.get("/reading/random", headers=HEADERS)

    assert limits.reading_starts == []


def test_random_corta_con_429_si_el_presupuesto_esta_agotado(client):
    app.dependency_overrides[get_reading_service] = lambda: FakeReadingService()
    app.dependency_overrides[get_limits_service] = lambda: FakeLimits(
        Decision(DecisionKind.PAUSED_TOTAL)
    )

    res = client.get("/reading/random", headers=HEADERS)

    assert res.status_code == 429
    assert res.json()["detail"]["reason"] == "paused"


def test_random_con_catalogo_vacio_es_503(client):
    app.dependency_overrides[get_reading_service] = lambda: FakeReadingService(
        error=ReadingError("sin textos", status=503)
    )
    app.dependency_overrides[get_limits_service] = lambda: FakeLimits()

    res = client.get("/reading/random", headers=HEADERS)

    assert res.status_code == 503


def test_random_exige_x_user_id(client):
    app.dependency_overrides[get_reading_service] = lambda: FakeReadingService()
    app.dependency_overrides[get_limits_service] = lambda: FakeLimits()

    assert client.get("/reading/random").status_code == 400


def test_la_pagina_de_lectura_se_renderiza(client):
    res = client.get("/reading")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `uv run pytest test_app_server_reading.py -v`
Expected: FAIL con `ImportError: cannot import name 'get_reading_service'`

- [ ] **Step 3: Construir el servicio en el composition root**

En `app/cmd/server.py`, agregar a los imports:

```python
from app.reading import ReadingError, ReadingService, build_reading_service
from app.storage import AsyncPostgresStorage, PostgresStorage
```

Después de `_feedback_repository = FeedbackRepository(_storage)`:

```python
# ReadingService: usa el almacenamiento ASÍNCRONO (app/reading corre dentro del event loop).
# Convive con `_storage`, el síncrono, que sirve a los repositorios aún no migrados.
_async_storage = AsyncPostgresStorage(settings.DATABASE_URL)
_reading_service = build_reading_service(_async_storage)
```

Y la dependencia, junto a las demás:

```python
def get_reading_service() -> ReadingService:
    """Dependencia FastAPI: entrega el servicio de la práctica de lectura."""
    return _reading_service
```

- [ ] **Step 4: Agregar el endpoint**

En `app/cmd/server.py`, después del bloque de conversación, con su propia sección:

```python
# --- práctica de lectura --------------------------------------------------------------

@app.get("/reading/random")
async def reading_random(
    user_id: str = Depends(get_user_id),
    reading: ReadingService = Depends(get_reading_service),
    limits: LimitsService = Depends(get_limits_service),
) -> dict:
    """Entrega un texto al azar del catálogo, ya recortado al extracto que se lee.

    Consulta los límites para avisar temprano si no se va a poder evaluar, pero NO consume
    cuota: pedir un texto no cuesta dinero, evaluarlo sí. Es `async def` porque el
    repositorio de lectura usa psycopg asíncrono; por eso la llamada a `limits`, que es
    sincrónica y va a Postgres, se aparta a un hilo en vez de bloquear el event loop.
    """
    try:
        decision = await asyncio.to_thread(limits.check_can_read, user_id)
    except Exception:
        logger.exception("check_can_read falló (¿Postgres?); se corta conservador como 'paused'.")
        raise HTTPException(status_code=429, detail={"reason": "paused"})

    if not decision.allowed:
        raise HTTPException(status_code=429, detail={"reason": decision.reason})

    try:
        return await reading.random_excerpt()
    except ReadingError as error:
        raise HTTPException(status_code=error.status, detail=str(error))
```

- [ ] **Step 5: Agregar la ruta de la página**

Junto al `index` que ya existe al final del archivo:

```python
@app.get("/reading", response_class=HTMLResponse)
def reading_page(request: Request) -> HTMLResponse:
    """Sirve la pantalla de práctica de lectura (dos paneles)."""
    return _templates.TemplateResponse(request, "reading.html")
```

Para que el test de esta ruta pase hace falta que `app/web/templates/reading.html` exista. Crear el placeholder mínimo ahora (Task 9 lo completa):

```html
{% extends "base.html" %}
{% block title %}Lectura en voz alta{% endblock %}
{% block content %}<div id="reading-root"></div>{% endblock %}
```

- [ ] **Step 6: Correr los tests y verificar que pasan**

Run: `uv run pytest test_app_server_reading.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 7: Correr la suite completa**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/cmd/server.py app/web/templates/reading.html test_app_server_reading.py
git commit -m "feat(reading): endpoint GET /reading/random y ruta de la pagina"
```

---

### Task 8: Endpoint `POST /reading/assess`

Acá sí se espera el resultado de Azure (es la respuesta, no un agregado en background), se cobra la cuota y se registra el costo.

**Files:**
- Modify: `app/cmd/server.py`
- Modify: `config.py` (`RATE_LIMIT_READING_PER_MIN`)
- Test: `test_app_server_reading.py` (agregar casos)

**Interfaces:**
- Consumes: `get_reading_service`, `FakeReadingService`, `FakeLimits` (Task 7); `ReadingService.assess` (Task 6); `LimitsService.record_reading_start` y `record_azure_usage` (Task 4).
- Produces: nada que otras tareas consuman.

- [ ] **Step 1: Escribir los tests que fallan**

Añadir a `test_app_server_reading.py`:

```python
ASSESS_RESULT = {
    "recognized_text": "one two three",
    "scores": {"pronunciation": 88.0, "completeness": 100.0},
    "words": [{"word": "one", "accuracy": 90.0, "error_type": "None", "phonemes": []}],
    "audio_seconds": 12.5,
    "reference_text": "One two three.",
}


def _post_assess(client, reading_id=7):
    return client.post(
        "/reading/assess",
        data={"reading_id": str(reading_id)},
        files={"audio": ("a.wav", b"fake wav bytes", "audio/wav")},
        headers=HEADERS,
    )


def test_assess_devuelve_los_scores(client):
    app.dependency_overrides[get_reading_service] = lambda: FakeReadingService(
        assess_result=ASSESS_RESULT
    )
    app.dependency_overrides[get_limits_service] = lambda: FakeLimits()

    res = _post_assess(client)

    assert res.status_code == 200
    assert res.json()["scores"]["completeness"] == 100.0


def test_assess_cobra_la_cuota_y_el_costo(client):
    limits = FakeLimits()
    app.dependency_overrides[get_reading_service] = lambda: FakeReadingService(
        assess_result=ASSESS_RESULT
    )
    app.dependency_overrides[get_limits_service] = lambda: limits

    _post_assess(client)

    assert limits.reading_starts == [("u1", 7)]
    assert limits.azure_usage == [("u1", "7", 12.5)]


def test_assess_corta_con_429_sin_cuota(client):
    limits = FakeLimits(Decision(DecisionKind.QUOTA))
    service = FakeReadingService(assess_result=ASSESS_RESULT)
    app.dependency_overrides[get_reading_service] = lambda: service
    app.dependency_overrides[get_limits_service] = lambda: limits

    res = _post_assess(client)

    assert res.status_code == 429
    assert res.json()["detail"]["reason"] == "quota"
    # No se llamó a Azure: los límites se comprueban ANTES de gastar.
    assert service.assessed is None


def test_assess_con_id_inexistente_es_404(client):
    app.dependency_overrides[get_reading_service] = lambda: FakeReadingService(
        error=ReadingError("no existe", status=404)
    )
    app.dependency_overrides[get_limits_service] = lambda: FakeLimits()

    assert _post_assess(client, reading_id=999).status_code == 404


def test_assess_no_cobra_si_azure_falla(client):
    """Un 502 de Azure no debe gastarle una lectura al usuario."""
    limits = FakeLimits()
    app.dependency_overrides[get_reading_service] = lambda: FakeReadingService(
        error=ReadingError("Azure canceló", status=502)
    )
    app.dependency_overrides[get_limits_service] = lambda: limits

    res = _post_assess(client)

    assert res.status_code == 502
    assert limits.reading_starts == []
    assert limits.azure_usage == []


def test_assess_ignora_un_reference_text_enviado_por_el_cliente(client):
    """El texto lo pone el servidor: si no, cualquiera evalúa 'hello' contra 'hello'."""
    service = FakeReadingService(assess_result=ASSESS_RESULT)
    app.dependency_overrides[get_reading_service] = lambda: service
    app.dependency_overrides[get_limits_service] = lambda: FakeLimits()

    res = client.post(
        "/reading/assess",
        data={"reading_id": "7", "reference_text": "hello"},
        files={"audio": ("a.wav", b"fake wav bytes", "audio/wav")},
        headers=HEADERS,
    )

    assert res.status_code == 200
    # El servicio solo recibió el id y el audio; el texto extra se descartó.
    assert service.assessed == (7, b"fake wav bytes")
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `uv run pytest test_app_server_reading.py -v`
Expected: FAIL — los nuevos dan 405/404 porque la ruta no existe.

- [ ] **Step 3: Implementar el endpoint**

En `app/cmd/server.py`, después de `reading_random`:

```python
@app.post("/reading/assess")
async def reading_assess(
    reading_id: int = Form(...),
    audio: UploadFile = File(...),
    user_id: str = Depends(get_user_id),
    reading: ReadingService = Depends(get_reading_service),
    limits: LimitsService = Depends(get_limits_service),
) -> dict:
    """Evalúa la lectura contra el extracto de `reading_id`, releído de la base.

    El cliente manda el id, nunca el texto de referencia: si lo mandara, podría evaluar un
    audio de "hello" contra un `reference_text` de "hello" y sacar 100 siempre.

    Los límites se comprueban ANTES de llamar a Azure, y la cuota se registra DESPUÉS de que
    responda: un fallo de Azure no debe gastarle una lectura al usuario.
    """
    try:
        decision = await asyncio.to_thread(limits.check_can_read, user_id)
    except Exception:
        logger.exception("check_can_read falló (¿Postgres?); se corta conservador como 'paused'.")
        raise HTTPException(status_code=429, detail={"reason": "paused"})

    if not decision.allowed:
        raise HTTPException(status_code=429, detail={"reason": decision.reason})

    try:
        result = await reading.assess(reading_id, await audio.read())
    except ReadingError as error:
        raise HTTPException(status_code=error.status, detail=str(error))

    await asyncio.to_thread(limits.record_reading_start, user_id, reading_id)
    await asyncio.to_thread(
        limits.record_azure_usage, user_id, str(reading_id), result["audio_seconds"]
    )
    return result
```

- [ ] **Step 4: Agregar el rate limit**

En `config.py`, junto a los otros:

```python
    # Mismo tope que RATE_LIMIT_ANSWER_PER_MIN: cubre una operacion equivalente (subir audio
    # y esperar a Azure).
    RATE_LIMIT_READING_PER_MIN: int = 20
```

En `app/cmd/server.py`, en el dict del `IpRateLimiter`:

```python
        "reading": settings.RATE_LIMIT_READING_PER_MIN,
```

Y en `_RATE_SCOPES`:

```python
    ("POST", "/reading/assess"): "reading",
```

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run: `uv run pytest test_app_server_reading.py -v`
Expected: PASS, 12 tests.

- [ ] **Step 6: Correr la suite completa**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/cmd/server.py config.py test_app_server_reading.py
git commit -m "feat(reading): endpoint POST /reading/assess con cuota y costo"
```

---

### Task 9: La pantalla dividida

El frontend del boceto: dos paneles, izquierda el texto a leer, derecha lo que va diciendo el usuario. Al terminar, la derecha pasa a ser el review y la izquierda marca las omisiones sobre el texto real.

**Files:**
- Modify: `app/web/templates/reading.html` (reemplaza el placeholder de la Task 7)
- Create: `app/web/static/reading.js`
- Modify: `app/web/templates/base.html` (navegación)
- Modify: `app/web/static/app.css` (layout de dos paneles)
- Reference: `app/web/static/shared.js` (`Api`, `Identity`, `createRecorder`, `showBanner`, `renderWord`, `$`), `app/web/templates/index.html:441-460` (cómo se pintan las palabras hoy)

**Interfaces:**
- Consumes de `shared.js`: `$(id)`, `Api.request(method, path, {json, form})`, `createRecorder({maxSeconds, lang, onLevel, onTranscript, onTick, onStart, onStop})` con `start(onDone)` y `onDone(wavBlob, transcript)`, `showBanner(reason)`, `renderWord(word, speak)`, `ApiError` con `.status` y `.reason`.
- Consume de la API: `GET /reading/random` y `POST /reading/assess` (Tasks 7 y 8).
- Produces: nada que otras tareas consuman.

- [ ] **Step 1: Agregar la navegación en `base.html`**

Dentro de `<main>`, antes del `<div id="banner">`:

```html
      {# Navegación entre modalidades. Vive en base.html para que cada página nueva la herede. #}
      <nav class="modes">
        <a href="/" class="{% block nav_conversation %}{% endblock %}">Conversación</a>
        <a href="/reading" class="{% block nav_reading %}{% endblock %}">Lectura</a>
      </nav>
```

Y en el bloque de scripts, para que cada página pueda sumar el suyo, verificar que `{% block scripts %}{% endblock %}` ya existe (sí existe, después de `shared.js`).

- [ ] **Step 2: Escribir la plantilla**

Reemplazar el contenido de `app/web/templates/reading.html`:

```html
{% extends "base.html" %}

{% block title %}Lectura en voz alta{% endblock %}
{% block nav_reading %}active{% endblock %}

{% block content %}
  <header class="reading-head">
    <h1 id="reading-title">Lectura en voz alta</h1>
    <p class="lead">
      Lee el texto en voz alta. Al terminar, Azure te dice qué palabras fallaste.
    </p>
    <p class="meta">
      <span id="reading-level" class="badge hidden"></span>
      <a id="reading-source" href="#" target="_blank" rel="noopener" class="hidden">Artículo original</a>
    </p>
  </header>

  {# Fila de scores: sólo aparece en el estado de review. #}
  <div id="reading-scores" class="scores hidden"></div>

  <div class="split">
    <section class="panel">
      <h2>Texto de referencia</h2>
      <div id="reading-text" class="panel-body">Cargando un texto…</div>
    </section>
    <section class="panel">
      <h2 id="right-title">Lo que estás diciendo</h2>
      <div id="reading-said" class="panel-body"></div>
    </section>
  </div>

  <div class="actions">
    <button id="btn-record" type="button" disabled>Empezar a leer</button>
    <button id="btn-another" type="button">Otro texto</button>
    <span id="reading-timer" class="timer"></span>
  </div>

  <p id="reading-error" class="error hidden" role="alert"></p>
{% endblock %}

{% block scripts %}
  <script src="/static/reading.js"></script>
{% endblock %}
```

- [ ] **Step 3: Escribir `reading.js`**

Crear `app/web/static/reading.js`:

```javascript
"use strict";
// Pantalla de lectura en voz alta: dos paneles y tres estados (listo → hablando → review).
// Lo compartido con la conversación (grabación, API, identidad, pintado de palabras) vive en
// shared.js; acá sólo está lo propio de esta modalidad.

let current = null; // { reading_id, excerpt, ... } del texto que se está leyendo

function showError(message) {
  const el = $("reading-error");
  el.textContent = message;
  el.classList.remove("hidden");
}

function clearError() {
  $("reading-error").classList.add("hidden");
}

// ---- Estado 1: listo ----
async function loadText() {
  clearError();
  $("btn-record").disabled = true;
  $("reading-text").textContent = "Cargando un texto…";
  $("reading-said").innerHTML = "";
  $("reading-scores").classList.add("hidden");
  $("right-title").textContent = "Lo que estás diciendo";

  try {
    current = await Api.request("GET", "/reading/random");
  } catch (err) {
    if (err.reason) return showBanner(err.reason);
    $("reading-text").textContent = "";
    return showError(err.message);
  }

  $("reading-text").textContent = current.excerpt;
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
}

// ---- Estado 2: hablando ----
// maxSeconds sale del tamaño del texto: ~2,5 palabras por segundo leyendo en voz alta, con
// un margen del doble para quien lea despacio, y un piso de 60 s.
function maxSecondsFor(wordCount) {
  return Math.max(60, Math.ceil((wordCount / 2.5) * 2));
}

const recorder = () =>
  createRecorder({
    maxSeconds: maxSecondsFor(current.word_count),
    lang: "en-US",
    onTranscript: (text) => {
      $("reading-said").textContent = text;
    },
    onTick: (secondsLeft) => {
      $("reading-timer").textContent = secondsLeft === null ? "" : `${secondsLeft}s`;
    },
    onStart: () => {
      $("btn-record").textContent = "Terminé";
      $("btn-another").disabled = true;
    },
    onStop: () => {
      $("btn-record").textContent = "Evaluando…";
      $("btn-record").disabled = true;
    },
  });

let active = null;

async function toggleRecording() {
  if (active) {
    const rec = active;
    active = null;
    await rec.stop();
    return;
  }
  clearError();
  active = recorder();
  await active.start(sendForReview);
}

// ---- Estado 3: review ----
async function sendForReview(wavBlob) {
  const form = new FormData();
  form.append("reading_id", String(current.reading_id));
  form.append("audio", wavBlob, "reading.wav");

  let result;
  try {
    result = await Api.request("POST", "/reading/assess", { form });
  } catch (err) {
    if (err.reason) return showBanner(err.reason);
    resetRecordButton();
    return showError(err.message);
  }

  renderReview(result);
  resetRecordButton();
}

function resetRecordButton() {
  $("btn-record").textContent = "Leer de nuevo";
  $("btn-record").disabled = false;
  $("btn-another").disabled = false;
}

function renderReview(result) {
  $("right-title").textContent = "Tu lectura, palabra por palabra";

  // Derecha: cada palabra coloreada por accuracy, con sus fonemas (lógica de shared.js).
  const said = $("reading-said");
  said.innerHTML = "";
  said.classList.add("words");
  (result.words || []).forEach((w) => said.appendChild(renderWord(w, () => {})));

  // Izquierda: el texto real, con las palabras omitidas resaltadas. Se resalta sobre el
  // texto de referencia que devolvió el servidor, no sobre el que tenga el navegador.
  const omitted = new Set(
    (result.words || [])
      .filter((w) => w.error_type === "Omission")
      .map((w) => w.word.toLowerCase())
  );
  const left = $("reading-text");
  left.innerHTML = "";
  (result.reference_text || current.excerpt).split(/\s+/).forEach((token) => {
    const bare = token.toLowerCase().replace(/[^a-z']/g, "");
    const span = document.createElement("span");
    span.textContent = token + " ";
    if (omitted.has(bare)) span.className = "omitted";
    left.appendChild(span);
  });

  // Arriba: los scores. `completeness` sólo existe en modo scripted, que es el de lectura.
  const scores = result.scores || {};
  const box = $("reading-scores");
  box.innerHTML = "";
  [
    ["Pronunciación", scores.pronunciation],
    ["Precisión", scores.accuracy],
    ["Fluidez", scores.fluency],
    ["Completitud", scores.completeness],
    ["Prosodia", scores.prosody],
  ].forEach(([label, value]) => {
    const el = document.createElement("div");
    el.className = `score ${scoreClass(value)}`;
    el.innerHTML = `<strong>${formatScore(value)}</strong><span>${label}</span>`;
    box.appendChild(el);
  });
  box.classList.remove("hidden");
}

$("btn-record").addEventListener("click", toggleRecording);
$("btn-another").addEventListener("click", loadText);
loadText();
```

- [ ] **Step 4: Agregar los estilos**

Al final de `app/web/static/app.css`:

```css
/* --- Práctica de lectura: dos paneles lado a lado --- */
.split {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}
/* En pantallas angostas los paneles se apilan: leer un texto en una columna de 160 px
   no es leer. */
@media (max-width: 720px) {
  .split { grid-template-columns: 1fr; }
}
.panel {
  border: 1px solid var(--border, #d8d3ca);
  border-radius: 12px;
  padding: 16px;
  background: #fff;
}
.panel h2 { margin: 0 0 12px; font-size: 1rem; }
.panel-body { min-height: 320px; line-height: 1.7; }
.omitted {
  background: #ffe0e0;
  text-decoration: line-through;
  border-radius: 3px;
}
.scores { display: flex; gap: 12px; flex-wrap: wrap; margin-bottom: 16px; }
.score { display: flex; flex-direction: column; align-items: center; min-width: 84px; }
.score strong { font-size: 1.4rem; }
.actions { display: flex; align-items: center; gap: 12px; margin-top: 16px; }
.timer { font-variant-numeric: tabular-nums; }
.modes { display: flex; gap: 16px; margin-bottom: 16px; }
.modes a.active { font-weight: 600; text-decoration: underline; }
.badge {
  display: inline-block; padding: 2px 8px; border-radius: 999px;
  background: #eee7db; font-size: .85rem;
}
```

Revisar los nombres de variables CSS que ya usa `app.css` (por ejemplo si define `--border` o colores con otro nombre) y ajustar para no introducir una paleta nueva.

- [ ] **Step 5: Verificar contra el servidor real**

```bash
docker compose up -d
uv run python -m app.reading.ingest   # poblar el catálogo si está vacío
uv run uvicorn app.cmd.server:app --reload
```

Abrir `http://localhost:8000/reading` y comprobar, uno por uno:
- Carga un texto y se ve en el panel izquierdo.
- "Otro texto" trae uno distinto.
- Al grabar, el panel derecho se llena con la transcripción en vivo.
- Al terminar, aparecen los scores (incluida Completitud, que no es "—") y las palabras coloreadas.
- Si se omite una palabra a propósito, queda tachada en el panel izquierdo.
- En una ventana angosta los paneles se apilan.

- [ ] **Step 6: Correr la suite completa**

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/web/
git commit -m "feat(web): pantalla de lectura con paneles de texto y transcripcion"
```

---

### Task 10: Documentación

**Files:**
- Modify: `VARIABLES-DE-ENTORNO.md`
- Modify: `README.md`
- Modify: `docs/superpowers/specs/2026-08-06-practica-lectura-design.md`

- [ ] **Step 1: Documentar las variables nuevas**

En `VARIABLES-DE-ENTORNO.md`, siguiendo el formato de las entradas existentes, agregar `READING_MAX_WORDS` (120, tamaño del extracto que se lee en voz alta), `USER_READING_QUOTA` (10, evaluaciones de lectura por usuario, independiente de la cuota de conversación) y `RATE_LIMIT_READING_PER_MIN` (20, peticiones por IP a `/reading/assess`).

- [ ] **Step 2: Documentar la modalidad en el README**

Agregar una sección corta explicando que además de la conversación hay práctica de lectura en `/reading`, que el catálogo se puebla con `python -m app.reading.ingest`, y que si está vacío la página responde 503 con esa instrucción.

- [ ] **Step 3: Marcar la fase 2 como ejecutada**

En `docs/superpowers/specs/2026-08-06-practica-lectura-design.md`, en la sección "Alcance por fases", marcar la fase 2 como entregada y apuntar al spec de esta fase para las decisiones que cambiaron (sin caché de extracto, texto al azar sin catálogo navegable).

- [ ] **Step 4: Commit**

```bash
git add VARIABLES-DE-ENTORNO.md README.md docs/
git commit -m "docs: variables y uso de la practica de lectura"
```
