"""FastAPI app — API contract v0 (xem .superpowers/sdd/app-skeleton-brief.md).

Chạy demo: `uvicorn app.backend.api:app --reload` rồi mở http://localhost:8000
"""
from __future__ import annotations

import logging
import os
from datetime import date

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.backend import asr, handoff, history, pipeline, registry_api, tts
from app.backend.handoff import HANDOFF_DB  # re-export cho test_api.py (tương thích ngược)
from app.backend.schemas import (
    AskRequest,
    AskResponse,
    TranscribeResponse,
    TtsRequest,
)

load_dotenv()

BASE_DIR = __import__("pathlib").Path(__file__).resolve().parent.parent.parent
WEB_DIR = BASE_DIR / "app" / "web"

TRANSCRIBE_UNAVAILABLE_MSG = "Dạ hiện em chưa nhận diện được giọng nói, bác gõ chữ giúp em nhé."
TRANSCRIBE_FAILED_MSG = "Dạ em nhận diện giọng nói bị lỗi, bác thử lại hoặc gõ chữ giúp em nhé."
TTS_UNAVAILABLE_MSG = "Dạ thiết bị chưa có giọng Việt và máy chủ chưa cấu hình Google Text-to-Speech."
TTS_FAILED_MSG = "Dạ em chưa tạo được giọng đọc tiếng Việt, bác thử lại sau nhé."

logger = logging.getLogger(__name__)

app = FastAPI(title="Trợ lý nông nghiệp — API v0")
app.include_router(history.router)
app.include_router(registry_api.router)
app.include_router(handoff.router)


@app.post("/api/ask", response_model=AskResponse)
def ask(req: AskRequest) -> AskResponse:
    result = pipeline.answer(req.text, req.region, date.today().isoformat(), session_id=req.session_id)
    response = AskResponse(**result)
    # Ghi log câu hỏi vào question_log — best-effort, lỗi nuốt bên trong log_question
    handoff.log_question(
        region=response.slots.region,
        crop=response.slots.crop,
        pest=response.slots.pest,
        text=req.text,
    )
    return response


@app.post("/api/transcribe", response_model=TranscribeResponse)
async def transcribe(audio: UploadFile = File(...)) -> TranscribeResponse:
    audio_bytes = await audio.read()

    # Ưu tiên (a) Google STT v2 Chirp 3 nếu có creds thật -> (b) whisper-1 stopgap
    # nếu chỉ có OPENAI_API_KEY -> (c) 503 tiếng Việt nếu không có gì.
    if asr.google_credentials_available():
        try:
            text = await asr.transcribe_google(audio_bytes)
        except Exception:
            logger.exception("Google Speech-to-Text transcription failed")
            raise HTTPException(status_code=502, detail=TRANSCRIBE_FAILED_MSG)
        return TranscribeResponse(text=text)

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail=TRANSCRIBE_UNAVAILABLE_MSG)

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://api.openai.com/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {api_key}"},
            data={"model": "whisper-1", "language": "vi"},
            files={"file": (audio.filename or "audio.webm", audio_bytes, audio.content_type or "audio/webm")},
        )
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=TRANSCRIBE_FAILED_MSG)
    data = resp.json()
    return TranscribeResponse(text=data.get("text", ""))


@app.post("/api/tts", response_class=Response)
async def synthesize_speech(req: TtsRequest) -> Response:
    if not asr.google_credentials_available():
        raise HTTPException(status_code=503, detail=TTS_UNAVAILABLE_MSG)
    try:
        audio = await tts.synthesize_google(req.text)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except tts.TtsServiceDisabledError as exc:
        raise HTTPException(
            status_code=503,
            detail="Cloud Text-to-Speech API chưa được bật. Hãy bật API này trong Google Cloud Console rồi thử lại.",
        ) from exc
    except Exception:
        logger.exception("Google Text-to-Speech synthesis failed")
        raise HTTPException(status_code=502, detail=TTS_FAILED_MSG)
    return Response(
        content=audio,
        media_type="audio/mpeg",
        headers={"Cache-Control": "private, max-age=3600"},
    )


# Trang landing ở "/" — app chat chuyển sang "/chat" (endpoint handoff cũ đã
# chuyển vào app/backend/handoff.py router).
@app.get("/")
def landing():
    return FileResponse(WEB_DIR / "landing.html")


@app.get("/chat")
def chat():
    return FileResponse(WEB_DIR / "index.html")



# Đăng ký API routes xong mới mount static — mount "/" chỉ bắt các path không khớp
# route nào ở trên (Starlette thử theo thứ tự đăng ký), đồng thời cho sw.js scope "/".
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
