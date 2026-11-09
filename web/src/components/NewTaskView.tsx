import React, { useState } from 'react';
import { ArrowUp } from 'lucide-react';
import { Task } from '../types/delegate';

interface NewTaskViewProps {
  onLaunch: (taskData: Partial<Task>) => void;
  onCancel: () => void;
  initialPrompt?: string;
  initialModel?: string;
  initialHarness?: string;
}

export const NewTaskView: React.FC<NewTaskViewProps> = ({
  onLaunch,
  initialPrompt = '',
  initialModel = 'claude-3-7-sonnet',
  initialHarness = 'sdk',
}) => {
  const [prompt, setPrompt] = useState(initialPrompt);

  const isMac =
    typeof navigator !== 'undefined' &&
    /Mac|iPod|iPhone|iPad/i.test(
      (navigator as Navigator & { userAgentData?: { platform?: string } }).userAgentData?.platform ||
        navigator.platform ||
        navigator.userAgent
    );

  const submitTask = () => {
    if (!prompt.trim()) return;

    const title = prompt.trim().split(/\r?\n/)[0].slice(0, 48);

    onLaunch({
      prompt: prompt.trim(),
      title,
      model: initialModel,
      harness: initialHarness as any,
      agent: initialModel.includes('claude')
        ? 'anthropic'
        : initialModel.includes('gpt') || initialModel.includes('o3')
        ? 'openai'
        : initialModel.includes('gemini')
        ? 'gemini'
        : 'grok',
    });
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    submitTask();
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    const isModPressed = isMac ? e.metaKey : e.ctrlKey;
    if (isModPressed && e.key === 'Enter') {
      e.preventDefault();
      submitTask();
    }
  };

  return (
    <div className="max-w-2xl mx-auto pt-16 sm:pt-24">
      <div className="mb-5">
        <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100 tracking-tight">
          新建任务
        </h1>
      </div>

      <form onSubmit={handleSubmit}>
        <div className="rounded-xl border border-zinc-200 bg-white dark:border-zinc-800 dark:bg-[#111113] focus-within:border-zinc-400 dark:focus-within:border-zinc-600 transition-colors">
          <textarea
            autoFocus
            rows={5}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="输入需要在隔离沙箱中执行的任务指令..."
            className="w-full p-4 bg-transparent text-sm text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 dark:placeholder:text-zinc-600 focus:outline-none resize-none leading-relaxed"
          />

          <div className="flex items-center justify-between px-4 py-2.5 border-t border-zinc-100 dark:border-zinc-800/80">
            <span className="text-[11px] text-zinc-400 dark:text-zinc-500 font-mono">
              {isMac ? '⌘ + Enter' : 'Ctrl + Enter'} 启动
            </span>

            <button
              type="submit"
              disabled={!prompt.trim()}
              className="px-3.5 py-1.5 rounded-lg bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-950 text-xs font-medium hover:bg-zinc-800 dark:hover:bg-zinc-200 disabled:opacity-30 disabled:cursor-not-allowed transition-colors cursor-pointer flex items-center gap-1.5"
            >
              <span>启动任务</span>
              <ArrowUp className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>
      </form>
    </div>
  );
};
