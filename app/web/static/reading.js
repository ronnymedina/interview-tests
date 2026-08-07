"use strict";
// Pantalla de lectura en voz alta: dos paneles y tres estados (listo → hablando → review).
// Lo compartido con la conversación (grabación, API, identidad, pintado de palabras) vive en
// shared.js; acá sólo está lo propio de esta modalidad.

let current = null; // el texto que se está leyendo, tal como lo devolvió /reading/random
let active = null; // grabador en curso, o null si no se está grabando

// Seguimiento de la lectura (ver "Seguimiento de la lectura" más abajo).
let paragraphs = []; // los párrafos del texto: su <p> y el conjunto de palabras que contiene
let currentPara = 0; // en cuál está leyendo el usuario

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
  stopListening();
  $("btn-record").disabled = true;
  $("btn-listen").disabled = true;
  $("btn-record").textContent = "Empezar a leer";
  $("reading-text").textContent = "Cargando un texto…";
  showSaidPlaceholder("Tu lectura aparecerá acá.\nPulsá «Empezar a leer» cuando estés listo.");
  $("reading-scores").classList.add("hidden");
  $("right-title").textContent = "Lo que estás diciendo";

  try {
    current = await Api.request("GET", `/reading/random?max_level=${Prefs.maxLevel()}`);
  } catch (err) {
    if (err.reason) return showBanner(err.reason);
    $("reading-text").textContent = "";
    $("reading-title").textContent = "Sin texto";
    return showError(err.message);
  }

  renderExcerpt(current.excerpt);
  $("reading-title").textContent = current.title;

  const level = $("reading-level");
  if (current.level === null || current.level === undefined) {
    level.classList.add("hidden");
  } else {
    level.textContent = `Nivel ${current.level}`;
    level.classList.remove("hidden");
  }

  // El título es el enlace: no hay un "Artículo original" suelto que mostrar u ocultar.
  $("reading-source").href = current.source_url;

  $("btn-record").disabled = false;
  $("btn-listen").disabled = false;
}

// Un <p> por párrafo: el extracto conserva los saltos del artículo original, y el HTML los
// colapsaría a un espacio si se pintara como texto plano. De paso se guarda el vocabulario
// de cada párrafo, que es con lo que después se ubica al lector.
function renderExcerpt(text) {
  const box = $("reading-text");
  box.innerHTML = "";
  paragraphs = [];
  for (const paragraph of text.split(/\n\s*\n/)) {
    if (!paragraph.trim()) continue;
    const p = document.createElement("p");
    p.textContent = paragraph.trim();
    box.appendChild(p);
    paragraphs.push({ el: p, words: new Set(bareWords(paragraph)) });
  }
  resetProgress();
}

// Placeholder del panel derecho: sin esto es un rectángulo blanco enorme y mudo.
function showSaidPlaceholder(message) {
  const said = $("reading-said");
  said.classList.remove("pron-words");
  said.innerHTML = "";
  const box = document.createElement("div");
  box.className = "empty-state";
  const icon = document.createElement("span");
  icon.className = "ico";
  icon.textContent = "🎙";
  const text = document.createElement("div");
  text.style.whiteSpace = "pre-line";
  text.textContent = message;
  box.append(icon, text);
  said.appendChild(box);
}

// ---- Seguimiento de la lectura ----
// El panel izquierdo no copia el scroll del derecho: se alinea con lo que el usuario lleva
// dicho, para que no haya que scrollear a mano mientras se lee en voz alta.

