import asyncio
import os
from datetime import datetime, timezone

_SECURE_COOKIES = os.getenv("SECURE_COOKIES", "false").lower() == "true"
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from ldap3.core.exceptions import LDAPBindError
from app.auth.ldap_service import authenticate, LDAPAccountLockedError, LDAPAccountExpiredError
from app.auth.session import create_session, delete_session, SESSION_LIFETIME_HOURS
from app.db.session import get_db
from app.db.models import User
from app.dependencies import limiter

from app.utils.templates import templates

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/login")
@limiter.limit("10/minute")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    import bcrypt as _bcrypt

    error = None
    user = None

    result = await db.execute(select(User).where(User.ldap_uid == username))
    db_user = result.scalar_one_or_none()

    # 1. Lokaler Fallback: Bootstrap-Admin mit local_password_hash (kein LDAP nötig)
    if db_user and db_user.local_password_hash:
        if _bcrypt.checkpw(password.encode(), db_user.local_password_hash.encode()):
            db_user.last_login = datetime.now(timezone.utc).replace(tzinfo=None)
            await db.commit()
            user = db_user
        else:
            error = "Ungültige Anmeldedaten."
    else:
        # 2. LDAP-Authentifizierung
        # asyncio.to_thread: LDAP-Bind ist ein synchroner Netzwerk-Call,
        # der sonst den Event Loop für alle anderen Requests blockieren würde.
        ldap_data = None
        try:
            ldap_data = await asyncio.to_thread(authenticate, username, password)
        except LDAPAccountLockedError:
            error = "Ihr Account ist gesperrt. Bitte wenden Sie sich an den Administrator."
        except LDAPAccountExpiredError:
            error = "Ihr Account ist abgelaufen. Bitte wenden Sie sich an den Administrator."
        except LDAPBindError:
            error = "Ungültige Anmeldedaten."
        except Exception:
            error = "Anmeldung fehlgeschlagen. Bitte versuchen Sie es erneut."

        if ldap_data and not error:
            if db_user is None:
                db_user = User(
                    ldap_uid=ldap_data["uid"],
                    display_name=ldap_data["display_name"],
                    email=ldap_data["email"],
                    is_global_admin=ldap_data["ldap_is_admin"],
                )
                db.add(db_user)
            else:
                db_user.display_name = ldap_data["display_name"]
                db_user.email = ldap_data["email"]
                # Immer synchronisieren — so wird der Admin-Status auch entzogen,
                # wenn der Nutzer aus der LDAP-Admin-Gruppe entfernt wurde.
                db_user.is_global_admin = ldap_data["ldap_is_admin"]
                db_user.last_login = datetime.now(timezone.utc).replace(tzinfo=None)
            await db.commit()
            await db.refresh(db_user)
            user = db_user

    if error or not user:
        return templates.TemplateResponse(request, "login.html", {
            "error": error or "Ungültige Anmeldedaten.",
        })

    token = await create_session(db, user.id)
    # Redirect auf "/" statt "/chat" — Smart-Redirect in root() leitet
    # Admins ohne Instanzen direkt zur Verwaltung weiter.
    response = RedirectResponse(url="/", status_code=302)
    response.set_cookie(
        "session_token", token,
        httponly=True,
        samesite="strict",
        secure=_SECURE_COOKIES,
        max_age=SESSION_LIFETIME_HOURS * 3600,
    )
    return response


@router.get("/logout")
async def logout(request: Request, db: AsyncSession = Depends(get_db)):
    token = request.cookies.get("session_token")
    if token:
        await delete_session(db, token)
    response = RedirectResponse(url="/login", status_code=302)
    response.delete_cookie("session_token")
    return response
