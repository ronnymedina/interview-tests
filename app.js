// Graba el microfono, lo convierte a WAV PCM 16-bit mono y lo manda al servidor
// junto al texto de referencia. Luego pinta los resultados de Azure.
// La grabacion dura hasta que el usuario pulsa "Parar": no hay limite de tiempo.

const TARGET_SAMPLE_RATE = 16000;

const els = {
  reference: document.getElementById("reference"),
  listenText: document.getElementById("listen-text"),
  textSelect: document.getElementById("text-select"),
  noTexts: document.getElementById("no-texts"),
  record: document.getElementById("record"),
  cancel: document.getElementById("cancel"),
  status: document.getElementById("status"),
  error: document.getElementById("error"),
  results: document.getElementById("results"),
  scores: document.getElementById("scores"),
  words: document.getElementById("words"),
  recognized: document.getElementById("recognized"),
  history: document.querySelector("#history tbody"),
  wordBank: document.querySelector("#word-bank tbody"),
  texts: document.querySelector("#texts tbody"),
  textForm: document.getElementById("text-form"),
  textId: document.getElementById("text-id"),
  textTitle: document.getElementById("text-title"),
  textContent: document.getElementById("text-content"),
  textDifficulty: document.getElementById("text-difficulty"),
  textFormError: document.getElementById("text-form-error"),
  newText: document.getElementById("new-text"),
  cancelText: document.getElementById("cancel-text"),
  ttsRate: document.getElementById("tts-rate"),
  ttsRateValue: document.getElementById("tts-rate-value"),
  ttsVoice: document.getElementById("tts-voice"),
  ttsTest: document.getElementById("tts-test"),
  menu: document.querySelector(".menu"),
  views: document.querySelectorAll(".view"),
  filters: document.querySelector(".filters"),
  convSetup: document.getElementById("conv-setup"),
  convPrompt: document.getElementById("conv-prompt"),
  convQuestions: document.getElementById("conv-questions"),
  convStart: document.getElementById("conv-start"),
  convSetupError: document.getElementById("conv-setup-error"),
  convActive: document.getElementById("conv-active"),
  convListen: document.getElementById("conv-listen"),
  convQuestion: document.getElementById("conv-question"),
  convRecord: document.getElementById("conv-record"),
  convStatus: document.getElementById("conv-status"),
  convTurn: document.getElementById("conv-turn"),
  convTurnScores: document.getElementById("conv-turn-scores"),
  convRecognized: document.getElementById("conv-recognized"),
  convError: document.getElementById("conv-error"),
  convFinal: document.getElementById("conv-final"),
  convFinalScores: document.getElementById("conv-final-scores"),
  convFeedback: document.getElementById("conv-feedback"),
  convRestart: document.getElementById("conv-restart"),
};

// Ultimos textos cargados, para poblar el selector de practica y la tabla de gestion.
let textsData = [];

// Ajustes de la voz, persistidos en el navegador para que sobrevivan a las recargas.
const ttsSettings = {
  rate: Number(localStorage.getItem("tts-rate")) || 0.9,
  voiceURI: localStorage.getItem("tts-voice") || "",
};

let state = "idle"; // idle | recording | sending

// A donde va el audio al parar de grabar. Por defecto, la evaluacion de un texto.
// La vista de conversacion lo cambia a su propio manejador.
let recordSink = null;

// Recursos de la grabacion en curso.
let audioContext = null;
let mediaStream = null;
let sourceNode = null;
let processorNode = null;
let chunks = [];

// --- text-to-speech (Web Speech API del navegador) ---------------------------

// Reproduce un texto en ingles con la voz del navegador, usando la velocidad y la voz
// elegidas en Ajustes. No usa Azure: es gratis y sin backend.
function speak(text) {
  const synth = window.speechSynthesis;
  if (!text || !synth) return;
  synth.cancel(); // corta lo que se este diciendo antes de empezar lo nuevo
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.lang = "en-US";
  utterance.rate = ttsSettings.rate;
  const voice = pickVoice();
  if (voice) utterance.voice = voice;
  synth.speak(utterance);
}

// Voces en ingles disponibles en el navegador. Se cargan de forma asincrona: la primera
// llamada puede devolver una lista vacia hasta el evento voiceschanged.
function englishVoices() {
  const synth = window.speechSynthesis;
  if (!synth) return [];
  return synth.getVoices().filter((v) => v.lang.startsWith("en"));
}

