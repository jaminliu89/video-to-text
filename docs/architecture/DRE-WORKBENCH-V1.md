# DRE Media Workbench — Product UI & architecture V1

Status: **DRAFT / NOT_READY FOR MERGE**. This is an implemented preview surface,
not a verified macOS production release.

## Product contract

User journey: **Import media → choose analysis → inspect time-aligned evidence → retrieve deliverables**.

- Primary object is a **media asset**, not an LLM chat thread.
- Main screen is an analysis studio: asset header, real job queue, video player,
  seekable ASR evidence, results preview.
- Library lists imported assets and opens any asset in the same studio.
- Tasks are persisted in SQLite and survive browser reload; running processes
  interrupted by app restart are marked interrupted and can be retried.
- Capability Centre reports real ASR registration, local API token and explicitly
  shows unintegrated features. Never fabricate completion or model availability.
- UI, REST and optional MCP adapter all call the same workbench service.
- Default inference policy is local-only; current distill job uses --no-llm.
  Cloud augmentation requires an explicit provider policy and separate review.
- The existing legacy NiceGUI app, CLI, tests and DMG entrypoint are preserved.

## Open-source engineering decisions

| Concern | Decision |
|---|---|
| Backend | Retain Python / NiceGUI / existing CLI; FastAPI routes via NiceGUI app |
| UI | New NiceGUI responsive workbench entrypoint; do not rewrite in React before usability tests |
| State | SQLite WAL, single machine, serial background worker |
| Inference | Reuse existing local ASR adapters; no implicit paid API fallback |
| MCP | SDK v2 MCPServer adapter using authenticated loopback REST API |
| Go / LangGraph | Not needed for a local deterministic media pipeline |
| WASM | Optional for heavier waveform/interactive media widgets, not needed for initial UI |
| Apple Vision | Swift native OCR adapter + Python job implemented, **macOS runtime verification pending** |
| Qwen3-VL / MLX | Candidate visual model, **not yet integrated** |

## Product UI hierarchy

The homepage opens Studio, not a toolbox. Four navigation areas:

1. **Studio**: active media, playable video, tasks, seekable ASR and OCR evidence.
2. **Library**: registered local videos and folder-based projects.
3. **Tasks and Deliverables**: persistent jobs, retries, complete exports.
4. **Capabilities**: installed models and optional API/MCP access.

The primary action is transcription; OCR, storyboard and evidence composition
are secondary. All real content comes from persisted job results, not mock data.

## Start

Run from the repository root:

~~~bash
python -m pip install -r requirements.txt
python workbench.py
~~~

Open http://127.0.0.1:8765 . The legacy entrypoint remains `python gui.py`.

Optional stdio MCP adapter (Python SDK v2):

~~~bash
python -m pip install 'mcp>=2,<3'
python -m v2t.workbench_mcp
~~~

API requests require `Authorization: Bearer <token>`.
The token is stored with mode 0600 in
`~/Library/Application Support/VideoToText/workbench/api_token`.
Never commit or log this token.

## API

- `GET /api/v1/capabilities`
- `GET /api/v1/media`
- `POST /api/v1/media` with `{"path":"/absolute/media/path"}`
- `POST /api/v1/jobs` with `{"media_id":"...", "kind":"transcribe", "engine":"auto"}`
- `GET /api/v1/jobs`, `GET /api/v1/jobs/{job_id}` (status only)
- `GET /api/v1/jobs/{job_id}/result?channel=segments&offset=0&limit=50`
- For OCR, submit `kind=ocr` on macOS with Xcode Command Line Tools
- `POST /api/v1/jobs/{job_id}/cancel` (only queued jobs)

Note: `POST /api/v1/media` is restricted to `V2T_AGENT_ALLOWED_ROOTS`
as an explicit colon-separated allowlist. The interactive Web UI can import
other local paths through direct user action.

## Acceptance gates before replacing the legacy UI

1. Linux syntax/import/contract tests; macOS-ARM runtime smoke.
2. Real video ASR, media seek, artifact retrieval, JSON CLI parity.
3. Browser usability: first import discoverable, keyboard, overflow, 390/768/1440px.
4. API token, media path traversal, symlink/allowlist, no-cloud fallback tests.
5. Crash and restart: queued/running job recovery, retried tasks.
6. Existing GUI / CLI / DMG workflows stay green.
7. Apple Vision OCR is now implemented but needs macOS hardware verification;
   local VLM, cloud reasoning with explicit approval and full-fidelity visual
   evidence still require separate implementation and E2E acceptance.
