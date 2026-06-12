"""RAG 对话路由 — LangGraph 多 Agent + 三层记忆 + SSE 流式。"""

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
    if isinstance(data, dict) or isinstance(data, list):
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


async def _load_memories(user_id: str, query: str) -> dict:
    """并行加载三层记忆。"""
    mem0_memories = []
    graph_context = ""
    store_data = {}

    tasks = []

    # 异步空操作函数
    async def _noop_list():
        return []

    async def _noop_dict_ctx():
        return {"context": ""}

    async def _noop_dict():
        return {}

    # Mem0
    if settings.MEM0_ENABLED:
        from app.services.memory_service import search_memories
        tasks.append(search_memories(user_id, query, top_k=5))
    else:
        tasks.append(_noop_list())

    # Memary
    if settings.MEMARY_ENABLED:
        from app.services.graph_memory import search_graph
        tasks.append(search_graph(user_id, query))
    else:
        tasks.append(_noop_dict_ctx())

    # Store
    if settings.STORE_ENABLED:
        from app.db.database import async_session_factory
        from app.services.store_service import store_get_all

        async def _load_store():
            async with async_session_factory() as db:
                entries = await store_get_all(db, user_id)
                return {e["key"]: e["value"] for e in entries}

        tasks.append(_load_store())
    else:
        tasks.append(_noop_dict())

    results = await asyncio.gather(*tasks, return_exceptions=True)

    if not isinstance(results[0], Exception):
        mem0_memories = results[0] if isinstance(results[0], list) else []
    if not isinstance(results[1], Exception):
        r1 = results[1]
        graph_context = r1.get("context", "") if isinstance(r1, dict) else ""
    if not isinstance(results[2], Exception):
        store_data = results[2] if isinstance(results[2], dict) else {}

    return {
        "mem0_memories": mem0_memories,
        "graph_context": graph_context,
        "store_data": store_data,
    }


async def _update_memories(user_id: str, query: str, answer: str):
    """异步更新三层记忆（不阻塞响应）。"""
    messages = [
        {"role": "user", "content": query},
        {"role": "assistant", "content": answer},
    ]

    try:
        if settings.MEM0_ENABLED:
            from app.services.memory_service import add_memory
            await add_memory(user_id, messages)
    except Exception as e:
        logger.error(f"Mem0 记忆写入失败: {e}")

    try:
        if settings.MEMARY_ENABLED:
            from app.services.graph_memory import add_to_graph
            await add_to_graph(user_id, messages)
    except Exception as e:
        logger.error(f"Memary 图谱写入失败: {e}")


@router.post("")
async def chat(
    req: ChatRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """发送消息并获取流式回答（LangGraph + SSE）。

    SSE 事件流：
    - agent:    当前处理的 Agent 名称
    - sources:  RAG 引用来源
    - memories: 命中的记忆摘要
    - token:    逐 token 流式返回
    - done:     回答完毕
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

            # 2. 构建当前消息
            current_message = HumanMessage(content=req.query)
            all_messages = history_messages + [current_message]

            # 3. 加载三层记忆
            memories = await _load_memories(str(current_user.id), req.query)

            # 4. 构建初始状态
            initial_state = {
                "messages": all_messages,
                "user_id": str(current_user.id),
                "user_name": current_user.username,
                "kb_ids": req.kb_ids or [],
                "search_all": req.search_all,
                "mem0_memories": memories["mem0_memories"],
                "graph_context": memories["graph_context"],
                "store_data": memories["store_data"],
                "agent_answer": "",
                "sources": [],
                "agent_name": "",
                "original_query": req.query,
            }

            # 5. 运行 Agent 图（流式输出 token）
            graph = get_compiled_graph()
            thread_id = str(current_user.id)
            config = {"configurable": {"thread_id": thread_id}}

            agent_name = ""
            async for event in graph.astream(initial_state, config, stream_mode="updates"):
                for node_name, node_output in event.items():
                    if node_name == "supervisor":
                        agent_name = node_output.get("agent_name", "general")
                        yield _sse_event("agent", {"name": agent_name})

                    elif node_name in ("rag_agent", "general_agent"):
                        agent_answer = node_output.get("agent_answer", "")
                        sources_data = node_output.get("sources", [])
                        full_answer = agent_answer

                        # 发送 sources
                        if sources_data:
                            yield _sse_event("sources", sources_data)

                        # 逐 token 流式发送（按字符分割模拟流式）
                        for char in agent_answer:
                            yield _sse_event("token", char)
                            await asyncio.sleep(0)

            # 6. 保存对话到数据库（使用新 session，避免 StreamingResponse 竞态）
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

                # 保存用户消息
                user_msg = Message(
                    id=uuid.uuid4(),
                    conversation_id=uuid.UUID(conversation_id),
                    role="user",
                    content=req.query,
                )
                write_db.add(user_msg)

                # 保存助手回答
                assistant_msg = Message(
                    id=uuid.uuid4(),
                    conversation_id=uuid.UUID(conversation_id),
                    role="assistant",
                    content=full_answer,
                    sources=sources_data if sources_data else None,
                )
                write_db.add(assistant_msg)
                await write_db.commit()

            # 7. 异步更新三层记忆
            asyncio.create_task(_update_memories(
                str(current_user.id), req.query, full_answer
            ))

            # 8. 发送 done 事件
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

    await db.delete(conv)
    await db.commit()
