# Módulo `app/limits/` (costo + cuota + presupuesto) — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Crear el módulo `app/limits/` que mide el costo (tokens de Gemini y segundos de Azure) y decide si la app puede atender una conversación nueva (cuota por usuario + presupuesto diario/total), persistiendo cada evento facturable y cada inicio de conversación en Postgres. Sin tocar todavía endpoints ni frontend.

**Architecture:** Cuatro piezas con una responsabilidad cada una: `cost.py` (cálculo de costo puro, sin BD, desde tarifas de `config`), `model.py` (el value object `Decision`), `repository.py` (la interfaz `UsageStore` + su adaptador Postgres delgado), y `service.py` (el `LimitsService` que compone la decisión con las lecturas del store y registra el uso). El servicio depende de la interfaz `UsageStore`, no del Postgres concreto, así su lógica se prueba con un doble en memoria (mismo criterio que `app/speech`).

**Tech Stack:** Python 3.11+, `psycopg` (Postgres), `pytest`, `uv`.

## Global Constraints

- Todas las variables de entorno se leen SOLO en `config.py`; el resto recibe valores ya tipados. Nada de `os.getenv` disperso. Los tests que dependen de una tarifa o presupuesto los fijan con `monkeypatch.setattr(config, ...)`, no con valores hardcodeados.
- Esta fase (Fase 2 del spec) crea `app/limits/` y las tablas. **No** modifica `app/cmd/server.py`, ni el grafo, ni el frontend: la inyección del `LimitsService` en el composition root y el cambio de endpoints van en la Fase 3.
- El costo es la **suma** de eventos persistidos (`SELECT SUM(cost_usd)`), nunca un contador mutable que se desincronice.
- Precedencia de la decisión (de más fuerte a más débil): **tope total** → **presupuesto diario** → **cuota del usuario** → permitir. El presupuesto global protege el costo por encima de la cuota individual.
- Reasons que ve el frontend (Fase 3): `"paused"` (diario o total, mismo banner neutro) | `"quota"` (límite del usuario) | permitido (sin reason).
- Los repositorios Postgres de `app/` son adaptadores delgados y **no** se testean unitariamente (igual que `ConversationRepository`); su conformidad con la interfaz se verifica de forma estructural (Protocol `runtime_checkable`), sin BD viva.
- Ticks/unidades no aplican acá; los segundos de audio llegan ya en segundos desde `app/speech`.
- Comando de tests: `uv run pytest <archivo> -v`.
- Tests en la raíz del repo, nombrados `test_app_limits_*.py`, siguiendo el patrón de `test_app_speech_*.py`.

---

### Task 1: `config.py` (constantes de tarifa/presupuesto) + `cost.py` (cálculo de costo puro)

**Files:**
- Modify: `config.py` (agrega las constantes de tarifa, presupuesto, cuota y límites del piloto)
- Create: `app/limits/__init__.py` (vacío por ahora; se llena en Task 2/3)
- Create: `app/limits/cost.py`
- Test: `test_app_limits_cost.py`

**Interfaces:**
- Consumes: `config.GEMINI_PRICE_INPUT_PER_1K`, `config.GEMINI_PRICE_OUTPUT_PER_1K`, `config.AZURE_SPEECH_PRICE_PER_SECOND` (floats).
- Produces:
  - `app.limits.cost.gemini_cost_usd(input_tokens: int, output_tokens: int) -> float`
  - `app.limits.cost.azure_cost_usd(audio_seconds: float) -> float`

- [ ] **Step 1: Agregar las constantes a `config.py`**

Insertar este bloque al final de `config.py` (después de la constante `CHAT_MODEL`, respetando "todas las env viven aquí"):

