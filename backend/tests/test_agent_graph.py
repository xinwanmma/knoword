"""Agent 图测试 — mock LLM，测试 Supervisor 路由逻辑。"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from langchain_core.messages import HumanMessage, AIMessage

from app.services.agent_graph import (
    AgentState,
    build_agent_graph,
    supervisor_node,
    route_after_supervisor,
    memory_retrieval_node,
    rag_agent_node,
    general_agent_node,
    _format_sources_text,
    _format_memories_text,
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
        "mem0_memories": [],
        "graph_context": "",
        "store_data": {},
        "agent_answer": "",
        "sources": [],
        "agent_name": "",
        "original_query": "你好",
    }
    defaults.update(kwargs)
    return defaults


def _mock_llm_response(content: str):
    """构造 mock LLM 响应。"""
    mock_response = MagicMock()
    mock_response.content = content
    return mock_response


# ==================== Supervisor 路由测试 ====================

class TestSupervisorNode:
    """Supervisor 路由决策测试。"""

    @patch("app.services.agent_graph.get_llm_for_supervisor")
    def test_supervisor_routes_to_rag_when_kb_selected(self, mock_llm):
        """有知识库时，LLM 返回 rag → 路由到 RAG Agent。"""
        mock_llm.return_value.invoke = MagicMock(
            return_value=_mock_llm_response("rag")
        )

        state = _make_state(
            messages=[HumanMessage(content="员工手册里写了什么？")],
            kb_ids=[1, 2],
            original_query="员工手册里写了什么？",
        )

        result = supervisor_node(state)
        assert result["agent_name"] == "rag"

    @patch("app.services.agent_graph.get_llm_for_supervisor")
    def test_supervisor_routes_to_general_for_chat(self, mock_llm):
        """无知识库 + 闲聊，LLM 返回 general → 路由到 General Agent。"""
        mock_llm.return_value.invoke = MagicMock(
            return_value=_mock_llm_response("general")
        )

        state = _make_state(
            messages=[HumanMessage(content="你好啊")],
            kb_ids=[],
            original_query="你好啊",
        )

        result = supervisor_node(state)
        assert result["agent_name"] == "general"

    @patch("app.services.agent_graph.get_llm_for_supervisor")
    def test_supervisor_fallback_on_invalid_response(self, mock_llm):
        """LLM 返回无效内容时，默认回退到 general。"""
        mock_llm.return_value.invoke = MagicMock(
            return_value=_mock_llm_response("我不知道")
        )

        state = _make_state(
            messages=[HumanMessage(content="随便什么")],
            kb_ids=[],
            original_query="随便什么",
        )

        result = supervisor_node(state)
        assert result["agent_name"] == "general"

    @patch("app.services.agent_graph.get_llm_for_supervisor")
    def test_supervisor_fallback_to_rag_when_kb_selected(self, mock_llm):
        """LLM 返回无效内容但有知识库 → 回退到 rag。"""
        mock_llm.return_value.invoke = MagicMock(
            return_value=_mock_llm_response("不确定")
        )

        state = _make_state(
            messages=[HumanMessage(content="相关问题")],
            kb_ids=[1],
            search_all=True,
            original_query="相关问题",
        )

        result = supervisor_node(state)
        assert result["agent_name"] == "rag"

    @patch("app.services.agent_graph.get_llm_for_supervisor")
    def test_supervisor_exception_fallback(self, mock_llm):
        """LLM 调用异常 → 回退到 general。"""
        mock_llm.return_value.invoke = MagicMock(
            side_effect=Exception("LLM 服务不可用")
        )

        state = _make_state()
        result = supervisor_node(state)
        assert result["agent_name"] == "general"

    @patch("app.services.agent_graph.get_llm_for_supervisor")
    def test_supervisor_empty_messages(self, mock_llm):
        """空消息列表 → 默认 general。"""
        state = _make_state(messages=[])
        result = supervisor_node(state)
        assert result["agent_name"] == "general"


# ==================== 路由函数测试 ====================

class TestRouteFunction:
    """route_after_supervisor 路由函数测试。"""

    def test_route_to_rag(self):
        state = {"agent_name": "rag"}
        assert route_after_supervisor(state) == "rag"

    def test_route_to_general(self):
        state = {"agent_name": "general"}
        assert route_after_supervisor(state) == "general"

    def test_route_default_general(self):
        state = {}
        assert route_after_supervisor(state) == "general"


# ==================== Memory Retrieval 测试 ====================

class TestMemoryRetrieval:
    """记忆检索节点测试。"""

    def test_passthrough_memories(self):
        """memory_retrieval 节点应该原样传递已加载的记忆。"""
        state = _make_state(
            mem0_memories=[{"memory": "用户喜欢中文", "score": 0.9}],
            graph_context="用户→工作→A公司",
            store_data={"language": "zh-CN"},
        )
        result = memory_retrieval_node(state)
        assert len(result["mem0_memories"]) == 1
        assert result["graph_context"] == "用户→工作→A公司"
        assert result["store_data"]["language"] == "zh-CN"

    def test_empty_memories(self):
        """无记忆时返回空值。"""
        state = _make_state()
        result = memory_retrieval_node(state)
        assert result["mem0_memories"] == []
        assert result["graph_context"] == ""
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

    def test_format_memories_all_layers(self):
        """三层记忆全部存在时正确格式化。"""
        text = _format_memories_text(
            memories=[{"memory": "用户素食"}, {"memory": "喜欢简洁回答"}],
            graph_context="张三→就职→A公司",
            store_data={"language": "zh", "style": "concise"},
        )
        assert "用户素食" in text
        assert "张三→就职→A公司" in text
        assert "language" in text

    def test_format_memories_empty(self):
        """无记忆时返回空字符串。"""
        text = _format_memories_text([], "", {})
        assert text == ""


# ==================== RAG Agent 测试 ====================

class TestRAGAgent:
    """RAG Agent 节点测试。"""

    @patch("app.services.agent_graph._retrieve_documents")
    @patch("app.services.agent_graph.get_llm")
    @pytest.mark.asyncio
    async def test_rag_agent_returns_answer(self, mock_llm, mock_retrieve):
        """RAG Agent 应返回带来源的回答。"""
        mock_retrieve.return_value = {
            "documents": ["年假5天"],
            "metadatas": [{"filename": "手册.pdf", "page": 1, "doc_id": 1}],
            "distances": [0.1],
        }
        mock_llm.return_value.invoke = MagicMock(
            return_value=_mock_llm_response("根据手册，年假为5天。")
        )

        state = _make_state(
            messages=[HumanMessage(content="年假几天？")],
            kb_ids=[1],
            original_query="年假几天？",
        )

        result = await rag_agent_node(state)
        assert "年假" in result["agent_answer"]
        assert len(result["sources"]) == 1
        assert result["sources"][0]["filename"] == "手册.pdf"

    @patch("app.services.agent_graph._retrieve_documents")
    @patch("app.services.agent_graph.get_llm")
    @pytest.mark.asyncio
    async def test_rag_agent_injects_memories(self, mock_llm, mock_retrieve):
        """RAG Agent 应注入记忆上下文。"""
        mock_retrieve.return_value = {"documents": [], "metadatas": [], "distances": []}
        mock_llm.return_value.invoke = MagicMock(
            return_value=_mock_llm_response("回答内容")
        )

        state = _make_state(
            messages=[HumanMessage(content="问题")],
            kb_ids=[1],
            original_query="问题",
            mem0_memories=[{"memory": "用户素食"}],
        )

        result = await rag_agent_node(state)
        # 验证 LLM 被调用且 prompt 中包含记忆
        call_args = mock_llm.return_value.invoke.call_args
        prompt_text = call_args[0][0][1].content
        assert "用户素食" in prompt_text


# ==================== General Agent 测试 ====================

class TestGeneralAgent:
    """General Agent 节点测试。"""

    @patch("app.services.agent_graph.get_llm")
    @pytest.mark.asyncio
    async def test_general_agent_returns_answer(self, mock_llm):
        """General Agent 应返回回答。"""
        mock_llm.return_value.invoke = MagicMock(
            return_value=_mock_llm_response("你好！有什么可以帮你的？")
        )

        state = _make_state(
            messages=[HumanMessage(content="你好")],
            original_query="你好",
        )

        result = await general_agent_node(state)
        assert "你好" in result["agent_answer"]
        assert result["sources"] == []

    @patch("app.services.agent_graph.get_llm")
    @pytest.mark.asyncio
    async def test_general_agent_with_history(self, mock_llm):
        """General Agent 应加载对话历史。"""
        mock_llm.return_value.invoke = MagicMock(
            return_value=_mock_llm_response("继续讨论")
        )

        state = _make_state(
            messages=[
                HumanMessage(content="第一轮"),
                AIMessage(content="第一轮回答"),
                HumanMessage(content="第二轮"),
            ],
            original_query="第二轮",
        )

        result = await general_agent_node(state)
        call_args = mock_llm.return_value.invoke.call_args
        prompt_text = call_args[0][0][1].content
        assert "第一轮" in prompt_text


# ==================== 图构建测试 ====================

class TestGraphBuild:
    """图构建测试。"""

    def test_graph_compiles(self):
        """图应能成功编译。"""
        graph = build_agent_graph()
        assert graph is not None

    def test_graph_has_expected_nodes(self):
        """图应包含所有预期节点。"""
        graph = build_agent_graph()
        # 编译后的图有 get_graph() 方法
        nodes = graph.get_graph().nodes
        node_names = [n.name if hasattr(n, 'name') else str(n) for n in nodes]
        assert "supervisor" in node_names or "supervisor" in str(node_names)
