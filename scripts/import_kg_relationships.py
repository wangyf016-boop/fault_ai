"""
Import relationships from KG JSON into Neo4j.
This script creates:
  - Problem -[HAS_CAUSE]-> Cause
  - Cause -[HAS_SOLUTION]-> Solution
by matching nodes on their 'name' property.
"""
from neo4j import GraphDatabase
import json
import os

# Neo4j connection
URI = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
USER = os.getenv('NEO4J_USER', 'neo4j')
PWD = os.getenv('NEO4J_PASSWORD', 'password')

# KG JSON path
KG_PATH = r'C:\Users\Aumovio\Desktop\bert_crf\data\output\knowledge_graph\2024_data\kg_2024.json'


def load_kg():
    with open(KG_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def main():
    print("Loading KG JSON...")
    kg = load_kg()
    
    # Build id -> name mappings
    phenomena = kg.get('phenomena', {})
    causes = kg.get('causes', {})
    solutions = kg.get('solutions', {})
    
    # phenomena use 'name', causes/solutions use 'text'
    phen_id_to_name = {v['id']: v['name'] for v in phenomena.values()}
    cause_id_to_name = {v['id']: v.get('text') or v.get('name') for v in causes.values()}
    sol_id_to_name = {v['id']: v.get('text') or v.get('name') for v in solutions.values()}
    
    print(f"Phenomena (Problems): {len(phen_id_to_name)}")
    print(f"Causes: {len(cause_id_to_name)}")
    print(f"Solutions: {len(sol_id_to_name)}")
    
    # Extract relationships
    rels = kg.get('relationships', [])
    has_cause_rels = [r for r in rels if r['type'] == 'has_cause']
    has_solution_rels = [r for r in rels if r['type'] == 'has_solution']
    
    print(f"has_cause relationships: {len(has_cause_rels)}")
    print(f"has_solution relationships: {len(has_solution_rels)}")
    
    driver = GraphDatabase.driver(URI, auth=(USER, PWD))
    
    # Import Problem -> Cause relationships
    print("\n--- Importing Problem -[HAS_CAUSE]-> Cause ---")
    success_pc, fail_pc = 0, 0
    with driver.session(database='neo4j') as session:
        for i, rel in enumerate(has_cause_rels):
            from_id = rel['from']  # phenomenon_X
            to_id = rel['to']      # cause_X
            
            phen_name = phen_id_to_name.get(from_id)
            cause_name = cause_id_to_name.get(to_id)
            
            if not phen_name or not cause_name:
                fail_pc += 1
                continue
            
            try:
                result = session.run("""
                    MATCH (p:Problem {name: $phen_name})
                    MATCH (c:Cause {name: $cause_name})
                    MERGE (p)-[r:HAS_CAUSE]->(c)
                    RETURN count(r) AS cnt
                """, phen_name=phen_name, cause_name=cause_name)
                cnt = result.single()['cnt']
                if cnt > 0:
                    success_pc += 1
                else:
                    fail_pc += 1
            except Exception as e:
                fail_pc += 1
                if fail_pc <= 5:
                    print(f"  Error: {e}")
            
            if (i + 1) % 1000 == 0:
                print(f"  Progress: {i+1}/{len(has_cause_rels)} (success: {success_pc}, fail: {fail_pc})")
    
    print(f"Problem->Cause: success={success_pc}, fail={fail_pc}")
    
    # Import Cause -> Solution relationships
    print("\n--- Importing Cause -[HAS_SOLUTION]-> Solution ---")
    success_cs, fail_cs = 0, 0
    with driver.session(database='neo4j') as session:
        for i, rel in enumerate(has_solution_rels):
            from_id = rel['from']  # cause_X
            to_id = rel['to']      # solution_X
            
            cause_name = cause_id_to_name.get(from_id)
            sol_name = sol_id_to_name.get(to_id)
            
            if not cause_name or not sol_name:
                fail_cs += 1
                continue
            
            try:
                result = session.run("""
                    MATCH (c:Cause {name: $cause_name})
                    MATCH (s:Solution {name: $sol_name})
                    MERGE (c)-[r:HAS_SOLUTION]->(s)
                    RETURN count(r) AS cnt
                """, cause_name=cause_name, sol_name=sol_name)
                cnt = result.single()['cnt']
                if cnt > 0:
                    success_cs += 1
                else:
                    fail_cs += 1
            except Exception as e:
                fail_cs += 1
                if fail_cs <= 5:
                    print(f"  Error: {e}")
            
            if (i + 1) % 1000 == 0:
                print(f"  Progress: {i+1}/{len(has_solution_rels)} (success: {success_cs}, fail: {fail_cs})")
    
    print(f"Cause->Solution: success={success_cs}, fail={fail_cs}")
    
    driver.close()
    print("\nDone!")


if __name__ == '__main__':
    main()
