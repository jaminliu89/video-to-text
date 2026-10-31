# ASR 引擎基准

- 音频：`109b6cad7404_audio.wav`（122.5s）
- 时间：2026-10-31 11:09
- 机器：darwin arm64

## 速度与内存

| 引擎 | 模型 | 稳态耗时 | 冷启动 | 倍速 | 峰值内存 | 段数 | 字数 |
|---|---|---:|---:|---:|---:|---:|---:|
| mlx-whisper | base | 1.7s | 4.3s | 72.6x | 489 MB | 63 | 652 |
| mlx-whisper | large-v3-turbo | 5.3s | 9.2s | 23.1x | 1144 MB | 58 | 655 |
| qwen3-asr | 0.6b | 11.5s | 50.9s | 10.6x | 1352 MB | 21 | 657 |
| faster-whisper | base | 14.3s | 17.3s | 8.6x | 816 MB | 62 | 649 |
| faster-whisper | small | 29.5s | 32.2s | 4.2x | 1326 MB | 59 | 653 |
| faster-whisper | large-v3-turbo | 47.7s | 50.8s | 2.6x | 2077 MB | 53 | 650 |

## 质量（CER，越低越好）

共识文本取自 `faster-whisper:large-v3-turbo`（离所有引擎平均距离最近）。

| 引擎 | 模型 | 与共识 CER | 平均两两 CER |
|---|---|---:|---:|
| faster-whisper | large-v3-turbo | 0.00% | 6.09% |
| mlx-whisper | large-v3-turbo | 2.77% | 6.11% |
| faster-whisper | small | 4.00% | 6.55% |
| qwen3-asr | 0.6b | 6.15% | 7.61% |
| faster-whisper | base | 7.23% | 7.67% |
| mlx-whisper | base | 10.31% | 9.66% |

## 关键术语命中（业务准确度）

| 引擎 | 模型 | 星月写作 | 写作 | 提示词 | 对标书 | 脑洞 | 合计 |
|---|---|---:|---:|---:|---:|---:|---:|
| faster-whisper | base | 0 | 1 | 4 | 4 | 6 | 15 |
| faster-whisper | small | 0 | 2 | 4 | 5 | 6 | 17 |
| faster-whisper | large-v3-turbo | 0 | 2 | 4 | 5 | 6 | 17 |
| mlx-whisper | large-v3-turbo | 0 | 2 | 4 | 5 | 6 | 17 |
| mlx-whisper | base | 0 | 0 | 4 | 5 | 6 | 15 |
| qwen3-asr | 0.6b | 0 | 2 | 4 | 5 | 6 | 17 |
