"""混合检索 + Reranker 测试。"""

import pytest
from unittest.mock import patch, AsyncMock
from app.services.hybrid_search import (
    _tokenize_chinese, _bm25_score, _simple_similarity
)
from app.services.agent_graph import _simple_similarity as graph_similarity


class TestTokenize:
    """中文分词测试。"""

    def test_basic_chinese(self):
        tokens = _tokenize_chinese("年假有几天")
        assert "年假有几天" in tokens
        assert len(tokens) > 0

    def test_mixed_text(self):
        tokens = _tokenize_chinese("Python是最好的语言")
        assert len(tokens) > 0

    def test_empty_text(self):
        tokens = _tokenize_chinese("")
        assert tokens == []


class TestBM25:
    """BM25 评分测试。"""

    def test_exact_match(self):
        query_tokens = ["年假"]
        doc_tokens = ["年假", "有", "几天"]
        score = _bm25_score(query_tokens, doc_tokens)
        assert score > 0

    def test_no_match(self):
        query_tokens = ["请假"]
        doc_tokens = ["年假", "有", "几天"]
        score = _bm25_score(query_tokens, doc_tokens)
        assert score == 0.0

    def test_empty_query(self):
        score = _bm25_score([], ["test"])
        assert score == 0.0


class TestSimilarity:
    """相似度测试。"""

    def test_identical(self):
        assert _simple_similarity("年假政策", "年假政策") == 1.0

    def test_partial_overlap(self):
        score = _simple_similarity("年假政策说明", "年假有几天")
        assert 0 < score < 1

    def test_no_overlap(self):
        score = _simple_similarity("今天天气", "年假政策")
        assert score == 0.0

    def test_empty(self):
        assert _simple_similarity("", "test") == 0.0
        assert _simple_similarity("test", "") == 0.0

    def test_graph_version_matches(self):
        """agent_graph._simple_similarity 应该行为一致。"""
        assert graph_similarity("年假政策", "年假政策") == 1.0
        assert graph_similarity("", "test") == 0.0
