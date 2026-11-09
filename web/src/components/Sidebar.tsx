import React from 'react';
import {
  CheckSquare, Coins, KeyRound, LayoutDashboard, LogOut, Moon, Network, PanelLeftClose, PanelLeftOpen,
  PlusCircle, ScrollText, Server, Settings, Shield, ShieldAlert, Sun, Users,
} from 'lucide-react';
import { cn } from '../lib/utils';

export type Tab =
  | 'home' | 'tasks' | 'new-task' | 'keys' | 'providers' | 'mcp' | 'audit' | 'billing' | 'task-detail'
  | 'admin-home' | 'admin-users' | 'admin-tasks' | 'admin-codes' | 'admin-channels' | 'admin-settings';

export type SidebarTab = Tab;

const GROUPS: { label: string; admin?: boolean; items: { id: SidebarTab; label: string; icon: React.ComponentType<{ className?: string }>; badge?: boolean }[] }[] = [
  { label: '工作台', items: [
    { id: 'home', label: '主页', icon: LayoutDashboard },
    { id: 'tasks', label: '任务', icon: CheckSquare, badge: true },
    { id: 'new-task', label: '新建', icon: PlusCircle },
  ]},
  { label: '接入', items: [
    { id: 'keys', label: '密钥', icon: KeyRound },
    { id: 'providers', label: '提供商', icon: Server },
    { id: 'mcp', label: 'MCP 接入', icon: Network },
    { id: 'billing', label: '账单', icon: Coins },
    { id: 'audit', label: '审计', icon: ShieldAlert },
  ]},
  { label: '管理', admin: true, items: [
    { id: 'admin-home', label: '概览', icon: Shield },
    { id: 'admin-users', label: '用户', icon: Users },
    { id: 'admin-tasks', label: '全部任务', icon: CheckSquare },
    { id: 'admin-codes', label: '充值码', icon: Coins },
    { id: 'admin-channels', label: '上游渠道', icon: Server },
    { id: 'admin-settings', label: '计费与队列', icon: Settings },
  ]},
];

export function Sidebar({
  activeTab, setActiveTab, taskCount = 0, userName = '', userEmail = '', initials = 'U',
  isDark = true, toggleTheme, onLogout, admin = false,
}: {
  activeTab: string;
  setActiveTab: (tab: SidebarTab) => void;
  taskCount?: number;
  userName?: string;
  userEmail?: string;
  initials?: string;
  isDark?: boolean;
  toggleTheme?: () => void;
  onLogout?: () => void;
  admin?: boolean;
}) {
  const [collapsed, setCollapsed] = React.useState(false);
  const groups = GROUPS.filter((group) => !group.admin || admin);

  return (
    <aside className={cn(
      'sticky top-0 z-30 flex h-screen shrink-0 select-none flex-col border-r border-zinc-200 bg-[#f7f7f5] transition-all duration-150 dark:border-zinc-800/80 dark:bg-[#0c0c0e]',
      collapsed ? 'w-14' : 'w-56',
    )}>
      <div className="flex h-14 items-center justify-between px-3.5">
        <button onClick={() => setActiveTab('home')} className="flex cursor-pointer items-center gap-2 text-left">
          <div className="flex h-6 w-6 items-center justify-center rounded-md bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-950">
            <svg viewBox="0 0 24 24" className="h-3.5 w-3.5 fill-none stroke-current stroke-[2.2]" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="9" />
              <line x1="5.6" y1="5.6" x2="18.4" y2="18.4" />
            </svg>
          </div>
          {!collapsed && <span className="text-sm font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">Delegate</span>}
        </button>
        <button onClick={() => setCollapsed((value) => !value)} className="cursor-pointer rounded p-1 text-zinc-400 hover:text-zinc-800 dark:hover:text-zinc-200" title={collapsed ? '展开侧边栏' : '收起侧边栏'}>
          {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
        </button>
      </div>

      <nav className="flex-1 overflow-y-auto px-2.5 py-2">
        {groups.map((group) => (
          <div key={group.label} className="mb-3">
            {!collapsed && <div className="px-2.5 pb-1.5 pt-1 text-[10px] font-medium tracking-wide text-zinc-400">{group.label}</div>}
            <div className="space-y-0.5">
              {group.items.map((item) => {
                const Icon = item.icon;
                const isActive = activeTab === item.id || (item.id === 'tasks' && activeTab === 'task-detail');
                return (
                  <button key={item.id} onClick={() => setActiveTab(item.id)} title={collapsed ? item.label : undefined}
                    className={cn(
                      'flex w-full cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-2 text-left text-[13px] transition-colors',
                      collapsed && 'justify-center px-0',
                      isActive
                        ? 'bg-zinc-200/80 font-medium text-zinc-950 dark:bg-zinc-800/90 dark:text-zinc-100'
                        : 'text-zinc-600 hover:bg-zinc-200/40 hover:text-zinc-950 dark:text-zinc-400 dark:hover:bg-zinc-800/40 dark:hover:text-zinc-200',
                    )}>
                    <Icon className="h-4 w-4 shrink-0" />
                    {!collapsed && (
                      <span className="flex min-w-0 flex-1 items-center justify-between">
                        <span className="truncate">{item.label}</span>
                        {item.badge && <span className="font-mono text-[11px] text-zinc-400 dark:text-zinc-500">{taskCount}</span>}
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
      </nav>

      <div className="border-t border-zinc-200/80 p-2.5 dark:border-zinc-800/80">
        <div className={cn('flex items-center rounded-lg px-2 py-1.5', collapsed ? 'justify-center' : 'justify-between')}>
          <div className="flex min-w-0 items-center gap-2.5">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-zinc-200 font-mono text-[11px] font-medium text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">{initials}</div>
            {!collapsed && (
              <div className="min-w-0">
                <div className="truncate text-xs font-medium text-zinc-900 dark:text-zinc-100">{userName}</div>
                <div className="truncate text-[11px] text-zinc-400">{userEmail}</div>
              </div>
            )}
          </div>
          {!collapsed && (
            <div className="flex">
              {toggleTheme && (
                <button onClick={toggleTheme} className="cursor-pointer rounded-md p-1.5 text-zinc-400 hover:bg-zinc-200/60 hover:text-zinc-900 dark:hover:bg-zinc-800 dark:hover:text-zinc-100" title={isDark ? '浅色模式' : '深色模式'}>
                  {isDark ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
                </button>
              )}
              {onLogout && (
                <button onClick={onLogout} className="cursor-pointer rounded-md p-1.5 text-zinc-400 hover:bg-zinc-200/60 hover:text-zinc-900 dark:hover:bg-zinc-800 dark:hover:text-zinc-100" title="退出">
                  <LogOut className="h-3.5 w-3.5" />
                </button>
              )}
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}
