"""Tests del LimitsService: decisión de admisión y registro de uso, con un store falso."""

import pytest

from app.limits.model import DecisionKind
from app.limits.repository import UsageStore
from app.limits.service import LimitsService
from config import settings


class FakeUsageStore:
    """Doble en memoria de UsageStore: valores de lectura fijos y captura de escrituras."""

    def __init__(self, daily=0.0, total=0.0, counts=None, reading_counts=None):
        self._daily = daily
        self._total = total
        self._counts = dict(counts or {})
        self._reading_counts = dict(reading_counts or {})
        self.starts: list[tuple[str, str]] = []
        self.reading_starts: list[tuple[str, int]] = []
        self.events: list[tuple] = []

    def add_conversation_start(self, user_id, conversation_id):
        self.starts.append((user_id, conversation_id))
        self._counts[user_id] = self._counts.get(user_id, 0) + 1

    def add_reading_start(self, user_id, reading_id):
        self.reading_starts.append((user_id, reading_id))
        self._reading_counts[user_id] = self._reading_counts.get(user_id, 0) + 1

    def reading_count(self, user_id):
        return self._reading_counts.get(user_id, 0)

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
    monkeypatch.setattr(settings, "DAILY_BUDGET_USD", 3.0)
    monkeypatch.setattr(settings, "TOTAL_BUDGET_USD", 10.0)
    monkeypatch.setattr(settings, "USER_CONVERSATION_QUOTA", 3)
    monkeypatch.setattr(settings, "USER_READING_QUOTA", 5)


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
    monkeypatch.setattr(settings, "GEMINI_PRICE_INPUT_PER_1K", 0.01)
    monkeypatch.setattr(settings, "GEMINI_PRICE_OUTPUT_PER_1K", 0.03)
    store = FakeUsageStore()
    cost = LimitsService(store).record_gemini_usage("u1", "c1", "question", 2000, 1000)
    assert cost == pytest.approx(0.05)
    assert len(store.events) == 1
    event = store.events[0]
    assert event[2] == "gemini"          # provider
    assert event[3] == "question"        # kind
    assert event[7] == pytest.approx(0.05)  # cost_usd


def test_record_azure_usage_computes_cost_and_stores_event(monkeypatch):
    monkeypatch.setattr(settings, "AZURE_SPEECH_PRICE_PER_SECOND", 0.0002)
    store = FakeUsageStore()
    cost = LimitsService(store).record_azure_usage("u1", "c1", 10.0)
    assert cost == pytest.approx(0.002)
    event = store.events[0]
    assert event[2] == "azure"           # provider
    assert event[3] == "assessment"      # kind
    assert event[6] == pytest.approx(10.0)  # audio_seconds


# --- cuota de la práctica de lectura ---------------------------------------------------

def test_check_can_read_allows_under_quota():
    service = LimitsService(FakeUsageStore(reading_counts={"u1": 4}))
    assert service.check_can_read("u1").allowed is True


def test_check_can_read_blocks_at_quota():
    service = LimitsService(FakeUsageStore(reading_counts={"u1": 5}))
    decision = service.check_can_read("u1")
    assert decision.kind is DecisionKind.QUOTA
    assert decision.reason == "quota"


def test_reading_quota_is_independent_from_conversation_quota():
    """Leer no debe gastarte las conversaciones: son modalidades distintas."""
    store = FakeUsageStore(counts={"u1": 3}, reading_counts={"u1": 0})
    service = LimitsService(store)
    assert service.check_can_start("u1").allowed is False
    assert service.check_can_read("u1").allowed is True


def test_total_budget_also_pauses_reading():
    """El dinero sí es uno solo: el presupuesto global corta las dos modalidades."""
    service = LimitsService(FakeUsageStore(total=10.0, reading_counts={"u1": 0}))
    decision = service.check_can_read("u1")
    assert decision.kind is DecisionKind.PAUSED_TOTAL
    assert decision.reason == "paused"


def test_daily_budget_also_pauses_reading():
    service = LimitsService(FakeUsageStore(daily=3.0, reading_counts={"u1": 0}))
    assert service.check_can_read("u1").kind is DecisionKind.PAUSED_DAILY


def test_record_reading_start_delegates_to_store():
    store = FakeUsageStore()
    LimitsService(store).record_reading_start("u1", 42)
    assert store.reading_starts == [("u1", 42)]


def test_record_azure_usage_accepts_a_custom_kind(monkeypatch):
    """La lectura registra su propio kind para poder separar costos por modalidad."""
    monkeypatch.setattr(settings, "AZURE_SPEECH_PRICE_PER_SECOND", 0.0002)
    store = FakeUsageStore()
    LimitsService(store).record_azure_usage("u1", "7", 10.0, kind="reading_assessment")
    assert store.events[0][3] == "reading_assessment"


def test_fake_store_conforms_to_protocol():
    # El doble implementa la misma interfaz que el adaptador real (Protocol runtime_checkable).
    assert isinstance(FakeUsageStore(), UsageStore)
