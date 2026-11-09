import React from 'react';
import { api } from '../lib/api';

export function BillingView({ reload }: { reload: () => Promise<void> }) {
  const [code, setCode] = React.useState('');
  const [message, setMessage] = React.useState('');
  const [logs, setLogs] = React.useState<{ time: number; model: string; input_tokens: number; output_tokens: number; cost_usd: number; content: string }[]>([]);

  React.useEffect(() => {
    api<{ logs: typeof logs }>('/api/console/billing').then((data) => setLogs(data.logs)).catch(() => setLogs([]));
  }, []);

  return (
    <div className="max-w-5xl space-y-5">
      <div>
        <h1 className="text-xl font-semibold tracking-tight text-zinc-900 dark:text-zinc-100">账单</h1>
        <p className="mt-1 text-xs text-zinc-500">平台模型费走网关流水。自带密钥的任务只记沙箱时间。</p>
      </div>
      <div className="rounded-xl glass-panel p-5">
        <div className="flex flex-wrap gap-2">
          <input value={code} onChange={(event) => setCode(event.target.value)} placeholder="DLG-..."
            className="min-w-48 flex-1 rounded-lg border border-zinc-200 bg-transparent px-3 py-1.5 font-mono text-xs dark:border-zinc-800" />
          <button className="rounded-lg glass-button-primary px-3.5 py-1.5 text-xs font-medium" onClick={async () => {
            try {
              const result = await api<{ credited_usd: number }>('/api/console/billing/redeem', { method: 'POST', body: JSON.stringify({ code }) });
              setMessage(`已入账 ${result.credited_usd} USD`);
              setCode('');
              await reload();
            } catch (err) {
              setMessage(err instanceof Error ? err.message : '兑换失败');
            }
          }}>兑换</button>
        </div>
        {message && <p className="mt-2 text-xs">{message}</p>}
      </div>
      <div className="overflow-x-auto rounded-xl glass-panel">
        <table className="w-full min-w-[640px] text-left text-xs">
          <thead className="border-b border-zinc-200 font-medium text-zinc-500 dark:border-zinc-800">
            <tr>
              <th className="px-4 py-3">模型</th>
              <th className="px-4 py-3">输入</th>
              <th className="px-4 py-3">输出</th>
              <th className="px-4 py-3">费用</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100 font-mono dark:divide-zinc-800/80">
            {logs.map((row, index) => (
              <tr key={index}>
                <td className="px-4 py-3 font-sans">{row.model || row.content || '—'}</td>
                <td className="px-4 py-3">{row.input_tokens}</td>
                <td className="px-4 py-3">{row.output_tokens}</td>
                <td className="px-4 py-3">${row.cost_usd}</td>
              </tr>
            ))}
            {!logs.length && <tr><td className="px-4 py-8 text-center text-zinc-400" colSpan={4}>没有流水。</td></tr>}
          </tbody>
        </table>
      </div>
    </div>
  );
}
