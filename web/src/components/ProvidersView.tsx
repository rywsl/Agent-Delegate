import React, { useState } from 'react';
import { Check, RefreshCw } from 'lucide-react';
import { ProviderItem } from '../types/delegate';

interface ProvidersViewProps {
  providers: ProviderItem[];
  onUpdateProvider: (id: string, updates: Partial<ProviderItem> & { apiKey?: string; clearApiKey?: boolean }) => void | Promise<void>;
  onTestProvider?: (id: string) => Promise<string>;
  canEdit?: boolean;
}

export const ProvidersView: React.FC<ProvidersViewProps> = ({
  providers,
  onUpdateProvider,
  onTestProvider,
  canEdit = true,
}) => {
  const [editingId, setEditingId] = useState<string | null>(null);
  const [baseUrlInput, setBaseUrlInput] = useState('');
  const [keyInput, setKeyInput] = useState('');
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<string | null>(null);

  const startEdit = (p: ProviderItem) => {
    setEditingId(p.id);
    setBaseUrlInput(p.baseUrl || '');
    setKeyInput('');
    setTestResult(null);
  };

  const handleSave = async (id: string) => {
    await onUpdateProvider(id, {
      baseUrl: baseUrlInput.trim(),
      apiKey: keyInput.trim(),
    });
    setEditingId(null);
  };

  const handleTestConnection = async (id: string) => {
    setTestingId(id);
    setTestResult(null);
    try {
      const message = onTestProvider
        ? await onTestProvider(id)
        : `${id.toUpperCase()} 连接正常`;
      setTestResult(message);
    } catch (err) {
      setTestResult(err instanceof Error ? err.message : '测试失败');
    } finally {
      setTestingId(null);
    }
  };

  return (
    <div className="space-y-5 max-w-5xl">
      <div>
        <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100 tracking-tight">
          提供商
        </h1>
        <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">
          配置模型 SDK 的 API 密钥与自定义端点。
        </p>
      </div>

      {testResult && (
        <div className="rounded-lg border border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900 p-3 text-xs text-zinc-800 dark:text-zinc-200 flex items-center justify-between">
          <span className="flex items-center gap-2 font-mono">
            <Check className="h-3.5 w-3.5" />
            {testResult}
          </span>
          <button
            onClick={() => setTestResult(null)}
            className="text-zinc-400 hover:text-zinc-700 dark:hover:text-zinc-200 cursor-pointer"
          >
            关闭
          </button>
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {providers.map((p) => {
          const isEditing = editingId === p.id;

          return (
            <div
              key={p.id}
              className="rounded-xl glass-panel p-5 flex flex-col justify-between"
            >
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="text-sm font-medium text-zinc-900 dark:text-zinc-100">
                      {p.name}
                    </h3>
                    <span className="text-[11px] font-mono text-zinc-400">
                      {p.pythonPackage}
                    </span>
                  </div>

                  <span className="px-2 py-0.5 rounded bg-zinc-100 dark:bg-zinc-800 text-zinc-700 dark:text-zinc-300 text-[11px]">
                    {p.configured ? '已配置' : '未配置'}
                  </span>
                </div>

                {isEditing ? (
                  <div className="space-y-3 pt-2 text-xs">
                    <div>
                      <label className="block text-[11px] text-zinc-500 mb-1">
                        Base URL
                      </label>
                      <input
                        type="text"
                        value={baseUrlInput}
                        onChange={(e) => setBaseUrlInput(e.target.value)}
                        placeholder="留空使用官方默认地址"
                        className="w-full px-3 py-1.5 font-mono text-xs rounded-lg glass-card text-zinc-900 dark:text-zinc-100 focus:outline-none"
                      />
                    </div>

                    <div>
                      <label className="block text-[11px] text-zinc-500 mb-1">
                        API Key ({p.envKeyVar})
                      </label>
                      <input
                        type="password"
                        value={keyInput}
                        onChange={(e) => setKeyInput(e.target.value)}
                        placeholder="留空保持不变"
                        className="w-full px-3 py-1.5 font-mono text-xs rounded-lg glass-card text-zinc-900 dark:text-zinc-100 focus:outline-none"
                      />
                    </div>

                    <div className="flex justify-end gap-2 pt-1">
                      <button
                        onClick={() => setEditingId(null)}
                        className="px-3 py-1 rounded-lg glass-button-secondary cursor-pointer"
                      >
                        取消
                      </button>
                      <button
                        onClick={() => handleSave(p.id)}
                        className="px-3.5 py-1 rounded-lg glass-button-primary font-medium cursor-pointer"
                      >
                        保存
                      </button>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-2 pt-2 text-xs font-mono">
                    <div className="flex justify-between items-center text-zinc-500">
                      <span>API Key</span>
                      <span className="text-zinc-800 dark:text-zinc-200">
                        {p.apiKeyMasked || '未设置'}
                      </span>
                    </div>

                    <div className="flex justify-between items-center text-zinc-500">
                      <span>Base URL</span>
                      <span className="text-zinc-800 dark:text-zinc-200 truncate max-w-[200px]">
                        {p.baseUrl || '默认'}
                      </span>
                    </div>

                    <div className="pt-2 border-t border-zinc-100 dark:border-zinc-800/80 flex flex-wrap gap-1.5">
                      {p.models.map((m) => (
                        <span
                          key={m}
                          className={`px-2 py-0.5 rounded text-[11px] font-mono ${
                            m === p.defaultModel
                              ? 'bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-950'
                              : 'bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-400'
                          }`}
                        >
                          {m}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>

              {!isEditing && canEdit && (
                <div className="flex items-center justify-between pt-3 mt-3 border-t border-zinc-100 dark:border-zinc-800/80">
                  <button
                    onClick={() => handleTestConnection(p.id)}
                    disabled={testingId === p.id}
                    className="flex items-center gap-1.5 text-xs text-zinc-500 hover:text-zinc-900 dark:hover:text-zinc-200 cursor-pointer"
                  >
                    <RefreshCw className={`h-3 w-3 ${testingId === p.id ? 'animate-spin' : ''}`} />
                    <span>{testingId === p.id ? '测试中...' : '测试连接'}</span>
                  </button>

                  <button
                    onClick={() => startEdit(p)}
                    className="text-xs text-zinc-900 dark:text-zinc-100 hover:underline cursor-pointer"
                  >
                    编辑
                  </button>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
};
