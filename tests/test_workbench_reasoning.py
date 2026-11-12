"""Offline tests of explicit provider policy and evidence ordering. No network."""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from v2t import workbench_reasoning as r

with tempfile.TemporaryDirectory(prefix="v2t-reason-") as temp:
    orig_config = r.CONFIG
    orig_chat = r._chat
    r.CONFIG = Path(temp) / "provider.json"
    try:
        try:
            r.save_provider("http://example.com/v1", "model", "secret")
            raise AssertionError("Cleartext remote URL should fail")
        except ValueError:
            pass
        info = r.save_provider("http://127.0.0.1:1234/v1", "test-model", "")
        assert info["configured"] and info["transport"] == "local"
        assert r.CONFIG.stat().st_mode & 0o077 == 0

        sources = {
            "segments": [{"start": 10, "text": "第二条语音"},
                         {"start": 1, "text": "第一条语音"}],
            "ocr_segments": [{"start": 5, "text": "画面中的文字"}],
        }
        lines = r._source_lines(sources)
        assert "ASR-00002" in lines[0] and "OCR-00001" in lines[1]
        assert "ASR-00001" in lines[2]
        r._chat = lambda system, prompt, max_tokens=3500: "已核对来源 [ASR-00002]、[OCR-00001]"
        result = r.generate(sources, "测试视频")
        assert result["status"] == "DONE"
        assert result["source_scope"] == "asr_ocr_text_only"
        assert result["evidence_lines"] == 3
        assert "测试视频" in result["analysis_markdown"]

        # Editing a different external endpoint may not reuse the old key.
        try:
            r.save_provider("https://different-provider.example/v1", "model", "")
            raise AssertionError("Must not reuse a credential across providers")
        except ValueError:
            pass
    finally:
        r.CONFIG = orig_config
        r._chat = orig_chat

print("DRE reasoning provider: PASS (consent policy inputs, ordering, no network)")
