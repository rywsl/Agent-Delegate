# Delegate

把本地 agent 的任务交给云端沙箱执行，只把报告、工作区 patch 和输出文件带回来。
本地客户端通过 MCP 接入。执行过程、工具调用和原始日志只在控制台里审计。

当前版本 **0.2.0**，许可证 **GPL-3.0**。没有计费系统。默认执行器使用 OpenAI、Anthropic、Gemini 官方 Python SDK，费用由模型提供商收取，网站只记录 token 用量。

## 快速开始

```bash
cp .env.example .env
# 设置 DELEGATE_SECRET_KEY、POSTGRES_PASSWORD、DELEGATE_PUBLIC_URL
docker compose --profile build build
docker compose up -d
```

1. 打开网站注册。第一个账户自动成为管理员。
2. 在「提供商」配置至少一家 API Key，也可以只用环境变量。
3. 在控制台选择默认模型、沙箱和 harness。
4. 创建 `dlg_…` API 密钥，接到本地 MCP 客户端。

worker 挂载 Docker socket，权限等同宿主机 root，请放在专用主机或虚拟机上。worker 重启时，仍在运行的任务会停止并标记失败。

## 控制台

`web/` 是控制台前端，通过会话接口 `/api/console` 使用账户、任务、密钥、提供商和审计数据。原有页面模板仍然保留。

```bash
# 终端 1
cd server && uv venv --python 3.12 && uv pip install -e ".[dev]"
DELEGATE_SECRET_KEY=change-me .venv/bin/delegate-web

# 终端 2
cd web && npm install && npm run dev
```

开发服务器默认是 `http://127.0.0.1:5173`，并把 `/api`、`/tasks`、`/mcp` 代理到 `http://127.0.0.1:8000`。`npm run build` 之后，后端在 `/app/` 提供构建结果。

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

- MCP 只暴露 `create_upload`、`delegate_task`、`wait_task`、`cancel_task`、`list_tasks`。
- 云端 agent 自主执行，不向用户提问。
- 大文件走一次性上传 URL。patch 小于 16 KB 时直接内联。
- 沙箱使用非 root 用户、资源限制、`cap_drop ALL` 和 `no-new-privileges`。
- 提供商密钥加密后写入数据库。任务规格、命令行参数和审计事件不保存密钥。

## 模型与执行器

| 提供商 | Python 包 | 环境变量 |
|---|---|---|
| OpenAI | `openai` | `OPENAI_API_KEY`、`OPENAI_BASE_URL` |
| Anthropic | `anthropic` | `ANTHROPIC_API_KEY`、`ANTHROPIC_BASE_URL` |
| Gemini | `google-genai` | `GEMINI_API_KEY`、`GEMINI_BASE_URL` |

后台配置优先于环境变量。Base URL 留空时使用官方地址，也可以填兼容服务地址。模型列表由 `DELEGATE_ANTHROPIC_MODELS`、`DELEGATE_OPENAI_MODELS`、`DELEGATE_GEMINI_MODELS` 配置，示例见 `.env.example`。

执行选项（提供商、模型、沙箱、harness、超时）由用户在控制台保存，本地调用方不能覆盖。

- 默认沙箱：`docker`
- 默认 harness：`sdk`（内置 shell、列目录、读、写、精确编辑）
- 可选 harness：`claude-code`、`codex`、`gemini`、`grok`、`pi`、`deepseek`

默认镜像不安装外部 CLI。需要时单独构建：

```bash
docker build --build-arg HARNESS_PACKAGES=@anthropic-ai/claude-code \
  -t delegate-sandbox:claude-code ./sandbox
```

```dotenv
DELEGATE_SANDBOX_IMAGES={"claude-code":"delegate-sandbox:claude-code"}
DELEGATE_HARNESSES=sdk,claude-code,codex,gemini,grok,pi,deepseek
DELEGATE_DEFAULT_HARNESS=sdk
```

`DELEGATE_HARNESS_COMMANDS` 可按 harness 覆盖启动命令，支持 `{model}`、`{prompt}`、`{full_prompt}`、`{system_prompt}`、`{workspace}`、`{max_turns}`。上线前先验证所选 CLI 版本。

## 本地接入

```bash
claude mcp add --transport http delegate https://你的域名/mcp \
  --header "Authorization: Bearer dlg_..."
```

也可参考 `client/mcp.json.example`，并把 `client/CLAUDE.md.snippet` 放进项目的 `CLAUDE.md`。
典型流程：`create_upload` → 执行打印出的上传命令 → `delegate_task` → 重复 `wait_task` → 下载并应用 patch。

## HTTP API

请求头：`Authorization: Bearer <API key>`。

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/tasks` | 提交任务 `{task, title?, upload_ids?, files?, repo_url?, repo_ref?}` |
| GET | `/api/v1/tasks`、`/api/v1/tasks/{id}` | 列表 / 结果 |
| GET | `/api/v1/tasks/{id}/wait?timeout=25` | 长轮询直到结束 |
| POST | `/api/v1/tasks/{id}/cancel` | 取消并收集已有结果 |
| POST | `/api/v1/uploads` | 申请一次性上传 URL |
| PUT/POST | `/api/v1/uploads/{token}` | 上传文件或归档 |
| GET | `/api/v1/downloads/{signed}/{name}` | 下载 patch 或输出文件 |
| GET | `/api/v1/me` | 当前账户 |

`/api/v1` 只返回结果，不返回执行过程。执行轨迹在控制台查看。

## 目录

```text
server/delegate/web/      网站、REST API、控制台 JSON、提供商配置
server/delegate/worker.py 任务调度与沙箱生命周期
server/delegate/events.py SDK / harness 输出 → 审计事件
server/delegate_mcp/      无状态 MCP 网关
sandbox/                  默认 SDK 执行器与可选 harness
client/                   MCP 配置示例
web/                      控制台前端
server/tests/             单元、Web、SDK 与 MCP 测试
```

## 测试

```bash
cd server
uv venv --python 3.12
uv pip install -e ".[dev]"
.venv/bin/python -m pytest -q
```

测试使用假 SDK 和假 Docker，不需要真实模型密钥。Compose 配置可单独检查：

```bash
docker compose --env-file .env.example config --quiet
```

真实部署时，用有效的提供商密钥从控制台提交一个会改文件并写入 `/outputs` 的任务，确认报告、token 用量、patch 和输出文件都能回来。

## 安全

- 不要提交 `.env`、数据库或 `data/`。
- `DELEGATE_SECRET_KEY` 使用长随机字符串，并同时用于会话和字段加密。
- 提供商密钥只出现在环境变量或加密后的数据库字段中。
- 第一个注册用户是管理员。之后可以在后台关闭公开注册。
