"""
v2t/distill.py — 第三模式：蒸馏（Distill）

输入：一个文件夹（里面可以有子文件夹、任意数量的视频、重复文件、同一门课的多集）
输出：一份"这批视频到底讲了什么"的完整认知包

固定八阶段（方法本身，不随视频变化）：
  S0 采集  递归扫描 + 元信息 + 清洗标题
  S1 去重  内容哈希 → 时长+画面指纹 → 逐字稿相似度（三层）
  S2 转写  逐视频 ASR（复用 v2t.asr，带缓存）+ 可选热词纠正
  S3 合并  段落切分 + 跨视频语句级去重 + 合并逐字稿
  S4 深读  单视频结构化拆解（讲了什么/步骤/概念/数字/证据）
  S5 综合  主题图谱 + 知识单元合并 + 冲突检测 + 学习路径
  S6 抽象  方法论：L0 事实 → L1 规律 → L2 方法 → L3 心智模型
  S7 逆向  若涉及产品：架构 + 商业模式 + 复刻路径
  S8 产出  00_总览 / 01_逐字稿合并 / 02_方法论 / 03_产品逆向 / 04_证据索引

设计约束：
  - 每个阶段结果落盘到 _work/，支持 --resume 断点续跑（1.6 小时视频不会白跑）。
  - LLM 不可用或调用失败时降级为规则结果，管线不崩。
  - 全流程只用一条 OpenAI 兼容协议（硅基流动 / 火山方舟 / 任意兼容端点）。
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

import config as cfg
from v2t import ffmpeg as ff
from v2t import distill_prompts as P
from v2t import asr as asr_mod

PIPELINE_VERSION = "1.0"

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".flv", ".webm", ".m4v", ".wmv", ".ts"}

# 去重 / 合并阈值（写死在这里，保证同一批视频每次跑出同样的结论）
THRESHOLDS = {
    "near_dup_hamming": 6,      # 画面 dHash 汉明距离 ≤ 6 视为同一画面
    "near_dup_duration": 0.02,  # 时长相差 ≤ 2% 才算"疑似同源"
    "content_dup_jaccard": 0.80,  # 整条视频逐字稿相似度 ≥ 0.8 → 内容重复
    "segment_dup_contain": 0.85,  # 单段语句被已有内容包含 ≥ 85% → 丢弃
    "shingle": 5,               # 中文 5-gram 指纹
    "min_segment_chars": 4,     # 太短的语气词不参与去重
}

# 明显无信息量的口播噪声
BOILERPLATE_STRICT = [r"^[嗯啊哦噢唉诶呀吧哈嘿]+$", r"^\W*$"]
BOILERPLATE_CTA = [r"点赞|三连|转发|收藏|评论区|私信|字幕组|未经允许|版权所有|"
                   r"关注公众号|点个关注|关注我|关注一下|加我微信"]

# 产品信号词：出现越多，越可能是"在讲一个产品"
PRODUCT_SIGNALS = [
    "会员", "套餐", "充值", "付费", "订阅", "价格", "元/月", "字数包",
    "额度", "积分", "消耗", "购买", "试用", "免费版", "升级", "开会员",
    "界面", "按钮", "面板", "点击", "设置", "功能", "后台", "账号",
]

# 数字抽取（价格 / 字数 / 比例 / 次数 / 时长 / 倍数）
NUMBER_PATTERNS = [
    ("价格", r"(\d+(?:\.\d+)?)\s*(?:元|块|块钱|RMB|人民币)"),
    ("字数", r"(\d+(?:\.\d+)?)\s*(?:万)?字"),
    ("次数", r"(\d+)\s*(?:次|条|篇|章|个)"),
    ("倍数", r"(\d+(?:\.\d+)?)\s*倍"),
    ("比例", r"(\d+(?:\.\d+)?)\s*%"),
    ("时长", r"(\d+(?:\.\d+)?)\s*(?:分钟|小时|天|个月|年)"),
    ("额度", r"(\d+)\s*(?:点|积分|token|Token)"),
]


# ============================================================
# 小工具
# ============================================================

def mmss(seconds) -> str:
    try:
        s = int(float(seconds))
    except (TypeError, ValueError):
        s = 0
    m, s = divmod(max(0, s), 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def hms(seconds) -> str:
    try:
        s = int(float(seconds))
    except (TypeError, ValueError):
        s = 0
    h, rem = divmod(max(0, s), 3600)
    m, s = divmod(rem, 60)
    return f"{h}小时{m}分" if h else f"{m}分{s}秒"


def ensure_dir(p: Path) -> Path:
    """建目录。某些网络盘/沙箱文件系统上 mkdir(exist_ok=True) 仍会抛 EEXIST，
    这里统一兜住：只要最后它确实是个目录就算成功。"""
    p = Path(p)
    try:
        p.mkdir(parents=True, exist_ok=True)
    except FileExistsError:
        if not p.is_dir():
            raise
    return p


def safe_name(name: str, max_len: int = 60) -> str:
    """文件名安全化：保留中文，去掉路径分隔符和奇怪字符"""
    s = re.sub(r'[\\/:*?"<>|\n\r\t]', "_", str(name))
    s = re.sub(r"\s+", "_", s.strip())
    s = s.strip("._")
    return s[:max_len] or "untitled"


def clean_title(filename: str) -> str:
    """把课程平台的长文件名洗成人话标题

    '星月写作教程 - 【星月写作教程】Ai提示词_提示词的使用教程·百万字AI小说也写不崩·...'
      → 'Ai提示词_提示词的使用教程'
    """
    s = Path(filename).stem
    # 1. 去掉平台前缀 "XXX教程 - "
    s = re.sub(r"^\s*[^【\-—]{0,20}(教程|课程)\s*[-—–]\s*", "", s)
    # 2. 去掉【课程名】标记，剩下的才是这一集的主题
    stripped = re.sub(r"【[^】]*】", "", s).strip(" -_·，,.")
    if len(norm_text(stripped)) >= 4:
        s = stripped
    else:
        brackets = re.findall(r"【([^】]+)】", s)
        if brackets:
            s = max(brackets, key=len)
    # 3. 砍掉营销尾巴（· 之后、第一个逗号/感叹号之后都是引流话术）
    s = re.split(r"[·｜|]", s)[0]
    s = re.split(r"[，,！!]", s)[0]
    s = re.sub(r"\s+", " ", s).strip(" -_·，,.")
    return s or Path(filename).stem


def parse_hotwords(spec: str) -> list:
    """解析热词纠正表："错词=正词,错词2=正词2"

    中文 ASR 对专有名词（产品名/人名/术语）系统性误听，靠换模型解决成本太高，
    用一张纠错表在转写后统一修，成本为零。
    """
    pairs = []
    for part in (spec or "").split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        wrong, right = part.split("=", 1)
        wrong, right = wrong.strip(), right.strip()
        if wrong and right and wrong != right:
            pairs.append((wrong, right))
    # 长词优先，避免 "新约" 先替换掉 "新约写作" 的一部分
    pairs.sort(key=lambda x: -len(x[0]))
    return pairs


def apply_hotwords(videos: list, pairs: list) -> int:
    """把纠错表应用到已转写的 segments 上（幂等）"""
    if not pairs:
        return 0
    fixed = 0
    for v in videos:
        for seg in v["segments"]:
            text = seg["text"]
            for wrong, right in pairs:
                if wrong in text:
                    fixed += text.count(wrong)
                    text = text.replace(wrong, right)
            seg["text"] = text
        v["chars"] = sum(len(x["text"]) for x in v["segments"])
    return fixed


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for blk in iter(lambda: f.read(chunk), b""):
            h.update(blk)
    return h.hexdigest()


def norm_text(text: str) -> str:
    """归一化：只留中日韩/字母/数字，小写"""
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]", "", (text or "").lower())


def shingles(text: str, k: int = THRESHOLDS["shingle"]) -> set:
    n = norm_text(text)
    if len(n) < k:
        return {n} if n else set()
    return {n[i:i + k] for i in range(len(n) - k + 1)}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def containment(part: set, whole: set) -> float:
    if not part:
        return 0.0
    return len(part & whole) / len(part)


def dhash64(img_path: Path) -> int:
    """感知哈希（dHash 8x8）：容忍压缩、分辨率、轻微裁剪"""
    try:
        from PIL import Image
        with Image.open(img_path) as im:
            im = im.convert("L").resize((9, 8), Image.Resampling.LANCZOS)
            px = list(im.getdata())
    except Exception:
        return 0
    bits = 0
    for row in range(8):
        for col in range(8):
            left = px[row * 9 + col]
            right = px[row * 9 + col + 1]
            bits = (bits << 1) | (1 if left > right else 0)
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def parse_json(text: str) -> dict:
    """从 LLM 回复里抠出 JSON，容忍代码块和前后废话"""
    if not text:
        raise ValueError("空回复")
    s = text.strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
        s = re.sub(r"\s*```$", "", s)
    start, end = s.find("{"), s.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("回复里没有 JSON 对象")
    body = s[start:end + 1]
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        # 常见毛病：中文引号、尾逗号、换行未转义
        body = body.replace("“", '"').replace("”", '"')
        body = re.sub(r",\s*([}\]])", r"\1", body)
        return json.loads(body)


# ============================================================
# LLM 客户端（OpenAI 兼容：硅基流动 / 火山方舟 / 其它）
# ============================================================

class LLM:
    """统一 LLM 入口。不可用时 available=False，调用返回 None（管线降级）。"""

    def __init__(self, log=print, enabled: bool = True):
        self.log = log
        self.calls = 0
        self.errors = 0
        if not enabled:
            self.base = self.key = self.model = ""
            self.provider = "disabled"
            self.available = False
            return
        self.base, self.key, self.model, self.provider = self._resolve()
        self.available = bool(self.base and self.key and self.model)
        self.last_finish = ""  # 上一次调用的 finish_reason（length = 被截断）

    @staticmethod
    def _resolve():
        # 1) 蒸馏专用配置
        base = cfg._get("DISTILL_LLM_BASE", "")
        key = cfg._get("DISTILL_LLM_KEY", "")
        model = cfg._get("DISTILL_LLM_MODEL", "")
        if base and key and model:
            return base.rstrip("/"), key, model, "distill"

        # 2) 硅基流动
        if cfg.SILICONFLOW_API_KEY:
            return (cfg.SILICONFLOW_BASE.rstrip("/"), cfg.SILICONFLOW_API_KEY,
                    cfg.LLM_MODEL, "siliconflow")

        # 3) 火山方舟（方舟的 endpoint id 也能直接当 model 用）
        if cfg.ARK_API_KEY and cfg.ARK_VIDEO_ENDPOINT:
            return (cfg.ARK_BASE.rstrip("/"), cfg.ARK_API_KEY,
                    cfg.ARK_VIDEO_ENDPOINT, "ark")

        return "", "", "", "none"

    def chat(self, prompt: str, max_tokens: int = 4000, temperature: float = 0.2,
             retries: int = 3, thinking: bool | None = None) -> str | None:
        """thinking: None=用服务端默认；False=关掉思维链（快 3-5 倍）；True=强制开启"""
        if not self.available:
            return None
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        mode = self._thinking_mode(thinking)
        if mode is not None and self.provider == "ark":
            payload["thinking"] = {"type": "enabled" if mode else "disabled"}
        body = json.dumps(payload).encode("utf-8")

        # 超时随输出预算放大：慢端点上 8000 token 可能要 10 分钟以上
        timeout = max(300, int(180 + max_tokens * 0.15))
        for attempt in range(1, retries + 1):
            req = urllib.request.Request(
                f"{self.base}/chat/completions",
                data=body,
                headers={"Content-Type": "application/json",
                         "Authorization": f"Bearer {self.key}"},
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = json.loads(resp.read())
                self.calls += 1
                choice = data["choices"][0]
                self.last_finish = choice.get("finish_reason") or ""
                if self.last_finish == "length":
                    self.log("    ! 输出被 max_tokens 截断")
                return choice["message"]["content"]
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode()[:200]
                except Exception:
                    pass
                self.errors += 1
                if e.code in (400, 401, 403, 404):
                    self.log(f"    ✗ LLM 拒绝（{e.code}）: {detail}")
                    return None
                if attempt == retries:
                    self.log(f"    ✗ LLM 失败（{e.code}）: {detail}")
                    return None
                time.sleep(2 * attempt)
            except Exception as e:
                self.errors += 1
                if attempt == retries:
                    self.log(f"    ✗ LLM 异常: {e}")
                    return None
                time.sleep(2 * attempt)
        return None

    def _thinking_mode(self, want: bool | None) -> bool | None:
        """全局配置优先：DISTILL_THINKING=off/on 覆盖各阶段默认"""
        pref = (cfg._get("DISTILL_THINKING", "auto") or "auto").lower()
        if pref in ("off", "false", "0", "disabled"):
            return False
        if pref in ("on", "true", "1", "enabled"):
            return True
        return want

    def chat_json(self, prompt: str, schema_hint: dict | None = None,
                  max_tokens: int = 4000, retries: int = 2,
                  thinking: bool | None = None) -> dict | None:
        """要 JSON。第一次解析失败就带着错误提示再要一次。"""
        text = self.chat(prompt, max_tokens=max_tokens, thinking=thinking)
        if not text:
            return None
        err = ""
        try:
            return parse_json(text)
        except Exception as e:
            err = str(e)
            self.log(f"    ! JSON 解析失败（{err}），重试一次")
        hint = ("请严格只输出一个 JSON 对象，不要代码块，不要注释，不要尾逗号。")
        if self.last_finish == "length":
            hint = ("上一次输出因为太长被截断了。这次请压缩：每个数组最多 5 项，"
                    "每条描述不超过 40 字，务必保证 JSON 括号完整闭合。")
        retry_prompt = prompt + "\n\n上一次你的输出不是合法 JSON（错误：" + err + "）。" + hint
        text = self.chat(retry_prompt, max_tokens=max_tokens, retries=retries,
                         thinking=thinking)
        if not text:
            return None
        try:
            return parse_json(text)
        except Exception:
            return None


# ============================================================
# S0 采集
# ============================================================

def scan_folder(folder: Path, recursive: bool = True) -> list:
    """递归扫描视频文件，跳过 macOS 资源分叉和隐藏文件"""
    folder = Path(folder).expanduser().resolve()
    if not folder.exists():
        raise FileNotFoundError(f"找不到文件夹: {folder}")

    files = []
    it = folder.rglob("*") if recursive else folder.glob("*")
    for p in it:
        if not p.is_file():
            continue
        if p.name.startswith("._") or p.name.startswith("."):
            continue
        if p.suffix.lower() not in VIDEO_EXTS:
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        if size < 512 * 1024:  # 太小的多半是坏文件/占位
            continue
        files.append({"path": p, "name": p.name, "size": size,
                      "rel": str(p.relative_to(folder))})

    files.sort(key=lambda x: (x["rel"].lower(), x["name"]))
    return files


def enrich_videos(files: list, log=print) -> list:
    """补元信息：时长/宽高/音轨 + 内容哈希 + 画面指纹"""
    videos = []
    for i, f in enumerate(files, 1):
        info = ff.probe(f["path"])
        vid = f"V{i:02d}"
        videos.append({
            "id": vid,
            "path": f["path"],
            "rel_path": f["rel"],
            "name": f["name"],
            "title": clean_title(f["name"]),
            "size": f["size"],
            "duration": round(info["duration"], 2),
            "width": info["width"],
            "height": info["height"],
            "has_audio": info["has_audio"],
            "sha256": "",
            "frame_hashes": [],
            "duplicate_of": None,
            "duplicate_reason": "",
            "segments": [],
            "chars": 0,
            "analysis": None,
        })
        log(f"  [{i}/{len(files)}] {vid} {videos[-1]['title'][:40]}  {hms(info['duration'])}")
    return videos


# ============================================================
# S1 去重（三层）
# ============================================================

def compute_fingerprints(videos: list, work_dir: Path, log=print) -> None:
    """内容哈希 + 3 帧画面指纹"""
    fp_dir = ensure_dir(work_dir / "frames")
    for v in videos:
        if v["sha256"]:
            continue
        v["sha256"] = sha256_file(v["path"])
        if v["duration"] <= 0:
            continue
        hashes = []
        for j, ratio in enumerate((0.15, 0.5, 0.85)):
            ts = v["duration"] * ratio
            out = fp_dir / f"{v['id']}_{j}.jpg"
            if ff.grab_frame(v["path"], ts, out):
                hashes.append(dhash64(out))
        v["frame_hashes"] = hashes
    log(f"  ✓ 指纹完成（{len(videos)} 条）")


def dedupe_files(videos: list, log=print) -> dict:
    """第一层：完全相同的文件；第二层：时长+画面几乎一样的文件"""
    groups = {"exact": [], "near": []}

    # L1 内容哈希
    by_hash = {}
    for v in videos:
        by_hash.setdefault(v["sha256"], []).append(v)
    for h, group in by_hash.items():
        if len(group) < 2:
            continue
        keep = max(group, key=lambda x: x["size"])
        losers = [g for g in group if g is not keep]
        for g in losers:
            g["duplicate_of"] = keep["id"]
            g["duplicate_reason"] = "文件内容完全相同（SHA-256 一致）"
        groups["exact"].append({
            "sha256": h[:16],
            "keep": keep["id"],
            "dropped": [g["id"] for g in losers],
            "reason": "SHA-256 完全一致",
        })

    # L2 时长 + 画面指纹
    alive = [v for v in videos if not v["duplicate_of"]]
    for i, a in enumerate(alive):
        if a["duplicate_of"]:
            continue
        for b in alive[i + 1:]:
            if b["duplicate_of"] or a["duplicate_of"]:
                continue
            if a["duration"] <= 0 or b["duration"] <= 0:
                continue
            dur_ratio = abs(a["duration"] - b["duration"]) / max(a["duration"], b["duration"])
            if dur_ratio > THRESHOLDS["near_dup_duration"]:
                continue
            if not a["frame_hashes"] or not b["frame_hashes"]:
                continue
            dists = [hamming(x, y) for x, y in zip(a["frame_hashes"], b["frame_hashes"])]
            avg = sum(dists) / len(dists)
            if avg <= THRESHOLDS["near_dup_hamming"]:
                keep, drop = (a, b) if a["size"] >= b["size"] else (b, a)
                drop["duplicate_of"] = keep["id"]
                drop["duplicate_reason"] = (
                    f"时长差 {dur_ratio*100:.1f}%，三帧画面平均汉明距离 {avg:.1f}（同一内容的不同压制）"
                )
                groups["near"].append({
                    "keep": keep["id"],
                    "dropped": [drop["id"]],
                    "avg_hamming": round(avg, 2),
                    "duration_delta": round(dur_ratio, 4),
                    "reason": "时长接近 + 画面指纹一致",
                })

    dropped = [v for v in videos if v["duplicate_of"]]
    log(f"  ✓ 文件级去重：完全重复 {len(groups['exact'])} 组，"
        f"近似重复 {len(groups['near'])} 组，丢弃 {len(dropped)} 条")
    return groups


# ============================================================
# S2 转写
# ============================================================

def transcribe_videos(videos: list, engine: str = "faster-whisper",
                      model_size: str | None = None, log=print) -> None:
    """逐视频转写（v2t.asr 自带缓存，重跑不重复算）"""
    for i, v in enumerate(videos, 1):
        if v["segments"]:
            continue
        if not v["has_audio"]:
            log(f"  [{i}/{len(videos)}] {v['id']} 无音轨，跳过")
            continue
        cache_key = v["sha256"][:12]
        audio = cfg.CACHE_DIR / f"{cache_key}_audio.wav"
        log(f"  [{i}/{len(videos)}] {v['id']} 转写 {hms(v['duration'])} ...")
        try:
            if not audio.exists():
                ff.extract_audio(v["path"], audio)
            segments = asr_mod.transcribe(audio, cache_key, engine, model_size=model_size)
        except Exception as e:
            log(f"    ✗ 转写失败: {e}")
            segments = []
        v["segments"] = [
            {"start": round(float(s.get("start", 0)), 2),
             "end": round(float(s.get("end", 0)), 2),
             "text": (s.get("text") or "").strip()}
            for s in (segments or []) if (s.get("text") or "").strip()
        ]
        v["chars"] = sum(len(s["text"]) for s in v["segments"])
        log(f"    ✓ {len(v['segments'])} 段 / {v['chars']} 字")


def dedupe_content(videos: list, log=print) -> dict:
    """第三层：整条视频逐字稿相似度（同一门课被重录/切片的情况）"""
    groups = []
    alive = [v for v in videos if not v["duplicate_of"] and v["segments"]]
    shingle_map = {v["id"]: shingles("".join(s["text"] for s in v["segments"])) for v in alive}

    for i, a in enumerate(alive):
        if a["duplicate_of"]:
            continue
        for b in alive[i + 1:]:
            if b["duplicate_of"]:
                continue
            score = jaccard(shingle_map[a["id"]], shingle_map[b["id"]])
            if score < THRESHOLDS["content_dup_jaccard"]:
                continue
            keep, drop = (a, b) if a["chars"] >= b["chars"] else (b, a)
            drop["duplicate_of"] = keep["id"]
            drop["duplicate_reason"] = f"逐字稿相似度 {score:.0%}（内容重复）"
            groups.append({
                "keep": keep["id"],
                "dropped": [drop["id"]],
                "similarity": round(score, 3),
                "reason": "逐字稿高度相似，保留信息量更大的一条",
            })
            log(f"  · {a['id']} ≈ {b['id']}（{score:.0%}）→ 保留 {keep['id']}")

    log(f"  ✓ 内容级去重：{len(groups)} 组")
    return {"content": groups}


# ============================================================
# S3 合并（语句级去重 + 段落化）
# ============================================================

def is_boilerplate(text: str) -> bool:
    """噪声判定：纯语气词，或短句里的求关注/版权声明（长句里的「关注」不算）"""
    t = (text or "").strip()
    n = norm_text(t)
    if len(n) < 2:
        return True
    if any(re.search(p, t) for p in BOILERPLATE_STRICT):
        return True
    if len(n) < 30 and any(re.search(p, t) for p in BOILERPLATE_CTA):
        return True
    return False


def merge_corpus(videos: list, log=print) -> dict:
    """把去重后的所有语句合成一份语料，顺手做跨视频语句级去重

    返回 {"segments": [...], "stats": {...}, "redundant_by_video": {...}}
    """
    kept = []
    seen = set()
    stats = {"total": 0, "kept": 0, "dropped_repeat": 0, "dropped_boilerplate": 0}
    redundant_by_video = {}

    ordered = sorted([v for v in videos if not v["duplicate_of"] and v["segments"]],
                     key=lambda x: x["rel_path"].lower())

    for v in ordered:
        redundant_by_video[v["id"]] = 0
        for seg in v["segments"]:
            text = seg["text"].strip()
            stats["total"] += 1
            if is_boilerplate(text):
                stats["dropped_boilerplate"] += 1
                continue
            sh = shingles(text)
            if sh and containment(sh, seen) >= THRESHOLDS["segment_dup_contain"]:
                stats["dropped_repeat"] += 1
                redundant_by_video[v["id"]] += 1
                continue
            seen |= sh
            kept.append({
                "video_id": v["id"],
                "video_title": v["title"],
                "start": seg["start"],
                "end": seg["end"],
                "text": text,
            })
            stats["kept"] += 1

    paragraphs = group_paragraphs(kept)
    stats["paragraphs"] = len(paragraphs)
    stats["chars_kept"] = sum(len(p["text"]) for p in paragraphs)
    log(f"  ✓ 合并：{stats['total']} 句 → 保留 {stats['kept']} 句"
        f"（重复 {stats['dropped_repeat']}，噪声 {stats['dropped_boilerplate']}）→ {stats['paragraphs']} 段")
    return {"segments": kept, "paragraphs": paragraphs,
            "stats": stats, "redundant_by_video": redundant_by_video}


def group_paragraphs(segments: list, gap: float = 1.6, max_chars: int = 200) -> list:
    """按停顿和长度把句子并成段落（逐字稿可读性）"""
    out = []
    for seg in segments:
        if out:
            last = out[-1]
            same_video = last["video_id"] == seg["video_id"]
            close = seg["start"] - last["end"] <= gap
            short = len(last["text"]) < max_chars
            ends_ok = not re.search(r"[。！？!?]$", last["text"])
            if same_video and close and short and ends_ok:
                joiner = "" if re.search(r"[，、；：,;:]$", last["text"]) else "，"
                last["text"] = last["text"].rstrip("，、；：,;:") + joiner + seg["text"]
                last["end"] = seg["end"]
                continue
        out.append({
            "video_id": seg["video_id"],
            "video_title": seg["video_title"],
            "start": seg["start"],
            "end": seg["end"],
            "text": seg["text"],
        })
    return out


# ============================================================
# 数字抽取（喂给产品逆向）
# ============================================================

def extract_numbers(videos: list) -> list:
    found = []
    for v in videos:
        if v["duplicate_of"]:
            continue
        for seg in v["segments"]:
            t = seg["text"]
            for label, pat in NUMBER_PATTERNS:
                for m in re.finditer(pat, t):
                    found.append({
                        "kind": label,
                        "value": m.group(0),
                        "context": t[max(0, m.start() - 18): m.end() + 18],
                        "video_id": v["id"],
                        "time": mmss(seg["start"]),
                    })
    # 去重（同值同视频只留一条）
    seen, out = set(), []
    for f in found:
        key = (f["kind"], f["value"], f["video_id"])
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


# ============================================================
# S4 单视频深读
# ============================================================

def transcript_text(video: dict, max_chars: int = 12000) -> str:
    lines = [f"[{mmss(s['start'])}] {s['text']}" for s in video["segments"]]
    text = "\n".join(lines)
    if len(text) > max_chars:
        text = text[: int(max_chars * 0.6)] + "\n...[中间省略]...\n" + text[-int(max_chars * 0.35):]
    return text


def analyze_video(video: dict, llm: LLM, log=print) -> dict:
    """单视频拆解。长视频分块，再合并。"""
    if not video["segments"]:
        return fallback_analysis(video, "无逐字稿")

    prompt = P.ANALYZE_VIDEO.format(
        schema=json.dumps(P.ANALYZE_VIDEO_SCHEMA, ensure_ascii=False, indent=2),
        video_id=video["id"],
        name=video["title"],
        duration=hms(video["duration"]),
        frames="（本模式以逐字稿为主，画面线索见 04_证据索引）",
        transcript=transcript_text(video),
    )
    # 结构化抽取不需要思维链：关掉快 3-5 倍，质量几乎无损
    # 输出预算按时长给：长视频步骤多，固定 3000 会被截断
    budget = min(6000, 2500 + int(video["duration"] / 60) * 150)
    data = llm.chat_json(prompt, P.ANALYZE_VIDEO_SCHEMA,
                         max_tokens=budget, thinking=False)
    if not data:
        return fallback_analysis(video, "LLM 不可用")
    data["_source"] = "llm"
    return data


def fallback_analysis(video: dict, reason: str) -> dict:
    """LLM 不可用时的降级结果：至少给出章节切分和关键句"""
    segs = video["segments"]
    sections, step = [], 6
    for i in range(0, len(segs), step):
        chunk = segs[i:i + step]
        if not chunk:
            continue
        sections.append({
            "title": chunk[0]["text"][:24],
            "start": mmss(chunk[0]["start"]),
            "end": mmss(chunk[-1]["end"]),
            "summary": "".join(s["text"] for s in chunk)[:120],
        })
    return {
        "gist": (segs[0]["text"][:60] if segs else video["title"]),
        "video_type": "未判定",
        "audience": "",
        "premise": "",
        "sections": sections,
        "key_points": [],
        "steps": [],
        "concepts": [],
        "rules_and_numbers": [],
        "ui_evidence": [],
        "quotes": [{"time": mmss(s["start"]), "text": s["text"][:80]}
                   for s in sorted(segs, key=lambda x: -len(x["text"]))[:5]],
        "pitfalls": [],
        "claims": [],
        "open_questions": [],
        "one_line_takeaway": "",
        "_source": f"fallback（{reason}）",
    }


def analyses_digest(videos: list, max_chars: int = 26000) -> str:
    """把单视频拆解压成给上层用的紧凑文本"""
    blocks = []
    for v in videos:
        a = v.get("analysis") or {}
        if not a:
            continue
        parts = [f"### {v['id']} · {v['title']}（{hms(v['duration'])}）",
                 f"讲了什么：{a.get('gist', '')}",
                 f"类型：{a.get('video_type', '')}｜受众：{a.get('audience', '')}"]
        if a.get("premise"):
            parts.append(f"前提：{a['premise']}")
        if a.get("sections"):
            parts.append("章节：" + " / ".join(
                f"[{s.get('start','')}]{s.get('title','')}" for s in a["sections"][:8]))
        if a.get("steps"):
            parts.append("步骤：" + "；".join(
                f"{s.get('order','')}.{s.get('action','')}"
                f"（{s.get('where','')}；{s.get('detail','')[:40]}）"
                for s in a["steps"][:12]))
        if a.get("key_points"):
            parts.append("观点：" + "；".join(k.get("point", "") for k in a["key_points"][:8]))
        if a.get("concepts"):
            parts.append("概念：" + "；".join(
                f"{c.get('name','')}={c.get('definition','')[:40]}" for c in a["concepts"][:8]))
        if a.get("rules_and_numbers"):
            parts.append("规则/数字：" + "；".join(
                f"{r.get('item','')}:{r.get('value','')}" for r in a["rules_and_numbers"][:10]))
        if a.get("ui_evidence"):
            parts.append("界面证据：" + "；".join(a["ui_evidence"][:6]))
        if a.get("pitfalls"):
            parts.append("坑：" + "；".join(a["pitfalls"][:5]))
        if a.get("claims"):
            parts.append("主张：" + "；".join(a["claims"][:5]))
        blocks.append("\n".join(parts))

    text = "\n\n".join(blocks)
    if len(text) > max_chars:
        text = text[: int(max_chars * 0.7)] + "\n...[部分视频拆解省略]...\n" + text[-int(max_chars * 0.25):]
    return text


# ============================================================
# S5 跨视频综合
# ============================================================

def topic_clusters(videos: list, top_n: int = 12) -> list:
    """规则聚类：先抽每个视频的高频词，再按词重合度归并（不依赖 LLM，确定性）"""
    stop = set("这个那个就是然后所以因为但是可以我们你们他们一个什么怎么这样那样"
               "时候如果还是不是没有现在知道大家觉得东西问题地方这里那里".split())
    stop |= {"的", "了", "是", "在", "我", "你", "他", "它", "和", "就", "都", "也", "有",
             "不", "人", "上", "中", "个", "这", "那", "要", "会", "到", "对", "说"}

    def top_terms(text: str, k: int = 18) -> list:
        grams = re.findall(r"[\u4e00-\u9fff]{2,4}", norm_text(text))
        freq = {}
        for g in grams:
            if g in stop or len(g) < 2:
                continue
            freq[g] = freq.get(g, 0) + 1
        return [w for w, _ in sorted(freq.items(), key=lambda x: -x[1])[:k]]

    per_video = []
    for v in videos:
        if v["duplicate_of"] or not v["segments"]:
            continue
        per_video.append({"video_id": v["id"], "terms": top_terms("".join(s["text"] for s in v["segments"]))})

    clusters = []
    for item in per_video:
        placed = False
        for c in clusters:
            if len(set(item["terms"]) & set(c["terms"])) >= 4:
                c["terms"] = list(dict.fromkeys(c["terms"] + item["terms"]))[:24]
                c["covered_by"].append(item["video_id"])
                placed = True
                break
        if not placed:
            clusters.append({"terms": item["terms"], "covered_by": [item["video_id"]]})

    clusters.sort(key=lambda c: -len(c["covered_by"]))
    return clusters[:top_n]


def synthesize(videos: list, corpus: dict, llm: LLM, log=print) -> dict:
    """跨视频综合：主题图谱 + 知识单元 + 冲突 + 学习路径"""
    active = [v for v in videos if not v["duplicate_of"] and v["analysis"]]
    total_dur = sum(v["duration"] for v in active)
    prompt = P.SYNTHESIZE.format(
        schema=json.dumps(P.SYNTHESIZE_SCHEMA, ensure_ascii=False, indent=2),
        n_videos=len(active),
        duration=hms(total_dur),
        analyses=analyses_digest(active),
    )
    data = llm.chat_json(prompt, P.SYNTHESIZE_SCHEMA, max_tokens=8000, thinking=False)
    if not data:
        data = {
            "corpus_gist": f"{len(active)} 条视频，共 {hms(total_dur)}，已合并逐字稿 {corpus['stats']['chars_kept']} 字。",
            "what_this_is": "",
            "topics": [],
            "knowledge_units": [],
            "redundancy": {"repeated_intros": [], "repeated_content": [], "unique_value": []},
            "learning_path": [],
            "conflicts": [],
            "missing_pieces": [],
            "master_summary": "LLM 不可用，未生成综合结论。逐字稿与单视频拆解仍完整保存在本目录。",
            "_source": "fallback",
        }
    # 规则聚类结果兜底补全主题
    if not data.get("topics"):
        data["topics"] = [{"name": "关键词簇", "weight": 3,
                           "summary": "、".join(c["terms"][:6]),
                           "covered_by": c["covered_by"], "key_insight": "", "gaps": []}
                          for c in topic_clusters(active)]
    return data


# ============================================================
# S6 方法论
# ============================================================

def methodology(videos: list, synthesis: dict, llm: LLM, log=print) -> dict:
    active = [v for v in videos if not v["duplicate_of"] and v["analysis"]]
    ku = "\n".join(
        f"- {u.get('unit', '')}：{u.get('detail', '')}"
        for u in (synthesis.get("knowledge_units") or [])[:60]
    ) or "（无）"
    prompt = P.METHODOLOGY.format(
        schema=json.dumps(P.METHODOLOGY_SCHEMA, ensure_ascii=False, indent=2),
        analyses=analyses_digest(active, max_chars=20000),
        knowledge_units=ku,
    )
    # 默认关思维链：慢端点上 8000 token + CoT 会超时。要质量就 DISTILL_THINKING=on
    data = llm.chat_json(prompt, P.METHODOLOGY_SCHEMA, max_tokens=8000, thinking=False)
    if not data:
        data = {
            "master_method": {},
            "method_cards": [],
            "mental_models": [],
            "decision_table": [],
            "quality_bar": [],
            "levels": {"L0_facts": [], "L1_rules": [], "L2_method": [], "L3_model": []},
            "_source": "fallback",
        }
    return data


# ============================================================
# S7 产品逆向
# ============================================================

def product_signal(videos: list) -> dict:
    text = "".join(s["text"] for v in videos if not v["duplicate_of"] for s in v["segments"])
    hits = {k: text.count(k) for k in PRODUCT_SIGNALS}
    hits = {k: c for k, c in hits.items() if c}
    score = sum(hits.values())
    top = sorted(hits.items(), key=lambda x: -x[1])[:8]
    return {"score": score, "hits": hits, "top": top,
            "likely": score >= 12 and len(hits) >= 4}


def reverse_product(videos: list, synthesis: dict, numbers: list, llm: LLM, log=print) -> dict:
    active = [v for v in videos if not v["duplicate_of"] and v["analysis"]]
    sig = product_signal(active)
    ku = "\n".join(
        f"- {u.get('unit', '')}：{u.get('detail', '')}"
        for u in (synthesis.get("knowledge_units") or [])[:40]
    ) or "（无）"
    num_text = "\n".join(
        f"- [{n['video_id']} {n['time']}] {n['kind']} {n['value']}  ← {n['context']}"
        for n in numbers[:80]
    ) or "（未抽取到硬数字）"

    prompt = P.PRODUCT.format(
        schema=json.dumps(P.PRODUCT_SCHEMA, ensure_ascii=False, indent=2),
        analyses=analyses_digest(active, max_chars=20000),
        knowledge_units=ku,
        numbers=num_text,
    )
    data = llm.chat_json(prompt, P.PRODUCT_SCHEMA, max_tokens=8000, thinking=False)
    if not data:
        data = {
            "is_product": sig["likely"],
            "confidence": 0.4 if sig["likely"] else 0.2,
            "why": f"规则信号：{sig['top']}",
            "product_name": "",
            "positioning": {}, "architecture": {}, "business_model": {},
            "clone_playbook": {}, "unknowns": [],
            "_source": "fallback",
        }
    data["_signal"] = sig
    return data


# ============================================================
# S8 产出
# ============================================================

def write_srt(segments: list, path: Path) -> None:
    def ts(sec):
        s = int(float(sec))
        ms = int((float(sec) - s) * 1000)
        h, rem = divmod(s, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    lines = []
    for i, seg in enumerate(segments, 1):
        lines += [str(i), f"{ts(seg['start'])} --> {ts(seg['end'])}", seg["text"], ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def md_frontmatter(meta: dict) -> str:
    lines = ["---"]
    for k, v in meta.items():
        lines.append(f"{k}: {v}")
    lines.append("---\n")
    return "\n".join(lines)


def render_overview(result: dict) -> str:
    vids = result["videos"]
    active = [v for v in vids if not v["duplicate_of"]]
    syn = result["synthesis"]
    stats = result["corpus"]["stats"]
    L = []
    L.append(md_frontmatter({
        "来源": "视频蒸馏",
        "批次": result["batch"],
        "视频数": f"{len(vids)} → 去重后 {len(active)}",
        "总时长": hms(sum(v["duration"] for v in active)),
        "生成时间": result["created_at"],
        "管线版本": f"{PIPELINE_VERSION} / prompt {P.PROMPT_VERSION}",
    }))
    L.append(f"# {result['batch']} · 蒸馏总览\n")
    L.append(f"> {syn.get('corpus_gist', '')}\n")

    L.append("## 这批是什么\n")
    L.append(syn.get("what_this_is", "") or "（LLM 未生成，见下方综述）")
    L.append("")

    L.append("## 数字概览\n")
    L.append("| 指标 | 数值 |")
    L.append("|---|---|")
    L.append(f"| 扫描到视频 | {len(vids)} 条 |")
    L.append(f"| 去重后 | {len(active)} 条 |")
    L.append(f"| 丢弃重复 | {len(vids) - len(active)} 条 |")
    L.append(f"| 总时长 | {hms(sum(v['duration'] for v in active))} |")
    L.append(f"| 原始语句 | {stats['total']} 句 |")
    L.append(f"| 去重后语句 | {stats['kept']} 句（丢重复 {stats['dropped_repeat']}，噪声 {stats['dropped_boilerplate']}） |")
    L.append(f"| 合并逐字稿 | {stats['paragraphs']} 段 / {stats['chars_kept']} 字 |")
    L.append(f"| 抽取硬数字 | {len(result['numbers'])} 条 |")
    L.append("")

    L.append("## 主题地图\n")
    topics = syn.get("topics") or []
    if topics:
        L.append("| 主题 | 重要度 | 覆盖视频 | 核心洞察 |")
        L.append("|---|---|---|---|")
        for t in topics:
            w = t.get("weight", 3)
            stars = "★" * int(w) if isinstance(w, (int, float)) else str(w)
            cov = "、".join(t.get("covered_by", []) or [])
            L.append(f"| {t.get('name','')} | {stars} | {cov} | {t.get('key_insight','')} |")
    else:
        L.append("（未生成主题）")
    L.append("")

    units = syn.get("knowledge_units") or []
    if units:
        L.append("## 知识单元（已跨视频合并去重）\n")
        for i, u in enumerate(units[:40], 1):
            merged = "、".join(u.get("merged_from", []) or [])
            L.append(f"**{i}. {u.get('unit','')}**  ")
            L.append(f"{u.get('detail','')}  ")
            if merged:
                L.append(f"<sub>来源：{merged}</sub>  ")
            if u.get("conflicts"):
                L.append(f"⚠️ 分歧：{u['conflicts']}  ")
            L.append("")

    red = syn.get("redundancy") or {}
    if red.get("repeated_content") or red.get("repeated_intros"):
        L.append("## 重复与冗余（这部分不用再看）\n")
        for x in (red.get("repeated_intros") or []):
            L.append(f"- 反复出现的开场：{x}")
        for x in (red.get("repeated_content") or []):
            L.append(f"- 被重复讲：{x}")
        L.append("")
    if red.get("unique_value"):
        L.append("### 只有它才有的信息\n")
        for u in red["unique_value"]:
            L.append(f"- **{u.get('video_id','')}**：{u.get('why','')}")
        L.append("")

    if syn.get("conflicts"):
        L.append("## 冲突与分歧\n")
        for c in syn["conflicts"]:
            L.append(f"- **{c.get('issue','')}**")
            for s in c.get("sides", []):
                L.append(f"  - {s}")
            if c.get("resolution"):
                L.append(f"  - 判断：{c['resolution']}")
        L.append("")

    if syn.get("missing_pieces"):
        L.append("## 缺口（这批视频没讲，但你得知道）\n")
        for m in syn["missing_pieces"]:
            L.append(f"- {m}")
        L.append("")

    if syn.get("learning_path"):
        L.append("## 建议观看顺序\n")
        L.append("| # | 视频 | 为什么 |")
        L.append("|---|---|---|")
        for i, p in enumerate(syn["learning_path"], 1):
            title = next((v["title"] for v in vids if v["id"] == p.get("video_id")), p.get("video_id", ""))
            L.append(f"| {i} | {p.get('video_id','')} {title} | {p.get('why','')} |")
        L.append("")

    L.append("## 综述\n")
    L.append(syn.get("master_summary", ""))
    L.append("")

    L.append("## 文件说明\n")
    L.append("| 文件 | 内容 |")
    L.append("|---|---|")
    L.append("| `01_逐字稿合并.md` | 全部视频去重合并后的逐字稿，带时间锚点 |")
    L.append("| `02_方法论.md` | 从操作里抽象出的可迁移方法论（L0→L3 四层） |")
    L.append("| `03_产品逆向.md` | 产品架构 + 商业模式 + 复刻路径 |")
    L.append("| `04_证据索引.md` | 每条结论的证据锚点、关键数字、界面线索 |")
    L.append("| `dedupe_report.md` | 去重明细（哪些是重复、为什么丢） |")
    L.append("| `transcripts/` | 单视频逐字稿（md / srt / txt） |")
    L.append("| `distill.json` | 全量结构化数据，给 Agent / 二次加工用 |")
    L.append("")
    return "\n".join(L)


def render_transcript(result: dict) -> str:
    vids = {v["id"]: v for v in result["videos"]}
    paragraphs = result["corpus"]["paragraphs"]
    L = [md_frontmatter({"来源": "视频蒸馏 · 合并逐字稿",
                         "批次": result["batch"],
                         "字数": result["corpus"]["stats"]["chars_kept"]}),
         f"# {result['batch']} · 合并逐字稿\n",
         "> 已做跨视频语句级去重：同一句被多个视频重复讲时只保留第一次出现。"
         "锚点格式 `[V03 04:12]` = 第 3 条视频的第 4 分 12 秒。\n"]

    current_video = None
    for p in paragraphs:
        if p["video_id"] != current_video:
            current_video = p["video_id"]
            v = vids.get(current_video, {})
            L.append(f"\n## {current_video} · {v.get('title','')}  ")
            L.append(f"<sub>{hms(v.get('duration', 0))} · {v.get('rel_path','')}</sub>\n")
        L.append(f"**[{p['video_id']} {mmss(p['start'])}]** {p['text']}\n")
    return "\n".join(L)


def render_methodology(result: dict) -> str:
    m = result["methodology"]
    master = m.get("master_method") or {}
    L = [md_frontmatter({"来源": "视频蒸馏 · 方法论",
                         "批次": result["batch"],
                         "方法卡": len(m.get("method_cards") or [])}),
         f"# {result['batch']} · 方法论\n"]
    if not master and not m.get("method_cards"):
        L.append("> LLM 不可用，本文件未生成。逐字稿仍完整可用，可手动阅读 01_逐字稿合并.md。")
        return "\n".join(L)

    if master:
        L.append(f"## 总方法：{master.get('name','')}\n")
        L.append(f"> {master.get('one_liner','')}\n")
        if master.get("problem"):
            L.append(f"**解决什么问题**：{master['problem']}\n")
        if master.get("preconditions"):
            L.append("**前提条件**\n")
            for p in master["preconditions"]:
                L.append(f"- {p}")
            L.append("")
        if master.get("big_picture"):
            L.append(f"**整体逻辑**：{master['big_picture']}\n")
        if master.get("stages"):
            L.append("### 阶段流程\n")
            L.append("| 阶段 | 目标 | 动作 | 产出 | 验收 | 做错的后果 |")
            L.append("|---|---|---|---|---|---|")
            for s in master["stages"]:
                do = "；".join(s.get("do", []) or [])
                L.append(f"| {s.get('stage','')} | {s.get('goal','')} | {do} | "
                         f"{s.get('output','')} | {s.get('check','')} | {s.get('failure','')} |")
            L.append("")

    cards = m.get("method_cards") or []
    if cards:
        L.append("## 方法卡\n")
        for i, c in enumerate(cards, 1):
            L.append(f"### {i}. {c.get('name','')}  <sub>{c.get('layer','')}</sub>\n")
            if c.get("trigger"):
                L.append(f"**什么时候用**：{c['trigger']}\n")
            if c.get("statement"):
                L.append(f"**方法**：{c['statement']}\n")
            if c.get("procedure"):
                L.append("**步骤**\n")
                for j, s in enumerate(c["procedure"], 1):
                    L.append(f"{j}. {s.get('step','')}")
                    if s.get("why"):
                        L.append(f"   - 为什么：{s['why']}")
                    if s.get("verify"):
                        L.append(f"   - 怎么算做对：{s['verify']}")
                L.append("")
            if c.get("heuristics"):
                L.append("**经验法则**：" + "；".join(c["heuristics"]) + "\n")
            if c.get("anti_patterns"):
                L.append("**反模式（别这么干）**")
                for a in c["anti_patterns"]:
                    L.append(f"- {a}")
                L.append("")
            if c.get("transfer"):
                L.append("**迁移**：" + "；".join(c["transfer"]) + "\n")
            if c.get("evidence"):
                L.append("**证据**")
                for e in c["evidence"][:6]:
                    L.append(f"- [{e.get('video_id','')} {e.get('time','')}] 「{e.get('quote','')}」")
                L.append("")

    if m.get("mental_models"):
        L.append("## 心智模型\n")
        for x in m["mental_models"]:
            L.append(f"- **{x.get('model','')}**：{x.get('explain','')}"
                     + (f"（用在：{x['use_when']}）" if x.get("use_when") else ""))
        L.append("")
    if m.get("decision_table"):
        L.append("## 决策表\n")
        L.append("| 如果 | 那就 | 因为 |")
        L.append("|---|---|---|")
        for d in m["decision_table"]:
            L.append(f"| {d.get('if','')} | {d.get('then','')} | {d.get('because','')} |")
        L.append("")
    if m.get("quality_bar"):
        L.append("## 质量线（可检验）\n")
        for q in m["quality_bar"]:
            L.append(f"- [ ] {q}")
        L.append("")

    lv = m.get("levels") or {}
    if any(lv.get(k) for k in lv):
        L.append("## 四层拆解\n")
        names = [("L3_model", "L3 心智模型"), ("L2_method", "L2 方法"),
                 ("L1_rules", "L1 规律"), ("L0_facts", "L0 事实")]
        for key, label in names:
            if lv.get(key):
                L.append(f"### {label}\n")
                for x in lv[key]:
                    L.append(f"- {x}")
                L.append("")
    return "\n".join(L)


def render_product(result: dict) -> str:
    p = result["product"]
    L = [md_frontmatter({"来源": "视频蒸馏 · 产品逆向",
                         "批次": result["batch"],
                         "是否产品": p.get("is_product")}),
         f"# {result['batch']} · 产品逆向\n"]

    if not p.get("is_product"):
        L.append("> 判定：这批视频不涉及具体产品，未做产品逆向。\n")
        L.append(f"判断依据：{p.get('why','')}")
        return "\n".join(L)

    L.append(f"> 产品：**{p.get('product_name','')}** ｜ 置信度 {p.get('confidence','')} ｜ 依据：{p.get('why','')}\n")

    pos = p.get("positioning") or {}
    if pos:
        L.append("## 一、定位\n")
        L.append("| 维度 | 内容 |")
        L.append("|---|---|")
        for k, label in (("what", "是什么"), ("for_whom", "给谁用"),
                         ("job_to_be_done", "替用户完成什么任务"),
                         ("wedge", "切入的痛点")):
            if pos.get(k):
                L.append(f"| {label} | {pos[k]} |")
        if pos.get("substitutes"):
            L.append(f"| 替代方案 | {'、'.join(pos['substitutes'])} |")
        L.append("")

    arch = p.get("architecture") or {}
    if arch.get("mermaid"):
        L.append("## 二、架构图\n")
        L.append("```mermaid")
        L.append(arch["mermaid"])
        L.append("```\n")
    if arch.get("layers"):
        L.append("### 分层模块\n")
        for layer in arch["layers"]:
            L.append(f"**{layer.get('layer','')}**\n")
            L.append("| 模块 | 作用 | 证据 |")
            L.append("|---|---|---|")
            for m in layer.get("modules", []):
                L.append(f"| {m.get('name','')} | {m.get('function','')} | {m.get('evidence','')} |")
            L.append("")
    if arch.get("data_objects"):
        L.append("### 数据对象\n")
        L.append("| 实体 | 字段 | 关系 |")
        L.append("|---|---|---|")
        for d in arch["data_objects"]:
            L.append(f"| {d.get('entity','')} | {'、'.join(d.get('fields', []) or [])} | {d.get('relations','')} |")
        L.append("")
    if arch.get("core_flows"):
        L.append("### 核心流程\n")
        for f in arch["core_flows"]:
            L.append(f"**{f.get('name','')}**  ")
            for i, s in enumerate(f.get("steps", []), 1):
                L.append(f"{i}. {s}")
            if f.get("pain_removed"):
                L.append(f"\n> 这一步省掉了用户什么：{f['pain_removed']}\n")
    if arch.get("ai_pipeline"):
        L.append("### AI 链路（推测）\n")
        L.append("| 环节 | 可能的技术 | 推断依据 |")
        L.append("|---|---|---|")
        for a in arch["ai_pipeline"]:
            L.append(f"| {a.get('stage','')} | {a.get('tech_guess','')} | {a.get('why','')} |")
        L.append("")

    bm = p.get("business_model") or {}
    if bm:
        L.append("## 三、商业模式\n")
        if bm.get("revenue_streams"):
            L.append("### 收入结构\n")
            for r in bm["revenue_streams"]:
                L.append(f"- **{r.get('stream','')}**：{r.get('mechanism','')}"
                         + (f"（证据：{r['evidence']}）" if r.get("evidence") else ""))
            L.append("")
        if bm.get("pricing"):
            L.append("### 定价\n")
            L.append("| 套餐 | 价格 | 额度 | 计量单位 |")
            L.append("|---|---|---|---|")
            for x in bm["pricing"]:
                L.append(f"| {x.get('plan','')} | {x.get('price','')} | {x.get('quota','')} | {x.get('unit','')} |")
            L.append("")
        if bm.get("metering_unit"):
            L.append(f"**核心计量单位**：{bm['metering_unit']}\n")
        ue = bm.get("unit_economics") or {}
        if ue:
            if ue.get("cost_drivers"):
                L.append("**成本项**：" + "、".join(ue["cost_drivers"]) + "\n")
            if ue.get("margin_hypothesis"):
                L.append(f"**毛利结构（推测）**：{ue['margin_hypothesis']}\n")
            if ue.get("leak_points"):
                L.append("**会被薅羊毛的地方**：")
                for x in ue["leak_points"]:
                    L.append(f"- {x}")
                L.append("")
        g = bm.get("growth") or {}
        if g:
            for k, label in (("channels", "获客渠道"), ("funnel", "转化路径"), ("retention_hook", "留存钩子")):
                if g.get(k):
                    L.append(f"**{label}**：" + " → ".join(g[k]) + "\n")
        if bm.get("moat"):
            L.append("### 护城河\n")
            for m in bm["moat"]:
                L.append(f"- {m}")
            L.append("")
        if bm.get("risks"):
            L.append("### 风险\n")
            for r in bm["risks"]:
                L.append(f"- {r}")
            L.append("")

    cp = p.get("clone_playbook") or {}
    if cp:
        L.append("## 四、复刻路径\n")
        if cp.get("mvp_weeks"):
            L.append(f"**MVP 周期**：{cp['mvp_weeks']}\n")
        for k, label in (("must_have", "必须有"), ("nice_to_have", "可以有"), ("skip", "第一期别做")):
            if cp.get(k):
                L.append(f"**{label}**")
                for x in cp[k]:
                    L.append(f"- {x}")
                L.append("")
        if cp.get("hardest_part"):
            L.append(f"**最难的不是功能**：{cp['hardest_part']}\n")
        if cp.get("first_10_users"):
            L.append(f"**前 10 个用户从哪来**：{cp['first_10_users']}\n")

    if p.get("unknowns"):
        L.append("## 五、待验证假设\n")
        for u in p["unknowns"]:
            L.append(f"- [ ] {u}")
        L.append("")
    return "\n".join(L)


def render_evidence(result: dict) -> str:
    vids = [v for v in result["videos"] if not v["duplicate_of"]]
    L = [md_frontmatter({"来源": "视频蒸馏 · 证据索引", "批次": result["batch"]}),
         f"# {result['batch']} · 证据索引\n",
         "> 所有结论都能在这里回查：原话、时间点、界面线索、硬数字。\n"]

    if result["numbers"]:
        L.append("## 硬数字（价格 / 字数 / 额度 / 比例）\n")
        L.append("| 类型 | 数值 | 上下文 | 出处 |")
        L.append("|---|---|---|---|")
        for n in result["numbers"][:60]:
            L.append(f"| {n['kind']} | {n['value']} | {n['context']} | {n['video_id']} {n['time']} |")
        L.append("")

    for v in vids:
        a = v.get("analysis") or {}
        L.append(f"\n## {v['id']} · {v['title']}\n")
        L.append(f"<sub>{hms(v['duration'])} · {v['rel_path']} · {v['chars']} 字</sub>\n")
        if a.get("gist"):
            L.append(f"**讲了什么**：{a['gist']}\n")
        if a.get("one_line_takeaway"):
            L.append(f"**一句话记住**：{a['one_line_takeaway']}\n")
        if a.get("sections"):
            L.append("**章节**")
            for s in a["sections"]:
                L.append(f"- `{s.get('start','')}-{s.get('end','')}` **{s.get('title','')}**：{s.get('summary','')}")
            L.append("")
        if a.get("steps"):
            L.append("**操作步骤**")
            for s in a["steps"]:
                L.append(f"{s.get('order','')}. {s.get('action','')}"
                         + (f" — 在 {s['where']}" if s.get("where") else "")
                         + (f"；{s['detail']}" if s.get("detail") else "")
                         + (f"  `[{s.get('time','')}]`" if s.get("time") else ""))
            L.append("")
        if a.get("ui_evidence"):
            L.append("**界面线索**：" + "；".join(a["ui_evidence"]) + "\n")
        if a.get("rules_and_numbers"):
            L.append("**规则/数值**")
            for r in a["rules_and_numbers"]:
                L.append(f"- {r.get('item','')}：{r.get('value','')}"
                         + (f"（{r['note']}）" if r.get("note") else ""))
            L.append("")
        if a.get("pitfalls"):
            L.append("**坑**")
            for x in a["pitfalls"]:
                L.append(f"- {x}")
            L.append("")
        if a.get("claims"):
            L.append("**主张/承诺**")
            for x in a["claims"]:
                L.append(f"- {x}")
            L.append("")
        if a.get("quotes"):
            L.append("**原话**")
            for q in a["quotes"][:10]:
                L.append(f"- `[{q.get('time','')}]` 「{q.get('text','')}」")
            L.append("")
    return "\n".join(L)


def render_dedupe(result: dict) -> str:
    d = result["dedupe"]
    vids = {v["id"]: v for v in result["videos"]}
    L = [md_frontmatter({"来源": "视频蒸馏 · 去重报告", "批次": result["batch"]}),
         f"# {result['batch']} · 去重报告\n"]

    total = len(result["videos"])
    dropped = total - len([v for v in result["videos"] if not v["duplicate_of"]])
    L.append(f"扫描 {total} 条，丢弃 {dropped} 条重复。\n")

    L.append("## 三层去重口径\n")
    L.append("| 层 | 判据 | 阈值 | 作用 |")
    L.append("|---|---|---|---|")
    L.append(f"| L1 文件级 | SHA-256 完全一致 | — | 同一文件被复制/改名 |")
    L.append(f"| L2 近似级 | 时长差 + 三帧 dHash 汉明距离 | ≤{THRESHOLDS['near_dup_duration']*100:.0f}% / ≤{THRESHOLDS['near_dup_hamming']} | 同一内容的不同压制、剪辑版 |")
    L.append(f"| L3 内容级 | 逐字稿 5-gram Jaccard | ≥{THRESHOLDS['content_dup_jaccard']:.0%} | 同一门课被重录 |")
    L.append("")

    if d.get("exact") or d.get("near") or (d.get("content") or {}).get("content"):
        L.append("## 明细\n")
        def label(vid):
            v = vids.get(vid) or {}
            return f"`{vid}` {v.get('title', '')}（{hms(v.get('duration', 0))}）"

        for g in d.get("exact") or []:
            L.append(f"- **完全相同**：保留 {label(g['keep'])}")
            for x in g["dropped"]:
                L.append(f"  - 丢弃 {label(x)}：文件内容完全一致")
        for g in d.get("near") or []:
            L.append(f"- **近似重复**：保留 {label(g['keep'])}")
            for x in g["dropped"]:
                L.append(f"  - 丢弃 {label(x)}：三帧画面平均汉明 {g['avg_hamming']}，"
                         f"时长差 {g['duration_delta']*100:.1f}%")
        for g in (d.get("content") or {}).get("content") or []:
            L.append(f"- **内容重复**：保留 {label(g['keep'])}")
            for x in g["dropped"]:
                L.append(f"  - 丢弃 {label(x)}：逐字稿相似度 {g['similarity']:.0%}")
        L.append("")
    else:
        L.append("没有发现重复文件。\n")

    L.append("## 逐条视频\n")
    L.append("| ID | 标题 | 时长 | 字数 | 重复句 | 状态 |")
    L.append("|---|---|---|---|---|---|")
    for v in result["videos"]:
        red = result["corpus"]["redundant_by_video"].get(v["id"], 0)
        status = f"重复 → {v['duplicate_of']}" if v["duplicate_of"] else "保留"
        L.append(f"| {v['id']} | {v['title'][:36]} | {hms(v['duration'])} | {v['chars']} | {red} | {status} |")
    L.append("")
    L.append("> 「重复句」= 该视频里被其他视频先讲过的语句数（跨视频语句级去重）。")
    return "\n".join(L)


def emit(result: dict, out_dir: Path, log=print) -> dict:
    """写全部产物"""
    ensure_dir(out_dir)
    tr_dir = ensure_dir(out_dir / "transcripts")
    outputs = {}

    def save(name, content):
        p = out_dir / name
        p.write_text(content, encoding="utf-8")
        outputs[name] = str(p)
        log(f"  ✓ {name}（{len(content)} 字符）")

    save("00_总览.md", render_overview(result))
    save("01_逐字稿合并.md", render_transcript(result))
    save("02_方法论.md", render_methodology(result))
    save("03_产品逆向.md", render_product(result))
    save("04_证据索引.md", render_evidence(result))
    save("dedupe_report.md", render_dedupe(result))

    # 单视频逐字稿
    for v in result["videos"]:
        if not v["segments"]:
            continue
        stem = f"{v['id']}_{safe_name(v['title'])}"
        (tr_dir / f"{stem}.txt").write_text(
            "\n".join(s["text"] for s in v["segments"]), encoding="utf-8")
        write_srt(v["segments"], tr_dir / f"{stem}.srt")
        lines = [f"# {v['id']} · {v['title']}\n",
                 f"<sub>{hms(v['duration'])} · {v['rel_path']}</sub>\n"]
        for s in v["segments"]:
            lines.append(f"**[{mmss(s['start'])}]** {s['text']}\n")
        (tr_dir / f"{stem}.md").write_text("\n".join(lines), encoding="utf-8")
    outputs["transcripts_dir"] = str(tr_dir)
    log(f"  ✓ transcripts/（{len([v for v in result['videos'] if v['segments']])} 份）")

    (out_dir / "dedupe_report.json").write_text(
        json.dumps(result["dedupe"], ensure_ascii=False, indent=2), encoding="utf-8")
    outputs["dedupe_report.json"] = str(out_dir / "dedupe_report.json")

    payload = {
        "version": PIPELINE_VERSION,
        "prompt_version": P.PROMPT_VERSION,
        "created_at": result["created_at"],
        "batch": result["batch"],
        "source_folder": result["source_folder"],
        "category": result["category"],
        "thresholds": THRESHOLDS,
        "stages": result["stages"],
        "llm": result["llm_info"],
        "videos": [{
            "id": v["id"],
            "name": v["name"],
            "rel_path": v["rel_path"],
            "title": v["title"],
            "size": v["size"],
            "duration": v["duration"],
            "width": v["width"],
            "height": v["height"],
            "sha256": v["sha256"],
            "duplicate_of": v["duplicate_of"],
            "duplicate_reason": v["duplicate_reason"],
            "chars": v["chars"],
            "segments_count": len(v["segments"]),
            "analysis_source": (v.get("analysis") or {}).get("_source", ""),
        } for v in result["videos"]],
        "dedupe": result["dedupe"],
        "corpus_stats": result["corpus"]["stats"],
        "redundant_by_video": result["corpus"]["redundant_by_video"],
        "synthesis": result["synthesis"],
        "methodology": result["methodology"],
        "product": result["product"],
        "numbers": result["numbers"],
        "analyses": {v["id"]: v["analysis"] for v in result["videos"] if v["analysis"]},
        "outputs": outputs,
    }
    (out_dir / "distill.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    outputs["distill.json"] = str(out_dir / "distill.json")
    log(f"  ✓ distill.json")
    return outputs


# ============================================================
# 编排
# ============================================================

def _stage(result, sid, name, fn, log):
    t0 = time.time()
    log(f"\n[{sid}] {name}")
    try:
        out = fn()
        status = "ok"
    except Exception as e:
        log(f"  ✗ {sid} 失败: {e}")
        out, status = None, f"error: {e}"
    elapsed = round(time.time() - t0, 1)
    result["stages"].append({"id": sid, "name": name, "status": status, "elapsed": elapsed})
    log(f"  ⏱ {sid} {elapsed}s")
    return out


def run_distill(folder, category: str = "未分类", batch: str | None = None,
                asr_engine: str = "faster-whisper", whisper_model: str | None = None,
                use_llm: bool = True,
                max_videos: int | None = None, resume: bool = True,
                concurrency: int = 3, hotwords: str = "",
                out_root: Path | None = None, log=print) -> dict:
    """蒸馏主入口。返回结果 dict（可直接 json.dumps 给 CLI/Agent）。"""
    folder = Path(folder).expanduser().resolve()
    t_start = time.time()
    ff.ensure_available()

    batch = batch or safe_name(folder.name)
    out_root = Path(out_root) if out_root else cfg.OUTPUT_DIR
    out_dir = out_root / category / batch
    work = ensure_dir(out_dir / "_work")

    # 缓存签名：热词表或提示词版本一变，依赖文本的中间结果就作废
    hotword_pairs = parse_hotwords(hotwords or cfg._get("DISTILL_HOTWORDS", ""))
    sig_src = "|".join(f"{a}={b}" for a, b in hotword_pairs) + "|" + P.PROMPT_VERSION
    sig = hashlib.sha1(sig_src.encode()).hexdigest()[:8]
    meta_path = work / "_meta.json"
    prev_meta = {}
    if meta_path.exists():
        try:
            prev_meta = json.loads(meta_path.read_text())
        except Exception:
            prev_meta = {}
    # 注意：没有 _meta.json 但已有中间结果（旧版本留下的）也算作废
    if prev_meta.get("sig") != sig:
        stale = ["s3_corpus.json", "s5_synthesis.json",
                 "s6_methodology.json", "s7_product.json"]
        removed = 0
        for name in stale:
            f = work / name
            if f.exists():
                f.unlink()
                removed += 1
        for f in work.glob("a_V*.json"):
            f.unlink()
            removed += 1
        if removed:
            log(f"  · 热词表 / 提示词版本变了，清掉 {removed} 个旧中间结果（转写缓存保留）")
    meta_path.write_text(json.dumps(
        {"sig": sig, "hotwords": hotword_pairs, "prompt_version": P.PROMPT_VERSION,
         "pipeline_version": PIPELINE_VERSION}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    log(f"VideoToText · 蒸馏模式 v{PIPELINE_VERSION}")
    log(f"源目录: {folder}")
    log(f"输出:   {out_dir}")

    result = {
        "version": PIPELINE_VERSION,
        "prompt_version": P.PROMPT_VERSION,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "batch": batch,
        "source_folder": str(folder),
        "category": category,
        "stages": [],
        "videos": [],
        "dedupe": {},
        "corpus": {"segments": [], "paragraphs": [], "stats": {}, "redundant_by_video": {}},
        "synthesis": {},
        "methodology": {},
        "product": {},
        "numbers": [],
        "llm_info": {},
    }

    # ---------- S0 采集 ----------
    def s0():
        files = scan_folder(folder)
        if max_videos:
            files = files[:max_videos]
        if not files:
            raise RuntimeError(f"{folder} 里没有找到视频文件")
        log(f"  发现 {len(files)} 个视频")
        return enrich_videos(files, log)

    cached = work / "s0_videos.json"
    if resume and cached.exists():
        log("\n[S0] 采集（复用缓存）")
        raw = json.loads(cached.read_text())
        for v in raw:
            v["path"] = Path(v["path"])
        result["videos"] = raw
        result["stages"].append({"id": "S0", "name": "采集", "status": "cached", "elapsed": 0})
    else:
        result["videos"] = _stage(result, "S0", "采集（递归扫描 + 元信息 + 标题清洗）", s0, log) or []
        if not result["videos"]:
            raise RuntimeError("采集阶段没有结果")
        (work / "s0_videos.json").write_text(json.dumps(
            [{**v, "path": str(v["path"])} for v in result["videos"]],
            ensure_ascii=False, indent=2), encoding="utf-8")

    videos = result["videos"]

    # ---------- S1 指纹 + 文件级去重 ----------
    def s1():
        compute_fingerprints(videos, work, log)
        return dedupe_files(videos, log)

    result["dedupe"] = _stage(result, "S1", "去重（哈希 + 画面指纹 + 逐字稿相似度）", s1, log) or {}

    # ---------- S2 转写 ----------
    def s2():
        transcribe_videos([v for v in videos if not v["duplicate_of"]],
                          asr_engine, whisper_model, log)
        return True

    if resume and (work / "s2_transcripts.json").exists():
        log("\n[S2] 转写（复用缓存）")
        saved = json.loads((work / "s2_transcripts.json").read_text())
        for v in videos:
            if v["id"] in saved:
                v["segments"] = saved[v["id"]].get("segments", [])
                v["chars"] = saved[v["id"]].get("chars", 0)
        result["stages"].append({"id": "S2", "name": "转写", "status": "cached", "elapsed": 0})
    else:
        _stage(result, "S2", "转写（本地 ASR，带缓存）", s2, log)
        (work / "s2_transcripts.json").write_text(json.dumps(
            {v["id"]: {"segments": v["segments"], "chars": v["chars"]} for v in videos},
            ensure_ascii=False), encoding="utf-8")

    # 热词纠正（在合并之前，保证下游全用修正后的文本）
    if hotword_pairs:
        fixed = apply_hotwords(videos, hotword_pairs)
        log(f"  ✓ 热词纠正 {fixed} 处（{len(hotword_pairs)} 条规则）")

    # ---------- S3 内容去重 + 合并 ----------
    def s3():
        content = dedupe_content(videos, log)
        result["dedupe"].update(content)
        return merge_corpus(videos, log)

    if resume and (work / "s3_corpus.json").exists():
        log("\n[S3] 合并（复用缓存）")
        data = json.loads((work / "s3_corpus.json").read_text())
        result["corpus"] = data["corpus"]
        result["dedupe"].update(data["dedupe"])
        # 内容级去重的 duplicate_of 也要恢复
        for g in (data["dedupe"].get("content") or []):
            for d in g.get("dropped", []):
                dv = next((x for x in videos if x["id"] == d), None)
                if dv:
                    dv["duplicate_of"] = g["keep"]
                    dv["duplicate_reason"] = f"逐字稿相似度 {g['similarity']:.0%}（内容重复）"
        result["stages"].append({"id": "S3", "name": "合并", "status": "cached", "elapsed": 0})
    else:
        corpus = _stage(result, "S3", "合并（语句级去重 + 段落化）", s3, log)
        if corpus:
            result["corpus"] = corpus
            (work / "s3_corpus.json").write_text(json.dumps(
                {"corpus": corpus, "dedupe": result["dedupe"]},
                ensure_ascii=False), encoding="utf-8")

    # ---------- S4 单视频深读 ----------
    llm = LLM(log=log, enabled=use_llm)
    result["llm_info"] = {"provider": llm.provider, "model": llm.model,
                          "available": llm.available, "calls": 0, "errors": 0}
    if llm.available:
        log(f"\n  LLM: {llm.provider} / {llm.model}")
    else:
        log("\n  ⚠ 没有可用的 LLM，将降级为规则结果（逐字稿与去重仍然完整）")

    def s4():
        active = [v for v in videos
                  if not v["duplicate_of"] and v["segments"] and not v.get("analysis")]
        if not active:
            return True
        lock = threading.Lock()
        counter = {"n": 0}

        def one(v):
            data = analyze_video(v, llm, log)
            v["analysis"] = data
            with lock:
                counter["n"] += 1
                log(f"  [{counter['n']}/{len(active)}] {v['id']} ✓ {str((data or {}).get('gist', ''))[:44]}")
                if (data or {}).get("_source") == "llm":
                    # 降级结果不落盘：下次有 LLM 时应该重跑
                    (work / f"a_{v['id']}.json").write_text(
                        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

        # LLM 调用是网络 IO，并发跑（ASR 是 CPU 密集，已经在 S2 串行做完了）
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            list(pool.map(one, active))
        return True

    # 单个视频分析也做断点续跑（降级结果不算数：有 LLM 时要重跑）
    for v in videos:
        f = work / f"a_{v['id']}.json"
        if not (resume and f.exists()):
            continue
        data = json.loads(f.read_text())
        is_fallback = str(data.get("_source", "")).startswith("fallback")
        if is_fallback and llm.available:
            continue
        v["analysis"] = data
    _stage(result, "S4", "深读（逐视频结构化拆解）", s4, log)

    # ---------- S5 综合 ----------
    def s5():
        return synthesize(videos, result["corpus"], llm, log)

    sf = work / "s5_synthesis.json"
    if resume and sf.exists():
        log("\n[S5] 综合（复用缓存）")
        result["synthesis"] = json.loads(sf.read_text())
        result["stages"].append({"id": "S5", "name": "综合", "status": "cached", "elapsed": 0})
    else:
        result["synthesis"] = _stage(result, "S5", "综合（主题图谱 + 知识合并 + 冲突）", s5, log) or {}
        if result["synthesis"].get("_source") != "fallback":
            sf.write_text(json.dumps(result["synthesis"], ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- 数字抽取 ----------
    result["numbers"] = extract_numbers(videos)

    # ---------- S6 方法论 ----------
    def s6():
        return methodology(videos, result["synthesis"], llm, log)

    mf = work / "s6_methodology.json"
    if resume and mf.exists():
        log("\n[S6] 方法论（复用缓存）")
        result["methodology"] = json.loads(mf.read_text())
        result["stages"].append({"id": "S6", "name": "方法论", "status": "cached", "elapsed": 0})
    else:
        result["methodology"] = _stage(result, "S6", "抽象（方法论 L0→L3）", s6, log) or {}
        if result["methodology"].get("_source") != "fallback":
            mf.write_text(json.dumps(result["methodology"], ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- S7 产品逆向 ----------
    def s7():
        return reverse_product(videos, result["synthesis"], result["numbers"], llm, log)

    pf = work / "s7_product.json"
    if resume and pf.exists():
        log("\n[S7] 产品逆向（复用缓存）")
        result["product"] = json.loads(pf.read_text())
        result["stages"].append({"id": "S7", "name": "产品逆向", "status": "cached", "elapsed": 0})
    else:
        result["product"] = _stage(result, "S7", "逆向（产品架构 + 商业模式）", s7, log) or {}
        if result["product"].get("_source") != "fallback":
            pf.write_text(json.dumps(result["product"], ensure_ascii=False, indent=2), encoding="utf-8")

    # ---------- S8 产出 ----------
    result["llm_info"]["calls"] = llm.calls
    result["llm_info"]["errors"] = llm.errors
    result["stages"].append({"id": "S8", "name": "产出", "status": "ok", "elapsed": 0})
    log("\n[S8] 产出")
    outputs = emit(result, out_dir, log)

    elapsed = round(time.time() - t_start, 1)
    log(f"\n✓ 完成，用时 {elapsed}s")
    log(f"  打开这个看：{outputs.get('00_总览.md')}")

    return {
        "ok": True,
        "batch": batch,
        "out_dir": str(out_dir),
        "outputs": outputs,
        "videos": {
            "scanned": len(videos),
            "kept": len([v for v in videos if not v["duplicate_of"]]),
            "dropped": len([v for v in videos if v["duplicate_of"]]),
            "duration_hours": round(sum(v["duration"] for v in videos if not v["duplicate_of"]) / 3600, 2),
        },
        "corpus": result["corpus"]["stats"],
        "llm": result["llm_info"],
        "product": {
            "is_product": bool(result["product"].get("is_product")),
            "confidence": result["product"].get("confidence"),
            "name": result["product"].get("product_name", ""),
        },
        "methodology_cards": len(result["methodology"].get("method_cards") or []),
        "numbers": len(result["numbers"]),
        "elapsed_seconds": elapsed,
        "stages": result["stages"],
    }
