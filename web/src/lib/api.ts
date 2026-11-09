export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

let csrf = '';

export function currentCsrf() {
  return csrf;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('Accept', 'application/json');
  if (init.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json');
  }
  const method = (init.method || 'GET').toUpperCase();
  if (method !== 'GET' && method !== 'HEAD' && csrf) {
    headers.set('X-CSRF-Token', csrf);
  }
  const response = await fetch(path, { ...init, headers, credentials: 'include' });
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (data && typeof data.csrf === 'string') {
    csrf = data.csrf;
  }
  if (!response.ok) {
    throw new ApiError(response.status, data.detail || response.statusText);
  }
  return data as T;
}

export interface SessionUser {
  id: number;
  email: string;
  display_name: string;
  is_admin: boolean;
  initials: string;
}

export interface ExecOptions {
  agent: string;
  model: string;
  sandbox: string;
  harness: string;
  timeout_s: number;
  max_turns: number;
}

export interface ConsoleOptions {
  current?: ExecOptions;
  agents?: string[];
  sandboxes?: string[];
  harnesses?: string[];
  models?: Record<string, string[]>;
  mcp_url?: string;
  public_url?: string;
  allow_registration?: boolean;
  sandbox?: {
    memory: string;
    cpus: number;
    pids: number;
    network: string;
    capacity: number;
    uid: number;
    image: string;
  };
}

export interface SessionPayload {
  csrf: string;
  user: SessionUser | null;
  options: ConsoleOptions;
  message?: string;
}

export const api = {
  session: () => request<SessionPayload>('/api/console/session'),
  login: (email: string, password: string) =>
    request<SessionPayload>('/api/console/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  register: (email: string, password: string, display_name: string) =>
    request<SessionPayload>('/api/console/register', {
      method: 'POST',
      body: JSON.stringify({ email, password, display_name }),
    }),
  logout: () => request<SessionPayload>('/api/console/logout', { method: 'POST', body: '{}' }),
  dashboard: () => request<Record<string, unknown>>('/api/console/dashboard'),
  tasks: () => request<{ tasks: Record<string, unknown>[] }>('/api/console/tasks'),
  task: (id: string) => request<Record<string, unknown>>(`/api/console/tasks/${id}`),
  createTask: (body: { task: string; title?: string; harness?: string; model?: string; agent?: string }) =>
    request<Record<string, unknown>>('/api/console/tasks', { method: 'POST', body: JSON.stringify(body) }),
  taskEvents: (id: string, after = 0) =>
    request<Record<string, unknown>>(`/api/console/tasks/${id}/events?after=${after}`),
  cancelTask: (id: string) =>
    request<Record<string, unknown>>(`/api/console/tasks/${id}/cancel`, { method: 'POST', body: '{}' }),
  saveSettings: (body: { agent?: string; model?: string; sandbox?: string; harness?: string }) =>
    request<SessionPayload>('/api/console/settings', { method: 'POST', body: JSON.stringify(body) }),
  keys: () => request<{ keys: Record<string, unknown>[] }>('/api/console/keys'),
  createKey: (name: string) =>
    request<{ token: string; key: Record<string, unknown> }>('/api/console/keys', {
      method: 'POST',
      body: JSON.stringify({ name }),
    }),
  revokeKey: (id: number) =>
    request<{ key: Record<string, unknown> }>(`/api/console/keys/${id}/revoke`, { method: 'POST', body: '{}' }),
  providers: () => request<{ providers: Record<string, unknown>[]; can_edit: boolean }>('/api/console/providers'),
  saveProvider: (id: string, body: { base_url: string; api_key?: string; clear_api_key?: boolean; enabled?: boolean }) =>
    request<{ providers: Record<string, unknown>[] }>(`/api/console/providers/${id}`, {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  checkProvider: (id: string) =>
    request<{ ok: boolean; message: string }>(`/api/console/providers/${id}/check`, { method: 'POST', body: '{}' }),
  audit: () => request<{ logs: Record<string, unknown>[] }>('/api/console/audit'),
};
