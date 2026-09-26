"""
课堂笔记助手 - 配置文件
"""
import os


def _read_first_line(path: str, default: str = "") -> str:
    """读取密钥文件: 跳过空行与 # 注释行, 取第一个有效行"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    return line
    except Exception:
        pass
    return default


# 阿里云百炼 API Key（ASR / 备用视觉和导图生成）
# 优先环境变量 DASHSCOPE_API_KEY；也可用 DASHSCOPE_KEY_FILE 指向一个只放密钥的文件
DASHSCOPE_API_KEY = (
    os.getenv("DASHSCOPE_API_KEY", "").strip()
    or _read_first_line(os.getenv("DASHSCOPE_KEY_FILE", ""))
)

# API 端点
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com"

# ASR 模型（录音文件转写，非实时）
ASR_MODEL = "qwen-audio-3.0-asr-flash-filetrans"

# DeepSeek 官方 API（V4 Flash 多模态实验版）
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
DEEPSEEK_API_KEY_FILE = os.getenv("DEEPSEEK_KEY_FILE", "")      # 可选：只放密钥的文件路径
DEEPSEEK_MODEL_FILE = os.getenv("DEEPSEEK_MODEL_FILE", "")      # 可选：只放模型名的文件路径
DEEPSEEK_DEFAULT_MODEL = "deepseek-v4-flash-multimodal-exp"
DEEPSEEK_MAX_TOKENS = 8000


DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "").strip() or _read_first_line(DEEPSEEK_API_KEY_FILE)
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "").strip() or _read_first_line(DEEPSEEK_MODEL_FILE, DEEPSEEK_DEFAULT_MODEL)
DEEPSEEK_ENABLED = bool(DEEPSEEK_API_KEY)

# 有 DeepSeek Key 时，导图生成和图片识别自动使用 DeepSeek；ASR 仍使用阿里云百炼

# 文件上传目录
UPLOAD_DIR = "uploads"
MAX_AUDIO_SIZE = 200 * 1024 * 1024  # 200MB
MAX_IMAGE_SIZE = 20 * 1024 * 1024   # 20MB

# 运行数据目录（会话持久化等，已在 .gitignore 排除）
DATA_DIR = os.getenv(
    "CLASSNOTE_DATA_DIR",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"),
)

# 思维导图存储
MINDMAP_DIR = "mindmaps"

# 用户确认后，导图在本机的保存目录
# 默认放在运行数据目录下；可用环境变量 CLASSNOTE_EXPORT_DIR 指定任意目录
LOCAL_EXPORT_DIR = os.getenv(
    "CLASSNOTE_EXPORT_DIR",
    os.path.join(DATA_DIR, "exports"),
)
