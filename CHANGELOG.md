# 更新记录

所有用户可见的变更都记录在此。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/)，版本遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### 工作流 · 开始节点优化
- **结构化入参定义**：开始节点支持像其它节点一样配置带「类型」的参数，而非仅逗号分隔字段名
  - 字段属性：参数名、类型（string / text / number / integer / float / boolean / select / multi_select / date / datetime / time / file / password / email / url / object / array）、默认值、是否必填、选项（select 用）
  - 后端按类型做强制转换与校验：number/integer/float→数值、boolean→布尔、select→选项校验回退首个、multi_select→逗号分隔数组、date/datetime/time/file/password/email/url/text/string→文本、object/array→JSON 对象/数组
  - 必填项缺失时执行报错并提示字段名
- **类型二级选择**：类型下拉改为「分组 + 具体类型」两级联动，文本/数值/布尔/选择/日期时间/文件/复合 7 大分组，避免 17 个类型平铺难找
- **运行时动态表单**：运行复杂工作流前，按 start 节点 schema 弹出对应类型输入框（数字框 / 勾选 / 下拉 / 文件 / 多选等），填完即跑
- **新增 API**：`GET /api/workflows/{wid}/input_schema` 返回开始节点入参 schema，供前端动态生成表单
- **向后兼容**：保留旧版 `input_fields`（逗号分隔字符串）配置，作为 string 类型字段处理

## [0.10.0] - 2026-08-13

### 蜂群多 Agent（agno 引擎 · 更快）
- **引入 agno 轻量框架**：多 Agent 协作底层改用 agno（Python 3.9 兼容的主流最快轻量 agent 框架，OpenAI 兼容直连 Ollama/百炼，无多余编排层，延迟更低）
- **四种蜂群模式**（多Agent协作弹窗可选）：
  - 🐝 蜂群·经理拆解：Manager 自动拆任务 → 多名成员按依赖并行执行 → 汇总（默认）
  - 🐝 蜂群·全并行：所有成员同时处理同一任务
  - 🐝 蜂群·流水线：前序成员输出作为后序输入
  - 🐝 蜂群·辩论：多视角独立作答 → 综合评审去伪存真
- **流式执行**：经理拆解计划、各成员结果、最终汇总全程 SSE 流式展示，进度可见
- **成员工具全保留**：各智能体绑定的内置工具/技能/MCP 自动包装为 agno 工具，搜索、时间、RAG 等能力在蜂群中照常可用
- **时间感知**：经理/成员/汇总均注入当前设备时间，避免模型编造日期


### 语音交互（本地 ASR + 流式朗读）
- **本地语音输入**：按住说话录音 → 后端 faster-whisper 离线转写（不依赖云端/Google），识别结果自动填入输入框；首次使用自动下载 base 模型（约 74MB，macOS/Windows/Linux 均可用，可用环境变量 `ABCODE_ASR_MODEL` 切换 stronger 模型）
- **流式朗读回复**：AI 流式输出时自动按句朗读（浏览器本地语音 speechSynthesis，跨平台含 iPad），输入条新增 🔊 喇叭开关可随时开启/关闭（localStorage 记忆）
- **手动朗读优化**：原有「朗读」按钮优先使用浏览器本地语音，后端 macOS say 作为兜底（Windows 不再报错）
- **模型时间感知**：对话/工作流/渠道均已注入当前时间，并内置 `get_current_time` 工具，模型可主动获取设备当前日期时间

### 工作流体验优化
- **测试面板「停止」按钮**：流式输出支持 AbortController 中断，点击停止后显示"已停止"状态，不再悬挂等待
- **测试历史弹窗**：每次测试自动记录输入 / 输出 / 状态 / 时间，弹窗可查看历史，点击任意一条可回填输入重新测试
- **体验配置弹窗三项修复**：添加时保留编辑中的欢迎语（不再重建弹窗丢内容）、保存时统一读取所有输入框（不再漏字段）、删除走专用函数避免被 localStorage 旧值覆盖

## [0.9.0] - 2026-08-11

### 新频道接入
- **Mattermost**：WebSocket + REST 接入（免公网），前端新增 server_url / access_token 字段
- 频道总数达 11 个运行时：钉钉 / Telegram / 飞书 / 企业微信 / Discord / OneBot / Slack / Matrix / MQTT / QQ / Mattermost

### 体验优化
- 频道列表新增「已配置 ✅ / 待配置 ⚠️」状态徽章，一眼识别哪些渠道填好了凭据
- Windows 打包脚本同步加入全部频道 SDK（PyInstaller 与 Nuitka 双脚本）

