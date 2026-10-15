"""FastAPI 服务：提供批改接口，并托管前端 index.html。

启动：.venv/bin/uvicorn backend.app:app --port 8000
"""
import base64
import binascii
from pathlib import Path
from typing import Dict, List

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import db
from .grader import MODEL, GradingError, credentials_configured, grade

ROOT = Path(__file__).resolve().parent.parent
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # Claude 单张图片上限
MEDIA_EXT = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}

app = FastAPI(title="智学闭环 · 自适应数学作业系统")


class Question(BaseModel):
    question_id: int
    text: str
    expr: str
    answer: str
    unit: str
    unit_name: str


class GradeRequest(BaseModel):
    student_id: str
    homework_id: str
    image_base64: str
    media_type: str = "image/jpeg"
    questions: List[Question] = Field(min_length=1, max_length=30)
    profile: Dict[str, float] = {}


@app.get("/api/health")
def health():
    return {"ok": True, "ai": credentials_configured(), "model": MODEL}


@app.post("/api/grade")
def grade_homework(req: GradeRequest):
    if not credentials_configured():
        raise HTTPException(503, "服务器未配置 ANTHROPIC_API_KEY")
    if req.media_type not in MEDIA_EXT:
        raise HTTPException(400, "只支持 JPG / PNG / WEBP 图片")
    try:
        image = base64.b64decode(req.image_base64, validate=True)
    except binascii.Error:
        raise HTTPException(400, "图片数据损坏，请重新拍照")
    if len(image) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "图片超过 5MB，请压缩后再上传")

    try:
        result = grade(req.student_id, req.homework_id, req.image_base64, req.media_type,
                       [q.model_dump() for q in req.questions], req.profile)
    except GradingError as e:
        raise HTTPException(502, str(e))

    result["submission_id"] = db.save_submission(req.student_id, req.homework_id, image, MEDIA_EXT[req.media_type], result)
    return result


@app.get("/api/submissions/{student_id}")
def submissions(student_id: str, limit: int = 50):
    return db.list_submissions(student_id, min(limit, 200))


@app.get("/")
def index():
    return FileResponse(ROOT / "index.html")
