# Módulo `app/feedback/` + `POST /feedback` (Fase 4) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recoger el feedback del usuario al terminar la demo (like/dislike, estrellas 1–5, comentario libre, "¿te interesarían más funciones?" + cuáles) y persistirlo en la tabla `pilot_feedback`, con un endpoint `POST /feedback` identificado por `X-User-Id`.

**Architecture:** Un módulo `app/feedback/` con dos piezas: `schemas.py` (validación de entrada con Pydantic, incluida la regla `rating` 1..5) y `repository.py` (`FeedbackRepository`, adaptador Postgres delgado que inserta la fila, mismo patrón que `ConversationRepository`). Se agrega la tabla `pilot_feedback` al esquema y un endpoint `POST /feedback` en el composition root que valida, exige `X-User-Id` y persiste.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, `psycopg` (Postgres), `pytest` + `fastapi.testclient`, `uv`.

## Global Constraints

- Todas las variables de entorno se leen SOLO en `config.py`. Esta fase no agrega ninguna env.
- Esta fase crea `app/feedback/` y su tabla, y agrega el endpoint `POST /feedback` en `app/cmd/server.py`. **No** toca `app/conversation/`, `app/speech/`, `app/limits/`, ni el frontend.
- Identidad: `POST /feedback` exige el header `X-User-Id` (reutiliza la dependencia `get_user_id` que ya existe en `app/cmd/server.py`). Falta/vacío → 400.
- Validación en el esquema Pydantic (no `if`s dispersos): `rating`, si viene, debe estar en 1..5; fuera de rango → 422 (FastAPI lo traduce de `ValidationError`). Todos los campos del formulario son opcionales (el usuario puede dejar partes sin llenar), consistente con la tabla (columnas anulables salvo `comment`/`suggestions`, que son `TEXT NOT NULL DEFAULT ''`).
- El repositorio Postgres es un adaptador delgado y NO se testea unitariamente contra una BD viva (igual que `ConversationRepository`); su SQL se ejerce en integración, no acá. La lógica testeable (validación del esquema + DDL) sí se prueba.
- La tabla `pilot_feedback` se define idéntica en `app/storage.py` (`_SCHEMA`, uso standalone) y en `docker/initdb/*.sql` (init del contenedor).
- Esquema de `pilot_feedback` (del modelo de datos del spec): `id`, `created_at TIMESTAMPTZ DEFAULT now()`, `user_id TEXT NOT NULL`, `liked BOOLEAN`, `rating INTEGER`, `comment TEXT NOT NULL DEFAULT ''`, `wants_more BOOLEAN`, `suggestions TEXT NOT NULL DEFAULT ''`.
- Tests en la raíz, nombrados `test_app_feedback*.py` / `test_app_server_feedback.py`. Los tests de endpoint inyectan un doble del repositorio vía `app.dependency_overrides` (sin BD). Comando: `uv run pytest <archivo> -v`.

---

### Task 1: Módulo `app/feedback/` (esquema + repositorio) + tabla `pilot_feedback`

**Files:**
- Create: `app/feedback/__init__.py`
- Create: `app/feedback/schemas.py`
- Create: `app/feedback/repository.py`
- Modify: `app/storage.py` (agregar `pilot_feedback` a la tupla `_SCHEMA`)
- Create: `docker/initdb/03-pilot-feedback.sql`
- Test: `test_app_feedback.py`

**Interfaces:**
- Consumes: `app.storage.PostgresStorage`.
- Produces:
  - `app.feedback.FeedbackRequest` (Pydantic) con campos `liked: bool | None`, `rating: int | None` (1..5), `comment: str = ""`, `wants_more: bool | None`, `suggestions: str = ""`.
  - `app.feedback.FeedbackRepository(storage: PostgresStorage)` con `save(user_id: str, feedback: FeedbackRequest) -> int` (devuelve el id de la fila insertada).

