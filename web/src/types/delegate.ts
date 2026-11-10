export type TaskStatus =
  | 'queued'
  | 'preparing'
  | 'running'
  | 'succeeded'
  | 'failed'
  | 'cancelled'
  | 'timeout';

export interface SandboxLimits {
  memory: string;
  cpus: string;
  pids: number;
  network: string;
}

export interface Attachment {
  path: string;
  size: number;
  sha256: string;
}

export interface OutputFile {
  path: string;
  size: number;
  sha256?: string;
  downloadUrl?: string;
}

export interface PatchStats {
  files: number;
  insertions: number;
  deletions: number;
  bytes: number;
  paths: string[];
}

export interface AgentUsage {
  agent: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  turns: number;
  reported_cost_usd?: number;
}

export interface NormEvent {
  id: string;
  ts: string;
  kind: 'runner' | 'stderr' | 'turn' | 'thinking' | 'tool_call' | 'tool_result' | 'message' | 'finish' | 'log';
  summary: string;
  phase?: string;
  tool_name?: string;
  tool_args?: Record<string, unknown> | string;
  tool_result?: string;
  data?: Record<string, unknown>;
}

export interface Task {
  id: string;
  title: string;
  prompt: string;
  source: 'mcp' | 'api' | 'web' | 'tui-cli';
  status: TaskStatus;
  status_reason?: string;
  client_info?: {
    client?: string;
    ip?: string;
    version?: string;
  };
  agent: string;
  model: string;
  sandbox: string;
  harness: string;
  timeout_s: number;
  max_turns: number;
  created_at: string;
  started_at?: string;
  finished_at?: string;
  duration_s?: number;
  repo_url?: string;
  repo_ref?: string;
  container_id?: string;
  container_name?: string;
  sandbox_image?: string;
  sandbox_limits?: SandboxLimits;
  exit_code?: number | null;
  result_text?: string;
  raw_patch?: string;
  patch_stats?: PatchStats;
  outputs?: OutputFile[];
  agent_usage?: AgentUsage;
  sandbox_points?: number;
  events?: NormEvent[];
  event_count?: number;
  api_key_prefix?: string;
  api_key_name?: string;
}

export interface ApiKeyItem {
  id: number;
  name: string;
  prefix: string;
  token?: string; // only visible right after creation
  created_at: string;
  last_used_at?: string | null;
  last_used_ip?: string | null;
  active: boolean;
}

export interface ProviderItem {
  id: string;
  name: string;
  pythonPackage: string;
  envKeyVar: string;
  envBaseUrlVar: string;
  configured: boolean;
  apiKey?: string;
  apiKeyMasked?: string;
  baseUrl?: string;
  models: string[];
  defaultModel: string;
}

export interface AuditRecord {
  id: string;
  ts: string;
  action: string;
  actor: string;
  ip: string;
  detail: Record<string, unknown>;
}
