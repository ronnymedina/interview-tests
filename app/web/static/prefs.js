"use strict";
// Único lugar que sabe DÓNDE se guardan las preferencias del usuario.
//
// Hoy es localStorage. Si mañana pasan a la base de datos detrás de un endpoint, solo cambia
// este archivo: ni Tts, ni la conversación, ni la lectura se enteran. Por eso nadie más en el
// frontend menciona localStorage.

// Las tres voces entre las que se elige. Solo existen en Chrome, que es el único navegador
// que esta versión soporta.
const VOICES = [
  { name: "Google US English", label: "🇺🇸 US" },
  { name: "Google UK English Female", label: "🇬🇧 UK F" },
  { name: "Google UK English Male", label: "🇬🇧 UK M" },
];

const Prefs = {
  // Se guarda el NOMBRE de la voz, no su posición en la lista del navegador: un índice
  // apuntaría a otra voz si cambiara el orden de las voces instaladas, y no significaría
  // nada si algún día esto viajara a un endpoint.
  voiceName() {
    return localStorage.getItem("pilot_voice") || VOICES[0].name;
  },
  setVoiceName(name) {
    localStorage.setItem("pilot_voice", name);
  },

  rate() {
    return Number(localStorage.getItem("pilot_rate")) || 0.95;
  },
  setRate(value) {
    localStorage.setItem("pilot_rate", String(value));
  },

  // Tope de dificultad de los textos de lectura. 7 es el máximo que ingiere el catálogo,
  // así que por defecto no filtra nada.
  maxLevel() {
    return Number(localStorage.getItem("pilot_max_level")) || 7;
  },
  setMaxLevel(level) {
    localStorage.setItem("pilot_max_level", String(level));
  },
};
