import React from 'react';
import { Field, Panel, PrimaryButton, Select, TextInput } from './ui';
import { api, type Session } from '../lib/api';
import type { Tab } from './Sidebar';

type TaskRow = {
  id: string; title: string; status: string; agent: string; model: string;
  billing_mode: string; queue_position: number | null; cost_usd: number; created_at: string;
};

function money(seconds: number) {
  const minutes = Math.floor(seconds / 60);
  return `${minutes} 分钟`;
}

export function UserViews({ tab, session, reload }: { tab: Tab; session: Session; reload: () => Promise<void> }) {
  if (tab === 'home') return <Home session={session} />;
  if (tab === 'tasks') return <Tasks />;
  if (tab === 'new') return <NewTask />;
  if (tab === 'keys') return <Keys />;
  if (tab === 'billing') return <Billing reload={reload} />;
  if (tab === 'audit') return <Audit />;
  return <Settings session={session} reload={reload} />;
}

function Home({ session }: { session: Session }) {
  const [data, setData] = React.useState<{ counts: Record<string, number>; tasks: TaskRow[]; queue: { waiting: number; max: number }; sandbox_usd_per_minute: number } | null>(null);
  React.useEffect(() => { api<typeof data>('/api/console/dashboard').then(setData); }, []);
  const user = session.user!;
  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">主页</h1>
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <Panel title="余额">
          <p className="text-2xl">{user.balance_usd == null ? '暂不可用' : `${user.balance_usd} USD`}</p>
          <p className="text-xs text-zinc-500">{user.balance_usd == null ? '模型网关未连接' : '平台模型费'}</p>
        </Panel>
        <Panel title="沙箱免费额度"><p className="text-2xl">{money(user.sandbox_free_seconds)}</p><p className="text-xs text-zinc-500">自带密钥时先扣这里</p></Panel>
        <Panel title="当前计费"><p className="text-2xl">{user.billing_mode === 'byok' ? '自带密钥' : '平台密钥'}</p><p className="text-xs text-zinc-500">没配密钥就走平台</p></Panel>
      </div>
      {data && (
        <Panel title="队列">
          <p className="text-sm text-zinc-500">正在排队 {data.queue.waiting} / {data.queue.max}。沙箱 {data.sandbox_usd_per_minute} USD/分钟，按实际上限取整到 1 分钟。</p>
          <ul className="mt-3 space-y-1 text-sm">
            {data.tasks.map((task) => <li key={task.id}>{task.title} · {task.status}{task.queue_position ? ` · 第 ${task.queue_position} 位` : ''}</li>)}
          </ul>
        </Panel>
      )}
    </div>
  );
}

function Tasks() {
  const [tasks, setTasks] = React.useState<TaskRow[]>([]);
  const [open, setOpen] = React.useState<Record<string, unknown> | null>(null);
  React.useEffect(() => { api<{ tasks: TaskRow[] }>('/api/console/tasks').then((data) => setTasks(data.tasks)); }, []);
  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">任务</h1>
      <Panel title="最近任务">
        {tasks.map((task) => (
          <button key={task.id} className="mb-2 block w-full rounded-lg border border-zinc-200 px-3 py-2 text-left text-sm dark:border-zinc-800" onClick={async () => setOpen(await api(`/api/console/tasks/${task.id}`))}>
            <span className="font-medium">{task.title}</span>
            <span className="ml-2 text-zinc-500">{task.status} · {task.agent}/{task.model} · {task.billing_mode} · ${task.cost_usd}</span>
          </button>
        ))}
        {!tasks.length && <p className="text-sm text-zinc-500">还没有任务。</p>}
      </Panel>
      {open && (
        <Panel title="详情">
          <pre className="overflow-auto text-xs">{JSON.stringify(open.billing ?? open, null, 2)}</pre>
        </Panel>
      )}
    </div>
  );
}