// La voz elegida en Ajustes, o la primera en ingles como respaldo.
function pickVoice() {
  const voices = englishVoices();
  return voices.find((v) => v.voiceURI === ttsSettings.voiceURI) || voices[0] || null;
}

// Puebla el selector de voces y marca la guardada. Se reinvoca en voiceschanged.
function populateVoices() {
  const voices = englishVoices();
  els.ttsVoice.innerHTML = "";
  for (const voice of voices) {
    const option = document.createElement("option");
    option.value = voice.voiceURI;
    option.textContent = `${voice.name} (${voice.lang})`;
    els.ttsVoice.appendChild(option);
  }
  const current = pickVoice();
  if (current) els.ttsVoice.value = current.voiceURI;
}

// Aplica los ajustes guardados a los controles de la vista Ajustes.
function initSettings() {
  els.ttsRate.value = ttsSettings.rate;
  els.ttsRateValue.textContent = ttsSettings.rate.toFixed(2).replace(/0$/, "");
  populateVoices();
  if (window.speechSynthesis) {
    window.speechSynthesis.addEventListener("voiceschanged", populateVoices);
  }
}

// --- grabacion ---------------------------------------------------------------

async function startRecording() {
  clearError();
  if (!recordSink && !els.textSelect.value) {
    showError("Elige primero un texto para practicar.");
    return;
  }

  try {
    mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
  } catch (err) {
    showError("No se pudo acceder al microfono: " + err.message);
    return;
  }

  audioContext = new AudioContext({ sampleRate: TARGET_SAMPLE_RATE });
  sourceNode = audioContext.createMediaStreamSource(mediaStream);
  processorNode = audioContext.createScriptProcessor(4096, 1, 1);
  chunks = [];

  processorNode.onaudioprocess = (event) => {
    // Hay que copiar: el buffer que entrega el evento se reutiliza.
    chunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
  };

  sourceNode.connect(processorNode);
  // El nodo solo procesa si esta conectado a la salida. No escribimos en el buffer
  // de salida, asi que no se oye nada por los parlantes.
  processorNode.connect(audioContext.destination);

  setState("recording");
}

function releaseAudio() {
  if (processorNode) {
    processorNode.onaudioprocess = null;
    processorNode.disconnect();
  }
  if (sourceNode) sourceNode.disconnect();
  if (mediaStream) mediaStream.getTracks().forEach((track) => track.stop());
  if (audioContext) audioContext.close();
  processorNode = sourceNode = mediaStream = audioContext = null;
}

function cancelRecording() {
  releaseAudio();
  chunks = [];
  setState("idle");
  els.status.textContent = "Intento cancelado.";
}

async function stopRecording() {
  const sampleRate = audioContext ? audioContext.sampleRate : TARGET_SAMPLE_RATE;
  const recorded = chunks;
  releaseAudio();
  chunks = [];

  if (recorded.length === 0) {
    setState("idle");
    showError("No se grabo audio.");
    return;
  }

  setState("sending");
  try {
    const wavBlob = encodeWav(recorded, sampleRate);
    if (recordSink) await recordSink(wavBlob);
    else await sendForAssessment(wavBlob);
  } finally {
    setState("idle");
  }
}

// --- WAV ---------------------------------------------------------------------

function encodeWav(recorded, sampleRate) {
  const samples = recorded.reduce((total, chunk) => total + chunk.length, 0);
  const buffer = new ArrayBuffer(44 + samples * 2);
  const view = new DataView(buffer);

  writeAscii(view, 0, "RIFF");
  view.setUint32(4, 36 + samples * 2, true); // tamano del archivo - 8
  writeAscii(view, 8, "WAVE");
  writeAscii(view, 12, "fmt ");
  view.setUint32(16, 16, true); // tamano del bloque fmt
  view.setUint16(20, 1, true); // 1 = PCM sin comprimir
  view.setUint16(22, 1, true); // canales: mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); // bytes por segundo
  view.setUint16(32, 2, true); // bytes por muestra
  view.setUint16(34, 16, true); // bits por muestra
  writeAscii(view, 36, "data");
  view.setUint32(40, samples * 2, true);

  let offset = 44;
  for (const chunk of recorded) {
    for (let i = 0; i < chunk.length; i++) {
      const value = Math.max(-1, Math.min(1, chunk[i]));
      view.setInt16(offset, value < 0 ? value * 0x8000 : value * 0x7fff, true);
      offset += 2;
    }
  }

  return new Blob([buffer], { type: "audio/wav" });
}

