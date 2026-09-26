"""
ASR 语音转文字服务
使用阿里云百炼 qwen-audio-3.0-asr-flash-filetrans（异步文件转写）

正确流程:
  1) 上传文件到 Files API 拿到临时 URL（支持大文件，不再受 6MB 请求体限制）
  2) 带 X-DashScope-Async: enable 头提交转写任务
  3) 轮询任务状态
  4) 任务成功后从 transcription_url 下载转写结果

修复历史:
  - 旧实现把整个音频文件直接塞进请求体, 超过百炼网关 6MB 限制 -> 400 TooLarge,
    导致录音文件无法上传转写。
"""
import os
import asyncio
import httpx
from config import DASHSCOPE_API_KEY, DASHSCOPE_BASE_URL, ASR_MODEL

# 音频格式映射：扩展名 -> (ASR格式名, MIME类型)
FORMAT_MAP = {
    'm4a':  ('m4a',  'audio/mp4'),
    'mp3':  ('mp3',  'audio/mpeg'),
    'wav':  ('wav',  'audio/wav'),
    'ogg':  ('ogg',  'audio/ogg'),
    'webm': ('webm', 'audio/webm'),
    'aac':  ('aac',  'audio/aac'),
    'flac': ('flac', 'audio/flac'),
    'amr':  ('amr',  'audio/amr'),
    'wma':  ('wma',  'audio/x-ms-wma'),
    '3gp':  ('3gp',  'audio/3gpp'),
    'opus': ('opus', 'audio/ogg'),
}


def _fmt_of(file_path: str):
    ext = os.path.splitext(file_path)[1].lower().lstrip('.')
    return FORMAT_MAP.get(ext, ('m4a', 'audio/mp4'))


def _headers() -> dict:
    return {"Authorization": "Bearer " + DASHSCOPE_API_KEY}


async def transcribe_audio(file_path: str) -> dict:
    """
    将音频文件转写为文字
    返回: {"text": "转写后的全文", "segments": [{"start": 0, "end": 5.2, "text": "..."}]}
    """
    file_url = await _upload_file(file_path)
    if not file_url:
        return {"error": "上传音频文件失败，请重试"}

    task_id = await _submit_task(file_url, file_path)
    if not task_id:
        return {"error": "提交转写任务失败，请重试"}

    return await _poll_result(task_id)


async def _upload_file(file_path: str):
    """上传到百炼 Files API，返回临时 URL"""
    url = DASHSCOPE_BASE_URL + "/api/v1/files"
    _, mime = _fmt_of(file_path)
    async with httpx.AsyncClient(timeout=300) as client:
        try:
            with open(file_path, "rb") as f:
                response = await client.post(
                    url, headers=_headers(),
                    files={"files": (os.path.basename(file_path), f, mime)},
                )
            if response.status_code != 200:
                print("文件上传失败: %s %s" % (response.status_code, response.text[:300]))
                return None
            uploaded = response.json().get("data", {}).get("uploaded_files", [])
            if not uploaded:
                print("文件上传失败: 返回为空")
                return None
            file_id = uploaded[0].get("file_id")
            if not file_id:
                print("文件上传失败: 缺少 file_id")
                return None

            # 查询文件详情拿临时 URL
            detail = None
            for _ in range(5):
                detail = await client.get(
                    DASHSCOPE_BASE_URL + "/api/v1/files/" + file_id,
                    headers=_headers(),
                )
                if detail.status_code == 200:
                    break
                await asyncio.sleep(2)
            if detail.status_code != 200:
                print("获取文件 URL 失败: %s" % detail.status_code)
                return None
            return detail.json().get("data", {}).get("url")
        except Exception as e:
            print("上传异常: %s" % e)
            return None