### 依赖
- requirements.txt 新增 websockets / lark-oapi / slack_sdk / paho-mqtt / qq-botpy（均可选，缺失时对应频道仅提示）

## [0.8.0] - 2026-08-11

### 新频道接入（全部免公网长连接）
- **飞书机器人**：lark-oapi WebSocket 长连接接入（免回调地址），startup 自动启动
- **企业微信**：应用消息主动推送（免公网）+ 发送 API，入站保留通用 Webhook
- **Discord**：机器人 Gateway 长连接接入（免公网）
- **OneBot（QQ 生态）**：正向 WebSocket 接入（如 go-cqhttp / NapCat），CQ 码过滤
- **Slack**：Socket Mode 接入（免公网），前端新增 App Token (xapp-) 字段
- **Matrix**：sync 长轮询接入（免公网），whoami 校验防回环
- **MQTT**：订阅-发布接入，回复带 `abcode:` 前缀防回环
- **QQ 官方机器人**：botpy WebSocket 接入（AppID/Token/Secret），支持群 @ 与私信
- 频道运行时统一在 startup 注册（钉钉/Telegram/飞书/企微/Discord/OneBot/Slack/Matrix/MQTT/QQ 共 10 个）

### 工作流体验优化
- 连线端点锚定真实端口圆心、拖线/重连同步；运行态高亮仅运行时显示、结束后自动清除；下游失败不再污染祖先节点状态
- 节点拖动时连线实时跟随（rAF + 轻量 path 更新）；跳过骨架 end 边修复顺序执行陷阱
- 修复模板 `tpl_rag` import 与 `output_variable` 缺失；aggregator separator 字段类型兼容
- 测试面板：高度限制 70vh 防出屏、节点详情折叠/展开、布局与滚动修复

### 会话增强
- 会话设置弹窗支持绑定智能体 + 工作流；输入条移除知识库/技能/MCP 入口，保留语音与文件

### Windows/macOS 桌面应用模式（非网页访问）
- **新增原生应用窗口**：Windows/macOS exe/.app 启动后打开 ABcode 桌面窗口（Windows 用系统 WebView2/EdgeChromium，macOS 用 Cocoa/WebKit，均基于 pywebview），不再依赖浏览器标签页；与 macapp（Swift+WKWebView）体验对齐
- 新增 `backend/desktop_shell.py`：同一进程内启动后端线程 + 打开应用窗口，后端就绪检测、失败自动回退浏览器模式（环境变量 `ABCODE_DESKTOP=0` 可禁用）
- 打包脚本同步：`build_windows.bat` / `build_nuitka_windows.bat` / `build_mac.sh` / `ABcode.spec` 增加 `webview`、`desktop_shell`、`dingtalk_stream` 依赖；macOS 构建版本号同步为 0.8.0
- `requirements.txt` 增加 `pywebview>=4.0`（可选依赖，未安装时回退浏览器模式）

### 钉钉频道修复（打通全链路）
- **修复钉钉回复不达**：此前消息能进、AI 能答，但回复发不回钉钉（`_conversation` 从未赋值、调用不存在的 `client.reply_text`）；现改用 SDK 官方 `self.reply_text(reply, incoming)`（走 sessionWebhook），消息出站恢复
- **修复缺 SDK 崩溃**：`dingtalk-stream` 未安装时 Stream 线程 import 失败但日志误报"已启动"；现于 requirements 声明依赖，并在启动时正确引导
- **修复频道配置保存 422**：前端 `api()` 未序列化 JSON body，保存配置时请求体为空导致后端 422「保存按钮无效」；现统一自动 `JSON.stringify`，钉钉/微信等频道配置可正常保存
- 扫码确认后仍需 AppKey/AppSecret（钉钉平台安全机制），配置保存现已可用

## [0.7.7] - 2026-08-10

### 多 Agent 协作加固
- **修复 router / planner_executor 模式不可用**：此前依赖模型严格输出 JSON，模型返回 markdown 代码块或说明文字时直接报「路由/Planner 返回格式错误」；现新增 JSON 稳健提取（容忍代码块/前后文字/自动截取花括号）
- **失败自动回退**：路由解析失败或路由到未知 Agent 时自动回退顺序执行，任何情况下保证有输出，不再卡死
- 移除 `/api/agents/multi/run` 接口重复定义（历史遗留，重复注册两次）

## [0.7.6] - 2026-08-10

