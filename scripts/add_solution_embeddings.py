#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
为 Neo4j 中已存在的 Solution 节点添加向量嵌入（embedding）
"""

import os
import math
from neo4j import GraphDatabase
import ollama
from dotenv import load_dotenv

load_dotenv()

# Neo4j连接配置
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")

# Ollama嵌入模型配置
OLLAMA_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "bge-m3:latest")
EMBEDDING_DIMENSION = 1024

print(f"Neo4j URI: {NEO4J_URI}")
print(f"使用 Ollama 嵌入模型: {OLLAMA_MODEL}")
print(f"嵌入维度: {EMBEDDING_DIMENSION}")


def get_embedding(text):
    """使用 Ollama 生成文本的向量嵌入"""
    if text is None:
        return None
    if isinstance(text, float):
        return None
    text = str(text).strip()
    if text == "" or text.lower() == "nan" or text == "未设置":
        return None
    
    # 清理特殊字符
    text = text.replace('\x00', '').replace('\ufeff', '')
    
    try:
        response = ollama.embeddings(model=OLLAMA_MODEL, prompt=text)
        embedding = response['embedding']
        
        # 检查嵌入向量中是否有 NaN 或 Inf 值
        if embedding and any(math.isnan(x) or math.isinf(x) for x in embedding):
            print(f"警告: 嵌入向量包含 NaN/Inf，跳过 (文本: {text[:30]}...)")
            return None
        
        return embedding
    except Exception as e:
        print(f"生成嵌入失败 (文本: {text[:50]}...): {e}")
        return None


def main():
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD), encrypted=False)
    
    try:
        with driver.session(database="neo4j") as session:
            # 1. 获取所有没有 embedding 的 Solution 节点
            print("\n=== 查询需要添加 embedding 的 Solution 节点 ===")
            result = session.run("""
                MATCH (s:Solution)
                WHERE s.embedding IS NULL
                RETURN s.id AS id, s.description AS description
            """)
            
            solutions = [(rec["id"], rec["description"]) for rec in result]
            print(f"找到 {len(solutions)} 个需要添加 embedding 的 Solution 节点")
            
            if not solutions:
                print("所有 Solution 节点已有 embedding，无需处理")
                return
            
            # 2. 为每个节点生成并更新 embedding
            print("\n=== 开始生成 embedding ===")
            success_count = 0
            fail_count = 0
            
            for i, (solution_id, description) in enumerate(solutions, 1):
                print(f"[{i}/{len(solutions)}] 处理: {description[:50]}...")
                
                embedding = get_embedding(description)
                
                if embedding:
                    # 更新节点的 embedding 属性
                    session.run("""
                        MATCH (s:Solution {id: $id})
                        SET s.embedding = $embedding
                    """, id=solution_id, embedding=embedding)
                    success_count += 1
                    print(f"  ✓ 成功 (维度: {len(embedding)})")
                else:
                    fail_count += 1
                    print(f"  ✗ 失败")
            
            # 3. 验证结果
            print("\n=== 验证结果 ===")
            result2 = session.run("""
                MATCH (s:Solution)
                WHERE s.embedding IS NOT NULL
                RETURN count(s) AS with_embedding
            """)
            rec = result2.single()
            print(f"有 embedding 的 Solution 节点: {rec['with_embedding']}")
            
            print(f"\n成功: {success_count}, 失败: {fail_count}")
            print("完成！现在 Solution 节点应该可以用于向量检索了。")
            
    finally:
        driver.close()


if __name__ == "__main__":
    main()