"""RAG 对话路由 — 流式 SSE 对话、历史管理。"""

import json
import uuid
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.database import get_db
from app.models.models import User, KnowledgeBase, Conversation, Message
from app.schemas.schemas import ChatRequest, ConversationOut, MessageOut
from app.core.security import get_current_user
from app.services.ollama_service import get_embedding, chat_stream
from app.services.vectorstore import search_documents

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["对话"])

SYSTEM_PROMPT = """你是一个知识库问答助手。请根据以下参考资料回答用户问题。
如果参考资料中没有相关信息，请如实说明"根据现有知识库资料，未找到相关信息"。
请用中文回答，保持回答准确、简洁、有条理。"""

CONTEXT_TEMPLATE = """参考资料：
{sources}

历史对话：
{history}

用户问题：{query}"""


def _format_sources_for_prompt(search_results: dict) -> str:
    """将检索结果格式化为 Prompt 中的参考资料。"""
    if not search_results["documents"]:
        return "(无相关参考资料)"

    lines = []
    for i, (doc_text, meta, dist) in enumerate(
        zip(search_results["documents"], search_results["metadatas"], search_results["distances"])
    ):
        # cosine distance → similarity score
        score = round(1 - dist, 4)
        filename = meta.get("filename", "未知文件")
        page = meta.get("page", "?")
        lines.append(f"[来源{i+1}] {filename} 第{page}页 (相关度: {score})\n{doc_text}")

    return "\n\n".join(lines)


def _format_history_for_prompt(messages: list[MessageOut]) -> str:
    """将最近 5 轮对话历史格式化为 Prompt。"""
    if not messages:
        return "(无历史对话)"

    # 取最近 5 轮（10 条消息）
    recent = messages[-10:]
    lines = []
    for msg in recent:
        role_name = "用户" if msg.role == "user" else "助手"
        lines.append(f"{role_name}: {msg.content[:200]}")

    return "\n".join(lines)


async def _get_user_accessible_kb_ids(user: User, db: AsyncSession) -> list[int]:
    """获取用户有权限访问的所有知识库 ID。"""
    query = select(KnowledgeBase.id).where(
        (KnowledgeBase.owner_id == user.id) | (KnowledgeBase.is_global == True)
    )
    if user.is_admin:
        query = select(KnowledgeBase.id)

    result = await db.execute(query)
    return [row[0] for row in result.all()]


async def _load_conversation_history(
    conversation_id: str, db: AsyncSession
) -> list[MessageOut]:
    """加载对话历史。"""
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        return []

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_uuid)
        .order_by(Message.created_at)
    )
    messages = result.scalars().all()
    return [
        MessageOut(
            id=m.id,
            role=m.role,
            content=m.content,
            sources=m.sources,
            created_at=m.created_at,
        )
        for m in messages
    ]


def _sse_event(event: str, data: str | dict) -> str:
    """构造 SSE 事件字符串。"""
    if isinstance(data, dict):
        data = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {data}\n\n"


