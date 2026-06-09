"""ChromaDB 向量数据库集成。"""

import logging
import chromadb
from chromadb.config import Settings as ChromaSettings

from app.config import settings

logger = logging.getLogger(__name__)

_client: chromadb.ClientAPI | None = None
_collection: chromadb.Collection | None = None

COLLECTION_NAME = "all_documents"


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


def get_collection() -> chromadb.Collection:
    """获取统一文档 collection（单例）。"""
    global _collection
    if _collection is None:
        client = get_chroma_client()
        _collection = client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(f"ChromaDB collection 就绪: {COLLECTION_NAME}, 当前文档数: {_collection.count()}")
    return _collection


def add_documents(
    ids: list[str],
    documents: list[str],
    embeddings: list[list[float]],
    metadatas: list[dict],
):
    """向 ChromaDB 中添加文档向量。

    Args:
        ids: 每条向量的唯一 ID（格式: "kb_{kb_id}_doc_{doc_id}_chunk_{i}"）
        documents: 文本内容
        embeddings: embedding 向量
        metadatas: 元数据
    """
    collection = get_collection()
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
    logger.info(f"已向 ChromaDB 写入 {len(ids)} 条向量")


def search_documents(
    query_embedding: list[float],
    n_results: int = 5,
    where: dict | None = None,
) -> dict:
    """在 ChromaDB 中搜索相似文档。

    Args:
        query_embedding: 查询向量
        n_results: 返回结果数
        where: metadata 过滤条件（如 {"kb_id": {"$in": [1, 2, 3]}}）

    Returns:
        {"ids": [...], "documents": [...], "metadatas": [...], "distances": [...]}
    """
    collection = get_collection()
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


def delete_by_kb_id(kb_id: int):
    """删除指定知识库的所有向量。"""
    collection = get_collection()
    try:
        collection.delete(where={"kb_id": kb_id})
        logger.info(f"已从 ChromaDB 删除 kb_id={kb_id} 的所有向量")
    except Exception as e:
        logger.warning(f"ChromaDB 删除 kb_id={kb_id} 失败（可能无数据）: {e}")


def delete_by_doc_id(doc_id: int):
    """删除指定文档的所有向量。"""
    collection = get_collection()
    try:
        collection.delete(where={"doc_id": doc_id})
        logger.info(f"已从 ChromaDB 删除 doc_id={doc_id} 的所有向量")
    except Exception as e:
        logger.warning(f"ChromaDB 删除 doc_id={doc_id} 失败: {e}")


def check_chromadb() -> bool:
    """检查 ChromaDB 是否可用。"""
    try:
        client = get_chroma_client()
        client.heartbeat()
        return True
    except Exception:
        return False
