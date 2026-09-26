"""
思维导图生成 & 管理路由
"""
import os
import re
import json
import uuid
from datetime import datetime
from fastapi import APIRouter
from pydantic import BaseModel
from config import MINDMAP_DIR, LOCAL_EXPORT_DIR, UPLOAD_DIR
from services.llm_service import generate_mindmap

router = APIRouter(prefix="/api/mindmap", tags=["思维导图"])

os.makedirs(MINDMAP_DIR, exist_ok=True)


class MindmapRequest(BaseModel):
    transcript_text: str
    image_texts: list[str] = []
    image_ids: list[str] = []


class SaveRequest(BaseModel):
    subject: str
    title: str
    mindmap: str
    date: str = None


class UpdateTitleRequest(BaseModel):
    title: str



@router.post("/generate")
async def create_mindmap(req: MindmapRequest):
    """根据转写文字和图片生成思维导图"""
    image_paths = []
    for file_id in req.image_ids:
        safe_name = os.path.basename(file_id)
        path = os.path.join(UPLOAD_DIR, safe_name)
        if safe_name and os.path.exists(path):
            image_paths.append(path)

    result = await generate_mindmap(
        req.transcript_text,
        req.image_texts,
        image_paths or None,
    )

    if "error" not in result:
        # 自动保存
        result["id"] = _save_mindmap(
            subject=result.get("subject", "未分类"),
            title=result.get("title", "未知课程"),
            mindmap=result["mindmap"],
        )

    return result


@router.post("/save")
async def save_mindmap(req: SaveRequest):
    """手动保存/更新思维导图"""
    mindmap_id = _save_mindmap(req.subject, req.title, req.mindmap, req.date)
    return {"id": mindmap_id, "status": "saved"}


