import React from 'react';
import { Field, Panel, PrimaryButton, TextInput } from './ui';
import { api } from '../lib/api';
import type { Tab } from './Sidebar';

type Settings = {
  sandbox_usd_per_minute: number;
  free_sandbox_minutes: number;
  max_queued_tasks: number;
  max_queued_per_user: number;
  sandbox_max_concurrent: number;
  per_user_concurrency: number;
  models: Record<string, string[]>;
  harnesses: { id: string; label: string; package: string; binary: string }[];
  harness_updated_at: string | null;
  channel_types: { id: number; label: string }[];
};

export function AdminViews({ tab }: { tab: Tab }) {
  if (tab === 'admin-users') return <Users />;
  if (tab === 'admin-codes') return <Codes />;
  if (tab === 'admin-channels') return <Channels />;
  if (tab === 'admin-settings') return <Platform />;
  if (tab === 'admin-tasks') return <Tasks />;
  return <Overview />;
}

function Overview() {
  const [data, setData] = React.useState<{ newapi_ok: boolean; newapi_message: string; counts: Record<string, number>; users: number; settings: Settings } | null>(null);
  const [update, setUpdate] = React.useState('');
  React.useEffect(() => { api<typeof data>('/api/console/admin/overview').then(setData); }, []);
  if (!data) return <p className="text-sm text-zinc-500">加载中…</p>;
  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">管理概览</h1>
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <Panel title="new-api"><p>{data.newapi_ok ? '正常' : '异常'}</p><p className="text-xs text-zinc-500">{data.newapi_message}</p></Panel>
        <Panel title="用户"><p className="text-2xl">{data.users}</p></Panel>
        <Panel title="任务">{Object.entries(data.counts).map(([status, count]) => <p key={status} className="text-sm">{status} {count}</p>)}</Panel>
      </div>
      <Panel title="沙箱 CLI">
        <p className="mb-2 text-sm text-zinc-500">不锁版本。点更新会把当前发布版装进共享卷，新任务优先用这套，不用改环境变量。</p>
        <ul className="mb-3 text-sm">{data.settings.harnesses.map((item) => <li key={item.id}>{item.label} · {item.package} · {item.binary}</li>)}</ul>
        <PrimaryButton onClick={async () => {
          setUpdate('正在安装…');
          try {
            await api('/api/console/admin/harnesses/update', { method: 'POST' });
            setUpdate('已更新');
          } catch (err) {
            setUpdate(err instanceof Error ? err.message : '更新失败');
          }
        }}>更新全部 CLI</PrimaryButton>
        {update && <p className="mt-2 text-sm">{update}</p>}
      </Panel>
    </div>
  );
}

function Users() {
  const [rows, setRows] = React.useState<{ id: number; email: string; is_admin: boolean; is_active: boolean; sandbox_free_seconds: number | null }[]>([]);
  const [usd, setUsd] = React.useState('5');
  async function refresh() { setRows((await api<{ users: typeof rows }>('/api/console/admin/users')).users); }
  React.useEffect(() => { refresh(); }, []);
  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">用户</h1>
      <Panel title="账户">
        {rows.map((row) => (
          <div key={row.id} className="mb-3 border-b border-zinc-200 pb-3 text-sm last:border-0 dark:border-zinc-800">
            <div className="font-medium">{row.email} {row.is_admin ? '· 管理员' : ''} {row.is_active ? '' : '· 已停用'}</div>
            <div className="text-zinc-500">免费沙箱 {row.sandbox_free_seconds ?? 0} 秒</div>
            <div className="mt-2 flex flex-wrap gap-2">
              <TextInput value={usd} onChange={(e) => setUsd(e.target.value)} />
              <button className="text-zinc-600" onClick={async () => { await api(`/api/console/admin/users/${row.id}/quota`, { method: 'POST', body: JSON.stringify({ usd: Number(usd), direction: 'add' }) }); }}>充值</button>
              <button className="text-zinc-600" onClick={async () => { await api(`/api/console/admin/users/${row.id}/free-seconds`, { method: 'POST', body: JSON.stringify({ seconds: 3600 }) }); refresh(); }}>赠送 60 分钟</button>
              <button className="text-zinc-600" onClick={async () => { await api(`/api/console/admin/users/${row.id}/toggle?field=active`, { method: 'POST' }); refresh(); }}>停用/启用</button>
            </div>
          </div>
        ))}
      </Panel>
    </div>
  );
}

function Codes() {
  const [amount, setAmount] = React.useState('10');
  const [fresh, setFresh] = React.useState<string[]>([]);
  const [rows, setRows] = React.useState<{ id: number; hint: string; quota_usd: number; note: string }[]>([]);
  async function refresh() { setRows((await api<{ codes: typeof rows }>('/api/console/admin/codes')).codes); }
  React.useEffect(() => { refresh(); }, []);
  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">充值码</h1>
      <Panel title="生成">
        <Field label="面额（USD）"><TextInput value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
        <PrimaryButton onClick={async () => {
          const created = await api<{ codes: string[] }>('/api/console/admin/codes', { method: 'POST', body: JSON.stringify({ amount_usd: Number(amount), count: 1 }) });
          setFresh(created.codes);
          refresh();
        }}>生成</PrimaryButton>
        {fresh.map((code) => <p key={code} className="mt-2 font-mono text-sm">{code}</p>)}
      </Panel>
      <Panel title="记录">
        {rows.map((row) => <p key={row.id} className="text-sm">…{row.hint} · ${row.quota_usd} · {row.note}</p>)}
      </Panel>
    </div>
  );
}

