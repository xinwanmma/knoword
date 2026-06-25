"""对话流程测试 — mock 向量检索与 LLM 流式。"""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock


def _mock_stream_tokens(tokens: list[str]):
    """构造 mock 的 astream 异步迭代器。"""

    class _FakeChunk:
        def __init__(self, content):
            self.content = content

    async def _aiter():
        for t in tokens:
            yield _FakeChunk(t)

    return _aiter()


class TestChatFlow:
    """对话完整流程测试（mock 检索与 LLM）。"""

    @pytest.mark.asyncio
    async def test_chat_with_kb_returns_sse(self, auth_client):
        """选择知识库时应返回 SSE 流。"""
        with patch("app.services.ollama_service.get_embedding", return_value=[0.1] * 384), \
             patch("app.services.vectorstore.search_documents", return_value={
                 "documents": ["年假5天"],
                 "metadatas": [{"filename": "手册.pdf", "page": 1, "doc_id": 1}],
                 "distances": [0.1],
             }), \
             patch("app.services.reranker.rerank_with_score_fusion", new=AsyncMock(return_value=[
                 {"text": "年假5天", "metadata": {"filename": "手册.pdf", "page": 1, "doc_id": 1}, "rerank_score": 0.9}
             ])), \
             patch("app.core.llm.get_llm") as mock_llm:

            mock_llm.return_value.astream = lambda *_args, **_kw: _mock_stream_tokens(["年假", "为", "5", "天"])

            resp = await auth_client.post("/api/chat", json={
                "query": "年假几天？",
                "kb_ids": [999],
                "search_all": False,
            }, headers={"Accept": "text/event-stream"})

            assert resp.status_code == 200
            content = resp.text
            assert "event:" in content
            assert "token" in content
            assert "done" in content

    @pytest.mark.asyncio
    async def test_chat_no_kb_uses_general_fallback(self, auth_client):
        """无知识库时应跳过检索直接生成。"""
        with patch("app.services.ollama_service.get_embedding", return_value=[0.1] * 384), \
             patch("app.services.vectorstore.search_documents", return_value={
                 "documents": [], "metadatas": [], "distances": [],
             }), \
             patch("app.core.llm.get_llm") as mock_llm:

            mock_llm.return_value.astream = lambda *_a, **_kw: _mock_stream_tokens(["你好", "！"])

            resp = await auth_client.post("/api/chat", json={
                "query": "你好",
                "kb_ids": [],
                "search_all": False,
            }, headers={"Accept": "text/event-stream"})

            assert resp.status_code == 200
            assert "token" in resp.text

    @pytest.mark.asyncio
    async def test_chat_saves_conversation(self, auth_client):
        """对话应保存到数据库。"""
        with patch("app.services.ollama_service.get_embedding", return_value=[0.1] * 384), \
             patch("app.services.vectorstore.search_documents", return_value={
                 "documents": [], "metadatas": [], "distances": [],
             }), \
             patch("app.core.llm.get_llm") as mock_llm:

            mock_llm.return_value.astream = lambda *_a, **_kw: _mock_stream_tokens(["测试回答"])

            await auth_client.post("/api/chat", json={
                "query": "测试消息",
                "kb_ids": [],
                "search_all": False,
            }, headers={"Accept": "text/event-stream"})

        resp = await auth_client.get("/api/chat/history")
        assert resp.status_code == 200
        convs = resp.json()
        assert any(c["title"] == "测试消息" for c in convs)
