# Cambios pendientes

Ideas discutidas todavia no implementadas, ordenadas por impacto/esfuerzo.

> Nota: estas ideas se escribieron cuando el codigo vivia en la raiz. Sus equivalentes
> actuales estan en `app/`: el frontend en `app/web/static/`, y la logica de Azure en
> `app/speech/` (`azure_client.py` + `assessment.py`).

## Latencia de Azure (mejorar tiempo de respuesta)

La demora **no** viene de la capa gratuita (F0 y S0 tienen la misma latencia por
peticion; F0 solo limita cuota). Las causas reales y sus posibles arreglos:

- [ ] **Region cercana** (fácil, sin código). Cambiar `AZURE_SPEECH_REGION` en `.env`
  por la region de Azure mas proxima (ej. `brazilsouth`, `westeurope`). Requiere que
  el recurso Speech este creado en esa region. Suele ser la mayor mejora si se esta
  lejos de `eastus`.
- [ ] **Streaming mientras se habla** (cambio de arquitectura, alto impacto en la
  sensacion de velocidad). Enviar el audio a Azure en vivo en vez de grabar-y-subir el
  WAV completo. El resultado apareceria casi al instante de parar, porque el analisis
  ocurre mientras se lee. Toca `app/web/static/` (capturar y enviar chunks) y `app/speech/`
  (reconocimiento desde stream en vez de archivo).
- [ ] **Textos mas cortos** (sin código). El tiempo de proceso escala con la duracion
  del audio.
- [ ] **Bajar la prosodia** (fácil, con trade-off). Quitar `enable_prosody_assessment()`
  en `app/speech/azure_client.py` acelera algo, pero se pierde el score de prosodia.
- [ ] **Silencio de cierre** (`Speech_SegmentationSilenceTimeoutMs`, hoy 1500 ms).
  Bajarlo reduce la espera final, pero arriesga cortar en pausas largas legitimas.

## Escuchar pronunciacion (text-to-speech)

- [x] **Web Speech API del navegador** (hecho). Boton 🔊 para el texto completo en
  Practicar y un 🔊 por palabra en "Palabra por palabra". Voz `en-US`, rate 0.9. Sin
  backend, gratis.
- [ ] **Escuchar palabras del Banco de palabras.** Anadir 🔊 a cada palabra de esa
  vista (es donde se repasan las que hay que mejorar).
- [ ] **Mejorar a Azure Neural TTS** (opcional). Voces mas naturales y consistentes,
  con SSML para decirlo mas lento o forzar un fonema. Reusa el mismo recurso Speech
  (misma key/region). Requiere sintetizar en el backend y devolver el audio.

## Vista de textos

- [ ] Mostrar el contenido del texto **con formato** (saltos de linea) en la tabla de la
  pestaña Textos, igual que ya se ve en la vista Practicar (`white-space: pre-wrap`).

## Notas

- El guardado y la visualizacion con formato en Practicar ya estan resueltos
  (`white-space: pre-wrap` en `.reference-text`).
- Azure recibe el texto formateado sin problema: ignora saltos de linea y espacios de
  mas al hacer el match, y usa la puntuacion para evaluar pausas/prosodia. No hay que
  limpiarlo.
