"""
Admin-endpoint access-control tests.

Verifies that non-admin users cannot reach any /api/admin/* endpoint,
and that admin users can.
"""
import pytest
import pytest_asyncio
from tests.conftest import (
    create_test_user,
    create_test_instance,
    grant_instance_access,
    create_session_token,
)

_ADMIN_ENDPOINTS_GET = [
    "/api/admin/users",
    "/api/admin/instances",
    "/api/admin/groups",
    "/api/admin/settings",
    "/api/admin/ldap",
    "/api/admin/status",
    "/api/admin/audit",
    "/api/admin/maintenance",
]


@pytest_asyncio.fixture
async def users():
    normal = await create_test_user()
    admin = await create_test_user(is_admin=True)
    return {
        "normal": normal,
        "admin": admin,
        "token_normal": await create_session_token(normal.id),
        "token_admin": await create_session_token(admin.id),
    }


class TestNonAdminBlocked:
    @pytest.mark.parametrize("path", _ADMIN_ENDPOINTS_GET)
    async def test_non_admin_gets_403(self, client, users, path):
        """Every GET admin endpoint must return 403 for non-admin users."""
        r = await client.get(path, cookies={"session_token": users["token_normal"]})
        assert r.status_code == 403, f"Expected 403 for {path}, got {r.status_code}"

    async def test_unauthenticated_gets_401(self, client):
        """Unauthenticated access to admin endpoints must return 401."""
        r = await client.get("/api/admin/users")
        assert r.status_code == 401


class TestAdminAllowed:
    async def test_admin_can_list_users(self, client, users):
        """Admin user gets 200 on /api/admin/users."""
        r = await client.get(
            "/api/admin/users",
            cookies={"session_token": users["token_admin"]},
        )
        assert r.status_code == 200

    async def test_admin_can_list_instances(self, client, users):
        r = await client.get(
            "/api/admin/instances",
            cookies={"session_token": users["token_admin"]},
        )
        assert r.status_code == 200

    async def test_admin_can_access_settings(self, client, users):
        r = await client.get(
            "/api/admin/settings",
            cookies={"session_token": users["token_admin"]},
        )
        assert r.status_code == 200


class TestImpersonationSafety:
    async def test_admin_cannot_impersonate_another_admin(self, client, users):
        """Admin A cannot impersonate admin B (privilege escalation)."""
        admin2 = await create_test_user(is_admin=True)
        r = await client.post(
            f"/api/admin/users/{admin2.id}/impersonate",
            cookies={"session_token": users["token_admin"]},
        )
        assert r.status_code == 403

    async def test_admin_can_impersonate_normal_user(self, client, users):
        """Admin can impersonate a non-admin user."""
        r = await client.post(
            f"/api/admin/users/{users['normal'].id}/impersonate",
            cookies={"session_token": users["token_admin"]},
        )
        assert r.status_code == 200
