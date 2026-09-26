"""
音频上传 & 转写路由
"""
import os
import uuid
from pathlib import Path
from fastapi import APIRouter, UploadFile, File
from config import UPLOAD_DIR, MAX_AUDIO_SIZE
from services.asr_service import transcribe_audio

router = APIRouter(prefix="/api/audio", tags=["音频"])


@router.post("/upload")
async def upload_audio(file: UploadFile = File(...)):
    """上传音频文件并转写为文字"""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = Path(file.filename).suffix or ".m4a"
    save_name = f"{uuid.uuid4().hex}{ext}"
    save_path = os.path.join(UPLOAD_DIR, save_name)

    size = 0
    with open(save_path, "wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_AUDIO_SIZE:
                f.close()
                try:
                    os.remove(save_path)
                except Exception:
                    pass
                return {"error": f"文件太大，最大支持 {MAX_AUDIO_SIZE // 1024 // 1024}MB"}
            f.write(chunk)

    # 转写
    result = await transcribe_audio(save_path)
    result["file_id"] = save_name

    return result