- [ ] **Step 1: Escribir los tests que fallan `test_app_feedback.py`**

```python
"""Valida el esquema de feedback (regla rating 1..5, opcionalidad) y el DDL de pilot_feedback."""

import pytest
from pydantic import ValidationError

from app.feedback import FeedbackRequest


def test_full_feedback_is_valid():
    fb = FeedbackRequest(
        liked=True, rating=5, comment="genial", wants_more=True, suggestions="más juegos"
    )
    assert fb.rating == 5
    assert fb.liked is True
    assert fb.suggestions == "más juegos"


def test_all_fields_optional_with_defaults():
    fb = FeedbackRequest()
    assert fb.liked is None
    assert fb.rating is None
    assert fb.comment == ""
    assert fb.wants_more is None
    assert fb.suggestions == ""


def test_rating_below_1_rejected():
    with pytest.raises(ValidationError):
        FeedbackRequest(rating=0)


def test_rating_above_5_rejected():
    with pytest.raises(ValidationError):
        FeedbackRequest(rating=6)


def test_rating_none_is_allowed():
    # rating es opcional: no darlo (o darlo None) es válido.
    assert FeedbackRequest(liked=False).rating is None


def test_schema_includes_pilot_feedback_table():
    from app.storage import _SCHEMA

    assert "pilot_feedback" in " ".join(_SCHEMA)
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `uv run pytest test_app_feedback.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.feedback'`.

- [ ] **Step 3: Implementar `app/feedback/schemas.py`**

```python
"""Esquema de entrada del formulario de feedback del piloto, validado con Pydantic.

Todos los campos son opcionales (el usuario puede dejar partes sin llenar). La única regla
es que `rating`, si viene, esté en 1..5; fuera de rango, Pydantic lanza ValidationError y
FastAPI responde 422. Refleja la tabla `pilot_feedback` (columnas anulables salvo los TEXT).
"""

from pydantic import BaseModel, Field


class FeedbackRequest(BaseModel):
    """Formulario de feedback: like/dislike, estrellas 1–5, comentario y '¿más funciones?'."""

    liked: bool | None = None  # like / dislike
    rating: int | None = Field(default=None, ge=1, le=5)  # estrellas 1..5
    comment: str = ""
    wants_more: bool | None = None  # ¿te interesarían más funciones?
    suggestions: str = ""  # cuáles
```

- [ ] **Step 4: Implementar `app/feedback/repository.py`**

```python
"""Repositorio del feedback del piloto (tabla `pilot_feedback`).

Aísla el SQL: el endpoint guarda una respuesta llamando `save`, sin escribir SQL a mano.
Recibe el almacenamiento por inyección de dependencia y NO crea la tabla (eso lo hace
`PostgresStorage.init_schema()` o el init del contenedor). Mismo patrón que
`ConversationRepository`. `created_at` lo pone Postgres por DEFAULT now().
"""

from app.feedback.schemas import FeedbackRequest
from app.storage import PostgresStorage


class FeedbackRepository:
    """Inserta respuestas del formulario de feedback. Recibe el almacenamiento inyectado."""

    def __init__(self, storage: PostgresStorage) -> None:
        self._storage = storage

    def save(self, user_id: str, feedback: FeedbackRequest) -> int:
        """Inserta una respuesta de feedback y devuelve el id de la fila creada."""
        with self._storage.connect() as conn:
            row = conn.execute(
                "INSERT INTO pilot_feedback "
                "(user_id, liked, rating, comment, wants_more, suggestions) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (
                    user_id,
                    feedback.liked,
                    feedback.rating,
                    feedback.comment,
                    feedback.wants_more,
                    feedback.suggestions,
                ),
            ).fetchone()
            # RETURNING id siempre devuelve la fila recién insertada.
            assert row is not None
            return int(row["id"])
```

- [ ] **Step 5: Implementar `app/feedback/__init__.py`**

