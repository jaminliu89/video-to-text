# DRE Media Studio V2 — 产品设计与验收契约

状态：**IMPLEMENTED ON DRAFT PR · NOT_RELEASED**  
目标分支：\`feat/dre-product-workbench\`  
产品原则：用户操作的对象是视频、证据与成品，不是模型或脚本。

## 体验主线

1. **媒体总览**：一眼看到项目、最新状态。唯一主行动是「导入素材」。
2. **导入**：拖入视频（复制到本地工作台资产目录）；课程文件夹可用本机路径登记。
3. **分析**：一个主按钮「开始完整分析」调用原有本地管线，ASR / OCR / 故事板独立操作是次入口。
4. **证据**：视频播放器、语音与 OCR 两条时间轴、可点击跳转的带时间戳文本；校对结果作为 overlay，原始模型输出不覆盖。
5. **撰写**：只有本地证据汇总完成后才能请求云端 API。显示模型、域名、发送字符量和范围，用户针对当前视频明确同意。
6. **交付**：Markdown 阅读、修改保存、可下载 Markdown/JSON/TXT/SRT；任务失败、队列状态有真实数据，不展示虚假的百分比。
7. **Agent**：MCP/REST 读取同一任务和分段证据；不复制本地模型实现。

## UI 决策

- 浏览器页面采用原生 HTML + CSS + JS，无打包工具链。既避免在 Mac 本地多出 Node 常驻开发服务，也摆脱旧 NiceGUI 拼组件的界面局限。
- NiceGUI 继续提供已有 Python Web 运行容器和旧界面（\`/legacy\`）；默认 \`/\` 跳转 \`/studio\`。
- 页面结构固定为「总览、分析工作台、文稿与交付、任务中心、模型与接入」。
- 主视图视觉权重：原视频 > 证据时间轴 > 转写与画面文字 > 作业状态 > 技术配置。
- 提供响应式布局和键盘 \`Cmd/Ctrl+K\` 项目查找；无外部 CDN。
- 禁止无实际执行效果的 UI 按钮。能力未接通时显示未就绪。

## 实现位置

- \`webui/index.html\`：语义化工作台壳
- \`webui/styles.css\`：品牌、布局、导航、响应式组件
- \`webui/core.js\`：状态、API、安全转义、操作反馈
- \`webui/app.js\`：五个产品视图与核心交互
- \`v2t/studio_api.py\`：浏览器上传、原始媒体流、审核存储、下载、用户会话
- \`v2t/workbench_service.py\`：模型适配与统一持久化任务执行
- \`v2t/workbench_reasoning.py\`：授权后文本证据推理
- \`v2t/workbench_mcp.py\`：兼容 Agent 的 MCP 接口

## 启动

~~~bash
git fetch origin feat/dre-product-workbench
git switch feat/dre-product-workbench
python -m pip install -r requirements.txt
python workbench.py
~~~

默认首页：\`http://127.0.0.1:8765/\`  
产品页面：\`http://127.0.0.1:8765/studio\`  
旧版保留：\`http://127.0.0.1:8765/legacy\`  
原有 \`python gui.py\` 不变。

## 数据与权限约束

- 本地媒体仅从浏览器会话读取；\`ui-api\` 的写操作验证 SameSite Cookie + Origin + \`X-DRE-UI\`。
- 外部 Agent 走 Bearer Token，导入路径必须位于显式 \`V2T_AGENT_ALLOWED_ROOTS\` 中。
- 浏览器上传受 \`V2T_MAX_UPLOAD_GB\` 限额，当前会在本地工作区创建内容哈希副本。
- 大模型 API 密钥在本机保存，云端增强推理必须逐项目授权，锁定本次授权的目标模型与服务端点。
- 保留 ASR/OCR 原文、校对层与 AI 生成文稿三份独立数据；编辑不篡改识别证据。

## 合并与发布门禁

| 项目 | 验收证据 |
|---|---|
| Python 与 JS 语法 | CI / syntax |
| 旧版 CLI 与 ASR 回归 | CI / units + smoke |
| UI 后端 HTTP 关键路径 | CI / test_studio_ui.py |
| Apple Vision OCR 编译 | macOS ARM CI |
| 真实视频 ASR、OCR 和长视频内存 | MacBook M2 Pro 实机记录 |
| 视觉截图 1440/768/390 与键盘可用性 | 浏览器截图 / 人工或自动验收 |
| 浏览器导入、播放、编辑、导出 | 实机 E2E |
| MCP 双客户端 | Codex + 独立客户端调用日志 |
| 远端授权 / 不外发测试 | 网络隔离 / 审计记录 |
| 安装包 | 旧 DMG 回归 + 新产品打包评估 |

没有获得对应证据的项目不得标记通过，不能把 CI 语法成功误报为产品稳定。 **本 PR 在这些门禁通过前保持 Draft。**

## 尚未声称完成

- Qwen3-VL 视觉语义模型的真实推理适配
- 真实多机位自动切点时间精度
- 音效分类 / 说话人识别
- Mac 真实视频识别精度指标
- 独立签名/公证后的可分发 DMG

这些属于真实的运行能力，不能由漂亮的 UI 或虚构测试数据代替。
