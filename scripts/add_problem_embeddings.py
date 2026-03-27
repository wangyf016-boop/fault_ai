"""
给 machining 数据库中的 Problem 节点批量添加 embedding 属性，
并创建 problem_embedding 向量索引。

不需要重新导入图谱，只是在现有节点上"补"一个向量字段。
运行方式：  python scripts/add_problem_embeddings.py
"""

import os
import sys
import time

# 确保项目根目录在 sys.path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()

# ── 配置 ──────────────────────────────────────────────
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
NEO4J_USER = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "12345678")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "machining")

BATCH_SIZE = 50  # 每批写入的节点数

# ── 初始化 Embedding 模型 ─────────────────────────────
from app.retrievers.embedding import EmbeddingModel

embedder = EmbeddingModel()

# 先测一次，获取维度
test_vec = embedder.embed_query("test").tolist()
VECTOR_DIM = len(test_vec)
print(f"[INFO] Embedding 维度: {VECTOR_DIM}")

# ── 连接 Neo4j ────────────────────────────────────────
driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def get_problems_without_embedding(tx):
    """获取所有还没有 embedding 的 Problem 节点"""
    result = tx.run(
        "MATCH (p:Problem) WHERE p.embedding IS NULL "
        "RETURN elementId(p) AS eid, p.name AS name"
    )
    return [(r["eid"], r["name"] or "") for r in result]


def set_embedding(tx, eid, embedding):
    """给单个节点设置 embedding 属性"""
    tx.run(
        "MATCH (p) WHERE elementId(p) = $eid "
        "SET p.embedding = $embedding",
        eid=eid,
        embedding=embedding,
    )


def create_vector_index(session):
    """创建向量索引（如果不存在）"""
    # 先检查是否已存在
    existing = session.run("SHOW INDEXES YIELD name RETURN collect(name) AS names").single()["names"]
    if "problem_embedding" in existing:
        print("[INFO] 向量索引 problem_embedding 已存在，跳过创建")
        return

    print(f"[INFO] 创建向量索引 problem_embedding (维度={VECTOR_DIM}, cosine)...")
    session.run(
        "CREATE VECTOR INDEX problem_embedding "
        "FOR (p:Problem) ON (p.embedding) "
        "OPTIONS {indexConfig: {"
        "  `vector.dimensions`: $dim,"
        "  `vector.similarity_function`: 'cosine'"
        "}}",
        dim=VECTOR_DIM,
    )
    print("[INFO] 向量索引创建完成")


# ── 主流程 ─────────────────────────────────────────────
def main():
    with driver.session(database=NEO4J_DATABASE) as session:
        # 1. 获取需要补 embedding 的节点
        problems = session.execute_read(get_problems_without_embedding)
        total = len(problems)
        print(f"[INFO] 需要补 embedding 的 Problem 节点: {total}")

        if total == 0:
            print("[INFO] 所有节点已有 embedding，直接检查索引")
            create_vector_index(session)
            driver.close()
            return

        # 2. 批量生成 embedding 并写入
        t0 = time.time()
        done = 0
        failed = 0

        for i in range(0, total, BATCH_SIZE):
            batch = problems[i : i + BATCH_SIZE]
            for eid, name in batch:
                text = name.strip()
                if not text:
                    text = "未知问题"
                try:
                    vec = embedder.embed_query(text).tolist()
                    session.execute_write(set_embedding, eid, vec)
                    done += 1
                except Exception as e:
                    failed += 1
                    print(f"  [WARN] 节点 {eid} ({text[:30]}) 失败: {e}")

            elapsed = time.time() - t0
            speed = done / elapsed if elapsed > 0 else 0
            print(f"  进度: {done}/{total}  失败: {failed}  "
                  f"耗时: {elapsed:.1f}s  速度: {speed:.1f} nodes/s")

        t1 = time.time()
        print(f"\n[INFO] Embedding 写入完成: {done} 成功, {failed} 失败, "
              f"总耗时 {t1 - t0:.1f}s")

        # 3. 创建向量索引
        create_vector_index(session)

    driver.close()
    print("[DONE] 全部完成！")


if __name__ == "__main__":
    main()