```python
"""Módulo de feedback del piloto: formulario validado + su persistencia en Postgres."""

from app.feedback.repository import FeedbackRepository
from app.feedback.schemas import FeedbackRequest

__all__ = ["FeedbackRepository", "FeedbackRequest"]
```

- [ ] **Step 6: Agregar la tabla `pilot_feedback` a `app/storage.py`**

En `app/storage.py`, dentro de la tupla `_SCHEMA`, agregar un cuarto elemento después del bloque
de `conversation_starts` (antes del paréntesis de cierre `)`), quedando:

```python
    """
    CREATE TABLE IF NOT EXISTS conversation_starts (
        id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        user_id         TEXT NOT NULL,
        conversation_id TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS pilot_feedback (
        id            INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
        user_id       TEXT NOT NULL,
        liked         BOOLEAN,
        rating        INTEGER,
        comment       TEXT NOT NULL DEFAULT '',
        wants_more    BOOLEAN,
        suggestions   TEXT NOT NULL DEFAULT ''
    );
    """,
)
```

(Es decir: se inserta el bloque `CREATE TABLE ... pilot_feedback ...` como último elemento de la
tupla. `init_schema` ya itera sobre `_SCHEMA`, así que no hay más cambios en `storage.py`.)

- [ ] **Step 7: Crear el DDL del contenedor `docker/initdb/03-pilot-feedback.sql`**

```sql
-- Tabla del feedback del piloto (app/feedback). Postgres ejecuta los .sql de
-- docker-entrypoint-initdb.d una sola vez, al crear el volumen de datos.
-- Debe coincidir con el DDL de PostgresStorage.init_schema() (app/storage.py).

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

- [ ] **Step 8: Correr los tests y verificar que pasan**

Run: `uv run pytest test_app_feedback.py -v`
Expected: PASS (6 tests).

- [ ] **Step 9: Verificar que la suite completa sigue verde (cambió `app/storage.py`)**

Run: `uv run pytest -q`
Expected: PASS (el cuarto elemento en `_SCHEMA` no afecta a los otros repositorios).

- [ ] **Step 10: Commit**

```bash
git add app/feedback/__init__.py app/feedback/schemas.py app/feedback/repository.py app/storage.py docker/initdb/03-pilot-feedback.sql test_app_feedback.py
git commit -m "feat(app/feedback): formulario validado + repositorio + tabla pilot_feedback"
```

---

### Task 2: Endpoint `POST /feedback`

**Files:**
- Modify: `app/cmd/server.py` (wiring del `FeedbackRepository` + endpoint `POST /feedback`)
- Test: `test_app_server_feedback.py`

**Interfaces:**
- Consumes (de Task 1): `app.feedback.FeedbackRepository`, `app.feedback.FeedbackRequest`. De `app/cmd/server.py` (ya existentes): la dependencia `get_user_id`, el `_storage` compartido.
- Produces:
  - Dependencia FastAPI `get_feedback_repository() -> FeedbackRepository`.
  - `POST /feedback` (header `X-User-Id`, body `FeedbackRequest`) → `201 {"id": int}` | `400` (sin user id) | `422` (rating fuera de 1..5).

- [ ] **Step 1: Escribir los tests que fallan `test_app_server_feedback.py`**

```python
"""Tests del endpoint POST /feedback: identidad, validación y persistencia (con repo doble)."""

import pytest
from fastapi.testclient import TestClient

from app.cmd import server


class FakeFeedbackRepo:
    """Doble de FeedbackRepository: captura lo guardado y devuelve un id fijo."""

    def __init__(self):
        self.saved = []

    def save(self, user_id, feedback):
        self.saved.append((user_id, feedback))
        return 42


@pytest.fixture
def client_with():
    def _make(repo=None):
        repo = repo or FakeFeedbackRepo()
        server.app.dependency_overrides[server.get_feedback_repository] = lambda: repo
        return TestClient(server.app), repo

    yield _make
    server.app.dependency_overrides.clear()


