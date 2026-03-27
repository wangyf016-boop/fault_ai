"""快速清空Neo4j数据库脚本"""
from neo4j import GraphDatabase

# 配置
URI = "bolt://localhost:7687"
USERNAME = "neo4j"
PASSWORD = "password"
DATABASE = "neo4j"

print("🗑️ 连接到Neo4j...")
driver = GraphDatabase.driver(URI, auth=(USERNAME, PASSWORD))

with driver.session(database=DATABASE) as session:
    # 检查当前节点数
    result = session.run("MATCH (n) RETURN count(n) as count")
    before_count = result.single()['count']
    print(f"📊 当前节点数: {before_count}")
    
    if before_count > 0:
        print("\n🗑️ 清空所有节点和关系...")
        session.run("MATCH (n) DETACH DELETE n")
        print("✅ 清空完成")
        
        # 验证
        result = session.run("MATCH (n) RETURN count(n) as count")
        after_count = result.single()['count']
        print(f"📊 剩余节点: {after_count}")
    else:
        print("✅ 数据库已经是空的")

driver.close()
print("\n✅ 完成！现在可以重新导入数据")
