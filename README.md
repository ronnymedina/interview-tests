# review-ingles

Practica de pronunciacion en ingles. Guardas tus textos, los lees en voz alta, y el API
de Azure Speech (Pronunciation Assessment) te dice que palabras y que sonidos fallaste.

> **Proyecto solo para uso local.** Esta pensado para correr en tu propia maquina
> (`localhost`) como herramienta personal para **mejorar la pronunciacion de cara a
> procesos de entrevista de trabajo** en ingles. No tiene autenticacion ni esta
> preparado para desplegarse en internet. Las credenciales viven solo en tu `.env`
> local (ignorado por git); ver [VARIABLES-DE-ENTORNO.md](VARIABLES-DE-ENTORNO.md).

## Puesta en marcha

1. **Crear el recurso en Azure**
   Portal de Azure → *Create a resource* → **Speech** → crealo (el tier gratuito `F0`
   alcanza de sobra: 5 horas de audio al mes).
   Cuando termine, entra al recurso → *Keys and Endpoint* y copia **KEY 1** y la
   **Location/Region** (ej. `eastus`).

2. **Configurar**

   ```bash
   cp .env.example .env
   ```

   Edita `.env` y pega tu key y tu region.

3. **Instalar y correr**

   ```bash
   uv sync
   uv run python main.py
   ```

4. Abre <http://127.0.0.1:8000>

## Como se usa

1. En la pestana **Textos**, crea un texto (titulo, contenido y dificultad opcional
   del 1 al 10). Puedes editarlo o borrarlo despues; borrar un texto elimina tambien
   sus intentos.
2. En **Practicar**, elige un texto guardado del selector.
3. **Hablar** → lee el texto en voz alta → **Parar**.
   **Cancelar** descarta el intento sin enviarlo.
4. Mira los resultados:
   - **Pronunciation** — score global.
   - **Accuracy** — que tan parecidos son tus sonidos a los de un nativo.
   - **Fluency** — si tus pausas entre palabras son naturales.
   - **Completeness** — cuanto del texto de referencia llegaste a decir.
   - **Prosody** — entonacion, ritmo y velocidad.
5. En *Palabra por palabra*, el color del subrayado indica el score
   (verde ≥ 80, ambar 60–79, rojo < 60). Gris punteado = no la dijiste,
   tachada = dijiste algo que no estaba en el texto.
   **Haz clic en una palabra** para ver el score de cada sonido (IPA): ahi ves
   exactamente que fonema necesitas practicar.

Cada intento queda guardado en `attempts.db` (sqlite) y aparece en el historial.

## Archivos

| Archivo | Que hace |
|---|---|
| `config.py` | Unico lugar que lee variables de entorno |
| `db.py` | Guarda textos e intentos en sqlite |
| `azure_speech.py` | Wrapper (`AzureSpeechClient`): unico punto que llama al API de Azure |
| `speech.py` | Logica de pronunciacion: normaliza, usa el wrapper y arma el resultado |
| `main.py` | Servidor FastAPI y rutas |
| `index.html`, `app.js`, `style.css` | La pagina: grabacion y visualizacion |

## Pronunciation Assessment de Azure

Referencia oficial:
[How to use pronunciation assessment (Python)](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-pronunciation-assessment?pivots=programming-language-python).

### Los scores

| Score | Que mide |
|---|---|
| **Accuracy** | Que tan parecidos son tus fonemas a los de un nativo. Se agrega desde el nivel de fonema a silaba, palabra y texto completo. |
| **Fluency** | Que tan naturales son tus pausas (silencios) entre palabras. |
| **Completeness** | Proporcion de palabras pronunciadas respecto al texto de referencia. |
| **Prosody** | Naturalidad del habla: acento, entonacion, velocidad y ritmo. Solo disponible en `en-US` y SDK ≥ 1.35. |
| **Pronunciation** (`PronScore`) | Score global, ponderado a partir de los anteriores. |

**Formula del score global** (ordenando los sub-scores de menor a mayor, `s0`..`s3`):

- Con prosodia: `PronScore = 0.4*s0 + 0.2*s1 + 0.2*s2 + 0.2*s3`
- Sin prosodia: `PronScore = 0.6*s0 + 0.2*s1 + 0.2*s2`

El peor score pesa mas. Es exactamente lo que replica `_aggregate()` en `speech.py`.

### Configuracion que usa este proyecto

Fijada en `azure_speech.py` (`AzureSpeechClient`):

- `PronunciationAssessmentGradingSystem.HundredMark` — scores de 0 a 100.
- `PronunciationAssessmentGranularity.Phoneme` — devuelve score por fonema, silaba,
  palabra y texto completo.
- `enable_prosody_assessment()` — activa el score de prosodia (solo `en-US`).
- `phoneme_alphabet = "IPA"` — fonemas en alfabeto IPA (los que pinta la pagina).

### `ErrorType` por palabra

Azure marca cada palabra con: `None`, `Omission`, `Insertion`, `Mispronunciation`,
`UnexpectedBreak`, `MissingBreak` o `Monotone`. Una palabra es `Mispronunciation`
cuando su `AccuracyScore` esta por debajo de 60.

### Modo continuo y miscue (importante)

Este proyecto usa **reconocimiento continuo** (sin el limite de ~30 s del modo
`recognize_once`). Segun la doc, en modo continuo **`EnableMiscue` no esta soportado**:
Azure no marca por si mismo `Omission` ni `Insertion`. Para obtener esas etiquetas hay
que **comparar lo reconocido contra el texto de referencia**, que es justo lo que hace
`speech.py` con `difflib`, siguiendo el
[sample oficial en Python](https://github.com/Azure-Samples/cognitive-services-speech-sdk/blob/master/scenarios/python/console/language-learning/pronunciation_assessment.py)
(`pronunciation_assessment_continuous_from_file`).

## Limites

- **Maximo 30 segundos de audio por intento.** Es el limite del modo `recognize_once`
  con deteccion de omisiones activada. La pagina corta la grabacion sola al llegar.
  Practica con parrafos cortos.
- Servidor pensado para `localhost`: no tiene autenticacion.
