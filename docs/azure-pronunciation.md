# Azure Pronunciation Assessment

How the pronunciation assessment works and which configuration this project uses.

Official reference:
[How to use pronunciation assessment (Python)](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-pronunciation-assessment?pivots=programming-language-python).

## The scores

| Score | What it measures |
|---|---|
| **Accuracy** | How close your phonemes are to a native speaker's. Aggregated from phoneme level up to syllable, word and full text. |
| **Fluency** | How natural your pauses (silences) between words are. |
| **Completeness** | Ratio of words pronounced against the reference text. Only applies when there is a reference text (reading). |
| **Prosody** | Naturalness of speech: stress, intonation, speed and rhythm. Only available on `en-US` and SDK ≥ 1.35. |
| **Pronunciation** (`PronScore`) | Overall score, weighted from the ones above. |

**Overall score formula** (sorting the sub-scores from lowest to highest, `s0`..`s3`):

- With prosody: `PronScore = 0.4*s0 + 0.2*s1 + 0.2*s2 + 0.2*s3`
- Without prosody: `PronScore = 0.6*s0 + 0.2*s1 + 0.2*s2`

The worst score weighs the most. That is exactly what the aggregation in `app/speech/`
replicates.

## Configuration this project uses

Set in `app/speech/azure_client.py`:

- `PronunciationAssessmentGradingSystem.HundredMark` — scores from 0 to 100.
- `PronunciationAssessmentGranularity.Phoneme` — score per phoneme, syllable, word and text.
- `enable_prosody_assessment()` — turns on the prosody score (`en-US` only).
- `phoneme_alphabet = "IPA"` — phonemes in the IPA alphabet (the ones the page renders).

## Per-word `ErrorType`

Azure marks every word with: `None`, `Omission`, `Insertion`, `Mispronunciation`,
`UnexpectedBreak`, `MissingBreak` or `Monotone`. A word is `Mispronunciation` when its
`AccuracyScore` falls below 60.

## Continuous mode and miscue

The project uses **continuous recognition** (no ~30 s limit like `recognize_once` mode). In
continuous mode **`EnableMiscue` is not supported**: Azure does not mark `Omission` or
`Insertion` by itself. Getting those labels requires **comparing what was recognized against
the reference text**, which is exactly what `app/speech/assessment.py` does with `difflib`,
following the
[official Python sample](https://github.com/Azure-Samples/cognitive-services-speech-sdk/blob/master/scenarios/python/console/language-learning/pronunciation_assessment.py)
(`pronunciation_assessment_continuous_from_file`).

## The reading excerpt

The text being read is an **excerpt** of the article (`READING_MAX_WORDS`, 120 by default),
trimmed at a sentence boundary. The article is stored whole; the excerpt is computed when
serving and recomputed when assessing, from the text id. That is why the browser never sends
the reference text: the server supplies it.

The screen's **Maximum level** selector is a cap, not an exact level: asking for 5 may give
you a 4 or a 5. If no text qualifies, the app says so instead of handing you a harder one.
