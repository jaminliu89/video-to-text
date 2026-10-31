"""
config.py — 统一配置管理
优先级：GUI 设置（storage.user） > .env > 默认值
"""

import os
import json
from pathlib import Path


BASE_DIR = Path(__file__).parent
# .app 打包后应用目录只读：用户配置放可写目录
_USER_HOME = Path(os.environ.get("VIDEOTOTEXT_HOME")
                  or (Path.home() / "Library" / "Application Support" / "VideoToText"))
ENV_PATH = BASE_DIR / ".env"
if not ENV_PATH.exists() and (_USER_HOME / ".env").exists():
    ENV_PATH = _USER_HOME / ".env"

# 从 .env 文件读取（不写入 os.environ，避免污染）
_ENV_FILE: dict[str, str] = {}
if ENV_PATH.exists():
    with open(ENV_PATH) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k:
                    _ENV_FILE[k] = v


def _get(key: str, default: str = "") -> str:
    """优先级: GUI storage > .env 文件 > 环境变量 > default"""
    # GUI 设置在运行时注入
    if hasattr(_get, "gui_config") and key in _get.gui_config:
        return _get.gui_config[key]
    if key in _ENV_FILE:
        return _ENV_FILE[key]
    return os.environ.get(key, default)


def set_gui_config(config: dict):
    """从 GUI storage 注入配置"""
    _get.gui_config = config


def get_gui_config() -> dict:
    return getattr(_get, "gui_config", {})


# ===== 配置项 =====

# 本地 Whisper
WHISPER_MODEL = _get("WHISPER_MODEL", "base")
WHISPER_CLI = _get("WHISPER_CLI", "whisper-cli")
WHISPER_MODEL_DIR = Path(_get("WHISPER_MODEL_DIR", str(Path.home() / ".cache" / "whisper"))).expanduser()

# mlx-whisper（Apple Silicon Metal 后端，同一份 Whisper 权重）
MLX_WHISPER_MODEL = _get("MLX_WHISPER_MODEL", "large-v3-turbo")

# Qwen3-ASR：0.6b / 1.7b 走本地 qwen-asr 包；flash 走 DashScope 云端
QWEN3_ASR_MODEL = _get("QWEN3_ASR_MODEL", "0.6b")
# 是否加载强制对齐模型拿字级时间戳（多下载 ~1.2G，长音频更慢）
QWEN3_ASR_ALIGN = _get("QWEN3_ASR_ALIGN", "0") in ("1", "true", "True", "on", "yes")
DASHSCOPE_API_KEY = _get("DASHSCOPE_API_KEY", "")
DASHSCOPE_BASE = _get("DASHSCOPE_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")

# 硅基流动
SILICONFLOW_API_KEY = _get("SILICONFLOW_API_KEY", "")
SILICONFLOW_BASE = _get("SILICONFLOW_BASE", "https://api.siliconflow.cn/v1")
LLM_MODEL = _get("LLM_MODEL", "deepseek-ai/DeepSeek-V3")
VLM_MODEL = _get("VLM_MODEL", "Qwen/Qwen3-VL-32B-Instruct")

# 火山方舟
ARK_API_KEY = _get("ARK_API_KEY", "")
ARK_BASE = _get("ARK_BASE", "https://ark.cn-beijing.volces.com/api/v3")
ARK_VIDEO_ENDPOINT = _get("ARK_VIDEO_ENDPOINT", "")

# Obsidian
DEFAULT_OBSIDIAN_VAULT = str(Path.home() / "Documents" / "Obsidian Vault")
OBSIDIAN_VAULT = Path(_get("OBSIDIAN_VAULT", DEFAULT_OBSIDIAN_VAULT)).expanduser()
DEFAULT_OBSIDIAN_FOLDER = _get("OBSIDIAN_FOLDER", "01_内容创作/视频笔记")

# 路径
CACHE_DIR = Path(_get("CACHE_DIR", str(BASE_DIR / "cache"))).expanduser()
OUTPUT_DIR = Path(_get("OUTPUT_DIR", str(BASE_DIR / "output"))).expanduser()
CACHE_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 关键帧数（关键帧模式）
DEFAULT_FRAME_COUNT = int(_get("FRAME_COUNT", "8"))

# 蒸馏模式专用 LLM（OpenAI 兼容端点）
# 留空则自动回落：硅基流动 → 火山方舟。适合用 Gemini / DeepSeek / 本地 vLLM 等
DISTILL_LLM_BASE = _get("DISTILL_LLM_BASE", "")
DISTILL_LLM_KEY = _get("DISTILL_LLM_KEY", "")
DISTILL_LLM_MODEL = _get("DISTILL_LLM_MODEL", "")
# 思维链开关：auto=抽取类关、抽象类开；off=全关（快 3-5 倍）；on=全开
DISTILL_THINKING = _get("DISTILL_THINKING", "auto")
# 热词纠正表："错词=正词,错词2=正词2"（修中文 ASR 的专有名词误听）
DISTILL_HOTWORDS = _get("DISTILL_HOTWORDS", "")


