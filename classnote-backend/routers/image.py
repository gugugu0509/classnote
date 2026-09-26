"""
图片上传 & 知识点提取路由
"""
import os
import uuid
from pathlib import Path
from fastapi import APIRouter, UploadFile, File
from config import UPLOAD_DIR, MAX_IMAGE_SIZE
from services.vision_service import extract_knowledge_from_image

router = APIRouter(prefix="/api/image", tags=["图片"])


@router.post("/upload")
async def upload_image(file: UploadFile = File(...)):
    """上传课堂图片，提取知识点"""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    ext = Path(file.filename).suffix or ".jpg"
    save_name = f"{uuid.uuid4().hex}{ext}"
    save_path = os.path.join(UPLOAD_DIR, save_name)

    size = 0
    with open(save_path, "wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_IMAGE_SIZE:
                f.close()
                try:
                    os.remove(save_path)
                except Exception:
                    pass
                return {"error": f"图片太大，最大支持 {MAX_IMAGE_SIZE // 1024 // 1024}MB"}
            f.write(chunk)

    # 提取知识点
    result = await extract_knowledge_from_image(save_path)
    result["file_id"] = save_name

    return result