function writeAscii(view, offset, text) {
  for (let i = 0; i < text.length; i++) {
    view.setUint8(offset + i, text.charCodeAt(i));
  }
}

// --- servidor ----------------------------------------------------------------

async function sendForAssessment(wavBlob) {
  const form = new FormData();
  form.append("audio", wavBlob, "recording.wav");
  form.append("text_id", els.textSelect.value);

  let response;
  try {
    response = await fetch("/assess", { method: "POST", body: form });
  } catch (err) {
    showError("No se pudo contactar al servidor: " + err.message);
    return;
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    showError(formatDetail(body.detail) || `El servidor respondio ${response.status}.`);
    return;
  }

  renderResult(await response.json());
  loadHistory();
  loadWordBank();
  loadTexts();
}

// `detail` es un string en nuestros errores, pero FastAPI devuelve una lista de
// objetos cuando falla la validacion del formulario.
function formatDetail(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((item) => item.msg).join(". ");
  return "";
}

async function loadHistory() {
  const response = await fetch("/history?limit=20");
  if (!response.ok) return;
  const attempts = await response.json();

  els.history.innerHTML = "";
  for (const attempt of attempts) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${new Date(attempt.created_at).toLocaleString()}</td>
      <td class="truncate">${escapeHtml(attempt.reference_text)}</td>
      <td>${formatScore(attempt.pronunciation_score)}</td>
    `;
    els.history.appendChild(row);
  }
}

let wordBankData = []; // ultimas palabras cargadas, para filtrar sin volver a pedirlas
let wordFilter = "all"; // all | poor | fair | good

async function loadWordBank() {
  const response = await fetch("/words?limit=200");
  if (!response.ok) return;
  wordBankData = await response.json();
  renderWordBank();
}

// Categoria de color de una palabra segun su promedio. Las que nunca se pronunciaron
// (promedio null, siempre saltadas) cuentan como "peores".
function wordCategory(stat) {
  if (stat.avg_accuracy === null) return "poor";
  return scoreClass(stat.avg_accuracy);
}

function renderWordBank() {
  els.wordBank.innerHTML = "";
  const visible = wordBankData.filter(
    (stat) => wordFilter === "all" || wordCategory(stat) === wordFilter
  );

  if (visible.length === 0) {
    const row = document.createElement("tr");
    row.innerHTML = `<td colspan="5" class="empty">Sin palabras en esta categoria.</td>`;
    els.wordBank.appendChild(row);
    return;
  }

  for (const stat of visible) {
    const cls = stat.avg_accuracy === null ? "omission" : scoreClass(stat.avg_accuracy);
    const row = document.createElement("tr");
    row.className = "word-row";
    row.innerHTML = `
      <td><span class="word ${cls}">${escapeHtml(stat.word)}</span></td>
      <td>${formatScore(stat.avg_accuracy)}</td>
      <td>${stat.times}</td>
      <td>${stat.failed || ""}</td>
      <td>${stat.skipped || ""}</td>
    `;
    // Fila oculta debajo, con el detalle de cada intento de esa palabra.
    const detailRow = document.createElement("tr");
    detailRow.className = "word-detail hidden";
    detailRow.innerHTML = `<td colspan="5"></td>`;

    let loaded = false;
    row.addEventListener("click", async () => {
      detailRow.classList.toggle("hidden");
      if (!loaded && !detailRow.classList.contains("hidden")) {
        loaded = true;
        detailRow.firstElementChild.appendChild(await wordHistoryDetail(stat.word));
      }
    });

    els.wordBank.append(row, detailRow);
  }
}

// Trae los scores de una palabra intento por intento y los muestra en linea.
async function wordHistoryDetail(word) {
  const box = document.createElement("div");
  box.className = "word-timeline";
  const response = await fetch(`/word-history?word=${encodeURIComponent(word)}`);
  if (!response.ok) {
    box.textContent = "No se pudo cargar el detalle.";
    return box;
  }
  for (const entry of await response.json()) {
    const item = document.createElement("span");
    const skipped = entry.error_type === "Omission";
    item.className = `timeline-item ${skipped ? "omission" : scoreClass(entry.accuracy)}`;
    const date = new Date(entry.created_at).toLocaleDateString();
    item.textContent = skipped ? `${date}: saltada` : `${date}: ${formatScore(entry.accuracy)}`;
    box.appendChild(item);
  }
  return box;
}

// --- render ------------------------------------------------------------------

const SCORE_LABELS = {
  pronunciation: "Pronunciation",
  accuracy: "Accuracy",
  fluency: "Fluency",
  completeness: "Completeness",
  prosody: "Prosody",
};

function renderResult(result) {
  // Azure omite prosody en idiomas que no la soportan; renderScoreCards ya salta
  // los valores null/undefined.
  renderScoreCards(els.scores, result.scores);

  els.words.innerHTML = "";
  for (const word of result.words) {
    els.words.appendChild(renderWord(word));
  }

  els.recognized.textContent = result.recognized_text || "(vacio)";
  els.results.classList.remove("hidden");
}

function renderWord(word) {
  const wrapper = document.createElement("span");
  wrapper.className = "word-wrapper";

  const button = document.createElement("button");
  button.type = "button";
  button.className = `word ${wordClass(word)}`;
  button.textContent = word.word;
  button.title = wordTitle(word);

  // Boton para oir como suena la palabra (voz del navegador).
  const listen = document.createElement("button");
  listen.type = "button";
  listen.className = "speak";
  listen.textContent = "🔊";
  listen.title = "Escuchar";
  listen.addEventListener("click", () => speak(word.word));

  const head = document.createElement("div");
  head.className = "word-head";
  head.append(button, listen);

  // Transcripcion fonetica siempre visible: los sonidos de la palabra en orden,
  // cada uno coloreado por su score. Los sonidos mal pronunciados quedan resaltados,
  // asi se ve "que parte de la palabra fallaste" sin abrir los numeros.
  // Son sonidos (IPA), no letras: el ingles no se escribe como se pronuncia.
  const ipa = document.createElement("div");
  ipa.className = "ipa";
  for (const phoneme of word.phonemes) {
    const sound = document.createElement("span");
    sound.className = `sound ${scoreClass(phoneme.accuracy)}`;
    sound.textContent = phoneme.phoneme;
    sound.title = `${phoneme.phoneme}: ${formatScore(phoneme.accuracy)}`;
    ipa.appendChild(sound);
  }

  // Detalle con el numero exacto de cada sonido, al hacer clic en la palabra.
  const detail = document.createElement("div");
  detail.className = "phonemes hidden";
  if (word.phonemes.length === 0) {
    detail.textContent = "Sin detalle de sonidos.";
  } else {
    for (const phoneme of word.phonemes) {
      const chip = document.createElement("span");
      chip.className = `phoneme ${scoreClass(phoneme.accuracy)}`;
      chip.textContent = `${phoneme.phoneme} ${formatScore(phoneme.accuracy)}`;
      detail.appendChild(chip);
    }
  }

  button.addEventListener("click", () => detail.classList.toggle("hidden"));
  wrapper.append(head, ipa, detail);
  return wrapper;
}

function wordClass(word) {
  if (word.error_type === "Omission") return "omission";
  if (word.error_type === "Insertion") return "insertion";
  return scoreClass(word.accuracy);
}

function wordTitle(word) {
  const messages = {
    Omission: "No la pronunciaste",
    Insertion: "La dijiste pero no esta en el texto",
    Mispronunciation: "Mal pronunciada",
    UnexpectedBreak: "Pausa inesperada antes de esta palabra",
    MissingBreak: "Falto una pausa antes de esta palabra",
    Monotone: "Entonacion plana",
  };
  const note = messages[word.error_type];
  const score = `Accuracy: ${formatScore(word.accuracy)}`;
  return note ? `${score} — ${note}` : score;
}

function scoreClass(score) {
  if (score === null || score === undefined) return "unknown";
  if (score >= 80) return "good";
  if (score >= 60) return "fair";
  return "poor";
}

function formatScore(score) {
  return score === null || score === undefined ? "—" : Math.round(score);
}

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

// --- textos guardados --------------------------------------------------------

async function loadTexts() {
  const response = await fetch("/texts");
  if (!response.ok) return;
  textsData = await response.json();
  renderTextSelect();
  renderTextsTable();
}

// Puebla el selector de la vista Practicar, conservando la seleccion actual si sigue
// existiendo. Si no hay textos, muestra el aviso y deshabilita la practica.
function renderTextSelect() {
  const previous = els.textSelect.value;
  els.noTexts.classList.toggle("hidden", textsData.length > 0);
  els.textSelect.classList.toggle("hidden", textsData.length === 0);

  els.textSelect.innerHTML = "";
  for (const text of textsData) {
    const option = document.createElement("option");
    option.value = text.id;
    option.textContent = text.difficulty
      ? `${text.title} (nivel ${text.difficulty})`
      : text.title;
    els.textSelect.appendChild(option);
  }

  if (textsData.some((text) => String(text.id) === previous)) {
    els.textSelect.value = previous;
  }
  showSelectedContent();
}

// Muestra el contenido del texto elegido para leerlo en voz alta.
function showSelectedContent() {
  const selected = textsData.find((text) => String(text.id) === els.textSelect.value);
  els.reference.textContent = selected ? selected.content : "";
  els.listenText.disabled = !selected;
  if (state === "idle") setState("idle"); // refresca el boton segun haya texto o no
}

function renderTextsTable() {
  els.texts.innerHTML = "";
  if (textsData.length === 0) {
    els.texts.innerHTML = `<tr><td colspan="5" class="empty">Sin textos todavia.</td></tr>`;
    return;
  }
  for (const text of textsData) {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td class="truncate">${escapeHtml(text.title)}</td>
      <td>${text.difficulty || "—"}</td>
      <td>${text.times}</td>
      <td>${formatScore(text.avg_pronunciation)}</td>
    `;
    const actions = document.createElement("td");
    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "secondary small";
    edit.textContent = "Editar";
    edit.addEventListener("click", () => openTextForm(text));
    const del = document.createElement("button");
    del.type = "button";
    del.className = "secondary small";
    del.textContent = "Borrar";
    del.addEventListener("click", () => deleteText(text));
    actions.append(edit, del);
    row.appendChild(actions);
    els.texts.appendChild(row);
  }
}

