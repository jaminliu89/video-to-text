# SEP #06 — 关键旧功能 smoke

| 项 | 值 |
|---|---|
| 产品 | video-to-text |
| 入口脚本 | `scripts/sep_smoke.py` |
| 环境 | 与 CI `check` job 一致：Python + `requirements.txt` + ffmpeg（蒸馏单测可能用到） |
| 不覆盖 | GUI、DMG、联网 ASR、真实视频端到端转写 |

## 路径

| feature_id | 断言 |
|---|---|
| `asr-transcribe` | 六引擎注册表；非 Apple Silicon 上 mlx 不可用；faster-whisper 可用；未知引擎抛错；`cli.py engines --json` 可解析 |
| `distill-pipeline` | 完整运行 `tests/test_distill_units.py` 且输出含「失败 0」 |

## 命令

```bash
python scripts/sep_smoke.py
echo $?   # 必须为 0
```

CI：`.github/workflows/ci.yml` 的 `check` job 在单测后执行同一命令。

未运行写 `NOT_RUN`；失败不得改阈值或删断言换绿灯。
