"""
LLM 文本结构化服务
将转写文字结构化，生成思维导图 Markdown
"""
import base64
import json
from pathlib import Path
import httpx
from config import (
    DASHSCOPE_API_KEY,
    DASHSCOPE_BASE_URL,
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_ENABLED,
    DEEPSEEK_MAX_TOKENS,
    DEEPSEEK_MODEL,
)


SYSTEM_PROMPT = """你是一位资深的内容整理专家。你的任务是将录音转写的文字整理成结构化的思维导图。

无论录音是什么内容——会议、课堂、播客、访谈、读书笔记、日常讨论——你都能从中提炼出清晰的逻辑结构。

请严格遵循以下规则：

1. 从文字中识别核心主题，按「主题 → 要点 → 细节」的层级组织
2. 提取关键信息：重要观点、论据、数据、结论、待办事项、定义、公式等
3. 输出格式必须是合法的 Markdown，用 # / ## / ### / #### 表示层级
4. 第一行用 # 写出内容主题作为标题
5. 不要遗漏重要信息，也不要添加原文中没有的内容
6. 如果原文提到公式或数据，用适当格式呈现（公式用 $$...$$ 包裹）
7. 每个要点下面要有具体的解释或例子，不要只写标题

输出格式示例：
```
# [内容主题]

## 一、[要点一]
### 1.1 [子要点]
- [具体内容]
- [例子/数据]

### 1.2 [子要点]
...

## 二、[要点二]
...
```
"""


def _build_full_content(transcript_text: str, image_texts: list[str] | None) -> str:
    full_content = f"## 录音转写内容\n\n{transcript_text}"
    if image_texts:
        image_block = "\n\n".join(
            f"## 图片{i+1}内容\n\n{t}" for i, t in enumerate(image_texts)
        )
        full_content += f"\n\n---\n\n{image_block}"
    return full_content


def _read_image_data_url(image_path: str) -> str | None:
    try:
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")
        ext = Path(image_path).suffix.lower()
        mime_map = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
        }
        mime_type = mime_map.get(ext, "image/jpeg")
        return f"data:{mime_type};base64,{image_data}"
    except Exception:
        return None


async def _generate_mindmap_deepseek(full_content: str, image_paths: list[str] | None) -> dict:
    """DeepSeek V4 Flash 多模态实验版：导图生成"""
    image_urls = []
    if image_paths:
        for image_path in image_paths:
            data_url = _read_image_data_url(image_path)
            if data_url:
                image_urls.append({"type": "image_url", "image_url": {"url": data_url}})

    if image_urls:
        user_content = [{"type": "text", "text": full_content}] + image_urls
    else:
        user_content = full_content

    url = f"{DEEPSEEK_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        "temperature": 0.3,
        "max_tokens": DEEPSEEK_MAX_TOKENS,
    }

    async with httpx.AsyncClient(timeout=180) as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code == 200:
                result = response.json()
                mindmap_text = result["choices"][0]["message"]["content"]
                subject, title = _extract_metadata(mindmap_text)
                return {
                    "provider": "deepseek",
                    "model": DEEPSEEK_MODEL,
                    "subject": subject,
                    "title": title,
                    "mindmap": mindmap_text,
                }
            error_text = response.text[:300]
            return {"error": f"DeepSeek调用失败: HTTP {response.status_code} {error_text}"}
        except Exception as e:
            return {"error": f"DeepSeek调用异常: {str(e)}"}


async def _generate_mindmap_dashscope(full_content: str) -> dict:
    """阿里云百炼 qwen-plus 备用通道"""
    url = f"{DASHSCOPE_BASE_URL}/compatible-mode/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "qwen-plus",
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": full_content},
        ],
        "temperature": 0.3,
        "max_tokens": 8000,
    }

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code == 200:
                result = response.json()
                mindmap_text = result["choices"][0]["message"]["content"]
                subject, title = _extract_metadata(mindmap_text)
                return {
                    "provider": "dashscope",
                    "model": "qwen-plus",
                    "subject": subject,
                    "title": title,
                    "mindmap": mindmap_text,
                }
            return {"error": f"LLM调用失败: {response.status_code}"}
        except Exception as e:
            return {"error": str(e)}


async def generate_mindmap(
    transcript_text: str,
    image_texts: list[str] = None,
    image_paths: list[str] = None,
) -> dict:
    """
    生成课堂思维导图。
    配置了 DeepSeek API Key 时自动使用 DeepSeek V4 Flash 多模态实验版；
    否则回退到阿里云百炼 qwen-plus，保证现有功能可用。
    """
    full_content = _build_full_content(transcript_text, image_texts)

    if DEEPSEEK_ENABLED:
        return await _generate_mindmap_deepseek(full_content, image_paths)
    return await _generate_mindmap_dashscope(full_content)


def _extract_metadata(mindmap: str) -> tuple[str, str]:
    """从思维导图内容中提取标题：优先找第一个一级标题"""
    for raw_line in mindmap.strip().splitlines():
        line = raw_line.strip()
        if line.startswith("```"):
            continue
        if line.startswith("# "):
            title = line[2:].strip()
            return "未分类", title or "未命名"
        if line.startswith("#") and not line.startswith("##"):
            title = line.lstrip("#").strip()
            return "未分类", title or "未命名"

    first_line = mindmap.strip().splitlines()[0].strip() if mindmap.strip() else ""
    title = first_line or "未命名"
    return "未分类", title
