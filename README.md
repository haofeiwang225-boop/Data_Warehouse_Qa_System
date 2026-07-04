# Data Agent

这是一个自然语言查询转 SQL 并执行的示例项目，后端使用 FastAPI、LangGraph、MySQL、Qdrant、Elasticsearch、Embedding 服务和本地 Ollama LLM，前端使用 Vue 3 + Vite。

## 1. 当前已跑通状态

当前验证通过的链路：

```text
用户问题: total sales amount
生成 SQL:
SELECT SUM(order_amount) AS total_sales_amount
FROM fact_order;

执行结果:
[{"total_sales_amount": 279159.5}]
```

当前使用的本地服务：

```text
MySQL: mysql-agent-test, 127.0.0.1:3307
Qdrant: 127.0.0.1:6333
Elasticsearch: 127.0.0.1:9200
Embedding: 127.0.0.1:8081
Ollama: 127.0.0.1:11434
LLM: qwen2.5:3b
```

## 2. 环境要求

- Python 3.12
- Node.js 和 npm
- Docker Desktop
- Ollama
- 本地 Ollama 模型 `qwen2.5:3b`

确认 Ollama 模型：

```powershell
ollama list
```

如果没有：

```powershell
ollama pull qwen2.5:3b
```

## 3. 安装依赖

后端使用项目内 `.venv`：

```powershell
.\.venv\Scripts\python.exe --version
```

前端依赖：

```powershell
cd data-agent-fronted
npm install
cd ..
```

## 4. 启动 Docker 服务

当前已经跑通的 MySQL 容器是 `mysql-agent-test`，映射端口是：

```text
127.0.0.1:3307 -> container:3306
```

确认 Docker 服务：

```powershell
docker ps
```

需要看到类似：

```text
mysql-agent-test   0.0.0.0:3307->3306/tcp
qdrant             0.0.0.0:6333-6334->6333-6334/tcp
embedding          0.0.0.0:8081->80/tcp
elasticsearch      0.0.0.0:9200->9200/tcp
```

如果 Qdrant、Embedding、Elasticsearch 没启动：

```powershell
cd docker
docker compose up -d elasticsearch qdrant embedding
cd ..
```

## 5. 当前配置

核心配置在 `conf/app_config.yaml`。

MySQL 当前应指向 Docker 的 `mysql-agent-test`：

```yaml
db_meta:
  host: 127.0.0.1
  port: 3307
  user: whf
  password: whf200311
  database: meta

db_dw:
  host: 127.0.0.1
  port: 3307
  user: whf
  password: whf200311
  database: dw
```

本地 LLM：

```yaml
llm:
  model_name: qwen2.5:3b
  api_key: ollama
  base_url: http://127.0.0.1:11434/v1
```

## 6. 验证基础服务

```powershell
Invoke-RestMethod http://127.0.0.1:6333/collections
Invoke-RestMethod http://127.0.0.1:9200
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

验证 Embedding：

```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8081/embed -Method Post -ContentType 'application/json' -Body '{"inputs":"test"}'
```

## 7. 构建元数据知识库

这一步会从 Docker MySQL 的 `dw` 读取业务表结构和样例数据，并写入：

- `meta` MySQL
- Qdrant 字段/指标向量索引
- Elasticsearch 字段取值索引

命令：

```powershell
.\.venv\Scripts\python.exe -m app.scrips.build_meta_knowledge -c conf\meta_config.yaml
```

成功时最后会看到：

```text
元数据知识库构建完成
```

## 8. 测试后端接口

不启动服务也可以用 FastAPI TestClient 直接测完整链路：

```powershell
@'
from fastapi.testclient import TestClient
from main import app

with TestClient(app) as client:
    with client.stream("POST", "/api/query", json={"query": "total sales amount"}) as response:
        print("status", response.status_code)
        for line in response.iter_lines():
            print(line)
'@ | .\.venv\Scripts\python.exe -
```

成功结果示例：

```text
status 200
data: {"type": "result", "data": [{"total_sales_amount": 279159.5}]}
```

## 9. 启动后端

推荐用 Python 方式启动，避免当前环境里 `uvicorn` CLI 和项目 `main.py` 的 `main()` 名称冲突：

```powershell
.\.venv\Scripts\python.exe -c "import uvicorn; uvicorn.run('main:app', host='127.0.0.1', port=8000)"
```

验证：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/openapi.json
```

## 10. 启动前端

```powershell
cd data-agent-fronted
npm run dev -- --host 127.0.0.1 --port 5173
```

访问：

```text
http://127.0.0.1:5173
```

前端通过 Vite 代理把 `/api` 请求转发到：

```text
http://localhost:8000
```

## 11. 前端构建验证

```powershell
cd data-agent-fronted
npm run build
```

成功时会看到：

```text
✓ built
```

## 12. 常见问题

### MySQL 端口

当前项目使用 Docker MySQL：

```text
127.0.0.1:3307
```

不要误改回 `3306`，除非你明确要使用本机 MySQL。

### LLM 连接失败

确认 Ollama 正在运行：

```powershell
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

确认有 `qwen2.5:3b`：

```powershell
ollama list
```

### Qdrant 版本 warning

可能看到：

```text
Qdrant client version 1.18.0 is incompatible with server version 1.16.3
```

这是兼容性提示，当前流程可以正常查询。
