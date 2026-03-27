"""
知识图谱导入Neo4j工具
======================

灵活的导入工具，自动检测最新的知识图谱文件
支持命令行参数指定文件路径
支持导入后自动添加向量嵌入

用法:
    python knowledge_graph/do_import.py                    # 自动检测最新的kg文件
    python knowledge_graph/do_import.py --file path/to/kg.json  # 指定文件
    python knowledge_graph/do_import.py --list             # 列出可用的kg文件
    python knowledge_graph/do_import.py --year 2023        # 导入指定年份
    python knowledge_graph/do_import.py --all              # 导入所有年份
    python knowledge_graph/do_import.py --all --embedding  # 导入并添加向量
"""
import os
import json
import math
import argparse
from pathlib import Path
from dotenv import load_dotenv
from neo4j import GraphDatabase
from tqdm import tqdm

try:
    import ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False

# 加载环境变量
load_dotenv()

# ============================================================
# 配置（从环境变量读取，与主项目保持一致）
# ============================================================

# Neo4j连接配置
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USERNAME", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "password")
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

# Ollama嵌入模型配置
OLLAMA_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "bge-m3:latest")
EMBEDDING_DIMENSION = 1024

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# 知识图谱文件搜索路径（支持多年份）
KG_OUTPUT_DIR = PROJECT_ROOT / "data" / "output"

# 固定的输出文件名（每次覆盖）
KG_LATEST_FILE = "kg_latest.json"

# 支持的年份列表
SUPPORTED_YEARS = ["2023", "2024", "2025"]

# 文件优先级（从高到低）
KG_FILE_PRIORITY = [
    "kg_{year}.json",
    "kg_latest.json",                        # 混合提取的最新结果
    "kg_prediction_pattern.json",            # 模式增强提取结果
    "kg_hybrid_latest.json",                 # 混合提取结果
    "kg_prediction_bert_from_triples.json",  # BERT提取结果
    "kg_rebuilt.json",                       # 重建的图谱
]


def find_kg_file(specified_file: str = None, year: str = None) -> Path:
    """
    查找知识图谱文件
    
    Args:
        specified_file: 指定的文件路径（可选）
        year: 指定年份（可选，如 "2023", "2024"）
    
    Returns:
        知识图谱文件路径
    """
    # 如果指定了文件，直接使用
    if specified_file:
        path = Path(specified_file)
        if path.exists():
            return path
        # 尝试在输出目录中查找
        for year_dir in SUPPORTED_YEARS:
            path = KG_OUTPUT_DIR / f"{year_dir}_data" / specified_file
            if path.exists():
                return path
        raise FileNotFoundError(f"文件不存在: {specified_file}")
    
    # 确定搜索目录
    if year:
        search_dirs = [KG_OUTPUT_DIR / f"{year}_data"]
    else:
        # 搜索所有年份目录
        search_dirs = [KG_OUTPUT_DIR / f"{y}_data" for y in SUPPORTED_YEARS]
    
    # 按优先级查找
    for search_dir in search_dirs:
        if not search_dir.exists():
            continue
        for filename_pattern in KG_FILE_PRIORITY:
            # 替换年份占位符
            filename = filename_pattern.replace("{year}", year or "2024")
            path = search_dir / filename
            if path.exists():
                return path
    
    # 查找任何kg_*.json文件
    all_kg_files = []
    for search_dir in search_dirs:
        if search_dir.exists():
            all_kg_files.extend(list(search_dir.glob("kg_*.json")))
    
    if all_kg_files:
        # 按修改时间排序，返回最新的
        all_kg_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        return all_kg_files[0]
    
    raise FileNotFoundError(f"未找到知识图谱文件，搜索目录: {search_dirs}")


