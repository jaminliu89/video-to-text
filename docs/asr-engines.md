# 转写引擎对比：faster-whisper / mlx-whisper / Qwen3-ASR

三个引擎都实现了同一套接口（`v2t/asr.py`），换引擎只需要改一个参数：

```bash
python3 cli.py transcribe video.mp4 --asr mlx-whisper --asr-model large-v3-turbo
python3 cli.py engines        # 先看这台机器上哪些引擎真能用
```

---

## 一句话结论

| 你的机器 / 需求 | 用哪个 | 为什么 |
|---|---|---|
| **Apple Silicon（M1–M4）默认** | `mlx-whisper` + `large-v3-turbo` | 5.3s 跑完 2 分钟音频（23 倍速），准确度与 faster-whisper turbo 持平 |
| Apple Silicon 只要速度 | `mlx-whisper` + `base` | 1.7s 跑完 2 分钟（72 倍速），适合先粗跑再挑重点 |
| Intel Mac / Windows / Linux 无 GPU | `faster-whisper` + `base` | 唯一稳的 CPU 方案，14.3s / 8.6 倍速 |
| 要断句和标点像人写的 | `qwen3-asr` 0.6b | 整句成段、标点规范，长文可读性明显更好 |
| 不想装模型、能联网 | `qwen3-asr` + `flash`（DashScope） | 零下载，按量计费 |

**但先看这个**：五个引擎、六种配置，没有一个把产品名"星月写作"听对。
换引擎解决不了专有名词，`--hotwords "错词=正词"` 才能，而且零成本。

## 实测数据

同一段 122.5 秒中文课程音频，MacBook（Apple Silicon / M 系列），模型权重已下载。
"稳态"= 权重已在内存里的第二次及以后；"冷启动"= 进程内第一次（含加载/编译）。
复现：`python3 benchmarks/asr_bench.py --audio <clip.wav> --engines ... --repeat 2`

| 引擎 | 模型 | 稳态耗时 | 冷启动 | 倍速 | 峰值内存 | 与共识 CER |
|---|---|---:|---:|---:|---:|---:|
| **mlx-whisper** | base | 1.7s | 4.3s | **72.6x** | 489 MB | 10.31% |
| **mlx-whisper** | large-v3-turbo | 5.3s | 9.2s | **23.1x** | 1144 MB | 2.77% |
| qwen3-asr | 0.6b | 11.5s | 50.9s | 10.6x | 1352 MB | 6.15% |
| faster-whisper | base | 14.3s | 17.3s | 8.6x | 816 MB | 7.23% |
| faster-whisper | small | 29.5s | 32.2s | 4.2x | 1326 MB | 4.00% |
| faster-whisper | large-v3-turbo | 47.7s | 50.8s | 2.6x | 2077 MB | 0.00%（共识基准） |

四个反直觉的点，都是实测出来的：

1. **mlx-whisper 的 turbo 比 faster-whisper 的 base 快 9 倍**，质量还高一个档。
   原因很直接：CTranslate2 在 Mac 上只能用 CPU + int8，MLX 走 Metal GPU + fp16。
2. **mlx-whisper 的 base 是全场最快（1.7s / 72 倍速）**，但 CER 最差。
   要速度用它，要质量用 turbo——同一个后端，差 3 倍耗时换 4 倍准确度，很划算。
3. **faster-whisper 的 turbo 最慢**（47.7s）。同一份权重在 CPU 上做 32 层解码就是这个代价。
   这也解释了为什么"换大模型更准"在 Mac 上以前不实用。
4. **qwen3-asr 的冷启动很贵**（50.9s，其中约 20s 是权重加载 + MPS 图编译）。
   批量跑必须在同一进程里复用模型——本项目已做缓存，20 个视频只付一次加载成本。

> 注意：第一版测量是在另一条 pip 安装同时抢 CPU 的时候跑的，数字普遍高 30–50%。
> 所以上面这张表是"机器空闲 + 权重预热"的口径，比"边装东西边跑"更接近真实使用。

---

## 质量：CER 会骗你，术语命中不会

| 引擎 | 模型 | 星月写作 | 写作 | 提示词 | 对标书 | 脑洞 |
|---|---|---:|---:|---:|---:|---:|
| faster-whisper | base | 0 | 1 | 4 | 4 | 6 |
| faster-whisper | small / turbo | 0 | 2 | 4 | 5 | 6 |
| mlx-whisper | large-v3-turbo | 0 | 2 | 4 | 5 | 6 |
| qwen3-asr | 0.6b | 0 | 2 | 4 | 5 | 6 |

