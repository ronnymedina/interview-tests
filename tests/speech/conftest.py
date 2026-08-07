"""Fixtures comunes a los tests de app/speech."""

import pytest

from config import settings


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    """assess_scripted/assess_unscripted exigen una key; en los tests basta una cualquiera.
    Va en conftest porque lo necesitan todos los módulos de acá, no uno solo."""
    monkeypatch.setattr(settings, "AZURE_SPEECH_KEY", "test-key")
