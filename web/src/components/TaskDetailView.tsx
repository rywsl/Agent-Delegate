import React, { useState } from 'react';
import {
  ArrowLeft,
  Terminal,
  Cpu,
  Clock,
  CheckCircle2,
  AlertCircle,
  XCircle,
  FileText,
  Layers,
  Code2,
  FolderArchive,
  Download,
  Copy,
  Check,
  ChevronDown,
  ChevronRight,
  Play,
  RotateCcw,
} from 'lucide-react';
import { Task, NormEvent } from '../types/delegate';
import { DiffViewer } from './DiffViewer';
import { formatBytes, formatDuration, calculateCacheEfficiency } from '../utils/task-parser';

interface TaskDetailViewProps {
  task: Task;
  onBack: () => void;
  onCancelTask: (taskId: string) => void;
  onRerunTask: (task: Task) => void;
  onSimulateStep?: (taskId: string) => void;
}

export const TaskDetailView: React.FC<TaskDetailViewProps> = ({
  task,
  onBack,
  onCancelTask,
  onRerunTask,
  onSimulateStep,
}) => {
  const [activeTab, setActiveTab] = useState<'events' | 'diff' | 'outputs' | 'report'>('events');
  const [eventFilter, setEventFilter] = useState<'all' | 'tool_call' | 'thinking' | 'runner' | 'stderr'>('all');
  const [expandedEvents, setExpandedEvents] = useState<Record<string, boolean>>({ 'ev-7': true, 'ev-202': true });
  const [copiedId, setCopiedId] = useState(false);

  const toggleEvent = (id: string) => {
    setExpandedEvents((prev) => ({ ...prev, [id]: !prev[id] }));
  };

  const handleCopyId = () => {
    navigator.clipboard.writeText(task.id);
    setCopiedId(true);
    setTimeout(() => setCopiedId(false), 2000);
  };

  const filteredEvents = (task.events || []).filter((e) => {
    if (eventFilter === 'all') return true;
    return e.kind === eventFilter;
  });

  const statusColors = {
    succeeded: 'text-emerald-500 bg-emerald-500/10 border-emerald-500/30',
    running: 'text-cyan-500 bg-cyan-500/10 border-cyan-500/30 animate-pulse',
    queued: 'text-amber-500 bg-amber-500/10 border-amber-500/30',
    preparing: 'text-sky-500 bg-sky-500/10 border-sky-500/30',
    failed: 'text-rose-500 bg-rose-500/10 border-rose-500/30',
    cancelled: 'text-zinc-500 bg-zinc-500/10 border-zinc-500/30',
    timeout: 'text-orange-500 bg-orange-500/10 border-orange-500/30',
  }[task.status];

  return (
    <div className="space-y-6">
      {/* Top back button and title block */}
      <div className="glass-panel rounded-2xl p-6 space-y-4">
        <div className="flex items-center justify-between">
          <button
            onClick={onBack}
            className="flex items-center gap-1.5 text-xs text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-200 transition-colors cursor-pointer group"
          >
            <ArrowLeft className="h-3.5 w-3.5 transition-transform group-hover:-translate-x-0.5" />
            <span>返回任务列表</span>
          </button>

          <div className="flex items-center gap-2">
            {task.status === 'running' && onSimulateStep && (
              <button
                onClick={() => onSimulateStep(task.id)}
                className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-semibold rounded-lg bg-cyan-600 hover:bg-cyan-500 text-white shadow-[0_2px_10px_rgba(8,145,178,0.3)] transition-all active:scale-95 cursor-pointer"
                title="模拟沙箱执行下一步"
              >
                <Play className="h-3.5 w-3.5" />
                <span>模拟沙箱执行</span>
              </button>
            )}

            {task.status === 'running' ? (
              <button
                onClick={() => onCancelTask(task.id)}
                className="flex items-center gap-1 px-3 py-1.5 text-xs font-medium rounded-lg border border-rose-300 text-rose-700 hover:bg-rose-50 dark:border-rose-900/40 dark:text-rose-400 dark:hover:bg-rose-950/20 transition-all cursor-pointer"
              >
                <XCircle className="h-3.5 w-3.5" />
                <span>取消任务</span>
              </button>
            ) : (
              <button
                onClick={() => onRerunTask(task)}
                className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg glass-button-secondary cursor-pointer"
              >
                <RotateCcw className="h-3.5 w-3.5" />
                <span>以此重新外派</span>
              </button>
            )}
          </div>
        </div>

        <div className="flex flex-wrap items-start justify-between gap-4 pt-1">
          <div className="space-y-2 max-w-3xl">
            <div className="flex items-center gap-2.5 flex-wrap">
              <span className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-mono font-semibold border backdrop-blur-md ${statusColors}`}>
                {task.status === 'succeeded' && <CheckCircle2 className="h-3 w-3" />}
                {task.status === 'running' && <span className="h-1.5 w-1.5 rounded-full bg-cyan-500 animate-ping" />}
                {task.status === 'failed' && <AlertCircle className="h-3 w-3" />}
                {task.status.toUpperCase()}
              </span>

              <button
                onClick={handleCopyId}
                className="flex items-center gap-1 font-mono text-xs px-2 py-0.5 rounded-md bg-white/40 dark:bg-white/5 border border-white/40 dark:border-white/5 hover:bg-white/80 dark:hover:bg-white/10 text-zinc-600 dark:text-zinc-300 transition-all cursor-pointer"
                title="点击复制任务 ID"
              >
                <span>{task.id}</span>
                {copiedId ? <Check className="h-3 w-3 text-emerald-500" /> : <Copy className="h-3 w-3 text-zinc-400" />}
              </button>

              <span className="text-zinc-300 dark:text-zinc-700">·</span>
              <span className="text-xs text-zinc-500 dark:text-zinc-400 font-mono">
                来源: {task.source.toUpperCase()}
                {task.api_key_prefix && ` (${task.api_key_prefix}…)`}
              </span>
            </div>

            <h1 className="text-xl sm:text-2xl font-bold tracking-tight text-zinc-900 dark:text-white font-display">
              {task.title}
            </h1>
          </div>

          {/* Quick Metrics Cards */}
          <div className="flex items-center gap-3 text-xs font-mono">
            <div className="rounded-xl glass-card px-3.5 py-2">
              <div className="text-[10px] text-zinc-400">执行耗时</div>
              <div className="font-semibold text-zinc-800 dark:text-zinc-200 tabular-nums">
                {formatDuration(task.duration_s)}
              </div>
            </div>

            {task.patch_stats && (
              <div className="rounded-xl glass-card px-3.5 py-2">
                <div className="text-[10px] text-zinc-400">代码变更</div>
                <div className="font-semibold tabular-nums">
                  <span className="text-emerald-600 dark:text-emerald-400">+{task.patch_stats.insertions}</span>{' '}
                  <span className="text-rose-600 dark:text-rose-400">-{task.patch_stats.deletions}</span>
                </div>
              </div>
            )}

            {task.agent_usage && (
              <div className="rounded-xl glass-card px-3.5 py-2">
                <div className="text-[10px] text-zinc-400">缓存命中率</div>
                <div className="font-semibold text-cyan-600 dark:text-cyan-400 tabular-nums">
                  {calculateCacheEfficiency(task.agent_usage.cache_read_tokens, task.agent_usage.input_tokens)}%
                </div>
              </div>
            )}
          </div>
        </div>

        {task.status_reason && (
          <div className="rounded-xl border border-rose-200 bg-rose-50/60 p-3 text-xs text-rose-800 dark:border-rose-900/40 dark:bg-rose-950/20 dark:text-rose-300 backdrop-blur-md">
            <strong>状态说明: </strong>
            {task.status_reason}
          </div>
        )}
      </div>

      {/* Two Column Layout: Left Prompt & Environment, Right Artifact Deck */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Metadata & Prompt */}
        <div className="space-y-6 lg:col-span-1">
          {/* Prompt card */}
          <div className="rounded-2xl glass-panel p-5 space-y-3">
            <h2 className="text-xs font-semibold text-zinc-900 dark:text-white uppercase tracking-wider">
              任务指令 (Prompt)
            </h2>
            <pre className="text-xs font-mono text-zinc-800 dark:text-zinc-200 bg-white/50 dark:bg-black/40 p-3.5 rounded-xl border border-zinc-200/50 dark:border-white/5 whitespace-pre-wrap leading-relaxed max-h-56 overflow-y-auto">
              {task.prompt}
            </pre>
            {task.repo_url && (
              <div className="pt-3 border-t border-zinc-200/40 dark:border-white/5 text-xs font-mono">
                <div className="text-zinc-400 text-[11px]">目标 Git 仓库:</div>
                <div className="text-zinc-700 dark:text-zinc-300 truncate mt-0.5">
                  {task.repo_url}
                  {task.repo_ref && <span className="text-cyan-600 dark:text-cyan-400"> @ {task.repo_ref}</span>}
                </div>
              </div>
            )}
          </div>

          {/* Sandbox & Container Specs */}
          <div className="rounded-2xl glass-panel p-5 space-y-3">
            <h2 className="text-xs font-semibold text-zinc-900 dark:text-white uppercase tracking-wider flex items-center justify-between">
              <span>沙箱容器审计</span>
              <span className="font-mono text-[11px] text-zinc-400">Docker</span>
            </h2>

            <div className="grid grid-cols-2 gap-2.5 text-xs font-mono">
              <div>
                <span className="text-zinc-400 text-[11px] block">模型提供商</span>
                <span className="font-medium text-zinc-800 dark:text-zinc-200">{task.agent} · {task.model}</span>
              </div>
              <div>
                <span className="text-zinc-400 text-[11px] block">执行 Harness</span>
                <span className="font-medium text-zinc-800 dark:text-zinc-200">{task.harness}</span>
              </div>
              <div>
                <span className="text-zinc-400 text-[11px] block">内存 / CPU</span>
                <span className="font-medium text-zinc-800 dark:text-zinc-200">
                  {task.sandbox_limits?.memory || '4096MB'} / {task.sandbox_limits?.cpus || '2.0'}
                </span>
              </div>
              <div>
                <span className="text-zinc-400 text-[11px] block">退出码 (Exit)</span>
                <span className={`font-medium ${task.exit_code === 0 ? 'text-emerald-500' : task.exit_code ? 'text-rose-500' : 'text-zinc-400'}`}>
                  {task.exit_code !== undefined && task.exit_code !== null ? task.exit_code : '运行中'}
                </span>
              </div>
              <div className="col-span-2 pt-1 border-t border-zinc-200/40 dark:border-white/5">
                <span className="text-zinc-400 text-[11px] block">容器镜像</span>
                <span className="text-zinc-600 dark:text-zinc-400 truncate block text-[11px]">
                  {task.sandbox_image || 'delegate-sandbox:sdk-v0.2.0'}
                </span>
              </div>
              {task.container_id && (
                <div className="col-span-2">
                  <span className="text-zinc-400 text-[11px] block">Container ID</span>
                  <span className="text-zinc-600 dark:text-zinc-400 truncate block text-[11px]">
                    {task.container_id.slice(0, 24)}…
                  </span>
                </div>
              )}
            </div>
          </div>

          {/* Token Usage Auditing */}
          {task.agent_usage && (
            <div className="rounded-2xl glass-panel p-5 space-y-3">
              <h2 className="text-xs font-semibold text-zinc-900 dark:text-white uppercase tracking-wider">
                Token 统计 (仅审计，不计费)
              </h2>
              <div className="space-y-2 text-xs font-mono">
                <div className="flex justify-between">
                  <span className="text-zinc-500 dark:text-zinc-400">Prompt 输入</span>
                  <span className="font-medium text-zinc-800 dark:text-zinc-200 tabular-nums">
                    {task.agent_usage.input_tokens.toLocaleString()}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-500 dark:text-zinc-400">Completion 输出</span>
                  <span className="font-medium text-zinc-800 dark:text-zinc-200 tabular-nums">
                    {task.agent_usage.output_tokens.toLocaleString()}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-zinc-500 dark:text-zinc-400">Prompt 缓存读取</span>
                  <span className="font-medium text-cyan-600 dark:text-cyan-400 tabular-nums">
                    {task.agent_usage.cache_read_tokens.toLocaleString()}
                  </span>
                </div>
                <div className="flex justify-between pt-1.5 border-t border-zinc-200/40 dark:border-white/5">
                  <span className="text-zinc-500 dark:text-zinc-400">对话轮次 (Turns)</span>
                  <span className="font-medium text-zinc-800 dark:text-zinc-200 tabular-nums">
                    {task.agent_usage.turns} / {task.max_turns}
                  </span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Right Column: Interactive Deck (Events, Diff, Outputs, Final Report) */}
        <div className="space-y-4 lg:col-span-2">
          {/* Deck tabs: Liquid Segmented pill */}
          <div className="flex items-center gap-1 p-1 rounded-xl glass-card">
            <button
              onClick={() => setActiveTab('events')}
              className={`flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium rounded-lg transition-all cursor-pointer ${
                activeTab === 'events'
                  ? 'bg-white text-zinc-950 font-semibold shadow-sm dark:bg-zinc-800 dark:text-white'
                  : 'text-zinc-600 hover:text-zinc-950 dark:text-zinc-400 dark:hover:text-zinc-200'
              }`}
            >
              <Terminal className="h-3.5 w-3.5" />
              <span>执行轨迹</span>
              <span className="font-mono text-[10px] text-zinc-400">({task.events?.length || 0})</span>
            </button>

            <button
              onClick={() => setActiveTab('diff')}
              className={`flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium rounded-lg transition-all cursor-pointer ${
                activeTab === 'diff'
                  ? 'bg-white text-zinc-950 font-semibold shadow-sm dark:bg-zinc-800 dark:text-white'
                  : 'text-zinc-600 hover:text-zinc-950 dark:text-zinc-400 dark:hover:text-zinc-200'
              }`}
            >
              <Code2 className="h-3.5 w-3.5" />
              <span>工作区 Patch</span>
              {task.patch_stats && (
                <span className="font-mono text-[10px] text-emerald-500 font-semibold">
                  (+{task.patch_stats.insertions}/-{task.patch_stats.deletions})
                </span>
              )}
            </button>

            <button
              onClick={() => setActiveTab('outputs')}
              className={`flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium rounded-lg transition-all cursor-pointer ${
                activeTab === 'outputs'
                  ? 'bg-white text-zinc-950 font-semibold shadow-sm dark:bg-zinc-800 dark:text-white'
                  : 'text-zinc-600 hover:text-zinc-950 dark:text-zinc-400 dark:hover:text-zinc-200'
              }`}
            >
              <FolderArchive className="h-3.5 w-3.5" />
              <span>产物文件 (/outputs)</span>
              <span className="font-mono text-[10px] text-zinc-400">({task.outputs?.length || 0})</span>
            </button>

            <button
              onClick={() => setActiveTab('report')}
              className={`flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium rounded-lg transition-all cursor-pointer ${
                activeTab === 'report'
                  ? 'bg-white text-zinc-950 font-semibold shadow-sm dark:bg-zinc-800 dark:text-white'
                  : 'text-zinc-600 hover:text-zinc-950 dark:text-zinc-400 dark:hover:text-zinc-200'
              }`}
            >
              <FileText className="h-3.5 w-3.5" />
              <span>诊断总结报告</span>
            </button>
          </div>

          {/* Tab 1: Events Timeline */}
          {activeTab === 'events' && (
            <div className="space-y-3">
              {/* Event filter pill buttons */}
              <div className="flex items-center gap-2 text-xs">
                <span className="text-zinc-400 text-[11px]">过滤:</span>
                {(['all', 'tool_call', 'thinking', 'runner', 'stderr'] as const).map((filter) => (
                  <button
                    key={filter}
                    onClick={() => setEventFilter(filter)}
                    className={`px-2.5 py-1 rounded-lg text-[11px] font-mono transition-all cursor-pointer ${
                      eventFilter === filter
                        ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-950 font-semibold shadow-xs'
                        : 'glass-button-secondary text-zinc-600 dark:text-zinc-400'
                    }`}
                  >
                    {filter === 'all' && '全部事件'}
                    {filter === 'tool_call' && '工具调用'}
                    {filter === 'thinking' && '思考轨迹'}
                    {filter === 'runner' && '容器生命周期'}
                    {filter === 'stderr' && '终端报错'}
                  </button>
                ))}
              </div>

              {/* Event items list */}
              <div className="space-y-2">
                {filteredEvents.length === 0 ? (
                  <div className="rounded-2xl glass-panel p-8 text-center text-xs text-zinc-500 dark:text-zinc-400">
                    无匹配该过滤类型的事件。
                  </div>
                ) : (
                  filteredEvents.map((ev) => {
                    const isExpanded = !!expandedEvents[ev.id];
                    const isTool = ev.kind === 'tool_call';
                    const isThinking = ev.kind === 'thinking';
                    const isStderr = ev.kind === 'stderr';

                    return (
                      <div
                        key={ev.id}
                        className={`rounded-xl glass-card text-xs transition-all overflow-hidden ${
                          isStderr
                            ? 'border-rose-400/40 bg-rose-50/40 dark:border-rose-900/40 dark:bg-rose-950/15'
                            : isThinking
                            ? 'border-cyan-400/40 bg-cyan-50/30 dark:border-cyan-900/40 dark:bg-cyan-950/15'
                            : ''
                        }`}
                      >
                        <div
                          onClick={() => toggleEvent(ev.id)}
                          className="flex items-center justify-between p-3.5 cursor-pointer hover:bg-black/5 dark:hover:bg-white/5 select-none"
                        >
                          <div className="flex items-center gap-2.5 truncate pr-2">
                            <span className="font-mono text-[10px] text-zinc-400">{ev.ts}</span>
                            <span
                              className={`px-2 py-0.5 rounded-full text-[10px] font-mono font-semibold uppercase backdrop-blur-md ${
                                isTool
                                  ? 'bg-amber-500/15 text-amber-700 dark:text-amber-400 border border-amber-500/30'
                                  : isThinking
                                  ? 'bg-cyan-500/15 text-cyan-700 dark:text-cyan-400 border border-cyan-500/30'
                                  : isStderr
                                  ? 'bg-rose-500/15 text-rose-700 dark:text-rose-400 border border-rose-500/30'
                                  : 'bg-zinc-200/50 text-zinc-700 dark:bg-white/10 dark:text-zinc-300'
                              }`}
                            >
                              {ev.kind}
                            </span>
                            <span className="font-medium text-zinc-900 dark:text-zinc-100 truncate">
                              {ev.summary}
                            </span>
                          </div>

                          <div className="text-zinc-400 shrink-0">
                            {isExpanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                          </div>
                        </div>

                        {/* Collapsible detailed payload */}
                        {isExpanded && (
                          <div className="border-t border-zinc-200/40 dark:border-white/5 p-3.5 bg-black/[0.02] dark:bg-black/30 space-y-2.5 font-mono">
                            {ev.tool_args && (
                              <div>
                                <span className="text-[10px] text-zinc-400 uppercase font-semibold block mb-1">
                                  参数 / Arguments
                                </span>
                                <pre className="p-2.5 rounded-lg bg-white/70 dark:bg-black/60 text-[11px] border border-zinc-200/60 dark:border-white/5 overflow-x-auto whitespace-pre-wrap">
                                  {typeof ev.tool_args === 'string'
                                    ? ev.tool_args
                                    : JSON.stringify(ev.tool_args, null, 2)}
                                </pre>
                              </div>
                            )}

                            {ev.tool_result && (
                              <div>
                                <span className="text-[10px] text-zinc-400 uppercase font-semibold block mb-1">
                                  输出 / Output
                                </span>
                                <pre className="p-2.5 rounded-lg bg-white/70 dark:bg-black/60 text-[11px] border border-zinc-200/60 dark:border-white/5 overflow-x-auto whitespace-pre-wrap text-zinc-700 dark:text-zinc-300">
                                  {ev.tool_result}
                                </pre>
                              </div>
                            )}

                            {ev.data && (
                              <div>
                                <span className="text-[10px] text-zinc-400 uppercase font-semibold block mb-1">
                                  上下文数据
                                </span>
                                <pre className="p-2.5 rounded-lg bg-white/70 dark:bg-black/60 text-[11px] border border-zinc-200/60 dark:border-white/5 overflow-x-auto whitespace-pre-wrap text-zinc-700 dark:text-zinc-300">
                                  {JSON.stringify(ev.data, null, 2)}
                                </pre>
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
            </div>
          )}

          {/* Tab 2: Diff Patch */}
          {activeTab === 'diff' && (
            <DiffViewer
              rawDiff={task.raw_patch || ''}
              patchBytes={task.patch_stats?.bytes}
              taskId={task.id}
            />
          )}

          {/* Tab 3: Outputs */}
          {activeTab === 'outputs' && (
            <div className="rounded-2xl glass-panel p-5 space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-semibold uppercase text-zinc-900 dark:text-white">
                  沙箱输出文件 (/outputs)
                </h3>
                <span className="text-xs font-mono text-zinc-500">
                  {task.outputs?.length || 0} 个可回传产物
                </span>
              </div>

              {!task.outputs || task.outputs.length === 0 ? (
                <div className="text-center py-8 text-xs text-zinc-500 dark:text-zinc-400">
                  沙箱执行过程未在 /outputs 目录中留下独立产物文件。
                </div>
              ) : (
                <div className="space-y-2">
                  {task.outputs.map((out, idx) => (
                    <div
                      key={idx}
                      className="flex items-center justify-between p-3.5 rounded-xl glass-card transition-all"
                    >
                      <div className="space-y-0.5">
                        <div className="font-mono text-xs font-medium text-zinc-900 dark:text-white">
                          {out.path}
                        </div>
                        {out.sha256 && (
                          <div className="font-mono text-[10px] text-zinc-400">
                            SHA-256: {out.sha256}
                          </div>
                        )}
                      </div>

                      <div className="flex items-center gap-3">
                        <span className="font-mono text-xs text-zinc-500 tabular-nums">
                          {formatBytes(out.size)}
                        </span>
                        <a
                          href={`#download-${out.path}`}
                          onClick={(e) => {
                            e.preventDefault();
                            alert(`下载产物: ${out.path}`);
                          }}
                          className="flex items-center gap-1 px-3 py-1 text-xs font-medium rounded-lg glass-button-secondary"
                        >
                          <Download className="h-3 w-3" />
                          <span>下载</span>
                        </a>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Tab 4: Markdown Executive Report */}
          {activeTab === 'report' && (
            <div className="rounded-2xl glass-panel p-6">
              <div className="prose prose-sm dark:prose-invert max-w-none text-xs leading-relaxed space-y-3 font-sans">
                {task.result_text ? (
                  <div className="whitespace-pre-line text-zinc-800 dark:text-zinc-200">
                    {task.result_text}
                  </div>
                ) : (
                  <p className="text-zinc-400">任务尚未结束或未返回总结文本。</p>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