def list_kg_files(year: str = None):
    """列出所有可用的知识图谱文件"""
    print("\n可用的知识图谱文件:")
    print("-" * 70)
    
    # 确定搜索目录
    if year:
        search_dirs = [(year, KG_OUTPUT_DIR / f"{year}_data")]
    else:
        search_dirs = [(y, KG_OUTPUT_DIR / f"{y}_data") for y in SUPPORTED_YEARS]
    
    found_any = False
    for year_label, search_dir in search_dirs:
        if not search_dir.exists():
            continue
        
        kg_files = list(search_dir.glob("kg_*.json"))
        if not kg_files:
            continue
        
        found_any = True
        print(f"\n📁 {year_label}年数据 ({search_dir.name}):")
        
        # 按修改时间排序
        kg_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
        
        for f in kg_files:
            size = f.stat().st_size / 1024  # KB
            mtime = f.stat().st_mtime
            from datetime import datetime
            mtime_str = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
            
            # 标记优先级
            priority = ""
            for idx, pattern in enumerate(KG_FILE_PRIORITY):
                if f.name == pattern.replace("{year}", year_label):
                    priority = f" [优先级{idx+1}]"
                    break
            
            print(f"  {f.name:<40} {size:>8.1f}KB  {mtime_str}{priority}")
    
    if not found_any:
        print(f"  (无) - 搜索目录: {KG_OUTPUT_DIR}")


