import React from 'react';
import {
  PanelLeftClose,
  PanelLeftOpen,
  LayoutDashboard,
  CheckSquare,
  PlusCircle,
  KeyRound,
  Server,
  Network,
  ShieldAlert,
  Sun,
  Moon,
  LogOut,
} from 'lucide-react';
import { cn } from '../lib/utils';

export type SidebarTab = 'home' | 'tasks' | 'new-task' | 'keys' | 'providers' | 'mcp' | 'audit' | 'task-detail';

interface SidebarProps {
  activeTab: string;
  setActiveTab: (tab: SidebarTab) => void;
  taskCount?: number;
  userEmail?: string;
  userName?: string;
  initials?: string;
  isDark?: boolean;
  toggleTheme?: () => void;
  onLogout?: () => void;
}

const GROUPS: { label: string; items: { id: SidebarTab; label: string; icon: React.ComponentType<{ className?: string }>; badge?: boolean }[] }[] = [
  {
    label: '工作台',
    items: [
      { id: 'home', label: '主页', icon: LayoutDashboard },
      { id: 'tasks', label: '任务', icon: CheckSquare, badge: true },
      { id: 'new-task', label: '新建', icon: PlusCircle },
    ],
  },
  {
    label: '接入',
    items: [
      { id: 'keys', label: '密钥', icon: KeyRound },
      { id: 'providers', label: '提供商', icon: Server },
      { id: 'mcp', label: 'MCP 接入', icon: Network },
      { id: 'audit', label: '审计', icon: ShieldAlert },
    ],
  },
];

