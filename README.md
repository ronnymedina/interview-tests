# review-ingles

Practica de pronunciacion en ingles. Guardas tus textos, los lees en voz alta, y el API
de Azure Speech (Pronunciation Assessment) te dice que palabras y que sonidos fallaste.

> **Proyecto solo para uso local.** Esta pensado para correr en tu propia maquina
> (`localhost`) como herramienta personal para **mejorar la pronunciacion de cara a
> procesos de entrevista de trabajo** en ingles. No tiene autenticacion ni esta
> preparado para desplegarse en internet. Las credenciales viven solo en tu `.env`
> local (ignorado por git); ver [VARIABLES-DE-ENTORNO.md](VARIABLES-DE-ENTORNO.md).

## Puesta en marcha

1. **Habilitar la credencial de Azure Speech**

   La app necesita una *key* de un recurso **Speech** de Azure. Es gratis con el tier
   `F0` (5 horas de audio al mes, suficiente para practicar). Pasos:

   1. **Cuenta de Azure.** Si no tienes, crea una gratis en
      <https://azure.microsoft.com/free/>. Pide tarjeta para verificar identidad, pero
      el tier `F0` de Speech no cobra.
   2. **Crear el recurso Speech.** Entra al [portal de Azure](https://portal.azure.com)
      → *Create a resource* → busca **Speech** → *Create*. Rellena:
      - **Subscription** y **Resource group** (crea uno nuevo si hace falta, ej. `rg-review-ingles`).
      - **Region**: elige la mas cercana a ti para bajar la latencia (ej. `eastus`,
        `brazilsouth`, `westeurope`). **Anota cual elegiste**, va en `AZURE_SPEECH_REGION`.
      - **Name**: cualquiera, ej. `speech-review-ingles`.
      - **Pricing tier**: **Free F0**.
      - *Review + create* → *Create* y espera a que termine el despliegue.
   3. **Copiar la key y la region.** Ve al recurso creado (*Go to resource*) →
      menu lateral **Keys and Endpoint**. Copia:
      - **KEY 1** → sera tu `AZURE_SPEECH_KEY`.
      - **Location/Region** → sera tu `AZURE_SPEECH_REGION` (debe coincidir con la del paso anterior).

   > La key es un **secreto**: no la subas a git ni la compartas. Solo vive en tu `.env`
   > local (que ya esta en `.gitignore`). Si se filtra, regenerala en
   > *Keys and Endpoint → Regenerate Key*. Detalle de todas las variables en
   > [VARIABLES-DE-ENTORNO.md](VARIABLES-DE-ENTORNO.md).

2. **Configurar**

   ```bash
   cp .env.example .env
   ```

   Edita `.env` y pega tu `AZURE_SPEECH_KEY` y tu `AZURE_SPEECH_REGION`.

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

## Practica de lectura (modulo `app/`)

El modulo migrado (`app/`, el que corre con docker-compose) tiene dos modalidades:

- `/` — **conversacion**: el tutor pregunta, tu respondes hablando.
- `/reading` — **lectura en voz alta**: la app te da un texto real, lo lees, y Azure
  evalua tu pronunciacion **contra ese texto**. La pantalla es de dos paneles: a la
  izquierda el texto, a la derecha lo que vas diciendo, que al terminar se convierte en
  el review con las palabras coloreadas y las omisiones tachadas sobre el texto real.

A diferencia del legacy, aca no escribes ni guardas tus propios textos: el catalogo se
puebla solo desde Engoo Daily News con un job periodico. Si `/reading` responde **503**,
es que el catalogo esta vacio; poblalo con:

```bash
python -m app.reading.ingest
```

El servidor tambien corre esa ingesta al arrancar si la tabla esta vacia, y luego cada
`READING_INGEST_INTERVAL_HOURS`.

El texto que se lee es un **extracto** del articulo (`READING_MAX_WORDS`, 120 por
defecto), recortado en limite de oracion. El articulo se guarda completo; el recorte se
calcula al servir y se vuelve a calcular al evaluar, a partir del id del texto. Por eso el
navegador nunca manda el texto de referencia: lo pone el servidor.

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

- **Sin limite de duracion por intento.** Este proyecto usa **reconocimiento continuo**
  (`start_continuous_recognition`), que no tiene el limite de ~30 s del modo
  `recognize_once`. La grabacion dura hasta que pulsas **Parar**. Aun asi conviene
  practicar con parrafos cortos: el tiempo de evaluacion en Azure escala con la
  duracion del audio.
- Servidor pensado para `localhost`: no tiene autenticacion.
