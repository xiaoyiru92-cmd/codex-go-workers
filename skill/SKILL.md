---
name: codex-pi-subagents
description: "Codex-only Go/Pi delegation for substantial implementation, debugging, document processing and local evidence gathering with independent subtasks. Proactively run Muse and DeepSeek workers concurrently; Codex owns planning and acceptance. Never invoke inside OpenCode/OMO or a Pi worker."
---

# Codex 专用 Go workers

## 宿主边界：先判断，再执行

**只对 Codex 生效。OpenCode、OMO、Pi worker 即使读到了本文件，也必须跳过，沿用自己的原有代理和模型路由；不要尝试运行本 skill 的命令，不要修复其调用失败，不要据此修改 OpenCode 的配置。**

本 skill 安装在 `~/.codex/skills/codex-pi-subagents`，不放入共享的 `~/.agents/skills` 或 OpenCode skill 目录。调用方必须是当前 Codex 聊天，具有宿主注入的 `CODEX_THREAD_ID`，祖先进程不能是 OpenCode。脚本缺少此变量或检测到 OpenCode 祖先进程时会拒绝运行；不要伪造变量或复制旧聊天 ID 来绕过。不要单凭所选 GPT 模型判断宿主。它不是 OS 安全隔离。

## 主控与派工

- Codex 自己负责理解需求、拆分、预算、关键判断、整合和最终验收。普通执行优先交给 Go workers，不要让主控包办可明确交付的工作。
- 对存在独立子任务的较大工作，**主动并发派工，不等用户逐次要求**。按可独立交付的任务数积极并发，默认全局上限为 **20**；不要固定收缩为 2–3 个。小改动、强依赖链和纯聊天不必拆分。上限是容量，不是凑数目标。
- 规划好独立任务后连续启动，不要等第一个完成才启动第二个。主控同时推进只能自己做的工作；没有独立工作时可以结束本回合，等待已启用的 queue 回报自动续接。不要为轮询而空转，也不要新建额外控制层。
- 同一目录中，只有纯只读 workers 可以并发。写入任务放在各自独立目录或 worktree；有关联的修改串行。不得以换状态目录绕过冲突检查。
- 每次派工给完整输入：目标、工作目录、允许修改的文件、已有材料、验收条件、时长及用量边界。只给所需上下文，长资料保存在文件中引用。不得把根聊天原文、凭据或无关历史整包传入。
- 任务授权允许这类本机委派时，按本 skill 使用 Go workers；不改变外部发送、远程访问、部署等动作原有授权边界。用户明确限定单代理、模型或禁止联网时，服从其限制。

## 角色和模型

**Pi 与 GPT 使用两套独立预设，不维护统一源模板，也不自动生成或同步两边配置。** Pi 的角色、模型、工具和提示词提前绑定在 `runtime/agents.json`，启动器直接加载选中的角色；主控每次只提交角色名、本次任务和必要材料路径，不读取、展开或转发整份角色提示词。

GPT 使用 Codex 原生子代理工具和其自身的角色指令体系，不经过 Pi，也不从 Pi 角色表借用模板。主控负责判断走哪条执行通道，分别持有原生 agent ID 或 Pi job ID。当前 skill 的 `agents` 列表只列 Pi 角色，不代表 Codex 所有可用角色。

角色目录默认只返回简短描述、模型和工具；只有确实需要检查配置时才使用 `agents --full`。完整角色指令进入选中的 worker 上下文，不加载其他角色，不把父聊天完整历史复制进去。预设仍占 worker 的输入上下文，不声称默认配置或缓存让这些 token 免费。

先运行 `agents` / `models` 查看当前配置，避免凭记忆猜角色。默认映射：

| 预设 | 模型入口 | 用途与工具 |
| --- | --- | --- |
| fixer | muse | 实现、修复；文件工具及 bash |
| designer | muse | 已定范围的 UI 实现；文件工具及 bash |
| explorer | deepseek | 只读查代码；read/grep/find/ls |
| librarian | muse | 阅读本地资料；read/grep/find/ls |
| reviewer | muse | 按需审查指定材料；read/grep/find/ls |
| quick | deepseek | 规则明确的提取、格式化、小批量修改；无 bash |

`muse` = `opencode-go/muse-spark-1.3-contributor`；`deepseek` = `opencode-go/deepseek-v4.1-flash`。两者复用本机 OpenCode v2 当前登录。**这里的 DeepSeek 是 Go 路由，不是 WorkBuddy 反代。** 不自动切换为 Zen 付费模型、其他供应商或其他账户。

