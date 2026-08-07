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
