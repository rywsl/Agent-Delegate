import React from 'react';
import {
  CheckSquare, Coins, KeyRound, LayoutDashboard, LogOut, Menu, Moon, PanelLeftClose, PanelLeftOpen,
  PlusCircle, ScrollText, Server, Settings, Shield, Sun, Users,
} from 'lucide-react';
import { cn } from '../lib/utils';

export type Tab =
  | 'home' | 'tasks' | 'new' | 'keys' | 'billing' | 'audit' | 'settings'
  | 'admin-home' | 'admin-users' | 'admin-codes' | 'admin-channels' | 'admin-settings' | 'admin-tasks';

const USER_GROUPS = [
  { label: '工作台', items: [
    { id: 'home' as Tab, label: '主页', icon: LayoutDashboard },
    { id: 'tasks' as Tab, label: '任务', icon: CheckSquare },
    { id: 'new' as Tab, label: '新建', icon: PlusCircle },
  ]},
  { label: '账户', items: [
    { id: 'keys' as Tab, label: '密钥', icon: KeyRound },
    { id: 'billing' as Tab, label: '账单', icon: Coins },
    { id: 'audit' as Tab, label: '审计', icon: ScrollText },
    { id: 'settings' as Tab, label: '设置', icon: Settings },
  ]},
];

const ADMIN_GROUPS = [
  { label: '管理', items: [
    { id: 'admin-home' as Tab, label: '概览', icon: Shield },
    { id: 'admin-users' as Tab, label: '用户', icon: Users },
    { id: 'admin-tasks' as Tab, label: '全部任务', icon: CheckSquare },
    { id: 'admin-codes' as Tab, label: '充值码', icon: Coins },
    { id: 'admin-channels' as Tab, label: '上游渠道', icon: Server },
    { id: 'admin-settings' as Tab, label: '计费与队列', icon: Settings },
  ]},
];

export function Sidebar({
  tab, setTab, admin, email, dark, toggleDark, onLogout, open, setOpen,
}: {
  tab: Tab;
  setTab: (tab: Tab) => void;
  admin: boolean;
  email: string;
  dark: boolean;
  toggleDark: () => void;
  onLogout: () => void;
  open: boolean;
  setOpen: (open: boolean) => void;
}) {
  const [collapsed, setCollapsed] = React.useState(false);
  const [mode, setMode] = React.useState<'user' | 'admin'>('user');
  const groups = mode === 'admin' && admin ? ADMIN_GROUPS : USER_GROUPS;
  function choose(next: Tab) {
    setTab(next);
    setOpen(false);
  }
  return (
    <>
    <button
      className="fixed left-3 top-3 z-20 rounded-md border border-zinc-200 bg-[#f6f6f4] p-2 text-zinc-600 md:hidden dark:border-zinc-800 dark:bg-[#0c0c0e] dark:text-zinc-300"
      onClick={() => setOpen(true)}
      title="菜单"
    >
      <Menu className="h-4 w-4" />
    </button>
    {open && <button className="fixed inset-0 z-30 bg-black/40 md:hidden" aria-label="关闭菜单" onClick={() => setOpen(false)} />}
    <aside className={cn(
      'fixed inset-y-0 left-0 z-40 flex h-screen shrink-0 flex-col border-r border-zinc-200/90 bg-[#f6f6f4] transition-transform dark:border-zinc-800/80 dark:bg-[#0c0c0e] md:static md:z-auto md:translate-x-0',
      collapsed ? 'w-60 md:w-[60px]' : 'w-60',
      open ? 'translate-x-0' : '-translate-x-full',
    )}>
      <div className={cn('flex h-14 items-center', collapsed ? 'justify-center' : 'justify-between px-3.5')}>
        {!collapsed && <span className="text-sm font-semibold tracking-tight">Delegate</span>}
        <button className="hidden rounded-md p-1.5 text-zinc-400 hover:bg-zinc-200/70 md:inline-flex dark:hover:bg-zinc-800" onClick={() => setCollapsed((v) => !v)} title="收起">
          {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
        </button>
      </div>
      {admin && !collapsed && (
        <div className="mx-3 mb-2 grid grid-cols-2 rounded-lg bg-zinc-200/70 p-0.5 text-xs dark:bg-zinc-900">
          <button className={cn('rounded-md py-1', mode === 'user' && 'bg-white dark:bg-zinc-800')} onClick={() => { setMode('user'); choose('home'); }}>用户</button>
          <button className={cn('rounded-md py-1', mode === 'admin' && 'bg-white dark:bg-zinc-800')} onClick={() => { setMode('admin'); choose('admin-home'); }}>管理</button>
        </div>
      )}
      <nav className="flex-1 overflow-y-auto px-2.5 pb-3">
        {groups.map((group) => (
          <div key={group.label} className="mb-3">
            {!collapsed && <div className="px-2.5 pb-1.5 pt-1 text-[10px] font-medium tracking-wide text-zinc-400">{group.label}</div>}
            {group.items.map((item) => {
              const Icon = item.icon;
              const active = tab === item.id;
              return (
                <button key={item.id} title={item.label} onClick={() => choose(item.id)}
                  className={cn('mb-0.5 flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-sm',
                    active ? 'bg-white text-zinc-900 shadow-sm dark:bg-zinc-800 dark:text-zinc-100' : 'text-zinc-500 hover:bg-zinc-200/60 dark:hover:bg-zinc-900')}>
                  <Icon className="h-4 w-4 shrink-0" />
                  {!collapsed && item.label}
                </button>
              );
            })}
          </div>
        ))}
      </nav>
      <div className="border-t border-zinc-200 p-2 dark:border-zinc-800">
        {!collapsed && <div className="truncate px-2 pb-1 text-xs text-zinc-400">{email}</div>}
        <div className="flex gap-1">
          <button className="rounded-md p-2 text-zinc-400 hover:bg-zinc-200/70 dark:hover:bg-zinc-800" onClick={toggleDark} title="主题">
            {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </button>
          <button className="rounded-md p-2 text-zinc-400 hover:bg-zinc-200/70 dark:hover:bg-zinc-800" onClick={onLogout} title="退出">
            <LogOut className="h-4 w-4" />
          </button>
        </div>
      </div>
    </aside>
    </>
  );
}
