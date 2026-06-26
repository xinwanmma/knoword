"""文档处理服务 — 解析、分块、向量化的完整管道。"""
import asyncio
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.models import Document
from app.services.parser import parse_document
from app.services.chunking import get_chunker
from app.services.embedding import get_embedding_provider
from app.services.vectorstore import add_documents, delete_by_doc_id

logger = logging.getLogger(__name__)


def _make_vector_id(kb_id: int, doc_id: int, chunk_index: int) -> str:
    """生成向量唯一 ID。"""
    return f"kb_{kb_id}_doc_{doc_id}_chunk_{chunk_index}"


async def process_document(doc_id: int, file_path: str):
    """异步处理单个文档：解析 → 分块 → 向量化 → 写入 ChromaDB。

    使用独立 session，状态修改后立即 commit，确保前端可实时查询状态。
    """
    from app.db.database import async_session_factory

    async with async_session_factory() as db:
        try:
            # 获取文档记录
            result = await db.execute(select(Document).where(Document.id == doc_id))
            doc = result.scalar_one_or_none()
            if doc is None:
                logger.error(f"文档不存在: doc_id={doc_id}")
                return

            # 标记为处理中
            doc.status = "processing"
            doc.error = None
            await db.commit()

            # 步骤 1：解析文档
            logger.info(f"[doc_{doc_id}] 开始解析: {doc.filename}")
            parsed = parse_document(file_path)
            logger.info(f"[doc_{doc_id}] 解析完成: {len(parsed.pages)} 页/段")

            # 步骤 2：分块（按 KB 策略）
            chunker = get_chunker(
                strategy=getattr(doc, "chunking_strategy", "recursive") or "recursive",
                chunk_size=getattr(doc, "chunk_size", None) or 500,
                chunk_overlap=getattr(doc, "chunk_overlap", None) or 50,
            )
            chunk_texts = chunker.split(parsed.full_text)
            logger.info(f"[doc_{doc_id}] 分块完成: {len(chunk_texts)} 个 chunk")

            if not chunk_texts:
                doc.status = "failed"
                doc.error = "文档内容为空，无法生成向量"
                await db.commit()
                return

            # 步骤 3：并发生成 embedding（按 KB embedding model）
            embedding_model = (
                getattr(doc, "embedding_model", None) or settings.OLLAMA_EMBED_MODEL
            )
            provider = get_embedding_provider(embedding_model)
            logger.info(
                f"[doc_{doc_id}] 开始生成 embedding ({len(chunk_texts)} chunks) "
                f"via {embedding_model}..."
            )

            semaphore = asyncio.Semaphore(4)

            async def _embed_with_limit(text: str) -> list[float]:
                async with semaphore:
                    return await provider.embed_query(text)

            embeddings_list = await asyncio.gather(
                *[_embed_with_limit(t) for t in chunk_texts]
            )

            ids = []
            documents = []
            embeddings = []
            metadatas = []

            for i, (text, embedding) in enumerate(zip(chunk_texts, embeddings_list)):
                vector_id = _make_vector_id(doc.kb_id, doc.id, i)
                ids.append(vector_id)
                documents.append(text)
                embeddings.append(embedding)
                metadatas.append({
                    "chunk_id": vector_id,  # 跟 id 保持一致，供检索时用
                    "kb_id": doc.kb_id,
                    "doc_id": doc.id,
                    "chunk_index": i,
                    "filename": doc.filename,
                    "page": 0,  # 新 chunker 切分后无页号信息
                    "start_char": 0,
                    "end_char": len(text),
                })

            # 步骤 4：写入 ChromaDB
            add_documents(ids, documents, embeddings, metadatas)

            # 更新文档状态
            doc.status = "ready"
            doc.chunk_count = len(chunk_texts)
            doc.error = None
            await db.commit()
            logger.info(f"[doc_{doc_id}] 处理完成: {len(chunk_texts)} 个 chunk 已向量化")

        except Exception as e:
            logger.error(f"[doc_{doc_id}] 处理失败: {e}", exc_info=True)
            try:
                # 重新查询并更新状态（避免使用过期对象）
                result = await db.execute(select(Document).where(Document.id == doc_id))
                doc = result.scalar_one_or_none()
                if doc is not None:
                    doc.status = "failed"
                    doc.error = str(e)[:1000]
                    await db.commit()
            except Exception as inner_e:
                logger.error(f"[doc_{doc_id}] 标记失败状态时出错: {inner_e}")


async def remove_document_vectors(doc_id: int):
    """删除文档的所有向量。"""
    delete_by_doc_id(doc_id)
    logger.info(f"已删除 doc_id={doc_id} 的所有向量")
