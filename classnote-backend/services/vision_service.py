"""
多模态视觉服务
使用大模型的视觉能力，从图片中提取知识点
"""
import base64
import json
import httpx
from pathlib import Path
from config import (
    DASHSCOPE_API_KEY,
    DASHSCOPE_BASE_URL,
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    DEEPSEEK_ENABLED,
    DEEPSEEK_MODEL,
)


VISION_PROMPT = """你是一位教育领域的图像识别专家。请仔细分析这张课堂相关的图片（可能是黑板板书、PPT课件、课本插图、手写笔记等）。

请完成以下任务：
1. 提取图片中的所有文字内容
2. 识别图片中的图表、公式、示意图并描述其含义
3. 提炼出核心知识点，用简洁的要点形式输出
4. 如果图片中有例题，请提取题目和解题步骤

输出格式：
```
### 图片内容概述
[一句话描述这是什么]

### 知识点提取
- **知识点1**: [详细解释]
- **知识点2**: [详细解释]
...

### 公式/定理（如有）
$$公式$$

### 例题（如有）
**题目**: ...
**解答**: ...
```
"""


async def _extract_with_deepseek(image_data_url: str) -> dict:
    """DeepSeek V4 Flash 多模态实验版：图片知识点提取"""
    url = f"{DEEPSEEK_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": image_data_url},
                    },
                    {"type": "text", "text": VISION_PROMPT},
                ],
            }
        ],
        "temperature": 0.1,
        "max_tokens": 4000,
    }

    async with httpx.AsyncClient(timeout=120) as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code == 200:
                result = response.json()
                text = result["choices"][0]["message"]["content"]
                return {"text": text, "provider": "deepseek", "model": DEEPSEEK_MODEL}
            error_text = response.text[:300]
            return {"error": f"DeepSeek视觉识别失败: HTTP {response.status_code} {error_text}"}
        except Exception as e:
            return {"error": f"DeepSeek视觉识别异常: {str(e)}"}


async def extract_knowledge_from_image(image_path: str) -> dict:
    """
    从图片中提取知识点。
    配置了 DeepSeek API Key 时自动使用 DeepSeek V4 Flash 多模态实验版；
    否则回退到阿里云百炼 qwen-vl-plus。
    """
    # 读取图片并转为 base64
    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    # 推断 MIME 类型
    ext = Path(image_path).suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".bmp": "image/bmp",
    }
    mime_type = mime_map.get(ext, "image/jpeg")
    image_data_url = f"data:{mime_type};base64,{image_data}"

    if DEEPSEEK_ENABLED:
        return await _extract_with_deepseek(image_data_url)

    url = f"{DASHSCOPE_BASE_URL}/compatible-mode/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": "qwen-vl-plus",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{mime_type};base64,{image_data}"
                        },
                    },
                    {"type": "text", "text": VISION_PROMPT},
                ],
            }
        ],
        "temperature": 0.1,
        "max_tokens": 4000,
    }

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            response = await client.post(url, headers=headers, json=payload)
            if response.status_code == 200:
                result = response.json()
                text = result["choices"][0]["message"]["content"]
                return {"text": text}
            else:
                return {"error": f"视觉识别失败: HTTP {response.status_code}"}
        except Exception as e:
            return {"error": str(e)}
