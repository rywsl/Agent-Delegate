# Delegate：把本地 agent 的任务外派给云端沙箱 agent

本地的 Claude Code 通过 MCP 把一个**完整、自洽的任务**交给云端，由沙箱容器里的 Claude Code / Codex 自主执行直至完成，
最后只把**结果**带回本地：结果报告、工作区 patch、输出文件。执行过程的全部细节（每条消息、每次工具调用、命令输出、
逐请求计费）只在网站上供审计。所有模型调用经过 sidecar 的 new-api 按 token 计费，网站把 new-api 完整包在内部：
每个网站用户都有一个由网站创建并托管凭证的 new-api 镜像账户。

```
 客户端                              服务器
┌──────────────────────┐   HTTPS   ┌──────────────────────────────────────────────────────────────────────┐
│ Claude Code          │  /mcp     │  Caddy ──► mcp (MCP 网关，无状态、不持有任何凭证)                         │
│   └─ MCP client ─────┼──────────►│              │ 用调用者自己的 API key 调用 ▼                              │
│                      │           │  Caddy ──► web (网站 + /api/v1 + 上传/下载) ◄──► Postgres               │
│ curl ── 上传/下载 ───┼──────────►│              │  root PAT / 镜像账户 PAT（只在网站手里）                     │
└──────────────────────┘           │              ▼                                                        │
                                   │           new-api (sidecar，不对公网开放) ◄── 每任务独立 key ──┐          │
                                   │              ▲                                              │          │
                                   │  worker ─────┴── docker ──► 沙箱容器 × N（claude / codex 无头运行）       │
                                   └──────────────────────────────────────────────────────────────────────┘
```

## 设计要点

**外派，不是遥控。** MCP 只提供五个粗粒度工具：`create_upload`、`delegate_task`、`wait_task`、`cancel_task`、
`list_tasks`。本地 agent 交出任务后不能逐步指挥云端 agent，也不能修改执行配置（agent 种类、模型、预算、超时）——
这些只能由用户在网站「设置」里决定。云端 agent 的系统提示要求它完全自主、不提问、最后给出报告。

**只回传结果。** 本地 agent 拿到的是：状态、结果报告、patch（小于 16 KB 直接内联，否则给下载链接）、
`/outputs` 里的输出文件（限时签名链接）、费用和一个给人看的审计链接。工具调用、命令、思考过程等都不出网站。

**文件不经过模型。** 把文件内容塞进工具参数会让本地模型逐 token 生成，又慢又贵。因此：
- 上传：`create_upload` 返回一次性上传 URL，本地 agent 用 shell 执行
  `git ls-files -co --exclude-standard -z | tar --null -T - -czf - | curl -fsS -T - '<url>'`（或单文件
  `curl -T file '<url>'`）；归档（tar / tar.gz / zip）**在沙箱内部**安全解压（防路径穿越、拒绝越界软链/设备文件）。
- 回执：沙箱把 `/workspace` 相对基线的全部改动打成 `git diff --binary`，本地 `curl … && git apply …` 即可；
  不属于仓库的交付物（报告、数据、二进制）放在 `/outputs`，打包回传，可整体或逐个下载。
- 小片段仍可用 `files` 参数内联（总量 1 MB 以内）。所有输入、输出与任务一起归档，可在网站审计和下载。

**计费完全走 new-api，且精确到任务。**
- 网站自动完成 new-api 首次初始化，用「登录 → 二次验证 → 创建令牌」流程拿到带作用域的 root PAT（`nap_…`）。
- 每个网站用户对应一个 new-api 镜像账户（用户名由网站生成，密码由站点密钥派生，网站持有其作用域 PAT）。
- **每个任务创建一个独立的 new-api 令牌，额度 = 任务预算**：预算上限由 new-api 强制执行；任务结束即删除令牌，
  沙箱里的 key 立刻失效；按令牌名从 new-api 日志汇总出该任务逐请求的 token 与费用（权威计费）。
- 充值/扣减用 new-api 的原子 `add_quota`，不会与进行中的消费产生读改写竞态；充值码由网站自己签发与核销。

**审计。** 网站保存：任务输入（描述、上传包、内联文件及 SHA-256）、沙箱信息（容器、镜像、资源限制、退出码）、
完整执行轨迹（规范化事件 + 原始 JSONL 日志）、patch 与输出文件、网关逐请求计费明细、agent 自报用量（交叉核对）、
以及账户级审计日志（登录、密钥、上传、任务、计费、管理操作，含 IP / UA）。

**隔离。**
- 沙箱：非 root 用户、`cap_drop ALL`、`no-new-privileges`、内存/CPU/进程数限制、`init`；
  只接入 `delegate_sandbox` 网络（可上网，能访问 new-api，访问不到网站和数据库）。
- 沙箱里唯一的凭证是本任务的预算受限 key（可选再用 `SANDBOX_ALLOWED_IPS` 限制来源 IP）。
- new-api 只绑定 `127.0.0.1:3000`，供运维配置上游渠道与定价。

## 目录

