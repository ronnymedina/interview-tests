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
