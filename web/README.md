# Delegate 控制台

控制台前端。数据来自后端会话接口 `/api/console`，覆盖账户、任务、密钥、提供商和审计。模型、沙箱、执行器和超时由账户设置决定，创建任务时写入记录，执行过程不能改写。提供商密钥只保存在后端。

## 开发

先启动后端（默认 `http://127.0.0.1:8000`）：

```bash
npm install
npm run dev
```

打开 `http://127.0.0.1:5173`。Vite 把 `/api`、`/tasks`、`/mcp` 代理到后端，登录态使用 `delegate_session` cookie。

## 构建

```bash
npm run build
```

存在 `web/dist` 时，后端把它挂到 `/app/`。
