import React, { useState, useEffect, useRef } from 'react';
import { ArrowLeft, Copy, Check } from 'lucide-react';
import { Task } from '../types/delegate';
import { formatBytes, formatDuration, calculateCacheEfficiency, parseGitDiff } from '../utils/task-parser';

export interface TaskTerminalProps {
  task?: Task;
  onBack: () => void;
  onUpdateTaskConfig?: (taskId: string, updates: Partial<Task>) => void;
  onSimulateStep?: (taskId: string) => void;
  onCancelTask?: (taskId: string) => void;
  models?: string[];
  harnesses?: string[];
  sandboxDefaults?: { memory?: string; cpus?: string | number };
}

export const TaskTerminal: React.FC<TaskTerminalProps> = ({
  task,
  onBack,
  onUpdateTaskConfig,
  onSimulateStep,
  onCancelTask,
  models,
  harnesses,
  sandboxDefaults,
}) => {
  const [inputVal, setInputVal] = useState('');
  const [tuiHistory, setTuiHistory] = useState<string[]>([]);
  const [tuiViewMode, setTuiViewMode] = useState<'stream' | 'diff' | 'outputs' | 'cost'>('stream');
  const [copiedPatch, setCopiedPatch] = useState(false);
  const [minimized, setMinimized] = useState(false);
  const [zoomed, setZoomed] = useState(false);

  const terminalEndRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    terminalEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [task?.events, tuiHistory, tuiViewMode]);

  if (!task) {
    return null;
  }

  const handleCommandSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const cmd = inputVal.trim();
    if (!cmd) return;

    setInputVal('');
    setTuiHistory((prev) => [...prev, `> ${cmd}`]);

    if (cmd.startsWith('/')) {
      handleSlashCommand(cmd);
      return;
    }

    if (onSimulateStep) {
      setTuiHistory((prev) => [...prev, `[exec] ${cmd}`]);
      onSimulateStep(task.id);
      return;
    }
    setTuiHistory((prev) => [...prev, '沙箱不接收自由输入，输入 /help 查看命令']);
  };

  const handleSlashCommand = (cmd: string) => {
    const lower = cmd.toLowerCase();
    if (lower === '/help') {
      setTuiHistory((prev) => [
        ...prev,
        `Commands: /stream  /diff  /outputs  /cost  /step  /cancel  /clear  /exit`,
      ]);
    } else if (lower === '/diff') {
      setTuiViewMode('diff');
    } else if (lower === '/outputs') {
      setTuiViewMode('outputs');
    } else if (lower === '/cost') {
      setTuiViewMode('cost');
    } else if (lower === '/stream') {
      setTuiViewMode('stream');
    } else if (lower === '/step') {
      if (onSimulateStep) {
        onSimulateStep(task.id);
        setTuiHistory((prev) => [...prev, `[step] advancing task execution...`]);
      } else {
        setTuiHistory((prev) => [...prev, `[step] 云端沙箱自动推进，请查看日志流`]);
      }
    } else if (lower === '/cancel' && onCancelTask) {
      onCancelTask(task.id);
      setTuiHistory((prev) => [...prev, `[signal] SIGTERM sent to container.`]);
    } else if (lower === '/clear') {
      setTuiHistory([]);
    } else if (lower === '/exit') {
      onBack();
    } else {
      setTuiHistory((prev) => [...prev, `unknown command: ${cmd} (type /help)`]);
    }
  };

  const copyPatch = () => {
    if (!task.raw_patch) return;
    navigator.clipboard.writeText(task.raw_patch);
    setCopiedPatch(true);
    setTimeout(() => setCopiedPatch(false), 2000);
  };

  const parsedDiff = task.raw_patch ? parseGitDiff(task.raw_patch) : null;
  const host = task.container_name || `sandbox-${task.id}`;
  const prompt = (
    <>
      <span className="term-user">delegate@{host}</span>
      <span className="term-dim">:</span>
      <span className="term-path">~/workspace</span>
      <span className="term-dim"> % </span>
    </>
  );

  return (
    <div className={`${zoomed ? 'max-w-none' : 'max-w-5xl'} mx-auto w-full min-w-0 space-y-4`}>
      {/* External Header & Navigation (Outside TUI) */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3 min-w-0">
          <button
            onClick={onBack}
            className="flex items-center gap-1.5 text-xs text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-100 transition-colors cursor-pointer shrink-0"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            <span>返回</span>
          </button>
          <span className="text-zinc-300 dark:text-zinc-700">/</span>
          <span className="text-sm font-medium text-zinc-900 dark:text-zinc-100 truncate">
            {task.title}
          </span>
          <span className="font-mono text-xs text-zinc-400 dark:text-zinc-500 shrink-0">
            {task.id}
          </span>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {task.raw_patch && (
            <button
              onClick={copyPatch}
              className="px-2.5 py-1 rounded-md border border-zinc-200 dark:border-zinc-800 text-xs text-zinc-700 dark:text-zinc-300 hover:bg-zinc-100 dark:hover:bg-zinc-800/60 transition-colors cursor-pointer flex items-center gap-1"
            >
              {copiedPatch ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
              <span>{copiedPatch ? '已复制补丁' : '复制 Patch'}</span>
            </button>
          )}
          {task.status === 'running' && onSimulateStep && (
            <button
              onClick={() => onSimulateStep(task.id)}
              className="px-2.5 py-1 rounded-md bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-950 text-xs font-medium hover:bg-zinc-800 dark:hover:bg-zinc-200 transition-colors cursor-pointer"
            >
              推进执行
            </button>
          )}
          {['queued', 'preparing', 'running'].includes(task.status) && onCancelTask && (
            <button
              onClick={() => onCancelTask(task.id)}
              className="px-2.5 py-1 rounded-md border border-zinc-200 dark:border-zinc-800 text-xs text-zinc-600 dark:text-zinc-400 hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors cursor-pointer"
            >
              终止任务
            </button>
          )}
        </div>
      </div>

      {/* External Configuration Bar (Placed strictly outside the TUI) */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 p-3 rounded-lg border border-zinc-200 bg-white dark:border-zinc-800/80 dark:bg-[#111113] text-xs">
        <div className="space-y-1">
          <span className="text-[11px] text-zinc-400 dark:text-zinc-500 block">模型</span>
          <select
            value={task.model}
            disabled={!onUpdateTaskConfig}
            onChange={(e) => onUpdateTaskConfig?.(task.id, { model: e.target.value })}
            className="w-full bg-transparent font-mono text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none cursor-pointer disabled:cursor-default"
          >
            {(models?.includes(task.model) ? models : [task.model, ...(models || [])]).map((model) => (
              <option key={model} value={model} className="bg-white dark:bg-zinc-900">{model}</option>
            ))}
          </select>
        </div>

        <div className="space-y-1">
          <span className="text-[11px] text-zinc-400 dark:text-zinc-500 block">执行器</span>
          <select
            value={task.harness}
            disabled={!onUpdateTaskConfig}
            onChange={(e) => onUpdateTaskConfig?.(task.id, { harness: e.target.value })}
            className="w-full bg-transparent font-mono text-xs text-zinc-900 dark:text-zinc-100 focus:outline-none cursor-pointer disabled:cursor-default"
          >
            {(harnesses?.includes(task.harness) ? harnesses : [task.harness, ...(harnesses || [])]).map((harness) => (
              <option key={harness} value={harness} className="bg-white dark:bg-zinc-900">{harness}</option>
            ))}
          </select>
        </div>

        <div className="space-y-1">
          <span className="text-[11px] text-zinc-400 dark:text-zinc-500 block">沙箱配额</span>
          <div className="font-mono text-zinc-800 dark:text-zinc-200 truncate">
            {task.sandbox_limits?.cpus || sandboxDefaults?.cpus || '-'} CPU · {task.sandbox_limits?.memory || sandboxDefaults?.memory || '-'}
          </div>
        </div>

        <div className="space-y-1">
          <span className="text-[11px] text-zinc-400 dark:text-zinc-500 block">耗时与轮次</span>
          <div className="font-mono text-zinc-800 dark:text-zinc-200">
            {task.duration_s == null ? '-' : formatDuration(task.duration_s)} · {task.agent_usage?.turns ?? 0}/{task.max_turns} 轮
          </div>
        </div>
      </div>

      <div className="mac-window text-[#e4e4e7] font-mono text-xs">
        <div className="mac-titlebar">
          <div className="mac-lights">
            <button type="button" className="mac-light mac-light-close" title="关闭并返回" onClick={onBack} />
            <button type="button" className="mac-light mac-light-min" title={minimized ? '展开' : '最小化'} onClick={() => setMinimized((value) => !value)} />
            <button type="button" className="mac-light mac-light-zoom" title={zoomed ? '还原' : '缩放'} onClick={() => { setMinimized(false); setZoomed((value) => !value); }} />
          </div>
          <div className="mac-title">{host} — zsh — 80×28</div>
          <span className="w-[78px]" />
        </div>

        {!minimized && (
        <div
          onClick={() => inputRef.current?.focus()}
          className={`term-screen px-4 py-3 overflow-y-auto select-text ${zoomed ? 'min-h-[68vh] max-h-[78vh]' : 'min-h-[460px] max-h-[62vh]'}`}
        >
          <div className="term-dim">Last login: {task.created_at || 'now'} on ttys001</div>
          <div className="break-all">{prompt}task-runner attach --id {task.id}</div>
          <div className="term-dim break-all"># {task.prompt}</div>
          <div className="term-dim"># status={task.status} model={task.model} harness={task.harness}</div>
          <div className="mt-2">
            {(
              [
                { id: 'stream', label: 'stream' },
                { id: 'diff', label: 'diff' },
                { id: 'outputs', label: 'outputs' },
                { id: 'cost', label: 'cost' },
              ] as const
            ).map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setTuiViewMode(tab.id)}
                className={`mr-4 cursor-pointer ${tuiViewMode === tab.id ? 'text-white underline' : 'term-dim hover:text-white'}`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Mode 1: Execution Stream */}
          {tuiViewMode === 'stream' && (
            <div className="space-y-2 pt-1">
              {(task.events || []).map((ev) => (
                <div key={ev.id} className="space-y-1">
                  <div className="flex items-baseline gap-2">
                    <span className="text-zinc-600 shrink-0">[{ev.ts}]</span>
                    <span className="text-zinc-400 uppercase shrink-0">
                      [{ev.kind}{ev.tool_name ? `:${ev.tool_name}` : ''}]
                    </span>
                    <span className="text-white">{ev.summary}</span>
                  </div>

                  {ev.tool_args && (
                    <div className="pl-16 text-zinc-400 whitespace-pre-wrap">
                      {typeof ev.tool_args === 'string'
                        ? `$ ${ev.tool_args}`
                        : ev.tool_args.command
                        ? `$ ${String(ev.tool_args.command)}`
                        : JSON.stringify(ev.tool_args)}
                    </div>
                  )}

                  {ev.tool_result && (
                    <div className="pl-16 text-zinc-500 whitespace-pre-wrap border-l border-zinc-800 ml-2">
                      {ev.tool_result}
                    </div>
                  )}
                </div>
              ))}

              {task.result_text && (
                <div className="pt-3 mt-3 border-t border-zinc-900 text-zinc-300 whitespace-pre-wrap">
                  {task.result_text}
                </div>
              )}
            </div>
          )}

          {/* Mode 2: Monochrome Diff */}
          {tuiViewMode === 'diff' && (
            <div className="space-y-2 pt-1">
              <div className="text-zinc-400">
                --- git diff ({parsedDiff?.files.length || 0} files, +{parsedDiff?.totalInsertions || 0} / -{parsedDiff?.totalDeletions || 0}) ---
              </div>
              {task.raw_patch ? (
                <div className="whitespace-pre overflow-x-auto leading-5">
                  {task.raw_patch.split(/\r?\n/).map((l, i) => {
                    const isAdd = l.startsWith('+') && !l.startsWith('+++');
                    const isDel = l.startsWith('-') && !l.startsWith('---');
                    const isHunk = l.startsWith('@@');

                    return (
                      <div
                        key={i}
                        className={
                          isAdd
                            ? 'term-add'
                            : isDel
                            ? 'term-del'
                            : isHunk
                            ? 'term-hunk pt-1'
                            : 'term-dim'
                        }
                      >
                        {l}
                      </div>
                    );
                  })}
                </div>
              ) : (
                <div className="text-zinc-600">no diff output available.</div>
              )}
            </div>
          )}

          {/* Mode 3: Monochrome Outputs */}
          {tuiViewMode === 'outputs' && (
            <div className="space-y-1.5 pt-1">
              <div className="text-zinc-400">--- /outputs directory ---</div>
                {task.outputs && task.outputs.length > 0 ? (
                task.outputs.map((out, idx) => (
                  <div key={idx} className="flex items-center justify-between py-1 border-b border-zinc-900">
                    {out.downloadUrl ? (
                      <a href={out.downloadUrl} className="text-white underline">{out.path}</a>
                    ) : (
                      <span className="text-white">{out.path}</span>
                    )}
                    <span className="text-zinc-500">{formatBytes(out.size)}</span>
                  </div>
                ))
              ) : (
                <div className="text-zinc-600">0 files in /outputs.</div>
              )}
            </div>
          )}

          {/* Mode 4: Monochrome Token Usage */}
          {tuiViewMode === 'cost' && (
            <div className="space-y-1 pt-1 text-zinc-300">
              <div className="text-zinc-400">--- token usage ---</div>
              <div>input_tokens      : {task.agent_usage?.input_tokens?.toLocaleString() || 0}</div>
              <div>output_tokens     : {task.agent_usage?.output_tokens?.toLocaleString() || 0}</div>
              <div>cache_read_tokens : {task.agent_usage?.cache_read_tokens?.toLocaleString() || 0}</div>
              <div>
                cache_hit_rate    :{' '}
                {task.agent_usage
                  ? `${calculateCacheEfficiency(task.agent_usage.cache_read_tokens, task.agent_usage.input_tokens)}%`
                  : '0%'}
              </div>
              <div>turns             : {task.agent_usage?.turns ?? 0} / {task.max_turns}</div>
              <div className="pt-2 text-zinc-400">--- sandbox ---</div>
              <div>sandbox_points    : {task.sandbox_points ?? 0}</div>
            </div>
          )}

          {/* Interactive Command History */}
          {tuiHistory.map((h, i) => (
            <div key={i} className="text-zinc-300 whitespace-pre-wrap">
              {h}
            </div>
          ))}

          <form onSubmit={handleCommandSubmit} className="mt-3 flex items-baseline">
            <span className="shrink-0">{prompt}</span>
            <span className="relative min-w-0 flex-1">
              <input
                ref={inputRef}
                type="text"
                value={inputVal}
                onChange={(event) => setInputVal(event.target.value)}
                spellCheck={false}
                autoCapitalize="off"
                className="term-input"
                aria-label="终端输入"
              />
              {inputVal.length === 0 && <span className="term-cursor absolute left-0 top-[0.2em]" />}
            </span>
          </form>
          <div ref={terminalEndRef} />
        </div>
        )}
      </div>
    </div>
  );
};
