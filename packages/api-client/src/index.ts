/**
 * Typed client for the MarketingOS API (/api/v1). Used by the web app and the mobile app.
 * Every request carries the bearer token and the selected workspace (tenant) id.
 */

export class ApiError extends Error {
  status: number;
  code: string;
  details: Record<string, unknown>;

  constructor(status: number, code: string, message: string, details: Record<string, unknown> = {}) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

export interface ClientOptions {
  baseUrl: string;
  getAccessToken: () => string | null;
  getWorkspaceId: () => string | null;
  /** Called once on a 401; return true if a new access token is now available. */
  refresh?: () => Promise<boolean>;
  onUnauthorized?: () => void;
}

export type Query = Record<string, string | number | boolean | null | undefined>;

export function createApiClient(opts: ClientOptions) {
  const base = opts.baseUrl.replace(/\/$/, "");

  function url(path: string, query?: Query) {
    const u = `${base}/api/v1${path}`;
    if (!query) return u;
    const params = Object.entries(query)
      .filter(([, v]) => v !== undefined && v !== null && v !== "")
      .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(String(v))}`);
    return params.length ? `${u}${u.includes("?") ? "&" : "?"}${params.join("&")}` : u;
  }

  function headers(extra?: Record<string, string>, workspaceId?: string | null) {
    const h: Record<string, string> = { ...extra };
    const token = opts.getAccessToken();
    const ws = workspaceId ?? opts.getWorkspaceId();
    if (token) h.Authorization = `Bearer ${token}`;
    if (ws) h["X-Workspace-Id"] = ws;
    return h;
  }

  async function send(method: string, path: string, init: { body?: BodyInit; json?: unknown; query?: Query; workspaceId?: string | null }, retried = false): Promise<Response> {
    const extra: Record<string, string> = {};
    let body = init.body;
    if (init.json !== undefined) {
      extra["Content-Type"] = "application/json";
      body = JSON.stringify(init.json);
    }
    const res = await fetch(url(path, init.query), { method, headers: headers(extra, init.workspaceId), body });
    if (res.status === 401 && !retried && opts.refresh && !path.startsWith("/auth/")) {
      if (await opts.refresh()) return send(method, path, init, true);
      opts.onUnauthorized?.();
    }
    if (!res.ok) {
      let code = "error";
      let message = `Request failed (${res.status})`;
      let details: Record<string, unknown> = {};
      try {
        const data = await res.json();
        code = data?.error?.code ?? code;
        message = data?.error?.message ?? message;
        details = data?.error?.details ?? {};
      } catch {
        /* non-JSON error body */
      }
      throw new ApiError(res.status, code, message, details);
    }
    return res;
  }

  async function json<T>(method: string, path: string, init: { json?: unknown; query?: Query; body?: BodyInit; workspaceId?: string | null } = {}): Promise<T> {
    const res = await send(method, path, init);
    if (res.status === 204) return undefined as T;
    return (await res.json()) as T;
  }

  return {
    url,
    get: <T>(path: string, query?: Query, workspaceId?: string | null) => json<T>("GET", path, { query, workspaceId }),
    post: <T>(path: string, body?: unknown, query?: Query) => json<T>("POST", path, { json: body ?? {}, query }),
    patch: <T>(path: string, body?: unknown) => json<T>("PATCH", path, { json: body ?? {} }),
    del: <T = void>(path: string) => json<T>("DELETE", path),
    upload: <T>(path: string, form: FormData) => json<T>("POST", path, { body: form }),
    /** Fetch a binary/text response (exports, reports) with auth headers. */
    blob: async (path: string, method = "GET", query?: Query) => (await send(method, path, { query })).blob(),
  };
}

export type ApiClient = ReturnType<typeof createApiClient>;

// ---- domain types (subset of the API's responses) --------------------------------------

export type Role =
  | "agency_owner" | "administrator" | "account_manager" | "marketing_manager"
  | "content_creator" | "analyst" | "client_approver" | "viewer";

export interface WorkspaceRef {
  id: string;
  name: string;
  kind: "business" | "agency" | "client";
  role: Role;
  organization_id: string;
  currency: string;
}

export interface User {
  id: string;
  email: string;
  full_name: string;
  email_verified: boolean;
  mfa_enabled: boolean;
  onboarding_completed: boolean;
  onboarding_state: Record<string, unknown>;
  workspaces: WorkspaceRef[];
}

export interface Session {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  user: User;
}

export interface WorkspaceDetail extends WorkspaceRef {
  timezone: string;
  industry: string | null;
  status: string;
  role_label: string;
  permissions: string[];
  settings: {
    approvals: { allow_self_approval: boolean; require_approval_for_pause: boolean; require_approval_for_budget_decrease: boolean };
    spend_limits: Record<string, number>;
    agents?: { disabled: string[] };
  };
  action_policies: Record<string, string>;
  credit_balance: number;
  plan: { code: string; name: string; limits: Record<string, number> } | null;
  client_id: string | null;
}

export type Provenance = "measured" | "calculated" | "internal" | "estimate";

export interface Kpi {
  value: number | null;
  previous: number | null;
  change_pct: number | null;
  kind: Provenance;
  sources: string[];
  unit: "count" | "money" | "ratio" | "score";
  lower_is_better: boolean;
}

export interface Approval {
  id: string;
  action_type: string;
  action_label: string;
  resource_type: string;
  resource_id: string;
  title: string;
  platform: string | null;
  status: string;
  budget_impact_minor: number | null;
  currency: string | null;
  ai_reasoning: string | null;
  expected_outcome: string | null;
  requested_by: string | null;
  requested_by_agent: string | null;
  decided_by: string | null;
  decided_at: string | null;
  decision_note: string | null;
  group_id: string | null;
  created_at: string;
  client: string | null;
  can_decide?: boolean;
  preview?: Record<string, any> | null;
  payload?: Record<string, any>;
}

export interface ContentAsset {
  id: string;
  title: string;
  platform: string;
  format: string;
  objective: string | null;
  status: string;
  current_version: number;
  body: Record<string, any>;
  brief: Record<string, any>;
  quality: { ok?: boolean; issues?: { level: string; field: string; message: string }[] };
  generation_status: "pending" | "ready" | "failed";
  generation_error: string | null;
  provider: string | null;
  brand_id: string | null;
  updated_at: string;
  versions?: { version: number; source: string; label: string | null; note: string | null; created_at: string; body: Record<string, any> }[];
  pending_approval_id?: string | null;
}

export interface MediaItem {
  media_asset_id?: string;
  id?: string;
  url: string;
  kind: string;
  mime_type?: string;
}

export interface SocialPost {
  id: string;
  format: string;
  caption: string;
  media: MediaItem[];
  scheduled_at: string | null;
  status: string;
  connected_account_id: string | null;
  account: { name: string; mode: string } | null;
  content_asset_id: string | null;
  approval_id: string | null;
  permalink: string | null;
  attempts: number;
  last_error: string | null;
  published_at: string | null;
  metrics: Record<string, number>;
}

export interface Campaign {
  id: string;
  platform: "meta" | "google";
  name: string;
  objective: string;
  status: string;
  ad_account_id: string | null;
  currency: string;
  daily_budget_minor: number | null;
  lifetime_budget_minor: number | null;
  start_date: string | null;
  end_date: string | null;
  config: Record<string, any>;
  external_id: string | null;
  last_error: string | null;
  created_by_ai: boolean;
  last_30_days: Record<string, number | null> | null;
  validation_errors?: string[];
  approvals?: { id: string; action_type: string; status: string; title: string; created_at: string }[];
  entities?: { level: string; external_id: string; name: string; status: string }[];
  submission_log?: { at: string; event: string; [k: string]: unknown }[];
}

export interface JobStatus {
  id: string;
  type: string;
  status: "queued" | "running" | "succeeded" | "failed" | "cancelled";
  result: Record<string, any>;
  error: string | null;
}

// ---- formatting helpers shared by web and mobile ---------------------------------------

export function formatMoney(minor: number | null | undefined, currency = "INR", digits = 0): string {
  if (minor === null || minor === undefined) return "—";
  return new Intl.NumberFormat("en-IN", { style: "currency", currency, maximumFractionDigits: digits, minimumFractionDigits: digits }).format(minor / 100);
}

export function formatNumber(n: number | null | undefined): string {
  if (n === null || n === undefined) return "—";
  return new Intl.NumberFormat("en-IN").format(n);
}

export function formatKpi(k: Pick<Kpi, "value" | "unit">, currency = "INR"): string {
  if (k.value === null || k.value === undefined) return "—";
  if (k.unit === "money") return formatMoney(k.value, currency, k.value < 10_000 ? 2 : 0);
  if (k.unit === "ratio") return k.value > 1.5 ? `${k.value.toFixed(2)}×` : `${(k.value * 100).toFixed(2)}%`;
  if (k.unit === "score") return `${k.value}`;
  return formatNumber(k.value);
}

export const STATUS_LABELS: Record<string, string> = {
  draft: "Draft", in_review: "In review", approved: "Approved", scheduled: "Scheduled", publishing: "Publishing",
  published: "Published", failed: "Failed", cancelled: "Cancelled", changes_requested: "Changes requested",
  rejected: "Rejected", pending: "Waiting", executed: "Done", superseded: "Replaced", pending_approval: "Awaiting approval",
  submitting: "Submitting", active: "Live", paused: "Paused", archived: "Archived", awaiting_approval: "Awaiting approval",
  running: "Running", completed: "Completed", queued: "Queued",
};