def test_feedback_requires_user_id(client_with):
    client, _ = client_with()
    resp = client.post("/feedback", json={"liked": True, "rating": 5})
    assert resp.status_code == 400


def test_feedback_saved_returns_201_with_id(client_with):
    client, repo = client_with()
    resp = client.post(
        "/feedback",
        json={"liked": True, "rating": 5, "comment": "genial", "wants_more": True,
              "suggestions": "más juegos"},
        headers={"X-User-Id": "u1"},
    )
    assert resp.status_code == 201
    assert resp.json() == {"id": 42}
    assert len(repo.saved) == 1
    user_id, feedback = repo.saved[0]
    assert user_id == "u1"
    assert feedback.rating == 5
    assert feedback.suggestions == "más juegos"


def test_feedback_invalid_rating_returns_422(client_with):
    client, _ = client_with()
    resp = client.post("/feedback", json={"rating": 9}, headers={"X-User-Id": "u1"})
    assert resp.status_code == 422


def test_feedback_minimal_body_ok(client_with):
    # Todo opcional: un body vacío es válido (el usuario no llenó nada).
    client, repo = client_with()
    resp = client.post("/feedback", json={}, headers={"X-User-Id": "u1"})
    assert resp.status_code == 201
    assert repo.saved[0][1].comment == ""
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `uv run pytest test_app_server_feedback.py -v`
Expected: FAIL — `AttributeError: module 'app.cmd.server' has no attribute 'get_feedback_repository'` (aún no existe), o 404 porque el endpoint `/feedback` no está registrado.

- [ ] **Step 3: Cablear el repositorio y agregar el endpoint en `app/cmd/server.py`**

En la zona de imports de `app/cmd/server.py`, agregar:

```python
from app.feedback import FeedbackRepository, FeedbackRequest
```

Debajo de la construcción de `_speech_service` (composition root), agregar:

```python
_feedback_repository = FeedbackRepository(_storage)
```

Junto a las otras dependencias FastAPI (`get_repository`, `get_limits_service`, etc.), agregar:

```python
def get_feedback_repository() -> FeedbackRepository:
    """Dependencia FastAPI: entrega el repositorio del feedback del piloto."""
    return _feedback_repository
```

Y agregar el endpoint (por ejemplo, después de `/conversation/answer`, antes del montaje del
frontend estático `app.mount(...)`):

```python
@app.post("/feedback", status_code=201)
def feedback_create(
    payload: FeedbackRequest,
    user_id: str = Depends(get_user_id),
    repo: FeedbackRepository = Depends(get_feedback_repository),
) -> dict:
    """Guarda el formulario de feedback del piloto con la identidad del navegador (X-User-Id)."""
    feedback_id = repo.save(user_id, payload)
    return {"id": feedback_id}
```

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `uv run pytest test_app_server_feedback.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Verificación completa**

Run: `uv run pytest -q`
Expected: PASS (suite completa; el nuevo endpoint no afecta a los existentes).

- [ ] **Step 6: Commit**

```bash
git add app/cmd/server.py test_app_server_feedback.py
git commit -m "feat(app/server): endpoint POST /feedback (persistencia con X-User-Id)"
```

---

## Notas para el que ejecute

- `FeedbackRepository` NO tiene test unitario contra Postgres a propósito: es un adaptador delgado
  sobre SQL, igual que `ConversationRepository`. Lo testeable (validación del esquema, presencia del
  DDL, cableado del endpoint con un doble) sí está cubierto.
- El endpoint reutiliza `get_user_id` de la Fase 3; no se redefine.
- La **Fase 5** (frontend) consumirá `POST /feedback` desde el formulario de la pantalla final.
- `pilot_feedback` es la última de las tres tablas operativas del piloto (`usage_events`,
  `conversation_starts`, `pilot_feedback`); con esto el modelo de datos del spec queda completo.