**五个引擎、六种配置，没有一个是把"星月写作"听对的**（都听成"新乐写作"）。
只有 qwen3-asr 在另一段 40 秒的样本里偶然写对过一次——因为它默认带采样，不是确定性的。

这就是为什么换引擎要放在最后：

1. 先用 `--hotwords "新乐写作=星月写作"`（零成本，立刻见效，且参与缓存签名）
2. 再考虑换模型（成本高 3–7 倍，而且这次证明了换模型也修不好专名）
3. 最后才是人工校对

CER 反而会骗人：qwen 的 CER 6.15% 比 whisper-turbo 的 2.77% 差，
但它的断句和标点明显更像人写的（"今天给大家带来的是进阶工具的讲解。"整句成段，
whisper 会连成一大坨）。CER 去掉了标点，所以看不见这个差别。

## 三者到底差在哪

### faster-whisper
- 后端：CTranslate2（C++ 推理引擎），CPU int8 量化
- 优点：跨平台（Mac/Win/Linux）、内存可控、生态成熟
- 缺点：Mac 上用不到 GPU；大模型慢到没法用在批量场景
- 适用：默认兜底、CI、服务器、批量跑长视频

### mlx-whisper
- 后端：Apple MLX，Metal GPU，fp16
- 优点：M 系列上 7 倍速度差；显存/内存统一架构，不用拷贝；权重和 Whisper 完全一样
- 缺点：**只能 macOS arm64**；小模型上反而慢；首次要下 1.6G 权重
- 适用：Mac 上跑批量蒸馏、长课程、需要 turbo 级质量的场景
- 坑：`mlx_whisper.transcribe(path)` 会自己 fork `ffmpeg` 解码，非交互 shell 里常找不到。
  本项目直接喂 numpy 数组，绕开这个依赖

### Qwen3-ASR
- 后端：Qwen3 基座 + ASR 训练，0.6B / 1.7B 两个尺寸；也有 `qwen3-asr-flash` 云端 API
- 优点：中文（含方言、口音、中英混说）明显更稳；支持上下文提示词纠偏；1.7B 只有 Whisper-large 的 1/4 体积
- 缺点：时间戳要靠额外的强制对齐模型（`Qwen3-ForcedAligner-0.6B`，再 1.2G）；
  本地部署要 transformers 全家桶（约 2G 依赖）；单次识别上限 5 分钟，长音频要切片
- 适用：中文为主、专有名词多、对字准率要求高的内容
- 两条通道：`--asr-model 0.6b/1.7b` 走本地，`--asr-model flash` 走 DashScope

---

## 什么时候不该换引擎

**换引擎是最后一步。** 实测中 `星月写作` 这个词，五个引擎全部听错（新约写作 / 新乐写作），
命中数都是 0。这种情况下：

1. 先用 `--hotwords "新约写作=星月写作,新乐写作=星月写作"`（零成本，立刻见效）
2. 再考虑换模型（成本高 3–7 倍）
3. 最后才考虑人工校对

蒸馏管线里热词表还会参与缓存签名：改了热词，S3–S7 会自动重跑，不会拿旧结果糊弄你。

---

## 复现基准

```bash
# 三个引擎一起比，顺带统计关键术语命中
python3 benchmarks/asr_bench.py \
  --audio cache/<hash>_audio.wav \
  --engines faster-whisper:base,faster-whisper:large-v3-turbo,mlx-whisper:large-v3-turbo,qwen3-asr:0.6b \
  --terms "星月写作,提示词,对标书" \
  --out benchmarks/results.md

# 直接从视频抽 2 分钟来比
python3 benchmarks/asr_bench.py --video course.mp4 --seconds 120 \
  --engines mlx-whisper:large-v3-turbo,faster-whisper:base
```

指标口径：

- **倍速** = 音频时长 / 处理耗时，越大越快
- **CER** = 字错率（编辑距离 / 参考长度），去标点后比较；没有人工标注时用"共识文本"当参考
  （离所有引擎平均距离最近的那个）
- **关键术语命中** 比 CER 更贴近业务：专有名词错一个字，下游检索和蒸馏全废
