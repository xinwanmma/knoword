"""RAG 对话路由 — LangChain LCEL 风格 + 真实流式 SSE。

设计要点：
- 权限安全：对话前校验用户对请求中 KB 的所有权
- 独立 session：SSE 流式响应全程在 event_stream 内部创建/释放 session，
  避免 Depends(get_db) 注入的 session 在长流式期间被长期持有（连接池耗尽）
- 真实流式：llm.astream() 逐 token 输出
- 无 LangGraph：直接调用 retrieval_pipeline.prepare_sources()
"""

import asyncio
import json
import logging
import uuid
from typing import Set

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import get_current_user
from app.db.database import async_session_factory, get_db
from app.models.models import Conversation, KnowledgeBase, Message, User
from app.schemas.schemas import ChatRequest, ConversationOut, MessageOut
from app.services.llm_provider import get_llm_provider
from app.services.retrieval_pipeline import prepare_sources

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["对话"])

# 持有后台 Task 引用，防止 GC 回收
_background_tasks: Set[asyncio.Task] = set()


# ==================== 辅助函数 ====================

def _sse_event(event: str, data) -> str:
    """构造 SSE 事件字符串。"""
    if isinstance(data, (dict, list)):
        data = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {data}\n\n"


def _format_sources_text(sources: list[dict]) -> str:
    """将检索结果格式化为 Prompt 文本。"""
    if not sources:
        return "(无相关参考资料)"

    lines = []
    for i, s in enumerate(sources):
        score = round(s.get("score", 0), 4)
        filename = s.get("filename", "未知文件")
        page = s.get("page", "?")
        content = s.get("content", "")
        lines.append(f"[来源{i+1}] {filename} 第{page}页 (相关度: {score})\n{content}")
    return "\n\n".join(lines)


def _format_history(messages: list) -> str:
    """格式化对话历史。"""
    lines = []
    for m in messages[-10:]:
        if isinstance(m, HumanMessage):
            lines.append(f"用户: {m.content[:200]}")
        elif isinstance(m, AIMessage):
            lines.append(f"助手: {m.content[:200]}")
    return "\n".join(lines)


async def _load_conversation_history(
    conversation_id: str, db: AsyncSession
) -> list[HumanMessage | AIMessage]:
    """加载对话历史为 LangChain 消息格式。"""
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

    lc_messages = []
    for m in messages:
        if m.role == "user":
            lc_messages.append(HumanMessage(content=m.content))
        elif m.role == "assistant":
            lc_messages.append(AIMessage(content=m.content))
    return lc_messages


async def _validate_kb_access(
    kb_ids: list[int], user_id: uuid.UUID, db: AsyncSession
) -> list[int]:
    """校验用户对请求中 KB 集合的访问权限，返回有效 KB ID 列表。

    Raises:
        HTTPException: 当用户请求访问不属于自己的 KB 时
    """
    if not kb_ids:
        return []

    result = await db.execute(
        select(KnowledgeBase.id).where(
            KnowledgeBase.id.in_(kb_ids),
            KnowledgeBase.owner_id == user_id,
        )
    )
    valid_ids = {row[0] for row in result.all()}
    invalid = set(kb_ids) - valid_ids
    if invalid:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"无权访问知识库: {sorted(invalid)}",
        )
    return list(valid_ids)


# ==================== 路由 ====================

@router.post("")
async def chat(
    req: ChatRequest,
    current_user: User = Depends(get_current_user),
):
    """发送消息并获取流式回答。

    流程：
    1. 校验 KB 权限（前置失败立即返回 403）
    2. 准备阶段（非流式）：向量检索 → Rerank
    3. 生成阶段（真流式）：llm.astream 逐 token 输出
    4. 保存：用户消息 + AI 回答入库

    SSE 事件：
    - status:  状态更新
    - sources: 检索引用来源
    - token:   逐 token 真实流式
    - done:    完成（含 conversation_id）
    - error:   错误
    """

    async def event_stream():
        full_answer = ""
        sources_data: list[dict] = []
        conversation_id = req.conversation_id

        # 整个 SSE 生命周期使用独立 session，避免占用 Depends 注入的会话
        async with async_session_factory() as db:
            try:
                # 1. 校验 KB 权限
                if req.kb_ids and not req.search_all:
                    await _validate_kb_access(req.kb_ids, current_user.id, db)
                elif req.search_all:
                    # 搜索全部时，查找当前用户的所有 KB
                    result = await db.execute(
                        select(KnowledgeBase.id).where(
                            KnowledgeBase.owner_id == current_user.id
                        )
                    )
                    req.kb_ids = [row[0] for row in result.all()]

                # 2. 加载对话历史
                history_messages = []
                if conversation_id:
                    history_messages = await _load_conversation_history(conversation_id, db)

                current_message = HumanMessage(content=req.query)
                all_messages = history_messages + [current_message]

                # 3. 检索（直接调用 retrieval_pipeline，替代 LangGraph）
                yield _sse_event("status", {"message": "正在检索相关资料..."})

                sources_data = await prepare_sources(
                    query=req.query,
                    kb_ids=req.kb_ids or [],
                    search_all=req.search_all,
                    top_k=5,
                )

                if sources_data:
                    yield _sse_event("sources", sources_data)

                # 4. 构建 prompt
                sources_text = _format_sources_text(sources_data)
                history_text = _format_history(all_messages)

                history_block = f"\n\n历史对话：\n{history_text}" if history_text else ""
                sources_block = f"\n\n参考资料：\n{sources_text}" if sources_data else ""

                system_prompt = f"""你是一个知识库问答助手。请根据以下参考资料回答用户问题。
如果资料中没有相关信息，请如实说明，不要编造。
请用中文回答，保持准确、简洁、有条理。{sources_block}{history_block}

用户问题：{req.query}"""

                # 5. 流式生成
                yield _sse_event("status", {"message": "正在生成回答..."})

                llm = get_llm_provider().get_chat_model()
                async for chunk in llm.astream([HumanMessage(content=system_prompt)]):
                    if chunk.content:
                        full_answer += chunk.content
                        yield _sse_event("token", chunk.content)
                        await asyncio.sleep(0)

                # 6. 保存到数据库（使用同一 session 减少连接浪费）
                if not conversation_id:
                    conv = Conversation(
                        id=uuid.uuid4(),
                        user_id=current_user.id,
                        title=req.query[:20] or "新对话",
                        kb_ids=req.kb_ids if not req.search_all else [],
                    )
                    db.add(conv)
                    await db.flush()
                    conversation_id = str(conv.id)

                db.add(Message(
                    id=uuid.uuid4(),
                    conversation_id=uuid.UUID(conversation_id),
                    role="user",
                    content=req.query,
                ))
                db.add(Message(
                    id=uuid.uuid4(),
                    conversation_id=uuid.UUID(conversation_id),
                    role="assistant",
                    content=full_answer,
                    sources=sources_data if sources_data else None,
                ))
                await db.commit()

                yield _sse_event("done", {"conversation_id": conversation_id})

            except HTTPException as he:
                yield _sse_event("error", {"message": he.detail})
            except Exception as e:
                logger.error(f"对话处理失败: {e}", exc_info=True)
                yield _sse_event("error", {"message": str(e)})
                await db.rollback()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ==================== 对话历史接口 ====================

@router.get("/history", response_model=list[ConversationOut])
async def list_conversations(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    limit: int = 50,
    offset: int = 0,
):
    """获取当前用户的会话列表（分页）。"""
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == current_user.id)
        .order_by(desc(Conversation.created_at))
        .offset(offset)
        .limit(min(limit, 100))
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

    await db.delete(conv)
    await db.commit()
