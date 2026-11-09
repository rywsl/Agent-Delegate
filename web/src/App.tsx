import React, { useCallback, useEffect, useState } from 'react';
import { Sidebar, type Tab } from './components/Sidebar';
import { OverviewDashboard } from './components/OverviewDashboard';
import { TasksView } from './components/TasksView';
import { NewTaskView } from './components/NewTaskView';
import { TaskTerminal } from './components/TaskTerminal';
import { ApiKeysView } from './components/ApiKeysView';
import { ProvidersView } from './components/ProvidersView';
import { McpGuideModal } from './components/McpGuideModal';
import { AuditView } from './components/AuditView';
import { BillingView } from './components/BillingView';
import { AdminViews } from './components/AdminViews';
import { api, loadSession, type Session } from './lib/api';
import type { ApiKeyItem, AuditRecord, ProviderItem, Task } from './types/delegate';

type Dash = {
  sandbox?: { memory: string; cpus: number; capacity: number; active: number; uid: number };
  usage?: { tokens: number; cache_rate: number };
  heatmap?: { cells: number[]; months: string[]; patch_lines: number; active_month: string; peak_date: string };
  queue?: { waiting: number; max: number };
  sandbox_usd_per_minute?: number;
};

function asTask(raw: Record<string, unknown>): Task {
  return {
    id: String(raw.id || ''),
    title: String(raw.title || ''),
    prompt: String(raw.prompt || ''),
    source: (['mcp', 'api', 'web', 'tui-cli'].includes(String(raw.source)) ? raw.source : 'web') as Task['source'],
    status: String(raw.status || 'queued') as Task['status'],
    status_reason: (raw.status_reason as string | undefined) || undefined,
    agent: String(raw.agent || ''),
    model: String(raw.model || ''),
    sandbox: 'docker',
    harness: String(raw.harness || raw.agent || ''),
    timeout_s: Number(raw.timeout_s || 0),
    max_turns: Number(raw.max_turns || 0),
    created_at: String(raw.created_at || ''),
    started_at: (raw.started_at as string | undefined) || undefined,
    finished_at: (raw.finished_at as string | undefined) || undefined,
    duration_s: raw.duration_s == null ? undefined : Number(raw.duration_s),
    container_name: (raw.container_name as string | undefined) || undefined,
    sandbox_limits: (raw.sandbox_limits as Task['sandbox_limits']) || undefined,
    result_text: (raw.result_text as string | undefined) || undefined,
    raw_patch: (raw.raw_patch as string | undefined) || undefined,
    patch_stats: (raw.patch_stats as Task['patch_stats']) || undefined,
    outputs: Array.isArray(raw.outputs) ? raw.outputs as Task['outputs'] : [],
    agent_usage: (raw.agent_usage as Task['agent_usage']) || undefined,
    events: Array.isArray(raw.events) ? raw.events as Task['events'] : [],
  };
}

