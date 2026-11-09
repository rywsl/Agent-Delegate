import React from 'react';
import { Terminal, Moon, Sun, Plus, Sparkles } from 'lucide-react';

interface HeaderProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  isDark: boolean;
  toggleTheme: () => void;
  onOpenNewTask: () => void;
  activeTaskCount: number;
}

export const Header: React.FC<HeaderProps> = ({
  activeTab,
  setActiveTab,
  isDark,
  toggleTheme,
  onOpenNewTask,
  activeTaskCount,
}) => {
  return (
    <header className="sticky top-0 z-40 w-full glass-panel border-b transition-all duration-200">
      <div className="mx-auto flex h-14 max-w-7xl items-center justify-between gap-8 px-4 sm:px-6">
        {/* Zone 1: Single text element wordmark */}
        <div className="flex items-center gap-3 shrink-0">
          <button
            onClick={() => setActiveTab('tasks')}
            className="flex items-center gap-2.5 text-left group cursor-pointer"
            aria-label="返回任务控制台"
          >
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-b from-zinc-800 to-zinc-950 text-white dark:from-white dark:to-zinc-200 dark:text-zinc-950 font-bold shadow-[0_2px_8px_rgba(0,0,0,0.15)] dark:shadow-[0_2px_12px_rgba(255,255,255,0.15)] transition-transform group-hover:scale-105 active:scale-95">
              <Terminal className="h-4 w-4" />
            </div>
            <div className="flex flex-col">
              <span className="text-sm font-bold tracking-tight text-zinc-900 dark:text-white whitespace-nowrap font-display">
                DELEGATE <span className="text-zinc-400 dark:text-zinc-500 font-normal">OS</span>
              </span>
              <span className="text-[11px] text-zinc-500 dark:text-zinc-400 font-mono">
                v0.2.0 · Docker Sandbox
              </span>
            </div>
          </button>
        </div>

        {/* Zone 2: Concise single-line navigation links with Liquid Segmented Feel */}
        <nav className="hidden md:flex items-center gap-1 p-1 rounded-lg bg-zinc-200/50 dark:bg-white/5 backdrop-blur-md border border-white/20 dark:border-white/5 text-xs font-medium">
          <button
            onClick={() => setActiveTab('tasks')}
            className={`px-3 py-1.5 rounded-md transition-all whitespace-nowrap shrink-0 cursor-pointer ${
              activeTab === 'tasks' || activeTab === 'task-detail'
                ? 'bg-white text-zinc-950 font-semibold shadow-sm dark:bg-zinc-800 dark:text-white'
                : 'text-zinc-600 hover:text-zinc-950 dark:text-zinc-400 dark:hover:text-zinc-100'
            }`}
          >
            任务中心
            {activeTaskCount > 0 && (
              <span className="ml-1.5 font-mono text-[10px] text-cyan-600 dark:text-cyan-400 font-bold">
                ({activeTaskCount})
              </span>
            )}
          </button>

          <button
            onClick={() => setActiveTab('keys')}
            className={`px-3 py-1.5 rounded-md transition-all whitespace-nowrap shrink-0 cursor-pointer ${
              activeTab === 'keys'
                ? 'bg-white text-zinc-950 font-semibold shadow-sm dark:bg-zinc-800 dark:text-white'
                : 'text-zinc-600 hover:text-zinc-950 dark:text-zinc-400 dark:hover:text-zinc-100'
            }`}
          >
            API 密钥
          </button>

          <button
            onClick={() => setActiveTab('providers')}
            className={`px-3 py-1.5 rounded-md transition-all whitespace-nowrap shrink-0 cursor-pointer ${
              activeTab === 'providers'
                ? 'bg-white text-zinc-950 font-semibold shadow-sm dark:bg-zinc-800 dark:text-white'
                : 'text-zinc-600 hover:text-zinc-950 dark:text-zinc-400 dark:hover:text-zinc-100'
            }`}
          >
            模型提供商
          </button>

          <button
            onClick={() => setActiveTab('mcp')}
            className={`px-3 py-1.5 rounded-md transition-all whitespace-nowrap shrink-0 cursor-pointer ${
              activeTab === 'mcp'
                ? 'bg-white text-zinc-950 font-semibold shadow-sm dark:bg-zinc-800 dark:text-white'
                : 'text-zinc-600 hover:text-zinc-950 dark:text-zinc-400 dark:hover:text-zinc-100'
            }`}
          >
            MCP 本地接入
          </button>

          <button
            onClick={() => setActiveTab('audit')}
            className={`px-3 py-1.5 rounded-md transition-all whitespace-nowrap shrink-0 cursor-pointer ${
              activeTab === 'audit'
                ? 'bg-white text-zinc-950 font-semibold shadow-sm dark:bg-zinc-800 dark:text-white'
                : 'text-zinc-600 hover:text-zinc-950 dark:text-zinc-400 dark:hover:text-zinc-100'
            }`}
          >
            安全审计
          </button>
        </nav>

        {/* Zone 3: Primary action + Theme toggle with Liquid Buttons */}
        <div className="flex items-center gap-2.5 shrink-0">
          <button
            onClick={toggleTheme}
            className="flex h-8 w-8 items-center justify-center rounded-md glass-button-secondary cursor-pointer"
            title={isDark ? '切换至亮色模式 (Liquid Glass Paper)' : '切换至暗色模式 (Liquid Obsidian)'}
            aria-label="切换主题"
          >
            {isDark ? <Sun className="h-4 w-4 text-amber-400" /> : <Moon className="h-4 w-4 text-zinc-700" />}
          </button>

          <button
            onClick={onOpenNewTask}
            className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-md glass-button-primary whitespace-nowrap cursor-pointer"
          >
            <Plus className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">外派新任务</span>
            <span className="sm:hidden">新任务</span>
          </button>
        </div>
      </div>

      {/* Mobile Sub-Navigation Bar */}
      <div className="flex md:hidden items-center gap-1 overflow-x-auto border-t border-zinc-200/40 dark:border-white/5 px-4 py-1.5 text-xs font-medium bg-white/40 dark:bg-black/20 backdrop-blur-md">
        <button
          onClick={() => setActiveTab('tasks')}
          className={`px-2.5 py-1 rounded text-xs whitespace-nowrap transition-colors ${
            activeTab === 'tasks' || activeTab === 'task-detail'
              ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-950 font-semibold shadow-xs'
              : 'text-zinc-600 dark:text-zinc-400'
          }`}
        >
          任务中心 {activeTaskCount > 0 && `(${activeTaskCount})`}
        </button>
        <button
          onClick={() => setActiveTab('keys')}
          className={`px-2.5 py-1 rounded text-xs whitespace-nowrap transition-colors ${
            activeTab === 'keys'
              ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-950 font-semibold shadow-xs'
              : 'text-zinc-600 dark:text-zinc-400'
          }`}
        >
          API 密钥
        </button>
        <button
          onClick={() => setActiveTab('providers')}
          className={`px-2.5 py-1 rounded text-xs whitespace-nowrap transition-colors ${
            activeTab === 'providers'
              ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-950 font-semibold shadow-xs'
              : 'text-zinc-600 dark:text-zinc-400'
          }`}
        >
          模型提供商
        </button>
        <button
          onClick={() => setActiveTab('mcp')}
          className={`px-2.5 py-1 rounded text-xs whitespace-nowrap transition-colors ${
            activeTab === 'mcp'
              ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-950 font-semibold shadow-xs'
              : 'text-zinc-600 dark:text-zinc-400'
          }`}
        >
          MCP 接入
        </button>
        <button
          onClick={() => setActiveTab('audit')}
          className={`px-2.5 py-1 rounded text-xs whitespace-nowrap transition-colors ${
            activeTab === 'audit'
              ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-950 font-semibold shadow-xs'
              : 'text-zinc-600 dark:text-zinc-400'
          }`}
        >
          安全审计
        </button>
      </div>
    </header>
  );
};
