"""
知识图谱导入Neo4j数据库
支持从kg_all_years.json导入完整的知识图谱到Neo4j
"""
import json
from pathlib import Path
from typing import Dict, List, Optional
from tqdm import tqdm

try:
    from neo4j import GraphDatabase
    NEO4J_AVAILABLE = True
except ImportError:
    NEO4J_AVAILABLE = False
    print("⚠️ 警告: neo4j库未安装，请运行: pip install neo4j")


class Neo4jKGImporter:
    """知识图谱Neo4j导入器"""
    
    def __init__(
        self, 
        uri: str = "bolt://localhost:7687",
        username: str = "neo4j", 
        password: str = "password",
        database: str = "neo4j"
    ):
        """
        初始化Neo4j连接
        
        Args:
            uri: Neo4j数据库URI (默认: bolt://localhost:7687)
            username: 用户名 (默认: neo4j)
            password: password(需要修改!)
            database: 数据库名称 (默认: neo4j)
        """
        if not NEO4J_AVAILABLE:
            raise ImportError("请先安装neo4j: pip install neo4j")
        
        self.uri = uri
        self.username = username
        self.password = password
        self.database = database
        self.driver = None
        
    def connect(self):
        """连接到Neo4j数据库"""
        try:
            self.driver = GraphDatabase.driver(
                self.uri, 
                auth=(self.username, self.password)
            )
            # 测试连接
            self.driver.verify_connectivity()
            print(f"✅ 成功连接到Neo4j: {self.uri}")
            return True
        except Exception as e:
            print(f"❌ 连接Neo4j失败: {e}")
            print(f"\n请检查:")
            print(f"  1. Neo4j服务是否启动")
            print(f"  2. URI是否正确: {self.uri}")
            print(f"  3. 用户名/密码是否正确")
            return False
    
    def close(self):
        """关闭连接"""
        if self.driver:
            self.driver.close()
            print("✅ Neo4j连接已关闭")
    
    def clear_database(self, confirm: bool = False):
        """
        清空数据库 (慎用!)
        
        Args:
            confirm: 是否确认清空 (必须明确设置为True)
        """
        if not confirm:
            print("⚠️ 警告: 清空数据库需要confirm=True参数")
            return False
        
        with self.driver.session(database=self.database) as session:
            print("🗑️ 清空数据库中...")
            session.run("MATCH (n) DETACH DELETE n")
            print("✅ 数据库已清空")
        return True
    
    def create_indexes(self):
        """创建索引以提升查询性能"""
        print("\n📊 创建索引...")
        
        indexes = [
            # 节点ID索引
            "CREATE INDEX device_id IF NOT EXISTS FOR (n:Device) ON (n.id)",
            "CREATE INDEX position_id IF NOT EXISTS FOR (n:Position) ON (n.id)",
            "CREATE INDEX entity_id IF NOT EXISTS FOR (n:Entity) ON (n.id)",
            "CREATE INDEX phenomenon_id IF NOT EXISTS FOR (n:Phenomenon) ON (n.id)",
            "CREATE INDEX cause_id IF NOT EXISTS FOR (n:Cause) ON (n.id)",
            "CREATE INDEX solution_id IF NOT EXISTS FOR (n:Solution) ON (n.id)",
            
            # 名称索引 (用于查询)
            "CREATE INDEX device_name IF NOT EXISTS FOR (n:Device) ON (n.name)",
            "CREATE INDEX entity_name IF NOT EXISTS FOR (n:Entity) ON (n.name)",
            "CREATE INDEX phenomenon_name IF NOT EXISTS FOR (n:Phenomenon) ON (n.name)",
        ]
        
        with self.driver.session(database=self.database) as session:
            for idx_query in indexes:
                try:
                    session.run(idx_query)
                except Exception as e:
                    # 忽略已存在的索引
                    if "already exists" not in str(e):
                        print(f"⚠️ 创建索引失败: {e}")
        
        print("✅ 索引创建完成")
    
    def import_from_json(self, json_file: Path, batch_size: int = 1000):
        """
        从JSON文件导入知识图谱
        
        Args:
            json_file: kg_all_years.json文件路径
            batch_size: 批次大小 (默认1000)
        """
        print(f"\n{'='*60}")
        print(f"📥 开始导入知识图谱到Neo4j")
        print(f"{'='*60}\n")
        
        # 读取JSON
        print(f"📖 读取文件: {json_file}")
        with open(json_file, 'r', encoding='utf-8') as f:
            kg_data = json.load(f)
        
        print(f"✅ 文件加载成功")
        print(f"   设备: {len(kg_data.get('devices', {}))}")
        print(f"   站位: {len(kg_data.get('positions', {}))}")
        print(f"   部件: {len(kg_data.get('entities', {}))}")
        print(f"   现象: {len(kg_data.get('phenomena', {}))}")
        print(f"   原因: {len(kg_data.get('causes', {}))}")
        print(f"   方案: {len(kg_data.get('solutions', {}))}")
        print(f"   关系: {len(kg_data.get('relationships', []))}")
        
        # 创建索引
        self.create_indexes()
        
        # 导入节点
        self._import_nodes(kg_data, batch_size)
        
        # 导入关系
        self._import_relationships(kg_data, batch_size)
        
        print(f"\n{'='*60}")
        print(f"✅ 导入完成!")
        print(f"{'='*60}")
    
    def _import_nodes(self, kg_data: Dict, batch_size: int):
        """导入所有节点"""
        print("\n📦 导入节点...")
        
        # 1. 设备节点
        devices = []
        for name, data in kg_data.get('devices', {}).items():
            devices.append({
                'id': data['id'],
                'name': name,
                'type': data.get('type', 'Device')
            })
        self._create_nodes_batch('Device', devices, batch_size)
        
        # 2. 站位节点
        positions = []
        for name, data in kg_data.get('positions', {}).items():
            positions.append({
                'id': data['id'],
                'name': data['name'],
                'device': data.get('device', '')
            })
        self._create_nodes_batch('Position', positions, batch_size)
        
        # 3. 部件节点
        entities = []
        for name, data in kg_data.get('entities', {}).items():
            entities.append({
                'id': data['id'],
                'name': name,
                'position': data.get('position', '')
            })
        self._create_nodes_batch('Entity', entities, batch_size)
        
        # 4. 故障现象节点
        phenomena = []
        for name, data in kg_data.get('phenomena', {}).items():
            phenomena.append({
                'id': data['id'],
                'name': name,
                'count': data.get('count', 0)
            })
        self._create_nodes_batch('Phenomenon', phenomena, batch_size)
        
        # 5. 原因节点
        causes = []
        for name, data in kg_data.get('causes', {}).items():
            causes.append({
                'id': data['id'],
                'name': name,
                'count': data.get('count', 0)
            })
        self._create_nodes_batch('Cause', causes, batch_size)
        
        # 6. 解决方案节点
        solutions = []
        for name, data in kg_data.get('solutions', {}).items():
            solutions.append({
                'id': data['id'],
                'name': name,
                'count': data.get('count', 0)
            })
        self._create_nodes_batch('Solution', solutions, batch_size)
    
    def _create_nodes_batch(self, label: str, nodes: List[Dict], batch_size: int):
        """批量创建节点"""
        if not nodes:
            return
        
        print(f"   创建 {label} 节点: {len(nodes)} 个")
        
        with self.driver.session(database=self.database) as session:
            for i in tqdm(range(0, len(nodes), batch_size), desc=f"  {label}"):
                batch = nodes[i:i+batch_size]
                
                # 构建Cypher查询
                query = f"""
                UNWIND $nodes AS node
                CREATE (n:{label})
                SET n = node
                """
                
                session.run(query, nodes=batch)
    
    def _import_relationships(self, kg_data: Dict, batch_size: int):
        """导入所有关系"""
        print("\n🔗 导入关系...")
        
        relationships = kg_data.get('relationships', [])
        print(f"   关系总数: {len(relationships)}")
        
        # 按类型分组
        rel_by_type = {}
        for rel in relationships:
            rel_type = rel['type']
            if rel_type not in rel_by_type:
                rel_by_type[rel_type] = []
            rel_by_type[rel_type].append(rel)
        
        # 批量创建每种类型的关系
        with self.driver.session(database=self.database) as session:
            for rel_type, rels in rel_by_type.items():
                print(f"   创建 {rel_type} 关系: {len(rels)} 条")
                
                for i in tqdm(range(0, len(rels), batch_size), desc=f"  {rel_type}"):
                    batch = rels[i:i+batch_size]
                    
                    # 根据关系类型使用不同的标签映射
                    label_map = self._get_label_map(rel_type)
                    
                    if not label_map:
                        continue
                    
                    # 构建Cypher查询
                    query = f"""
                    UNWIND $rels AS rel
                    MATCH (from:{label_map['from']} {{id: rel.from}})
                    MATCH (to:{label_map['to']} {{id: rel.to}})
                    CREATE (from)-[r:{rel_type.upper()}]->(to)
                    SET r.properties = rel.properties
                    """
                    
                    session.run(query, rels=batch)
    
    def _get_label_map(self, rel_type: str) -> Optional[Dict[str, str]]:
        """获取关系类型对应的节点标签"""
        mapping = {
            'contains': {'from': 'Device', 'to': 'Position'},
            'contains_entity': {'from': 'Position', 'to': 'Entity'},
            'exhibits_phenomenon': {'from': 'Entity', 'to': 'Phenomenon'},
            'has_cause': {'from': 'Phenomenon', 'to': 'Cause'},
            'has_solution': {'from': 'Cause', 'to': 'Solution'},
            'causes_phenomenon': {'from': 'Cause', 'to': 'Phenomenon'},
            'solves_phenomenon': {'from': 'Solution', 'to': 'Phenomenon'},
        }
        return mapping.get(rel_type)
    
    def verify_import(self):
        """验证导入结果"""
        print("\n🔍 验证导入结果...")
        
        with self.driver.session(database=self.database) as session:
            # 统计节点数量
            node_counts = session.run("""
                MATCH (n)
                RETURN labels(n)[0] AS label, count(n) AS count
                ORDER BY count DESC
            """).data()
            
            print("\n节点统计:")
            for item in node_counts:
                print(f"   {item['label']}: {item['count']}")
            
            # 统计关系数量
            rel_counts = session.run("""
                MATCH ()-[r]->()
                RETURN type(r) AS type, count(r) AS count
                ORDER BY count DESC
            """).data()
            
            print("\n关系统计:")
            for item in rel_counts:
                print(f"   {item['type']}: {item['count']}")


