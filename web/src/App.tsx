import React from 'react';
import { Sidebar, type Tab } from './components/Sidebar';
import { Field, PrimaryButton, TextInput } from './components/ui';
import { api, loadSession, type Session } from './lib/api';
import { AdminViews } from './components/AdminViews';
import { UserViews } from './components/UserViews';

function Login({ session, onDone }: { session: Session; onDone: (session: Session) => void }) {
  const [mode, setMode] = React.useState<'login' | 'register'>('login');
  const [email, setEmail] = React.useState('');
  const [password, setPassword] = React.useState('');
  const [name, setName] = React.useState('');
  const [error, setError] = React.useState('');
  const [busy, setBusy] = React.useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError('');
    try {
      const path = mode === 'login' ? '/api/console/login' : '/api/console/register';
      const next = await api<Session>(path, { method: 'POST', body: JSON.stringify({ email, password, display_name: name }) });
      onDone(next);
    } catch (err) {
      setError(err instanceof Error ? err.message : '登录失败');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#f6f6f4] px-4 dark:bg-[#0a0a0a]">
      <form onSubmit={submit} className="glass-panel w-full max-w-sm rounded-2xl p-6">
        <h1 className="mb-1 text-lg font-semibold">Delegate</h1>
        <p className="mb-5 text-sm text-zinc-500">{mode === 'login' ? '登录控制台' : '创建账号'}</p>
        {mode === 'register' && <Field label="昵称"><TextInput value={name} onChange={(e) => setName(e.target.value)} /></Field>}
        <Field label="邮箱"><TextInput type="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></Field>
        <Field label="密码"><TextInput type="password" required minLength={8} value={password} onChange={(e) => setPassword(e.target.value)} /></Field>
        {error && <p className="mb-3 text-sm text-red-500">{error}</p>}
        <PrimaryButton disabled={busy} type="submit">{busy ? '请稍候' : mode === 'login' ? '登录' : '注册'}</PrimaryButton>
        {session.allow_registration && (
          <button type="button" className="mt-4 block text-sm text-zinc-500" onClick={() => setMode(mode === 'login' ? 'register' : 'login')}>
            {mode === 'login' ? '没有账号？注册' : '已有账号？登录'}
          </button>
        )}
      </form>
    </div>
  );
}

export default function App() {
  const [session, setSession] = React.useState<Session | null>(null);
  const [tab, setTab] = React.useState<Tab>('home');
  const [dark, setDark] = React.useState(true);
  const [error, setError] = React.useState('');
  const [navOpen, setNavOpen] = React.useState(false);

  React.useEffect(() => {
    document.documentElement.classList.toggle('dark', dark);
  }, [dark]);

  React.useEffect(() => {
    loadSession().then(setSession).catch((err) => setError(err.message));
  }, []);

  if (error) return <p className="p-8 text-red-500">{error}</p>;
  if (!session) return <p className="p-8 text-zinc-500">加载中…</p>;
  if (!session.user) return <Login session={session} onDone={setSession} />;

  return (
    <div className="flex min-h-screen bg-[#f7f7f5] text-zinc-900 dark:bg-[#0a0a0a] dark:text-zinc-100">
      <Sidebar
        tab={tab}
        setTab={setTab}
        admin={session.user.is_admin}
        email={session.user.email}
        dark={dark}
        toggleDark={() => setDark((value) => !value)}
        onLogout={async () => {
          await api('/api/console/logout', { method: 'POST' });
          setSession(await loadSession());
          setTab('home');
        }}
        open={navOpen}
        setOpen={setNavOpen}
      />
      <main className="page-enter min-w-0 flex-1 overflow-auto p-4 pt-14 md:p-10">
        {tab.startsWith('admin-')
          ? <AdminViews tab={tab} />
          : <UserViews tab={tab} session={session} reload={async () => setSession(await loadSession())} />}
      </main>
    </div>
  );
}