```python
# --- Piloto demo: tarifas, presupuesto y cuota (todas configurables por entorno) --------
# Las tarifas son aproximaciones para el piloto; el costo real se ajusta cambiando la env,
# no el código. "PER_1K" = precio por cada 1000 tokens.
GEMINI_PRICE_INPUT_PER_1K: float = float(os.getenv("GEMINI_PRICE_INPUT_PER_1K", "0.0003"))
GEMINI_PRICE_OUTPUT_PER_1K: float = float(os.getenv("GEMINI_PRICE_OUTPUT_PER_1K", "0.0025"))

# Azure Pronunciation Assessment se cobra por duración de audio. ~$1/hora ≈ 0.000278 $/s.
AZURE_SPEECH_PRICE_PER_SECOND: float = float(
    os.getenv("AZURE_SPEECH_PRICE_PER_SECOND", "0.000278")
)

# Presupuesto de costo en dos niveles: al superar el diario la app pausa hasta el día
# siguiente (se rehabilita solo al cambiar la fecha); al alcanzar el total pausa hasta
# intervención manual. Mismo banner neutro para ambos.
DAILY_BUDGET_USD: float = float(os.getenv("DAILY_BUDGET_USD", "3.0"))
TOTAL_BUDGET_USD: float = float(os.getenv("TOTAL_BUDGET_USD", "10.0"))

# Cuota de conversaciones de por vida por usuario (X-User-Id).
USER_CONVERSATION_QUOTA: int = int(os.getenv("USER_CONVERSATION_QUOTA", "3"))

# Límites del turno/conversación. Se consumen en fases posteriores (endpoints/frontend);
# se declaran acá para mantener config.py como mapa único de la configuración.
MAX_ANSWER_SECONDS: int = int(os.getenv("MAX_ANSWER_SECONDS", "30"))
MAX_QUESTIONS: int = int(os.getenv("MAX_QUESTIONS", "5"))
```

- [ ] **Step 2: Crear el paquete vacío `app/limits/__init__.py`**

```python
```

(Archivo vacío por ahora; en Task 3 exporta la API pública del módulo.)

- [ ] **Step 3: Escribir los tests que fallan `test_app_limits_cost.py`**

```python
"""Caracteriza el cálculo de costo puro (sin BD) con tarifas fijadas por el test."""

import pytest

import config
from app.limits.cost import azure_cost_usd, gemini_cost_usd


def test_gemini_cost_sums_input_and_output_by_rate(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_PRICE_INPUT_PER_1K", 0.01)
    monkeypatch.setattr(config, "GEMINI_PRICE_OUTPUT_PER_1K", 0.03)
    # 2000 in * 0.01/1k + 1000 out * 0.03/1k = 0.02 + 0.03 = 0.05
    assert gemini_cost_usd(2000, 1000) == pytest.approx(0.05)


def test_gemini_cost_zero_tokens_is_zero(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_PRICE_INPUT_PER_1K", 0.01)
    monkeypatch.setattr(config, "GEMINI_PRICE_OUTPUT_PER_1K", 0.03)
    assert gemini_cost_usd(0, 0) == 0.0


def test_azure_cost_is_seconds_by_rate(monkeypatch):
    monkeypatch.setattr(config, "AZURE_SPEECH_PRICE_PER_SECOND", 0.0002)
    assert azure_cost_usd(10.0) == pytest.approx(0.002)


def test_azure_cost_zero_seconds_is_zero(monkeypatch):
    monkeypatch.setattr(config, "AZURE_SPEECH_PRICE_PER_SECOND", 0.0002)
    assert azure_cost_usd(0.0) == 0.0
```

- [ ] **Step 4: Correr los tests y verificar que fallan**

Run: `uv run pytest test_app_limits_cost.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.limits.cost'`.

- [ ] **Step 5: Implementar `app/limits/cost.py`**

