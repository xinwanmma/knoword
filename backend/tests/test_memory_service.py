"""Store 服务测试 — PostgreSQL JSONB 键值存储。"""

import pytest
from datetime import datetime

from app.services.store_service import (
    store_put,
    store_get,
    store_get_all,
    store_delete,
    store_delete_all,
    UserStore,
)
from app.db.database import async_session_factory


@pytest.fixture
async def fresh_db():
    """每个测试使用干净的数据库。"""
    async with async_session_factory() as session:
        yield session
        # 清理测试数据
        from sqlalchemy import delete
        await session.execute(delete(UserStore))
        await session.commit()


USER_ID = "test-user-store-001"


# ==================== Store CRUD 测试 ====================

class TestStorePutAndGet:
    """存储和获取测试。"""

    @pytest.mark.asyncio
    async def test_put_and_get_string(self, fresh_db):
        """存取字符串值。"""
        await store_put(fresh_db, USER_ID, "language", "zh-CN")
        result = await store_get(fresh_db, USER_ID, "language")
        assert result is not None
        assert result["key"] == "language"
        assert result["value"]["data"] == "zh-CN"

    @pytest.mark.asyncio
    async def test_put_and_get_dict(self, fresh_db):
        """存取字典值。"""
        prefs = {"style": "concise", "tone": "formal"}
        await store_put(fresh_db, USER_ID, "preferences", prefs)
        result = await store_get(fresh_db, USER_ID, "preferences")
        assert result["value"] == prefs

    @pytest.mark.asyncio
    async def test_put_and_get_list(self, fresh_db):
        """存取列表值。"""
        topics = ["AI", "Python", "RAG"]
        await store_put(fresh_db, USER_ID, "topics", topics)
        result = await store_get(fresh_db, USER_ID, "topics")
        assert result["value"] == topics

    @pytest.mark.asyncio
    async def test_put_overwrite(self, fresh_db):
        """重复 put 应覆盖旧值。"""
        await store_put(fresh_db, USER_ID, "key1", "old_value")
        await store_put(fresh_db, USER_ID, "key1", "new_value")
        result = await store_get(fresh_db, USER_ID, "key1")
        assert result["value"]["data"] == "new_value"

    @pytest.mark.asyncio
    async def test_get_nonexistent_key(self, fresh_db):
        """获取不存在的 key 返回 None。"""
        result = await store_get(fresh_db, USER_ID, "nonexistent")
        assert result is None


class TestStoreGetAll:
    """批量获取测试。"""

    @pytest.mark.asyncio
    async def test_get_all(self, fresh_db):
        """获取用户所有数据。"""
        await store_put(fresh_db, USER_ID, "a", "1")
        await store_put(fresh_db, USER_ID, "b", "2")
        await store_put(fresh_db, USER_ID, "c", "3")

        results = await store_get_all(fresh_db, USER_ID)
        assert len(results) == 3
        keys = {r["key"] for r in results}
        assert keys == {"a", "b", "c"}

    @pytest.mark.asyncio
    async def test_get_all_by_namespace(self, fresh_db):
        """按 namespace 过滤。"""
        await store_put(fresh_db, USER_ID, "k1", "v1", namespace="chat")
        await store_put(fresh_db, USER_ID, "k2", "v2", namespace="settings")
        await store_put(fresh_db, USER_ID, "k3", "v3", namespace="chat")

        results = await store_get_all(fresh_db, USER_ID, namespace="chat")
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_user_isolation(self, fresh_db):
        """不同用户的数据应隔离。"""
        await store_put(fresh_db, "user_A", "key", "value_A")
        await store_put(fresh_db, "user_B", "key", "value_B")

        result_a = await store_get(fresh_db, "user_A", "key")
        result_b = await store_get(fresh_db, "user_B", "key")
        assert result_a["value"]["data"] == "value_A"
        assert result_b["value"]["data"] == "value_B"

        # 清理
        await store_delete_all(fresh_db, "user_A")
        await store_delete_all(fresh_db, "user_B")


class TestStoreDelete:
    """删除测试。"""

    @pytest.mark.asyncio
    async def test_delete_existing_key(self, fresh_db):
        """删除存在的 key。"""
        await store_put(fresh_db, USER_ID, "to_delete", "value")
        deleted = await store_delete(fresh_db, USER_ID, "to_delete")
        assert deleted is True
        result = await store_get(fresh_db, USER_ID, "to_delete")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_key(self, fresh_db):
        """删除不存在的 key 返回 False。"""
        deleted = await store_delete(fresh_db, USER_ID, "ghost")
        assert deleted is False

    @pytest.mark.asyncio
    async def test_delete_all(self, fresh_db):
        """清空用户所有数据。"""
        await store_put(fresh_db, USER_ID, "x", "1")
        await store_put(fresh_db, USER_ID, "y", "2")
        count = await store_delete_all(fresh_db, USER_ID)
        assert count >= 2
        results = await store_get_all(fresh_db, USER_ID)
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_delete_all_by_namespace(self, fresh_db):
        """按 namespace 清空。"""
        await store_put(fresh_db, USER_ID, "a", "1", namespace="chat")
        await store_put(fresh_db, USER_ID, "b", "2", namespace="chat")
        await store_put(fresh_db, USER_ID, "c", "3", namespace="settings")

        count = await store_delete_all(fresh_db, USER_ID, namespace="chat")
        assert count >= 2

        results_chat = await store_get_all(fresh_db, USER_ID, namespace="chat")
        assert len(results_chat) == 0

        results_settings = await store_get_all(fresh_db, USER_ID, namespace="settings")
        assert len(results_settings) == 1


# ==================== Store API 测试 ====================

class TestStoreAPI:
    """Store HTTP API 测试。"""

    @pytest.mark.asyncio
    async def test_put_and_get_via_api(self, auth_client):
        """通过 API 存取数据。"""
        # PUT
        resp = await auth_client.put("/api/store", json={
            "key": "api_key",
            "value": {"test": True},
        })
        assert resp.status_code == 204

        # GET
        resp = await auth_client.get("/api/store/api_key")
        assert resp.status_code == 200
        data = resp.json()
        assert data["value"]["test"] is True

        # 清理
        await auth_client.delete("/api/store/api_key")

    @pytest.mark.asyncio
    async def test_list_via_api(self, auth_client):
        """通过 API 列出所有数据。"""
        await auth_client.put("/api/store", json={"key": "list_test", "value": "ok"})
        resp = await auth_client.get("/api/store")
        assert resp.status_code == 200
        entries = resp.json()
        assert any(e["key"] == "list_test" for e in entries)
        # 清理
        await auth_client.delete("/api/store/list_test")

    @pytest.mark.asyncio
    async def test_delete_via_api(self, auth_client):
        """通过 API 删除数据。"""
        await auth_client.put("/api/store", json={"key": "del_test", "value": "bye"})
        resp = await auth_client.delete("/api/store/del_test")
        assert resp.status_code == 204

        resp = await auth_client.get("/api/store/del_test")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_get_nonexistent_via_api(self, auth_client):
        """获取不存在的 key 返回 404。"""
        resp = await auth_client.get("/api/store/does_not_exist")
        assert resp.status_code == 404