function bareWords(text) {
  return text
    .toLowerCase()
    .split(/\s+/)
    .map((token) => token.replace(/[^a-z']/g, ""))
    .filter(Boolean);
}

// Deja el texto limpio. El resaltado no aparece hasta que se empieza a grabar: en reposo no
// hay ningún lector al que ubicar.
function resetProgress() {
  paragraphs.forEach((para) => para.el.classList.remove("para-read", "para-at"));
  currentPara = 0;
  $("reading-text").scrollTop = 0;
}

// Se mira sólo la cola de lo dicho: lo de hace veinte palabras no dice nada sobre dónde está
// el lector ahora.
const TAIL = 7;

// Ubicar al lector por párrafo y no palabra por palabra. Seguir cada palabra era frágil: una
// palabra corriente ("the", "to") aparece más adelante en el texto y arrastraba el marcador
// varias líneas, o incluso otro párrafo. Acá el marcador sólo puede quedarse donde está o
// pasar al párrafo siguiente —nunca saltar dos, nunca volver atrás—, y sólo lo hace cuando la
// cola de lo dicho coincide más con el párrafo que viene que con el actual.
function followTranscript(transcript) {
  if (!paragraphs.length) return;
  const tail = bareWords(transcript).slice(-TAIL);
  if (!tail.length) return;
  if (overlap(tail, currentPara + 1) > overlap(tail, currentPara)) {
    currentPara += 1;
    markParagraph();
    scrollToParagraph();
  }
}

// Cuántas de las últimas palabras dichas pertenecen a ese párrafo. -1 si no existe, para que
// el final del texto no intente avanzar.
function overlap(tail, index) {
  const para = paragraphs[index];
  if (!para) return -1;
  return tail.filter((word) => para.words.has(word)).length;
}

// Un solo color, que se va mudando de párrafo. Lo ya leído queda apagado.
function markParagraph() {
  paragraphs.forEach((para, index) => {
    para.el.classList.toggle("para-read", index < currentPara);
    para.el.classList.toggle("para-at", index === currentPara);
  });
}

// El párrafo en curso se deja a un tercio de la altura del panel: pegado al borde inferior no
// se vería lo que viene, que es justo lo que hay que leer a continuación.
function scrollToParagraph() {
  const box = $("reading-text");
  const para = paragraphs[currentPara];
  if (para) box.scrollTop = Math.max(0, para.el.offsetTop - box.clientHeight / 3);
}

// ---- Escuchar el texto ----
// El mismo botón alterna entre leer y cortar, así siempre hay salida: nunca queda una voz
// sonando sin forma de pararla.
let listening = false;

// Sólo el icono: el altavoz ya dice lo que hace, y el título del artículo necesita la línea
// entera para él. El texto sigue existiendo para lectores de pantalla en aria-label.
function setListenButton(icon, label) {
  const button = $("btn-listen");
  button.textContent = icon;
  button.title = label;
  button.setAttribute("aria-label", label);
}

function stopListening() {
  Tts.stop();
  listening = false;
  setListenButton("🔊", "Escuchar el texto");
}

function toggleListen() {
  if (listening) return stopListening();
  listening = true;
  setListenButton("⏹", "Detener la lectura");
  Tts.speak(current.excerpt, { onend: stopListening });
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
      const said = $("reading-said");
      said.textContent = text;
      said.scrollTop = said.scrollHeight; // lo último dicho siempre a la vista
      followTranscript(text);
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
  stopListening(); // el micrófono se abre: la voz del tutor se calla
  showSaidPlaceholder("Escuchando…\nEmpezá a leer el texto en voz alta.");
  resetProgress();
  markParagraph(); // se resalta el primer párrafo: ahí empieza la lectura
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
  (result.words || []).forEach((word) =>
    said.appendChild(renderWord(word, (t) => Tts.speak(t)))
  );

  // Izquierda: el texto real, con las palabras omitidas tachadas. Se pinta sobre el texto de
  // referencia que devolvió el servidor, no sobre la copia que tenga el navegador.
  const omitted = new Set(
    (result.words || [])
      .filter((word) => word.error_type === "Omission")
      .map((word) => word.word.toLowerCase())
  );
  // El panel izquierdo se repinta desde cero: los <p> que seguía el dictado dejan de existir,
  // así que el seguimiento se descarta hasta la próxima grabación.
  paragraphs = [];
  currentPara = 0;
  const left = $("reading-text");
  left.innerHTML = "";
  left.scrollTop = 0;
  for (const paragraph of (result.reference_text || current.excerpt).split(/\n\s*\n/)) {
    if (!paragraph.trim()) continue;
    const p = document.createElement("p");
    for (const token of paragraph.trim().split(/\s+/)) {
      const bare = token.toLowerCase().replace(/[^a-z']/g, "");
      const span = document.createElement("span");
      span.textContent = token + " ";
      if (omitted.has(bare)) span.className = "omitted";
      p.appendChild(span);
    }
    left.appendChild(p);
  }

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
$("btn-listen").addEventListener("click", toggleListen);
$("max-level").addEventListener("change", () => {
  Prefs.setMaxLevel($("max-level").value);
  loadText(); // el texto actual puede estar por encima del nuevo tope
});

Tts.load();
speechSynthesis.onvoiceschanged = () => Tts.load();
$("max-level").value = String(Prefs.maxLevel());
loadText();
