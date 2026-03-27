# Neo4j导入配置文件
# 复制此文件为 neo4j_config.py 并修改配置

# ============================================
# Neo4j 数据库连接配置
# ============================================

# Neo4j服务器地址
# 默认本地: bolt://localhost:7687
# 远程服务器: bolt://your-server-ip:7687
NEO4J_URI = "bolt://localhost:7687"

# 用户名 (默认为neo4j)
NEO4J_USERNAME = "neo4j"

# 密码 (⚠️ 必须修改!)
# 首次安装Neo4j后需要修改默认密码
NEO4J_PASSWORD = "password"

# 数据库名称
# Neo4j 4.x+支持多数据库, 默认为"neo4j"
# 也可以创建新数据库如: "device_kg"
NEO4J_DATABASE = "neo4j"

# ============================================
# 导入配置
# ============================================

# 知识图谱JSON文件路径
# 相对于项目根目录
KG_JSON_FILE = "data/output/knowledge_graph/kg_prediction_pattern.json"

# 是否清空现有数据 (⚠️ 慎用!)
# True: 导入前删除所有节点和关系
# False: 追加导入 (可能产生重复)
CLEAR_EXISTING_DATA = True

# 批次大小
# 根据机器性能调整, 值越大内存占用越高但速度越快
# 推荐: 1000-5000
BATCH_SIZE = 1000

# ============================================
# 高级配置
# ============================================

# 是否创建索引 (推荐开启)
# 索引可以显著提升查询性能
CREATE_INDEXES = True

# 导入后是否验证数据
VERIFY_AFTER_IMPORT = True

# 是否显示详细日志
VERBOSE = True
