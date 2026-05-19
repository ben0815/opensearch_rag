"""CLI: python -m app.cli.admin create-admin <username> <password>"""
import asyncio
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

_env_file = os.getenv("ENV_FILE") or str(Path(__file__).resolve().parents[3] / "infra" / ".env")
load_dotenv(_env_file, override=False)

from sqlalchemy import select
from app.db.session import get_session_factory
from app.db.models import User


async def _create_admin(username: str, password: str):
    import bcrypt
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    factory = get_session_factory()
    async with factory() as db:
        result = await db.execute(select(User).where(User.ldap_uid == username))
        user = result.scalar_one_or_none()
        if user is None:
            user = User(
                ldap_uid=username,
                display_name=username,
                email="",
                is_global_admin=True,
                local_password_hash=pw_hash,
            )
            db.add(user)
            await db.commit()
            print(f"Admin-Benutzer '{username}' angelegt.")
        else:
            user.is_global_admin = True
            user.local_password_hash = pw_hash
            await db.commit()
            print(f"Benutzer '{username}' auf Global-Admin aktualisiert.")


if __name__ == "__main__":
    if len(sys.argv) < 4 or sys.argv[1] != "create-admin":
        print("Usage: python -m app.cli.admin create-admin <username> <password>")
        sys.exit(1)
    asyncio.run(_create_admin(sys.argv[2], sys.argv[3]))
