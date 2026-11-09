import React, { useState } from 'react';
import { Copy, Download, Check, FileCode, Split, AlignJustify } from 'lucide-react';
import { parseGitDiff, formatBytes } from '../utils/task-parser';

interface DiffViewerProps {
  rawDiff: string;
  patchBytes?: number;
  taskId: string;
}

export const DiffViewer: React.FC<DiffViewerProps> = ({ rawDiff, patchBytes, taskId }) => {
  const [copied, setCopied] = useState(false);
  const [selectedFileIndex, setSelectedFileIndex] = useState(0);
  const [viewMode, setViewMode] = useState<'unified' | 'split'>('unified');

  const parsed = parseGitDiff(rawDiff);

  if (!rawDiff || parsed.files.length === 0) {
    return (
      <div className="rounded-2xl glass-panel p-8 text-center">
        <p className="text-sm text-zinc-500 dark:text-zinc-400">此任务未产生工作区变更或 Patch 文本为空。</p>
      </div>
    );
  }

  const currentFile = parsed.files[selectedFileIndex] || parsed.files[0];

  const handleCopy = () => {
    navigator.clipboard.writeText(rawDiff);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  const handleDownload = () => {
    const blob = new Blob([rawDiff], { type: 'text/plain;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `delegate-${taskId}.patch`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  };

  return (
    <div className="rounded-2xl glass-panel overflow-hidden">
      {/* Top action & stat bar */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-zinc-200/50 dark:border-white/5 px-4.5 py-3.5 bg-black/[0.02] dark:bg-white/[0.02]">
        <div className="flex items-center gap-3">
          <span className="text-xs font-semibold text-zinc-900 dark:text-white">
            Patch 变更总览
          </span>
          <div className="flex items-center gap-2 text-xs font-mono">
            <span className="text-zinc-500 dark:text-zinc-400">
              {parsed.files.length} 个文件
            </span>
            <span className="text-zinc-300 dark:text-zinc-700">·</span>
            <span className="text-emerald-600 dark:text-emerald-400 font-semibold tabular-nums">
              +{parsed.totalInsertions}
            </span>
            <span className="text-zinc-300 dark:text-zinc-700">/</span>
            <span className="text-rose-600 dark:text-rose-400 font-semibold tabular-nums">
              -{parsed.totalDeletions}
            </span>
            {patchBytes && (
              <>
                <span className="text-zinc-300 dark:text-zinc-700">·</span>
                <span className="text-zinc-500 dark:text-zinc-400">
                  {formatBytes(patchBytes)}
                </span>
              </>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2.5">
          {/* View Mode Switcher: Liquid Segmented */}
          <div className="flex items-center rounded-lg p-0.5 bg-zinc-200/50 dark:bg-white/5 border border-white/20 dark:border-white/5">
            <button
              onClick={() => setViewMode('unified')}
              className={`flex items-center gap-1 px-2.5 py-1 text-[11px] rounded-md transition-all cursor-pointer ${
                viewMode === 'unified'
                  ? 'bg-white text-zinc-950 font-medium shadow-xs dark:bg-zinc-800 dark:text-white'
                  : 'text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200'
              }`}
              title="Unified View"
            >
              <AlignJustify className="h-3 w-3" />
              <span>Unified</span>
            </button>
            <button
              onClick={() => setViewMode('split')}
              className={`flex items-center gap-1 px-2.5 py-1 text-[11px] rounded-md transition-all cursor-pointer ${
                viewMode === 'split'
                  ? 'bg-white text-zinc-950 font-medium shadow-xs dark:bg-zinc-800 dark:text-white'
                  : 'text-zinc-500 hover:text-zinc-800 dark:text-zinc-400 dark:hover:text-zinc-200'
              }`}
              title="Split View"
            >
              <Split className="h-3 w-3" />
              <span>Split</span>
            </button>
          </div>

          <button
            onClick={handleCopy}
            className="flex items-center gap-1 px-3 py-1 text-xs font-medium rounded-lg glass-button-secondary cursor-pointer"
          >
            {copied ? <Check className="h-3.5 w-3.5 text-emerald-500" /> : <Copy className="h-3.5 w-3.5" />}
            <span>{copied ? '已复制' : '复制 Patch'}</span>
          </button>

          <button
            onClick={handleDownload}
            className="flex items-center gap-1 px-3.5 py-1 text-xs font-semibold rounded-lg glass-button-primary cursor-pointer"
          >
            <Download className="h-3.5 w-3.5" />
            <span>下载 .patch</span>
          </button>
        </div>
      </div>

      {/* File Navigation Tabs */}
      {parsed.files.length > 1 && (
        <div className="flex border-b border-zinc-200/50 dark:border-white/5 bg-black/[0.01] dark:bg-black/20 overflow-x-auto">
          {parsed.files.map((file, idx) => (
            <button
              key={idx}
              onClick={() => setSelectedFileIndex(idx)}
              className={`flex items-center gap-2 px-3.5 py-2.5 text-xs font-mono border-r border-zinc-200/50 dark:border-white/5 whitespace-nowrap transition-all cursor-pointer ${
                selectedFileIndex === idx
                  ? 'bg-white/80 text-zinc-950 font-semibold border-b-2 border-b-zinc-900 dark:bg-white/5 dark:text-white dark:border-b-white'
                  : 'text-zinc-500 hover:text-zinc-800 hover:bg-white/40 dark:text-zinc-400 dark:hover:text-zinc-200'
              }`}
            >
              <FileCode className="h-3.5 w-3.5 text-zinc-400" />
              <span>{file.newPath}</span>
              <span className="text-[10px] text-emerald-600 dark:text-emerald-400">+{file.insertions}</span>
              <span className="text-[10px] text-rose-600 dark:text-rose-400">-{file.deletions}</span>
            </button>
          ))}
        </div>
      )}

      {/* Current File Header */}
      <div className="flex items-center justify-between border-b border-zinc-200/50 dark:border-white/5 px-4.5 py-2 text-xs font-mono text-zinc-600 dark:text-zinc-400 bg-black/[0.02] dark:bg-white/[0.02]">
        <div className="flex items-center gap-2 truncate">
          <FileCode className="h-3.5 w-3.5 shrink-0 text-zinc-400" />
          <span className="font-semibold text-zinc-900 dark:text-zinc-200 truncate">{currentFile.newPath}</span>
          {currentFile.oldPath !== currentFile.newPath && (
            <span className="text-zinc-400 text-[11px]">(renamed from {currentFile.oldPath})</span>
          )}
        </div>
        <div className="flex items-center gap-2 shrink-0 text-[11px]">
          <span className="text-emerald-600 dark:text-emerald-400 font-semibold tabular-nums">+{currentFile.insertions}</span>
          <span className="text-rose-600 dark:text-rose-400 font-semibold tabular-nums">-{currentFile.deletions}</span>
        </div>
      </div>

      {/* Code diff lines */}
      <div className="overflow-x-auto font-mono text-xs max-h-[560px] overflow-y-auto leading-5 select-text">
        {currentFile.lines.map((line, idx) => {
          if (line.type === 'header') {
            return (
              <div
                key={idx}
                className="flex items-center px-4 py-1 text-cyan-700 bg-cyan-50/70 dark:text-cyan-400 dark:bg-cyan-950/30 border-y border-cyan-100 dark:border-cyan-900/30 font-semibold text-[11px]"
              >
                {line.text}
              </div>
            );
          }

          const isAdd = line.type === 'add';
          const isDel = line.type === 'del';

          return (
            <div
              key={idx}
              className={`flex items-start hover:bg-black/5 dark:hover:bg-white/5 transition-colors ${
                isAdd
                  ? 'bg-emerald-500/10 text-emerald-950 dark:text-emerald-200 dark:bg-emerald-950/30'
                  : isDel
                  ? 'bg-rose-500/10 text-rose-950 dark:text-rose-200 dark:bg-rose-950/30'
                  : 'text-zinc-800 dark:text-zinc-300'
              }`}
            >
              {/* Line numbers */}
              <div className="flex w-16 shrink-0 select-none border-r border-zinc-200/50 dark:border-white/5 text-zinc-400 dark:text-zinc-600 text-right pr-2 text-[10px] tabular-nums">
                <span className="w-8">{line.oldLineNumber ?? ''}</span>
                <span className="w-8">{line.newLineNumber ?? ''}</span>
              </div>

              {/* Marker +/- */}
              <div
                className={`w-5 shrink-0 text-center select-none font-bold ${
                  isAdd
                    ? 'text-emerald-600 dark:text-emerald-400'
                    : isDel
                    ? 'text-rose-600 dark:text-rose-400'
                    : 'text-zinc-400'
                }`}
              >
                {isAdd ? '+' : isDel ? '-' : ' '}
              </div>

              {/* Line content */}
              <div className="flex-1 whitespace-pre pr-4 pl-1 font-mono">{line.text || ' '}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