function Login({ session, onDone }: { session: Session; onDone: (session: Session) => void }) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const path = mode === 'login' ? '/api/console/login' : '/api/console/register';
      onDone(await api<Session>(path, { method: 'POST', body: JSON.stringify({ email, password, display_name: name }) }));
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#fafaf9] p-6 text-zinc-900 dark:bg-[#0a0a0c] dark:text-zinc-100">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-[#111113]">
        <div className="flex items-center gap-2">
          <div className="flex h-6 w-6 items-center justify-center rounded-md bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-950">
            <svg viewBox="0 0 24 24" className="h-3.5 w-3.5 fill-none stroke-current stroke-[2.2]" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="9" /><line x1="5.6" y1="5.6" x2="18.4" y2="18.4" />
            </svg>
          </div>
          <h1 className="text-sm font-semibold tracking-tight">Delegate</h1>
        </div>
        <p className="text-xs text-zinc-500">{mode === 'login' ? '登录后查看沙箱任务与审计记录。' : '注册后即可提交隔离沙箱任务。'}</p>
        {mode === 'register' && <input value={name} onChange={(event) => setName(event.target.value)} placeholder="昵称" className="w-full rounded-lg border border-zinc-200 bg-transparent px-3 py-2 text-sm dark:border-zinc-800" />}
        <input type="email" required value={email} onChange={(event) => setEmail(event.target.value)} placeholder="邮箱" className="w-full rounded-lg border border-zinc-200 bg-transparent px-3 py-2 text-sm dark:border-zinc-800" />
        <input type="password" required minLength={8} value={password} onChange={(event) => setPassword(event.target.value)} placeholder="密码" className="w-full rounded-lg border border-zinc-200 bg-transparent px-3 py-2 text-sm dark:border-zinc-800" />
        {error && <p className="text-xs text-zinc-700 dark:text-zinc-200">{error}</p>}
        <button disabled={busy} className="w-full cursor-pointer rounded-lg bg-zinc-900 px-3 py-2 text-xs font-medium text-white disabled:opacity-40 dark:bg-zinc-100 dark:text-zinc-950">{busy ? '请稍候…' : mode === 'login' ? '登录' : '注册'}</button>
        {session.allow_registration && (
          <button type="button" className="w-full cursor-pointer text-xs text-zinc-500" onClick={() => setMode(mode === 'login' ? 'register' : 'login')}>
            {mode === 'login' ? '没有账户？注册' : '已有账户？登录'}
          </button>
        )}
      </form>
    </div>
  );
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [bootError, setBootError] = useState('');
  const [error, setError] = useState('');
  const [tab, setTab] = useState<Tab>('home');
  const [dark, setDark] = useState(true);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [selectedId, setSelectedId] = useState('');
  const [dash, setDash] = useState<Dash>({});
  const [keys, setKeys] = useState<ApiKeyItem[]>([]);
  const [freshToken, setFreshToken] = useState<string | null>(null);
  const [providers, setProviders] = useState<ProviderItem[]>([]);
  const [logs, setLogs] = useState<AuditRecord[]>([]);
  const [draftHarness, setDraftHarness] = useState('claude');

  useEffect(() => { document.documentElement.classList.toggle('dark', dark); }, [dark]);

  const refreshHome = useCallback(async () => {
    const [home, list] = await Promise.all([
      api<Dash>('/api/console/dashboard'),
      api<{ tasks: Record<string, unknown>[] }>('/api/console/tasks'),
    ]);
    setDash(home);
    setTasks((prev) => (list.tasks || []).map((row) => {
      const next = asTask(row);
      const existing = prev.find((task) => task.id === next.id);
      if (!existing) return next;
      return { ...next, events: existing.events?.length ? existing.events : next.events, raw_patch: existing.raw_patch || next.raw_patch, prompt: existing.prompt || next.prompt, result_text: existing.result_text || next.result_text };
    }));
  }, []);

  useEffect(() => {
    loadSession().then(async (next) => {
      setSession(next);
      if (next.user) await refreshHome();
    }).catch((err: Error) => setBootError(err.message));
  }, [refreshHome]);

  const selected = tasks.find((task) => task.id === selectedId);

  useEffect(() => {
    if (tab !== 'task-detail' || !selected) return;
    if (!['queued', 'preparing', 'running'].includes(selected.status)) return;
    const taskId = selected.id;
    const timer = window.setInterval(async () => {
      const current = tasks.find((task) => task.id === taskId);
      const after = Math.max(0, ...(current?.events || []).map((event) => Number((event as { seq?: number }).seq || 0)));
      try {
        const snap = await api<Record<string, unknown>>(`/api/console/tasks/${taskId}/events?after=${after}`);
        setTasks((prev) => prev.map((task) => {
          if (task.id !== taskId) return task;
          const incoming = Array.isArray(snap.events) ? (snap.events as Record<string, unknown>[]).map((event) => ({
            id: String(event.id || event.seq),
            seq: Number(event.seq || 0),
            ts: String(event.ts || ''),
            kind: String(event.kind || 'log') as NonNullable<Task['events']>[number]['kind'],
            summary: String(event.summary || ''),
            tool_name: event.tool_name ? String(event.tool_name) : undefined,
            tool_args: event.tool_args as Record<string, unknown> | string | undefined,
            tool_result: event.tool_result ? String(event.tool_result) : undefined,
          })) : [];
          return {
            ...task,
            status: String(snap.status || task.status) as Task['status'],
            status_reason: (snap.status_reason as string | undefined) || task.status_reason,
            duration_s: snap.duration_s == null ? task.duration_s : Number(snap.duration_s),
            result_text: (snap.result_text as string | undefined) || task.result_text,
            agent_usage: (snap.agent_usage as Task['agent_usage']) || task.agent_usage,
            patch_stats: (snap.patch_stats as Task['patch_stats']) || task.patch_stats,
            raw_patch: (snap.raw_patch as string | undefined) || task.raw_patch,
            outputs: Array.isArray(snap.outputs) ? snap.outputs as Task['outputs'] : task.outputs,
            events: [...(task.events || []), ...incoming],
          };
        }));
      } catch {
        // Keep the last frame if a poll fails.
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [tab, selected?.id, selected?.status, tasks]);

  async function openTask(task: Task) {
    setSelectedId(task.id);
    setTab('task-detail');
    try {
      const detail = asTask(await api<Record<string, unknown>>(`/api/console/tasks/${task.id}`));
      setTasks((prev) => prev.some((item) => item.id === detail.id) ? prev.map((item) => item.id === detail.id ? detail : item) : [detail, ...prev]);
    } catch (err) {
      setError(err instanceof Error ? err.message : '任务加载失败');
    }
  }

  async function openNew(config?: { harness?: string; model?: string }) {
    const harness = config?.harness || session?.options?.agent || 'claude';
    const model = config?.model || (session?.models[harness] || [])[0] || session?.options?.model || '';
    setDraftHarness(harness);
    if (session?.options && (harness !== session.options.agent || model !== session.options.model)) {
      try {
        await api('/api/console/settings', { method: 'POST', body: JSON.stringify({ agent: harness, model }) });
        setSession(await loadSession());
      } catch (err) {
        setError(err instanceof Error ? err.message : '无法切换执行器');
        return;
      }
    }
    setTab('new-task');
  }

  async function launch(taskData: Partial<Task>) {
    try {
      const created = asTask(await api<Record<string, unknown>>('/api/console/tasks', {
        method: 'POST',
        body: JSON.stringify({ task: taskData.prompt || '', title: taskData.title }),
      }));
      setTasks((prev) => [created, ...prev.filter((task) => task.id !== created.id)]);
      setSelectedId(created.id);
      setTab('task-detail');
      await refreshHome();
    } catch (err) {
      setError(err instanceof Error ? err.message : '任务提交失败');
    }
  }

  useEffect(() => {
    if (!session?.user) return;
    if (tab === 'keys') api<{ keys: ApiKeyItem[] }>('/api/console/keys').then((data) => setKeys(data.keys)).catch((err: Error) => setError(err.message));
    if (tab === 'providers') {
      api<{ providers: { provider: string; label: string; harness: string; configured: boolean; hint: string; base_url: string }[] }>('/api/console/provider-keys').then((data) => {
        setProviders(data.providers.map((row) => ({
          id: row.provider,
          name: row.label,
          pythonPackage: row.harness,
          envKeyVar: 'API_KEY',
          envBaseUrlVar: 'BASE_URL',
          configured: row.configured,
          apiKeyMasked: row.hint ? `····${row.hint}` : undefined,
          baseUrl: row.base_url,
          models: session.models[row.harness] || [],
          defaultModel: (session.models[row.harness] || [])[0] || '',
        })));
      }).catch((err: Error) => setError(err.message));
    }
    if (tab === 'audit') {
      api<{ logs: AuditRecord[] }>('/api/console/audit').then((data) => setLogs(data.logs || [])).catch((err: Error) => setError(err.message));
    }
    if (tab === 'home' || tab === 'tasks') refreshHome().catch((err: Error) => setError(err.message));
  }, [tab, session, refreshHome]);

  if (bootError) return <p className="p-8 text-sm text-zinc-500">{bootError}</p>;
  if (!session) return <p className="p-8 text-xs text-zinc-500">正在连接…</p>;
  if (!session.user) return <Login session={session} onDone={setSession} />;

  const user = session.user;
  const initials = (user.display_name || user.email).slice(0, 2).toUpperCase();
  const billingLine = `${user.balance_usd == null ? '余额暂不可用' : `余额 ${user.balance_usd} USD`} · 免费沙箱 ${Math.floor(user.sandbox_free_seconds / 60)} 分钟 · ${user.billing_mode === 'byok' ? '自带密钥' : '平台密钥'}`;
  const queueLine = dash.queue ? `排队 ${dash.queue.waiting}/${dash.queue.max}` : undefined;

  return (
    <div className="flex h-screen overflow-hidden bg-[#fafaf9] text-zinc-900 dark:bg-[#0a0a0c] dark:text-zinc-100">
      <Sidebar
        activeTab={tab}
        setActiveTab={setTab}
        taskCount={tasks.length}
        userName={user.display_name}
        userEmail={user.email}
        initials={initials}
        isDark={dark}
        admin={user.is_admin}
        toggleTheme={() => setDark((value) => !value)}
        onLogout={async () => {
          await api('/api/console/logout', { method: 'POST' });
          setSession(await loadSession());
          setTab('home');
        }}
      />
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
        <main key={tab} className="page-enter min-w-0 flex-1 overflow-auto p-6 md:p-10">
          <div className="mx-auto w-full max-w-6xl">
            {error && (
              <div className="mb-4 flex items-center justify-between rounded-lg border border-zinc-300 px-3 py-2 text-xs dark:border-zinc-700">
                <span>{error}</span>
                <button className="cursor-pointer text-zinc-400" onClick={() => setError('')}>关闭</button>
              </div>
            )}
            {tab === 'home' && (
              <OverviewDashboard tasks={tasks} sandbox={dash.sandbox} usage={dash.usage} heatmap={dash.heatmap}
                billingLine={billingLine} queueLine={queueLine} userName={user.display_name.split(/\s+/)[0] || user.display_name}
                onSelectTask={openTask} onOpenNewTask={openNew} onNavigateTab={(next) => setTab(next as Tab)} />
            )}
            {tab === 'tasks' && <TasksView tasks={tasks} onSelectTask={openTask} onOpenNewTask={() => setTab('new-task')} />}
            {tab === 'new-task' && <NewTaskView onLaunch={launch} onCancel={() => setTab('tasks')} initialHarness={draftHarness} initialModel={session.options?.model || ''} />}
            {tab === 'task-detail' && (
              <TaskTerminal
                task={selected}
                models={session.models[selected?.agent || session.options?.agent || ''] || []}
                harnesses={session.agents.map((item) => item.id)}
                sandboxDefaults={dash.sandbox}
                onBack={() => setTab('tasks')}
                onCancelTask={async (taskId) => {
                  const result = await api<{ status: string }>(`/api/console/tasks/${taskId}/cancel`, { method: 'POST' });
                  setTasks((prev) => prev.map((task) => task.id === taskId ? { ...task, status: result.status as Task['status'] } : task));
                }}
              />
            )}
            {tab === 'keys' && (
              <ApiKeysView keys={keys} newlyCreatedToken={freshToken} onClearNewToken={() => setFreshToken(null)}
                onCreateKey={async (name) => {
                  const created = await api<{ token: string }>('/api/console/keys', { method: 'POST', body: JSON.stringify({ name }) });
                  setFreshToken(created.token);
                  setKeys((await api<{ keys: ApiKeyItem[] }>('/api/console/keys')).keys);
                }}
                onRevokeKey={async (id) => {
                  await api(`/api/console/keys/${id}/revoke`, { method: 'POST' });
                  setKeys((await api<{ keys: ApiKeyItem[] }>('/api/console/keys')).keys);
                }} />
            )}
            {tab === 'providers' && (
              <ProvidersView providers={providers} onUpdateProvider={async (id, updates) => {
                const saved = await api<{ providers: { provider: string; label: string; harness: string; configured: boolean; hint: string; base_url: string }[] }>(`/api/console/provider-keys/${id}`, {
                  method: 'POST',
                  body: JSON.stringify({ api_key: updates.apiKey || '', base_url: updates.baseUrl || '', enabled: true }),
                });
                setProviders(saved.providers.map((row) => ({
                  id: row.provider, name: row.label, pythonPackage: row.harness, envKeyVar: 'API_KEY', envBaseUrlVar: 'BASE_URL',
                  configured: row.configured, apiKeyMasked: row.hint ? `····${row.hint}` : undefined, baseUrl: row.base_url,
                  models: session.models[row.harness] || [], defaultModel: (session.models[row.harness] || [])[0] || '',
                })));
              }} />
            )}
            {tab === 'mcp' && <McpGuideModal activeKeyPrefix={keys.find((key) => key.active)?.prefix || 'dlg_'} />}
            {tab === 'audit' && <AuditView logs={logs} />}
            {tab === 'billing' && <BillingView reload={async () => setSession(await loadSession())} />}
            {tab.startsWith('admin-') && <AdminViews tab={tab} />}
          </div>
        </main>
      </div>
    </div>
  );
}