// Abre el formulario. Con `text` precarga para editar; sin el, en blanco para crear.
function openTextForm(text) {
  els.textFormError.classList.add("hidden");
  els.textId.value = text ? text.id : "";
  els.textTitle.value = text ? text.title : "";
  els.textContent.value = text ? text.content : "";
  els.textDifficulty.value = text && text.difficulty ? text.difficulty : "";
  els.textForm.classList.remove("hidden");
  els.textTitle.focus();
}

function closeTextForm() {
  els.textForm.classList.add("hidden");
  els.textForm.reset();
}

async function saveText(event) {
  event.preventDefault();
  els.textFormError.classList.add("hidden");

  const difficultyRaw = els.textDifficulty.value.trim();
  const body = {
    title: els.textTitle.value.trim(),
    content: els.textContent.value.trim(),
    difficulty: difficultyRaw === "" ? null : Number(difficultyRaw),
  };

  const id = els.textId.value;
  const url = id ? `/texts/${id}` : "/texts";
  const method = id ? "PUT" : "POST";
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    els.textFormError.textContent = formatDetail(detail.detail) || "No se pudo guardar.";
    els.textFormError.classList.remove("hidden");
    return;
  }

  closeTextForm();
  await loadTexts();
}

async function deleteText(text) {
  const message =
    text.times > 0
      ? `Borrar "${text.title}" y sus ${text.times} intento(s) de practica?`
      : `Borrar "${text.title}"?`;
  if (!confirm(message)) return;

  const response = await fetch(`/texts/${text.id}`, { method: "DELETE" });
  if (!response.ok) return;
  await loadTexts();
  loadHistory();
  loadWordBank();
}

