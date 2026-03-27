# app

后端核心目录，当前基于 `FastAPI + LangGraph`。

## 主要职责

- `server.py`
  FastAPI 入口，负责聊天接口、图谱接口、会话接口，以及 LangGraph 工作流编排。

- `chains/`
  包含追问识别、路由策略和检索记录格式化等逻辑。

- `retrievers/`
  包含 embedding 封装、Qdrant 检索与 collection 操作。

- `tools/`
  包含 Neo4j 检索工具和图查询辅助逻辑。

- `diagnosis/`
  负责三段式诊断：图谱证据、相似记录、排查流程。

- `dataset/`
  负责 CSV 导入、字段映射和向量入库。

- `ocr/`
  负责 PDF OCR 任务与结果存储。

- `settings/`
  负责 LLM 配置与 prompt 配置接口。

- `db/`
  包含 SQLite 会话库与 OCR 结果库。

## 当前路由逻辑

聊天主路由目前收口为：

- `history`
  追问场景，优先使用当前结果记录和历史消息。

- `search`
  普通检索，再根据 `search_strategy` 分派到：
  `qdrant / neo4j / hybrid`

- `diagnosis`
  三段式诊断，返回图谱、记录和流程计划。

## 启动

```powershell
.venv\Scripts\python -m uvicorn app.server:app --host 0.0.0.0 --port 8000 --reload
```
