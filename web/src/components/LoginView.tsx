import React, { useState } from 'react';

interface LoginViewProps {
  allowRegistration: boolean;
  error?: string | null;
  onLogin: (email: string, password: string) => Promise<void>;
  onRegister: (email: string, password: string, displayName: string) => Promise<void>;
}

export const LoginView: React.FC<LoginViewProps> = ({
  allowRegistration,
  error,
  onLogin,
  onRegister,
}) => {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [busy, setBusy] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setBusy(true);
    try {
      if (mode === 'login') {
        await onLogin(email.trim(), password);
      } else {
        await onRegister(email.trim(), password, displayName.trim());
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="min-h-screen bg-[#fafaf9] text-zinc-900 dark:bg-[#0a0a0c] dark:text-zinc-100 flex items-center justify-center p-6">
      <form onSubmit={submit} className="w-full max-w-sm rounded-xl border border-zinc-200 bg-white p-6 dark:border-zinc-800 dark:bg-[#111113] space-y-4">
        <div className="flex items-center gap-2">
          <div className="flex h-6 w-6 items-center justify-center rounded-md bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-950">
            <svg viewBox="0 0 24 24" className="h-3.5 w-3.5 fill-none stroke-current stroke-[2.2]" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="9" />
              <line x1="5.6" y1="5.6" x2="18.4" y2="18.4" />
            </svg>
          </div>
          <h1 className="text-sm font-semibold tracking-tight">Delegate</h1>
        </div>
        <p className="text-xs text-zinc-500">
          {mode === 'login' ? '登录后查看沙箱任务与审计记录。' : '注册后即可提交隔离沙箱任务。'}
        </p>
        {error && (
          <div className="rounded-lg border border-zinc-300 dark:border-zinc-700 px-3 py-2 text-xs text-zinc-700 dark:text-zinc-200">
            {error}
          </div>
        )}
        {mode === 'register' && (
          <input
            value={displayName}
            onChange={(event) => setDisplayName(event.target.value)}
            placeholder="显示名称"
            className="w-full px-3 py-2 text-sm rounded-lg border border-zinc-200 dark:border-zinc-800 bg-transparent focus:outline-none"
          />
        )}
        <input
          type="email"
          required
          autoFocus
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          placeholder="邮箱"
          className="w-full px-3 py-2 text-sm rounded-lg border border-zinc-200 dark:border-zinc-800 bg-transparent focus:outline-none"
        />
        <input
          type="password"
          required
          minLength={mode === 'register' ? 8 : 1}
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          placeholder="密码"
          className="w-full px-3 py-2 text-sm rounded-lg border border-zinc-200 dark:border-zinc-800 bg-transparent focus:outline-none"
        />
        <button
          type="submit"
          disabled={busy}
          className="w-full px-3 py-2 rounded-lg text-xs font-medium bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-950 disabled:opacity-40 cursor-pointer"
        >
          {busy ? '请稍候…' : mode === 'login' ? '登录' : '注册'}
        </button>
        {allowRegistration && (
          <button
            type="button"
            onClick={() => setMode(mode === 'login' ? 'register' : 'login')}
            className="w-full text-xs text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 cursor-pointer"
          >
            {mode === 'login' ? '没有账户？注册' : '已有账户？登录'}
          </button>
        )}
      </form>
    </div>
  );
};
