import React, { useState } from 'react';
import { Search, Plus, ArrowRight } from 'lucide-react';
import { Task } from '../types/delegate';
import { formatDuration } from '../utils/task-parser';

interface TasksViewProps {
  tasks: Task[];
  onSelectTask: (task: Task) => void;
  onOpenNewTask: () => void;
}

export const TasksView: React.FC<TasksViewProps> = ({
  tasks,
  onSelectTask,
  onOpenNewTask,
}) => {
  const [statusFilter, setStatusFilter] = useState<'all' | 'running' | 'succeeded' | 'failed' | 'cancelled'>('all');
  const [searchQuery, setSearchQuery] = useState('');

  const filteredTasks = tasks.filter((t) => {
    const matchStatus = statusFilter === 'all' || t.status === statusFilter;
    const matchSearch =
      searchQuery === '' ||
      t.title.toLowerCase().includes(searchQuery.toLowerCase()) ||
      t.id.toLowerCase().includes(searchQuery.toLowerCase()) ||
      t.model.toLowerCase().includes(searchQuery.toLowerCase()) ||
      t.harness.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (t.agent && t.agent.toLowerCase().includes(searchQuery.toLowerCase()));
    return matchStatus && matchSearch;
  });

  const runningCount = tasks.filter((t) => t.status === 'running' || t.status === 'queued').length;
  const succeededCount = tasks.filter((t) => t.status === 'succeeded').length;
  const failedCount = tasks.filter((t) => t.status === 'failed').length;

  return (
    <div className="space-y-5 max-w-5xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100 tracking-tight">
          任务
        </h1>

        <button
          onClick={onOpenNewTask}
          className="px-3.5 py-1.5 rounded-lg text-xs font-medium bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-950 hover:bg-zinc-800 dark:hover:bg-zinc-200 transition-colors cursor-pointer flex items-center gap-1.5"
        >
          <Plus className="h-3.5 w-3.5" />
          <span>新建任务</span>
        </button>
      </div>

      {/* Filter and Search Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div className="flex items-center gap-1 text-xs overflow-x-auto pb-1 sm:pb-0">
          {[
            { id: 'all', label: '全部', count: tasks.length },
            { id: 'running', label: '进行中', count: runningCount },
            { id: 'succeeded', label: '已完成', count: succeededCount },
            { id: 'failed', label: '失败', count: failedCount },
            { id: 'cancelled', label: '已取消', count: tasks.filter((t) => t.status === 'cancelled').length },
          ].map((tab) => (
            <button
              key={tab.id}
              onClick={() => setStatusFilter(tab.id as any)}
              className={`px-3 py-1.5 rounded-lg text-xs transition-colors cursor-pointer flex items-center gap-1.5 whitespace-nowrap ${
                statusFilter === tab.id
                  ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-950 font-medium'
                  : 'text-zinc-500 hover:text-zinc-900 hover:bg-zinc-100 dark:text-zinc-400 dark:hover:text-zinc-200 dark:hover:bg-zinc-800/60'
              }`}
            >
              <span>{tab.label}</span>
              <span className="opacity-60 font-mono text-[11px]">{tab.count}</span>
            </button>
          ))}
        </div>

        <div className="relative min-w-[220px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-zinc-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="搜索任务..."
            className="w-full pl-8 pr-3 py-1.5 rounded-lg bg-white dark:bg-[#111113] border border-zinc-200 dark:border-zinc-800 text-xs text-zinc-800 dark:text-zinc-200 placeholder:text-zinc-400 focus:outline-none focus:border-zinc-400 dark:focus:border-zinc-600"
          />
        </div>
      </div>

      {/* Task List */}
      <div className="rounded-xl border border-zinc-200 bg-white dark:border-zinc-800/80 dark:bg-[#111113] overflow-hidden">
        {filteredTasks.length === 0 ? (
          <div className="py-12 text-center text-zinc-400 text-xs">
            暂无任务记录
          </div>
        ) : (
          <div className="divide-y divide-zinc-100 dark:divide-zinc-800/80 text-xs">
            {filteredTasks.map((task) => (
              <div
                key={task.id}
                onClick={() => onSelectTask(task)}
                className="p-4 flex items-center justify-between hover:bg-zinc-50 dark:hover:bg-zinc-900/50 cursor-pointer transition-colors group"
              >
                <div className="space-y-1 min-w-0 pr-4">
                  <div className="flex items-center gap-2 flex-wrap font-mono text-[11px] text-zinc-500 dark:text-zinc-400">
                    <span className="px-1.5 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-800 dark:text-zinc-200 uppercase text-[10px]">
                      {task.status}
                    </span>
                    <span>{task.id}</span>
                    <span>·</span>
                    <span>{task.model}</span>
                    <span>·</span>
                    <span>{task.harness}</span>
                    <span>·</span>
                    <span>{formatDuration(task.duration_s || 0)}</span>
                  </div>

                  <div className="font-medium text-sm text-zinc-900 dark:text-zinc-100 truncate">
                    {task.title}
                  </div>
                </div>

                <div className="flex items-center gap-4 shrink-0">
                  {task.patch_stats && (
                    <div className="text-right font-mono text-[11px] text-zinc-500 dark:text-zinc-400 tabular-nums">
                      +{task.patch_stats.insertions} / -{task.patch_stats.deletions}
                    </div>
                  )}

                  <ArrowRight className="h-4 w-4 text-zinc-400 group-hover:text-zinc-900 dark:group-hover:text-zinc-100 transition-colors" />
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
