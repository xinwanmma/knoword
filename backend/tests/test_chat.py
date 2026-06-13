"""端到端测试 — mock Ollama API，测试完整对话流程。"""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.main import app


# ==================== Mock Ollama 响应 ====================

def _mock_ollama_tags(installed_models: list[str]):
    """模拟 Ollama /api/tags 响应。"""
    return {
        "models": [{"name": m, "size": 1000} for m in installed_models]
    }


def _mock_ollama_embeddings(embedding: list[float] = None):
    """模拟 Ollama /api/embeddings 响应。"""
    return {"embedding": embedding or [0.1] * 384}


def _mock_ollama_chat_stream(tokens: list[str]):
    """模拟 Ollama /api/chat 流式响应。"""
    lines = []
    for token in tokens:
        lines.append(json.dumps({
            "message": {"role": "assistant", "content": token},
            "done": False,
        }))
    lines.append(json.dumps({
        "message": {"role": "assistant", "content": ""},
        "done": True,
    }))
    return "\n".join(lines)


# ==================== 健康检查测试 ====================

class TestHealthCheck:
    """健康检查 API 测试。"""

    @pytest.mark.asyncio
    async def test_health_returns_status(self, client):
        """健康检查应返回 status 和 services。"""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"models": [{"name": "qwen3.5:2b"}, {"name": "qwen3-embedding:0.6b"}]}

        with patch("httpx.AsyncClient") as MockClient, \
             patch("app.services.vectorstore.check_chromadb", return_value=True):
            instance = AsyncMock()
            instance.get.return_value = mock_response
            instance.post.return_value = mock_response
            instance.__aenter__ = AsyncMock(return_value=instance)
            instance.__aexit__ = AsyncMock(return_value=False)
            MockClient.return_value = instance

            resp = await client.get("/api/health")
            assert resp.status_code == 200
            data = resp.json()
            assert "status" in data
            assert "services" in data


# ==================== 认证流程测试 ====================

class TestAuthFlow:
    """认证完整流程测试。"""

    @pytest.mark.asyncio
    async def test_register_and_login(self, client):
        """注册 → 登录 → 获取用户信息。"""
        # 注册
        resp = await client.post("/api/auth/register", json={
            "username": "e2e_user",
            "email": "e2e@test.com",
            "password": "pass123456",
        })
        assert resp.status_code == 201
        data = resp.json()
        assert "access_token" in data
        assert data["user"]["username"] == "e2e_user"

        # 登录
        resp = await client.post("/api/auth/login", json={
            "username": "e2e_user",
            "password": "pass123456",
        })
        assert resp.status_code == 200
        token = resp.json()["access_token"]

        # 获取用户信息
        resp = await client.get("/api/auth/me", headers={
            "Authorization": f"Bearer {token}",
        })
        assert resp.status_code == 200
        assert resp.json()["username"] == "e2e_user"

    @pytest.mark.asyncio
    async def test_duplicate_username(self, client):
        """重复用户名应返回 400。"""
        await client.post("/api/auth/register", json={
            "username": "dup_user",
            "email": "dup@test.com",
            "password": "pass123456",
        })
        resp = await client.post("/api/auth/register", json={
            "username": "dup_user",
            "email": "dup2@test.com",
            "password": "pass123456",
        })
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_wrong_password(self, client):
        """错误密码应返回 401。"""
        await client.post("/api/auth/register", json={
            "username": "wrong_pw_user",
            "email": "wrong@test.com",
            "password": "correctpass",
        })
        resp = await client.post("/api/auth/login", json={
            "username": "wrong_pw_user",
            "password": "wrongpass",
        })
        assert resp.status_code == 401


# ==================== 知识库流程测试 ====================