```python
"""Cálculo de costo de una llamada facturable, en USD.

Funciones puras: no tocan la base ni la red, solo aplican las tarifas de `config` a la
cantidad consumida. El costo se calcula al registrar cada evento y se guarda ya resuelto,
para que el total sea una simple suma (ver app/limits/repository.py).
"""

import config


def gemini_cost_usd(input_tokens: int, output_tokens: int) -> float:
    """Costo en USD de una llamada a Gemini según tokens de entrada y salida."""
    cost = (
        input_tokens / 1000 * config.GEMINI_PRICE_INPUT_PER_1K
        + output_tokens / 1000 * config.GEMINI_PRICE_OUTPUT_PER_1K
    )
    return round(cost, 6)


def azure_cost_usd(audio_seconds: float) -> float:
    """Costo en USD de la evaluación de Azure según la duración de audio procesada."""
    return round(audio_seconds * config.AZURE_SPEECH_PRICE_PER_SECOND, 6)
```

- [ ] **Step 6: Correr los tests y verificar que pasan**

Run: `uv run pytest test_app_limits_cost.py -v`
Expected: PASS (4 tests).

- [ ] **Step 7: Commit**

```bash
git add config.py app/limits/__init__.py app/limits/cost.py test_app_limits_cost.py
git commit -m "feat(app/limits): constantes de tarifa/cuota en config + calculo de costo puro"
```

---

### Task 2: `model.py` (Decision) + `service.py` (LimitsService con store inyectable)

**Files:**
- Create: `app/limits/model.py`
- Create: `app/limits/repository.py` (solo la interfaz `UsageStore` en esta task; el adaptador Postgres va en Task 3)
- Create: `app/limits/service.py`
- Test: `test_app_limits_service.py`

**Interfaces:**
- Consumes: `app.limits.cost.gemini_cost_usd`, `app.limits.cost.azure_cost_usd`, `config.DAILY_BUDGET_USD`, `config.TOTAL_BUDGET_USD`, `config.USER_CONVERSATION_QUOTA`.
- Produces:
  - `app.limits.model.DecisionKind` (Enum: `ALLOW`, `QUOTA`, `PAUSED_DAILY`, `PAUSED_TOTAL`).
  - `app.limits.model.Decision(kind: DecisionKind)` con propiedades `allowed: bool` y `reason: str | None`.
  - `app.limits.repository.UsageStore` (Protocol `runtime_checkable`) con:
    `add_conversation_start(user_id, conversation_id) -> None`,
    `add_usage_event(user_id, conversation_id, provider, kind, input_tokens, output_tokens, audio_seconds, cost_usd) -> None`,
    `daily_cost_usd() -> float`, `total_cost_usd() -> float`, `conversation_count(user_id) -> int`.
  - `app.limits.service.LimitsService(store: UsageStore)` con:
    `check_can_start(user_id: str) -> Decision`,
    `record_conversation_start(user_id: str, conversation_id: str) -> None`,
    `record_gemini_usage(user_id, conversation_id, kind, input_tokens, output_tokens) -> float`,
    `record_azure_usage(user_id, conversation_id, audio_seconds) -> float`.

- [ ] **Step 1: Implementar `app/limits/model.py`**

```python
"""Value object de la decisión de admisión de una conversación nueva.

`LimitsService.check_can_start` devuelve un `Decision`. El `kind` distingue los cuatro casos
internos (para log/diagnóstico); `reason` los colapsa a lo que necesita el frontend: los dos
tipos de pausa comparten el banner neutro "paused" y la cuota del usuario es "quota".
"""

import enum
from dataclasses import dataclass


class DecisionKind(str, enum.Enum):
    ALLOW = "allow"
    QUOTA = "quota"
    PAUSED_DAILY = "paused_daily"
    PAUSED_TOTAL = "paused_total"


@dataclass(frozen=True)
class Decision:
    kind: DecisionKind

    @property
    def allowed(self) -> bool:
        return self.kind is DecisionKind.ALLOW

    @property
    def reason(self) -> str | None:
        """Motivo para el frontend: None si se permite, 'quota' o 'paused' si no."""
        if self.kind is DecisionKind.ALLOW:
            return None
        if self.kind is DecisionKind.QUOTA:
            return "quota"
        return "paused"  # PAUSED_DAILY y PAUSED_TOTAL comparten banner neutro
```

- [ ] **Step 2: Crear la interfaz `UsageStore` en `app/limits/repository.py`**

