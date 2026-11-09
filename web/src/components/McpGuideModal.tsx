import React, { useState } from 'react';
import { Copy, Check } from 'lucide-react';

interface McpGuideModalProps {
  onClose?: () => void;
  activeKeyPrefix?: string;
}

export const McpGuideModal: React.FC<McpGuideModalProps> = ({ activeKeyPrefix = 'dlg_9a2b' }) => {
  const [copiedStep, setCopiedStep] = useState<number | null>(null);

  const serverUrl = window.location.origin;
  const cliAddCmd = `claude mcp add --transport http delegate ${serverUrl}/mcp 
  --header "Authorization: Bearer ${activeKeyPrefix}••••••••"`;

  const mcpJsonContent = JSON.stringify(
    {
      mcpServers: {
        delegate: {
          url: `${serverUrl}/mcp`,
          headers: {
            Authorization: `Bearer ${activeKeyPrefix}...`,
          },
        },
      },
    },
    null,
    2
  );

  const copyToClipboard = (text: string, step: number) => {
    navigator.clipboard.writeText(text);
    setCopiedStep(step);
    setTimeout(() => setCopiedStep(null), 2000);
  };

  return (
    <div className="space-y-5 max-w-4xl">
      <div>
        <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-100 tracking-tight">
          MCP 接入
        </h1>
        <p className="text-xs text-zinc-500 dark:text-zinc-400 mt-1">
          通过 HTTP 传输协议将本地客户端连接至沙箱服务。
        </p>
      </div>

      <div className="rounded-xl glass-panel p-5 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-medium text-zinc-900 dark:text-zinc-100">
            命令行接入
          </h3>
          <button
            onClick={() => copyToClipboard(cliAddCmd, 1)}
            className="flex items-center gap-1 px-2.5 py-1 text-xs rounded-md glass-button-secondary cursor-pointer"
          >
            {copiedStep === 1 ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
            <span>{copiedStep === 1 ? '已复制' : '复制'}</span>
          </button>
        </div>

        <pre className="p-3 rounded-lg bg-zinc-50 dark:bg-black font-mono text-xs border border-zinc-200 dark:border-zinc-800 overflow-x-auto text-zinc-800 dark:text-zinc-200 leading-relaxed">
          {cliAddCmd}
        </pre>
      </div>

      <div className="rounded-xl glass-panel p-5 space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-medium text-zinc-900 dark:text-zinc-100">
            mcp.json 配置文件
          </h3>
          <button
            onClick={() => copyToClipboard(mcpJsonContent, 2)}
            className="flex items-center gap-1 px-2.5 py-1 text-xs rounded-md glass-button-secondary cursor-pointer"
          >
            {copiedStep === 2 ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
            <span>{copiedStep === 2 ? '已复制' : '复制'}</span>
          </button>
        </div>

        <pre className="p-3 rounded-lg bg-zinc-50 dark:bg-black font-mono text-xs border border-zinc-200 dark:border-zinc-800 overflow-x-auto text-zinc-800 dark:text-zinc-200 leading-relaxed">
          {mcpJsonContent}
        </pre>
      </div>
    </div>
  );
};
