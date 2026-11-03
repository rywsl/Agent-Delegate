# Delegate

把本地 agent 的完整任务外派给云端沙箱 agent，最后只带回结果报告、工作区 patch 和输出文件。
本地 Claude Code 等客户端通过 MCP 接入；云端执行过程、工具调用与原始日志只在网站上供用户审计。

**当前开源版本：0.2.0，GPL-3.0。** 项目不包含计费系统，也不需要 `new-api`。默认执行器直接采用
OpenAI、Anthropic、Gemini 官方 Python SDK，费用由模型提供商收取，网站只记录 token 用量用于审计。

## 架构

```text
本地 Agent                         服务器
┌─────────────────┐        ┌──────────────────────────────────────────────┐
│ MCP client      │ /mcp   │ mcp ──► web / REST API ──► Postgres          │
│ curl 上传/下载  ├───────►│                    │                         │
└─────────────────┘        │                  worker                      │
                           │                    └─► Docker 沙箱 × N        │
                           │                          ├─ 官方 Python SDK    │
                           │                          └─ 可选外部 harness   │
                           └──────────────────────────────────────────────┘
```

- MCP 只暴露 `create_upload`、`delegate_task`、`wait_task`、`cancel_task`、`list_tasks` 五个粗粒度工具。
- 云端 agent 自主执行，不向用户提问；最终报告、patch、`/outputs` 文件回传给本地 agent。
- 大文件通过一次性 URL 上传，不塞进模型工具参数；patch 小于 16 KB 时直接内联。
- 沙箱使用非 root 用户、资源限制、`cap_drop ALL` 和 `no-new-privileges`。
- 提供商密钥在数据库中加密保存；任务规格、命令行参数和审计事件中不保存密钥。

## 模型提供商与 Base URL

支持以下官方 Python 库：

| 提供商 | Python 包 | 环境变量 |
|---|---|---|
| OpenAI | `openai` | `OPENAI_API_KEY`、`OPENAI_BASE_URL` |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY`、`ANTHROPIC_BASE_URL` |
| Gemini | `google-genai` | `GEMINI_API_KEY`、`GEMINI_BASE_URL` |

管理员在「管理 → 模型提供商」中为每家配置 API Key、Base URL 和启用状态。Base URL 留空时使用官方地址，
也可填写 OpenAI/Anthropic/Gemini 兼容服务地址。后台配置优先于环境变量；清除后台密钥后可回退到环境变量。

模型列表由 `DELEGATE_ANTHROPIC_MODELS`、`DELEGATE_OPENAI_MODELS`、`DELEGATE_GEMINI_MODELS` 配置。
完整示例见 `.env.example`。

## 沙箱与 Harness

用户在「设置」中选择模型提供商、模型、沙箱、harness 和超时；本地调用方不能覆盖这些选项。

- 默认沙箱：`docker`。
- 默认 harness：`sdk`，使用内置多轮工具调用循环，支持 shell、文件列表、读取、写入和精确编辑。
- 可选 harness：`claude-code`、`codex`、`gemini`、`grok`、`pi`、`deepseek`。

**默认镜像不会安装任何外部 harness。** 它只包含三家 Python SDK 和执行器，避免把所有 CLI 及其运行时打包进去。
需要外部 harness 时，为单个工具构建独立镜像。例如：

```bash
docker build --build-arg HARNESS_PACKAGES=@anthropic-ai/claude-code \
  -t delegate-sandbox:claude-code ./sandbox
```

然后在 `.env` 中映射镜像：

```dotenv
DELEGATE_SANDBOX_IMAGES={"claude-code":"delegate-sandbox:claude-code"}
```

可通过 `DELEGATE_HARNESS_COMMANDS` 覆盖启动命令，值是以 harness 名为键的 JSON 数组，支持
`{model}`、`{prompt}`、`{full_prompt}`、`{system_prompt}`、`{workspace}`、`{max_turns}` 占位符。
外部 CLI 的参数兼容性由其版本决定；生产部署前应先验证所选版本。默认 `sdk` 路径不需要 Node.js 或任何外部 CLI。

可用项和默认值通过以下变量配置：

```dotenv
DELEGATE_SANDBOXES=docker
DELEGATE_DEFAULT_SANDBOX=docker
DELEGATE_HARNESSES=sdk,claude-code,codex,gemini,grok,pi,deepseek
DELEGATE_DEFAULT_HARNESS=sdk
```

## 部署

```bash
cp .env.example .env
# 修改 DELEGATE_SECRET_KEY、POSTGRES_PASSWORD 和公开地址
docker compose --profile build build
docker compose up -d
```

1. 打开网站注册；第一个账户自动成为管理员。
2. 在「管理 → 模型提供商」配置至少一家 API Key，也可通过环境变量配置。
3. 在「设置」选择默认模型、沙箱和 harness。
4. 在「API 密钥」页创建本地 MCP 使用的 `dlg_…` 密钥。

注意：worker 挂载 Docker socket，等价于宿主机 root，请部署在专用主机或虚拟机上。worker 重启时，仍在运行的任务会停止并标记失败。

从 0.1 升级时会自动添加用户执行选项和任务沙箱/harness 字段；旧计费表与字段不会再被使用，也不会自动删除历史数据。

## 本地接入

```bash
claude mcp add --transport http delegate https://你的域名/mcp \
  --header "Authorization: Bearer dlg_..."
```

也可参考 `client/mcp.json.example`，并把 `client/CLAUDE.md.snippet` 放进项目的 `CLAUDE.md`。
典型流程为 `create_upload` → 执行打印出的上传命令 → `delegate_task` → 重复 `wait_task` → 下载并应用 patch。

## HTTP API

所有接口使用 `Authorization: Bearer <API key>`：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/tasks` | 提交任务 `{task, title?, upload_ids?, files?, repo_url?, repo_ref?}` |
| GET | `/api/v1/tasks`、`/api/v1/tasks/{id}` | 列表 / 结果视图 |
| GET | `/api/v1/tasks/{id}/wait?timeout=25` | 长轮询直到结束 |
| POST | `/api/v1/tasks/{id}/cancel` | 取消并收集已有结果 |
| POST | `/api/v1/uploads` | 申请一次性上传 URL |
| PUT/POST | `/api/v1/uploads/{token}` | 上传文件或归档 |
| GET | `/api/v1/downloads/{signed}/{name}` | 下载 patch / 输出文件 |
| GET | `/api/v1/me` | 当前账户信息 |

## 目录

```text
server/delegate/web/       网站、REST API、用户设置和后台提供商配置
server/delegate/worker.py  任务调度与沙箱生命周期
server/delegate/events.py  SDK / harness 输出 → 审计事件
server/delegate_mcp/       无状态 MCP 网关
sandbox/agent.py          默认官方 SDK 多轮工具执行器
sandbox/harness.py        可选外部 harness 适配
server/tests/             单元、Web、SDK 工具循环及 MCP 端到端测试
```

## 测试

```bash
cd server
uv venv --python 3.12
uv pip install -e ".[dev]"
.venv/bin/python -m pytest -q
```

测试使用假 SDK 响应和假 Docker，不需要真实模型密钥，也不会产生模型费用。Compose 配置可验证：

```bash
docker compose --env-file .env.example config --quiet
```

真实部署验证时，请在后台配置有效的提供商密钥，从网页提交一个要求修改文件并写入 `/outputs` 的任务，
确认报告、token 用量、patch 和输出文件均能返回。