export const Sidebar: React.FC<SidebarProps> = ({
  activeTab,
  setActiveTab,
  taskCount = 0,
  userEmail = '',
  userName = '',
  initials = 'U',
  isDark = true,
  toggleTheme,
  onLogout,
}) => {
  const [collapsed, setCollapsed] = React.useState(() => localStorage.getItem('delegate-sidebar') === '1');

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      localStorage.setItem('delegate-sidebar', prev ? '0' : '1');
      return !prev;
    });
  };

  return (
    <aside
      className={cn(
        'h-screen sticky top-0 flex flex-col border-r border-zinc-200/90 bg-[#f6f6f4] dark:border-zinc-800/80 dark:bg-[#0c0c0e] transition-[width] duration-200 ease-out select-none z-30 shrink-0',
        collapsed ? 'w-[60px]' : 'w-60'
      )}
    >
      <div className={cn('flex h-14 items-center', collapsed ? 'justify-center px-2' : 'justify-between px-3.5')}>
        <button
          onClick={() => setActiveTab('home')}
          className="flex items-center gap-2.5 text-left cursor-pointer rounded-lg focus-visible:outline focus-visible:outline-zinc-400"
          title="回到主页"
        >
          <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-zinc-900 text-white shadow-sm dark:bg-zinc-100 dark:text-zinc-950">
            <svg viewBox="0 0 24 24" className="h-3.5 w-3.5 fill-none stroke-current stroke-[2.2]" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="12" cy="12" r="9" />
              <line x1="5.6" y1="5.6" x2="18.4" y2="18.4" />
            </svg>
          </div>
          {!collapsed && (
            <span className="font-semibold tracking-tight text-zinc-900 dark:text-zinc-100 text-sm">Delegate</span>
          )}
        </button>
        {!collapsed && (
          <button
            onClick={toggleCollapsed}
            className="p-1.5 text-zinc-400 hover:text-zinc-800 hover:bg-zinc-200/70 dark:hover:text-zinc-200 dark:hover:bg-zinc-800 rounded-md transition-colors cursor-pointer active:scale-95"
            title="收起侧边栏"
          >
            <PanelLeftClose className="h-4 w-4" />
          </button>
        )}
      </div>

      <nav className="flex-1 px-2.5 pb-3 overflow-y-auto">
        {GROUPS.map((group) => (
          <div key={group.label} className="mb-3">
            {!collapsed && (
              <div className="px-2.5 pb-1.5 pt-1 text-[10px] font-medium tracking-wide text-zinc-400 dark:text-zinc-500">
                {group.label}
              </div>
            )}
            <div className="space-y-0.5">
              {group.items.map((item) => {
                const Icon = item.icon;
                const isActive = activeTab === item.id || (item.id === 'tasks' && activeTab === 'task-detail');
                return (
                  <button
                    key={item.id}
                    onClick={() => setActiveTab(item.id)}
                    title={collapsed ? item.label : undefined}
                    className={cn(
                      'group relative w-full flex items-center rounded-lg text-[13px] transition-all duration-150 text-left cursor-pointer active:scale-[0.98]',
                      collapsed ? 'justify-center h-9' : 'gap-2.5 px-2.5 py-2',
                      isActive
                        ? 'bg-white text-zinc-950 font-medium shadow-sm ring-1 ring-zinc-200/80 dark:bg-zinc-800/90 dark:text-zinc-50 dark:ring-zinc-700/80'
                        : 'text-zinc-600 hover:text-zinc-950 hover:bg-zinc-200/55 dark:text-zinc-400 dark:hover:text-zinc-100 dark:hover:bg-zinc-800/50'
                    )}
                  >
                    {isActive && (
                      <span className="accent-mark absolute left-0 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full" />
                    )}
                    <Icon className={cn('h-4 w-4 shrink-0', isActive ? 'text-zinc-950 dark:text-zinc-100' : 'text-zinc-500 group-hover:text-zinc-800 dark:text-zinc-400 dark:group-hover:text-zinc-200')} />
                    {!collapsed && (
                      <span className="flex-1 flex items-center justify-between min-w-0">
                        <span className="truncate">{item.label}</span>
                        {item.badge && (
                          <span className={cn('min-w-5 rounded-full px-1.5 text-center font-mono text-[10px]', isActive ? 'bg-[var(--blue-mid)] text-white' : 'text-zinc-400 dark:text-zinc-500')}>
                            {taskCount}
                          </span>
                        )}
                      </span>
                    )}
                    {collapsed && item.badge && taskCount > 0 && (
                      <span className="accent-dot absolute right-1.5 top-1.5 h-1.5 w-1.5 rounded-full" />
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        ))}
        {collapsed && (
          <button
            onClick={toggleCollapsed}
            className="mx-auto mt-1 flex h-9 w-9 items-center justify-center rounded-lg text-zinc-400 hover:bg-zinc-200/70 hover:text-zinc-800 dark:hover:bg-zinc-800 dark:hover:text-zinc-200 cursor-pointer"
            title="展开侧边栏"
          >
            <PanelLeftOpen className="h-4 w-4" />
          </button>
        )}
      </nav>

      <div className="p-2.5 border-t border-zinc-200/80 dark:border-zinc-800/80">
        <div className={cn('flex items-center rounded-xl', collapsed ? 'justify-center py-1' : 'gap-2 px-2 py-1.5')}>
          <div className="h-8 w-8 rounded-full bg-zinc-200 dark:bg-zinc-800 flex items-center justify-center font-medium text-[11px] text-zinc-700 dark:text-zinc-300 font-mono shrink-0" title={userName}>
            {initials}
          </div>
          {!collapsed && (
            <>
              <div className="min-w-0 flex-1">
                <div className="text-xs font-medium text-zinc-900 dark:text-zinc-100 truncate">{userName}</div>
                <div className="text-[11px] text-zinc-400 dark:text-zinc-500 truncate">{userEmail}</div>
              </div>
              {toggleTheme && (
                <button
                  onClick={toggleTheme}
                  className="p-1.5 rounded-md text-zinc-400 hover:text-zinc-900 hover:bg-zinc-200/70 dark:hover:text-zinc-100 dark:hover:bg-zinc-800 transition-colors cursor-pointer active:scale-95"
                  title={isDark ? '浅色模式' : '深色模式'}
                >
                  {isDark ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
                </button>
              )}
              {onLogout && (
                <button
                  onClick={onLogout}
                  className="p-1.5 rounded-md text-zinc-400 hover:text-zinc-900 hover:bg-zinc-200/70 dark:hover:text-zinc-100 dark:hover:bg-zinc-800 transition-colors cursor-pointer active:scale-95"
                  title="退出"
                >
                  <LogOut className="h-3.5 w-3.5" />
                </button>
              )}
            </>
          )}
        </div>
      </div>
    </aside>
  );
};
