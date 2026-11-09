import React, { useState } from 'react';
import {
  Search,
  CheckCircle2,
  Clock,
  AlertCircle,
  XCircle,
  FileCode,
  ArrowRight,
  Terminal,
  Cpu,
} from 'lucide-react';
import { Task } from '../types/delegate';
import { formatDuration } from '../utils/task-parser';

interface TaskListProps {
  tasks: Task[];
  onSelectTask: (task: Task) => void;
  onOpenNewTask: () => void;
}

export const TaskList: React.FC<TaskListProps> = ({
  tasks,
  onSelectTask,
  onOpenNewTask,
}) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<'all' | 'running' | 'succeeded' | 'failed'>('all');

  const filteredTasks = tasks.filter((task) => {
    const matchesSearch =
      task.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
      task.id.toLowerCase().includes(searchTerm.toLowerCase()) ||
      task.model.toLowerCase().includes(searchTerm.toLowerCase()) ||
      task.prompt.toLowerCase().includes(searchTerm.toLowerCase());

    if (!matchesSearch) return false;

    if (statusFilter === 'running') return task.status === 'running' || task.status === 'queued';
    if (statusFilter === 'succeeded') return task.status === 'succeeded';
    if (statusFilter === 'failed') return task.status === 'failed' || task.status === 'timeout' || task.status === 'cancelled';

    return true;
  });

  const runningCount = tasks.filter((t) => t.status === 'running' || t.status === 'queued').length;
  const succeededCount = tasks.filter((t) => t.status === 'succeeded').length;
  const failedCount = tasks.filter((t) => ['failed', 'timeout', 'cancelled'].includes(t.status)).length;

  return (
    <div className="space-y-5">
      {/* Top filter and search bar */}
      <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
        {/* Status filter tabs: Liquid Glass segmented pill */}
        <div className="flex items-center gap-1 p-1 rounded-xl bg-zinc-200/50 dark:bg-white/5 backdrop-blur-md border border-white/40 dark:border-white/5 text-xs font-medium">
          <button
            onClick={() => setStatusFilter('all')}
            className={`px-3 py-1.5 rounded-lg transition-all whitespace-nowrap cursor-pointer ${
              statusFilter === 'all'
                ? 'bg-white text-zinc-950 shadow-sm dark:bg-zinc-800 dark:text-white font-semibold'
                : 'text-zinc-600 hover:text-zinc-950 dark:text-zinc-400 dark:hover:text-zinc-100'
            }`}
          >
            全部任务 ({tasks.length})
          </button>
          <button
            onClick={() => setStatusFilter('running')}
            className={`px-3 py-1.5 rounded-lg transition-all whitespace-nowrap cursor-pointer ${
              statusFilter === 'running'
                ? 'bg-white text-zinc-950 shadow-sm dark:bg-zinc-800 dark:text-white font-semibold'
                : 'text-zinc-600 hover:text-zinc-950 dark:text-zinc-400 dark:hover:text-zinc-100'
            }`}
          >
            进行中 ({runningCount})
          </button>
          <button
            onClick={() => setStatusFilter('succeeded')}
            className={`px-3 py-1.5 rounded-lg transition-all whitespace-nowrap cursor-pointer ${
              statusFilter === 'succeeded'
                ? 'bg-white text-zinc-950 shadow-sm dark:bg-zinc-800 dark:text-white font-semibold'
                : 'text-zinc-600 hover:text-zinc-950 dark:text-zinc-400 dark:hover:text-zinc-100'
            }`}
          >
            已成功 ({succeededCount})
          </button>
          <button
            onClick={() => setStatusFilter('failed')}
            className={`px-3 py-1.5 rounded-lg transition-all whitespace-nowrap cursor-pointer ${
              statusFilter === 'failed'
                ? 'bg-white text-zinc-950 shadow-sm dark:bg-zinc-800 dark:text-white font-semibold'
                : 'text-zinc-600 hover:text-zinc-950 dark:text-zinc-400 dark:hover:text-zinc-100'
            }`}
          >
            异常/取消 ({failedCount})
          </button>
        </div>

        {/* Search Input: Liquid Glass input */}
        <div className="relative w-full sm:w-72">
          <Search className="absolute left-3.5 top-2.5 h-3.5 w-3.5 text-zinc-400" />
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="搜索任务标题、ID 或模型..."
            className="w-full pl-9 pr-3.5 py-1.5 text-xs rounded-xl glass-card text-zinc-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-zinc-400 dark:focus:ring-white/20 transition-all placeholder:text-zinc-400"
          />
        </div>
      </div>

      {/* Task Table / Cards */}
      {filteredTasks.length === 0 ? (
        <div className="rounded-2xl glass-panel p-12 text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-2xl bg-zinc-100 dark:bg-white/5 border border-white/20 dark:border-white/5 mb-3 text-zinc-400">
            <Terminal className="h-6 w-6" />
          </div>
          <h3 className="text-sm font-semibold text-zinc-900 dark:text-white font-display">暂无匹配任务</h3>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1 max-w-sm mx-auto">
            可以通过上方「外派新任务」或在本地终端运行 Claude Code 自动外派任务。
          </p>
          <button
            onClick={onOpenNewTask}
            className="mt-4 px-4 py-2 text-xs font-semibold rounded-xl glass-button-primary"
          >
            外派第一个任务
          </button>
        </div>
      ) : (
        <div className="rounded-2xl glass-panel overflow-hidden divide-y divide-zinc-200/40 dark:divide-white/5">
          {filteredTasks.map((task) => {
            const isRunning = task.status === 'running' || task.status === 'queued';
            const isSucceeded = task.status === 'succeeded';
            const isFailed = ['failed', 'timeout', 'cancelled'].includes(task.status);

            return (
              <div
                key={task.id}
                onClick={() => onSelectTask(task)}
                className="group p-4.5 hover:bg-white/50 dark:hover:bg-white/[0.04] cursor-pointer transition-all duration-150 flex flex-col sm:flex-row sm:items-center justify-between gap-4"
              >
                {/* Left block: Title, metadata, ID */}
                <div className="space-y-1.5 min-w-0 flex-1">
                  <div className="flex items-center gap-2.5">
                    {/* Status Pill with Liquid Tint */}
                    <span
                      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-[10px] font-mono font-semibold uppercase border backdrop-blur-md ${
                        isSucceeded
                          ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-600 dark:text-emerald-400'
                          : isRunning
                          ? 'border-cyan-500/30 bg-cyan-500/10 text-cyan-600 dark:text-cyan-400'
                          : 'border-rose-500/30 bg-rose-500/10 text-rose-600 dark:text-rose-400'
                      }`}
                    >
                      {isSucceeded && <CheckCircle2 className="h-3 w-3" />}
                      {isRunning && <span className="h-1.5 w-1.5 rounded-full bg-cyan-500 animate-ping" />}
                      {isFailed && <AlertCircle className="h-3 w-3" />}
                      {task.status}
                    </span>

                    <span className="font-mono text-xs text-zinc-400 group-hover:text-zinc-600 dark:group-hover:text-zinc-300 transition-colors">
                      {task.id}
                    </span>

                    <span className="text-zinc-300 dark:text-zinc-700">·</span>

                    <span className="text-xs text-zinc-600 dark:text-zinc-400 font-mono">
                      {task.agent} · {task.model}
                    </span>

                    <span className="text-zinc-300 dark:text-zinc-700">·</span>

                    <span className="text-xs text-zinc-400 font-mono">
                      harness: {task.harness}
                    </span>
                  </div>

                  <h3 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100 group-hover:text-cyan-600 dark:group-hover:text-cyan-400 transition-colors truncate">
                    {task.title}
                  </h3>

                  <div className="flex items-center gap-3 text-xs text-zinc-500 dark:text-zinc-400 font-mono">
                    <span>来源: {task.source.toUpperCase()}</span>
                    <span>·</span>
                    <span>创建于: {task.created_at}</span>
                    {task.duration_s !== undefined && (
                      <>
                        <span>·</span>
                        <span>耗时: {formatDuration(task.duration_s)}</span>
                      </>
                    )}
                  </div>
                </div>

                {/* Right block: Diff stats & Interactive Arrow */}
                <div className="flex items-center justify-between sm:justify-end gap-5 shrink-0">
                  {task.patch_stats ? (
                    <div className="text-right font-mono text-xs">
                      <div className="text-zinc-400 text-[11px]">
                        {task.patch_stats.files} 个文件变更
                      </div>
                      <div className="tabular-nums font-semibold">
                        <span className="text-emerald-600 dark:text-emerald-400">
                          +{task.patch_stats.insertions}
                        </span>{' '}
                        <span className="text-rose-600 dark:text-rose-400">
                          -{task.patch_stats.deletions}
                        </span>
                      </div>
                    </div>
                  ) : isRunning ? (
                    <div className="text-right font-mono text-xs text-cyan-600 dark:text-cyan-400">
                      <div className="text-[11px] text-zinc-400">沙箱状态</div>
                      <div className="animate-pulse flex items-center gap-1">
                        <span className="inline-block h-1.5 w-1.5 rounded-full bg-cyan-500 animate-ping" />
                        <span>执行中...</span>
                      </div>
                    </div>
                  ) : null}

                  <div className="h-8 w-8 rounded-full flex items-center justify-center glass-button-secondary group-hover:scale-105 active:scale-95 transition-all">
                    <ArrowRight className="h-4 w-4 text-zinc-500 group-hover:text-zinc-900 dark:group-hover:text-white transition-colors" />
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
