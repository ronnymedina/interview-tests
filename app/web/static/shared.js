"use strict";
// Utilidades compartidas por todas las modalidades (conversación, lectura, …).
// Regla: acá NO se referencian ids del DOM propios de una página. Todo lo que necesite
// tocar la UI de una modalidad entra por callback, así este archivo sirve a cualquiera.

const $ = (id) => document.getElementById(id);

// ---- Identidad: un UUID por navegador, en localStorage ----
const Identity = {
  get() {
    let id = localStorage.getItem("pilot_user_id");
    if (!id) {
      id = crypto.randomUUID();
      localStorage.setItem("pilot_user_id", id);
    }
    return id;
  },
};

class ApiError extends Error {
  constructor(status, reason, message) {
    super(message);
    this.status = status;
    this.reason = reason; // 'paused' | 'quota' | null
  }
}

// ---- Cliente API: agrega X-User-Id; normaliza errores (incl. 429 con reason) ----
const Api = {
  async request(method, path, { json, form } = {}) {
    const headers = { "X-User-Id": Identity.get() };
    let body;
    if (json !== undefined) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(json);
    } else if (form !== undefined) {
      body = form; // FormData: el navegador pone el multipart boundary
    }
    const res = await fetch(path, { method, headers, body });
    if (!res.ok) {
      let detail = res.statusText;
      let reason = null;
      try {
        const data = await res.json();
        if (data && typeof data.detail === "object" && data.detail) {
          reason = data.detail.reason || null;
          detail = reason || res.statusText;
        } else if (data && data.detail) {
          detail = data.detail;
        }
      } catch (_) {}
      throw new ApiError(res.status, reason, typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return res.status === 204 ? null : res.json();
  },
};

// ---- Grabación: WAV PCM 16-bit mono vía AudioContext, en paralelo al reconocimiento ----
function floatTo16BitPCM(view, offset, input) {
  for (let i = 0; i < input.length; i++, offset += 2) {
    const s = Math.max(-1, Math.min(1, input[i]));
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
}
function encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeStr = (off, str) => { for (let i = 0; i < str.length; i++) view.setUint8(off + i, str.charCodeAt(i)); };
  writeStr(0, "RIFF"); view.setUint32(4, 36 + samples.length * 2, true); writeStr(8, "WAVE");
  writeStr(12, "fmt "); view.setUint32(16, 16, true); view.setUint16(20, 1, true);
  view.setUint16(22, 1, true); view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true); view.setUint16(32, 2, true); view.setUint16(34, 16, true);
  writeStr(36, "data"); view.setUint32(40, samples.length * 2, true);
  floatTo16BitPCM(view, 44, samples);
  return new Blob([view], { type: "audio/wav" });
}

// ---- Grabación: WAV PCM 16-bit mono vía AudioContext, en paralelo al reconocimiento ----
// Es una fábrica y no un singleton porque cada página decide su duración máxima, su idioma
// y qué hacer con el nivel de voz, el parcial reconocido y el segundero. Sin callbacks no
// toca el DOM: así la misma grabación sirve a la conversación y a la lectura.
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;

function createRecorder({
  maxSeconds = 30,
  lang = "en-US",
  onLevel = () => {},
  onTranscript = () => {},
  onTick = () => {},
  onStart = () => {},
  onStop = () => {},
} = {}) {
  return {
    audioCtx: null, source: null, processor: null, stream: null,
    chunks: [], sampleRate: 16000, recognition: null, transcript: "",
    timerId: null, secondsLeft: maxSeconds, onDone: null,
    _stopping: false, _recording: false,

    async start(onDone) {
      this._stopping = false;
      this.onDone = onDone; this.chunks = []; this.transcript = "";
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      this.sampleRate = this.audioCtx.sampleRate;
      this.source = this.audioCtx.createMediaStreamSource(this.stream);
      this.processor = this.audioCtx.createScriptProcessor(4096, 1, 1);
      this.processor.onaudioprocess = (e) => {
        const data = e.inputBuffer.getChannelData(0);
        this.chunks.push(new Float32Array(data));
        // Nivel de voz (RMS) del buffer, para que la página anime lo que quiera.
        let sum = 0;
        for (let i = 0; i < data.length; i++) sum += data[i] * data[i];
        onLevel(Math.sqrt(sum / data.length));
      };
      this.source.connect(this.processor);
      this.processor.connect(this.audioCtx.destination);
      this._startRecognition();
      this._startTimer();
      onStart();
    },

    _startRecognition() {
      if (!SR) return; // sin reconocimiento se envía audio con transcript vacío -> el backend valida
      const rec = new SR();
      rec.lang = lang; rec.continuous = true; rec.interimResults = true;
      let acc = "";
      rec.onresult = (e) => {
        let interim = "";
        for (let i = e.resultIndex; i < e.results.length; i++) {
          const t = e.results[i][0].transcript;
          if (e.results[i].isFinal) acc += t + " "; else interim += t;
        }
        this.transcript = acc.trim();
        onTranscript((acc + interim).trim());
      };
      rec.onend = () => { if (this._recording) { try { rec.start(); } catch (_) {} } };
      rec.onerror = () => {};
      this.recognition = rec; this._recording = true;
      try { rec.start(); } catch (_) {}
    },

    _startTimer() {
      this.secondsLeft = maxSeconds;
      onTick(this.secondsLeft);
      this.timerId = setInterval(() => {
        this.secondsLeft -= 1;
        onTick(this.secondsLeft);
        if (this.secondsLeft <= 0) this.stop();
      }, 1000);
    },

    async stop() {
      if (this._stopping || !this.audioCtx) return;
      this._stopping = true;
      clearInterval(this.timerId); this.timerId = null;
      this._recording = false;
      onTick(null); // null = se terminó, la página limpia su contador
      try { this.recognition && this.recognition.stop(); } catch (_) {}
      this.processor.disconnect(); this.source.disconnect();
      this.stream.getTracks().forEach((t) => t.stop());
      // Aplanar chunks a un solo Float32Array.
      const len = this.chunks.reduce((n, c) => n + c.length, 0);
      const samples = new Float32Array(len);
      let off = 0; for (const c of this.chunks) { samples.set(c, off); off += c.length; }
      await this.audioCtx.close(); this.audioCtx = null;
      const wav = encodeWav(samples, this.sampleRate);
      onStop();
      this.onDone && this.onDone(wav, this.transcript);
    },
  };
}