```
docker-compose.yml        全部服务；deploy/ 下是 Caddyfile 与 Postgres 初始化脚本
.env.example              全部配置项
server/                   Python 服务（同一镜像三种角色）
  delegate/web/           网站、/api/v1、上传/下载、管理后台（FastAPI + Jinja2）
  delegate/worker.py      调度任务、管理沙箱生命周期、记录事件、计费对账
  delegate/billing.py     new-api 封装：初始化、镜像账户、每任务令牌、对账、余额
  delegate/newapi.py      new-api 管理 API 客户端（按 v1.0 源码核对：JWT/二次验证/PAT/作用域）
  delegate/events.py      Claude Code stream-json / Codex exec --json → 审计事件
  delegate/transfer.py    一次性上传 URL、签名下载链接
  delegate_mcp/server.py  MCP 网关（Streamable HTTP，无状态）
  tests/                  单元测试 + 可选的真实 new-api / 真实 CLI 端到端测试
sandbox/                  沙箱镜像（claude-code + codex）与容器内 runner.py
client/                   本地 Claude Code 的接入示例
```

## 部署

```bash
cp .env.example .env            # 填写密钥、域名、模型列表等
docker compose --profile build build   # 构建服务镜像与沙箱镜像 delegate-sandbox:latest
docker compose up -d
```

1. 打开网站注册：**第一个注册的账户自动成为管理员**（也可 `docker compose exec web delegate-admin create-admin you@x.com`）。
2. 在 new-api 后台配置上游渠道与模型定价：`ssh -L 3000:127.0.0.1:3000 server`，浏览器打开
   `http://localhost:3000`，用 `root` / `NEWAPI_ROOT_PASSWORD` 登录。渠道里的模型名需与
   `DELEGATE_CLAUDE_MODELS` / `DELEGATE_CODEX_MODELS` 一致；Codex 需要支持 `/v1/responses` 的渠道。
3. 管理后台 → 用户 → 调整余额，或生成充值码发给用户。
4. 管理后台概览页可看到 new-api 与 Docker 的健康状态。

注意：worker 需要挂载 Docker socket（等价于宿主机 root），请部署在专用主机/虚拟机上。
worker 重启时仍在运行的任务会被标记为失败（并停止其容器、回收令牌）。

## 本地接入

在网站「API 密钥」页创建密钥，然后：

```bash
claude mcp add --transport http delegate https://你的域名/mcp --header "Authorization: Bearer dlg_..."
```

或使用 `client/mcp.json.example`。可把 `client/CLAUDE.md.snippet` 放进项目的 CLAUDE.md，告诉本地 agent 何时以及如何外派。

一次典型交互：`create_upload` → 本地 shell 执行打印出的 tar|curl 命令 → `delegate_task(task=…, upload_ids=[…])`
→ 若仍在运行则反复 `wait_task` → 拿到报告，执行 `curl … && git apply …` 应用改动。

每次调用最多阻塞约 100 秒（`DELEGATE_MCP_DEFAULT_WAIT`）：Claude Code 会把超过约 2 分钟的 MCP 调用转入后台，
并中断 5 分钟无响应的调用，所以采用“有界等待 + 重复 wait_task”的方式，长任务也能可靠地等到结束。

## HTTP API

所有接口用 `Authorization: Bearer <API key>`（MCP 网关就是基于这些接口实现的）：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/tasks` | 提交任务 `{task, title?, upload_ids?, files?, repo_url?, repo_ref?}` |
| GET | `/api/v1/tasks` · `/api/v1/tasks/{id}` | 列表 / 结果视图 |
| GET | `/api/v1/tasks/{id}/wait?timeout=25` | 长轮询直到结束 |
| POST | `/api/v1/tasks/{id}/cancel` | 取消（已完成部分仍会收集） |
| POST | `/api/v1/uploads` | 申请上传槽 `{dest}` → 一次性 `upload_url` |
| PUT/POST | `/api/v1/uploads/{token}` | 上传（URL 即凭证，单次有效） |
| GET | `/api/v1/downloads/{signed}/{name}` | patch / 输出文件（签名、限时） |
| GET | `/api/v1/me` | 余额 |

## 测试

```bash
cd server
uv venv --python 3.12 && uv pip install -e ".[dev]"
.venv/Scripts/python -m pytest          # 单元 + 集成（假 new-api、假 Docker）+ MCP 协议端到端
```

可选的真实环境测试（需要一个全新的 new-api，以及本机安装的 `claude` / `codex` CLI）：

```bash
SESSION_SECRET=x CRITICAL_RATE_LIMIT_ENABLE=false GLOBAL_API_RATE_LIMIT_ENABLE=false ./new-api --port 3399
NEWAPI_TEST_URL=http://127.0.0.1:3399 pytest tests/test_newapi_integration.py
NEWAPI_TEST_URL=http://127.0.0.1:3399 CLAUDE_E2E=1 CODEX_E2E=1 pytest tests/test_e2e_claude.py tests/test_e2e_codex.py -s
```

端到端测试让真实的 Claude Code / Codex CLI（使用与沙箱完全相同的参数）经 new-api 的每任务 key 访问一个脚本化上游，
校验事件解析、文件改动以及 new-api 日志对账出的费用与理论值一致。
