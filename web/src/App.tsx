import React, { useCallback, useEffect, useState } from 'react';
import { Sidebar } from './components/Sidebar';
import { OverviewDashboard, HeatmapData, SandboxSnapshot, UsageSnapshot } from './components/OverviewDashboard';
import { TasksView } from './components/TasksView';
import { NewTaskView } from './components/NewTaskView';
import { TaskTerminal } from './components/TaskTerminal';
import { ApiKeysView } from './components/ApiKeysView';
import { ProvidersView } from './components/ProvidersView';
import { McpGuideModal } from './components/McpGuideModal';
import { AuditView } from './components/AuditView';
import { LoginView } from './components/LoginView';
import { api, ConsoleOptions, SessionUser } from './lib/api';
import { ApiKeyItem, AuditRecord, ProviderItem, Task, NormEvent } from './types/delegate';

function fmtDate(value: unknown): string {
  if (!value || typeof value !== 'string') return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`;
}

function fmtClock(value: unknown): string {
  if (!value || typeof value !== 'string') return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value.slice(11, 19);
  return date.toTimeString().slice(0, 8);
}

function asTask(raw: Record<string, unknown>): Task {
  const events = Array.isArray(raw.events) ? raw.events.map((event) => asEvent(event as Record<string, unknown>)) : undefined;
  const outputs = Array.isArray(raw.outputs)
    ? raw.outputs.map((item) => {
        const file = item as Record<string, unknown>;
        return {
          path: String(file.path || ''),
          size: Number(file.size || 0),
          sha256: file.sha256 ? String(file.sha256) : undefined,
          downloadUrl: file.download_url ? String(file.download_url) : file.downloadUrl ? String(file.downloadUrl) : undefined,
        };
      })
    : undefined;
  return {
    ...(raw as unknown as Task),
    created_at: fmtDate(raw.created_at),
    started_at: raw.started_at ? fmtDate(raw.started_at) : undefined,
    finished_at: raw.finished_at ? fmtDate(raw.finished_at) : undefined,
    events,
    outputs,
    patch_stats: (raw.patch_stats as Task['patch_stats']) || undefined,
    agent_usage: (raw.agent_usage as Task['agent_usage']) || undefined,
    raw_patch: (raw.raw_patch as string | null) || undefined,
    result_text: (raw.result_text as string | null) || undefined,
  };
}

function asEvent(raw: Record<string, unknown>): NormEvent & { seq?: number } {
  return {
    id: String(raw.id),
    seq: Number(raw.seq || 0),
    ts: fmtClock(raw.ts),
    kind: raw.kind as NormEvent['kind'],
    summary: String(raw.summary || ''),
    phase: raw.phase ? String(raw.phase) : undefined,
    tool_name: raw.tool_name ? String(raw.tool_name) : undefined,
    tool_args: raw.tool_args as NormEvent['tool_args'],
    tool_result: raw.tool_result ? String(raw.tool_result) : undefined,
    data: raw.data as Record<string, unknown> | undefined,
  };
}

function asKey(raw: Record<string, unknown>): ApiKeyItem {
  return {
    id: Number(raw.id),
    name: String(raw.name || ''),
    prefix: String(raw.prefix || ''),
    created_at: fmtDate(raw.created_at),
    last_used_at: raw.last_used_at ? fmtDate(raw.last_used_at) : null,
    last_used_ip: raw.last_used_ip ? String(raw.last_used_ip) : null,
    active: Boolean(raw.active),
  };
}

function asProvider(raw: Record<string, unknown>): ProviderItem {
  return {
    id: String(raw.id),
    name: String(raw.name || raw.id),
    pythonPackage: String(raw.python_package || ''),
    envKeyVar: String(raw.env_key || ''),
    envBaseUrlVar: String(raw.env_base_url || ''),
    configured: Boolean(raw.configured),
    apiKeyMasked: raw.api_key_masked ? String(raw.api_key_masked) : '',
    baseUrl: raw.base_url ? String(raw.base_url) : '',
    models: Array.isArray(raw.models) ? raw.models.map(String) : [],
    defaultModel: String(raw.default_model || ''),
  };
}

function asAudit(raw: Record<string, unknown>): AuditRecord {
  return {
    id: String(raw.id),
    ts: fmtDate(raw.ts),
    action: String(raw.action || ''),
    actor: String(raw.actor || ''),
    ip: String(raw.ip || ''),
    detail: (raw.detail as Record<string, unknown>) || {},
  };
}

export default function App() {
  const [booting, setBooting] = useState(true);
  const [user, setUser] = useState<SessionUser | null>(null);
  const [options, setOptions] = useState<ConsoleOptions>({});
  const [allowRegistration, setAllowRegistration] = useState(true);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [apiKeys, setApiKeys] = useState<ApiKeyItem[]>([]);
  const [providers, setProviders] = useState<ProviderItem[]>([]);
  const [canEditProviders, setCanEditProviders] = useState(false);
  const [auditLogs, setAuditLogs] = useState<AuditRecord[]>([]);
  const [sandbox, setSandbox] = useState<SandboxSnapshot | undefined>();
  const [usage, setUsage] = useState<UsageSnapshot | undefined>();
  const [heatmap, setHeatmap] = useState<HeatmapData | undefined>();
  const [activeTab, setActiveTab] = useState('home');
  const [selectedTaskId, setSelectedTaskId] = useState<string>('');
  const [isDark, setIsDark] = useState(true);
  const [newlyCreatedToken, setNewlyCreatedToken] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    document.documentElement.classList.toggle('dark', isDark);
  }, [isDark]);

  const applySession = (payload: { user: SessionUser | null; options?: ConsoleOptions }) => {
    setUser(payload.user);
    if (payload.options) {
      setOptions(payload.options);
      setAllowRegistration(payload.options.allow_registration !== false);
    }
  };

  const refreshHome = useCallback(async () => {
    const [dash, list] = await Promise.all([api.dashboard(), api.tasks()]);
    const dashboard = dash as {
      sandbox?: SandboxSnapshot;
      usage?: UsageSnapshot;
      heatmap?: HeatmapData;
      options?: ConsoleOptions;
    };
    setSandbox(dashboard.sandbox);
    setUsage(dashboard.usage);
    setHeatmap(dashboard.heatmap);
    if (dashboard.options) setOptions(dashboard.options);
    setTasks((prev) => (list.tasks || []).map((row) => {
      const next = asTask(row);
      const existing = prev.find((task) => task.id === next.id);
      if (!existing) return next;
      return {
        ...next,
        events: existing.events?.length ? existing.events : next.events,
        raw_patch: existing.raw_patch || next.raw_patch,
        outputs: existing.outputs?.length ? existing.outputs : next.outputs,
        result_text: existing.result_text || next.result_text,
      };
    }));
  }, []);

  useEffect(() => {
    api.session()
      .then(async (payload) => {
        applySession(payload);
        setAllowRegistration(payload.options?.allow_registration !== false);
        if (payload.user) await refreshHome();
      })
      .catch((err: Error) => setError(err.message))
      .finally(() => setBooting(false));
  }, [refreshHome]);

  const selectedTask = tasks.find((task) => task.id === selectedTaskId);

  useEffect(() => {
    if (activeTab !== 'task-detail' || !selectedTask) return;
    if (!['queued', 'preparing', 'running'].includes(selectedTask.status)) return;
    const taskId = selectedTask.id;
    const timer = window.setInterval(async () => {
      const current = tasks.find((task) => task.id === taskId);
      const after = Math.max(0, ...(current?.events || []).map((event) => Number((event as NormEvent & { seq?: number }).seq || 0)));
      try {
        const snap = await api.taskEvents(taskId, after);
        setTasks((prev) => prev.map((task) => {
          if (task.id !== taskId) return task;
          const incoming = Array.isArray(snap.events) ? snap.events.map((event) => asEvent(event as Record<string, unknown>)) : [];
          const outputs = Array.isArray(snap.outputs)
            ? (snap.outputs as Record<string, unknown>[]).map((file) => ({
                path: String(file.path || ''),
                size: Number(file.size || 0),
                downloadUrl: file.download_url ? String(file.download_url) : undefined,
              }))
            : task.outputs;
          return {
            ...task,
            status: String(snap.status || task.status) as Task['status'],
            status_reason: (snap.status_reason as string | null) || task.status_reason,
            duration_s: snap.duration_s == null ? task.duration_s : Number(snap.duration_s),
            result_text: (snap.result_text as string | null) || task.result_text,
            agent_usage: (snap.agent_usage as Task['agent_usage']) || task.agent_usage,
            patch_stats: (snap.patch_stats as Task['patch_stats']) || task.patch_stats,
            raw_patch: (snap.raw_patch as string | null) || task.raw_patch,
            outputs,
            events: [...(task.events || []), ...incoming],
          };
        }));
      } catch {
        // Keep the last snapshot if a poll fails.
      }
    }, 2000);
    return () => window.clearInterval(timer);
  }, [activeTab, selectedTask?.id, selectedTask?.status, tasks]);

  const openTask = async (task: Task) => {
    setError(null);
    setSelectedTaskId(task.id);
    setActiveTab('task-detail');
    try {
      const detail = await api.task(task.id);
      const next = asTask(detail);
      setTasks((prev) => {
        const exists = prev.some((item) => item.id === next.id);
        return exists ? prev.map((item) => (item.id === next.id ? next : item)) : [next, ...prev];
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : '任务加载失败');
    }
  };

  const handleOpenNewTask = async (config?: { model?: string; harness?: string }) => {
    setError(null);
    try {
      if (config?.harness || config?.model) {
        const saved = await api.saveSettings({
          harness: config.harness,
          model: config.model,
          agent: options.current?.agent,
          sandbox: options.current?.sandbox,
        });
        if (saved.options) setOptions(saved.options);
      }
      setActiveTab('new-task');
    } catch (err) {
      setError(err instanceof Error ? err.message : '无法切换执行器');
    }
  };

  const handleLaunchTask = async (taskData: Partial<Task>) => {
    setError(null);
    try {
      const created = await api.createTask({
        task: taskData.prompt || '',
        title: taskData.title,
        ...(taskData.harness && taskData.harness !== current?.harness ? { harness: taskData.harness } : {}),
        ...(taskData.model && taskData.model !== current?.model ? { model: taskData.model } : {}),
        ...(taskData.agent && taskData.agent !== current?.agent ? { agent: taskData.agent } : {}),
      });
      const next = asTask(created);
      setTasks((prev) => [next, ...prev.filter((task) => task.id !== next.id)]);
      setSelectedTaskId(next.id);
      setActiveTab('task-detail');
      await refreshHome();
    } catch (err) {
      setError(err instanceof Error ? err.message : '任务提交失败');
    }
  };

  const handleCancelTask = async (taskId: string) => {
    setError(null);
    try {
      const result = await api.cancelTask(taskId);
      setTasks((prev) => prev.map((task) => task.id === taskId ? {
        ...task,
        status: String(result.status || 'cancelled') as Task['status'],
        status_reason: (result.status_reason as string | undefined) || task.status_reason,
      } : task));
    } catch (err) {
      setError(err instanceof Error ? err.message : '取消失败');
    }
  };

  const loadKeys = async () => {
    const payload = await api.keys();
    setApiKeys((payload.keys || []).map(asKey));
  };

  const loadProviders = async () => {
    const payload = await api.providers();
    setProviders((payload.providers || []).map(asProvider));
    setCanEditProviders(Boolean(payload.can_edit));
  };

  const loadAudit = async () => {
    const payload = await api.audit();
    setAuditLogs((payload.logs || []).map(asAudit));
  };

  useEffect(() => {
    if (!user) return;
    if (activeTab === 'keys') loadKeys().catch((err: Error) => setError(err.message));
    if (activeTab === 'providers') loadProviders().catch((err: Error) => setError(err.message));
    if (activeTab === 'audit') loadAudit().catch((err: Error) => setError(err.message));
    if (activeTab === 'home' || activeTab === 'tasks') refreshHome().catch((err: Error) => setError(err.message));
  }, [activeTab, user, refreshHome]);

  if (booting) {
    return <div className="min-h-screen bg-[#0a0a0c] text-zinc-500 text-xs p-8">正在连接…</div>;
  }

  if (!user) {
    return (
      <LoginView
        allowRegistration={allowRegistration}
        error={error}
        onLogin={async (email, password) => {
          setError(null);
          try {
            const payload = await api.login(email, password);
            applySession(payload);
            await refreshHome();
          } catch (err) {
            setError(err instanceof Error ? err.message : '登录失败');
          }
        }}
        onRegister={async (email, password, displayName) => {
          setError(null);
          try {
            const payload = await api.register(email, password, displayName);
            applySession(payload);
            await refreshHome();
          } catch (err) {
            setError(err instanceof Error ? err.message : '注册失败');
          }
        }}
      />
    );
  }

  const current = options.current;
  const activeKey = apiKeys.find((key) => key.active)?.prefix;

  return (
    <div className="h-screen overflow-hidden bg-[#fafaf9] text-zinc-900 dark:bg-[#0a0a0c] dark:text-zinc-100 flex">
      <Sidebar
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        taskCount={tasks.length}
        userEmail={user.email}
        userName={user.display_name}
        initials={user.initials}
        isDark={isDark}
        toggleTheme={() => setIsDark((prev) => !prev)}
        onLogout={async () => {
          await api.logout();
          setUser(null);
          setTasks([]);
          setApiKeys([]);
          setActiveTab('home');
        }}
      />

      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <main key={activeTab} className="page-enter min-w-0 flex-1 overflow-auto p-6 md:p-10">
          {error && (
            <div className="mb-4 rounded-lg border border-zinc-300 dark:border-zinc-700 px-3 py-2 text-xs flex items-center justify-between">
              <span>{error}</span>
              <button onClick={() => setError(null)} className="text-zinc-400 cursor-pointer">关闭</button>
            </div>
          )}

          {activeTab === 'home' && (
            <OverviewDashboard
              tasks={tasks}
              sandbox={sandbox}
              usage={usage}
              heatmap={heatmap}
              onSelectTask={openTask}
              onOpenNewTask={handleOpenNewTask}
              onNavigateTab={setActiveTab}
              userName={user.display_name.split(/\s+/)[0] || user.display_name}
            />
          )}

          {activeTab === 'tasks' && (
            <TasksView
              tasks={tasks}
              onSelectTask={openTask}
              onOpenNewTask={() => setActiveTab('new-task')}
            />
          )}

          {activeTab === 'new-task' && (
            <NewTaskView
              onLaunch={handleLaunchTask}
              onCancel={() => setActiveTab('tasks')}
              initialModel={current?.model || ''}
              initialHarness={current?.harness || 'sdk'}
            />
          )}

          {activeTab === 'task-detail' && (
            <TaskTerminal
              task={selectedTask}
              models={options.models?.[selectedTask?.agent || current?.agent || ''] || []}
              harnesses={options.harnesses || []}
              sandboxDefaults={options.sandbox}
              onBack={() => setActiveTab('tasks')}
              onCancelTask={handleCancelTask}
            />
          )}

          {activeTab === 'keys' && (
            <ApiKeysView
              keys={apiKeys}
              mcpUrl={options.mcp_url}
              newlyCreatedToken={newlyCreatedToken}
              onClearNewToken={() => setNewlyCreatedToken(null)}
              onCreateKey={async (name) => {
                const created = await api.createKey(name);
                setNewlyCreatedToken(created.token);
                await loadKeys();
              }}
              onRevokeKey={async (id) => {
                await api.revokeKey(id);
                await loadKeys();
              }}
            />
          )}

          {activeTab === 'providers' && (
            <ProvidersView
              providers={providers}
              canEdit={canEditProviders}
              onUpdateProvider={async (id, updates) => {
                const saved = await api.saveProvider(id, {
                  base_url: updates.baseUrl || '',
                  api_key: updates.apiKey || '',
                  clear_api_key: updates.clearApiKey,
                  enabled: true,
                });
                setProviders((saved.providers || []).map(asProvider));
              }}
              onTestProvider={async (id) => {
                const result = await api.checkProvider(id);
                return result.message;
              }}
            />
          )}

          {activeTab === 'mcp' && (
            <McpGuideModal
              mcpUrl={options.mcp_url}
              activeKeyPrefix={activeKey || 'dlg_'}
            />
          )}

          {activeTab === 'audit' && <AuditView logs={auditLogs} />}
        </main>
      </div>
    </div>
  );
}
