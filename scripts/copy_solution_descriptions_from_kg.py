import json
from neo4j import GraphDatabase
import os

KG = r'C:\Users\Aumovio\Desktop\bert_crf\data\output\knowledge_graph\2024_data\kg_2024.json'
URI = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
USER = os.getenv('NEO4J_USER', 'neo4j')
PWD = os.getenv('NEO4J_PASSWORD', 'password')

N = 5

def main():
    with open(KG, 'r', encoding='utf-8-sig') as f:
        j = json.load(f)
    sols = list(j.get('solutions', {}).items())[:N]
    driver = GraphDatabase.driver(URI, auth=(USER, PWD))
    with driver.session(database='neo4j') as session:
        for i, (k,v) in enumerate(sols,1):
            desc = ''
            sid = None
            if isinstance(v, dict):
                desc = v.get('description','') or v.get('text','') or ''
                sid = v.get('id')
            print(f'[{i}/{len(sols)}] key={k} id={sid} desc_len={len(desc)}')
            if desc:
                if sid:
                    session.run("MATCH (s:Solution {id:$id}) SET s.description = $desc", id=sid, desc=desc)
                else:
                    session.run("MATCH (s:Solution {name:$name}) SET s.description = $desc", name=k, desc=desc)
                print('  written')
            else:
                print('  no desc available')
    driver.close()

if __name__ == '__main__':
    main()
