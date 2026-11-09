import React, { useState } from 'react';
import {
  ArrowUpRight,
  MoreHorizontal,
  Terminal,
  Cpu,
  Layers,
  Network,
} from 'lucide-react';
import { Task } from '../types/delegate';

interface OverviewDashboardProps {
  tasks: Task[];
  onSelectTask: (task: Task) => void;
  onOpenNewTask: (config?: { model?: string; harness?: string }) => void;
  onNavigateTab?: (tab: string) => void;
  userName?: string;
  sandbox?: { memory: string; cpus: string | number; capacity: number; active: number; uid: number };
  usage?: { tokens: number; cache_rate: number };
  heatmap?: { cells: number[]; months: string[]; patch_lines: number; active_month: string; peak_date: string };
  billingLine?: string;
  queueLine?: string;
}

export const OverviewDashboard: React.FC<OverviewDashboardProps> = ({
  tasks,
  onOpenNewTask,
  onNavigateTab,
  userName = '',
  sandbox,
  usage,
  heatmap,
  billingLine,
  queueLine,
}) => {
  const [heatmapFilter, setHeatmapFilter] = useState<'all' | 'tab' | 'agent'>('all');
  const cells = heatmap?.cells?.length ? heatmap.cells : Array.from({ length: 52 * 7 }, () => 0);
  const months = heatmap?.months?.length
    ? heatmap.months
    : ['Nov', 'Dec', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov'];
  const runningCount = sandbox?.active ?? tasks.filter((t) => t.status === 'running' || t.status === 'queued' || t.status === 'preparing').length;
  const capacity = Math.max(1, sandbox?.capacity || 8);
  const quota = Math.min(100, Math.round((runningCount / capacity) * 100));
  const tokenTotal = usage?.tokens ?? 0;
  const cacheRate = usage?.cache_rate ?? 0;
  const patchLines = heatmap?.patch_lines ?? 0;

  return (
    <div className="space-y-6 pb-12 max-w-5xl">
      <div>
        <h1 className="text-2xl font-medium text-zinc-900 dark:text-zinc-100 tracking-tight">
          Welcome, {userName}.
        </h1>
        {billingLine && <p className="mt-1 font-mono text-[11px] text-zinc-400">{billingLine}</p>}
      </div>

      {/* Top 2 Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Card 1: Sandbox Pool */}
        <div className="rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800/80 dark:bg-[#111113] flex flex-col justify-between space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400">沙箱集群</span>
              <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300">
                <span className="h-1.5 w-1.5 rounded-full bg-zinc-900 dark:bg-zinc-100" />
                运行中
              </span>
            </div>

            <button
              onClick={() => onNavigateTab && onNavigateTab('tasks')}
              className="text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 p-1 cursor-pointer"
              title="查看任务"
            >
              <MoreHorizontal className="h-4 w-4" />
            </button>
          </div>

          <div className="space-y-2">
            <div className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100 font-mono tracking-tight">
              {quota}% <span className="text-xs font-normal text-zinc-500">配额 ({runningCount} / {capacity} 容器活跃)</span>
            </div>
            <div className="h-1 w-full rounded-full bg-zinc-100 dark:bg-zinc-800 overflow-hidden">
              <div className="h-full rounded-full bg-zinc-900 dark:bg-zinc-100" style={{ width: `${quota}%` }} />
            </div>
          </div>

          <div className="flex items-center justify-between text-xs text-zinc-400 dark:text-zinc-500 pt-1 font-mono">
            <span>{sandbox?.memory || '—'} · {sandbox?.cpus ?? '—'} CPUs</span>
            <span>{queueLine || `uid=${sandbox?.uid ?? 10001}`}</span>
          </div>
        </div>

        {/* Card 2: Token Usage */}
        <div className="rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800/80 dark:bg-[#111113] flex flex-col justify-between space-y-4">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-zinc-500 dark:text-zinc-400">本月用量</span>
            <div className="flex items-center gap-2">
              <button
                onClick={() => onNavigateTab && onNavigateTab('mcp')}
                className="px-3 py-1 rounded-full text-xs border border-zinc-200 dark:border-zinc-800 hover:bg-zinc-50 dark:hover:bg-zinc-800/60 text-zinc-700 dark:text-zinc-300 transition-colors cursor-pointer"
              >
                MCP 配置
              </button>
              <button
                onClick={() => onNavigateTab && onNavigateTab('audit')}
                className="px-3 py-1 rounded-full text-xs bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-950 hover:bg-zinc-800 dark:hover:bg-zinc-200 transition-colors cursor-pointer font-medium"
              >
                审计日志
              </button>
            </div>
          </div>

          <div>
            <div className="text-2xl font-semibold text-zinc-900 dark:text-zinc-100 font-mono tracking-tight">
              {tokenTotal.toLocaleString()} <span className="text-xs font-normal text-zinc-500">tokens</span>
            </div>
          </div>

          <div className="flex items-center justify-between text-xs text-zinc-400 dark:text-zinc-500 pt-1 font-mono">
            <span>缓存命中率 {cacheRate}%</span>
            <span>共 {tasks.length} 个任务</span>
          </div>
        </div>
      </div>

      {/* 4 Quick Entry Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <div
          onClick={() => onOpenNewTask({ harness: 'claude' })}
          className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800/80 dark:bg-[#111113] hover:border-zinc-300 dark:hover:border-zinc-700 transition-colors cursor-pointer group flex flex-col justify-between h-32"
        >
          <div className="flex items-start justify-between">
            <Cpu className="h-4 w-4 text-zinc-600 dark:text-zinc-300" />
            <ArrowUpRight className="h-3.5 w-3.5 text-zinc-400 group-hover:text-zinc-900 dark:group-hover:text-zinc-100 transition-colors" />
          </div>
          <div>
            <h3 className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
              Claude Code
            </h3>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              在隔离沙箱里运行 Claude Code。
            </p>
          </div>
        </div>

        <div
          onClick={() => onOpenNewTask({ harness: 'codex' })}
          className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800/80 dark:bg-[#111113] hover:border-zinc-300 dark:hover:border-zinc-700 transition-colors cursor-pointer group flex flex-col justify-between h-32"
        >
          <div className="flex items-start justify-between">
            <Terminal className="h-4 w-4 text-zinc-600 dark:text-zinc-300" />
            <ArrowUpRight className="h-3.5 w-3.5 text-zinc-400 group-hover:text-zinc-900 dark:group-hover:text-zinc-100 transition-colors" />
          </div>
          <div>
            <h3 className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
              CLI 容器套件
            </h3>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              独立容器镜像运行命令行工具链。
            </p>
          </div>
        </div>

        <div
          onClick={() => onOpenNewTask({ harness: 'gemini' })}
          className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800/80 dark:bg-[#111113] hover:border-zinc-300 dark:hover:border-zinc-700 transition-colors cursor-pointer group flex flex-col justify-between h-32"
        >
          <div className="flex items-start justify-between">
            <Layers className="h-4 w-4 text-zinc-600 dark:text-zinc-300" />
            <ArrowUpRight className="h-3.5 w-3.5 text-zinc-400 group-hover:text-zinc-900 dark:group-hover:text-zinc-100 transition-colors" />
          </div>
          <div>
            <h3 className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
              扩展执行器
            </h3>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              支持 Codex、Grok 与多模型路由。
            </p>
          </div>
        </div>

        <div
          onClick={() => onNavigateTab && onNavigateTab('mcp')}
          className="rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800/80 dark:bg-[#111113] hover:border-zinc-300 dark:hover:border-zinc-700 transition-colors cursor-pointer group flex flex-col justify-between h-32"
        >
          <div className="flex items-start justify-between">
            <Network className="h-4 w-4 text-zinc-600 dark:text-zinc-300" />
            <ArrowUpRight className="h-3.5 w-3.5 text-zinc-400 group-hover:text-zinc-900 dark:group-hover:text-zinc-100 transition-colors" />
          </div>
          <div>
            <h3 className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
              MCP 协议接入
            </h3>
            <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
              通过 HTTP 接入本地开发客户端。
            </p>
          </div>
        </div>
      </div>

      {/* Activity Heatmap */}
      <div className="rounded-xl border border-zinc-200 bg-white p-5 dark:border-zinc-800/80 dark:bg-[#111113] space-y-4">
        <div className="flex items-center justify-between">
          <div className="space-y-0.5">
            <div className="text-xs text-zinc-500 dark:text-zinc-400">代码变更行数</div>
            <div className="text-xl font-semibold font-mono tracking-tight text-zinc-900 dark:text-zinc-100">
              {patchLines.toLocaleString()}
            </div>
          </div>

          <div className="flex items-center gap-1 p-0.5 rounded-full bg-zinc-100 dark:bg-zinc-800/80 text-xs">
            {(['all', 'tab', 'agent'] as const).map((mode) => (
              <button
                key={mode}
                onClick={() => setHeatmapFilter(mode)}
                className={`px-3 py-1 rounded-full capitalize transition-colors cursor-pointer ${
                  heatmapFilter === mode
                    ? 'bg-white text-zinc-950 font-medium shadow-2xs dark:bg-zinc-700 dark:text-zinc-100'
                    : 'text-zinc-500 hover:text-zinc-800 dark:text-zinc-400'
                }`}
              >
                {mode}
              </button>
            ))}
          </div>
        </div>

        <div className="overflow-x-auto pt-1 pb-1">
          <div className="flex justify-between text-[11px] text-zinc-400 font-mono mb-2 min-w-[680px]">
            {months.map((m, i) => (
              <span key={i}>{m}</span>
            ))}
          </div>

          <div className="grid grid-flow-col grid-rows-7 gap-1 min-w-[680px]">
            {cells.map((level, idx) => {
              let bg = 'bg-zinc-100 dark:bg-zinc-800/70';
              if (level === 1) bg = 'bg-zinc-300 dark:bg-zinc-700';
              if (level === 2) bg = 'bg-zinc-400 dark:bg-zinc-500';
              if (level === 3) bg = 'bg-zinc-600 dark:bg-zinc-400';
              if (level === 4) bg = 'bg-zinc-900 dark:bg-zinc-100';

              return (
                <div
                  key={idx}
                  className={`h-2.5 w-2.5 rounded-[2px] ${bg}`}
                />
              );
            })}
          </div>
        </div>

        <div className="flex flex-wrap items-center justify-between gap-4 pt-3 border-t border-zinc-100 dark:border-zinc-800/80 text-xs font-mono text-zinc-500 dark:text-zinc-400">
          <div className="flex items-center gap-6">
            <div>
              <span className="block text-[10px] text-zinc-400">活跃月份</span>
              <span className="text-zinc-800 dark:text-zinc-200">{heatmap?.active_month || '—'}</span>
            </div>
            <div>
              <span className="block text-[10px] text-zinc-400">峰值日期</span>
              <span className="text-zinc-800 dark:text-zinc-200">{heatmap?.peak_date || '—'}</span>
            </div>
          </div>

          <div className="flex items-center gap-1 text-[11px]">
            <span>Less</span>
            <span className="h-2.5 w-2.5 rounded-[2px] bg-zinc-100 dark:bg-zinc-800/70" />
            <span className="h-2.5 w-2.5 rounded-[2px] bg-zinc-300 dark:bg-zinc-700" />
            <span className="h-2.5 w-2.5 rounded-[2px] bg-zinc-400 dark:bg-zinc-500" />
            <span className="h-2.5 w-2.5 rounded-[2px] bg-zinc-600 dark:bg-zinc-400" />
            <span className="h-2.5 w-2.5 rounded-[2px] bg-zinc-900 dark:bg-zinc-100" />
            <span>More</span>
          </div>
        </div>
      </div>
    </div>
  );
};