function Channels() {
  const [types, setTypes] = React.useState<{ id: number; label: string }[]>([]);
  const [rows, setRows] = React.useState<{ id: number; name: string; type: number; models: string; base_url: string; has_key: boolean }[]>([]);
  const [form, setForm] = React.useState({ name: '', type: 14, key: '', base_url: '', models: '', group: 'default' });
  const [message, setMessage] = React.useState('');
  async function refresh() {
    const data = await api<{ channels: typeof rows; types: typeof types }>('/api/console/admin/channels');
    setRows(data.channels);
    setTypes(data.types);
  }
  React.useEffect(() => { refresh().catch((err) => setMessage(err.message)); }, []);
  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">上游渠道</h1>
      <p className="mb-3 text-sm text-zinc-500">渠道写进 new-api。这里是唯一的入口，管理后台不再打开 new-api 自己的页面。</p>
      {message && <p className="mb-3 text-sm text-red-500">{message}</p>}
      <Panel title="已有渠道">
        {rows.map((row) => (
          <div key={row.id} className="mb-2 flex items-center justify-between text-sm">
            <span>{row.name} · type {row.type} · {row.models || '未填模型'}</span>
            <button className="text-zinc-500" onClick={async () => { await api(`/api/console/admin/channels/${row.id}`, { method: 'DELETE' }); refresh(); }}>删除</button>
          </div>
        ))}
        {!rows.length && <p className="text-sm text-zinc-500">还没有渠道。</p>}
      </Panel>
      <Panel title="添加">
        <Field label="名称"><TextInput value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></Field>
        <Field label="类型">
          <select className="w-full rounded-lg border border-zinc-200 bg-white px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900" value={form.type} onChange={(e) => setForm({ ...form, type: Number(e.target.value) })}>
            {types.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select>
        </Field>
        <Field label="上游密钥"><TextInput type="password" value={form.key} onChange={(e) => setForm({ ...form, key: e.target.value })} /></Field>
        <Field label="Base URL"><TextInput value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} /></Field>
        <Field label="模型，逗号分隔"><TextInput value={form.models} onChange={(e) => setForm({ ...form, models: e.target.value })} /></Field>
        <PrimaryButton onClick={async () => {
          try {
            await api('/api/console/admin/channels', { method: 'POST', body: JSON.stringify(form) });
            setForm({ ...form, key: '' });
            setMessage('已添加');
            refresh();
          } catch (err) {
            setMessage(err instanceof Error ? err.message : '添加失败');
          }
        }}>保存到 new-api</PrimaryButton>
      </Panel>
    </div>
  );
}

function Platform() {
  const [settings, setSettings] = React.useState<Settings | null>(null);
  const [message, setMessage] = React.useState('');
  React.useEffect(() => { api<Settings>('/api/console/admin/settings').then(setSettings); }, []);
  if (!settings) return <p className="text-sm text-zinc-500">加载中…</p>;
  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">计费与队列</h1>
      <Panel title="沙箱与排队">
        <Field label="沙箱单价（USD / 分钟）"><TextInput value={settings.sandbox_usd_per_minute} onChange={(e) => setSettings({ ...settings, sandbox_usd_per_minute: Number(e.target.value) })} /></Field>
        <Field label="新用户免费分钟（一次性，不按月重置）"><TextInput value={settings.free_sandbox_minutes} onChange={(e) => setSettings({ ...settings, free_sandbox_minutes: Number(e.target.value) })} /></Field>
        <Field label="全局排队上限"><TextInput value={settings.max_queued_tasks} onChange={(e) => setSettings({ ...settings, max_queued_tasks: Number(e.target.value) })} /></Field>
        <Field label="每用户排队上限"><TextInput value={settings.max_queued_per_user} onChange={(e) => setSettings({ ...settings, max_queued_per_user: Number(e.target.value) })} /></Field>
        <p className="mb-3 text-xs text-zinc-500">同时运行的沙箱仍是 {settings.sandbox_max_concurrent}，每用户同时 {settings.per_user_concurrency}。模型真实单价仍在 new-api 渠道里。</p>
        <PrimaryButton onClick={async () => {
          await api('/api/console/admin/settings', { method: 'POST', body: JSON.stringify(settings) });
          setMessage('已保存');
        }}>保存</PrimaryButton>
        {message && <p className="mt-2 text-sm">{message}</p>}
      </Panel>
      <Panel title="开放模型">
        {Object.entries(settings.models).map(([agent, models]) => (
          <Field key={agent} label={agent}>
            <TextInput value={models.join(',')} onChange={(e) => setSettings({ ...settings, models: { ...settings.models, [agent]: e.target.value.split(',').map((item) => item.trim()).filter(Boolean) } })} />
          </Field>
        ))}
      </Panel>
    </div>
  );
}

function Tasks() {
  const [rows, setRows] = React.useState<{ id: string; title: string; status: string; email: string; billing_mode: string; cost_usd: number }[]>([]);
  React.useEffect(() => { api<{ tasks: typeof rows }>('/api/console/admin/tasks').then((data) => setRows(data.tasks)); }, []);
  return (
    <div>
      <h1 className="mb-4 text-xl font-semibold">全部任务</h1>
      <Panel title="队列与历史">
        {rows.map((row) => <p key={row.id} className="text-sm">{row.email} · {row.title} · {row.status} · {row.billing_mode} · ${row.cost_usd}</p>)}
      </Panel>
    </div>
  );
}
