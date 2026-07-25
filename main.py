"""Servidor HTTP: sirve la pagina y expone la evaluacion de pronunciacion."""

import os
import tempfile

import uvicorn
from fastapi import FastAPI, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

import config
import conversation
import db
import scoring
import speech

# Los estaticos se sirven con rutas explicitas y no montando la carpeta entera,
# para no exponer .env ni attempts.db por HTTP.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="review-ingles")

db.init_db()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(BASE_DIR, "index.html"))


@app.get("/app.js")
def app_js() -> FileResponse:
    return FileResponse(os.path.join(BASE_DIR, "app.js"), media_type="text/javascript")


@app.get("/style.css")
def style_css() -> FileResponse:
    return FileResponse(os.path.join(BASE_DIR, "style.css"), media_type="text/css")


class TextIn(BaseModel):
    title: str
    content: str
    difficulty: int | None = None


class ConversationStartIn(BaseModel):
    system_prompt: str
    max_questions: int = 5


def _clean_text(text: TextIn) -> tuple[str, str, int | None]:
    """Valida y normaliza un texto de entrada. Lanza 400 con mensaje en espanol."""
    title = text.title.strip()
    content = text.content.strip()
    if not title:
        raise HTTPException(status_code=400, detail="El titulo esta vacio.")
    if not content:
        raise HTTPException(status_code=400, detail="El contenido esta vacio.")
    if text.difficulty is not None and not (1 <= text.difficulty <= 10):
        raise HTTPException(status_code=400, detail="La dificultad debe ser un numero del 1 al 10.")
    return title, content, text.difficulty


@app.get("/texts")
def get_texts() -> list[dict]:
    return db.list_texts()


@app.post("/texts")
def create_text(text: TextIn) -> dict:
    title, content, difficulty = _clean_text(text)
    text_id = db.create_text(title, content, difficulty)
    return db.get_text(text_id)


@app.put("/texts/{text_id}")
def update_text(text_id: int, text: TextIn) -> dict:
    if db.get_text(text_id) is None:
        raise HTTPException(status_code=404, detail="El texto no existe.")
    title, content, difficulty = _clean_text(text)
    db.update_text(text_id, title, content, difficulty)
    return db.get_text(text_id)


@app.delete("/texts/{text_id}")
def delete_text(text_id: int) -> dict:
    if db.get_text(text_id) is None:
        raise HTTPException(status_code=404, detail="El texto no existe.")
    db.delete_text(text_id)
    return {"ok": True}


@app.post("/assess")
async def assess(audio: UploadFile, text_id: int = Form(...)) -> JSONResponse:
    text = db.get_text(text_id)
    if text is None:
        raise HTTPException(status_code=404, detail="El texto no existe.")
    reference_text = text["content"]

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="No llego audio.")

    # El SDK de Azure lee desde un archivo, no desde memoria.
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp.write(audio_bytes)
        wav_path = tmp.name

    try:
        # La evaluacion es sincrona y puede tardar varios segundos; corre en un hilo
        # aparte para no bloquear el servidor.
        result = await run_in_threadpool(speech.assess, wav_path, reference_text)
    except speech.SpeechError as error:
        raise HTTPException(status_code=error.status, detail=str(error))
    finally:
        os.unlink(wav_path)

    result["attempt_id"] = db.save_attempt(text_id, result)
    return JSONResponse(result)


@app.post("/conversation/start")
def conversation_start(payload: ConversationStartIn) -> dict:
    prompt = payload.system_prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="El system prompt esta vacio.")
    if not (1 <= payload.max_questions <= 20):
        raise HTTPException(
            status_code=400, detail="El numero de preguntas debe estar entre 1 y 20."
        )
    try:
        conversation_id, question = conversation.start(prompt, payload.max_questions)
    except conversation.ConversationError as error:
        raise HTTPException(status_code=error.status, detail=str(error))
    return {"conversation_id": conversation_id, "question": question}


@app.post("/conversation/{conversation_id}/answer")
async def conversation_answer(
    conversation_id: str,
    audio: UploadFile,
    mode: str = Form("azure"),
    transcript: str = Form(""),
) -> JSONResponse:
    # Chequeo barato del id antes de cualquier trabajo pesado.
    try:
        conversation_exists = await run_in_threadpool(conversation.exists, conversation_id)
    except conversation.ConversationError as error:
        raise HTTPException(status_code=error.status, detail=str(error))
    if not conversation_exists:
        raise HTTPException(status_code=404, detail="La conversacion no existe o expiro.")

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status_code=400, detail="No llego audio.")

    if mode == "browser":
        # El texto lo transcribe el navegador; el audio se puntua en segundo plano.
        recognized_text = transcript.strip()
        if not recognized_text:
            raise HTTPException(status_code=400, detail="No llego la transcripcion.")
        scoring.enqueue(conversation_id, audio_bytes)
        turn_scores = None
    else:
        # Modo azure: se evalua ahora para mostrar el score del turno; el resultado igual
        # queda encolado para el agregado final.
        future = scoring.enqueue(conversation_id, audio_bytes)
        assessment = await run_in_threadpool(future.result)
        if assessment is None:
            raise HTTPException(
                status_code=422,
                detail="No se detecto voz en el audio. Revisa el microfono e intenta de nuevo.",
            )
        recognized_text = assessment["recognized_text"]
        turn_scores = assessment["scores"]

    try:
        result = await run_in_threadpool(conversation.answer, conversation_id, recognized_text)
    except conversation.ConversationError as error:
        raise HTTPException(status_code=error.status, detail=str(error))

    response = {"recognized_text": recognized_text, "turn_scores": turn_scores}
    if "final" in result:
        final = result["final"]
        scored = await run_in_threadpool(scoring.collect, conversation_id)
        scores, words = scoring.aggregate(scored)
        db.save_conversation(
            final["system_prompt"],
            final["questions_asked"],
            scores,
            final["content_feedback"],
            words,
        )
        response["final"] = {"scores": scores, "content_feedback": final["content_feedback"]}
    else:
        response["next_question"] = result["question"]
    return JSONResponse(response)


@app.get("/history")
def history(limit: int = 20) -> list[dict]:
    return db.list_attempts(limit)


@app.get("/words")
def words(limit: int = 200) -> list[dict]:
    """Banco de palabras: historial por palabra, de peor a mejor."""
    return db.list_word_stats(limit)


@app.get("/word-history")
def word_history(word: str) -> list[dict]:
    """Los scores de una palabra concreta, intento por intento."""
    return db.list_word_history(word)


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=config.PORT)