(El adaptador Postgres concreto se agrega en Task 3; en esta task solo va el Protocol para que
`LimitsService` y su doble de test tengan un contrato común.)

```python
"""Persistencia del uso facturable y de los inicios de conversación.

`UsageStore` es el contrato que consume `LimitsService`: lecturas para decidir (costo del día,
costo total, nº de conversaciones del usuario) y escrituras para registrar (evento de uso,
inicio de conversación). Es un `Protocol` para que el servicio dependa de la interfaz y no del
Postgres concreto: en los tests se inyecta un doble en memoria. El adaptador Postgres
(`PostgresUsageStore`) se agrega en la misma capa.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class UsageStore(Protocol):
    """Contrato de persistencia que necesita LimitsService."""

    def add_conversation_start(self, user_id: str, conversation_id: str) -> None:
        """Registra que un usuario inició una conversación (para la cuota)."""
        ...

    def add_usage_event(
        self,
        user_id: str,
        conversation_id: str,
        provider: str,
        kind: str,
        input_tokens: int,
        output_tokens: int,
        audio_seconds: float,
        cost_usd: float,
    ) -> None:
        """Registra una llamada facturable con su costo ya calculado."""
        ...

    def daily_cost_usd(self) -> float:
        """Suma del costo de los eventos de hoy (fecha del servidor)."""
        ...

    def total_cost_usd(self) -> float:
        """Suma del costo de todos los eventos."""
        ...

    def conversation_count(self, user_id: str) -> int:
        """Número de conversaciones iniciadas por ese usuario."""
        ...
```

- [ ] **Step 3: Escribir los tests que fallan `test_app_limits_service.py`**