### 卸载器残留修复
- **修复卸载后残留**：安装器安装在 `%LOCALAPPDATA%\ABcode`，但卸载段 `RMDir` 非递归删不掉 `data/` 子目录；且服务进程未停止时文件被锁导致删除失败
- 卸载器现在先 `taskkill` 结束 ABcode 进程，再 `RMDir /r` 递归删除整个安装目录，卸载后无任何残留

## [0.7.5] - 2026-08-10

### CI 构建修复（Windows PowerShell 中文编码陷阱）
- **根因**：GitHub Actions 的 `shell: powershell`（Windows PowerShell 5.1）读取 UTF-8 无 BOM 脚本时按 CP1252 解码，中文字符的 UTF-8 第二字节若为 `0x93`/`0x94`（如「打」「生」）会被误读为引号 `"`，直接拆断字符串导致 `TerminatorExpectedAtEndOfString`，安装包构建/冒烟测试在解析阶段即崩溃
- **修复**：CI 中所有 PowerShell 脚本块改为纯 ASCII 英文，彻底消除编码歧义；便携版使用说明文件名改为 `README.txt`
- 附带：多 Agent 协作弹窗（前端 UI + 后端 `mode` 参数覆盖编排模式）、钉钉验证脚本与公开二维码

## [0.7.4] - 2026-08-10

### Windows 便携版
- 新增便携版 zip（解压即用，无需安装器）：数据落在 exe 同目录 `data/`，删除整个目录即完成清理
- 附带使用说明 `README.txt`

## [0.7.3] - 2026-08-10

### 安装器卸载程序修复
- **修复 `WriteUninstaller` 缺失**：installer.nsi 未生成 uninstall.exe，卸载流程从未真实可用
- **修复冒烟测试漏洞**：卸载验证此前在 uninstall.exe 不存在时会静默跳过，已改为缺失即失败，防止安装器问题再次漏网

## [0.7.2] - 2026-08-10

### 安装器修复（Windows 版「根本用不了」问题彻底闭环）
- **修复全新安装启动失败**：`workflow_templates` 表新旧 schema 冲突，全新数据库启动即报 `no column named nodes`；已自动迁移重建，新装即可用
- Windows 真实安装冒烟测试通过：静默安装 → 启动 → 服务 HTTP 200 → 数据落盘 → 卸载，全链路 CI 验证

## [0.7.1] - 2026-08-10

### 原生安装包修复
- **修复 Windows/Mac 安装包缺少运行时依赖**：打包前未安装 requirements，导致运行报 `No module named fastapi`；现打包流程自动补装依赖
- 新增 Windows 真实安装冒烟测试 job，防止安装包问题再次漏网

## [0.7.0] - 2026-08-10

### Windows 打包版可用性大修
- **自动打开浏览器**：安装启动后自动打开默认浏览器进入 ABcode（无需手动找地址）
- **数据落在 exe 旁**：数据库等数据存到安装目录 `data/`，不再写入系统目录，更新/卸载/备份更可控
- **无黑窗口**：控制台窗口隐藏，后台静默运行，托盘体验更干净
- 三平台（Windows/macOS/Linux）原生安装包构建成功并发布

## [0.6.1] - 2026-08-08

### 频道消息收发（修复「扫码后无法用」）
- **根因修复**：此前扫码仅把频道标记为启用，并没有真实的消息收发通道，微信/钉钉对话自然无法使用
- **通用 Webhook 入站**：`POST /api/channels/{cid}/webhook`（JSON `{sender,text}`），收到消息自动触发 AI 对话并返回回复，本地即可用 curl 验证闭环
- **频道消息面板**：每个频道可查看收发记录、模拟发送测试对话、一键清空
- **钉钉 Stream 机器人**：在频道配置填写 AppKey/AppSecret 后，ABcode 通过钉钉官方 Stream 长连接接收消息并自动回复（免公网回调）；未填写时优雅降级提示
- **会话上下文**：每个频道的每个发送者保留最近 14 轮上下文；对话带 Agent 工具能力（联网搜索/抓取/文件/命令）
- 新增 `dingtalk-stream` 可选依赖（未安装不影响其他功能）

### 智能体增强
- 回答来源开关（show_sources）+ 回复干预；记忆历史脏数据修复（role 回填）

## [0.6.0] - 2026-08-07

