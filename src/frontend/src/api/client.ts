import type {
  AdminUserCreateRequest,
  AdminUserOut,
  DocumentOut,
  GroupOut,
  InstanceAdminOut,
  InstanceCreateRequest,
  InstanceMemberOut,
  InstanceOut,
  InstancePatchRequest,
  LDAPConfigIn,
  LDAPConfigOut,
  LDAPSearchResult,
  LoginRequest,
  LoginResponse,
  PaginatedAdminUsers,
  PaginatedAuditLog,
  PaginatedChatHistory,
  PaginatedGroups,
  SettingsResponse,
  StatusOut,
  UserOut,
  UserPreferences,
  UserPresenceOut,
} from "@/types/api";

class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public detail?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function getCsrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

async function request<T>(
  method: string,
  path: string,
  body?: unknown,
  signal?: AbortSignal,
): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (method !== "GET" && method !== "HEAD") {
    const csrf = getCsrfToken();
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }

  const resp = await fetch(path, {
    method,
    headers,
    credentials: "include",
    signal,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });

  if (!resp.ok) {
    let detail: unknown;
    try {
      detail = await resp.json();
    } catch {
      detail = undefined;
    }
    const msg = (detail as { detail?: string })?.detail ?? resp.statusText;
    throw new ApiError(resp.status, String(msg), detail);
  }

  if (resp.status === 204) return undefined as unknown as T;
  return resp.json() as Promise<T>;
}

const get = <T>(path: string, signal?: AbortSignal) => request<T>("GET", path, undefined, signal);
const post = <T>(path: string, body?: unknown, signal?: AbortSignal) =>
  request<T>("POST", path, body, signal);
const put = <T>(path: string, body?: unknown) => request<T>("PUT", path, body);
const patch = <T>(path: string, body?: unknown) => request<T>("PATCH", path, body);
const del = (path: string) => request<void>("DELETE", path);

// ─── Auth ─────────────────────────────────────────────────────────────────────

export const auth = {
  login: (data: LoginRequest) => post<LoginResponse>("/api/auth/login", data),
  logout: () => post<void>("/api/auth/logout"),
  me: () => get<UserOut>("/api/auth/me"),
};

// ─── User ─────────────────────────────────────────────────────────────────────

export const user = {
  instances: () => get<InstanceOut[]>("/api/instances"),
  patchMe: (data: { default_instance_id?: number | null; preferences?: Partial<UserPreferences> }) =>
    patch<UserOut>("/api/users/me", data),
};

// ─── Chat ─────────────────────────────────────────────────────────────────────

export const chat = {
  history: (params?: { page?: number; per_page?: number; instance_id?: number }) => {
    const q = new URLSearchParams();
    if (params?.page) q.set("page", String(params.page));
    if (params?.per_page) q.set("per_page", String(params.per_page));
    if (params?.instance_id) q.set("instance_id", String(params.instance_id));
    return get<PaginatedChatHistory>(`/api/chat/history?${q}`);
  },
  patchHistory: (id: number, data: { duration_s?: number; ttft_s?: number }) =>
    patch<void>(`/api/chat/history/${id}`, data),
  deleteHistory: (id: number) => del(`/api/chat/history/${id}`),
  deleteAllHistory: (instanceId?: number) => {
    const q = instanceId ? `?instance_id=${instanceId}` : "";
    return del(`/api/chat/history${q}`);
  },
};

// ─── Documents ────────────────────────────────────────────────────────────────

export const documents = {
  list: (instanceId: number) => get<DocumentOut[]>(`/api/documents/${instanceId}`),
  delete: (instanceId: number, hash: string) => del(`/api/documents/${instanceId}/${hash}`),
};

// ─── Presence ─────────────────────────────────────────────────────────────────

export const presence = {
  list: (signal?: AbortSignal) => get<UserPresenceOut[]>("/api/users/presence", signal),
};

// ─── Admin – Instances ────────────────────────────────────────────────────────

export const adminInstances = {
  list: () => get<InstanceAdminOut[]>("/api/admin/instances"),
  get: (id: number) => get<InstanceAdminOut>(`/api/admin/instances/${id}`),
  create: (data: InstanceCreateRequest) => post<InstanceAdminOut>("/api/admin/instances", data),
  patch: (id: number, data: InstancePatchRequest) =>
    patch<InstanceAdminOut>(`/api/admin/instances/${id}`, data),
  delete: (id: number) => del(`/api/admin/instances/${id}`),
  members: (id: number) => get<InstanceMemberOut[]>(`/api/admin/instances/${id}/members`),
  addMember: (id: number, data: { user_id: number; role: string }) =>
    post<void>(`/api/admin/instances/${id}/members`, data),
  removeMember: (id: number, userId: number) =>
    del(`/api/admin/instances/${id}/members/${userId}`),
};

// ─── Admin – Users ────────────────────────────────────────────────────────────