def import_to_neo4j(kg_file: Path, year: str = None, clear_db: bool = True, add_embedding: bool = False):
    """
    导入知识图谱到Neo4j
    
    Args:
        kg_file: 知识图谱文件路径
        year: 年份标记（会添加到节点属性中，便于跨年份查询）
        clear_db: 是否清空数据库（默认True；设为False可追加导入多年份数据）
        add_embedding: 是否添加向量嵌入（默认False）
    """
    print(f"\n[导入知识图谱到Neo4j]")
    print(f"文件: {kg_file}")
    if year:
        print(f"年份: {year}")
    print("-" * 60)
    
    # 连接Neo4j
    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    print("✅ 已连接到Neo4j")
    
    # 读取文件
    with open(kg_file, 'r', encoding='utf-8-sig') as f:
        kg = json.load(f)
    
    # 统计节点
    device_count = len(kg.get('devices', {}))
    position_count = len(kg.get('positions', {}))
    entity_count = len(kg.get('entities', {}))
    phen_count = len(kg.get('phenomena', {}))
    cause_count = len(kg.get('causes', {}))
    sol_count = len(kg.get('solutions', {}))
    rel_count = len(kg.get('relationships', []))
    
    total_nodes = device_count + position_count + entity_count + phen_count + cause_count + sol_count
    print(f"✅ 已加载: {total_nodes} 节点, {rel_count} 关系")
    
    # 导入
    with driver.session(database=NEO4J_DATABASE) as session:
        # 清空（如果需要）
        if clear_db:
            session.run("MATCH (n) DETACH DELETE n")
            print("✅ 已清空数据库")
        else:
            print("⚠️ 追加模式，保留现有数据")
        
        # 导入设备节点（带年份标记）
        for name, data in tqdm(kg.get('devices', {}).items(), desc="Device"):
            description = data.get('description', '') if isinstance(data, dict) else ''
            if not description:
                description = name
            session.run(
                "MERGE (x:Device {name: $name}) SET x.description = $description, x.year = $year",
                name=name, description=description, year=year or ""
            )
        
        # 导入站位节点
        for name, data in tqdm(kg.get('positions', {}).items(), desc="Station"):
            description = data.get('description', '') if isinstance(data, dict) else ''
            if not description:
                description = name
            session.run(
                "MERGE (x:Station {name: $name}) SET x.description = $description, x.year = $year",
                name=name, description=description, year=year or ""
            )
        
        # 导入实体节点
        for name, data in tqdm(kg.get('entities', {}).items(), desc="Entity"):
            description = data.get('description', '') if isinstance(data, dict) else ''
            if not description:
                description = name
            session.run(
                "MERGE (x:Entity {name: $name}) SET x.description = $description, x.year = $year",
                name=name, description=description, year=year or ""
            )
        
        # 导入问题节点（Problem）- 使用 CREATE 因为每条记录应该是唯一的
        for name, data in tqdm(kg.get('phenomena', {}).items(), desc="Problem"):
            description = data.get('description', name)
            timestamp = data.get('timestamp', '')
            # 用 description + year 作为唯一标识
            session.run(
                """CREATE (x:Problem {name: $name, description: $description, 
                   timestamp: $timestamp, year: $year})""",
                name=name, description=description, timestamp=timestamp, year=year or ""
            )
        
        # 导入原因节点
        for name, data in tqdm(kg.get('causes', {}).items(), desc="Cause"):
            description = data.get('description', '') if isinstance(data, dict) else ''
            if not description:
                description = name
            session.run(
                "MERGE (x:Cause {name: $name}) SET x.description = $description, x.year = $year",
                name=name, description=description, year=year or ""
            )
        
        # 导入方案节点
        for name, data in tqdm(kg.get('solutions', {}).items(), desc="Solution"):
            description = data.get('description', '') if isinstance(data, dict) else ''
            if not description:
                description = name
            session.run(
                "MERGE (x:Solution {name: $name}) SET x.description = $description, x.year = $year",
                name=name, description=description, year=year or ""
            )
        
        # 构建ID到名称的映射
        id_to_name = {}
        for name, data in kg.get('devices', {}).items():
            id_to_name[data['id']] = name
        for name, data in kg.get('positions', {}).items():
            id_to_name[data['id']] = name
        for name, data in kg.get('entities', {}).items():
            id_to_name[data['id']] = name
        for name, data in kg.get('phenomena', {}).items():
            id_to_name[data['id']] = name
        for name, data in kg.get('causes', {}).items():
            id_to_name[data['id']] = name
        for name, data in kg.get('solutions', {}).items():
            id_to_name[data['id']] = name
        
        # 导入关系
        for rel in tqdm(kg.get('relationships', []), desc="关系"):
            from_id = rel['from']
            to_id = rel['to']
            rel_type = rel['type']
            
            from_name = id_to_name.get(from_id)
            to_name = id_to_name.get(to_id)
            
            if from_name and to_name:
                try:
                    session.run(
                        f"MATCH (a {{name: $from_name}}), (b {{name: $to_name}}) CREATE (a)-[:{rel_type}]->(b)",
                        from_name=from_name, to_name=to_name
                    )
                except:
                    pass
    
    # 统计
    with driver.session(database=NEO4J_DATABASE) as session:
        n_count = session.run("MATCH (n) RETURN count(n)").single()[0]
        r_count = session.run("MATCH ()-[r]->() RETURN count(r)").single()[0]
    
    print(f"\n✅ 导入完成!")
    print(f"  节点: {n_count}")
    print(f"  关系: {r_count}")
    
    # 添加向量嵌入（如果需要）
    if add_embedding:
        add_embeddings_to_neo4j(driver)
    
    driver.close()
    return n_count, r_count


def get_embedding(text: str):
    """使用 Ollama 生成文本的向量嵌入"""
    if not OLLAMA_AVAILABLE:
        return None
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
            return None
        
        return embedding
    except Exception as e:
        print(f"生成嵌入失败: {e}")
        return None


