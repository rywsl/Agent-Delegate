import React, { useState } from 'react';
import { Search, ChevronDown, ChevronRight } from 'lucide-react';
import { AuditRecord } from '../types/delegate';

interface AuditViewProps {
  logs: AuditRecord[];
}

export const AuditView: React.FC<AuditViewProps> = ({ logs }) => {
  const [searchTerm, setSearchTerm] = useState('');
  const [expandedRow, setExpandedRow] = useState<string | null>(null);

  const filteredLogs = logs.filter(
    (l) =>
      l.action.toLowerCase().includes(searchTerm.toLowerCase()) ||
      l.actor.toLowerCase().includes(searchTerm.toLowerCase()) ||
      l.ip.includes(searchTerm) ||
      JSON.stringify(l.detail).toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="space-y-5 max-w-5xl">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100 tracking-tight">
            审计
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">
            操作记录与任务调用留痕。
          </p>
        </div>

        <div className="relative w-full sm:w-60">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-zinc-400" />
          <input
            type="text"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            placeholder="搜索审计记录..."
            className="w-full pl-8 pr-3 py-1.5 text-xs rounded-lg glass-card text-zinc-900 dark:text-zinc-100 focus:outline-none placeholder:text-zinc-400"
          />
        </div>
      </div>

      <div className="rounded-xl glass-panel overflow-x-auto">
        <table className="w-full text-left text-xs font-mono min-w-[640px]">
          <thead className="border-b border-zinc-200 dark:border-zinc-800 text-zinc-500 dark:text-zinc-400 font-medium font-sans">
            <tr>
              <th className="px-4 py-3">时间</th>
              <th className="px-4 py-3">事件</th>
              <th className="px-4 py-3">操作者</th>
              <th className="px-4 py-3">IP</th>
              <th className="px-4 py-3">详情</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/80">
            {filteredLogs.map((log) => {
              const isExpanded = expandedRow === log.id;

              return (
                <React.Fragment key={log.id}>
                  <tr
                    onClick={() => setExpandedRow(isExpanded ? null : log.id)}
                    className="hover:bg-zinc-50/80 dark:hover:bg-zinc-900/40 cursor-pointer transition-colors"
                  >
                    <td className="px-4 py-3 text-zinc-500 dark:text-zinc-400 tabular-nums whitespace-nowrap">
                      {log.ts}
                    </td>
                    <td className="px-4 py-3 text-zinc-900 dark:text-zinc-100 font-medium">
                      {log.action}
                    </td>
                    <td className="px-4 py-3 text-zinc-600 dark:text-zinc-300">
                      {log.actor}
                    </td>
                    <td className="px-4 py-3 text-zinc-500 dark:text-zinc-400">
                      {log.ip}
                    </td>
                    <td className="px-4 py-3 max-w-xs truncate text-zinc-500 dark:text-zinc-400">
                      <div className="flex items-center justify-between">
                        <span className="truncate">{JSON.stringify(log.detail)}</span>
                        {isExpanded ? (
                          <ChevronDown className="h-3.5 w-3.5 shrink-0 text-zinc-400 ml-2" />
                        ) : (
                          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-zinc-400 ml-2" />
                        )}
                      </div>
                    </td>
                  </tr>

                  {isExpanded && (
                    <tr className="bg-zinc-50 dark:bg-black/50">
                      <td colSpan={5} className="px-4 py-3">
                        <pre className="text-[11px] p-3 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-black text-zinc-800 dark:text-zinc-200 overflow-x-auto">
                          {JSON.stringify(log.detail, null, 2)}
                        </pre>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};