// ---- Banner de pausa / cuota (los ids viven en base.html: sirven a cualquier página) ----
function showBanner(reason) {
  $("app").classList.add("hidden");
  $("banner").classList.remove("hidden");
  if (reason === "quota") {
    $("banner-title").textContent = "Llegaste al límite de la demo";
    $("banner-text").textContent = "Ya usaste tus conversaciones de práctica. ¡Gracias por probarla!";
  } else if (reason === "rate_limited") {
    $("banner-title").textContent = "Demasiados intentos seguidos";
    $("banner-text").textContent = "Vas muy rápido. Espera un momento y recarga la página para continuar.";
  } else {
    $("banner-title").textContent = "En pausa por el momento";
    $("banner-text").textContent = "La demo está descansando. Vuelve a intentarlo más tarde.";
  }
}

// ---- Pronunciación palabra por palabra (datos objetivos de Azure) ----
// Portado del frontend legacy: cada palabra se colorea por su accuracy, con los
// sonidos (IPA) visibles y un detalle expandible con el score de cada fonema.
function scoreClass(score) {
  if (score === null || score === undefined) return "unknown";
  if (score >= 80) return "good";
  if (score >= 60) return "fair";
  return "poor";
}
function formatScore(score) {
  return score === null || score === undefined ? "—" : Math.round(score);
}
function wordClass(word) {
  if (word.error_type === "Omission") return "unknown";
  return scoreClass(word.accuracy);
}
function wordTitle(word) {
  const messages = {
    Mispronunciation: "Mal pronunciada",
    UnexpectedBreak: "Pausa inesperada antes de esta palabra",
    MissingBreak: "Faltó una pausa antes de esta palabra",
    Monotone: "Entonación plana",
  };
  const note = messages[word.error_type];
  const score = `Accuracy: ${formatScore(word.accuracy)}`;
  return note ? `${score} — ${note}` : score;
}

// Cada palabra se colorea por su accuracy, con los sonidos (IPA) visibles y un detalle
// expandible con el score de cada fonema. `speak` se inyecta: quién pronuncia la palabra
// depende de los controles de voz de cada página.
function renderWord(word, speak) {
  const wrapper = document.createElement("span");
  wrapper.className = "word-wrapper";

  const button = document.createElement("button");
  button.type = "button";
  button.className = `word ${wordClass(word)}`;
  button.textContent = word.word;
  button.title = wordTitle(word);

  const listen = document.createElement("button");
  listen.type = "button"; listen.className = "speak";
  listen.textContent = "🔊"; listen.title = "Escuchar";
  listen.setAttribute("aria-label", `Escuchar ${word.word}`);
  listen.addEventListener("click", () => speak(word.word));

  const head = document.createElement("div");
  head.className = "word-head";
  head.append(button, listen);

  // Los sonidos (IPA) en orden, cada uno coloreado por su score: se ve QUÉ parte falló.
  const ipa = document.createElement("div");
  ipa.className = "ipa";
  for (const phoneme of word.phonemes || []) {
    const sound = document.createElement("span");
    sound.className = `sound ${scoreClass(phoneme.accuracy)}`;
    sound.textContent = phoneme.phoneme;
    sound.title = `${phoneme.phoneme}: ${formatScore(phoneme.accuracy)}`;
    ipa.appendChild(sound);
  }

  // Detalle con el número exacto de cada sonido, al hacer clic en la palabra.
  const detail = document.createElement("div");
  detail.className = "phonemes hidden";
  if (!word.phonemes || word.phonemes.length === 0) {
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
