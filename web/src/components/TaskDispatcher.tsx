import React, { useState } from 'react';
import {
  Send,
  GitBranch,
  ShieldAlert,
  Sliders,
  Sparkles,
  Cpu,
  Layers,
  Clock,
  RotateCcw,
} from 'lucide-react';
import { Task } from '../types/delegate';

interface TaskDispatcherProps {
  onDispatch: (taskData: Partial<Task>) => void;
  onCancel: () => void;
  initialPrompt?: string;
  initialTitle?: string;
}

export const TaskDispatcher: React.FC<TaskDispatcherProps> = ({
  onDispatch,
  onCancel,
  initialPrompt = '',
  initialTitle = '',
}) => {
  const [title, setTitle] = useState(initialTitle);
  const [prompt, setPrompt] = useState(initialPrompt);
  const [agent, setAgent] = useState<'anthropic' | 'openai' | 'gemini' | 'grok'>('anthropic');
  const [model, setModel] = useState('claude-3-7-sonnet');
  const [harness, setHarness] = useState<'sdk' | 'claude-code' | 'codex' | 'gemini' | 'grok' | 'pi' | 'deepseek'>('sdk');
  const [repoUrl, setRepoUrl] = useState('');
  const [repoRef, setRepoRef] = useState('main');
  const [timeoutMinutes, setTimeoutMinutes] = useState(30);
  const [maxTurns, setMaxTurns] = useState(12);
  const [showAdvanced, setShowAdvanced] = useState(false);

  // Model selection sync
  const handleAgentChange = (newAgent: 'anthropic' | 'openai' | 'gemini' | 'grok') => {
    setAgent(newAgent);
    if (newAgent === 'anthropic') setModel('claude-3-7-sonnet');
    if (newAgent === 'openai') setModel('gpt-4o');
    if (newAgent === 'gemini') setModel('gemini-2.5-flash');
    if (newAgent === 'grok') setModel('grok-2-1212');
  };

  const handlePreset = (presetTitle: string, presetPrompt: string, presetRepo: string) => {
    setTitle(presetTitle);
    setPrompt(presetPrompt);
    setRepoUrl(presetRepo);
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!prompt.trim()) return;

    const generatedTitle = title.trim() || prompt.trim().split('\n')[0].slice(0, 40);

    onDispatch({
      title: generatedTitle,
      prompt: prompt.trim(),
      agent,
      model,
      harness,
      repo_url: repoUrl.trim() || undefined,
      repo_ref: repoRef.trim() || undefined,
      timeout_s: timeoutMinutes * 60,
      max_turns: maxTurns,
      source: 'web',
    });
  };

  return (
    <div className="rounded-2xl glass-panel shadow-xl overflow-hidden">
      {/* Header */}
      <div className="border-b border-zinc-200/50 dark:border-white/5 px-6 py-4.5 flex items-center justify-between">
        <div>
          <h2 className="text-base font-bold text-zinc-900 dark:text-white font-display">
            外派任务给云端沙箱 (Delegate Task)
          </h2>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-0.5">
            任务将在隔离 Docker 容器中执行，完成后回传诊断报告、Git Patch 与 /outputs 产物。
          </p>
        </div>

        <button
          onClick={onCancel}
          className="text-xs text-zinc-400 hover:text-zinc-600 dark:hover:text-zinc-200 cursor-pointer"
        >
          取消
        </button>
      </div>

      <form onSubmit={handleSubmit} className="p-6 space-y-5">
        {/* Quick Presets */}
        <div className="space-y-1.5">
          <span className="text-[11px] font-semibold text-zinc-400 uppercase tracking-wider">
            快速预设范例
          </span>
          <div className="flex flex-wrap gap-2">
            {[
              {
                name: '异步死锁与连接泄漏修复',
                title: '修复 Python 异步连接池超时死锁问题',
                prompt: '在高并发请求下，连接池 acquire() 在超时后未能释放底层 socket 锁。请编写复现单元测试，修复 pool.py 锁释放逻辑，并确保所有 pytest 通过。',
                repo: 'https://github.com/acme/pool-service',
              },
              {
                name: 'Playwright Flaky 测试修复',
                title: 'Docker 沙箱内跑 Playwright 端到端测试并定位 Flaky Case',
                prompt: '运行 e2e/checkout_spec.ts，解决由于网络动画延时引起的 locator timeout，重构成显式 waitForResponse 验证机制。',
                repo: 'https://github.com/acme/web-shop',
              },
              {
                name: 'API 规范重构至 Hono/Zod',
                title: '迁移 REST handler 至 Hono 架构并输出 OpenAPI 规范',
                prompt: '将现有路由重构为 Hono 驱动，并将输入输出通过 Zod 进行严格类型约束，在 /outputs 目录中生成 client-types.d.ts。',
                repo: 'https://github.com/acme/api-core',
              },
            ].map((p, idx) => (
              <button
                key={idx}
                type="button"
                onClick={() => handlePreset(p.title, p.prompt, p.repo)}
                className="text-left px-3 py-1.5 text-xs rounded-xl glass-button-secondary cursor-pointer"
              >
                {p.name}
              </button>
            ))}
          </div>
        </div>

        {/* Task Title */}
        <div className="space-y-1.5">
          <label className="block text-xs font-semibold text-zinc-900 dark:text-zinc-200">
            任务标题 (可选)
          </label>
          <input
            type="text"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="简要概括外派任务，留空将自动从 Prompt 提取首行"
            className="w-full px-3.5 py-2 text-xs rounded-xl glass-card text-zinc-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-zinc-400 dark:focus:ring-white/20 transition-all placeholder:text-zinc-400"
          />
        </div>

        {/* Prompt Input */}
        <div className="space-y-1.5">
          <label className="block text-xs font-semibold text-zinc-900 dark:text-zinc-200">
            任务详述 (Prompt) <span className="text-rose-500">*</span>
          </label>
          <textarea
            required
            rows={5}
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            placeholder="详细说明需要云端沙箱 agent 解决的问题、期望的目标、测试命令以及输出产物..."
            className="w-full px-3.5 py-2.5 text-xs font-mono rounded-xl glass-card text-zinc-900 dark:text-white focus:outline-none focus:ring-1 focus:ring-zinc-400 dark:focus:ring-white/20 transition-all leading-relaxed placeholder:text-zinc-400"
          />
        </div>

        {/* Model & Harness Configuration */}
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 pt-1">
          {/* Agent Provider */}
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-zinc-900 dark:text-zinc-200">
              模型提供商 (Provider)
            </label>
            <select
              value={agent}
              onChange={(e) => handleAgentChange(e.target.value as any)}
              className="w-full px-3.5 py-2 text-xs rounded-xl glass-card text-zinc-900 dark:text-white focus:outline-none cursor-pointer"
            >
              <option value="anthropic">Anthropic (Claude)</option>
              <option value="openai">OpenAI (GPT / o3)</option>
              <option value="gemini">Google Gemini</option>
              <option value="grok">xAI Grok</option>
            </select>
          </div>

          {/* Model Name */}
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-zinc-900 dark:text-zinc-200">
              模型规格 (Model)
            </label>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              className="w-full px-3.5 py-2 text-xs font-mono rounded-xl glass-card text-zinc-900 dark:text-white focus:outline-none cursor-pointer"
            >
              {agent === 'anthropic' && (
                <>
                  <option value="claude-3-7-sonnet">claude-3-7-sonnet (推荐)</option>
                  <option value="claude-3-5-sonnet">claude-3-5-sonnet</option>
                  <option value="claude-3-5-haiku">claude-3-5-haiku</option>
                </>
              )}
              {agent === 'openai' && (
                <>
                  <option value="gpt-4o">gpt-4o (推荐)</option>
                  <option value="o3-mini">o3-mini (深度推理)</option>
                  <option value="gpt-4o-mini">gpt-4o-mini</option>
                </>
              )}
              {agent === 'gemini' && (
                <>
                  <option value="gemini-2.5-flash">gemini-2.5-flash (超速)</option>
                  <option value="gemini-2.5-pro">gemini-2.5-pro</option>
                </>
              )}
              {agent === 'grok' && (
                <>
                  <option value="grok-2-1212">grok-2-1212</option>
                  <option value="grok-beta">grok-beta</option>
                </>
              )}
            </select>
          </div>

          {/* Harness */}
          <div className="space-y-1.5">
            <label className="block text-xs font-semibold text-zinc-900 dark:text-zinc-200">
              执行 Harness
            </label>
            <select
              value={harness}
              onChange={(e) => setHarness(e.target.value as any)}
              className="w-full px-3.5 py-2 text-xs font-mono rounded-xl glass-card text-zinc-900 dark:text-white focus:outline-none cursor-pointer"
            >
              <option value="sdk">sdk (默认 Python 闭环工具)</option>
              <option value="claude-code">claude-code (容器化 CLI)</option>
              <option value="codex">codex</option>
              <option value="gemini">gemini</option>
              <option value="grok">grok</option>
              <option value="deepseek">deepseek</option>
            </select>
          </div>
        </div>

        {/* Git Workspace Options */}
        <div className="space-y-1.5">
          <label className="block text-xs font-semibold text-zinc-900 dark:text-zinc-200 flex items-center gap-1.5">
            <GitBranch className="h-3.5 w-3.5 text-zinc-400" />
            <span>目标代码仓库 (Git Repository)</span>
          </label>
          <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
            <input
              type="url"
              value={repoUrl}
              onChange={(e) => setRepoUrl(e.target.value)}
              placeholder="https://github.com/org/repo (可选)"
              className="sm:col-span-3 px-3.5 py-2 text-xs font-mono rounded-xl glass-card text-zinc-900 dark:text-white focus:outline-none"
            />
            <input
              type="text"
              value={repoRef}
              onChange={(e) => setRepoRef(e.target.value)}
              placeholder="main / 分支或 commit"
              className="sm:col-span-1 px-3.5 py-2 text-xs font-mono rounded-xl glass-card text-zinc-900 dark:text-white focus:outline-none"
            />
          </div>
        </div>

        {/* Advanced constraints toggle */}
        <div className="pt-2">
          <button
            type="button"
            onClick={() => setShowAdvanced(!showAdvanced)}
            className="flex items-center gap-1.5 text-xs text-zinc-500 hover:text-zinc-900 dark:text-zinc-400 dark:hover:text-zinc-200 cursor-pointer"
          >
            <Sliders className="h-3.5 w-3.5" />
            <span>{showAdvanced ? '收起高级沙箱限制' : '配置超时时长与轮次上限'}</span>
          </button>

          {showAdvanced && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-3 p-4 rounded-xl glass-card">
              <div className="space-y-1.5">
                <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                  执行超时限制 (Timeout)
                </label>
                <div className="flex gap-2">
                  {[10, 30, 60].map((mins) => (
                    <button
                      key={mins}
                      type="button"
                      onClick={() => setTimeoutMinutes(mins)}
                      className={`px-3 py-1 text-xs rounded-lg transition-all cursor-pointer ${
                        timeoutMinutes === mins
                          ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-950 font-semibold shadow-xs'
                          : 'glass-button-secondary text-zinc-600 dark:text-zinc-400'
                      }`}
                    >
                      {mins} 分钟
                    </button>
                  ))}
                </div>
              </div>

              <div className="space-y-1.5">
                <label className="block text-xs font-semibold text-zinc-700 dark:text-zinc-300">
                  最大自主轮次 (Max Turns)
                </label>
                <div className="flex gap-2">
                  {[8, 12, 20].map((turns) => (
                    <button
                      key={turns}
                      type="button"
                      onClick={() => setMaxTurns(turns)}
                      className={`px-3 py-1 text-xs rounded-lg transition-all cursor-pointer ${
                        maxTurns === turns
                          ? 'bg-zinc-900 text-white dark:bg-white dark:text-zinc-950 font-semibold shadow-xs'
                          : 'glass-button-secondary text-zinc-600 dark:text-zinc-400'
                      }`}
                    >
                      {turns} 轮
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Submit Bar */}
        <div className="flex items-center justify-end gap-3 pt-4 border-t border-zinc-200/50 dark:border-white/5">
          <button
            type="button"
            onClick={onCancel}
            className="px-4 py-2 text-xs font-medium rounded-xl glass-button-secondary cursor-pointer"
          >
            取消
          </button>

          <button
            type="submit"
            className="flex items-center gap-1.5 px-5 py-2 text-xs font-semibold rounded-xl glass-button-primary cursor-pointer"
          >
            <Send className="h-3.5 w-3.5" />
            <span>立即外派至 Docker 沙箱</span>
          </button>
        </div>
      </form>
    </div>
  );
};
