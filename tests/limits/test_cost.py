"""Caracteriza el cálculo de costo puro (sin BD) con tarifas fijadas por el test."""

import pytest

from config import settings
from app.limits.cost import azure_cost_usd, gemini_cost_usd


def test_gemini_cost_sums_input_and_output_by_rate(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_PRICE_INPUT_PER_1K", 0.01)
    monkeypatch.setattr(settings, "GEMINI_PRICE_OUTPUT_PER_1K", 0.03)
    # 2000 in * 0.01/1k + 1000 out * 0.03/1k = 0.02 + 0.03 = 0.05
    assert gemini_cost_usd(2000, 1000) == pytest.approx(0.05)


def test_gemini_cost_zero_tokens_is_zero(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_PRICE_INPUT_PER_1K", 0.01)
    monkeypatch.setattr(settings, "GEMINI_PRICE_OUTPUT_PER_1K", 0.03)
    assert gemini_cost_usd(0, 0) == 0.0


def test_azure_cost_is_seconds_by_rate(monkeypatch):
    monkeypatch.setattr(settings, "AZURE_SPEECH_PRICE_PER_SECOND", 0.0002)
    assert azure_cost_usd(10.0) == pytest.approx(0.002)


def test_azure_cost_zero_seconds_is_zero(monkeypatch):
    monkeypatch.setattr(settings, "AZURE_SPEECH_PRICE_PER_SECOND", 0.0002)
    assert azure_cost_usd(0.0) == 0.0
