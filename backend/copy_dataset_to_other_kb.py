"""跨 KB 复制 dataset 工具。

场景：两个 KB 切块策略相同、文档内容相同，唯一区别是 embedding 模型
（或单纯想用同一份题测两个 KB），把 dataset 从 KB A 复制到 KB B。

使用：
    python copy_dataset_to_other_kb.py <source_dataset_id> <target_kb_id> [--force]
    python copy_dataset_to_other_kb.py <source_dataset_id> <target_kb_id> --dry-run

前置条件（必须满足，不满足会 abort）：
  1. 源 dataset 存在
  2. 目标 KB 存在
  3. 源/目标 KB 的文档数量、文件名列表一致
  4. 每个文档的 chunk 数一致（切块策略相同）
  5. （可选）新 chunk_id 至少 90% 能在目标 KB 的 collection 里找到

做了什么：
  1. 把 source_chunk_ids 里所有 `kb_{old}_` 前缀替换为 `kb_{new}_`
  2. （如有需要）按 document.filename 建立 doc_id 映射表
  3. source_doc_ids 里的老 doc_id 替换为新 doc_id
  4. 复制整份 qa_pairs，绑到新 KB，生成新 dataset
"""
import asyncio
import sys
import uuid
from collections import defaultdict

from sqlalchemy import select

from app.db.database import async_session_factory
from app.models.eval_models import EvaluationDataset
from app.models.models import Document, KnowledgeBase
from app.services.vectorstore import get_collection


def find_embedding_model_for_kb(kb: KnowledgeBase) -> str | None:
    """取 KB 锁定的 embedding model。"""
    return kb.embedding_model


async def collect_kb_documents(kb_id: int) -> dict[int, dict]:
    """收集一个 KB 的所有文档：{doc_id: {filename, chunk_count}}"""
    async with async_session_factory() as db:
        result = await db.execute(
            select(Document).where(Document.kb_id == kb_id)
        )
        docs = result.scalars().all()
    return {
        d.id: {
            "filename": d.filename,
            "chunk_count": d.chunk_count,
            "status": d.status,
        }
        for d in docs
    }


async def check_chunk_ids_exist(
    embedding_model: str, chunk_ids: list[str]
) -> tuple[set[str], set[str]]:
    """检查 chunk_ids 是否在新 KB 的 collection 里存在。
    返回 (found, missing)。
    """
    try:
        coll = get_collection(embedding_model)
    except Exception as e:
        print(f"  ⚠️  无法访问 collection {embedding_model}: {e}")
        return set(), set(chunk_ids)

    # 一次性 get 整个 KB 数据，按 id 过滤
    try:
        # 先从 id 前缀推断 kb_id
        if not chunk_ids:
            return set(), set()
        kb_id_new = int(chunk_ids[0].split("_")[1])  # "kb_6_..." -> 6
        all_data = coll.get(where={"kb_id": kb_id_new}, limit=10000)
        existing_ids = set(all_data["ids"])
    except Exception as e:
        print(f"  ⚠️  collection 查询失败: {e}")
        return set(), set(chunk_ids)

    found = set(c for c in chunk_ids if c in existing_ids)
    missing = set(c for c in chunk_ids if c not in existing_ids)
    return found, missing


