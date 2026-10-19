# Codex Go Workers

Codex 原生主控负责规划与验收，Pi SDK 复用本机 OpenCode v2 Go 登录运行子任务；GPT 推理使用独立的原生 Codex 子代理，不经过 Pi。

仓库地址：https://github.com/xiaoyiru92-cmd/codex-go-workers

详细用法见 `USAGE.md`，Codex 宿主内的派工规则见 `skill/SKILL.md`。本文只做总览，不重复全部细节。

## 适用环境

- macOS
- Python 3.10+、Node 22+、npm
- 正在运行的本地 OpenCode v2 Desktop，且有你自己的有效 Go 登录
- 带 `queue` 功能的 Codex Desktop

OpenCode 本身保持原流程，本项目不修改其路由、插件或全局配置。

## 安装

```bash
git clone https://github.com/xiaoyiru92-cmd/codex-go-workers.git
cd codex-go-workers
python3 install.py
```

根目录脚本将新建 `~/.codex/skills/codex-pi-subagents` 并执行 `npm ci`。

- 若目标目录已存在，默认拒绝覆盖。
- 测试用途支持 `--target` 与 `--skip-deps`。

## 角色与模型

Pi 角色在 `agents.json` 中定义，GPT 原生子代理是另一套独立配置，本项目不预置、不生成、不同步原生角色。

| Pi 角色 | 实际模型入口 | 说明 |
| --- | --- | --- |
| fixer | `opencode-go/muse-spark-1.3-contributor` | 默认值；实现与修复 |
| designer | `opencode-go/muse-spark-1.3-contributor` | 已定范围的 UI 实现 |
| librarian | `opencode-go/muse-spark-1.3-contributor` | 本地资料阅读，无网页工具 |
| reviewer | `opencode-go/muse-spark-1.3-contributor` | 只读审查 |
| explorer | `opencode-go/deepseek-v4.1-flash` | 只读代码查找 |
| quick | `opencode-go/deepseek-v4.1-flash` | 规则明确的小批量处理，无 bash |

其中 DeepSeek 走 Go 路由，不是 WorkBuddy 反代。

## 并发说明

默认 Pi worker 上限为 20，可在配置或单次调用中调整。该数字是容量上限，不是“已做 20 路压测”的证明。

## 常用调用示例

以下命令在 Codex 的执行环境中运行；`pi_JOB_ID` 以实际返回为准。普通终端可先在仓库里运行 `python3 pi.py models` 做离线配置检查。

```bash
PI="$HOME/.codex/skills/codex-pi-subagents/scripts/pi.py"
python3 "$PI" agents
python3 "$PI" start --agent explorer --cwd /absolute/project --prompt-file /absolute/search.txt
python3 "$PI" send pi_JOB_ID --text '先看解析器，再动 UI。'
python3 "$PI" send pi_JOB_ID --mode followUp --text '当前工作结束后检查文档。'
python3 "$PI" resume pi_JOB_ID --prompt '继续处理剩余的失败测试。'
python3 "$PI" cancel pi_JOB_ID
python3 "$PI" ack pi_JOB_ID --run 1 --verdict accepted --note '已检查产物与相关测试。'
```

`steer` 在下一个工具边界生效，不能改写正在运行的命令；`followUp` 等当前工作结束后再执行；任务结束后用 `resume` 续接。收到 queue 回报后，主控仍需检查产物再写 `ack`。

## 账号与隐私

- 请用你自己的账号与额度，不分享凭据，不共用登录状态。
- 本项目不包含真实会话日志、个人配置、任务 ID、组织 ID 或凭据。
- 不提供 WorkBuddy 入口。

## 验证状态与边界

- 历史环境中曾用真实 Muse / DeepSeek 做过功能验证，包括多任务并发、 steering、恢复与 queue 回调；具体范围以 `USAGE.md` 中的验证说明为准。
- 你机器上的结果未经验证，需要自行按 `USAGE.md` 运行检查。
- 已知边界：平台为 macOS；OAuth 过期需 OpenCode 自行续登，不自动刷新；通知 `uncertain/submitting` 状态需人工核对后再决定是否重发；工具 cwd 不是 OS 沙箱。

## 本地检查

```bash
python3 -m unittest -v test_offline.py
```

这组检查不调用模型。真实模型检查需先在仓库执行 `npm ci --ignore-scripts --no-audit --no-fund`，再按 `USAGE.md` 运行 `verify.py` 或 `verify_presets.py`；会使用你自己的 Go 额度。历史已验范围与未验边界见 [VERIFICATION.md](VERIFICATION.md)。

本项目采用 MIT License，Pi 依赖由 npm 安装，不随仓库打包。