```python
"""Tests del LimitsService: decisión de admisión y registro de uso, con un store falso."""

import pytest

import config
from app.limits.model import DecisionKind
from app.limits.repository import UsageStore
from app.limits.service import LimitsService


class FakeUsageStore:
    """Doble en memoria de UsageStore: valores de lectura fijos y captura de escrituras."""

    def __init__(self, daily=0.0, total=0.0, counts=None):
        self._daily = daily
        self._total = total
        self._counts = dict(counts or {})
        self.starts: list[tuple[str, str]] = []
        self.events: list[tuple] = []

    def add_conversation_start(self, user_id, conversation_id):
        self.starts.append((user_id, conversation_id))
        self._counts[user_id] = self._counts.get(user_id, 0) + 1

    def add_usage_event(self, user_id, conversation_id, provider, kind,
                        input_tokens, output_tokens, audio_seconds, cost_usd):
        self.events.append(
            (user_id, conversation_id, provider, kind,
             input_tokens, output_tokens, audio_seconds, cost_usd)
        )

    def daily_cost_usd(self):
        return self._daily

    def total_cost_usd(self):
        return self._total

    def conversation_count(self, user_id):
        return self._counts.get(user_id, 0)


@pytest.fixture(autouse=True)
def _budgets(monkeypatch):
    """Presupuestos y cuota fijos para que las decisiones sean deterministas."""
    monkeypatch.setattr(config, "DAILY_BUDGET_USD", 3.0)
    monkeypatch.setattr(config, "TOTAL_BUDGET_USD", 10.0)
    monkeypatch.setattr(config, "USER_CONVERSATION_QUOTA", 3)


def test_allows_when_under_all_limits():
    service = LimitsService(FakeUsageStore(daily=0.0, total=0.0, counts={"u1": 0}))
    decision = service.check_can_start("u1")
    assert decision.allowed is True
    assert decision.reason is None


def test_total_budget_reached_pauses():
    service = LimitsService(FakeUsageStore(daily=0.0, total=10.0, counts={"u1": 0}))
    decision = service.check_can_start("u1")
    assert decision.kind is DecisionKind.PAUSED_TOTAL
    assert decision.reason == "paused"


def test_daily_budget_reached_pauses():
    service = LimitsService(FakeUsageStore(daily=3.0, total=5.0, counts={"u1": 0}))
    decision = service.check_can_start("u1")
    assert decision.kind is DecisionKind.PAUSED_DAILY
    assert decision.reason == "paused"


def test_quota_exhausted_blocks_user():
    service = LimitsService(FakeUsageStore(daily=0.0, total=0.0, counts={"u1": 3}))
    decision = service.check_can_start("u1")
    assert decision.kind is DecisionKind.QUOTA
    assert decision.reason == "quota"


def test_total_budget_takes_precedence_over_quota():
    # Aunque el usuario agotó su cuota, la pausa global manda (protege el costo).
    service = LimitsService(FakeUsageStore(daily=0.0, total=10.0, counts={"u1": 3}))
    assert service.check_can_start("u1").kind is DecisionKind.PAUSED_TOTAL


def test_record_conversation_start_delegates_to_store():
    store = FakeUsageStore()
    LimitsService(store).record_conversation_start("u1", "c1")
    assert store.starts == [("u1", "c1")]


def test_record_gemini_usage_computes_cost_and_stores_event(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_PRICE_INPUT_PER_1K", 0.01)
    monkeypatch.setattr(config, "GEMINI_PRICE_OUTPUT_PER_1K", 0.03)
    store = FakeUsageStore()
    cost = LimitsService(store).record_gemini_usage("u1", "c1", "question", 2000, 1000)
    assert cost == pytest.approx(0.05)
    assert len(store.events) == 1
    event = store.events[0]
    assert event[2] == "gemini"          # provider
    assert event[3] == "question"        # kind
    assert event[7] == pytest.approx(0.05)  # cost_usd


def test_record_azure_usage_computes_cost_and_stores_event(monkeypatch):
    monkeypatch.setattr(config, "AZURE_SPEECH_PRICE_PER_SECOND", 0.0002)
    store = FakeUsageStore()
    cost = LimitsService(store).record_azure_usage("u1", "c1", 10.0)
    assert cost == pytest.approx(0.002)
    event = store.events[0]
    assert event[2] == "azure"           # provider
    assert event[3] == "assessment"      # kind
    assert event[6] == pytest.approx(10.0)  # audio_seconds


def test_fake_store_conforms_to_protocol():
    # El doble implementa la misma interfaz que el adaptador real (Protocol runtime_checkable).
    assert isinstance(FakeUsageStore(), UsageStore)
```

- [ ] **Step 4: Correr los tests y verificar que fallan**

Run: `uv run pytest test_app_limits_service.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'app.limits.service'`.

- [ ] **Step 5: Implementar `app/limits/service.py`**

```python
"""Servicio de límites: decide la admisión de una conversación y registra el uso.

Compone las lecturas del `UsageStore` con los presupuestos/cuota de `config` para producir una
`Decision`, y ofrece helpers que calculan el costo (vía app/limits/cost) y lo persisten como
evento. Depende de la interfaz `UsageStore`, no del Postgres concreto, así su lógica se prueba
con un doble en memoria. La construcción real (`build_limits_service`) vive en __init__.py.
"""

import config
from app.limits.cost import azure_cost_usd, gemini_cost_usd
from app.limits.model import Decision, DecisionKind
from app.limits.repository import UsageStore


class LimitsService:
    """Aplica cuota por usuario y presupuesto diario/total sobre eventos persistidos."""

    def __init__(self, store: UsageStore) -> None:
        self._store = store

    def check_can_start(self, user_id: str) -> Decision:
        """Decide si `user_id` puede iniciar una conversación.

        Precedencia: tope total → presupuesto diario → cuota del usuario → permitir. El
        presupuesto global protege el costo por encima de la cuota individual.
        """
        if self._store.total_cost_usd() >= config.TOTAL_BUDGET_USD:
            return Decision(DecisionKind.PAUSED_TOTAL)
        if self._store.daily_cost_usd() >= config.DAILY_BUDGET_USD:
            return Decision(DecisionKind.PAUSED_DAILY)
        if self._store.conversation_count(user_id) >= config.USER_CONVERSATION_QUOTA:
            return Decision(DecisionKind.QUOTA)
        return Decision(DecisionKind.ALLOW)

    def record_conversation_start(self, user_id: str, conversation_id: str) -> None:
        """Registra el inicio de una conversación (cuenta para la cuota del usuario)."""
        self._store.add_conversation_start(user_id, conversation_id)

    def record_gemini_usage(
        self,
        user_id: str,
        conversation_id: str,
        kind: str,
        input_tokens: int,
        output_tokens: int,
    ) -> float:
        """Calcula y persiste el costo de una llamada a Gemini. Devuelve el costo en USD."""
        cost = gemini_cost_usd(input_tokens, output_tokens)
        self._store.add_usage_event(
            user_id, conversation_id, "gemini", kind,
            input_tokens, output_tokens, 0.0, cost,
        )
        return cost

    def record_azure_usage(
        self, user_id: str, conversation_id: str, audio_seconds: float
    ) -> float:
        """Calcula y persiste el costo de la evaluación de Azure. Devuelve el costo en USD."""
        cost = azure_cost_usd(audio_seconds)
        self._store.add_usage_event(
            user_id, conversation_id, "azure", "assessment",
            0, 0, audio_seconds, cost,
        )
        return cost
```