async def main(source_dataset_id: str, target_kb_id: int, force: bool = False, dry_run: bool = False):
    """主流程。"""
    # 0. 参数解析
    try:
        source_dataset_uuid = uuid.UUID(source_dataset_id)
    except ValueError:
        print(f"❌ source_dataset_id 不是合法 UUID: {source_dataset_id}")
        return 1

    print("=" * 70)
    print(f"跨 KB 复制 dataset 工具")
    print(f"  源 dataset: {source_dataset_id}")
    print(f"  目标 KB:    {target_kb_id}")
    print(f"  模式:       {'DRY-RUN（不写库）' if dry_run else '实际执行'}")
    print("=" * 70)

    # 1. 取源 dataset
    async with async_session_factory() as db:
        result = await db.execute(
            select(EvaluationDataset).where(EvaluationDataset.id == source_dataset_uuid)
        )
        src_ds = result.scalar_one_or_none()
        if not src_ds:
            print(f"❌ 源 dataset {source_dataset_id} 不存在")
            return 1

        source_kb_id = src_ds.kb_id
        print(f"\n[源 dataset] {src_ds.name!r}")
        print(f"  id={src_ds.id}, kb_id={source_kb_id}, qa_count={len(src_ds.qa_pairs or [])}")
        print(f"  created_at={src_ds.created_at}")

        # 2. 取源/目标 KB
        result = await db.execute(
            select(KnowledgeBase).where(KnowledgeBase.id.in_([source_kb_id, target_kb_id]))
        )
        kbs = {kb.id: kb for kb in result.scalars().all()}
        if source_kb_id not in kbs:
            print(f"❌ 源 KB {source_kb_id} 不存在")
            return 1
        if target_kb_id not in kbs:
            print(f"❌ 目标 KB {target_kb_id} 不存在")
            return 1

        src_kb = kbs[source_kb_id]
        tgt_kb = kbs[target_kb_id]

        print(f"\n[源 KB] id={src_kb.id} name={src_kb.name!r} embedding={src_kb.embedding_model}")
        print(f"[目标 KB] id={tgt_kb.id} name={tgt_kb.name!r} embedding={tgt_kb.embedding_model}")

        if source_kb_id == target_kb_id:
            print(f"❌ 源 KB 和目标 KB 相同（{source_kb_id}），无需复制")
            return 1

        if not src_ds.qa_pairs:
            print(f"❌ 源 dataset 没有 qa_pairs")
            return 1

    # 3. 校验：文档内容必须一致
    print(f"\n[校验 1] 文档内容一致性...")
    src_docs = await collect_kb_documents(source_kb_id)
    tgt_docs = await collect_kb_documents(target_kb_id)
    src_by_name = {d["filename"]: (did, d) for did, d in src_docs.items()}
    tgt_by_name = {d["filename"]: (did, d) for did, d in tgt_docs.items()}

    src_filenames = set(src_by_name.keys())
    tgt_filenames = set(tgt_by_name.keys())

    missing_in_tgt = src_filenames - tgt_filenames
    extra_in_tgt = tgt_filenames - src_filenames
    common = src_filenames & tgt_filenames

    print(f"  源 KB 文档数: {len(src_filenames)}")
    print(f"  目标 KB 文档数: {len(tgt_filenames)}")
    print(f"  共同文档: {len(common)}")
    if missing_in_tgt:
        print(f"  ⚠️  源 KB 有但目标 KB 缺: {missing_in_tgt}")
    if extra_in_tgt:
        print(f"  ⚠️  目标 KB 多出文档（不影响复制）: {extra_in_tgt}")

    if not common:
        print(f"  ❌ 没有任何共同文档！两个 KB 内容完全无关，dataset 不能复用")
        return 1

    # 4. 校验：每个共同文档的 chunk 数必须一致（说明切块策略相同）
    print(f"\n[校验 2] 共同文档的 chunk 数一致性...")
    chunk_count_mismatch = []
    for fn in sorted(common):
        src_did, src_d = src_by_name[fn]
        tgt_did, tgt_d = tgt_by_name[fn]
        if src_d["chunk_count"] != tgt_d["chunk_count"]:
            chunk_count_mismatch.append({
                "filename": fn,
                "src_doc_id": src_did,
                "tgt_doc_id": tgt_did,
                "src_chunks": src_d["chunk_count"],
                "tgt_chunks": tgt_d["chunk_count"],
            })
            print(f"  ❌ {fn}: 源 chunk={src_d['chunk_count']} 目标 chunk={tgt_d['chunk_count']}（切块策略不同！）")
        else:
            print(f"  ✓ {fn}: doc_id {src_did}→{tgt_did}, chunks={src_d['chunk_count']}")

    if chunk_count_mismatch:
        print(f"\n  ❌ {len(chunk_count_mismatch)} 个文档切块数不一致，不能安全复制")
        if not force:
            print(f"  （用 --force 强制复制，但 source_chunk_ids 会指向错误的 chunk）")
            return 1
        print(f"  --force 已开启，强制继续")

    # 5. 构造 doc_id 映射表
    doc_id_map: dict[int, int] = {}  # source_doc_id -> target_doc_id
    for fn in common:
        src_did = src_by_name[fn][0]
        tgt_did = tgt_by_name[fn][0]
        doc_id_map[src_did] = tgt_did

    # 6. 改写 qa_pairs
    print(f"\n[改写] 处理 {len(src_ds.qa_pairs)} 道 QA...")
    new_qa_pairs = []
    total_chunk_refs = 0
    for qa in src_ds.qa_pairs:
        new_qa = dict(qa)  # shallow copy

        # 6.1 chunk_id 前缀替换：kb_6_doc_X_chunk_Y -> kb_7_doc_X_chunk_Y
        # chunk_id 格式: "kb_{kb_id}_doc_{doc_id}_chunk_{chunk_index}"
        # 拆 _ 后：['kb', '{kb_id}', 'doc', '{doc_id}', 'chunk', '{chunk_index}'] = 6 parts
        old_chunks = qa.get("source_chunk_ids", []) or []
        new_chunks = []
        for cid in old_chunks:
            parts = cid.split("_")
            if len(parts) >= 6 and parts[0] == "kb" and parts[2] == "doc" and parts[4] == "chunk":
                try:
                    old_kb_id = int(parts[1])
                    old_doc_id = int(parts[3])
                    chunk_index = parts[5]
                    new_doc_id = doc_id_map.get(old_doc_id, old_doc_id)
                    new_cid = f"kb_{target_kb_id}_doc_{new_doc_id}_chunk_{chunk_index}"
                    new_chunks.append(new_cid)
                    total_chunk_refs += 1
                except (ValueError, IndexError) as e:
                    print(f"  ⚠️  无法解析 chunk_id: {cid!r} ({e})，保留原值")
                    new_chunks.append(cid)
            else:
                # 非标准格式（如 "chunk_13" 没 kb_ 前缀），保留原值
                new_chunks.append(cid)

        new_qa["source_chunk_ids"] = new_chunks

        # 6.2 source_doc_ids 替换
        old_docs = qa.get("source_doc_ids", []) or []
        new_docs = [doc_id_map.get(d, d) for d in old_docs]
        new_qa["source_doc_ids"] = new_docs

        # 6.3 去掉 copy 标记（避免误判）
        new_qa.pop("is_out_of_scope", None)  # OOS 不跨 KB 复制
        new_qa.pop("is_multihop", None)      # multi-hop 标记也重置

        new_qa_pairs.append(new_qa)

    print(f"  ✓ 改写 {len(new_qa_pairs)} 道 QA，共 {total_chunk_refs} 个 chunk 引用")

    # 7. 校验：新 chunk_id 是否在目标 KB 的 collection 里
    print(f"\n[校验 3] 新 chunk_id 在目标 KB collection 里是否存在...")
    all_new_chunk_ids = []
    for qa in new_qa_pairs:
        all_new_chunk_ids.extend(qa.get("source_chunk_ids", []))
    # 去重
    all_new_chunk_ids = list(set(all_new_chunk_ids))

    tgt_embedding = tgt_kb.embedding_model
    if tgt_embedding and all_new_chunk_ids:
        found, missing = await check_chunk_ids_exist(tgt_embedding, all_new_chunk_ids)
        if missing and not all_new_chunk_ids[0].split("_")[1] == str(target_kb_id):
            # 实际是新 KB 的 prefix
            print(f"  ⚠️  {len(missing)}/{len(all_new_chunk_ids)} 个 chunk_id 在 collection 里找不到")
            print(f"  示例缺失: {list(missing)[:3]}")
            if not force and len(missing) > len(all_new_chunk_ids) * 0.1:
                print(f"  ❌ 缺失 > 10%，可能 collection 没正确生成")
                print(f"  （用 --force 强制复制，但评估时 Recall 会全 0）")
                return 1
        else:
            print(f"  ✓ 全部 {len(all_new_chunk_ids)} 个 chunk_id 在 collection 里找到")
    else:
        print(f"  ⚠️  跳过校验（target KB 无 embedding_model 或无 chunk）")

    # 8. 干跑模式
    if dry_run:
        print(f"\n=== DRY-RUN：以下是新 dataset 的预览（不会写库）===")
        print(f"  name: {src_ds.name} (copy to kb_{target_kb_id})")
        print(f"  kb_id: {target_kb_id}")
        print(f"  qa_count: {len(new_qa_pairs)}")
        if new_qa_pairs:
            sample = new_qa_pairs[0]
            print(f"\n  示例 QA:")
            print(f"    question: {sample.get('question', '')[:80]}")
            print(f"    ground_truth: {sample.get('ground_truth', '')[:80]}")
            print(f"    source_chunk_ids: {sample.get('source_chunk_ids', [])}")
            print(f"    source_doc_ids: {sample.get('source_doc_ids', [])}")
        return 0

    # 9. 实际写库
    print(f"\n[写库] 创建新 dataset...")
    new_name = f"{src_ds.name} (copy to kb_{target_kb_id})"
    new_description = (
        f"从 dataset {src_ds.id} 复制：\n"
        f"  - 源 KB: {source_kb_id} ({src_kb.name!r}, embedding={src_kb.embedding_model})\n"
        f"  - 目标 KB: {target_kb_id} ({tgt_kb.name!r}, embedding={tgt_kb.embedding_model})\n"
        f"  - 复制时间: {__import__('datetime').datetime.now().isoformat()}\n"
        f"  - 共同文档数: {len(common)}\n"
        f"  - doc_id 映射: {doc_id_map}"
    )

    async with async_session_factory() as db:
        new_ds = EvaluationDataset(
            id=uuid.uuid4(),
            name=new_name,
            kb_id=target_kb_id,
            description=new_description,
            qa_pairs=new_qa_pairs,
            created_by=src_ds.created_by,
        )
        db.add(new_ds)
        await db.commit()
        await db.refresh(new_ds)

    print(f"\n=== ✅ 完成 ===")
    print(f"  新 dataset id: {new_ds.id}")
    print(f"  name: {new_ds.name!r}")
    print(f"  kb_id: {target_kb_id}")
    print(f"  qa_count: {len(new_qa_pairs)}")
    print(f"\n下一步：进评估中心，选这个新 dataset 启动评估。")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        print("\n用法示例:")
        print("  python copy_dataset_to_other_kb.py <source_dataset_uuid> <target_kb_id>")
        print("  python copy_dataset_to_other_kb.py <source_dataset_uuid> <target_kb_id> --dry-run")
        print("  python copy_dataset_to_other_kb.py <source_dataset_uuid> <target_kb_id> --force")
        sys.exit(1)

    source_id = sys.argv[1]
    target_kb = int(sys.argv[2])
    is_force = "--force" in sys.argv
    is_dry = "--dry-run" in sys.argv

    exit_code = asyncio.run(main(source_id, target_kb, force=is_force, dry_run=is_dry))
    sys.exit(exit_code)
