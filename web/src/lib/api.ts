export type User = {
  id: number;
  email: string;
  display_name: string;
  is_admin: boolean;
  balance_usd: number | null;
  points: number;
  sandbox_free_seconds: number;
  billing_mode: string;
};

export type Session = {
  csrf: string;
  user: User | null;
  allow_registration: boolean;
  agents: { id: string; label: string; provider: string }[];
  models: Record<string, string[]>;
  options: { agent: string; model: string; budget_quota: number; timeout_s: number; max_turns: number } | null;
  sandbox_usd_per_minute: number | null;
  sandbox_points_per_minute: number | null;
  points_per_usd: number | null;
};

let csrf = '';

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  headers.set('Accept', 'application/json');
  if (init.body && !headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
  if (csrf && init.method && init.method !== 'GET') headers.set('X-CSRF-Token', csrf);
  const response = await fetch(path, { ...init, headers, credentials: 'same-origin' });
  const data = await response.json().catch(() => ({}));
  if (data && typeof data === 'object' && 'csrf' in data && typeof data.csrf === 'string') csrf = data.csrf;
  if (!response.ok) {
    const detail = (data as { detail?: string }).detail || response.statusText;
    throw new ApiError(response.status, detail);
  }
  return data as T;
}

export function loadSession() {
  return api<Session>('/api/console/session');
}
