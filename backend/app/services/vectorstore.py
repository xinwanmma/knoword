"""ChromaDB 向量数据库集成。

Collection 分桶策略（按 embedding_model 物理隔离）：
- 每个 embedding model 一个 collection：kb_emb_{safe_name}
- 同一 embedding model 的多个 KB 共享 collection（可跨 KB 检索，where kb_id 过滤）
- 不同 embedding model 物理隔离 → 避免维度冲突

Collection 命名规范：
- `qwen3-embedding:0.6b` → `kb_emb_qwen3_embedding_0_6b`
- `Qwen/Qwen3-Embedding-8B` → `kb_emb_Qwen_Qwen3_Embedding_8B`
- `shibing624/text2vec-base-chinese` → `kb_emb_shibing624_text2vec_base_chinese`

迁移：
- 老 collection `all_documents` 里的数据需要跑 `migrate_chromadb_collections.py` 重写到新 collection
- 迁移完成后老 collection 可清空
"""

import logging
import re

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import settings

logger = logging.getLogger(__name__)

_client: chromadb.ClientAPI | None = None
_collections: dict[str, chromadb.Collection] = {}  # safe_name -> Collection

# 老 collection 名（兼容旧数据；新代码不再写入此 collection）
LEGACY_COLLECTION_NAME = "all_documents"
# 新 collection 名前缀
COLLECTION_PREFIX = "kb_emb_"
# 默认 embedding model（None 时 fallback）
DEFAULT_EMBEDDING_MODEL = "qwen3-embedding:0.6b"


def get_chroma_client() -> chromadb.ClientAPI:
    """获取 ChromaDB 客户端（单例）。"""
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(
            path=settings.CHROMADB_PATH,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
        logger.info(f"ChromaDB 已连接: {settings.CHROMADB_PATH}")
    return _client


def _safe_name(embedding_model: str) -> str:
    """把 embedding model 名字转成合法 collection 名（只保留 [A-Za-z0-9_]）。"""
    name = re.sub(r"[^A-Za-z0-9_]", "_", embedding_model)
    name = re.sub(r"_+", "_", name)
    return name.strip("_")


def _collection_name(embedding_model: str | None) -> str:
    """生成 collection name：kb_emb_{safe_name}"""
    em = embedding_model or DEFAULT_EMBEDDING_MODEL
    return f"{COLLECTION_PREFIX}{_safe_name(em)}"


def get_collection(embedding_model: str | None = None) -> chromadb.Collection:
    """按 embedding_model 取/创建 collection（单例缓存）。

    embedding_model=None 时 fallback 到默认 0.6b 的 collection。
    """
    em = embedding_model or DEFAULT_EMBEDDING_MODEL
    safe = _safe_name(em)
    if safe in _collections:
        return _collections[safe]
    client = get_chroma_client()
    name = f"{COLLECTION_PREFIX}{safe}"
    collection = client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )
    _collections[safe] = collection
    logger.info(
        f"ChromaDB collection 就绪: {name} (embedding={em}), 当前文档数: {collection.count()}"
    )
    return collection


def add_documents(
    ids: list[str],
    documents: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict],
    embedding_model: str | None = None,
):
    """向 ChromaDB 中添加文档向量（按 embedding_model 路由 collection）。

    Args:
        ids: 每条向量的唯一 ID（格式: "kb_{kb_id}_doc_{doc_id}_chunk_{i}"）
        documents: 文本内容
        embeddings: embedding 向量
        metadatas: 元数据
        embedding_model: 该文档用的 embedding model（决定走哪个 collection）
    """
    collection = get_collection(embedding_model)
    # ChromaDB 单次批量上限，分批写入
    batch_size = 100
    for i in range(0, len(ids), batch_size):
        end = min(i + batch_size, len(ids))
        collection.add(
            ids=ids[i:end],
            documents=documents[i:end],
            embeddings=embeddings[i:end],
            metadatas=metadatas[i:end],
        )
    em = embedding_model or DEFAULT_EMBEDDING_MODEL
    logger.info(f"已向 ChromaDB [{_collection_name(em)}] 写入 {len(ids)} 条向量")


def search_documents(
    query_embedding: list[float],
    n_results: int = 5,
    where: dict | None = None,
    embedding_model: str | None = None,
) -> dict:
    """在 ChromaDB 中搜索相似文档（按 embedding_model 路由 collection）。

    Args:
        query_embedding: 查询向量（必须用与目标 KB 文档相同的 embedding model 生成）
        n_results: 返回结果数
        where: metadata 过滤条件（如 {"kb_id": {"$in": [1, 2, 3]}}）
        embedding_model: 路由到哪个 collection（必须与 query_embedding 维度一致）

    Returns:
        {"ids": [...], "documents": [...], "metadatas": [...], "distances": [...]}
    """
    collection = get_collection(embedding_model)
    kwargs = {
        "query_embeddings": [query_embedding],
        "n_results": n_results,
    }
    if where:
        kwargs["where"] = where

    results = collection.query(**kwargs)

    # 解包单查询结果（query 返回的是嵌套列表）
    return {
        "ids": results["ids"][0] if results["ids"] else [],
        "documents": results["documents"][0] if results["documents"] else [],
        "metadatas": results["metadatas"][0] if results["metadatas"] else [],
        "distances": results["distances"][0] if results["distances"] else [],
    }


def delete_by_kb_id(kb_id: int, embedding_model: str | None = None):
    """删除指定知识库的所有向量。

    embedding_model=None 时遍历所有 collection 删除（用于彻底清理）。
    embedding_model 指定时只清该 collection。
    """
    if embedding_model:
        _delete_from_one(get_collection(embedding_model), kb_id, "kb_id", embedding_model)
        return
    # 遍历所有 collection
    client = get_chroma_client()
    for coll in client.list_collections():
        _delete_from_one(coll, kb_id, "kb_id", coll.name)


def delete_by_doc_id(doc_id: int, embedding_model: str | None = None):
    """删除指定文档的所有向量。"""
    if embedding_model:
        _delete_from_one(get_collection(embedding_model), doc_id, "doc_id", embedding_model)
        return
    client = get_chroma_client()
    for coll in client.list_collections():
        _delete_from_one(coll, doc_id, "doc_id", coll.name)


def _delete_from_one(collection, value, field, label):
    """从单个 collection 按 field=value 删除。"""
    try:
        collection.delete(where={field: value})
        logger.info(f"已从 ChromaDB [{label}] 删除 {field}={value} 的所有向量")
    except Exception as e:
        logger.warning(f"ChromaDB [{label}] 删除 {field}={value} 失败（可能无数据）: {e}")


def check_chromadb() -> bool:
    """检查 ChromaDB 是否可用。"""
    try:
        client = get_chroma_client()
        client.heartbeat()
        return True
    except Exception:
        return False
