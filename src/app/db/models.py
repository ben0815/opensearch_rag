from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text, DateTime, JSON, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, relationship
from sqlalchemy import Index


def _utcnow() -> datetime:
    """Naive UTC datetime — drop-in replacement for deprecated datetime.utcnow()."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id                   = Column(Integer, primary_key=True)
    ldap_uid             = Column(String(255), unique=True, nullable=False)
    display_name         = Column(String(255))
    email                = Column(String(255))
    is_global_admin      = Column(Boolean, nullable=False, default=False)
    is_active            = Column(Boolean, nullable=False, default=True)
    local_password_hash  = Column(String(255))
    created_at           = Column(DateTime, nullable=False, default=_utcnow)
    last_login           = Column(DateTime)
    default_instance_id  = Column(Integer, ForeignKey("instances.id", ondelete="SET NULL"))
    preferences          = Column(JSON)
    instance_memberships = relationship("InstanceMember", back_populates="user", foreign_keys="InstanceMember.user_id")
    group_memberships    = relationship("GroupMember", back_populates="user")
    sessions             = relationship("Session", back_populates="user")


class Instance(Base):
    __tablename__ = "instances"
    id          = Column(Integer, primary_key=True)
    name        = Column(String(255), nullable=False)
    slug        = Column(String(64), unique=True, nullable=False)
    description = Column(Text)
    settings    = Column(JSON)
    created_at  = Column(DateTime, nullable=False, default=_utcnow)
    updated_at  = Column(DateTime, onupdate=_utcnow)
    members     = relationship("InstanceMember", back_populates="instance")


class InstanceMember(Base):
    __tablename__ = "instance_members"
    user_id     = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    instance_id = Column(Integer, ForeignKey("instances.id", ondelete="CASCADE"), primary_key=True)
    role        = Column(String(32), nullable=False, default="viewer")
    added_at    = Column(DateTime, nullable=False, default=_utcnow)
    added_by    = Column(Integer, ForeignKey("users.id"))
    user        = relationship("User", back_populates="instance_memberships", foreign_keys=[user_id])
    instance    = relationship("Instance", back_populates="members")


class Group(Base):
    __tablename__ = "groups"
    __table_args__ = (UniqueConstraint("name", name="groups_name_unique"),)
    id            = Column(Integer, primary_key=True)
    name          = Column(String(255), nullable=False)
    ldap_group_dn = Column(Text)
    created_at    = Column(DateTime, nullable=False, default=_utcnow)
    updated_at    = Column(DateTime, onupdate=_utcnow)
    instance_roles = relationship("GroupInstanceRole", back_populates="group")
    members        = relationship("GroupMember", back_populates="group")


class GroupInstanceRole(Base):
    __tablename__ = "group_instance_roles"
    group_id    = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    instance_id = Column(Integer, ForeignKey("instances.id", ondelete="CASCADE"), primary_key=True)
    role        = Column(String(32), nullable=False, default="viewer")
    group       = relationship("Group", back_populates="instance_roles")


class GroupMember(Base):
    __tablename__ = "group_members"
    user_id  = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    group_id = Column(Integer, ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True)
    user     = relationship("User", back_populates="group_memberships")
    group    = relationship("Group", back_populates="members")


class AppSetting(Base):
    __tablename__ = "app_settings"
    key        = Column(String(64), primary_key=True)
    value      = Column(Text, nullable=False)
    updated_at = Column(DateTime, nullable=False, default=_utcnow, onupdate=_utcnow)
    updated_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))


class ChatHistory(Base):
    __tablename__ = "chat_history"
    id                = Column(Integer, primary_key=True)
    user_id           = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    instance_id       = Column(Integer, ForeignKey("instances.id", ondelete="CASCADE"), nullable=False)
    question          = Column(Text, nullable=False)
    answer            = Column(Text, nullable=False)
    context_docs      = Column(JSON)
    response_metadata = Column(JSON)
    created_at        = Column(DateTime, nullable=False, default=_utcnow)


class Session(Base):
    __tablename__ = "sessions"
    token              = Column(String(128), primary_key=True)
    user_id            = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    expires_at         = Column(DateTime, nullable=False)
    created_at         = Column(DateTime, nullable=False, default=_utcnow)
    is_impersonation   = Column(Boolean, nullable=False, default=False)
    impersonated_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    user               = relationship("User", back_populates="sessions", foreign_keys=[user_id])


class AuditLog(Base):
    __tablename__ = "audit_log"
    id          = Column(Integer, primary_key=True)
    user_id     = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    action      = Column(String(64), nullable=False)
    target_type = Column(String(64))
    target_id   = Column(String(255))
    detail      = Column(JSON)
    ip_address  = Column(String(64))
    created_at  = Column(DateTime, nullable=False, default=_utcnow)