- [ ] **Step 6: Correr los tests y verificar que pasan**

Run: `uv run pytest test_app_limits_service.py -v`
Expected: PASS (9 tests).

- [ ] **Step 7: Commit**

```bash
git add app/limits/model.py app/limits/repository.py app/limits/service.py test_app_limits_service.py
git commit -m "feat(app/limits): LimitsService (decision de admision + registro de uso) con store inyectable"
```

---

### Task 3: Adaptador Postgres + DDL de las tablas + API pública del módulo

**Files:**
- Modify: `app/limits/repository.py` (agrega `PostgresUsageStore` bajo el Protocol ya existente)
- Modify: `app/storage.py` (extiende el esquema con `usage_events` y `conversation_starts`)
- Create: `docker/initdb/02-usage-and-starts.sql` (mismo DDL para el init del contenedor)
- Modify: `app/limits/__init__.py` (exporta la API pública + `build_limits_service`)
- Test: `test_app_limits_repository.py`

**Interfaces:**
- Consumes: `app.storage.PostgresStorage`, `app.limits.service.LimitsService`, `app.limits.repository.UsageStore`.
- Produces:
  - `app.limits.repository.PostgresUsageStore(storage: PostgresStorage)` que implementa `UsageStore`.
  - `app.limits.build_limits_service(storage: PostgresStorage) -> LimitsService`.
  - Reexporta `LimitsService`, `Decision`, `DecisionKind`, `UsageStore`, `PostgresUsageStore`.

- [ ] **Step 1: Escribir los tests que fallan `test_app_limits_repository.py`**

