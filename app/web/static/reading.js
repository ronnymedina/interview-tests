"use strict";
// Pantalla de lectura en voz alta: dos paneles y tres estados (listo → hablando → review).
// Lo compartido con la conversación (grabación, API, identidad, pintado de palabras) vive en
// shared.js; acá sólo está lo propio de esta modalidad.

let current = null; // el texto que se está leyendo, tal como lo devolvió /reading/random
let active = null; // grabador en curso, o null si no se está grabando

function showError(message) {
  const el = $("reading-error");
  el.textContent = message;
  el.classList.remove("hidden");
}

function clearError() {
  $("reading-error").classList.add("hidden");
}

// ---- Estado 1: listo ----
async function loadText() {
  clearError();
  $("btn-record").disabled = true;
  $("btn-record").textContent = "Empezar a leer";
  $("reading-text").textContent = "Cargando un texto…";
  $("reading-said").innerHTML = "";
  $("reading-said").classList.remove("pron-words");
  $("reading-scores").classList.add("hidden");
  $("right-title").textContent = "Lo que estás diciendo";

  try {
    current = await Api.request("GET", "/reading/random");
  } catch (err) {
    if (err.reason) return showBanner(err.reason);
    $("reading-text").textContent = "";
    return showError(err.message);
  }

  $("reading-text").textContent = current.excerpt;
  $("reading-title").textContent = current.title;

  const level = $("reading-level");
  if (current.level === null || current.level === undefined) {
    level.classList.add("hidden");
  } else {
    level.textContent = `Nivel ${current.level}`;
    level.classList.remove("hidden");
  }

  const source = $("reading-source");
  source.href = current.source_url;
  source.classList.remove("hidden");

  $("btn-record").disabled = false;
}

// ---- Estado 2: hablando ----
// El tope de grabación sale del tamaño del texto: ~2,5 palabras por segundo leyendo en voz
// alta, con el doble de margen para quien lea despacio, y un piso de 60 s.
function maxSecondsFor(wordCount) {
  return Math.max(60, Math.ceil((wordCount / 2.5) * 2));
}

function newRecorder() {
  return createRecorder({
    maxSeconds: maxSecondsFor(current.word_count),
    lang: "en-US",
    onTranscript: (text) => {
      $("reading-said").textContent = text;
    },
    onTick: (secondsLeft) => {
      $("reading-timer").textContent = secondsLeft === null ? "" : `${secondsLeft}s`;
    },
    onStart: () => {
      $("btn-record").textContent = "Terminé";
      $("btn-another").disabled = true;
    },
    onStop: () => {
      $("btn-record").textContent = "Evaluando…";
      $("btn-record").disabled = true;
      // El grabador puede pararse solo al agotarse el tiempo, no sólo por el botón.
      active = null;
    },
  });
}

async function toggleRecording() {
  if (active) {
    const recorder = active;
    active = null;
    await recorder.stop();
    return;
  }
  clearError();
  $("reading-said").textContent = "";
  active = newRecorder();
  await active.start(sendForReview);
}

// ---- Estado 3: review ----
async function sendForReview(wavBlob) {
  const form = new FormData();
  form.append("reading_id", String(current.reading_id));
  form.append("audio", wavBlob, "reading.wav");

  let result;
  try {
    result = await Api.request("POST", "/reading/assess", { form });
  } catch (err) {
    if (err.reason) return showBanner(err.reason);
    resetRecordButton();
    return showError(err.message);
  }

  renderReview(result);
  resetRecordButton();
}

function resetRecordButton() {
  $("btn-record").textContent = "Leer de nuevo";
  $("btn-record").disabled = false;
  $("btn-another").disabled = false;
  $("reading-timer").textContent = "";
}

function renderReview(result) {
  $("right-title").textContent = "Tu lectura, palabra por palabra";

  // Derecha: cada palabra coloreada por accuracy, con sus fonemas (lógica de shared.js).
  const said = $("reading-said");
  said.innerHTML = "";
  said.classList.add("pron-words");
  (result.words || []).forEach((word) => said.appendChild(renderWord(word, () => {})));

  // Izquierda: el texto real, con las palabras omitidas tachadas. Se pinta sobre el texto de
  // referencia que devolvió el servidor, no sobre la copia que tenga el navegador.
  const omitted = new Set(
    (result.words || [])
      .filter((word) => word.error_type === "Omission")
      .map((word) => word.word.toLowerCase())
  );
  const left = $("reading-text");
  left.innerHTML = "";
  (result.reference_text || current.excerpt).split(/\s+/).forEach((token) => {
    const bare = token.toLowerCase().replace(/[^a-z']/g, "");
    const span = document.createElement("span");
    span.textContent = token + " ";
    if (omitted.has(bare)) span.className = "omitted";
    left.appendChild(span);
  });

  // Arriba: los scores. `completeness` sólo existe en modo scripted, que es el de lectura.
  const scores = result.scores || {};
  const box = $("reading-scores");
  box.innerHTML = "";
  [
    ["Pronunciación", scores.pronunciation],
    ["Precisión", scores.accuracy],
    ["Fluidez", scores.fluency],
    ["Completitud", scores.completeness],
    ["Prosodia", scores.prosody],
  ].forEach(([label, value]) => {
    const el = document.createElement("div");
    el.className = `score ${scoreClass(value)}`;
    const number = document.createElement("b");
    number.textContent = formatScore(value);
    const caption = document.createElement("small");
    caption.textContent = label;
    el.append(number, caption);
    box.appendChild(el);
  });
  box.classList.remove("hidden");
}

$("btn-record").addEventListener("click", toggleRecording);
$("btn-another").addEventListener("click", loadText);
loadText();