async def _submit_task(file_url: str, file_path: str = "") -> str | None:
    """提交异步转写任务，返回 task_id"""
    url = DASHSCOPE_BASE_URL + "/api/v1/services/audio/asr/transcription"

    headers = _headers()
    headers["Content-Type"] = "application/json"
    headers["X-DashScope-Async"] = "enable"

    fmt, _ = _fmt_of(file_path) if file_path else ('m4a', 'audio/mp4')

    body = {
        "model": ASR_MODEL,
        "input": {"file_urls": [file_url]},
        "parameters": {
            "format": fmt,
            "language_hints": ["zh", "en"],
            "disfluency_removal_enabled": True,
        },
    }

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            response = await client.post(url, headers=headers, json=body)
            if response.status_code == 200:
                return response.json().get("output", {}).get("task_id")
            print("提交失败: %s %s" % (response.status_code, response.text[:300]))
            return None
        except Exception as e:
            print("请求异常: %s" % e)
            return None


async def _fetch_transcript(turl: str) -> dict:
    """下载转写结果 JSON，返回 {full_text, segments}"""
    empty = {"full_text": "", "segments": []}
    async with httpx.AsyncClient(timeout=60) as client:
        try:
            resp = await client.get(turl)
            if resp.status_code != 200:
                print("下载转写结果失败: %s" % resp.status_code)
                return empty
            tj = resp.json()
        except Exception as e:
            print("下载转写结果异常: %s" % e)
            return empty

    full_text = ""
    segments = []
    for item in tj.get("transcripts", []):
        # 新结构: transcripts[].text 为整段文本; 也可能带 sentences 分句
        sentences = item.get("sentences")
        if sentences:
            for s in sentences:
                text = (s.get("text") or "").strip()
                if not text:
                    continue
                full_text += text + "\n"
                segments.append({
                    "start": s.get("begin_time", 0) / 1000.0,
                    "end": s.get("end_time", 0) / 1000.0,
                    "text": text,
                    "speaker": s.get("speaker_id", 0),
                })
        else:
            text = (item.get("text") or "").strip()
            if text:
                full_text += text + "\n"
                segments.append({
                    "start": 0,
                    "end": 0,
                    "text": text,
                    "speaker": item.get("speaker_id", 0),
                })
    return {"full_text": full_text, "segments": segments}


async def _poll_result(task_id: str, max_wait: int = 600) -> dict:
    """轮询转写结果；成功后下载 transcription_url 内容"""
    url = DASHSCOPE_BASE_URL + "/api/v1/tasks/" + task_id

    async with httpx.AsyncClient(timeout=60) as client:
        for _ in range(max_wait // 5):
            await asyncio.sleep(5)
            try:
                response = await client.get(url, headers=_headers())
                if response.status_code != 200:
                    continue

                result = response.json()
                output = result.get("output", {})
                task_status = output.get("task_status")

                if task_status == "SUCCEEDED":
                    results = output.get("results", [])
                    full_text = ""
                    segments = []

                    for item in results:
                        # 优先从 transcription_url 下载
                        turl = item.get("transcription_url")
                        if turl:
                            fetched = await _fetch_transcript(turl)
                            full_text += fetched["full_text"]
                            segments.extend(fetched["segments"])
                            continue

                        # 兼容旧结构 transcripts[].channel_results[].sentences[]
                        for seg in item.get("transcripts", []):
                            for ch in seg.get("channel_results", []):
                                for sentence in ch.get("sentences", []):
                                    text = (sentence.get("text") or "").strip()
                                    full_text += text + "\n"
                                    segments.append({
                                        "start": sentence.get("begin_time", 0) / 1000.0,
                                        "end": sentence.get("end_time", 0) / 1000.0,
                                        "text": text,
                                        "speaker": sentence.get("speaker_id", 0),
                                    })

                    if not full_text:
                        return {"error": "转写成功但内容为空（录音可能太短或没有语音）"}
                    return {"text": full_text.strip(), "segments": segments}

                elif task_status == "FAILED":
                    return {"error": "转写失败，请检查录音格式或稍后重试"}

            except Exception as e:
                print("轮询异常: %s" % e)

    return {"error": "转写超时，请稍后重试"}
