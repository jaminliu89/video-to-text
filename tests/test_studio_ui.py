"""DRE Studio HTTP-level smoke, no inference and no network.

Uses a fake mp4 blob to exercise ingestion and evidence, not media decoding.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi.testclient import TestClient
from nicegui import app
from v2t import workbench_service as svc
from v2t import studio_api as studio
from v2t import workbench_ui as legacy_api  # register /api/v1 in the same app as production

with tempfile.TemporaryDirectory(prefix="dre-studio-api-") as tmp:
    base = Path(tmp)
    svc.STATE = base / "state"
    svc.STAGING = svc.STATE / "imports"
    svc.DB = svc.STATE / "workbench.sqlite3"
    svc._initialized = False
    svc.initialize_schema_once()
    studio.ensure_tables()

    client = TestClient(app, base_url="http://127.0.0.1:8765")
    page = client.get("/studio")
    assert page.status_code == 200, page.text[:300]
    assert "DRE Studio" in page.text
    assert "dre_studio" in page.cookies

    css = client.get("/studio-assets/styles.css")
    js = client.get("/studio-assets/app.js")
    assert css.status_code == 200 and js.status_code == 200

    bootstrap = client.get("/ui-api/bootstrap")
    assert bootstrap.status_code == 200, bootstrap.text[:300]
    assert bootstrap.json()["mode"] == "local_first"

    # Malicious cross-origin POST must fail even if the browser has a cookie.
    bad = client.post("/ui-api/import/path", json={"path": str(base)},
                      headers={"origin":"https://other.example","x-dre-ui":"1"})
    assert bad.status_code == 403

    headers={"origin":"http://127.0.0.1:8765","x-dre-ui":"1",
             "x-file-name":"upload-sample.mp4"}
    uploaded=client.post("/ui-api/upload",content=b"fake-video-bytes-for-import",
                         headers=headers)
    assert uploaded.status_code == 200,uploaded.text[:500]
    asset=uploaded.json()
    assert asset["kind"] == "video"
    assert client.get("/ui-api/media/"+asset["id"]+"/stream").status_code == 200

    with svc._db() as db:
        db.execute(
          "INSERT INTO jobs (id,media_id,kind,engine,state,result,created_at,updated_at)"
          " VALUES(?,?,?,?,?,?,?,?)",
          ("test-asr",asset["id"],"transcribe","fake","done",
           json.dumps({"segments":[{"start":0,"end":1.2,"text":"旧识别文本"}]},
                      ensure_ascii=False),svc.now(),svc.now())
        )

    before=client.get("/ui-api/jobs/test-asr/result")
    assert before.status_code == 200
    assert before.json()["data"]["segments"][0]["text"] == "旧识别文本"

    correction=client.put("/ui-api/jobs/test-asr/evidence",
       headers=headers, json={"channel":"segments","index":0,"text":"已校对的文本"})
    assert correction.status_code == 200,correction.text[:400]
    after=client.get("/ui-api/jobs/test-asr/result")
    assert after.json()["data"]["segments"][0]["text"] == "已校对的文本"

    with svc._db() as db:
        raw=db.execute("SELECT result FROM jobs WHERE id='test-asr'").fetchone()["result"]
    assert json.loads(raw)["segments"][0]["text"] == "旧识别文本"

    export=client.get("/ui-api/jobs/test-asr/export?format=md")
    assert export.status_code == 200
    assert "已校对的文本" in export.text

    # API endpoints for external agents must remain separately authenticated.
    unauthorized=client.get("/api/v1/jobs")
    assert unauthorized.status_code == 401
    assert client.get("/ui-api/jobs").json()["jobs"][0]["id"] == "test-asr"

print("DRE Studio HTTP: PASS (session, upload, cross-origin, reviews, export)")
