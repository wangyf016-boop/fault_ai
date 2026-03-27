"""给 Neo4j 关系补写统一 row_id / row_ids 字段。

规则：
- row_ids: 直接来自 source_rows（清洗空值）
- row_id: 当且仅当 row_ids 长度为 1 时写入该值；否则置空

用途：
- 让查询层可以统一使用 row_id / row_ids，而不是混用旧字段。
"""

from __future__ import annotations

import os
from neo4j import GraphDatabase


def main() -> None:
    uri = os.getenv("NEO4J_URI", "bolt://127.0.0.1:7687")
    user = os.getenv("NEO4J_USERNAME", "neo4j")
    pwd = os.getenv("NEO4J_PASSWORD", "12345678")
    db = os.getenv("NEO4J_DATABASE", "machining")

    driver = GraphDatabase.driver(uri, auth=(user, pwd))
    try:
        cypher = """
MATCH ()-[r]->()
WITH r,
     [x IN coalesce(r.source_rows, [])
      WHERE x IS NOT NULL AND trim(toString(x)) <> ''
      | toString(x)] AS cleaned
SET r.row_ids = cleaned,
    r.row_id = CASE WHEN size(cleaned) = 1 THEN cleaned[0] ELSE NULL END
RETURN count(r) AS total,
       count(CASE WHEN r.row_id IS NOT NULL THEN 1 END) AS single_row_id,
       count(CASE WHEN r.row_ids IS NOT NULL AND size(r.row_ids) > 0 THEN 1 END) AS row_ids_filled
"""
        with driver.session(database=db) as session:
            rec = session.run(cypher).single()
            print({
                "total": rec["total"],
                "single_row_id": rec["single_row_id"],
                "row_ids_filled": rec["row_ids_filled"],
            })
    finally:
        driver.close()


if __name__ == "__main__":
    main()
