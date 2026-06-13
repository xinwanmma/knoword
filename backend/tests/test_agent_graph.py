"""Agent 图测试 — mock LLM，测试 prepare/generate/postprocess 逻辑。"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, AsyncMock as AMock
from langchain_core.messages import HumanMessage, AIMessage

from app.services.agent_graph import (
    AgentState,
    build_agent_graph,
    prepare_node,
    route_after_prepare,
    _format_sources_text,
    _format_store_text,
    _simple_similarity,
)


# ==================== 辅助函数 ====================

def _make_state(**kwargs) -> dict:
    """构造测试用的 AgentState。"""
    defaults = {
        "messages": [HumanMessage(content="你好")],
        "user_id": "test-user-001",
        "user_name": "测试用户",
        "kb_ids": [],
        "search_all": False,
        "store_data": {},
        "agent_answer": "",
        "sources": [],
        "agent_name": "",
        "original_query": "你好",
        "from_cache": False,
    }
    defaults.update(kwargs)
    return defaults


# ==================== 规则路由测试 ====================

class TestRuleBasedRouting:
    """规则路由测试（替代 LLM Supervisor）。"""

    @pytest.mark.asyncio
    async def test_route_to_rag_when_kb_selected(self):
        """有知识库 → rag"""
        state = _make_state(
            messages=[HumanMessage(content="员工手册里写了什么？")],
            kb_ids=[1, 2],
            original_query="员工手册里写了什么？",
        )
        # Mock Store 加载
        with patch("app.services.agent_graph._load_user_store", return_value={}):
            with patch("app.services.agent_graph._check_cache", return_value=None):
                with patch("app.services.agent_graph._get_permitted_kb_ids", return_value=[1, 2]):
                    result = await prepare_node(state)
        assert result["agent_name"] == "rag"

    @pytest.mark.asyncio
    async def test_route_to_general_when_no_kb(self):
        """无知识库 → general"""
        state = _make_state(
            messages=[HumanMessage(content="你好啊")],
            kb_ids=[],
            original_query="你好啊",
        )
        with patch("app.services.agent_graph._load_user_store", return_value={}):
            with patch("app.services.agent_graph._check_cache", return_value=None):
                with patch("app.services.agent_graph._get_permitted_kb_ids", return_value=[]):
                    result = await prepare_node(state)
        assert result["agent_name"] == "general"

    @pytest.mark.asyncio
    async def test_route_to_rag_when_search_all(self):
        """search_all=True → rag"""
        state = _make_state(
            messages=[HumanMessage(content="相关问题")],
            search_all=True,
            original_query="相关问题",
        )
        with patch("app.services.agent_graph._load_user_store", return_value={}):
            with patch("app.services.agent_graph._check_cache", return_value=None):
                with patch("app.services.agent_graph._get_permitted_kb_ids", return_value=[1]):
                    result = await prepare_node(state)
        assert result["agent_name"] == "rag"

    @pytest.mark.asyncio
    async def test_route_returns_store_data(self):
        """prepare 应返回 Store 数据"""
        state = _make_state(
            store_data={"language": "zh-CN"},
        )
        with patch("app.services.agent_graph._load_user_store", return_value={"language": "zh-CN"}):
            with patch("app.services.agent_graph._check_cache", return_value=None):
                with patch("app.services.agent_graph._get_permitted_kb_ids", return_value=[]):
                    result = await prepare_node(state)
        assert result["store_data"]["language"] == "zh-CN"


# ==================== 路由函数测试 ====================

class TestRouteFunction:
    """route_after_prepare 路由函数测试。"""

    def test_route_to_generate(self):
        state = {"from_cache": False}
        assert route_after_prepare(state) == "generate"

    def test_route_to_postprocess_on_cache(self):
        state = {"from_cache": True}
        assert route_after_prepare(state) == "postprocess"


# ==================== Memory Retrieval 测试 ====================

class TestMemoryRetrieval:
    """记忆检索节点测试。"""

    def test_passthrough_store(self):
        """memory_retrieval 节点应该原样传递 Store 数据。"""
        state = _make_state(
            store_data={"language": "zh-CN", "style": "concise"},
        )
        result = memory_retrieval_node(state)
        assert result["store_data"]["language"] == "zh-CN"
        assert result["store_data"]["style"] == "concise"

    def test_empty_memories(self):
        """无记忆时返回空值。"""
        state = _make_state()
        result = memory_retrieval_node(state)
        assert result["store_data"] == {}


# ==================== 格式化函数测试 ====================

class TestFormatFunctions:
    """Prompt 格式化函数测试。"""

    def test_format_sources_with_results(self):
        """有检索结果时正确格式化。"""
        search_results = {
            "documents": ["员工手册规定年假5天", "加班需提前申请"],
            "metadatas": [
                {"filename": "手册.pdf", "page": 1, "doc_id": 1},
                {"filename": "手册.pdf", "page": 3, "doc_id": 1},
            ],
            "distances": [0.1, 0.3],
        }
        text = _format_sources_text(search_results)
        assert "手册.pdf" in text
        assert "员工手册规定年假5天" in text
        assert "相关度" in text

    def test_format_sources_empty(self):
        """无检索结果时返回占位文本。"""
        text = _format_sources_text({"documents": []})
        assert "无相关参考资料" in text

    def test_format_store_data(self):
        """Store 数据正确格式化。"""
        text = _format_store_text(
            {"language": "zh", "style": "concise"},
        )
        assert "language" in text
        assert "concise" in text

    def test_format_store_empty(self):
        """无 Store 数据时返回空字符串。"""
        text = _format_store_text({})
        assert text == ""


# ==================== 相似度测试 ====================

class TestSimilarity:
    """相似度函数测试。"""

    def test_identical(self):
        assert _simple_similarity("年假政策", "年假政策") == 1.0

    def test_partial(self):
        score = _simple_similarity("年假政策说明", "年假有几天")
        assert 0 < score < 1

    def test_empty(self):
        assert _simple_similarity("", "test") == 0.0


# ==================== 图构建测试 ====================

class TestGraphBuild:
    """图构建测试。"""

    def test_graph_compiles(self):
        """图应能成功编译。"""
        graph = build_agent_graph()
        assert graph is not None
