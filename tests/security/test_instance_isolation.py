"""
IDOR / Instance-Isolation security tests.

Verifies that users cannot access instances they are not members of.
These are Priorität-1 tests — if they fail, data from one tenant leaks to another.
"""
import pytest
import pytest_asyncio
from tests.conftest import (
    create_test_user,
    create_test_instance,
    grant_instance_access,
    create_session_token,
)


@pytest_asyncio.fixture
async def two_tenants():
    """
    Two isolated users and two isolated instances.
    user_a is a viewer in instance_a only.
    user_b is a viewer in instance_b only.
    admin_user is a global admin with access to everything.
    """
    user_a = await create_test_user()
    user_b = await create_test_user()
    admin = await create_test_user(is_admin=True)
    instance_a = await create_test_instance()
    instance_b = await create_test_instance()

    await grant_instance_access(user_a.id, instance_a.id, "viewer")
    await grant_instance_access(user_b.id, instance_b.id, "viewer")

    return {
        "user_a": user_a,
        "user_b": user_b,
        "admin": admin,
        "instance_a": instance_a,
        "instance_b": instance_b,
        "token_a": await create_session_token(user_a.id),
        "token_b": await create_session_token(user_b.id),
        "token_admin": await create_session_token(admin.id),
    }


class TestDocumentAccess:
    async def test_user_cannot_list_documents_in_foreign_instance(self, client, two_tenants):
        """User A has no membership in instance B — must get 403."""
        d = two_tenants
        r = await client.get(
            f"/api/documents/{d['instance_b'].id}",
            cookies={"session_token": d["token_a"]},
        )
        assert r.status_code == 403

    async def test_user_can_list_documents_in_own_instance(self, client, two_tenants):
        """User A is viewer in instance A — must get 200."""
        d = two_tenants
        r = await client.get(
            f"/api/documents/{d['instance_a'].id}",
            cookies={"session_token": d["token_a"]},
        )
        assert r.status_code == 200

    async def test_reverse_isolation_holds(self, client, two_tenants):
        """User B cannot access instance A either."""
        d = two_tenants
        r = await client.get(
            f"/api/documents/{d['instance_a'].id}",
            cookies={"session_token": d["token_b"]},
        )
        assert r.status_code == 403

    async def test_admin_can_access_any_instance(self, client, two_tenants):
        """Global admin sees all instances."""
        d = two_tenants
        r = await client.get(
            f"/api/documents/{d['instance_b'].id}",
            cookies={"session_token": d["token_admin"]},
        )
        assert r.status_code == 200


class TestChatAccess:
    async def test_user_cannot_stream_foreign_instance(self, client, two_tenants):
        """User A requests chat on instance B — must get 403 before any LLM call."""
        d = two_tenants
        r = await client.post(
            "/api/chat/stream",
            json={"question": "test", "instance_id": d["instance_b"].id},
            cookies={"session_token": d["token_a"]},
        )
        assert r.status_code == 403

    async def test_unauthenticated_request_is_rejected(self, client, two_tenants):
        """No session cookie — must get 401."""
        d = two_tenants
        r = await client.get(f"/api/documents/{d['instance_a'].id}")
        assert r.status_code == 401


class TestHistoryClearScope:
    async def test_user_cannot_clear_history_of_foreign_instance(self, client, two_tenants):
        """User A cannot delete chat history scoped to instance B."""
        d = two_tenants
        r = await client.delete(
            f"/api/chat/history?instance_id={d['instance_b'].id}",
            cookies={"session_token": d["token_a"]},
        )
        assert r.status_code == 403

    async def test_user_can_clear_own_history(self, client, two_tenants):
        """User A can delete their own history for instance A."""
        d = two_tenants
        r = await client.delete(
            f"/api/chat/history?instance_id={d['instance_a'].id}",
            cookies={"session_token": d["token_a"]},
        )
        # 200 or 204 — whatever the handler returns on success
        assert r.status_code in (200, 204)
