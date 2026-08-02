"""Módulo de feedback del piloto: formulario validado + su persistencia en Postgres."""

from app.feedback.repository import FeedbackRepository
from app.feedback.schemas import FeedbackRequest

__all__ = ["FeedbackRepository", "FeedbackRequest"]
