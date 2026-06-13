"""RAG 对话路由 — LangGraph + 真实流式 SSE。"""

import json
import uuid
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.database import get_db
from app.models.models import User, KnowledgeBase, Conversation, Message
from app.schemas.schemas import ChatRequest, ConversationOut, MessageOut
from app.core.security import get_current_user
from app.services.agent_graph import get_compiled_graph

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["对话"])


def _sse_event(event: str, data) -> str:
    """构造 SSE 事件字符串。"""
    if isinstance(data, (dict, list)):
        data = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {data}\n\n"


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


@router.post("")
async def chat(
    req: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """发送消息并获取流式回答（LangGraph + 真实流式）。

    流程：
    1. prepare 阶段（非流式）：Store 加载 + 缓存检查 + 路由 + 检索
    2. generate 阶段（真流式）：llm.astream 逐 token 输出
    3. postprocess 阶段：缓存保存 + 自动提取记忆

    SSE 事件：
    - agent:    当前 Agent 名称
    - sources:  RAG 引用来源
    - token:    逐 token 真实流式
    - cache:    缓存命中标记
    - done:     完成
    - error:    错误
    """

    async def event_stream():
        conversation_id = req.conversation_id
        full_answer = ""
        sources_data = []

        try:
            # 1. 加载对话历史
            history_messages = []
            if conversation_id:
                history_messages = await _load_conversation_history(conversation_id, db)

            current_message = HumanMessage(content=req.query)
            all_messages = history_messages + [current_message]

            # 2. 构建初始状态
            initial_state = {
                "messages": all_messages,
                "user_id": str(current_user.id),
                "user_name": current_user.username,
                "kb_ids": req.kb_ids or [],
                "search_all": req.search_all,
                "store_data": {},
                "agent_answer": "",
                "sources": [],
                "agent_name": "",
                "original_query": req.query,
                "from_cache": False,
            }

            # 3. 运行 prepare 阶段（发出进度事件）
            yield _sse_event("status", {"message": "正在分析意图..."})

            graph = get_compiled_graph()
            thread_id = str(current_user.id)
            config = {"configurable": {"thread_id": thread_id}}

            prepare_result = None
            async for event in graph.astream(initial_state, config, stream_mode="updates"):
                for node_name, node_output in event.items():
                    if node_name == "prepare":
                        prepare_result = node_output

            if prepare_result is None:
                yield _sse_event("error", {"message": "准备阶段失败"})
                return

            agent_name = prepare_result.get("agent_name", "general")
            from_cache = prepare_result.get("from_cache", False)
            sources_data = prepare_result.get("sources", [])

            # 4. 发送 agent 事件
            yield _sse_event("agent", {"name": agent_name})

            # 5. 缓存命中 → 直接返回答案
            if from_cache:
                full_answer = prepare_result.get("agent_answer", "")
                yield _sse_event("cache", {"hit": True})
                for char in full_answer:
                    yield _sse_event("token", char)
                    await asyncio.sleep(0)
            else:
                # 6. 真流式生成：用 llm.astream 逐 token 输出
                if sources_data:
                    yield _sse_event("sources", sources_data)

                # 重新构建完整状态用于 generate
                generate_state = {
                    **initial_state,
                    **prepare_result,
                    "messages": all_messages,
                }

                # 直接调用 llm.astream 实现真流式
                agent_name = prepare_result.get("agent_name", "general")
                store_data = prepare_result.get("store_data", {})
                query = req.query

                from app.services.agent_graph import (
                    _format_store_text, _format_sources_text, _format_history,
                    _build_rag_prompt, _build_general_prompt,
                )

                store_text = _format_store_text(store_data)
                history_text = _format_history(all_messages)

                if agent_name == "rag" and sources_data:
                    src_text = _format_sources_text({
                        "documents": [s.get("content", "") for s in sources_data],
                        "metadatas": [{"filename": s.get("filename", ""), "page": s.get("page", "?")} for s in sources_data],
                        "distances": [1.0 - s.get("score", 0) for s in sources_data],
                    })
                    prompt_messages = _build_rag_prompt(query, store_text, src_text, history_text)
                else:
                    prompt_messages = _build_general_prompt(query, store_text, history_text, current_user.username)

                from app.core.llm import get_llm
                llm = get_llm()

                async for chunk in llm.astream(prompt_messages):
                    if chunk.content:
                        full_answer += chunk.content
                        yield _sse_event("token", chunk.content)
                        await asyncio.sleep(0)

                # 7. 异步后处理（缓存 + 自动记忆）
                asyncio.create_task(_postprocess(
                    str(current_user.id), req.query, full_answer
                ))

            # 8. 保存对话到数据库
            from app.db.database import async_session_factory
            async with async_session_factory() as write_db:
                if not conversation_id:
                    conv = Conversation(
                        id=uuid.uuid4(),
                        user_id=current_user.id,
                        title=req.query[:20],
                        kb_ids=req.kb_ids if not req.search_all else [],
                    )
                    write_db.add(conv)
                    await write_db.flush()
                    conversation_id = str(conv.id)

                user_msg = Message(
                    id=uuid.uuid4(),
                    conversation_id=uuid.UUID(conversation_id),
                    role="user",
                    content=req.query,
                )
                write_db.add(user_msg)

                assistant_msg = Message(
                    id=uuid.uuid4(),
                    conversation_id=uuid.UUID(conversation_id),
                    role="assistant",
                    content=full_answer,
                    sources=sources_data if sources_data else None,
                    agent=agent_name,
                )
                write_db.add(assistant_msg)
                await write_db.commit()

            # 9. done
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


async def _postprocess(user_id: str, query: str, answer: str):
    """后处理：缓存 + 自动记忆（异步不阻塞响应）。"""
    try:
        from app.services.agent_graph import _save_to_cache, _auto_extract_and_save
        await _save_to_cache(user_id, query, answer)
        await _auto_extract_and_save(user_id, query, answer)
    except Exception as e:
        logger.error(f"Postprocess failed: {e}")


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
