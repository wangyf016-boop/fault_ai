# Fault AI Project

面向制造现场故障检索、追问分析和诊断排查的本地化 AI 项目。

当前项目由 `FastAPI + LangGraph + Neo4j + Qdrant + React/Vite` 组成，支持：

- 聊天式故障检索
- 追问复用当前结果和历史对话
- 三段式诊断：知识图谱 -> 相似记录 -> 排查流程
- Neo4j 图谱查询、邻居展开、编辑与回滚
- CSV 数据导入到 Qdrant / Neo4j
- PDF OCR 任务处理
- LLM 与 Prompt 在线配置

## 当前工作逻辑

### 1. 数据处理与入库

1. `app/dataset/dataset_router.py` 负责接收 CSV，做字段映射、日期清洗和文本拼接。
2. `app/retrievers/embedding.py` 负责生成 embedding，默认支持 Ollama，也支持智谱 embedding。
3. 向量写入 Qdrant，结构化字段可同步写入 Neo4j。
4. 当前启用中的 Qdrant collection 记录在根目录 `collection_registry.json`。

### 2. 聊天检索与路由

`/chat` 请求先处理 `query_mode`：

- `auto`：自动判断是不是追问
- `new`：强制按新问题处理
- `followup`：强制按追问处理

随后 LangGraph 主路由会收口为 3 类：

- `history`：追问场景，优先基于当前结果记录和历史消息回答
- `search`：普通检索，再按 `search_strategy` 分派到 `qdrant / neo4j / hybrid`
- `diagnosis`：三段式诊断，返回图谱、记录表、流程计划

### 3. 三段式诊断

诊断模式的后端流程在 `app/diagnosis/diagnosis_engine.py` 与 `app/server.py` 中协同完成：

1. 从 Neo4j 抽取相关子图
2. 从 Qdrant 召回相似记录
3. 结合图谱与记录生成排查流程和 flow plan

### 4. 前端展示

- 普通检索：答案 + 检索记录表
- 追问：基于当前记录和历史上下文继续回答
- 诊断：知识图谱 + 相似记录 + 排查流程
- 图谱页：独立的 Neo4j 可视化、搜索和编辑入口

## 项目结构

```text
Fault_AI_Project/
|-- app/
|   |-- server.py                    # FastAPI 入口 + LangGraph 编排
|   |-- chains/                      # 路由、追问、记录格式化
|   |-- dataset/                     # CSV 导入与嵌入
|   |-- db/                          # SQLite 会话库与 OCR 结果库
|   |-- diagnosis/                   # 三段式诊断逻辑
|   |-- ocr/                         # OCR 路由与服务
|   |-- retrievers/                  # Embedding 与 Qdrant 检索
|   |-- settings/                    # LLM / Prompt 配置
|   |-- tools/                       # Neo4j 工具与图查询辅助
|-- frontend/
|   |-- src/components/              # 聊天、图谱、诊断等组件
|   |-- src/pages/                   # 页面级视图
|   |-- src/services/                # 前端 API 封装
|-- collection_registry.json         # 当前启用的 Qdrant 集合
|-- prompts_config.json              # Prompt 配置
|-- requirements.txt                 # Python 依赖
|-- start_server.bat                 # 后端启动脚本
|-- start_frontend.bat               # 前端启动脚本
|-- start_qdrant.bat                 # Qdrant 启动脚本
|-- reimport_machining.py            # 重新导入 machining 数据的辅助脚本
```

## 环境要求

- Windows 10/11
- Python 3.10+
- Node.js 18+
- Neo4j 5+
- Qdrant
- 可选：Ollama

## 安装

### 1. 安装 Python 依赖

```powershell
py -3 -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install -r requirements.txt
```

### 2. 安装前端依赖

```powershell
cd frontend
npm install
cd ..
```

## 环境变量

建议在项目根目录准备 `.env`，至少包含以下配置：

```env
# ========== LLM ==========
LLM_TYPE=ollama
API_BASE_URL=http://127.0.0.1:1235
GLM_API_KEY=
GLM_MODEL=
MODEL_NAME=
OLLAMA_BASE_URL=http://127.0.0.1:11434
OLLAMA_MODEL=qwen3:8b

# ========== Embedding ==========
EMBEDDING_PROVIDER=ollama
EMBEDDING_MODEL=bge-m3:latest
EMBEDDING_BASE_URL=http://127.0.0.1:11434
ZHIPUAI_API_KEY=

# ========== Qdrant ==========
QDRANT_HOST=127.0.0.1
QDRANT_PORT=6333

# ========== Neo4j ==========
NEO4J_URI=bolt://127.0.0.1:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=12345678
NEO4J_DATABASE=machining
```

说明：

- Settings 页面可以在线修改 LLM 配置，并写回 `.env`
- Prompt 配置会保存在根目录 `prompts_config.json`

## 启动方式

建议按下面顺序启动：

### 1. 启动 Neo4j

确保本地 Neo4j 已启动，并且 `.env` 中的数据库连接信息正确。

### 2. 启动 Qdrant

可以手动启动，也可以使用：

```powershell
start_qdrant.bat
```

注意：

- `start_qdrant.bat` 当前包含本机绝对路径
- 新机器上必须先修改 `qdrant.exe` 路径和 `storage` 路径

### 3. 启动后端

```powershell
start_server.bat
```

或者直接运行：

```powershell
.venv\Scripts\python -m uvicorn app.server:app --host 0.0.0.0 --port 8000 --reload
```

### 4. 启动前端

```powershell
start_frontend.bat
```

或者直接运行：

```powershell
cd frontend
npm run dev
```

默认访问地址：

- 前端：[http://localhost:5173](http://localhost:5173)
- 后端：[http://localhost:8000](http://localhost:8000)
- 接口文档：[http://localhost:8000/docs](http://localhost:8000/docs)

## 关键接口

### 聊天与会话

- `GET /health`
- `POST /chat`
- `GET /conversations`
- `GET /conversations/{conversation_id}/messages`
- `DELETE /conversations/{conversation_id}`

### 图谱

- `GET /graph`
- `GET /graph/search`
- `POST /graph/search-by-records`
- `GET /graph/neighbors`
- `GET /graph/node/{node_id}/neighbors`
- `POST /graph/node`
- `PUT /graph/node/{node_id}`
- `DELETE /graph/node/{node_id}`
- `POST /graph/edge`
- `DELETE /graph/edge/{rel_id}`
- `GET /graph/mutations`
- `POST /graph/mutations/{mutation_id}/rollback`

### 数据集

- `/api/datasets/*`

### OCR

- `/api/ocr/*`

### 设置

- `/settings/*`

## 迁移与部署注意事项

如果你要把项目迁到新机器，建议一起处理下面这些内容：

### 必带配置

- `.env`
- `prompts_config.json`
- `collection_registry.json`

### 需要保留历史数据时

- Neo4j 数据库本体，或者原始 CSV 与重导入方案
- Qdrant 的 `storage` 目录，或者重新执行数据嵌入任务
- `app/db/conversations.db`，用于保留聊天记录
- `app/db/ocr_results.db`，用于保留 OCR 结果

### 关于 Neo4j

- 如果直接迁移 Neo4j 数据库文件或整库备份，一般不需要重新构图
- 如果只迁代码，不迁图数据库数据，则需要重新导入图谱数据

### 关于 Qdrant

- 如果直接迁移 Qdrant 的 `storage` 目录，原有 collection 可以直接继续使用
- 如果不迁移 `storage`，则需要重新执行 CSV 嵌入导入流程


