"""Cálculo de costo de una llamada facturable, en USD.

Funciones puras: no tocan la base ni la red, solo aplican las tarifas de `config` a la
cantidad consumida. El costo se calcula al registrar cada evento y se guarda ya resuelto,
para que el total sea una simple suma (ver app/limits/repository.py).
"""

from config import settings


def gemini_cost_usd(input_tokens: int, output_tokens: int) -> float:
    """Costo en USD de una llamada a Gemini según tokens de entrada y salida."""
    # NOTE: asume UN solo modelo. Desde que el revisor puede correr en otro
    # (`REVIEW_CHAT_MODEL`), si ese modelo es mas caro que el del tutor este calculo
    # SUBESTIMA: los tokens del revisor se cobran a la tarifa del tutor. Arreglarlo es
    # cambiar el par de precios por un mapa modelo -> (precio_in, precio_out) y que
    # `_gemini_tokens` en server.py devuelva el desglose en vez de agregar;
    # `callback.usage_metadata` ya viene indexado por nombre de modelo.
    cost = (
        input_tokens / 1000 * settings.GEMINI_PRICE_INPUT_PER_1K
        + output_tokens / 1000 * settings.GEMINI_PRICE_OUTPUT_PER_1K
    )
    return round(cost, 6)


def azure_cost_usd(audio_seconds: float) -> float:
    """Costo en USD de la evaluación de Azure según la duración de audio procesada."""
    return round(audio_seconds * settings.AZURE_SPEECH_PRICE_PER_SECOND, 6)