角色配置位于本 skill 的 `runtime/agents.json`，可编辑模型、工具、提示词和默认并发数；也可通过全局 `--config /absolute/agents.json` 为一次调用选择另一配置。`--model deepseek` 可显式覆盖模型；`--tools` 只能缩小角色的工具集合。任务创建时保存配置快照，`resume` 沿用原角色与模型；要换角色或模型，开新任务并交接已验收的文件。

GPT/Astra/Oracle 的困难推理留在 Codex 主控或已获授权的原生代理。不要把 Codex 订阅凭据接入 Pi，也不要为了一个 Go worker 再创建长期等待的原生传话代理。Go 的 20 并发上限只约束 Pi 任务池；原生 GPT 代理遵守宿主实际限制。

## 命令

以下入口自带 Codex 调用方检查、稳定的状态目录和本 skill 自己的运行时：

```bash
python3 ~/.codex/skills/codex-pi-subagents/scripts/pi.py agents
python3 ~/.codex/skills/codex-pi-subagents/scripts/pi.py models
python3 ~/.codex/skills/codex-pi-subagents/scripts/pi.py start --agent fixer --cwd /absolute/worktree --prompt-file /absolute/task.txt
python3 ~/.codex/skills/codex-pi-subagents/scripts/pi.py start --agent explorer --cwd /absolute/other/project --prompt-file /absolute/search.txt
python3 ~/.codex/skills/codex-pi-subagents/scripts/pi.py list
python3 ~/.codex/skills/codex-pi-subagents/scripts/pi.py status pi_JOB_ID
python3 ~/.codex/skills/codex-pi-subagents/scripts/pi.py send pi_JOB_ID --id unique_instruction_id --text '具体的新指令'
python3 ~/.codex/skills/codex-pi-subagents/scripts/pi.py send pi_JOB_ID --mode followUp --text '当前工作结束后做这一步'
python3 ~/.codex/skills/codex-pi-subagents/scripts/pi.py resume pi_JOB_ID --prompt '基于已保存会话继续处理这一步'
python3 ~/.codex/skills/codex-pi-subagents/scripts/pi.py cancel pi_JOB_ID
python3 ~/.codex/skills/codex-pi-subagents/scripts/pi.py recover
```

使用命令实际返回的 job ID。默认绑定当前聊天并启用 queue 通知；正式派工保留此默认值。`--no-notify` 只用于当前回合内会主动验收完的短测试。不要硬编码或复用其他聊天的 ID。状态和会话默认保存在 `~/.codex/pi-subagents`。

`steer` 在当前工具调用后的边界交付，不能即时改写正在运行的命令；重复发送同一 instruction ID 会在该 worker 内去重。worker 已结束后用 `resume`，不要反复尝试 `send`。默认限时 600 秒、最多 24 次模型请求，每请求最多 2048 输出 token；按任务大小通过对应参数调整，不因并发无限放大预算。临时模型错误最多重试同一请求一次，不自动重跑整个工具任务。

## 工具能力

worker 只拥有角色列出的 Pi 工具，不继承 Codex 的连接器、网页搜索、浏览器或原生代理接口。Pi SDK 支持自定义工具，但本运行时没有自动装载外部扩展、MCP 或其他 skills。主控负责获取缺失资料和必要的浏览器/视觉验收；不要把本地资料阅读声称为已联网研究。工具 cwd 不是 OS 沙箱。

## 回报与验收

收到 `[CODEX_PI_RESULT ...]` 后先看该 run 的 `acceptance.json`，已验收就不再派工或重复执行产物。否则读取 `result.json`、运行状态和指定文件，核对任务范围与实际产物，再写入决定：

```bash
python3 ~/.codex/skills/codex-pi-subagents/scripts/pi.py ack pi_JOB_ID --run 1 --verdict accepted --note '实际检查及结论'
```

失败用 `rejected`，并区分模型失败、工具失败、超时、取消与通知失败。worker 说成功不等于主控验收；queue 入队也不等于已经处理。验收后有独立待办时及时补位，直到原任务完成。

主控直接持有 job ID，不依赖中间代理等待。`recover` 保留会话和部分产物，不自动重放工具；先检查部分工作，再决定续接。通知处于 `uncertain/submitting` 时先核对聊天，不自动重发。OpenCode 失联、登录过期或供应商报错时报告边界，不修改其全局配置、不盲目换账户或模型。
