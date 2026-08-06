"""Tests del LimitsService: decisión de admisión y registro de uso, con un store falso."""

import pytest

from config import settings
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
    monkeypatch.setattr(settings, "DAILY_BUDGET_USD", 3.0)
    monkeypatch.setattr(settings, "TOTAL_BUDGET_USD", 10.0)
    monkeypatch.setattr(settings, "USER_CONVERSATION_QUOTA", 3)


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


def test_fake_store_conforms_to_protocol():
    # El doble implementa la misma interfaz que el adaptador real (Protocol runtime_checkable).
    assert isinstance(FakeUsageStore(), UsageStore)