function NewTask() {
  const [task, setTask] = React.useState('');
  const [message, setMessage] = React.useState('');
  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">新建任务</h1>
      <Panel title="提交">
        <p className="mb-3 text-sm text-zinc-500">模型和预算用账户设置里的值。本地调用方也不能改这些。</p>
        <textarea className="mb-3 min-h-40 w-full rounded-lg border border-zinc-200 bg-white p-3 text-sm dark:border-zinc-700 dark:bg-zinc-900" value={task} onChange={(e) => setTask(e.target.value)} />
        <PrimaryButton onClick={async () => {
          try {
            const created = await api<{ id: string; status: string; queue_position?: number }>('/api/console/tasks', { method: 'POST', body: JSON.stringify({ task }) });
            setMessage(`已排队 ${created.id}，位置 ${created.queue_position ?? '—'}`);
            setTask('');
          } catch (err) {
            setMessage(err instanceof Error ? err.message : '提交失败');
          }
        }}>提交</PrimaryButton>
        {message && <p className="mt-3 text-sm">{message}</p>}
      </Panel>
    </div>
  );
}

function Keys() {
  const [keys, setKeys] = React.useState<{ id: number; name: string; prefix: string; active: boolean }[]>([]);
  const [token, setToken] = React.useState('');
  const [providers, setProviders] = React.useState<{ provider: string; label: string; configured: boolean; enabled: boolean; hint: string; base_url: string; default_base_url: string }[]>([]);
  const [drafts, setDrafts] = React.useState<Record<string, { api_key: string; base_url: string }>>({});

  async function refresh() {
    setKeys((await api<{ keys: typeof keys }>('/api/console/keys')).keys);
    setProviders((await api<{ providers: typeof providers }>('/api/console/provider-keys')).providers);
  }
  React.useEffect(() => { refresh(); }, []);

  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">密钥</h1>
      <Panel title="调用 Delegate 的 API 密钥">
        <PrimaryButton onClick={async () => {
          const created = await api<{ token: string }>('/api/console/keys', { method: 'POST', body: JSON.stringify({ name: 'default' }) });
          setToken(created.token);
          refresh();
        }}>新建</PrimaryButton>
        {token && <p className="mt-3 break-all font-mono text-xs">只显示一次：{token}</p>}
        <ul className="mt-3 space-y-1 text-sm">
          {keys.map((key) => (
            <li key={key.id} className="flex items-center justify-between">
              <span>{key.name} · {key.prefix} · {key.active ? '有效' : '已吊销'}</span>
              {key.active && <button className="text-zinc-500" onClick={async () => { await api(`/api/console/keys/${key.id}/revoke`, { method: 'POST' }); refresh(); }}>吊销</button>}
            </li>
          ))}
        </ul>
      </Panel>
      <Panel title="自带模型密钥">
        <p className="mb-3 text-sm text-zinc-500">配了并且启用后，这个提供商的任务不再走平台计费，只收沙箱时间。删掉之后自动回到平台密钥。</p>
        {providers.map((row) => {
          const draft = drafts[row.provider] || { api_key: '', base_url: row.base_url };
          return (
            <form key={row.provider} className="mb-4 border-b border-zinc-200 pb-4 last:border-0 dark:border-zinc-800" onSubmit={async (event) => {
              event.preventDefault();
              await api(`/api/console/provider-keys/${row.provider}`, { method: 'POST', body: JSON.stringify({ ...draft, enabled: true }) });
              refresh();
            }}>
              <div className="mb-2 text-sm font-medium">{row.label} {row.configured ? `· 已保存 ····${row.hint}` : '· 未配置，使用平台'}</div>
              <Field label="API key"><TextInput type="password" value={draft.api_key} placeholder="留空则保留现有密钥" onChange={(e) => setDrafts({ ...drafts, [row.provider]: { ...draft, api_key: e.target.value } })} /></Field>
              <Field label="Base URL"><TextInput value={draft.base_url} placeholder={row.default_base_url} onChange={(e) => setDrafts({ ...drafts, [row.provider]: { ...draft, base_url: e.target.value } })} /></Field>
              <div className="flex gap-2">
                <PrimaryButton type="submit">保存</PrimaryButton>
                {row.configured && <button type="button" className="text-sm text-zinc-500" onClick={async () => { await api(`/api/console/provider-keys/${row.provider}`, { method: 'DELETE' }); refresh(); }}>删除并改回平台</button>}
              </div>
            </form>
          );
        })}
      </Panel>
    </div>
  );
}