// --- estado de la UI ---------------------------------------------------------

function setState(next) {
  state = next;
  els.record.textContent = state === "recording" ? "Parar" : "Hablar";
  els.record.disabled = state === "sending" || !els.textSelect.value;
  els.cancel.disabled = state !== "recording";
  els.textSelect.disabled = state !== "idle";

  if (state === "recording") els.status.textContent = "Grabando... habla ahora.";
  else if (state === "sending") els.status.textContent = "Evaluando con Azure...";
  else if (els.status.textContent !== "Intento cancelado.") els.status.textContent = "";
}

// El pipeline de grabacion (startRecording/stopRecording) es compartido entre la
// practica y la conversacion. `recordSink` ya nos dice a cual de las dos pertenece
// el intento en curso, asi que lo reusamos para enrutar los errores al elemento
// visible correspondiente: practica -> els.error, conversacion -> els.convError.
function showError(message) {
  const target = recordSink ? els.convError : els.error;
  target.textContent = message;
  target.classList.remove("hidden");
}

function clearError() {
  const target = recordSink ? els.convError : els.error;
  target.textContent = "";
  target.classList.add("hidden");
}

// --- conversacion ------------------------------------------------------------

let conversationId = null;

function showConvError(message) {
  els.convError.textContent = message;
  els.convError.classList.remove("hidden");
}

