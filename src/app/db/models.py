from datetime import datetime, timezone
from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text, DateTime, JSON
from sqlalchemy.orm import DeclarativeBase, relationship


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
    local_password_hash  = Column(String(255))
    created_at           = Column(DateTime, nullable=False, default=_utcnow)
    last_login           = Column(DateTime)
    instance_memberships = relationship("InstanceMember", back_populates="user", foreign_keys="InstanceMember.user_id")
    group_memberships    = relationship("GroupMember", back_populates="user")
    sessions             = relationship("Session", back_populates="user")


class Instance(Base):
    __tablename__ = "instances"
    id          = Column(Integer, primary_key=True)
    name        = Column(String(255), nullable=False)
    slug        = Column(String(64), unique=True, nullable=False)
    description = Column(Text)
    created_at  = Column(DateTime, nullable=False, default=_utcnow)
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
    id            = Column(Integer, primary_key=True)
    name          = Column(String(255), nullable=False)
    ldap_group_dn = Column(Text)
    created_at    = Column(DateTime, nullable=False, default=_utcnow)
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


class ChatHistory(Base):
    __tablename__ = "chat_history"
    id           = Column(Integer, primary_key=True)
    user_id      = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    instance_id  = Column(Integer, ForeignKey("instances.id", ondelete="CASCADE"), nullable=False)
    question     = Column(Text, nullable=False)
    answer       = Column(Text, nullable=False)
    context_docs = Column(JSON)
    created_at   = Column(DateTime, nullable=False, default=_utcnow)


class Session(Base):
    __tablename__ = "sessions"
    token      = Column(String(128), primary_key=True)
    user_id    = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, nullable=False, default=_utcnow)
    user       = relationship("User", back_populates="sessions")
