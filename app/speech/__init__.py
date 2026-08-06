"""Módulo de evaluación de pronunciación (Azure) del piloto.

Expone el servicio inyectable y su construcción desde config. La conexión con el SDK vive en
azure_client.py; la lógica de scoring en assessment.py y scoring.py.
"""

from app.speech.assessment import SpeechError, assess_scripted
from app.speech.service import SpeechService, build_speech_service

__all__ = ["SpeechService", "SpeechError", "assess_scripted", "build_speech_service"]