```python
"""Verifica de forma estructural (sin BD viva) el adaptador Postgres y el DDL del esquema.

Los repositorios Postgres de app/ son adaptadores delgados y no se testean unitariamente
(igual que ConversationRepository); acá se comprueba que el adaptador conforma la interfaz
UsageStore y que el esquema incluye las tablas nuevas.
"""

from app.limits import PostgresUsageStore, build_limits_service
from app.limits.repository import UsageStore
from app.limits.service import LimitsService
from app.storage import PostgresStorage


def test_postgres_store_conforms_to_protocol():
    store = PostgresUsageStore(PostgresStorage("postgresql://x/y"))
    assert isinstance(store, UsageStore)


def test_build_limits_service_returns_service():
    service = build_limits_service(PostgresStorage("postgresql://x/y"))
    assert isinstance(service, LimitsService)


def test_storage_schema_includes_new_tables():
    from app.storage import _SCHEMA

    schema_sql = " ".join(_SCHEMA)
    assert "usage_events" in schema_sql
    assert "conversation_starts" in schema_sql
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `uv run pytest test_app_limits_repository.py -v`
Expected: FAIL con `ImportError: cannot import name 'PostgresUsageStore' from 'app.limits'`.

- [ ] **Step 3: Agregar `PostgresUsageStore` a `app/limits/repository.py`**

Añadir estos imports al inicio del archivo (junto al `from typing import ...` ya existente):

```python
from app.storage import PostgresStorage
```

Y agregar la clase al final del archivo (debajo del Protocol `UsageStore`):

```python
class PostgresUsageStore:
    """Adaptador Postgres de UsageStore. Aísla el SQL; recibe el almacenamiento inyectado.

    Sigue el mismo patrón que ConversationRepository: abre una conexión nueva por operación
    vía `storage.connect()` y no crea la tabla (eso lo hace `PostgresStorage.init_schema()` o
    el init del contenedor). `created_at` lo pone Postgres por DEFAULT now().
    """

    def __init__(self, storage: PostgresStorage) -> None:
        self._storage = storage

    def add_conversation_start(self, user_id: str, conversation_id: str) -> None:
        with self._storage.connect() as conn:
            conn.execute(
                "INSERT INTO conversation_starts (user_id, conversation_id) VALUES (%s, %s)",
                (user_id, conversation_id),
            )

    def add_usage_event(
        self,
        user_id: str,
        conversation_id: str,
        provider: str,
        kind: str,
        input_tokens: int,
        output_tokens: int,
        audio_seconds: float,
        cost_usd: float,
    ) -> None:
        with self._storage.connect() as conn:
            conn.execute(
                "INSERT INTO usage_events "
                "(user_id, conversation_id, provider, kind, input_tokens, output_tokens, "
                "audio_seconds, cost_usd) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (user_id, conversation_id, provider, kind, input_tokens, output_tokens,
                 audio_seconds, cost_usd),
            )

    def daily_cost_usd(self) -> float:
        with self._storage.connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM usage_events "
                "WHERE created_at::date = CURRENT_DATE"
            ).fetchone()
        assert row is not None  # COALESCE + agregado sin GROUP BY siempre devuelve una fila
        return float(row["total"])

    def total_cost_usd(self) -> float:
        with self._storage.connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(SUM(cost_usd), 0) AS total FROM usage_events"
            ).fetchone()
        assert row is not None
        return float(row["total"])

    def conversation_count(self, user_id: str) -> int:
        with self._storage.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM conversation_starts WHERE user_id = %s",
                (user_id,),
            ).fetchone()
        assert row is not None
        return int(row["n"])
