"""Admin-Endpunkte: LDAP-Konfiguration."""
import asyncio as _asyncio

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User
from app.db.session import get_db
from app.schemas import LDAPConfigIn, LDAPConfigOut, LDAPSearchResult
from app.services.config_service import (
    get_ldap_config,
    save_ldap_config,
)
from app.routes.admin._shared import _audit, _require_admin

router = APIRouter()


@router.get("")
async def get_ldap(
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    cfg = await get_ldap_config(db)
    return LDAPConfigOut(
        ldap_url=cfg.get("ldap_url", ""),
        ldap_user_search_base=cfg.get("ldap_user_search_base", ""),
        ldap_uid_attr=cfg.get("ldap_uid_attr", "uid"),
        ldap_display_name_attr=cfg.get("ldap_display_name_attr", "displayName"),
        ldap_mail_attr=cfg.get("ldap_mail_attr", "mail"),
        ldap_user_filter=cfg.get("ldap_user_filter", "(objectClass=inetOrgPerson)"),
        ldap_admin_group_dn=cfg.get("ldap_admin_group_dn", ""),
        ldap_bind_dn=cfg.get("ldap_bind_dn", ""),
        ldap_bind_password_set=bool(cfg.get("ldap_bind_password")),
        ldap_enabled=cfg.get("ldap_enabled", "true").lower() not in ("false", "0", "off"),
        ldap_allow_auto_registration=cfg.get("ldap_allow_auto_registration", "true").lower() not in ("false", "0", "off"),
    ).model_dump()


@router.put("")
async def update_ldap(
    body: LDAPConfigIn,
    request: Request,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    data = body.model_dump(exclude={"ldap_bind_password"})
    data["ldap_enabled"] = "true" if body.ldap_enabled else "false"
    data["ldap_allow_auto_registration"] = "true" if body.ldap_allow_auto_registration else "false"
    if body.ldap_bind_password is not None:
        data["ldap_bind_password"] = body.ldap_bind_password
    await save_ldap_config(db, data, updated_by=admin.id)

    _audit(db, admin.id, "ldap_config_change", detail={"url": body.ldap_url})
    await db.commit()

    cfg = await get_ldap_config(db)
    return LDAPConfigOut(
        ldap_url=cfg.get("ldap_url", ""),
        ldap_user_search_base=cfg.get("ldap_user_search_base", ""),
        ldap_uid_attr=cfg.get("ldap_uid_attr", "uid"),
        ldap_display_name_attr=cfg.get("ldap_display_name_attr", "displayName"),
        ldap_mail_attr=cfg.get("ldap_mail_attr", "mail"),
        ldap_user_filter=cfg.get("ldap_user_filter", "(objectClass=inetOrgPerson)"),
        ldap_admin_group_dn=cfg.get("ldap_admin_group_dn", ""),
        ldap_bind_dn=cfg.get("ldap_bind_dn", ""),
        ldap_bind_password_set=bool(cfg.get("ldap_bind_password")),
        ldap_enabled=cfg.get("ldap_enabled", "true").lower() not in ("false", "0", "off"),
        ldap_allow_auto_registration=cfg.get("ldap_allow_auto_registration", "true").lower() not in ("false", "0", "off"),
    ).model_dump()


@router.post("/test")
async def test_ldap(
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    from ldap3 import Server, Connection, ALL
    from ldap3.core.exceptions import LDAPException

    cfg = await get_ldap_config(db)
    ldap_url = cfg.get("ldap_url", "")
    bind_dn = cfg.get("ldap_bind_dn", "")
    bind_pw = cfg.get("ldap_bind_password", "")

    def _do_test():
        try:
            server = Server(ldap_url, get_info=ALL, connect_timeout=5)
            conn = Connection(server, user=bind_dn or None, password=bind_pw or None, auto_bind=True)
            conn.unbind()
            return {"ok": True, "error": None}
        except LDAPException as exc:
            return {"ok": False, "error": str(exc)}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    return await _asyncio.to_thread(_do_test)


@router.post("/search")
async def search_ldap_users(
    request: Request,
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    from ldap3 import Server, Connection, ALL, SUBTREE
    from ldap3.core.exceptions import LDAPException
    from ldap3.utils.conv import escape_filter_chars

    body = await request.json()
    query = str(body.get("query", "")).strip()

    cfg = await get_ldap_config(db)
    ldap_url = cfg.get("ldap_url", "")
    bind_dn = cfg.get("ldap_bind_dn", "")
    bind_pw = cfg.get("ldap_bind_password", "")
    search_base = cfg.get("ldap_user_search_base", "")
    uid_attr = cfg.get("ldap_uid_attr", "uid")
    dn_attr = cfg.get("ldap_display_name_attr", "displayName")
    mail_attr = cfg.get("ldap_mail_attr", "mail")
    user_filter = cfg.get("ldap_user_filter", "(objectClass=inetOrgPerson)")

    if not bind_dn:
        raise HTTPException(status_code=400, detail="Kein Bind-DN konfiguriert. LDAP-Suche erfordert einen Service-Account.")

    def _do_search():
        try:
            server = Server(ldap_url, get_info=ALL, connect_timeout=5)
            conn = Connection(server, user=bind_dn, password=bind_pw or None, auto_bind=True)

            if query:
                escaped = escape_filter_chars(query)
                search_filter = f"(&{user_filter}(|({uid_attr}=*{escaped}*)({dn_attr}=*{escaped}*)({mail_attr}=*{escaped}*)))"
            else:
                search_filter = user_filter

            conn.search(
                search_base=search_base,
                search_filter=search_filter,
                search_scope=SUBTREE,
                attributes=[uid_attr, dn_attr, mail_attr],
                size_limit=50,
            )

            results = []
            for entry in conn.entries:
                uid_val = getattr(entry, uid_attr, None)
                if not uid_val or not uid_val.value:
                    continue
                results.append({
                    "ldap_uid": str(uid_val.value),
                    "display_name": str(getattr(entry, dn_attr).value) if getattr(entry, dn_attr, None) and getattr(entry, dn_attr).value else None,
                    "email": str(getattr(entry, mail_attr).value) if getattr(entry, mail_attr, None) and getattr(entry, mail_attr).value else None,
                })
            conn.unbind()
            return results
        except LDAPException as exc:
            raise RuntimeError(str(exc)) from exc

    try:
        results = await _asyncio.to_thread(_do_search)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=f"LDAP-Fehler: {exc}") from exc

    existing_uids = {
        row[0] for row in (await db.execute(select(User.ldap_uid))).all()
    }
    return [
        LDAPSearchResult(ldap_uid=r["ldap_uid"], display_name=r["display_name"], email=r["email"]).model_dump()
        for r in results
        if r["ldap_uid"] not in existing_uids
    ]


@router.post("/sync")
async def sync_ldap(
    admin=Depends(_require_admin),
    db: AsyncSession = Depends(get_db),
):
    from ldap3 import Server, Connection, ALL
    from ldap3.core.exceptions import LDAPException
    from ldap3.utils.conv import escape_filter_chars

    cfg = await get_ldap_config(db)
    ldap_url = cfg.get("ldap_url", "")
    search_base = cfg.get("ldap_user_search_base", "")
    uid_attr = cfg.get("ldap_uid_attr", "uid")
    dn_attr = cfg.get("ldap_display_name_attr", "displayName")
    mail_attr = cfg.get("ldap_mail_attr", "mail")
    admin_group_dn = cfg.get("ldap_admin_group_dn", "")
    bind_dn = cfg.get("ldap_bind_dn", "")
    bind_pw = cfg.get("ldap_bind_password", "")

    users = (await db.execute(select(User).where(User.is_active == True))).scalars().all()  # noqa: E712

    synced = 0
    errors = 0

    def _sync_user(ldap_uid: str):
        try:
            server = Server(ldap_url, get_info=ALL, connect_timeout=5)
            conn = Connection(server, user=bind_dn or None, password=bind_pw or None, auto_bind=True)
            conn.search(
                search_base=search_base,
                search_filter=f"({uid_attr}={escape_filter_chars(ldap_uid)})",
                attributes=[uid_attr, dn_attr, mail_attr],
            )
            if not conn.entries:
                conn.unbind()
                return None
            entry = conn.entries[0]
            result = {
                "display_name": str(getattr(entry, dn_attr, ldap_uid) or ldap_uid),
                "email": str(getattr(entry, mail_attr, "") or ""),
                "is_global_admin": False,
            }
            if admin_group_dn:
                user_dn = f"{uid_attr}={ldap_uid},{search_base}"
                conn.search(
                    search_base=admin_group_dn,
                    search_filter=f"(member={escape_filter_chars(user_dn)})",
                    attributes=["cn"],
                )
                result["is_global_admin"] = len(conn.entries) > 0
            conn.unbind()
            return result
        except (LDAPException, Exception):
            return None

    for user in users:
        if not user.ldap_uid or user.local_password_hash:
            continue
        try:
            ldap_data = await _asyncio.to_thread(_sync_user, user.ldap_uid)
            if ldap_data:
                user.display_name = ldap_data["display_name"]
                user.email = ldap_data["email"]
                if admin_group_dn:
                    user.is_global_admin = ldap_data["is_global_admin"]
                synced += 1
            else:
                errors += 1
        except Exception:
            errors += 1

    if synced:
        await db.commit()

    _audit(db, admin.id, "ldap_sync", detail={"synced": synced, "errors": errors})
    await db.commit()

    return {"synced": synced, "errors": errors}
