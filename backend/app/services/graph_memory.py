"""Memary 知识图谱记忆服务 — 实体关系网络 + 多跳推理 + 话题演化追踪。

核心概念来自 Memary：
- Memory Stream：按时间记录所有出现的实体
- Entity Knowledge Store：追踪实体的频率和最近提及时间
- Knowledge Graph：Neo4j 存储实体关系图

每个用户拥有独立的子图，通过 user_id 隔离。
"""

import logging
from datetime import datetime
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

# Neo4j 驱动实例
_driver = None


def _get_driver():
    """获取 Neo4j 驱动。"""
    global _driver
    if _driver is not None:
        return _driver

    try:
        from neo4j import GraphDatabase
        _driver = GraphDatabase.driver(
            settings.NEO4J_URL,
            auth=("neo4j", settings.NEO4J_PW),
        )
        # 验证连接
        _driver.verify_connectivity()
        logger.info("✅ Neo4j 连接成功")
        return _driver
    except Exception as e:
        logger.error(f"❌ Neo4j 连接失败: {e}")
        return None


def _close_driver():
    global _driver
    if _driver:
        _driver.close()
        _driver = None


# ==================== 实体提取 ====================

async def extract_entities(text: str) -> list[dict]:
    """用 LLM 从文本中提取实体和关系。

    Returns:
        [{"entity": "张三", "type": "PERSON", "relations": [{"type": "WORKS_AT", "target": "A公司"}]}, ...]
    """
    from app.core.llm import get_llm

    llm = get_llm(temperature=0.1)

    prompt = f"""从以下文本中提取所有命名实体和它们之间的关系。
返回 JSON 数组格式，每个元素包含：
- entity: 实体名称
- type: 实体类型 (PERSON/ORG/PROJECT/TECH/LOCATION/CONCEPT)
- relations: 关系列表，每个关系包含 type (关系类型大写下划线) 和 target (目标实体)

文本：
{text}

只返回 JSON 数组，不要其他文字。如果没有实体，返回空数组 []。"""

    try:
        from langchain_core.messages import HumanMessage
        response = await llm.ainvoke([HumanMessage(content=prompt)])
        content = response.content.strip()

        # 尝试提取 JSON
        import json
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        if content.startswith("["):
            return json.loads(content)
        return []
    except Exception as e:
        logger.error(f"实体提取失败: {e}")
        return []


# ==================== 知识图谱操作 ====================

async def add_to_graph(user_id: str, messages: list[dict]) -> dict:
    """从对话中提取实体和关系，写入 Neo4j 知识图谱。

    Args:
        user_id: 用户 ID
        messages: [{"role": "user"/"assistant", "content": "..."}]

    Returns:
        {"entities_added": int, "relations_added": int}
    """
    driver = _get_driver()
    if driver is None:
        return {"entities_added": 0, "relations_added": 0}

    # 合并消息文本
    text = "\n".join(m["content"] for m in messages if m.get("content"))
    if not text.strip():
        return {"entities_added": 0, "relations_added": 0}

    # 提取实体
    entities = await extract_entities(text)
    if not entities:
        return {"entities_added": 0, "relations_added": 0}

    entities_count = 0
    relations_count = 0
    now = datetime.utcnow().isoformat()

    with driver.session(database="neo4j") as session:
        for item in entities:
            entity_name = item.get("entity", "").strip()
            entity_type = item.get("type", "UNKNOWN")
            if not entity_name:
                continue

            # 创建或更新实体节点
            session.run(
                """
                MERGE (e:Entity {name: $name, user_id: $user_id})
                SET e.type = $type,
                    e.last_mentioned = $last_mentioned,
                    e.mention_count = COALESCE(e.mention_count, 0) + 1
                """,
                name=entity_name,
                user_id=user_id,
                type=entity_type,
                last_mentioned=now,
            )
            entities_count += 1

            # 创建关系
            for rel in item.get("relations", []):
                rel_type = rel.get("type", "RELATED_TO").upper().replace(" ", "_")
            # 清洗关系类型，防止 Cypher 注入
            import re as _re
            rel_type = _re.sub(r'[^A-Z0-9_]', '', rel_type)
            if not rel_type:
                rel_type = "RELATED_TO"
                target_name = rel.get("target", "").strip()
                if not target_name:
                    continue

                # 创建目标实体
                session.run(
                    """
                    MERGE (t:Entity {name: $name, user_id: $user_id})
                    """,
                    name=target_name,
                    user_id=user_id,
                )

                # 创建关系
                session.run(
                    f"""
                    MATCH (a:Entity {{name: $from_name, user_id: $user_id}})
                    MATCH (b:Entity {{name: $to_name, user_id: $user_id}})
                    MERGE (a)-[r:{rel_type}]->(b)
                    SET r.last_updated = $now
                    """,
                    from_name=entity_name,
                    to_name=target_name,
                    user_id=user_id,
                    now=now,
                )
                relations_count += 1

    logger.info(f"Memary 写入 user={user_id}: {entities_count} 实体, {relations_count} 关系")
    return {"entities_added": entities_count, "relations_added": relations_count}