### 工作流循环
- 新增**循环节点后端执行引擎**：遍历数组设置 item/index 变量、执行循环体、收集结果数组、支持嵌套循环与 end/stop 边界
- 新增 9 种缺失工作流节点：iteration 遍历 / kb_index 入库 / memory 读写清 / mcp_call / json_parse / email / webhook，循环体内 end 边界回退上一节点输出
- 补齐 9 种节点专属配置面板 + MCP 服务器下拉自动加载
- 循环节点变量提示：buildVarHints 补充 item/index/loop_id_results 变量 chips
- 新增 2 个内置工作流模板：批量处理 loop / 数据处理管道 iteration+json_parse，内置模板启动时 upsert 更新
- 工作流节点输出变量名全面对齐 + code 节点沙箱修复
- 修复工作流执行记录保存崩溃（output/error 为 dict 时 SQLite binding 失败）

### 知识库 RAG 升级
- **多知识库支持**：kb 表 + 文档归属 kb_id + 按库检索/统计/清空/导出 + 前端库选择器（新建/切换/删除）
- **检索质量优化**：BM25 检索算法 + 命中高亮 + 查询侧过滤高频单字 token + 二进制魔数检测防伪装文本
- **Markdown 标题感知分块**：按 #/##/### 标题切分，分块保留标题上下文，章节级检索精度大幅提升
- **切片打分排序增强**：混合打分（BM25 归一化 + 短语连续命中 + 覆盖率 + 位置加权）+ MMR 多样性排序 + 阈值过滤 + 前端打分条展示
- **格式扩展**：支持 PDF（pypdf）/ Word（docx）/ 30 种文本格式，上传去重（content_hash）+ 导出 JSON 备份 + 清空 + 按名称过滤
- **上下文优化**：build_context 按文档聚合去重 + snippet 命中上下文片段（带省略号）
- **前端增强**：拖拽上传 + 搜索测试面板（高亮结果预览）+ 快捷引用面板修复

### 聊天与体验
- 聊天指定知识库：工具栏知识库选择下拉（全部/单库，localStorage 持久化）+ ChatBody.kb_id + build_context 按库检索
- 修复 _pRaf 未声明导致 init 中断的严重 bug；index.html 静态资源加版本号防缓存
- 智能体测试弹窗：选择智能体后弹出专用测试对话框（显示模型/供应商/API Key 缺失警告），替代原生 prompt 输入
- 工作流画布连线重连：连线端点显示可拖动手柄，拖到新端口即重连（源端只接输出口、目标端只接输入口）
- 工作流测试面板消息渲染修复：空状态占位自动隐藏、消息容器显隐控制

### 智能体增强
- 智能体绑定增强：技能/知识库/MCP 多选绑定 + 工作流绑定（run_workflow 工具，Agent 对话中可调用工作流），详情页展示绑定名称
- 回答来源显示：SSE 结束事件携带 sources 时，气泡底部展示知识库引用（文档名+匹配度）
- 回复干预：AI 回复后出现「✏️ 干预回复」按钮，点击把内容放回输入框修改重发

### 许可
- 新增**有限开源许可证 LICENSE v1.0**：允许学习/研究/个人使用，禁止商用与闭源再分发

## [0.3.0] - 2026-08-05

### 工作流能力
- 新增**可视化工作流画布**：拖拽连线、节点选中/删除/配置、变量 chips 输入
- 新增 **16 种节点类型**：开始、LLM、知识检索、意图分类、参数提取、工具、数据连接、条件、变量、文本处理、聚合、代码、HTTP、模板、直达(提前终止)、结束
- 新增 **7 种节点专属配置面板** + MySQL/PG 连接器表单
- 新增 **6 个内置工作流模板**（一键套用）
- 新增**工作流执行引擎**与执行历史/结果追踪

### MCP 多协议
- 支持 **6 种协议**：stdio / HTTP / SSE / WebSocket / Unix Socket / TCP
- 动态协议表单、编辑已有服务器、自定义请求头
- 连接测试与统一管理

### 其他
- 新增数据连接器（SQLite/MySQL/PostgreSQL/CSV/JSON/HTTP）
- 修复若干前端解析 bug

## [0.2.0] - 2026-08-04

### 平台扩展
- **自动更新能力**：启动检查 + 定时检查 + 下载进度条 + 一键安装 + 备份回滚 + 更新历史 + 通知横幅
- **MCP 支持**：标准 MCP 协议接入外部工具

## [0.1.0] - 2026-08-04

### 核心基础
- 多会话聊天、SSE 流式输出、Markdown 渲染、附件上传
- 多模型供应商（OpenAI 兼容），12+ 预设，一键拉取模型列表
- Agent 工具调用（联网搜索/抓取/文件/命令）
- 知识库 RAG、定时任务、团队协作、专家套件
- 个人偏好设置、自建搜索引擎、频道功能
- macOS 原生 App（Swift WKWebView）