def all_config_dict() -> dict:
    """返回所有配置（用于设置页显示）"""
    return {
        "WHISPER_MODEL": WHISPER_MODEL,
        "MLX_WHISPER_MODEL": MLX_WHISPER_MODEL,
        "QWEN3_ASR_MODEL": QWEN3_ASR_MODEL,
        "DASHSCOPE_API_KEY": mask_key(DASHSCOPE_API_KEY),
        "SILICONFLOW_API_KEY": mask_key(SILICONFLOW_API_KEY),
        "SILICONFLOW_BASE": SILICONFLOW_BASE,
        "LLM_MODEL": LLM_MODEL,
        "VLM_MODEL": VLM_MODEL,
        "ARK_API_KEY": mask_key(ARK_API_KEY),
        "ARK_BASE": ARK_BASE,
        "ARK_VIDEO_ENDPOINT": ARK_VIDEO_ENDPOINT,
        "DISTILL_LLM_BASE": DISTILL_LLM_BASE,
        "DISTILL_LLM_KEY": mask_key(DISTILL_LLM_KEY),
        "DISTILL_LLM_MODEL": DISTILL_LLM_MODEL,
        "DISTILL_THINKING": DISTILL_THINKING,
        "OBSIDIAN_VAULT": str(OBSIDIAN_VAULT),
        "OBSIDIAN_FOLDER": DEFAULT_OBSIDIAN_FOLDER,
        "CACHE_DIR": str(CACHE_DIR),
        "OUTPUT_DIR": str(OUTPUT_DIR),
    }


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "***"
    return key[:4] + "***" + key[-4:]


# 配置项元数据（设置页用）
CONFIG_FIELDS = [
    {
        "section": "转写引擎",
        "items": [
            {"key": "WHISPER_MODEL", "label": "faster-whisper 模型", "type": "text", "default": "base"},
            {"key": "MLX_WHISPER_MODEL", "label": "mlx-whisper 模型（Apple Silicon）", "type": "text", "default": "large-v3-turbo"},
            {"key": "QWEN3_ASR_MODEL", "label": "Qwen3-ASR 模型（0.6b/1.7b/flash）", "type": "text", "default": "0.6b"},
            {"key": "QWEN3_ASR_ALIGN", "label": "Qwen3 字级时间戳（1/0，需对齐模型）", "type": "text", "default": "0"},
            {"key": "DASHSCOPE_API_KEY", "label": "阿里云百炼 API Key（qwen3-asr-flash 云端）", "type": "password", "default": ""},
        ],
    },
    {
        "section": "本地 Whisper",
        "items": [
            {"key": "WHISPER_MODEL_DIR", "label": "模型目录", "type": "text", "default": "~/.cache/whisper"},
        ],
    },
    {
        "section": "硅基流动（关键帧 + VLM + LLM 摘要）",
        "items": [
            {"key": "SILICONFLOW_API_KEY", "label": "API Key", "type": "password", "default": ""},
            {"key": "SILICONFLOW_BASE", "label": "API 地址", "type": "text", "default": "https://api.siliconflow.cn/v1"},
            {"key": "LLM_MODEL", "label": "LLM 模型", "type": "text", "default": "deepseek-ai/DeepSeek-V3"},
            {"key": "VLM_MODEL", "label": "VLM 模型", "type": "text", "default": "Qwen/Qwen3-VL-32B-Instruct"},
        ],
    },
    {
        "section": "火山方舟（豆包视频理解）",
        "items": [
            {"key": "ARK_API_KEY", "label": "API Key", "type": "password", "default": ""},
            {"key": "ARK_BASE", "label": "API 地址", "type": "text", "default": "https://ark.cn-beijing.volces.com/api/v3"},
            {"key": "ARK_VIDEO_ENDPOINT", "label": "视频模型 Endpoint ID", "type": "text", "default": ""},
        ],
    },
    {
        "section": "蒸馏模式（第三个模式用的 LLM）",
        "items": [
            {"key": "DISTILL_LLM_BASE", "label": "API 地址（OpenAI 兼容，留空自动回落）", "type": "text", "default": ""},
            {"key": "DISTILL_LLM_KEY", "label": "API Key", "type": "password", "default": ""},
            {"key": "DISTILL_LLM_MODEL", "label": "模型名", "type": "text", "default": ""},
            {"key": "DISTILL_THINKING", "label": "思维链（auto/off/on）", "type": "text", "default": "auto"},
            {"key": "DISTILL_HOTWORDS", "label": "热词纠正（错=对,错2=对2）", "type": "text", "default": ""},
        ],
    },
    {
        "section": "Obsidian",
        "items": [
            {"key": "OBSIDIAN_VAULT", "label": "Vault 路径", "type": "text", "default": "~/Documents/Obsidian Vault"},
            {"key": "OBSIDIAN_FOLDER", "label": "默认导出目录", "type": "text", "default": "01_内容创作/视频笔记"},
        ],
    },
    {
        "section": "路径",
        "items": [
            {"key": "CACHE_DIR", "label": "缓存目录", "type": "text", "default": "./cache"},
            {"key": "OUTPUT_DIR", "label": "输出目录", "type": "text", "default": "./output"},
        ],
    },
]
