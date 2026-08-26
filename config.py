"""
config.py — 统一配置管理
优先级：GUI 设置（storage.user） > .env > 默认值
"""

import os
import json
from pathlib import Path


BASE_DIR = Path(__file__).parent
ENV_PATH = BASE_DIR / ".env"

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
WHISPER_MODEL = _get("WHISPER_MODEL", "small")
WHISPER_CLI = _get("WHISPER_CLI", "whisper-cli")
WHISPER_MODEL_DIR = Path(_get("WHISPER_MODEL_DIR", str(Path.home() / ".cache" / "whisper"))).expanduser()

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


def all_config_dict() -> dict:
    """返回所有配置（用于设置页显示）"""
    return {
        "WHISPER_MODEL": WHISPER_MODEL,
        "SILICONFLOW_API_KEY": mask_key(SILICONFLOW_API_KEY),
        "SILICONFLOW_BASE": SILICONFLOW_BASE,
        "LLM_MODEL": LLM_MODEL,
        "VLM_MODEL": VLM_MODEL,
        "ARK_API_KEY": mask_key(ARK_API_KEY),
        "ARK_BASE": ARK_BASE,
        "ARK_VIDEO_ENDPOINT": ARK_VIDEO_ENDPOINT,
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
        "section": "本地 Whisper",
        "items": [
            {"key": "WHISPER_MODEL", "label": "Whisper 模型", "type": "text", "default": "small"},
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