class TestKnowledgeBaseFlow:
    """知识库 CRUD 完整流程。"""

    @pytest.mark.asyncio
    async def test_create_list_delete_kb(self, auth_client):
        """创建 → 列表 → 详情 → 删除。"""
        # 创建
        resp = await auth_client.post("/api/kb", json={
            "name": "测试知识库",
            "description": "用于测试",
        })
        assert resp.status_code == 201
        kb_id = resp.json()["id"]

        # 列表
        resp = await auth_client.get("/api/kb")
        assert resp.status_code == 200
        kbs = resp.json()
        assert any(k["id"] == kb_id for k in kbs)

        # 详情
        resp = await auth_client.get(f"/api/kb/{kb_id}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "测试知识库"

        # 删除
        resp = await auth_client.delete(f"/api/kb/{kb_id}")
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_user_cannot_access_other_kb(self, auth_client):
        """普通用户不能访问其他用户的私有知识库。"""
        # 创建知识库
        resp = await auth_client.post("/api/kb", json={"name": "私有KB"})
        kb_id = resp.json()["id"]

        # 注册第二个用户
        await auth_client.post("/api/auth/register", json={
            "username": "other_user",
            "email": "other@test.com",
            "password": "pass123456",
        })
        resp = await auth_client.post("/api/auth/login", json={
            "username": "other_user",
            "password": "pass123456",
        })
        other_token = resp.json()["access_token"]

        # 第二个用户尝试访问
        resp = await auth_client.get(f"/api/kb/{kb_id}", headers={
            "Authorization": f"Bearer {other_token}",
        })
        assert resp.status_code == 403

        # 清理
        await auth_client.delete(f"/api/kb/{kb_id}")


# ==================== 对话流程测试 ====================

class TestChatFlow:
    """对话完整流程测试 (mock Ollama)。"""

    @pytest.mark.asyncio
    async def test_chat_stream_returns_sse(self, auth_client):
        """对话请求应返回 SSE 流式响应。"""
        mock_chat_response = _mock_ollama_chat_stream(["你好", "！", "有什么", "问题"])

        with patch("app.services.ollama_service.get_embedding", return_value=[0.1] * 384), \
             patch("app.services.vectorstore.search_documents", return_value={
                 "documents": [], "metadatas": [], "distances": [],
             }), \
             patch("app.core.llm.get_llm") as mock_llm, \
             patch("app.core.llm.get_llm_for_supervisor") as mock_supervisor:

            # Mock Supervisor 返回 general
            mock_supervisor.return_value.invoke = MagicMock(
                return_value=MagicMock(content="general")
            )

            # Mock RAG/General Agent 生成
            mock_llm.return_value.invoke = MagicMock(
                return_value=MagicMock(content="你好！有什么可以帮你的？")
            )

            resp = await auth_client.post("/api/chat", json={
                "query": "你好",
                "kb_ids": [],
                "search_all": False,
            }, headers={"Accept": "text/event-stream"})

            # SSE 响应
            assert resp.status_code == 200
            content = resp.text
            assert "event:" in content
            assert "data:" in content
            # 应包含 done 事件
            assert "done" in content

    @pytest.mark.asyncio
    async def test_chat_with_kb_triggers_rag(self, auth_client):
        """选择知识库时应触发 RAG Agent。"""
        with patch("app.services.ollama_service.get_embedding", return_value=[0.1] * 384), \
             patch("app.services.vectorstore.search_documents", return_value={
                 "documents": ["年假5天"],
                 "metadatas": [{"filename": "手册.pdf", "page": 1, "doc_id": 1}],
                 "distances": [0.1],
             }), \
             patch("app.core.llm.get_llm") as mock_llm, \
             patch("app.core.llm.get_llm_for_supervisor") as mock_supervisor:

            mock_supervisor.return_value.invoke = MagicMock(
                return_value=MagicMock(content="rag")
            )
            mock_llm.return_value.invoke = MagicMock(
                return_value=MagicMock(content="年假为5天。")
            )

            resp = await auth_client.post("/api/chat", json={
                "query": "年假几天？",
                "kb_ids": [999],
                "search_all": False,
            }, headers={"Accept": "text/event-stream"})

            assert resp.status_code == 200
            content = resp.text
            # 应包含 agent 事件
            assert "agent" in content
            # 应包含 token 事件
            assert "token" in content

    @pytest.mark.asyncio
    async def test_chat_saves_conversation(self, auth_client):
        """对话应保存到数据库。"""
        with patch("app.services.ollama_service.get_embedding", return_value=[0.1] * 384), \
             patch("app.services.vectorstore.search_documents", return_value={
                 "documents": [], "metadatas": [], "distances": [],
             }), \
             patch("app.core.llm.get_llm") as mock_llm, \
             patch("app.core.llm.get_llm_for_supervisor") as mock_supervisor:

            mock_supervisor.return_value.invoke = MagicMock(
                return_value=MagicMock(content="general")
            )
            mock_llm.return_value.invoke = MagicMock(
                return_value=MagicMock(content="测试回答")
            )

            await auth_client.post("/api/chat", json={
                "query": "测试消息",
                "kb_ids": [],
                "search_all": False,
            }, headers={"Accept": "text/event-stream"})

        # 检查会话列表
        resp = await auth_client.get("/api/chat/history")
        assert resp.status_code == 200
        convs = resp.json()
        assert len(convs) >= 1
        assert convs[0]["title"] == "测试消息"


# ==================== 分类测试 ====================

class TestCategoryFlow:
    """分类管理测试。"""

    @pytest.mark.asyncio
    async def test_create_and_list_categories(self, auth_client):
        """创建分类 → 列出分类。"""
        # 先注册为管理员
        resp = await auth_client.post("/api/auth/login", json={
            "username": "testadmin",
            "password": "testpass123",
        })
        admin_token = resp.json()["access_token"]

        resp = await auth_client.post("/api/categories", json={
            "name": "技术文档",
        }, headers={"Authorization": f"Bearer {admin_token}"})
        assert resp.status_code == 201

        resp = await auth_client.get("/api/categories")
        assert resp.status_code == 200
        cats = resp.json()
        assert any(c["name"] == "技术文档" for c in cats)