def add_embeddings_to_neo4j(driver, node_labels: list = None):
    """
    为 Neo4j 节点添加向量嵌入
    
    Args:
        driver: Neo4j 驱动
        node_labels: 要处理的节点类型列表，默认 ['Problem', 'Cause', 'Solution']
    """
    if not OLLAMA_AVAILABLE:
        print("⚠️ ollama 未安装，跳过向量嵌入")
        return
    
    if node_labels is None:
        node_labels = ['Problem', 'Cause', 'Solution']
    
    print(f"\n[添加向量嵌入]")
    print(f"使用模型: {OLLAMA_MODEL}")
    print(f"节点类型: {', '.join(node_labels)}")
    print("-" * 60)
    
    with driver.session(database=NEO4J_DATABASE) as session:
        for label in node_labels:
            # 获取没有 embedding 的节点
            result = session.run(f"""
                MATCH (n:{label})
                WHERE n.embedding IS NULL
                RETURN id(n) AS id, n.name AS name, n.description AS description
            """)
            
            nodes = [(rec["id"], rec["name"], rec["description"]) for rec in result]
            
            if not nodes:
                print(f"  {label}: 所有节点已有 embedding")
                continue
            
            print(f"  {label}: 需要处理 {len(nodes)} 个节点")
            
            success_count = 0
            for node_id, name, description in tqdm(nodes, desc=f"    {label}"):
                # 优先用 description，否则用 name
                text = description if description else name
                embedding = get_embedding(text)
                
                if embedding:
                    session.run(f"""
                        MATCH (n:{label})
                        WHERE id(n) = $id
                        SET n.embedding = $embedding
                    """, id=node_id, embedding=embedding)
                    success_count += 1
            
            print(f"    ✅ 成功: {success_count}/{len(nodes)}")


# ============================================================
# 主函数
# ============================================================

def import_all_years(add_embedding: bool = False):
    """导入所有年份的知识图谱（合并到同一个Neo4j数据库）"""
    print("\n" + "=" * 70)
    print("📊 导入所有年份的知识图谱")
    print("=" * 70)
    
    first = True
    imported_years = []
    total_nodes = 0
    total_rels = 0
    
    for year in SUPPORTED_YEARS:
        try:
            kg_file = find_kg_file(year=year)
            print(f"\n{'='*30} {year}年 {'='*30}")
            # 只在最后一个年份导入时添加 embedding（避免重复）
            n, r = import_to_neo4j(kg_file, year=year, clear_db=first, add_embedding=False)
            first = False  # 后续年份使用追加模式
            imported_years.append(year)
            total_nodes += n
            total_rels += r
        except FileNotFoundError as e:
            print(f"⚠️ {year}年: 未找到知识图谱文件，跳过")
    
    # 所有年份导入后，统一添加 embedding
    if add_embedding and imported_years:
        print(f"\n{'='*30} 添加向量嵌入 {'='*30}")
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        add_embeddings_to_neo4j(driver)
        driver.close()
    
    print("\n" + "=" * 70)
    print(f"✅ 导入完成！")
    print(f"   已导入年份: {', '.join(imported_years)}")
    print(f"   总节点数: {total_nodes}")
    print(f"   总关系数: {total_rels}")
    print("=" * 70)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="知识图谱导入Neo4j工具")
    parser.add_argument("--file", "-f", type=str, help="指定知识图谱文件路径")
    parser.add_argument("--year", "-y", type=str, choices=SUPPORTED_YEARS, help="指定年份（如 2023, 2024）")
    parser.add_argument("--all", "-a", action="store_true", help="导入所有年份的数据（合并）")
    parser.add_argument("--list", "-l", action="store_true", help="列出可用的知识图谱文件")
    parser.add_argument("--append", action="store_true", help="追加模式（不清空数据库）")
    parser.add_argument("--embedding", "-e", action="store_true", help="导入后添加向量嵌入（用于向量检索）")
    
    args = parser.parse_args()
    
    if args.list:
        list_kg_files(year=args.year)
    elif args.all:
        import_all_years(add_embedding=args.embedding)
    else:
        try:
            kg_file = find_kg_file(args.file, year=args.year)
            import_to_neo4j(kg_file, year=args.year, clear_db=not args.append, add_embedding=args.embedding)
        except FileNotFoundError as e:
            print(f"\n❌ 错误: {e}")
            list_kg_files(year=args.year)