// Pinta un set de scores (mismo formato que la practica) en un contenedor dado.
function renderScoreCards(container, scores) {
  container.innerHTML = "";
  for (const [key, label] of Object.entries(SCORE_LABELS)) {
    const value = scores[key];
    if (value === null || value === undefined) continue;
    const card = document.createElement("div");
    card.className = `card ${scoreClass(value)}`;
    card.innerHTML = `<span class="value">${formatScore(value)}</span><span class="label">${label}</span>`;
    container.appendChild(card);
  }
}

// Muestra una pregunta nueva: la escribe y la habla.
function showQuestion(question) {
  els.convQuestion.textContent = question;
  els.convTurn.classList.add("hidden");
  speak(question);
}

async function startConversation() {
  els.convSetupError.classList.add("hidden");
  const systemPrompt = els.convPrompt.value.trim();
  const maxQuestions = Number(els.convQuestions.value);
  if (!systemPrompt) {
    els.convSetupError.textContent = "Escribe un escenario.";
    els.convSetupError.classList.remove("hidden");
    return;
  }
  if (!Number.isInteger(maxQuestions) || maxQuestions < 1 || maxQuestions > 20) {
    els.convSetupError.textContent = "El numero de preguntas debe ser un entero entre 1 y 20.";
    els.convSetupError.classList.remove("hidden");
    return;
  }

  els.convStart.disabled = true;
  let response;
  try {
    response = await fetch("/conversation/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ system_prompt: systemPrompt, max_questions: maxQuestions }),
    });
  } catch (err) {
    els.convStart.disabled = false;
    els.convSetupError.textContent = "No se pudo contactar al servidor: " + err.message;
    els.convSetupError.classList.remove("hidden");
    return;
  }
  els.convStart.disabled = false;

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    els.convSetupError.textContent =
      formatDetail(body.detail) || `El servidor respondio ${response.status}.`;
    els.convSetupError.classList.remove("hidden");
    return;
  }

  const data = await response.json();
  conversationId = data.conversation_id;
  els.convSetup.classList.add("hidden");
  els.convFinal.classList.add("hidden");
  els.convActive.classList.remove("hidden");
  showQuestion(data.question);
}

// Sink de grabacion para la conversacion: manda el audio de la respuesta al servidor.
async function sendConversationAnswer(wavBlob) {
  els.convError.classList.add("hidden");
  const form = new FormData();
  form.append("audio", wavBlob, "answer.wav");

  let response;
  try {
    response = await fetch(`/conversation/${conversationId}/answer`, {
      method: "POST",
      body: form,
    });
  } catch (err) {
    showConvError("No se pudo contactar al servidor: " + err.message);
    els.convStatus.textContent = "";
    return;
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    showConvError(formatDetail(body.detail) || `El servidor respondio ${response.status}.`);
    els.convStatus.textContent = "";
    return;
  }

  const data = await response.json();
  renderScoreCards(els.convTurnScores, data.turn_scores);
  els.convRecognized.textContent = data.recognized_text || "(vacio)";
  els.convTurn.classList.remove("hidden");

  if (data.final) {
    renderScoreCards(els.convFinalScores, data.final.scores);
    els.convFeedback.textContent = data.final.content_feedback;
    els.convActive.classList.add("hidden");
    els.convFinal.classList.remove("hidden");
    conversationId = null;
    els.convStatus.textContent = "";
    loadWordBank();
  } else {
    showQuestion(data.next_question);
    els.convStatus.textContent = "";
  }
}