function Billing({ reload }: { reload: () => Promise<void> }) {
  const [code, setCode] = React.useState('');
  const [logs, setLogs] = React.useState<{ time: number; model: string; input_tokens: number; output_tokens: number; cost_usd: number; content: string }[]>([]);
  const [message, setMessage] = React.useState('');
  React.useEffect(() => { api<{ logs: typeof logs }>('/api/console/billing').then((data) => setLogs(data.logs)); }, []);
  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">账单</h1>
      <Panel title="兑换充值码">
        <div className="flex flex-wrap gap-2">
          <TextInput value={code} onChange={(e) => setCode(e.target.value)} placeholder="DLG-..." />
          <PrimaryButton onClick={async () => {
            try {
              const result = await api<{ credited_usd: number }>('/api/console/billing/redeem', { method: 'POST', body: JSON.stringify({ code }) });
              setMessage(`已入账 ${result.credited_usd} USD`);
              setCode('');
              reload();
            } catch (err) {
              setMessage(err instanceof Error ? err.message : '兑换失败');
            }
          }}>兑换</PrimaryButton>
        </div>
        {message && <p className="mt-2 text-sm">{message}</p>}
      </Panel>
      <Panel title="网关流水">
        <ul className="space-y-1 text-sm">
          {logs.map((row, index) => <li key={index}>{row.model || row.content} · in {row.input_tokens} / out {row.output_tokens} · ${row.cost_usd}</li>)}
          {!logs.length && <li className="text-zinc-500">没有流水。</li>}
        </ul>
      </Panel>
    </div>
  );
}

function Audit() {
  const [rows, setRows] = React.useState<{ ts: string; action: string; actor: string; target: string | null }[]>([]);
  React.useEffect(() => { api<{ rows: typeof rows }>('/api/console/audit').then((data) => setRows(data.rows)); }, []);
  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">审计</h1>
      <Panel title="我的操作">
        <ul className="space-y-1 font-mono text-xs">
          {rows.map((row, index) => <li key={index}>{row.ts} {row.action} {row.target || ''}</li>)}
        </ul>
      </Panel>
    </div>
  );
}

function Settings({ session, reload }: { session: Session; reload: () => Promise<void> }) {
  const options = session.options!;
  const [agent, setAgent] = React.useState(options.agent);
  const [model, setModel] = React.useState(options.model);
  const [budget, setBudget] = React.useState('5');
  const [timeout, setTimeoutMin] = React.useState(String(Math.round(options.timeout_s / 60)));
  const [message, setMessage] = React.useState('');
  const models = session.models[agent] || [];
  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">设置</h1>
      <Panel title="任务默认">
        <Field label="Harness">
          <Select value={agent} onChange={(e) => { setAgent(e.target.value); setModel((session.models[e.target.value] || [])[0] || ''); }}>
            {session.agents.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          </Select>
        </Field>
        <Field label="模型">
          <Select value={model} onChange={(e) => setModel(e.target.value)}>
            {models.map((item) => <option key={item}>{item}</option>)}
          </Select>
        </Field>
        <Field label="平台密钥时的单任务预算（USD）"><TextInput value={budget} onChange={(e) => setBudget(e.target.value)} /></Field>
        <Field label="超时（分钟）"><TextInput value={timeout} onChange={(e) => setTimeoutMin(e.target.value)} /></Field>
        <PrimaryButton onClick={async () => {
          await api('/api/console/settings', { method: 'POST', body: JSON.stringify({ agent, model, budget_usd: Number(budget), timeout_min: Number(timeout) }) });
          setMessage('已保存');
          reload();
        }}>保存</PrimaryButton>
        {message && <p className="mt-2 text-sm">{message}</p>}
      </Panel>
    </div>
  );
}
