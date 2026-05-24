"""Pydantic schemas for the REST API."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ─── User ─────────────────────────────────────────────────────────────────────

class UserPreferences(BaseModel):
    language: str = "de"
    theme: str = "auto"


class UserOut(BaseModel):
    id: int
    ldap_uid: str
    display_name: str | None = None
    email: str | None = None
    is_global_admin: bool
    is_active: bool
    created_at: datetime
    last_login: datetime | None = None
    default_instance_id: int | None = None
    preferences: UserPreferences = Field(default_factory=UserPreferences)
    is_impersonation: bool = False
    impersonated_by: str | None = None

    @field_validator("preferences", mode="before")
    @classmethod
    def _default_preferences(cls, v: Any) -> Any:
        if v is None or v == {}:
            return UserPreferences()
        return v

    model_config = ConfigDict(from_attributes=True)


class UserPatchRequest(BaseModel):
    default_instance_id: int | None = None
    preferences: UserPreferences | None = None


# ─── Auth ─────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    user: UserOut
    session_lifetime_hours: int


# ─── Instances ────────────────────────────────────────────────────────────────

class InstanceOut(BaseModel):
    id: int
    name: str
    slug: str
    description: str | None = None
    settings: dict | None = None
    role: str
    created_at: datetime
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class InstanceAdminOut(BaseModel):
    id: int
    name: str
    slug: str
    description: str | None = None
    settings: dict | None = None
    created_at: datetime
    updated_at: datetime | None = None
    member_count: int = 0
    group_count: int = 0
    doc_count: int = 0

    model_config = ConfigDict(from_attributes=True)


class InstanceCreateRequest(BaseModel):
    name: str
    description: str = ""
    analyzer: str = "german"


class InstancePatchRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    settings: dict | None = None
    clear_settings: bool = False


class InstanceMemberOut(BaseModel):
    user_id: int
    ldap_uid: str
    display_name: str | None = None
    role: str


class AddInstanceMemberRequest(BaseModel):
    user_id: int
    role: str  # "viewer" | "manager"


# ─── Chat ─────────────────────────────────────────────────────────────────────

class ChatRequest(BaseModel):
    question: str
    instance_id: int


class ChatHistoryOut(BaseModel):
    id: int
    question: str
    answer: str
    context_docs: list | None = None
    created_at: datetime
    instance_id: int
    instance_name: str
    response_metadata: dict | None = None

    model_config = ConfigDict(from_attributes=True)


class ChatHistoryPatchRequest(BaseModel):
    duration_s: float | None = None
    ttft_s: float | None = None


class PaginatedChatHistory(BaseModel):
    items: list[ChatHistoryOut]
    total: int
    page: int
    total_pages: int


# ─── Documents ────────────────────────────────────────────────────────────────

class DocumentOut(BaseModel):
    sha256: str
    title: str
    file_size: int
    page_count: int
    chunk_count: int
    indexed_date: str


class AssignInstanceRequest(BaseModel):
    instance_id: int
    role: str  # "viewer" | "manager"


# ─── Admin – Users ────────────────────────────────────────────────────────────

class AdminUserOut(BaseModel):
    id: int
    ldap_uid: str
    display_name: str | None = None
    email: str | None = None
    is_global_admin: bool
    is_active: bool
    created_at: datetime
    last_login: datetime | None = None
    instance_memberships: list[dict] = Field(default_factory=list)
    group_names: list[str] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class AdminUserPatchRequest(BaseModel):
    is_global_admin: bool | None = None
    is_active: bool | None = None


class PaginatedAdminUsers(BaseModel):
    items: list[AdminUserOut]
    total: int
    page: int
    total_pages: int


# ─── Admin – Groups ───────────────────────────────────────────────────────────

class GroupInstanceRoleOut(BaseModel):
    instance_id: int
    instance_name: str
    role: str


class GroupOut(BaseModel):
    id: int
    name: str
    ldap_group_dn: str | None = None
    created_at: datetime
    member_ids: list[int] = Field(default_factory=list)
    instance_roles: list[GroupInstanceRoleOut] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class GroupCreateRequest(BaseModel):
    name: str
    ldap_group_dn: str = ""


class AssignGroupInstanceRequest(BaseModel):
    instance_id: int
    role: str  # "viewer" | "manager"


class AddGroupMemberRequest(BaseModel):
    user_id: int


class AssignUserGroupRequest(BaseModel):
    group_id: int


class PaginatedGroups(BaseModel):
    items: list[GroupOut]
    total: int
    page: int
    total_pages: int


# ─── Admin – Settings ─────────────────────────────────────────────────────────

class SettingOut(BaseModel):
    key: str
    value: str
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class SettingSpec(BaseModel):
    key: str
    label: str
    type: str
    inputmode: str | None = None
    min: float | None = None
    max: float | None = None
    step: float | None = None
    hint: str | None = None
    description: str | None = None


class SettingsPatchRequest(BaseModel):
    values: dict[str, Any]


class SettingsResponse(BaseModel):
    settings: list[SettingOut]
    spec: list[SettingSpec]
    config_snapshot: dict


# ─── Admin – LDAP ─────────────────────────────────────────────────────────────

class LDAPConfigOut(BaseModel):
    ldap_url: str
    ldap_user_search_base: str
    ldap_uid_attr: str
    ldap_display_name_attr: str
    ldap_mail_attr: str
    ldap_user_filter: str
    ldap_admin_group_dn: str
    ldap_bind_dn: str
    ldap_bind_password_set: bool
    ldap_enabled: bool
    ldap_allow_auto_registration: bool


class LDAPConfigIn(BaseModel):
    ldap_url: str
    ldap_user_search_base: str
    ldap_uid_attr: str = "uid"
    ldap_display_name_attr: str = "displayName"
    ldap_mail_attr: str = "mail"
    ldap_user_filter: str = "(objectClass=inetOrgPerson)"
    ldap_admin_group_dn: str = ""
    ldap_bind_dn: str = ""
    ldap_bind_password: str | None = None  # None = don't change
    ldap_enabled: bool = True
    ldap_allow_auto_registration: bool = True


class AdminUserCreateRequest(BaseModel):
    ldap_uid: str
    display_name: str | None = None
    email: str | None = None
    is_global_admin: bool = False


class LDAPSearchResult(BaseModel):
    ldap_uid: str
    display_name: str | None = None
    email: str | None = None


# ─── Admin – Audit ────────────────────────────────────────────────────────────

class AuditLogOut(BaseModel):
    id: int
    user_id: int | None = None
    action: str
    target_type: str | None = None
    target_id: str | None = None
    detail: dict | None = None
    ip_address: str | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PaginatedAuditLog(BaseModel):
    items: list[AuditLogOut]
    total: int
    page: int
    total_pages: int


# ─── Admin – Status ───────────────────────────────────────────────────────────

class ServiceStatus(BaseModel):
    ok: bool
    error: str | None = None
    extra: dict = Field(default_factory=dict)


class StatusOut(BaseModel):
    app_version: str
    opensearch: dict
    ollama: dict
    redis: dict
    postgres: dict


# ─── Helpers ──────────────────────────────────────────────────────────────────

def user_out(
    user: Any,
    is_impersonation: bool = False,
    impersonated_by: str | None = None,
) -> UserOut:
    """Construct UserOut from ORM User, injecting session-derived impersonation fields."""
    return UserOut(
        id=user.id,
        ldap_uid=user.ldap_uid,
        display_name=user.display_name,
        email=user.email,
        is_global_admin=user.is_global_admin,
        is_active=user.is_active,
        created_at=user.created_at,
        last_login=user.last_login,
        default_instance_id=getattr(user, "default_instance_id", None),
        preferences=getattr(user, "preferences", None) or {},
        is_impersonation=is_impersonation,
        impersonated_by=impersonated_by,
    )
