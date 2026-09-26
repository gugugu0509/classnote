"""
微信公众号消息处理
"""
import hashlib
import time
import xmltodict
import httpx
from config import DASHSCOPE_API_KEY, DASHSCOPE_BASE_URL, UPLOAD_DIR
from services.session_store import SessionStore
import os
import uuid

# 微信公众号/测试号配置：一律从环境变量读取（请勿在源码里写死 AppSecret）
WECHAT_APPID = os.getenv("WECHAT_APPID", "")
WECHAT_APPSECRET = os.getenv("WECHAT_APPSECRET", "")
WECHAT_TOKEN = os.getenv("WECHAT_TOKEN", "")

# 会话持久化：内容落盘到 DATA_DIR/wechat_sessions.json，服务重启后自动恢复
# 结构：{ openid: { texts: [...], images: [...], last_active: ts } }
_store = SessionStore()

# 微信 access_token 缓存
_access_token = None
_access_token_expire = 0


def verify_signature(signature: str, timestamp: str, nonce: str) -> bool:
    """验证微信签名"""
    tmp = sorted([WECHAT_TOKEN, timestamp, nonce])
    tmp_str = "".join(tmp)
    return hashlib.sha1(tmp_str.encode()).hexdigest() == signature


def parse_message(xml_body: str) -> dict:
    """解析微信XML消息"""
    try:
        return xmltodict.parse(xml_body).get("xml", {})
    except Exception as e:
        print(f"微信消息解析失败: {e}")
        return {}



def _cdata(text: str) -> str:
    """构建安全的 CDATA 文本，防止内容中的 ]]> 破坏 XML"""
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def build_text_reply(from_user: str, to_user: str, content: str) -> str:
    """构建文本回复XML"""
    return f"""<xml>
<ToUserName>{_cdata(from_user)}</ToUserName>
<FromUserName>{_cdata(to_user)}</FromUserName>
<CreateTime>{int(time.time())}</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content>{_cdata(content)}</Content>
</xml>"""


def get_user_session(openid: str) -> dict:
    """获取或创建用户会话（落盘实现见 services/session_store.py）"""
    return _store.get(openid)


async def get_access_token() -> str:
    """获取微信 access_token"""
    global _access_token, _access_token_expire
    if _access_token and time.time() < _access_token_expire:
        return _access_token

    url = "https://api.weixin.qq.com/cgi-bin/token"
    params = {
        "grant_type": "client_credential",
        "appid": WECHAT_APPID,
        "secret": WECHAT_APPSECRET,
    }
    async with httpx.AsyncClient() as client:
        r = await client.get(url, params=params)
        data = r.json()
        _access_token = data.get("access_token")
        _access_token_expire = time.time() + data.get("expires_in", 7200) - 300
        return _access_token


async def handle_message(msg: dict) -> str:
    """处理微信消息：无论成功失败，处理完都把会话落盘（服务重启不丢笔记）。"""
    try:
        return await _handle_message_inner(msg)
    finally:
        _store.save()