// Al entrar/salir de la vista conversacion, se conecta/desconecta el sink de grabacion y
// se reusan los botones de grabar. La vista tiene su propio boton, que delega en el flujo
// comun de grabacion apuntando al sink de conversacion.
els.convStart.addEventListener("click", startConversation);
els.convListen.addEventListener("click", () => speak(els.convQuestion.textContent));
els.convRecord.addEventListener("click", async () => {
  if (state === "idle") {
    recordSink = sendConversationAnswer;
    await startRecording();
    if (state === "recording") {
      els.convRecord.textContent = "Parar";
      els.convStatus.textContent = "Grabando... responde ahora.";
    } else {
      // startRecording no arranco (permiso denegado, sin audio, etc.). El error ya
      // quedo visible en convError via el enrutado de showError; solo falta que el
      // boton y el estado no mientan sobre que se esta grabando.
      els.convRecord.textContent = "Responder";
      els.convStatus.textContent = "";
      recordSink = null;
    }
  } else if (state === "recording") {
    els.convRecord.textContent = "Responder";
    // stopRecording() corre de forma sincrona hasta su primer await, asi que para
    // cuando esta linea se ejecuta `state` ya refleja si el envio arranco
    // ("sending") o si no hubo audio y se aborto ("idle" + error en convError).
    const pending = stopRecording();
    els.convStatus.textContent = state === "sending" ? "Evaluando..." : "";
    await pending;
  }
});
els.convRestart.addEventListener("click", () => {
  els.convFinal.classList.add("hidden");
  els.convSetup.classList.remove("hidden");
});

// --- arranque ----------------------------------------------------------------

els.record.addEventListener("click", () => {
  if (state === "idle") startRecording();
  else if (state === "recording") stopRecording();
});
els.cancel.addEventListener("click", cancelRecording);

// Muestra una vista por su nombre y marca su boton en el menu.
function switchView(name) {
  els.menu.querySelectorAll("button").forEach((b) => {
    b.classList.toggle("active", b.dataset.view === name);
  });
  els.views.forEach((view) => {
    view.classList.toggle("hidden", view.id !== `view-${name}`);
  });

  // Cambiar de pestana a mitad de una grabacion la cancela: si no, el audio
  // quedaria apuntando al sink equivocado (p.ej. conversacion grabando y luego
  // "Parar" en practica mandaria ese audio a /assess). Solo una grabacion activa
  // se cancela aqui: un envio en curso ("sending") se deja terminar solo, para que
  // su `finally { setState("idle") }` no le pise el estado a una grabacion nueva
  // que el usuario arranque mientras tanto.
  if (state === "recording") {
    cancelRecording();
    els.status.textContent = "";
    els.convRecord.textContent = "Responder";
    els.convStatus.textContent = "";
  }

  // Fuera de la conversacion, la grabacion vuelve a su destino por defecto.
  if (name !== "conversation") recordSink = null;
}

// Menu: muestra la vista elegida y oculta las demas.
els.menu.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-view]");
  if (button) switchView(button.dataset.view);
});

// Enlace del aviso "no tienes textos" que lleva a la pestana Textos.
els.noTexts.addEventListener("click", (event) => {
  if (event.target.closest("button[data-goto]")) switchView("texts");
});

// Selector de texto en la vista Practicar.
els.textSelect.addEventListener("change", showSelectedContent);

// Escuchar el texto completo con la voz del navegador.
els.listenText.addEventListener("click", () => speak(els.reference.textContent));

// Ajustes de la voz: velocidad y voz, persistidos en localStorage.
els.ttsRate.addEventListener("input", () => {
  ttsSettings.rate = Number(els.ttsRate.value);
  els.ttsRateValue.textContent = ttsSettings.rate.toFixed(2).replace(/0$/, "");
  localStorage.setItem("tts-rate", String(ttsSettings.rate));
});
els.ttsVoice.addEventListener("change", () => {
  ttsSettings.voiceURI = els.ttsVoice.value;
  localStorage.setItem("tts-voice", ttsSettings.voiceURI);
  // Reproduce una muestra al vuelo para oir la voz recien elegida.
  speak("The quick brown fox jumps over the lazy dog.");
});
els.ttsTest.addEventListener("click", () =>
  speak("The quick brown fox jumps over the lazy dog.")
);

// Formulario de textos.
els.newText.addEventListener("click", () => openTextForm(null));
els.cancelText.addEventListener("click", closeTextForm);
els.textForm.addEventListener("submit", saveText);

// Filtros del banco de palabras por color.
els.filters.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-filter]");
  if (!button) return;
  els.filters.querySelectorAll("button").forEach((b) => b.classList.remove("active"));
  button.classList.add("active");
  wordFilter = button.dataset.filter;
  renderWordBank();
});

initSettings();
loadTexts();
loadHistory();
loadWordBank();