export const adminUsers = {
  list: (params?: { page?: number; per_page?: number; search?: string }) => {
    const q = new URLSearchParams();
    if (params?.page) q.set("page", String(params.page));
    if (params?.per_page) q.set("per_page", String(params.per_page));
    if (params?.search) q.set("q", params.search);
    return get<PaginatedAdminUsers>(`/api/admin/users?${q}`);
  },
  create: (data: AdminUserCreateRequest) => post<AdminUserOut>("/api/admin/users", data),
  patch: (id: number, data: { is_global_admin?: boolean; is_active?: boolean }) =>
    patch<AdminUserOut>(`/api/admin/users/${id}`, data),
  delete: (id: number) => del(`/api/admin/users/${id}`),
  assignInstance: (id: number, data: { instance_id: number; role: string }) =>
    post<void>(`/api/admin/users/${id}/instances`, data),
  removeInstance: (id: number, instanceId: number) =>
    del(`/api/admin/users/${id}/instances/${instanceId}`),
  assignGroup: (id: number, data: { group_id: number }) =>
    post<void>(`/api/admin/users/${id}/groups`, data),
  removeGroup: (id: number, groupId: number) =>
    del(`/api/admin/users/${id}/groups/${groupId}`),
  impersonate: (id: number) => post<UserOut>(`/api/admin/users/${id}/impersonate`),
};

// ─── Admin – Groups ───────────────────────────────────────────────────────────

export const adminGroups = {
  list: (params?: { page?: number; per_page?: number }) => {
    const q = new URLSearchParams();
    if (params?.page) q.set("page", String(params.page));
    if (params?.per_page) q.set("per_page", String(params.per_page));
    return get<PaginatedGroups>(`/api/admin/groups?${q}`);
  },
  create: (data: { name: string; ldap_group_dn?: string }) =>
    post<GroupOut>("/api/admin/groups", data),
  delete: (id: number) => del(`/api/admin/groups/${id}`),
  assignInstance: (id: number, data: { instance_id: number; role: string }) =>
    post<void>(`/api/admin/groups/${id}/instances`, data),
  removeInstance: (id: number, instanceId: number) =>
    del(`/api/admin/groups/${id}/instances/${instanceId}`),
  addMember: (id: number, data: { user_id: number }) =>
    post<void>(`/api/admin/groups/${id}/members`, data),
  removeMember: (id: number, userId: number) =>
    del(`/api/admin/groups/${id}/members/${userId}`),
};

// ─── Admin – Settings ─────────────────────────────────────────────────────────

export const adminSettings = {
  get: () => get<SettingsResponse>("/api/admin/settings"),
  patch: (values: Record<string, string | number | boolean>) =>
    patch<SettingsResponse>("/api/admin/settings", { values }),
};

// ─── Admin – LDAP ─────────────────────────────────────────────────────────────

export const adminLdap = {
  get: () => get<LDAPConfigOut>("/api/admin/ldap"),
  save: (data: LDAPConfigIn) => put<LDAPConfigOut>("/api/admin/ldap", data),
  test: () => post<{ ok: boolean; error: string | null }>("/api/admin/ldap/test"),
  sync: () => post<{ synced: number; errors: number }>("/api/admin/ldap/sync"),
  search: (query: string) => post<LDAPSearchResult[]>("/api/admin/ldap/search", { query }),
};

// ─── Admin – Status ───────────────────────────────────────────────────────────

export const adminStatus = {
  get: () => get<StatusOut>("/api/admin/status"),
};

// ─── Admin – Audit ────────────────────────────────────────────────────────────

export const adminAudit = {
  list: (params?: {
    page?: number;
    per_page?: number;
    action?: string;
    user_id?: number;
    username?: string;
    ip?: string;
    date_from?: string;
    date_to?: string;
    order_by?: "created_at" | "ip_address" | "action" | "user_id";
    order_dir?: "asc" | "desc";
  }) => {
    const q = new URLSearchParams();
    if (params?.page) q.set("page", String(params.page));
    if (params?.per_page) q.set("per_page", String(params.per_page));
    if (params?.action) q.set("action", params.action);
    if (params?.user_id) q.set("user_id", String(params.user_id));
    if (params?.username) q.set("username", params.username);
    if (params?.ip) q.set("ip", params.ip);
    if (params?.date_from) q.set("date_from", params.date_from);
    if (params?.date_to) q.set("date_to", params.date_to);
    if (params?.order_by) q.set("order_by", params.order_by);
    if (params?.order_dir) q.set("order_dir", params.order_dir);
    return get<PaginatedAuditLog>(`/api/admin/audit?${q}`);
  },
};

// ─── Admin – Maintenance ──────────────────────────────────────────────────────

export const adminMaintenance = {
  status: () => get<{ maintenance_mode: boolean }>("/api/admin/maintenance"),
  set: (enabled: boolean) => post<void>("/api/admin/maintenance", { enabled }),
};

export { ApiError };
