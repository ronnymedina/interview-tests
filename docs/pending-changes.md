# Pending changes

Ideas already discussed but not implemented yet, ordered by impact/effort.

> Note: these ideas were written when the code lived at the repo root. Their current
> equivalents are under `app/`: the frontend in `app/web/static/`, and the Azure logic in
> `app/speech/` (`azure_client.py` + `assessment.py`).

## Azure latency (improving response time)

The delay does **not** come from the free tier (F0 and S0 have the same per-request latency;
F0 only caps quota). The real causes and their possible fixes:

- [ ] **A closer region** (easy, no code). Change `AZURE_SPEECH_REGION` in `.env` to the
  nearest Azure region (e.g. `brazilsouth`, `westeurope`). Requires the Speech resource to be
  created in that region. Usually the biggest win when you are far from `eastus`.
- [ ] **Stream while speaking** (architectural change, high impact on perceived speed). Send
  the audio to Azure live instead of record-then-upload the whole WAV. The result would show
  up almost the instant you stop, because analysis happens while you read. Touches
  `app/web/static/` (capturing and sending chunks) and `app/speech/` (recognition from a
  stream instead of a file).
- [ ] **Shorter texts** (no code). Processing time scales with audio duration.
- [ ] **Drop prosody** (easy, with a trade-off). Removing `enable_prosody_assessment()` in
  `app/speech/azure_client.py` speeds things up somewhat, at the cost of the prosody score.
- [ ] **Closing silence** (`Speech_SegmentationSilenceTimeoutMs`, currently 1500 ms).
  Lowering it cuts the final wait, but risks cutting off legitimate long pauses.

## Hearing pronunciation (text-to-speech)

- [x] **Browser Web Speech API** (done). A 🔊 button for the full text in Practice, and one 🔊
  per word in "Word by word". `en-US` voice, rate 0.9. No backend, free.
- [ ] **Hear the words in the Word bank.** Add 🔊 to every word in that view — it is where the
  ones that need work get reviewed.
- [ ] **Upgrade to Azure Neural TTS** (optional). More natural and consistent voices, with
  SSML to slow it down or force a phoneme. Reuses the same Speech resource (same key and
  region). Requires synthesizing on the backend and returning the audio.

## Texts view

- [ ] Show the text content **with formatting** (line breaks) in the Texts tab table, the
  same way the Practice view already does (`white-space: pre-wrap`).

## Notes

- Saving and formatted display in Practice are already solved (`white-space: pre-wrap` on
  `.reference-text`).
- Azure handles formatted text without trouble: it ignores line breaks and extra spaces when
  matching, and uses punctuation to assess pauses and prosody. No need to clean it up.