async def search_graph(user_id: str, query: str, max_depth: int = 2) -> dict:
    """知识图谱搜索：实体识别 → 子图构建 → 上下文返回。

    Returns:
        {"entities": [...], "relations": [...], "context": "自然语言描述"}
    """
    driver = _get_driver()
    if driver is None:
        return {"entities": [], "relations": [], "context": ""}

    # 先从查询中提取关键词
    entities = await extract_entities(query)
    entity_names = [e["entity"] for e in entities if e.get("entity")]

    if not entity_names:
        # 简单分词作为备选
        entity_names = [w for w in query.split() if len(w) >= 2][:3]

    if not entity_names:
        return {"entities": [], "relations": [], "context": ""}

    result_entities = []
    result_relations = []

    with driver.session(database="neo4j") as session:
        for name in entity_names[:3]:  # 最多查 3 个实体
            # 查找实体及其 N 跳关系
            records = session.run(
                f"""
                MATCH (e:Entity {{name: $name, user_id: $user_id}})
                CALL {{
                    WITH e
                    MATCH path = (e)-[*1..{max_depth}]-(related:Entity {{user_id: $user_id}})
                    RETURN related, relationships(path) as rels, length(path) as depth
                    ORDER BY depth
                    LIMIT 20
                }}
                RETURN e.name as center, e.type as center_type,
                       related.name as related_name, related.type as related_type,
                       [r in rels | type(r)] as rel_types
                """,
                name=name,
                user_id=user_id,
            )

            for record in records:
                result_entities.append({
                    "name": record["related_name"],
                    "type": record["related_type"],
                    "relation_to_center": record["rel_types"],
                })
                # 收集关系
                for rt in record.get("rel_types", []):
                    result_relations.append({
                        "source": record["center"],
                        "type": rt,
                        "target": record["related_name"],
                    })

    # 去重
    seen = set()
    unique_entities = []
    for e in result_entities:
        key = e["name"]
        if key not in seen:
            seen.add(key)
            unique_entities.append(e)

    # 生成上下文
    context_lines = []
    for e in unique_entities[:10]:
        rels = ", ".join(e.get("relation_to_center", []))
        context_lines.append(f"- {e['name']} ({e['type']}) [关系: {rels}]")

    return {
        "entities": unique_entities[:10],
        "relations": result_relations,
        "context": "\n".join(context_lines),
    }


async def get_entity_context(user_id: str, entities: list[str]) -> str:
    """获取指定实体的关联上下文。"""
    driver = _get_driver()
    if driver is None:
        return ""

    context_parts = []
    with driver.session(database="neo4j") as session:
        for name in entities[:5]:
            records = session.run(
                """
                MATCH (e:Entity {name: $name, user_id: $user_id})-[r]-(related:Entity {user_id: $user_id})
                RETURN type(r) as rel_type, related.name as related_name, related.type as related_type
                LIMIT 10
                """,
                name=name,
                user_id=user_id,
            )
            for record in records:
                context_parts.append(
                    f"{name} --[{record['rel_type']}]--> {record['related_name']} ({record['related_type']})"
                )

    return "\n".join(context_parts)


async def get_entities(user_id: str, limit: int = 20) -> list[dict]:
    """获取用户高频实体列表。"""
    driver = _get_driver()
    if driver is None:
        return []

    with driver.session(database="neo4j") as session:
        records = session.run(
            """
            MATCH (e:Entity {user_id: $user_id})
            RETURN e.name as name, e.type as type, e.mention_count as count, e.last_mentioned as last_mentioned
            ORDER BY e.mention_count DESC
            LIMIT $limit
            """,
            user_id=user_id,
            limit=limit,
        )
        return [
            {
                "name": r["name"],
                "type": r["type"],
                "mention_count": r["count"],
                "last_mentioned": r["last_mentioned"],
            }
            for r in records
        ]


async def get_timeline(user_id: str) -> list[dict]:
    """获取实体提及的时间线（话题演化）。"""
    driver = _get_driver()
    if driver is None:
        return []

    with driver.session(database="neo4j") as session:
        records = session.run(
            """
            MATCH (e:Entity {user_id: $user_id})
            WHERE e.last_mentioned IS NOT NULL
            RETURN e.name as name, e.type as type, e.last_mentioned as time
            ORDER BY e.last_mentioned DESC
            LIMIT 30
            """,
            user_id=user_id,
        )
        return [
            {"name": r["name"], "type": r["type"], "time": r["time"]}
            for r in records
        ]


async def clear_graph(user_id: str) -> bool:
    """清空用户知识图谱数据。"""
    driver = _get_driver()
    if driver is None:
        return False

    try:
        with driver.session(database="neo4j") as session:
            session.run(
                """
                MATCH (n:Entity {user_id: $user_id})
                DETACH DELETE n
                """,
                user_id=user_id,
            )
        logger.info(f"Memary 已清空 user={user_id} 的知识图谱")
        return True
    except Exception as e:
        logger.error(f"Memary 清空失败: {e}")
        return False
