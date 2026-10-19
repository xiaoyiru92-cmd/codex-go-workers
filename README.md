# Codex Workers (Go or your API)

Codex 负责拆分、判断和验收；Pi SDK 在独立进程中执行子任务，保存会话并支持续接。用户自己选择 API 和模型：**OpenAI 兼容 API（Chat Completions）**或 **OpenCode Go**。新安装不预选服务商，也不自动调用 Muse / DeepSeek。

## 安装与首次配置

需要 macOS、Python 3.10+、Node.js 22+、npm；空闲聊天回报需要支持 `queue` 的 Codex Desktop CLI。只有选择 Go 才需要正在运行并已登录的本地 OpenCode v2 Desktop。

```bash
git clone https://github.com/xiaoyiru92-cmd/codex-go-workers.git
cd codex-go-workers
python3 install.py
python3 ~/.codex/skills/codex-pi-subagents/scripts/pi.py setup
```

`setup` 可以在普通终端运行，不调用模型。依次选择：

1. OpenAI 兼容 API 或 OpenCode Go。
2. API 基地址（兼容 API 才需要）与主模型 ID；可给 explorer / quick 另选一个模型。
3. 兼容 API 的密钥来源：环境变量名、已有的私有密钥文件路径，或本机无密钥服务。
4. 兼容模型的上下文与输出上限。这些是用户填写的限制，不是自动发现的能力。

配置只保存密钥来源，不保存密钥内容。不要把密钥发进聊天或写进仓库。密钥文件需属于当前用户，权限为 `600`，且不能是符号链接。远程 API 需 HTTPS；HTTP 和无密钥模式仅支持本机回环地址。桌面进程未继承终端环境变量时，可使用私有密钥文件。

首次运行如果尚未配置，会先提示选择；非交互环境返回 `setupRequired`，不会创建任务或消耗模型额度。取消配置保留原文件；重新配置会先保留一份私有备份。现有 Go 安装无须重新配置，也不会被自动切换。

安装默认拒绝覆盖已有目录；`--target` 可指定新目录，`--skip-deps` 仅复制文件。直接从源码使用时运行 `python3 pi.py setup`，并安装 npm 依赖。不要复制示例配置当作未经用户选择的默认值。

## 调用与结果交接

以下派工命令在 Codex 内使用：

```bash
PI="$HOME/.codex/skills/codex-pi-subagents/scripts/pi.py"
python3 "$PI" agents
python3 "$PI" models
python3 "$PI" start --agent explorer --cwd /absolute/project --prompt-file /absolute/task.txt
python3 "$PI" inbox
python3 "$PI" wait pi_JOB_ID --timeout 30
python3 "$PI" result pi_JOB_ID
python3 "$PI" ack pi_JOB_ID --run 1 --verdict accepted --note '实际检查与结果'
python3 "$PI" send pi_JOB_ID --text '具体的新要求'
python3 "$PI" resume pi_JOB_ID --prompt '继续处理剩余工作'
```

**默认采用异步交接：派工 → 完成独立工作 → 主动结束当前回合 → queue 唤醒下一回合 → 验收并继续。** 主控如果只是在等待 worker，就必须让出回合，不能持续运行等待命令或推理，让用户手动点击“引导”。发出 commentary 不等于结束回合；需要真正结束当前响应。

交接前的可见回复应简要保留用户已确认的要求、已完成内容与待续事项。Codex 可能折叠同一长回合中的过程消息和用户补充；点击“用时”右侧箭头可查看。本项目不控制宿主的折叠开关。

有独立工作时在工作边界用 `inbox` 补查结果。`wait` 保留用于短诊断，不作为默认编排方式。结束回合前确认待办任务已启用通知并绑定本聊天；回报后的 `ack` 防止重复处理。已入队不代表已读，仍不声称宿主支持运行中的即时打断。

## 角色和运行结构

角色包含 fixer、designer、explorer、librarian、reviewer、quick。角色绑定工具与提示词，模型由用户配置。只读角色不能用 `--tools` 增加写入或 shell 能力。不同角色可配置不同 API 和模型别名。

```text
Codex 主控 → Python 启动器/监督进程 → Pi SDK worker → 用户选择的 API
     ↑              会话、状态、结果文件              │
     └──────── inbox / wait / 空闲时 queue ────────────┘
```

`agents.json` 保存角色和非秘密连接设置；每次派工保存配置快照，`resume` 沿用原模型与连接设置。凭据在运行时从指定来源读取。Go 路由复用本机 OpenCode 活跃登录；兼容 API 不依赖 OpenCode。原生 GPT 子代理仍由 Codex 单独管理。

## 检查与边界

```bash
python3 -m unittest -v test_offline.py test_setup.py test_lifecycle.py test_handoff.py
node --test test_connection.mjs
npm ci --ignore-scripts --no-audit --no-fund
python3 -m unittest -v test_compatible_integration.py
```

兼容 API 整体验证使用本地模拟服务器和真实 Pi SDK，不证明任意第三方服务都兼容。支持流式 Chat Completions 和工具调用；本版不包含 Responses-only API、原生 Anthropic 或原生 Gemini 协议。自定义 API 价格未知，不把 SDK 的零价占位当成免费。

需要真实 Go 验证时，显式运行 `verify.py` 或 `verify_presets.py`，它们使用 `examples/opencode-go.json` 的测试模型，会消耗自己的 Go 额度。详见 [VERIFICATION.md](VERIFICATION.md) 和 [USAGE.md](USAGE.md)。

默认 20 是并发上限，不是 20 路实测结论。工具 cwd 不是操作系统沙箱；OAuth 自动刷新、重启自动恢复和绝对可靠的通知传输不在已验证范围内。

MIT License。Pi SDK 由 npm 安装，不随仓库打包。
