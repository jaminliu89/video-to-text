#!/usr/bin/env python3
"""
tests/test_distill_units.py — 蒸馏管线的纯函数单测（不联网、不调 ffmpeg、不调 LLM）

跑法：
    python3 tests/test_distill_units.py

CI 里也跑这个。任何一个断言失败就退出码非 0。
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from v2t import distill as D  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, extra=""):
    (PASS if cond else FAIL).append(name)
    print(("  ✓ " if cond else "  ✗ ") + name + (f"  {extra}" if extra and not cond else ""))


# ---------------- 标题清洗 ----------------

def test_clean_title():
    cases = [
        ("星月写作教程 - 【星月写作教程】Ai提示词_提示词的使用教程与创作方法·百万字AI小说也写不崩·AI写作.mp4",
         "Ai提示词_提示词的使用教程与创作方法"),
        ("星月写作教程 - 网文十万稿费作者，首次公开自己全部的开书创作流程，写网文必看教程！.mp4",
         "网文十万稿费作者"),
        ("第03讲 三幕式结构.mp4", "第03讲 三幕式结构"),
        ("【某课程】01 开篇·引流话术·关注我.mp4", "01 开篇"),
        ("plain_name.mp4", "plain_name"),
    ]
    for src, want in cases:
        got = D.clean_title(src)
        check(f"clean_title → {want}", got == want, f"got={got!r}")


# ---------------- 指纹与相似度 ----------------

def test_shingles():
    a = D.shingles("我们今天来讲一下提示词怎么写")
    b = D.shingles("我们今天来讲一下提示词怎么写")
    c = D.shingles("完全不同的内容关于视频剪辑")
    check("shingles 稳定", a == b)
    check("jaccard 自身为 1", abs(D.jaccard(a, b) - 1.0) < 1e-9)
    check("jaccard 无关为 0", D.jaccard(a, c) == 0.0)
    check("containment 全包含为 1", D.containment(a, a | c) == 1.0)


def test_norm_text():
    check("norm_text 去标点", D.norm_text("你好，世界！AI 2026") == "你好世界ai2026")


# ---------------- 噪声判定 ----------------

def test_boilerplate():
    check("纯语气词是噪声", D.is_boilerplate("嗯嗯"))
    check("求关注短句是噪声", D.is_boilerplate("记得点赞关注"))
    check("长句里的关注不是噪声", not D.is_boilerplate("这里要关注提示词的结构和顺序"))
    check("正常内容不是噪声", not D.is_boilerplate("先选章纲再续写正文"))


# ---------------- 段落化 ----------------

def test_group_paragraphs():
    segs = [
        {"video_id": "V01", "video_title": "t", "start": 0.0, "end": 2.0, "text": "第一句"},
        {"video_id": "V01", "video_title": "t", "start": 2.3, "end": 4.0, "text": "第二句"},
        {"video_id": "V01", "video_title": "t", "start": 20.0, "end": 22.0, "text": "隔了很久"},
        {"video_id": "V02", "video_title": "u", "start": 22.1, "end": 23.0, "text": "换视频了"},
    ]
    out = D.group_paragraphs(segs)
    check("相邻短句并段", out[0]["text"].startswith("第一句") and "第二句" in out[0]["text"])
    check("间隔大就断段", len(out) >= 3)
    check("换视频必须断段", out[-1]["video_id"] == "V02")


# ---------------- 去重 ----------------

def _fake_video(vid, sha, dur=100.0, hashes=None, segs=None, size=1000):
    return {
        "id": vid, "path": Path(f"/tmp/{vid}.mp4"), "rel_path": f"{vid}.mp4",
        "name": f"{vid}.mp4", "title": vid, "size": size, "duration": dur,
        "width": 1280, "height": 720, "has_audio": True, "sha256": sha,
        "frame_hashes": hashes or [], "duplicate_of": None, "duplicate_reason": "",
        "segments": segs or [], "chars": sum(len(s["text"]) for s in (segs or [])),
        "analysis": None,
    }


def test_dedupe_exact():
    vids = [_fake_video("V01", "aaa", size=900), _fake_video("V02", "aaa", size=1000)]
    groups = D.dedupe_files(vids)
    check("完全相同文件被识别", len(groups["exact"]) == 1)
    check("保留体积更大的", vids[1]["duplicate_of"] is None and vids[0]["duplicate_of"] == "V02")


def test_dedupe_near():
    same = [0b10101010] * 3
    vids = [
        _fake_video("V01", "h1", dur=100.0, hashes=same, size=900),
        _fake_video("V02", "h2", dur=101.0, hashes=same, size=1000),
        _fake_video("V03", "h3", dur=300.0, hashes=[0b01010101] * 3, size=800),
    ]
    groups = D.dedupe_files(vids)
    check("近似重复被识别", len(groups["near"]) == 1)
    check("时长差太大不算重复", vids[2]["duplicate_of"] is None)


def test_dedupe_content():
    txt = "先选章纲再续写正文，然后检查冲突点，最后只改冲突不全文重写。" * 3
    segs = [{"start": i * 2.0, "end": i * 2.0 + 2, "text": txt} for i in range(3)]
    vids = [_fake_video("V01", "c1", segs=segs), _fake_video("V02", "c2", segs=segs),
            _fake_video("V03", "c3", segs=[{"start": 0, "end": 1, "text": "完全无关的一段话内容"}] * 3)]
    groups = D.dedupe_content(vids)
    check("逐字稿相同被判内容重复", len(groups["content"]) == 1)
    check("无关视频不受影响", vids[2]["duplicate_of"] is None)


def test_merge_corpus():
    common = {"start": 0.0, "end": 2.0, "text": "欢迎大家来到本课程今天我们讲提示词"}
    vids = [
        _fake_video("V01", "m1", segs=[common,
                                       {"start": 3.0, "end": 5.0, "text": "第一步是选章纲"}]),
        _fake_video("V02", "m2", segs=[dict(common),
                                       {"start": 3.0, "end": 5.0, "text": "第二步是给约束"}]),
    ]
    out = D.merge_corpus(vids)
    texts = [p["text"] for p in out["paragraphs"]]
    check("重复开场只保留一次", sum("欢迎大家" in t for t in texts) == 1)
    check("独有内容都保留", any("第一步" in t for t in texts) and any("第二步" in t for t in texts))
    check("统计里有丢弃计数", out["stats"]["dropped_repeat"] >= 1)


# ---------------- 数字抽取 ----------------

def test_extract_numbers():
    segs = [
        {"start": 0, "end": 2, "text": "会员是29元一个月，包含30万字"},
        {"start": 2, "end": 4, "text": "听书是2.5倍的消耗倍率"},
        {"start": 4, "end": 6, "text": "免费额度是3次"},
    ]
    vids = [_fake_video("V01", "n1", segs=segs)]
    nums = D.extract_numbers(vids)
    kinds = {n["kind"] for n in nums}
    values = " ".join(n["value"] for n in nums)
    check("抽到价格", "价格" in kinds and "29元" in values)
    check("抽到字数", "字数" in kinds and "30万字" in values)
    check("抽到倍数", "倍数" in kinds and "2.5倍" in values)


def test_hotwords():
    pairs = D.parse_hotwords("新约写作=星月写作,新约=星月,坏项,=x,a=")
    check("解析忽略非法项", len(pairs) == 2, str(pairs))
    check("长词优先替换", pairs[0][0] == "新约写作")
    vids = [_fake_video("V01", "hw", segs=[
        {"start": 0, "end": 1, "text": "欢迎来到新约写作，新约很好用"}])]
    n = D.apply_hotwords(vids, pairs)
    got = vids[0]["segments"][0]["text"]
    check("热词替换生效", got == "欢迎来到星月写作，星月很好用", got)
    check("替换次数统计", n == 2, str(n))
    check("幂等", D.apply_hotwords(vids, pairs) == 0)


def test_product_signal():
    segs = [{"start": i, "end": i + 1,
             "text": "会员 套餐 充值 付费 价格 额度 消耗 界面 按钮 面板 点击 功能 设置 账号"}
            for i in range(3)]
    vids = [_fake_video("V01", "p1", segs=segs)]
    sig = D.product_signal(vids)
    check("产品信号命中", sig["likely"] is True and sig["score"] > 12)


# ---------------- JSON 解析 ----------------

def test_parse_json():
    check("代码块 JSON", D.parse_json('```json\n{"a": 1}\n```') == {"a": 1})
    check("带前后废话", D.parse_json('好的，结果如下：{"a": 1} 希望有帮助') == {"a": 1})
    check("尾逗号容错", D.parse_json('{"a": [1, 2,],}') == {"a": [1, 2]})
    check("中文引号容错", D.parse_json('{“a”: 1}') == {"a": 1})


# ---------------- 画面指纹 ----------------

def test_dhash():
    try:
        from PIL import Image
    except ImportError:
        check("dhash（跳过：没装 Pillow）", True)
        return
    with tempfile.TemporaryDirectory() as td:
        p1 = Path(td) / "a.jpg"
        p2 = Path(td) / "b.jpg"
        img = Image.new("L", (64, 64))
        for x in range(64):
            for y in range(64):
                img.putpixel((x, y), 255 if x < 32 else 0)
        img.save(p1)
        img.resize((32, 32)).save(p2)  # 缩放后仍应高度相似
        h1, h2 = D.dhash64(p1), D.dhash64(p2)
        check("dhash 非零", h1 != 0)
        check("缩放后指纹接近", D.hamming(h1, h2) <= 2, f"hamming={D.hamming(h1, h2)}")


# ---------------- 渲染（Markdown 不炸） ----------------

def _minimal_result():
    v = _fake_video("V01", "r1", segs=[{"start": 0, "end": 2, "text": "测试内容"}])
    v["analysis"] = {"gist": "讲了一件事", "sections": [], "steps": [], "quotes": [],
                     "rules_and_numbers": [], "ui_evidence": [], "pitfalls": [],
                     "claims": [], "concepts": [], "key_points": [],
                     "one_line_takeaway": "记住这句", "_source": "llm"}
    return {
        "batch": "测试批次", "created_at": "2026-01-01 00:00", "source_folder": "/tmp",
        "category": "测试", "videos": [v],
        "dedupe": {"exact": [], "near": [], "content": []},
        "corpus": {"segments": [], "paragraphs": [
            {"video_id": "V01", "video_title": "V01", "start": 0.0, "end": 2.0, "text": "测试内容"}],
            "stats": {"total": 1, "kept": 1, "dropped_repeat": 0,
                      "dropped_boilerplate": 0, "paragraphs": 1, "chars_kept": 4},
            "redundant_by_video": {"V01": 0}},
        "synthesis": {"corpus_gist": "g", "what_this_is": "w", "topics": [],
                      "knowledge_units": [], "redundancy": {}, "conflicts": [],
                      "missing_pieces": [], "learning_path": [], "master_summary": "s"},
        "methodology": {"master_method": {"name": "M", "stages": []},
                        "method_cards": [{"name": "卡1", "layer": "流程",
                                          "procedure": [{"step": "a", "why": "b", "verify": "c"}],
                                          "anti_patterns": ["x"], "transfer": ["y"],
                                          "evidence": [{"video_id": "V01", "time": "00:01", "quote": "q"}]}],
                        "mental_models": [], "decision_table": [], "quality_bar": [],
                        "levels": {"L0_facts": ["f"]}},
        "product": {"is_product": True, "confidence": 0.8, "product_name": "P",
                    "positioning": {"what": "w"}, "architecture": {"mermaid": "graph TD\nA-->B"},
                    "business_model": {"pricing": [{"plan": "月", "price": "29元"}]},
                    "clone_playbook": {"must_have": ["a"]}, "unknowns": ["u"]},
        "numbers": [{"kind": "价格", "value": "29元", "context": "会员29元",
                     "video_id": "V01", "time": "00:01"}],
        "llm_info": {}, "stages": [],
    }


def test_render():
    r = _minimal_result()
    for fn, name in ((D.render_overview, "总览"), (D.render_transcript, "逐字稿"),
                     (D.render_methodology, "方法论"), (D.render_product, "产品逆向"),
                     (D.render_evidence, "证据"), (D.render_dedupe, "去重报告")):
        try:
            text = fn(r)
            ok = isinstance(text, str) and len(text) > 50 and "None" not in text
        except Exception as e:  # noqa: BLE001
            ok, text = False, f"{type(e).__name__}: {e}"
        check(f"渲染 {name}", ok, text[:120] if not ok else "")


def test_emit():
    r = _minimal_result()
    with tempfile.TemporaryDirectory() as td:
        out = D.emit(r, Path(td), log=lambda *_: None)
        files = {Path(p).name for p in out.values() if Path(p).suffix in (".md", ".json")}
        want = {"00_总览.md", "01_逐字稿合并.md", "02_方法论.md",
                "03_产品逆向.md", "04_证据索引.md", "dedupe_report.md", "distill.json"}
        check("产出文件齐全", want <= files, str(want - files))
        data = json.loads((Path(td) / "distill.json").read_text())
        check("distill.json 可解析", data["batch"] == "测试批次" and len(data["videos"]) == 1)
        check("transcripts 目录生成", (Path(td) / "transcripts").is_dir())


def main():
    groups = [
        ("标题清洗", test_clean_title),
        ("指纹与相似度", test_shingles),
        ("文本归一化", test_norm_text),
        ("噪声判定", test_boilerplate),
        ("段落化", test_group_paragraphs),
        ("去重 · 文件级", test_dedupe_exact),
        ("去重 · 近似级", test_dedupe_near),
        ("去重 · 内容级", test_dedupe_content),
        ("合并 · 语句级去重", test_merge_corpus),
        ("数字抽取", test_extract_numbers),
        ("热词纠正", test_hotwords),
        ("产品信号", test_product_signal),
        ("JSON 解析", test_parse_json),
        ("画面指纹", test_dhash),
        ("Markdown 渲染", test_render),
        ("落盘产出", test_emit),
    ]
    for name, fn in groups:
        print(f"\n[{name}]")
        fn()

    print(f"\n通过 {len(PASS)} / 失败 {len(FAIL)}")
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print(f"  - {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