def load_config_from_file(config_file: Path) -> Dict:
    """从配置文件加载配置"""
    import importlib.util
    
    spec = importlib.util.spec_from_file_location("neo4j_config", config_file)
    config_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config_module)
    
    return {
        'NEO4J_URI': getattr(config_module, 'NEO4J_URI', 'bolt://localhost:7687'),
        'NEO4J_USERNAME': getattr(config_module, 'NEO4J_USERNAME', 'neo4j'),
        'NEO4J_PASSWORD': getattr(config_module, 'NEO4J_PASSWORD', 'your_password_here'),
        'NEO4J_DATABASE': getattr(config_module, 'NEO4J_DATABASE', 'neo4j'),
        'KG_JSON_FILE': Path(getattr(config_module, 'KG_JSON_FILE', 'data/output/knowledge_graph/kg_all_years.json')),
        'CLEAR_EXISTING': getattr(config_module, 'CLEAR_EXISTING_DATA', False),
        'BATCH_SIZE': getattr(config_module, 'BATCH_SIZE', 1000),
    }


def main():
    """主函数 - 配置后运行"""
    import argparse
    
    parser = argparse.ArgumentParser(description='导入知识图谱到Neo4j数据库')
    parser.add_argument('--config', type=str, help='配置文件路径 (可选)')
    parser.add_argument('--uri', type=str, help='Neo4j URI (覆盖配置文件)')
    parser.add_argument('--password', type=str, help='Neo4j密码 (覆盖配置文件)')
    args = parser.parse_args()
    
    # 加载配置
    if args.config:
        config_file = Path(args.config)
        if not config_file.exists():
            print(f"❌ 配置文件不存在: {config_file}")
            return
        config = load_config_from_file(config_file)
        print(f"✅ 已加载配置文件: {config_file}")
    else:
        # 使用默认配置
        config = {
            'NEO4J_URI': "bolt://localhost:7687",
            'NEO4J_USERNAME': "neo4j",
            'NEO4J_PASSWORD': "your_password_here",  # ⚠️ 请修改密码!
            'NEO4J_DATABASE': "neo4j",
            'KG_JSON_FILE': Path("data/output/knowledge_graph/kg_2025.json"),
            'CLEAR_EXISTING': False,
            'BATCH_SIZE': 1000,
        }
        print("⚠️ 使用默认配置 (建议创建配置文件)")
    
    # 命令行参数覆盖配置文件
    if args.uri:
        config['NEO4J_URI'] = args.uri
    if args.password:
        config['NEO4J_PASSWORD'] = args.password
    
    # 提取配置
    NEO4J_URI = config['NEO4J_URI']
    NEO4J_USERNAME = config['NEO4J_USERNAME']
    NEO4J_PASSWORD = config['NEO4J_PASSWORD']
    NEO4J_DATABASE = config['NEO4J_DATABASE']
    KG_JSON_FILE = config['KG_JSON_FILE']
    CLEAR_EXISTING = config['CLEAR_EXISTING']
    BATCH_SIZE = config['BATCH_SIZE']
    
    # 检查文件是否存在
    if not KG_JSON_FILE.exists():
        print(f"❌ 错误: 找不到文件 {KG_JSON_FILE}")
        print("\n可用的JSON文件:")
        kg_dir = Path("data/output/knowledge_graph")
        if kg_dir.exists():
            for f in kg_dir.glob("*.json"):
                print(f"  - {f}")
        return
    
    # 创建导入器
    importer = Neo4jKGImporter(
        uri=NEO4J_URI,
        username=NEO4J_USERNAME,
        password=NEO4J_PASSWORD,
        database=NEO4J_DATABASE
    )
    
    # 连接数据库
    if not importer.connect():
        return
    
    try:
        # 清空数据库 (可选)
        if CLEAR_EXISTING:
            confirm = input("\n⚠️ 确认清空数据库? (yes/no): ")
            if confirm.lower() == 'yes':
                importer.clear_database(confirm=True)
            else:
                print("❌ 取消清空")
                return
        
        # 导入数据
        importer.import_from_json(KG_JSON_FILE, batch_size=BATCH_SIZE)
        
        # 验证结果
        importer.verify_import()
        
        print("\n💡 提示: 可以在Neo4j Browser中查看图谱")
        print(f"   访问: http://localhost:7474")
        print(f"   执行查询: MATCH (n) RETURN n LIMIT 100")
        
    except Exception as e:
        print(f"\n❌ 导入失败: {e}")
        import traceback
        traceback.print_exc()
    
    finally:
        # 关闭连接
        importer.close()


if __name__ == "__main__":
    main()