```

- [ ] **Step 4: Extender el esquema en `app/storage.py`**

Reemplazar la constante `_SCHEMA` (que hoy es un único string con `conversation_configs`) por una
tupla de sentencias, y ajustar `init_schema` para ejecutarlas una a una (psycopg ejecuta una
sentencia por `execute`). Sustituir el bloque `_SCHEMA = """..."""` y el método `init_schema`
por lo siguiente:

```python
# DDL de las tablas de app/. Es la misma definición que usan los scripts de init del
# contenedor Postgres (docker/initdb/*.sql); se expone acá para poder crear el esquema
# desde código en un entorno standalone. Una sentencia por elemento (psycopg ejecuta una
# sentencia por llamada a execute).
_SCHEMA: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS conversation_configs (
        id           INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        created_at   TEXT NOT NULL,
        updated_at   TEXT NOT NULL,
        name         TEXT NOT NULL,
        user_context TEXT NOT NULL
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS usage_events (
        id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        user_id         TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        provider        TEXT NOT NULL,
        kind            TEXT NOT NULL,
        input_tokens    INTEGER NOT NULL DEFAULT 0,
        output_tokens   INTEGER NOT NULL DEFAULT 0,
        audio_seconds   REAL NOT NULL DEFAULT 0,
        cost_usd        NUMERIC(10,6) NOT NULL DEFAULT 0
    );
    """,
    """
    CREATE TABLE IF NOT EXISTS conversation_starts (
        id              INTEGER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        user_id         TEXT NOT NULL,
        conversation_id TEXT NOT NULL
    );
    """,
)
```

Y reemplazar el método `init_schema`:

```python
    def init_schema(self) -> None:
        """Crea las tablas de app/ si no existen (uso standalone, sin compose)."""
        with self.connect() as conn:
            for statement in _SCHEMA:
                conn.execute(statement)
```

- [ ] **Step 5: Crear el DDL del contenedor `docker/initdb/02-usage-and-starts.sql`**

```sql
-- Tablas operativas del piloto (app/limits): costo por evento y cuota por usuario.
-- Postgres ejecuta los .sql de docker-entrypoint-initdb.d una sola vez, al crear el volumen.
-- Debe coincidir con el DDL de PostgresStorage.init_schema() (app/storage.py).

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
```

- [ ] **Step 6: Exportar la API pública en `app/limits/__init__.py`**

```python
"""Módulo de límites del piloto: costo, cuota por usuario y presupuesto diario/total.

Expone el servicio inyectable y su construcción desde el almacenamiento. La lógica de decisión
vive en service.py; el cálculo de costo en cost.py; la persistencia en repository.py.
"""

from app.limits.model import Decision, DecisionKind
from app.limits.repository import PostgresUsageStore, UsageStore
from app.limits.service import LimitsService
from app.storage import PostgresStorage

__all__ = [
    "Decision",
    "DecisionKind",
    "LimitsService",
    "PostgresUsageStore",
    "UsageStore",
    "build_limits_service",
]


def build_limits_service(storage: PostgresStorage) -> LimitsService:
    """Arma el LimitsService con el adaptador Postgres sobre el almacenamiento compartido.

    A diferencia de speech/conversación, limits NO degrada a None: si Postgres está caído, la
    decisión conservadora (cortar) la toma la Fase 3 al fallar la consulta. Acá solo se compone.
    """
    return LimitsService(PostgresUsageStore(storage))
```

- [ ] **Step 7: Correr los tests y verificar que pasan**

Run: `uv run pytest test_app_limits_repository.py -v`
Expected: PASS (3 tests).

- [ ] **Step 8: Correr toda la suite del módulo para verificar que nada se rompió**

Run: `uv run pytest test_app_limits_cost.py test_app_limits_service.py test_app_limits_repository.py -v`
Expected: PASS (16 tests en total).

- [ ] **Step 9: Verificar que el resto de la suite sigue verde (cambió `app/storage.py`)**

Run: `uv run pytest -q`
Expected: PASS (la suite completa; el cambio de `_SCHEMA` a tupla no afecta a `ConversationRepository`, que no lo usa).

- [ ] **Step 10: Commit**

```bash
git add app/limits/repository.py app/limits/__init__.py app/storage.py docker/initdb/02-usage-and-starts.sql test_app_limits_repository.py
git commit -m "feat(app/limits): adaptador Postgres + DDL de usage_events/conversation_starts + build"
```

---

## Notas para el que ejecute

- Esta fase **no** toca `app/cmd/server.py`. La inyección del `LimitsService` en el composition
  root (reutilizando el `_storage` que ya existe ahí) y el chequeo `check_can_start` en
  `/conversation/start`, más el registro de `usage_events` en `/conversation/answer`, van en la
  **Fase 3** (`docs/superpowers/plans/` siguiente).
- `PostgresUsageStore` no tiene test unitario a propósito: es un adaptador delgado sobre SQL, igual
  que `ConversationRepository`. La lógica arriesgada (decisión y costo) sí está cubierta con dobles.
  Si más adelante se quiere una prueba de integración contra un Postgres real, va aparte y se salta
  cuando la BD no está disponible.
- El cambio de `_SCHEMA` (string → tupla de sentencias) es necesario porque psycopg ejecuta una
  sentencia por `execute`; se mantiene el DDL de `conversation_configs` idéntico, solo reorganizado.
- Las tarifas por defecto de `config.py` son aproximaciones del piloto; el costo se afina por env,
  no tocando código.