@router.post("")
async def chat(
    req: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """发送消息并获取流式回答（SSE）。

    SSE 事件流：
    - sources: 引用来源
    - token: 逐 token 流式返回
    - done: 回答完毕
    - error: 错误
    """

    async def event_stream():
        conversation_id = req.conversation_id
        sources_data = []

        try:
            # 步骤 1：确定搜索的知识库范围
            if req.search_all:
                kb_ids = await _get_user_accessible_kb_ids(current_user, db)
            elif req.kb_ids:
                # 过滤用户有权限的知识库
                accessible = await _get_user_accessible_kb_ids(current_user, db)
                kb_ids = [kid for kid in req.kb_ids if kid in accessible]
            else:
                kb_ids = []

            # 步骤 2：检索相关文档
            search_results = {"documents": [], "metadatas": [], "distances": []}
            if kb_ids:
                query_embedding = await get_embedding(req.query)

                # 构建过滤条件
                if len(kb_ids) == 1:
                    where_filter = {"kb_id": kb_ids[0]}
                else:
                    where_filter = {"kb_id": {"$in": kb_ids}}

                search_results = search_documents(
                    query_embedding=query_embedding,
                    n_results=5,
                    where=where_filter,
                )

            # 步骤 3：构造 sources 数据
            sources_data = []
            for i, (doc_text, meta, dist) in enumerate(
                zip(
                    search_results.get("documents", []),
                    search_results.get("metadatas", []),
                    search_results.get("distances", []),
                )
            ):
                score = round(1 - dist, 4)
                sources_data.append({
                    "doc_id": meta.get("doc_id", 0),
                    "filename": meta.get("filename", ""),
                    "page": meta.get("page"),
                    "content": doc_text[:500],
                    "score": score,
                })

            # 步骤 4：发送 sources 事件（先发，前端立即渲染引用卡片）
            if sources_data:
                yield _sse_event("sources", sources_data)

            # 步骤 5：加载历史对话
            history_messages = []
            if conversation_id:
                history_messages = await _load_conversation_history(conversation_id, db)

            # 步骤 6：构造 Prompt
            context_text = _format_sources_for_prompt(search_results)
            history_text = _format_history_for_prompt(history_messages)
            user_message = CONTEXT_TEMPLATE.format(
                sources=context_text,
                history=history_text,
                query=req.query,
            )

            messages_for_llm = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ]

            # 步骤 7：流式调用 LLM
            full_answer = ""
            async for token in chat_stream(messages_for_llm):
                full_answer += token
                yield _sse_event("token", token)
                # 让出控制权，避免阻塞
                await asyncio.sleep(0)

            # 步骤 8：保存对话到数据库
            if not conversation_id:
                # 创建新会话
                conv = Conversation(
                    id=uuid.uuid4(),
                    user_id=current_user.id,
                    title=req.query[:20],
                    kb_ids=req.kb_ids if not req.search_all else [],
                )
                db.add(conv)
                await db.flush()
                conversation_id = str(conv.id)
            else:
                conv_result = await db.execute(
                    select(Conversation).where(Conversation.id == uuid.UUID(conversation_id))
                )
                conv = conv_result.scalar_one_or_none()

            # 保存用户消息
            user_msg = Message(
                id=uuid.uuid4(),
                conversation_id=uuid.UUID(conversation_id),
                role="user",
                content=req.query,
            )
            db.add(user_msg)

            # 保存助手回答
            assistant_msg = Message(
                id=uuid.uuid4(),
                conversation_id=uuid.UUID(conversation_id),
                role="assistant",
                content=full_answer,
                sources=sources_data if sources_data else None,
            )
            db.add(assistant_msg)
            await db.commit()

            # 步骤 9：发送 done 事件
            yield _sse_event("done", {"conversation_id": conversation_id})

        except Exception as e:
            logger.error(f"对话处理失败: {e}", exc_info=True)
            yield _sse_event("error", {"message": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/history", response_model=list[ConversationOut])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取当前用户的会话列表。"""
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(desc(Conversation.created_at))
        .limit(50)
    )
    convs = result.scalars().all()
    return [ConversationOut.model_validate(c) for c in convs]


@router.get("/history/{conversation_id}", response_model=list[MessageOut])
async def get_conversation_messages(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取某次对话的消息详情。"""
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的会话 ID")

    conv_result = await db.execute(
        select(Conversation).where(Conversation.id == conv_uuid)
    )
    conv = conv_result.scalar_one_or_none()

    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if conv.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权访问此会话")

    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_uuid)
        .order_by(Message.created_at)
    )
    messages = result.scalars().all()
    return [MessageOut.model_validate(m) for m in messages]


@router.delete("/history/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除某次对话。"""
    try:
        conv_uuid = uuid.UUID(conversation_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="无效的会话 ID")

    conv_result = await db.execute(
        select(Conversation).where(Conversation.id == conv_uuid)
    )
    conv = conv_result.scalar_one_or_none()

    if conv is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    if conv.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="无权删除此会话")

    await db.delete(conv)  # CASCADE 删除消息
    await db.commit()