@router.get("/list")
async def list_mindmaps(subject: str = None):
    """获取所有思维导图列表，可按科目筛选"""
    mindmaps = []
    for filename in os.listdir(MINDMAP_DIR):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(MINDMAP_DIR, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if subject and data.get("subject") != subject:
                continue
            mindmaps.append({
                "id": data["id"],
                "subject": data["subject"],
                "title": data["title"],
                "date": data.get("date", ""),
            })
        except Exception:
            pass

    mindmaps.sort(key=lambda x: x.get("date", ""), reverse=True)
    return {"mindmaps": mindmaps}



def _safe_mindmap_id(mindmap_id: str) -> str:
    """只允许 12 位十六进制 id，防止路径穿越"""
    name = os.path.basename(mindmap_id or "")
    if re.fullmatch(r"[0-9a-fA-F]{12}", name):
        return name
    return ""


@router.get("/subjects/list")
async def list_subjects():
    """获取所有科目列表（必须定义在 /{mindmap_id} 之前，否则会被动态路由遮蔽）"""
    subjects_set = set()
    for filename in os.listdir(MINDMAP_DIR):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(MINDMAP_DIR, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            subjects_set.add(data.get("subject", "未分类"))
        except Exception:
            pass
    return {"subjects": sorted(subjects_set)}


@router.get("/{mindmap_id}")
async def get_mindmap(mindmap_id: str):
    """获取单个思维导图详情"""
    safe_id = _safe_mindmap_id(mindmap_id)
    if not safe_id:
        return {"error": "思维导图不存在"}
    path = os.path.join(MINDMAP_DIR, f"{safe_id}.json")
    if not os.path.exists(path):
        return {"error": "思维导图不存在"}

    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


@router.delete("/{mindmap_id}")
async def delete_mindmap(mindmap_id: str):
    """删除思维导图"""
    safe_id = _safe_mindmap_id(mindmap_id)
    if not safe_id:
        return {"error": "思维导图不存在"}
    path = os.path.join(MINDMAP_DIR, f"{safe_id}.json")
    if not os.path.exists(path):
        return {"error": "思维导图不存在"}
    os.remove(path)
    return {"status": "deleted", "id": safe_id}


SHARED_DIR = "shared"
os.makedirs(SHARED_DIR, exist_ok=True)


@router.post("/{mindmap_id}/share")
async def share_mindmap(mindmap_id: str):
    """分享思维导图给温凉"""
    safe_id = _safe_mindmap_id(mindmap_id)
    if not safe_id:
        return {"error": "思维导图不存在"}
    src = os.path.join(MINDMAP_DIR, f"{safe_id}.json")
    if not os.path.exists(src):
        return {"error": "思维导图不存在"}

    with open(src, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 保存到共享目录
    share_path = os.path.join(SHARED_DIR, f"{safe_id}.md")
    with open(share_path, "w", encoding="utf-8") as f:
        f.write(f"# {data['title']}\n\n")
        f.write(f"> {data['subject']} · {data['date']}\n\n")
        f.write(data['mindmap'])

    return {"status": "shared", "id": safe_id, "title": data["title"]}


@router.post("/{mindmap_id}/confirm-local")
async def confirm_local_save(mindmap_id: str):
    """用户确认后，把导图保存到本机 LOCAL_EXPORT_DIR（默认 data/exports，可用 CLASSNOTE_EXPORT_DIR 指定）"""
    safe_id = _safe_mindmap_id(mindmap_id)
    if not safe_id:
        return {"error": "思维导图不存在"}
    src = os.path.join(MINDMAP_DIR, f"{safe_id}.json")
    if not os.path.exists(src):
        return {"error": "思维导图不存在"}

    with open(src, "r", encoding="utf-8") as f:
        data = json.load(f)

    try:
        os.makedirs(LOCAL_EXPORT_DIR, exist_ok=True)
        filename = _build_local_filename(data, safe_id)
        local_path = os.path.join(LOCAL_EXPORT_DIR, filename)

        with open(local_path, "w", encoding="utf-8") as f:
            f.write(f"# {data.get('title', '未命名')}\n\n")
            f.write(f"> {data.get('subject', '未分类')} · {data.get('date', '')}\n\n")
            f.write(data.get("mindmap", ""))

        return {
            "status": "saved_local",
            "id": safe_id,
            "filename": filename,
            "path": local_path,
        }
    except Exception as e:
        return {"error": f"本地保存失败: {e}"}



@router.post("/{mindmap_id}/title")
async def update_mindmap_title(mindmap_id: str, req: UpdateTitleRequest):
    """修改思维导图标题，并同步已保存到本机的本地文件（LOCAL_EXPORT_DIR）"""
    safe_id = _safe_mindmap_id(mindmap_id)
    if not safe_id:
        return {"error": "思维导图不存在"}

    src = os.path.join(MINDMAP_DIR, f"{safe_id}.json")
    if not os.path.exists(src):
        return {"error": "思维导图不存在"}

    new_title = req.title.strip()
    if not new_title:
        return {"error": "标题不能为空"}

    with open(src, "r", encoding="utf-8") as f:
        data = json.load(f)

    old_title = data.get("title", "")
    data["title"] = new_title

    with open(src, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    local_updated = False
    if os.path.isdir(LOCAL_EXPORT_DIR):
        suffix = f"_{safe_id}.md"
        for filename in os.listdir(LOCAL_EXPORT_DIR):
            if not filename.endswith(suffix):
                continue
            local_path = os.path.join(LOCAL_EXPORT_DIR, filename)
            try:
                with open(local_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                with open(local_path, "w", encoding="utf-8") as f:
                    for line in lines:
                        if line.startswith("# ") and old_title and old_title in line:
                            f.write(f"# {new_title}\n")
                        else:
                            f.write(line)
                local_updated = True
            except Exception:
                pass

    return {
        "status": "updated",
        "id": safe_id,
        "title": new_title,
        "local_updated": local_updated,
    }


def _build_local_filename(data: dict, mindmap_id: str) -> str:
    """根据导图信息生成安全的本地文件名"""
    subject = _safe_filename(data.get("subject", "未分类"))[:40]
    title = _safe_filename(data.get("title", "未命名"))[:60]
    date = _safe_filename(data.get("date", "")).replace(" ", "_")[:20]
    return f"{date}_{subject}_{title}_{mindmap_id}.md"


def _safe_filename(text: str) -> str:
    """移除 Windows 文件名中的非法字符"""
    text = re.sub(r'[\\/:*?"<>|]', "_", str(text))
    text = text.strip().strip(".")
    return text or "未命名"



def _save_mindmap(subject: str, title: str, mindmap: str, date: str = None) -> str:
    """保存思维导图到文件"""
    mindmap_id = uuid.uuid4().hex[:12]
    data = {
        "id": mindmap_id,
        "subject": subject,
        "title": title,
        "mindmap": mindmap,
        "date": date or datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    path = os.path.join(MINDMAP_DIR, f"{mindmap_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return mindmap_id
