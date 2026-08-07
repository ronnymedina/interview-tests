# El Pronunciation Assessment de Azure

Como funciona la evaluacion de pronunciacion y que configuracion usa este proyecto.

Referencia oficial:
[How to use pronunciation assessment (Python)](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-pronunciation-assessment?pivots=programming-language-python).

## Los scores

| Score | Que mide |
|---|---|
| **Accuracy** | Que tan parecidos son tus fonemas a los de un nativo. Se agrega desde el nivel de fonema a silaba, palabra y texto completo. |
| **Fluency** | Que tan naturales son tus pausas (silencios) entre palabras. |
| **Completeness** | Proporcion de palabras pronunciadas respecto al texto de referencia. Solo aplica cuando hay texto de referencia (lectura). |
| **Prosody** | Naturalidad del habla: acento, entonacion, velocidad y ritmo. Solo disponible en `en-US` y SDK ≥ 1.35. |
| **Pronunciation** (`PronScore`) | Score global, ponderado a partir de los anteriores. |

**Formula del score global** (ordenando los sub-scores de menor a mayor, `s0`..`s3`):

- Con prosodia: `PronScore = 0.4*s0 + 0.2*s1 + 0.2*s2 + 0.2*s3`
- Sin prosodia: `PronScore = 0.6*s0 + 0.2*s1 + 0.2*s2`

El peor score pesa mas. Es exactamente lo que replica el agregado en `app/speech/`.

## Configuracion que usa este proyecto

Fijada en `app/speech/azure_client.py`:

- `PronunciationAssessmentGradingSystem.HundredMark` — scores de 0 a 100.
- `PronunciationAssessmentGranularity.Phoneme` — score por fonema, silaba, palabra y texto.
- `enable_prosody_assessment()` — activa el score de prosodia (solo `en-US`).
- `phoneme_alphabet = "IPA"` — fonemas en alfabeto IPA (los que pinta la pagina).

## `ErrorType` por palabra

Azure marca cada palabra con: `None`, `Omission`, `Insertion`, `Mispronunciation`,
`UnexpectedBreak`, `MissingBreak` o `Monotone`. Una palabra es `Mispronunciation` cuando su
`AccuracyScore` esta por debajo de 60.

## Modo continuo y miscue

Se usa **reconocimiento continuo** (sin el limite de ~30 s del modo `recognize_once`). En
modo continuo **`EnableMiscue` no esta soportado**: Azure no marca por si mismo `Omission`
ni `Insertion`. Para obtener esas etiquetas hay que **comparar lo reconocido contra el texto
de referencia**, que es justo lo que hace `app/speech/assessment.py` con `difflib`, siguiendo
el [sample oficial en Python](https://github.com/Azure-Samples/cognitive-services-speech-sdk/blob/master/scenarios/python/console/language-learning/pronunciation_assessment.py)
(`pronunciation_assessment_continuous_from_file`).

## El extracto de lectura

El texto que se lee es un **extracto** del articulo (`READING_MAX_WORDS`, 120 por defecto),
recortado en limite de oracion. El articulo se guarda completo; el recorte se calcula al
servir y se vuelve a calcular al evaluar a partir del id del texto. Por eso el navegador
nunca manda el texto de referencia: lo pone el servidor.

El selector **Nivel maximo** de la pantalla es un tope, no un nivel exacto: pedir 5 puede
darte un 4 o un 5. Si no hay ningun texto que cumpla, la app lo dice en vez de darte uno mas
dificil.
