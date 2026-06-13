"""已移除。知识图谱功能不再使用。"""


async def add_to_graph(user_id: str, messages: list[dict]) -> dict:
    return {"entities_added": 0, "relations_added": 0}


async def search_graph(user_id: str, query: str, max_depth: int = 2) -> dict:
    return {"entities": [], "relations": [], "context": ""}


async def get_entities(user_id: str, limit: int = 20) -> list[dict]:
    return []


async def get_timeline(user_id: str) -> list[dict]:
    return []


async def clear_graph(user_id: str) -> bool:
    return True