async def _handle_message_inner(msg: dict) -> str:
    """实际的消息分发逻辑。"""
    msg_type = msg.get("MsgType", "")
    from_user = msg.get("FromUserName", "")
    to_user = msg.get("ToUserName", "")
    session = get_user_session(from_user)

    # 文本消息
    if msg_type == "text":
        content = msg.get("Content", "").strip()

        if content in ["生成", "生成导图", "生成思维导图"]:
            return await handle_generate(from_user, to_user, session)

        elif content in ["清空", "重新开始", "重置"]:
            session["texts"] = []
            session["images"] = []
            return build_text_reply(from_user, to_user, "已清空，重新开始吧")
        elif content in ["帮助", "help"]:
            return build_text_reply(from_user, to_user,
                "📝 课堂笔记助手\n\n"
                "🎙️ 发语音 → 自动转写\n"
                "📷 发图片 → 提取知识点\n"
                "✍️ 发文字 → 手动输入笔记\n"
                "回复「生成」→ 生成思维导图\n"
                "回复「清空」→ 重新开始\n"
                "回复「状态」→ 查看当前进度"
            )
        elif content in ["状态", "进度"]:
            text_count = len(session["texts"])
            img_count = len(session["images"])
            char_count = sum(len(t) for t in session["texts"])
            return build_text_reply(from_user, to_user,
                f"📊 当前进度\n\n"
                f"🎙️ 已记录语音：{text_count} 段\n"
                f"📷 已提取图片：{img_count} 张\n"
                f"📝 文字总量：{char_count} 字符\n\n"
                f"回复「生成」创建思维导图"
            )

        else:
            # 其他文本，当手动笔记
            session["texts"].append(content)
            return build_text_reply(from_user, to_user,
                f"已记录文字笔记 ({len(content)}字)\n"
                f"当前共 {len(session['texts'])} 段文字，{len(session['images'])} 张图片\n"
                f"回复「生成」创建思维导图"
            )

    # 语音消息
    elif msg_type == "voice":
        media_id = msg.get("MediaId", "")
        text = await download_and_transcribe(media_id)
        if text:
            session["texts"].append(text)
            preview = text[:100] + ("…" if len(text) > 100 else "")
            return build_text_reply(from_user, to_user,
                f"🎙️ 已转写：\n{preview}\n\n"
                f"当前共 {len(session['texts'])} 段\n"
                f"回复「生成」创建思维导图"
            )
        else:
            return build_text_reply(from_user, to_user,
                "语音转写失败，请稍后重试"
            )

    # 图片消息
    elif msg_type == "image":
        media_id = msg.get("MediaId", "")
        knowledge = await download_and_analyze_image(media_id)
        if knowledge:
            session["images"].append(knowledge)
            preview = knowledge[:100] + ("…" if len(knowledge) > 100 else "")
            return build_text_reply(from_user, to_user,
                f"📷 已提取：\n{preview}\n\n"
                f"当前共 {len(session['images'])} 张\n"
                f"回复「生成」创建思维导图"
            )
        else:
            return build_text_reply(from_user, to_user,
                "图片识别失败，请稍后重试"
            )

    # 其他消息类型
    else:
        return build_text_reply(from_user, to_user,
            "请发送语音、图片、文字，或回复「生成」创建思维导图。回复「帮助」查看使用说明。"
        )


async def handle_generate(from_user: str, to_user: str, session: dict) -> str:
    """生成思维导图"""
    texts = session.get("texts", [])
    images = session.get("images", [])

    if not texts and not images:
        return build_text_reply(from_user, to_user,
            "还没有任何内容。请先发送语音、图片或文字。"
        )

    # 合并文字
    full_text = "\n\n".join(texts)

    # 调用LLM生成
    from services.llm_service import generate_mindmap
    result = await generate_mindmap(full_text, images if images else None)

    if "error" in result:
        return build_text_reply(from_user, to_user,
            f"生成失败：{result['error']}"
        )

    # 回复导图内容（微信限制2048字，太长则截断）
    mindmap = result["mindmap"]
    title = result.get("title", "思维导图")

    if len(mindmap) > 1800:
        mindmap = mindmap[:1800] + "\n\n…(内容过长已截断)"

    reply = f"🧠 {title}\n\n{mindmap}\n\n━━━━━━━\n回复「清空」重新开始 | 「帮助」查看说明"

    # 清空会话
    session["texts"] = []
    session["images"] = []

    return build_text_reply(from_user, to_user, reply)


async def download_and_transcribe(media_id: str) -> str | None:
    """下载微信语音文件并转写"""
    token = await get_access_token()
    url = f"https://api.weixin.qq.com/cgi-bin/media/get?access_token={token}&media_id={media_id}"

    save_path = os.path.join(UPLOAD_DIR, f"wechat_voice_{uuid.uuid4().hex}.amr")
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            r = await client.get(url)
            if r.status_code == 200:
                with open(save_path, "wb") as f:
                    f.write(r.content)

                from services.asr_service import transcribe_audio
                result = await transcribe_audio(save_path)
                return result.get("text")
        except Exception as e:
            print(f"语音下载/转写异常: {e}")
    return None


async def download_and_analyze_image(media_id: str) -> str | None:
    """下载微信图片并提取知识点"""
    token = await get_access_token()
    url = f"https://api.weixin.qq.com/cgi-bin/media/get?access_token={token}&media_id={media_id}"

    save_path = os.path.join(UPLOAD_DIR, f"wechat_img_{uuid.uuid4().hex}.jpg")
    os.makedirs(UPLOAD_DIR, exist_ok=True)

    async with httpx.AsyncClient(timeout=60) as client:
        try:
            r = await client.get(url)
            if r.status_code == 200:
                with open(save_path, "wb") as f:
                    f.write(r.content)

                from services.vision_service import extract_knowledge_from_image
                result = await extract_knowledge_from_image(save_path)
                return result.get("text")
        except Exception as e:
            print(f"图片下载/识别异常: {e}")
    return None
