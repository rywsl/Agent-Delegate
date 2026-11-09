import React, { useState } from 'react';
import { Plus, Copy, Check } from 'lucide-react';
import { ApiKeyItem } from '../types/delegate';
import { generateMcpCommand } from '../utils/task-parser';

interface ApiKeysViewProps {
  keys: ApiKeyItem[];
  onCreateKey: (name: string) => void;
  onRevokeKey: (id: number) => void;
  newlyCreatedToken: string | null;
  onClearNewToken: () => void;
}

export const ApiKeysView: React.FC<ApiKeysViewProps> = ({
  keys,
  onCreateKey,
  onRevokeKey,
  newlyCreatedToken,
  onClearNewToken,
}) => {
  const [keyName, setKeyName] = useState('');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [copiedToken, setCopiedToken] = useState(false);
  const [copiedCmd, setCopiedCmd] = useState<number | null>(null);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!keyName.trim()) return;
    onCreateKey(keyName.trim());
    setKeyName('');
    setShowCreateModal(false);
  };

  const handleCopyNewToken = () => {
    if (!newlyCreatedToken) return;
    navigator.clipboard.writeText(newlyCreatedToken);
    setCopiedToken(true);
    setTimeout(() => setCopiedToken(false), 2000);
  };

  const handleCopyMcp = (key: ApiKeyItem) => {
    const appUrl = window.location.origin;
    const cmd = generateMcpCommand(appUrl, `${key.prefix}••••••••`);
    navigator.clipboard.writeText(cmd);
    setCopiedCmd(key.id);
    setTimeout(() => setCopiedCmd(null), 2000);
  };

  return (
    <div className="space-y-5 max-w-5xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100 tracking-tight">
            API 密钥
          </h1>
          <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">
            用于本地客户端访问沙箱接口的鉴权凭证。
          </p>
        </div>

        <button
          onClick={() => setShowCreateModal(true)}
          className="flex items-center gap-1.5 px-3.5 py-1.5 text-xs font-medium rounded-lg glass-button-primary cursor-pointer"
        >
          <Plus className="h-3.5 w-3.5" />
          <span>创建密钥</span>
        </button>
      </div>

      {newlyCreatedToken && (
        <div className="rounded-xl border border-zinc-300 dark:border-zinc-700 bg-zinc-50 dark:bg-zinc-900 p-4 space-y-3">
          <div className="flex items-center justify-between text-xs">
            <span className="font-medium text-zinc-900 dark:text-zinc-100">
              新密钥已生成，请立即复制保存
            </span>
            <button
              onClick={onClearNewToken}
              className="text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200 underline cursor-pointer"
            >
              关闭
            </button>
          </div>

          <div className="flex items-center gap-2">
            <input
              type="text"
              readOnly
              value={newlyCreatedToken}
              className="flex-1 font-mono text-xs px-3 py-1.5 rounded-lg border border-zinc-200 dark:border-zinc-800 bg-white dark:bg-black text-zinc-900 dark:text-zinc-100 select-all focus:outline-none"
            />
            <button
              onClick={handleCopyNewToken}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium rounded-lg glass-button-primary cursor-pointer"
            >
              {copiedToken ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
              <span>{copiedToken ? '已复制' : '复制'}</span>
            </button>
          </div>
        </div>
      )}

      <div className="rounded-xl glass-panel overflow-x-auto">
        <table className="w-full text-left text-xs min-w-[600px]">
          <thead className="border-b border-zinc-200 dark:border-zinc-800 text-zinc-500 dark:text-zinc-400 font-medium">
            <tr>
              <th className="px-4 py-3">名称</th>
              <th className="px-4 py-3">前缀</th>
              <th className="px-4 py-3">创建时间</th>
              <th className="px-4 py-3">最近使用</th>
              <th className="px-4 py-3">状态</th>
              <th className="px-4 py-3 text-right">操作</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-100 dark:divide-zinc-800/80 font-mono">
            {keys.map((k) => (
              <tr key={k.id} className="hover:bg-zinc-50/80 dark:hover:bg-zinc-900/40 transition-colors">
                <td className="px-4 py-3 font-sans font-medium text-zinc-900 dark:text-zinc-100">
                  {k.name}
                </td>
                <td className="px-4 py-3 text-zinc-600 dark:text-zinc-300">
                  {k.prefix}…
                </td>
                <td className="px-4 py-3 text-zinc-500 dark:text-zinc-400">
                  {k.created_at}
                </td>
                <td className="px-4 py-3 text-zinc-500 dark:text-zinc-400">
                  {k.last_used_at || '未使用'}
                </td>
                <td className="px-4 py-3 font-sans">
                  <span className="px-2 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 text-[11px]">
                    {k.active ? '有效' : '已撤销'}
                  </span>
                </td>
                <td className="px-4 py-3 text-right space-x-2 font-sans">
                  {k.active && (
                    <button
                      onClick={() => handleCopyMcp(k)}
                      className="px-2.5 py-1 text-xs rounded-md glass-button-secondary cursor-pointer"
                    >
                      {copiedCmd === k.id ? '已复制' : '复制配置'}
                    </button>
                  )}

                  {k.active && (
                    <button
                      onClick={() => onRevokeKey(k.id)}
                      className="px-2.5 py-1 text-xs rounded-md text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-100 transition-colors cursor-pointer"
                    >
                      撤销
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {showCreateModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-md rounded-xl glass-panel p-5 space-y-4">
            <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">
              新建 API 密钥
            </h2>

            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-xs text-zinc-600 dark:text-zinc-400 mb-1.5">
                  名称
                </label>
                <input
                  type="text"
                  required
                  autoFocus
                  value={keyName}
                  onChange={(e) => setKeyName(e.target.value)}
                  placeholder="例如: Workstation"
                  className="w-full px-3 py-1.5 text-xs rounded-lg glass-card text-zinc-900 dark:text-zinc-100 focus:outline-none"
                />
              </div>

              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setShowCreateModal(false)}
                  className="px-3.5 py-1.5 text-xs rounded-lg glass-button-secondary cursor-pointer"
                >
                  取消
                </button>
                <button
                  type="submit"
                  className="px-3.5 py-1.5 text-xs font-medium rounded-lg glass-button-primary cursor-pointer"
                >
                  生成
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
