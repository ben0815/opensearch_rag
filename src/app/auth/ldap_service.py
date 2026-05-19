import os
from datetime import datetime, timezone
from ldap3 import Server, Connection, ALL
from ldap3.core.exceptions import LDAPBindError, LDAPException
from ldap3.utils.conv import escape_filter_chars
from app.utils.logging_config import setup_logger

logger = setup_logger(__name__)

LDAP_URL               = os.getenv("LDAP_URL", "ldap://localhost:389")
LDAP_USER_SEARCH_BASE  = os.getenv("LDAP_USER_SEARCH_BASE", "ou=users,dc=example,dc=com")
LDAP_UID_ATTR          = os.getenv("LDAP_UID_ATTR", "uid")
LDAP_DISPLAY_NAME_ATTR = os.getenv("LDAP_DISPLAY_NAME_ATTR", "displayName")
LDAP_MAIL_ATTR         = os.getenv("LDAP_MAIL_ATTR", "mail")
LDAP_USER_FILTER       = os.getenv("LDAP_USER_FILTER", "(objectClass=inetOrgPerson)")
LDAP_ADMIN_GROUP_DN    = os.getenv("LDAP_ADMIN_GROUP_DN", "")

STATUS_ATTRS = [
    LDAP_UID_ATTR, LDAP_DISPLAY_NAME_ATTR, LDAP_MAIL_ATTR,
    "shadowExpire", "pwdAccountLockedTime", "shadowInactive",
]


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


def _build_user_dn(uid: str) -> str:
    # Escape RFC 4514 special characters in the attribute value before embedding in a DN
    return f"{LDAP_UID_ATTR}={uid.translate(_DN_SPECIAL)},{LDAP_USER_SEARCH_BASE}"


def authenticate(username: str, password: str) -> dict:
    """
    Bind als Benutzer, prüft Status-Attribute.
    Gibt dict mit {uid, display_name, email, ldap_is_admin} zurück.
    Wirft LDAPAuthError-Subklasse bei gesperrtem/abgelaufenem Account.
    Wirft LDAPBindError bei falschem Passwort / nicht vorhandenem User.
    """
    user_dn = _build_user_dn(username)
    server = Server(LDAP_URL, get_info=ALL)

    try:
        conn = Connection(server, user=user_dn, password=password, auto_bind=True)
    except LDAPBindError:
        raise

    conn.search(
        search_base=LDAP_USER_SEARCH_BASE,
        search_filter=f"({LDAP_UID_ATTR}={escape_filter_chars(username)})",
        attributes=STATUS_ATTRS,
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
                raise LDAPAccountExpiredError("Account abgelaufen (shadowExpire)")

    is_admin = False
    if LDAP_ADMIN_GROUP_DN:
        try:
            conn.search(
                search_base=LDAP_ADMIN_GROUP_DN,
                search_filter=f"(member={escape_filter_chars(user_dn)})",
                attributes=["cn"],
            )
            is_admin = len(conn.entries) > 0
        except LDAPException:
            logger.warning("LDAP-Admin-Gruppen-Check fehlgeschlagen")

    conn.unbind()

    return {
        "uid": str(getattr(entry, LDAP_UID_ATTR, username)),
        "display_name": str(getattr(entry, LDAP_DISPLAY_NAME_ATTR, username) or username),
        "email": str(getattr(entry, LDAP_MAIL_ATTR, "") or ""),
        "ldap_is_admin": is_admin,
    }
