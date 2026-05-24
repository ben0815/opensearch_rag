"""CLI admin commands.

Usage:
    python -m app.cli.admin create-admin <username> <password>
    python -m app.cli.admin rotate-encryption-key <new_key>
"""
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
                is_active=True,
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


async def _rotate_encryption_key(new_key: str):
    """Re-encrypt all encrypted app_settings values with a new Fernet key.

    Steps:
    1. Decrypt all 'enc:' values with the OLD key (from ENCRYPTION_KEY env var)
    2. Re-encrypt with the new key
    3. Print updated values — apply them by setting ENCRYPTION_KEY=<new_key> in infra/.env

    Run BEFORE updating ENCRYPTION_KEY in .env.
    """
    from cryptography.fernet import Fernet
    from app.db.models import AppSetting
    from app.utils.crypto import decrypt, _PREFIX

    try:
        new_fernet = Fernet(new_key.encode())
    except Exception as e:
        print(f"Ungültiger Schlüssel: {e}")
        sys.exit(1)

    factory = get_session_factory()
    async with factory() as db:
        rows = (await db.execute(select(AppSetting))).scalars().all()
        updated = 0
        for row in rows:
            if not row.value.startswith(_PREFIX):
                continue
            try:
                plaintext = decrypt(row.value)
            except ValueError as e:
                print(f"WARNUNG: {row.key} konnte nicht entschlüsselt werden: {e}")
                continue
            new_encrypted = _PREFIX + new_fernet.encrypt(plaintext.encode()).decode()
            row.value = new_encrypted
            updated += 1
            print(f"  {row.key}: re-encrypted")
        await db.commit()

    print(f"\n{updated} Wert(e) neu verschlüsselt.")
    print(f"Setze jetzt ENCRYPTION_KEY={new_key} in infra/.env und starte die App neu.")


def _generate_key():
    from cryptography.fernet import Fernet
    print(Fernet.generate_key().decode())


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python -m app.cli.admin create-admin <username> <password>")
        print("  python -m app.cli.admin rotate-encryption-key <new_key>")
        print("  python -m app.cli.admin generate-encryption-key")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "create-admin":
        if len(sys.argv) < 4:
            print("Usage: python -m app.cli.admin create-admin <username> <password>")
            sys.exit(1)
        asyncio.run(_create_admin(sys.argv[2], sys.argv[3]))

    elif cmd == "rotate-encryption-key":
        if len(sys.argv) < 3:
            print("Usage: python -m app.cli.admin rotate-encryption-key <new_key>")
            print("Generate a new key: python -m app.cli.admin generate-encryption-key")
            sys.exit(1)
        asyncio.run(_rotate_encryption_key(sys.argv[2]))

    elif cmd == "generate-encryption-key":
        _generate_key()

    else:
        print(f"Unbekannter Befehl: {cmd}")
        sys.exit(1)
