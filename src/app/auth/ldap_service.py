import os
from datetime import datetime, timezone
from ldap3 import Server, Connection, ALL
from ldap3.core.exceptions import LDAPBindError, LDAPException
from ldap3.utils.conv import escape_filter_chars
from app.utils.logging_config import setup_logger

logger = setup_logger(__name__)


class LDAPAuthError(Exception):
    pass


class LDAPAccountLockedError(LDAPAuthError):
    pass


class LDAPAccountExpiredError(LDAPAuthError):
    pass


_DN_SPECIAL = str.maketrans({
    "\\": "\\\\", ",": "\\,", "+": "\\+", "<": "\\<",
    ">": "\\>", '"': '\\"', ";": "\\;", "=": "\\=", "\x00": "",
})


def _build_user_dn(uid: str, uid_attr: str, search_base: str) -> str:
    return f"{uid_attr}={uid.translate(_DN_SPECIAL)},{search_base}"


def authenticate(username: str, password: str, ldap_config: dict | None = None) -> dict:
    """
    Bind as user, check status attributes.
    ldap_config: dict from config_service.get_ldap_config() — overrides env defaults.

    Returns dict with {uid, display_name, email, ldap_is_admin}.
    Raises LDAPAuthError subclass for locked/expired accounts.
    Raises LDAPBindError for wrong password / unknown user.
    """
    cfg = ldap_config or {}
    ldap_url        = cfg.get("ldap_url") or os.getenv("LDAP_URL", "ldap://localhost:389")
    search_base     = cfg.get("ldap_user_search_base") or os.getenv("LDAP_USER_SEARCH_BASE", "ou=users,dc=example,dc=com")
    uid_attr        = cfg.get("ldap_uid_attr") or os.getenv("LDAP_UID_ATTR", "uid")
    dn_attr         = cfg.get("ldap_display_name_attr") or os.getenv("LDAP_DISPLAY_NAME_ATTR", "displayName")
    mail_attr       = cfg.get("ldap_mail_attr") or os.getenv("LDAP_MAIL_ATTR", "mail")
    admin_group_dn  = cfg.get("ldap_admin_group_dn") or os.getenv("LDAP_ADMIN_GROUP_DN", "")

    status_attrs = [uid_attr, dn_attr, mail_attr, "shadowExpire", "pwdAccountLockedTime", "shadowInactive"]

    user_dn = _build_user_dn(username, uid_attr, search_base)
    server = Server(ldap_url, get_info=ALL)

    try:
        conn = Connection(server, user=user_dn, password=password, auto_bind=True)
    except LDAPBindError:
        raise

    conn.search(
        search_base=search_base,
        search_filter=f"({uid_attr}={escape_filter_chars(username)})",
        attributes=status_attrs,
    )
    if not conn.entries:
        raise LDAPAuthError("Benutzer nicht gefunden nach Bind")

    entry = conn.entries[0]

    locked_time = getattr(entry, "pwdAccountLockedTime", None)
    if locked_time and locked_time.value:
        raise LDAPAccountLockedError("Account gesperrt (ppolicy)")

    shadow_expire = getattr(entry, "shadowExpire", None)
    if shadow_expire and shadow_expire.value not in (None, -1):
        expire_epoch_days = int(shadow_expire.value)
        if expire_epoch_days > 0:
            expire_dt = datetime.fromtimestamp(expire_epoch_days * 86400, tz=timezone.utc)
            if expire_dt < datetime.now(tz=timezone.utc):
                shadow_inactive = getattr(entry, "shadowInactive", None)
                grace_days = int(shadow_inactive.value) if shadow_inactive and shadow_inactive.value else 0
                if grace_days <= 0 or expire_dt.timestamp() + grace_days * 86400 < datetime.now(tz=timezone.utc).timestamp():
                    raise LDAPAccountExpiredError("Account abgelaufen (shadowExpire/shadowInactive)")

    is_admin = False
    if admin_group_dn:
        try:
            conn.search(
                search_base=admin_group_dn,
                search_filter=f"(member={escape_filter_chars(user_dn)})",
                attributes=["cn"],
            )
            is_admin = len(conn.entries) > 0
        except LDAPException:
            logger.warning("LDAP-Admin-Gruppen-Check fehlgeschlagen")

    conn.unbind()

    return {
        "uid": str(getattr(entry, uid_attr, username)),
        "display_name": str(getattr(entry, dn_attr, username) or username),
        "email": str(getattr(entry, mail_attr, "") or ""),
        "ldap_is_admin": is_admin,
    }
