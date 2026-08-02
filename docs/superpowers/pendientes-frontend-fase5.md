# Pendientes del frontend (piloto)

Registrados el 2026-08-02, tras completar la Fase 5. **Resueltos el 2026-08-02** adoptando un rediseño **estilo Apple** (paleta gris `#f5f5f7`, acento azul `#0071e3`, tipografía SF, tarjetas blancas con sombra suave). Archivo: `app/web/index.html`.

## 1. El óvalo tutor: forma y color — ✅ HECHO

- **Forma:** ahora es un **círculo perfecto 150×150** (antes 132×168 "huevo").
- **Color:** se eliminó el dorado. El orbe es un gradiente **violeta→rosa tipo Siri** (opción "D · Atardecer"): `radial-gradient(circle at 38% 32%, #d9a8ff, #9a6bff 55%, #ff7eb3)` con glow morado. Estado *hablando* con halo morado; *grabando* con anillo verde.
- El acento dorado global se reemplazó por el azul Apple en botones, bordes, focus y progreso (tokens `--gold`/`--gold-deep`/`--gold-soft` conservan el nombre pero ahora valen azul/gris; se dejó así para no tocar cada uso).

## 2. Paleta de fondo (crema/blanco) — ✅ HECHO

- Adoptada la paleta Apple: fondo **`#f5f5f7`** (gris claro, "más claro pero no tan blanco"), tarjetas **`#ffffff`**, tinta **`#1d1d1f`**, muted **`#6e6e73`**.
- La referencia "estilo wrapo" ya no fue necesaria; si más adelante se trae otra, basta ajustar los tokens `--cream`/`--ivory` en `:root`.

## 3. Render de Markdown en la pantalla final — ✅ HECHO

- `showFinal` ahora usa `$("feedback").innerHTML = renderMarkdown(...)`.
- `renderMarkdown` es un parser ligero **sin dependencias**: soporta headings `#/##/###`, listas `-`/`*` y numeradas, **negritas**, *cursivas* y `código` inline. **Escapa el HTML** de entrada (seguro contra inyección).
- CSS `.prose` reestilado (headings SF, listas, código); se quitó `white-space: pre-wrap`.

## 4. Palabras clicables con señal de que se pueden escuchar — ✅ HECHO

- Cada pill ahora muestra un **ícono de altavoz 🔊** en un círculo azul, con `title="Toca para escuchar"`, `aria-label` accesible, `cursor: pointer` y **cambio de color/borde al hover**.
- Archivo: `renderWords` + CSS `.pill`/`.pill .spk`.

## 5. Indicador "Pregunta X de N" — ✅ HECHO

- El backend ahora devuelve `question_number` y `total_questions` en `/conversation/start` y en cada turno no-final de `/conversation/answer` (salen del estado del grafo: `questions_asked` / `max_questions`).
- Archivos: `app/conversation/service.py` (`start` devuelve 4-tupla; `answer` agrega los campos), `app/cmd/server.py` (`/start`), `app/web/index.html` (`#q-progress`, `setQuestion(text, meta)`).
- Test actualizado: `test_app_server_start.py`.

## 6. Indicador de carga del feedback — ✅ HECHO

- Al responder, mientras se espera a `/conversation/answer` (Gemini + Azure), se muestra un spinner + mensaje ("Analizando tu respuesta…" o **"Preparando tu feedback…"** si era la última pregunta), el orbe pasa a estado *thinking* y el botón se bloquea con "Procesando…". Al terminar se restaura.
- Archivo: `app/web/index.html` (`#talk-loading`, `.spinner`, `.oval.thinking`, `showTalkLoading`/`hideTalkLoading`, `sendAnswer`).

## 7. Pronunciación palabra por palabra (datos de Azure) — ✅ HECHO

- La pantalla final ahora muestra una sección **"Tu pronunciación, palabra por palabra"** que aprovecha `final.pronunciation.words[]` (que ya llegaba y se descartaba): cada palabra coloreada por su `accuracy` (verde/ámbar/rojo), los sonidos (IPA) visibles y coloreados, 🔊 para escucharla y clic para expandir el score de cada fonema. Es el mismo comportamiento del frontend legacy (`app.js` `renderWord`), portado al estilo Apple.
- **Solo frontend, cero costo extra de Azure** (el dato ya viajaba). Colores semánticos nuevos: `--ok`/`--warn`/`--bad` (independientes del acento azul).
- Archivo: `app/web/index.html` (`#pron-block`, `renderPronunciation`/`renderWord` + helpers `scoreClass`/`wordClass`/`wordTitle`, CSS `.pron-words`/`.word`/`.ipa`/`.phoneme`).
- Nota: en modo *unscripted* Azure no da `Omission`/`Insertion` (necesitan referencia); el coloreo se basa en `accuracy` y `Mispronunciation`.

---

**Verificación:** frontend validado con `node --check` y lógica de coloreo probada con datos de ejemplo; backend con la suite completa (**127 tests pasan**, incluido el ajuste de `start`). Falta la **verificación visual en navegador** (la extensión de Chrome no estaba conectada).

---

## Opciones adicionales de la API de Azure (investigado 2026-08-02)

Referencia: [Microsoft Learn — Pronunciation Assessment](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/how-to-pronunciation-assessment) (doc rev. 2025-11-21).

**Hoy usamos** modo *unscripted* (sin texto de referencia), granularidad `Phoneme`, prosodia activada, IPA. Exponemos al frontend 4 scores globales (pronunciation, accuracy, fluency, prosody) — pero el backend **ya envía y el frontend descarta** `words[]` con `accuracy`, `error_type` y `phonemes[]` por palabra.

**Quick wins (dato ya disponible, solo frontend):**
- Resaltar en el reconocimiento las palabras con `accuracy` baja / `error_type = Mispronunciation` (Azure marca <60), con score objetivo por palabra.
- Complementar las `practice_words` de Gemini con el score real de Azure por palabra.

**Requieren leer más del JSON que ya pedimos (cambio chico en `azure_client`):**
- **NBestPhonemes**: por fonema, los 5 candidatos que Azure "oyó" con score → decirle "dijiste /ə/ donde iba /ɛ/". Alto valor didáctico. Hay que fijar `NBestPhonemeCount` y leerlo (hoy `word_to_dict` solo toma phoneme+accuracy).
- **Feedback de prosodia por palabra**: `UnexpectedBreak`/`MissingBreak` (con `Confidence`, umbral sugerido 0.75) y `Monotone` → explicar el número de prosodia ("pausa rara aquí", "entonación monótona"). Solo `en-US` (ya lo usamos).
- **Sílabas** (`Syllable`, solo `en-US`): granularidad intermedia, más fácil de mostrar que fonemas IPA sueltos.

**Grandes (arquitectura/costo):**
- Pasada híbrida *scripted*: Azure STT → usar el texto reconocido como referencia → correr assessment con referencia para obtener **CompletenessScore** y miscue (Omission/Insertion) y accuracy más precisa. Duplica llamadas/costo de Azure; probablemente no vale para el piloto.

**No hace falta:**
- **Content assessment (vocabulary/grammar/topic)** de Azure está **retirado** (SDK ≥ 1.46). Microsoft recomienda un LLM — ya lo cubrimos con el feedback y las `phrases` de Gemini.
