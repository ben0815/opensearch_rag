// Mirrors src/app/schemas.py — keep in sync when backend schemas change.

export interface UserPreferences {
  language: "de" | "en";
  theme: "auto" | "light" | "dark";
}

export interface UserOut {
  id: number;
  ldap_uid: string;
  display_name: string | null;
  email: string | null;
  is_global_admin: boolean;
  is_active: boolean;
  created_at: string;
  last_login: string | null;
  default_instance_id: number | null;
  preferences: UserPreferences;
  is_impersonation: boolean;
  impersonated_by: string | null;
}

export interface UserPresenceOut {
  id: number;
  display_name: string | null;
  ldap_uid: string;
  is_querying: boolean;
}

export interface LoginRequest {
  username: string;
  password: string;
}

export interface LoginResponse {
  user: UserOut;
  session_lifetime_hours: number;
}

// ─── Instances ────────────────────────────────────────────────────────────────

export interface InstanceOut {
  id: number;
  name: string;
  slug: string;
  description: string | null;
  settings: Record<string, unknown> | null;
  role: string;
  created_at: string;
  updated_at: string | null;
}

export interface InstanceAdminOut {
  id: number;
  name: string;
  slug: string;
  description: string | null;
  settings: Record<string, unknown> | null;
  created_at: string;
  updated_at: string | null;
  member_count: number;
  group_count: number;
  doc_count: number;
}

export interface InstanceMemberOut {
  user_id: number;
  ldap_uid: string;
  display_name: string | null;
  role: string;
}

export interface InstanceCreateRequest {
  name: string;
  description?: string;
  analyzer?: string;
}

export interface InstancePatchRequest {
  name?: string;
  description?: string;
  settings?: Record<string, unknown>;
  clear_settings?: boolean;
}

// ─── Chat ─────────────────────────────────────────────────────────────────────

export interface ChatRequest {
  question: string;
  instance_id: number;
}

export interface ChatHistoryOut {
  id: number;
  question: string;
  answer: string;
  context_docs: unknown[] | null;
  created_at: string;
  instance_id: number;
  instance_name: string;
  response_metadata: Record<string, unknown> | null;
}

export interface PaginatedChatHistory {
  items: ChatHistoryOut[];
  total: number;
  page: number;
  total_pages: number;
}

// ─── Documents ────────────────────────────────────────────────────────────────

export interface DocumentOut {
  sha256: string;
  title: string;
  display_name: string;
  description: string;
  valid_until: string | null;
  file_size: number;
  page_count: number;
  chunk_count: number;
  indexed_date: string;
}

export interface ConflictItem {
  name: string;
  hash: string;
}

export interface CheckNamesResponse {
  conflicts: ConflictItem[];
}

export type UploadProgressEvent =
  | { file: string; index: number; total: number; progress: number }
  | { file: string; index: number; total: number; status: "ok"; progress: 100; chunk_count: number; warnings: string[] }
  | { file: string; index: number; total: number; status: "already_indexed"; progress: 100 }
  | { file: string; index: number; total: number; status: "error"; error: string }
  | { done: true; total: number };

// ─── Admin – Users ────────────────────────────────────────────────────────────

export interface AdminUserCreateRequest {
  ldap_uid: string;
  display_name?: string | null;
  email?: string | null;
  is_global_admin?: boolean;
}

export interface AdminUserOut {
  id: number;
  ldap_uid: string;
  display_name: string | null;
  email: string | null;
  is_global_admin: boolean;
  is_active: boolean;
  created_at: string;
  last_login: string | null;
  instance_memberships: Array<{ instance_id: number; instance_name: string; role: string }>;
  group_names: string[];
}

export interface PaginatedAdminUsers {
  items: AdminUserOut[];
  total: number;
  page: number;
  total_pages: number;
}

// ─── Admin – Groups ───────────────────────────────────────────────────────────

export interface GroupInstanceRoleOut {
  instance_id: number;
  instance_name: string;
  role: string;
}

export interface GroupOut {
  id: number;
  name: string;
  ldap_group_dn: string | null;
  created_at: string;
  member_ids: number[];
  instance_roles: GroupInstanceRoleOut[];
}

export interface PaginatedGroups {
  items: GroupOut[];
  total: number;
  page: number;
  total_pages: number;
}

// ─── Admin – Settings ─────────────────────────────────────────────────────────

export interface SettingOut {
  key: string;
  value: string;
  updated_at: string | null;
}

export interface SettingSpec {
  key: string;
  label: string;
  type: string;
  inputmode?: string;
  min?: number;
  max?: number;
  step?: number;
  hint?: string;
  description?: string | null;
}

export interface SettingsResponse {
  settings: SettingOut[];
  spec: SettingSpec[];
  config_snapshot: Record<string, unknown>;
}

// ─── Admin – LDAP ─────────────────────────────────────────────────────────────

export interface LDAPConfigIn {
  ldap_url: string;
  ldap_user_search_base: string;
  ldap_uid_attr?: string;
  ldap_display_name_attr?: string;
  ldap_mail_attr?: string;
  ldap_user_filter?: string;
  ldap_admin_group_dn?: string;
  ldap_bind_dn?: string;
  ldap_bind_password?: string | null;
  ldap_enabled?: boolean;
  ldap_allow_auto_registration?: boolean;
}

export interface LDAPConfigOut {
  ldap_url: string;
  ldap_user_search_base: string;
  ldap_uid_attr: string;
  ldap_display_name_attr: string;
  ldap_mail_attr: string;
  ldap_user_filter: string;
  ldap_admin_group_dn: string;
  ldap_bind_dn: string;
  ldap_bind_password_set: boolean;
  ldap_enabled: boolean;
  ldap_allow_auto_registration: boolean;
}

export interface LDAPSearchResult {
  ldap_uid: string;
  display_name: string | null;
  email: string | null;
}

// ─── Admin – Audit ────────────────────────────────────────────────────────────

export interface AuditLogOut {
  id: number;
  user_id: number | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  detail: Record<string, unknown> | null;
  ip_address: string | null;
  created_at: string;
  ldap_uid: string | null;
}

export interface PaginatedAuditLog {
  items: AuditLogOut[];
  total: number;
  page: number;
  total_pages: number;
}

// ─── Admin – Status ───────────────────────────────────────────────────────────

export interface StatusOut {
  app_version: string;
  opensearch: Record<string, unknown>;
  ollama: Record<string, unknown>;
  redis: Record<string, unknown>;
  postgres: Record<string, unknown>;
}

// ─── SSE Chat ─────────────────────────────────────────────────────────────────

export interface SourceChunk {
  source: string;
  filename: string;
  page: number | null;
  score: number;
  search_source?: "bm25" | "knn" | "both" | null;
  excerpt: string;
}

export interface ChatDoneEvent {
  history_id: number;
  answer: string;
  retrieval_ms?: number;
  llm_generation_s: number;
}
