# Data Warehouse QA System

> 将业务人员的问题转换为可执行、可追溯的数仓查询结果。

Data Warehouse QA System 是一个面向结构化数据仓库的自然语言问答项目。业务人员不需要了解表名、字段名或 SQL 语法，只需输入诸如“总销售额是多少”“华东地区的订单量”这类问题，
系统便会从业务元数据中识别相关的表、字段、指标和值，生成 SQL、完成校验，并将真实查询结果流式返回到页面。

项目以零售订单数仓为内置示例，包含订单事实表以及客户、商品、地区、日期等维表，并预置 GMV、AOV 等业务指标。它既可以作为本地可运行的 Text-to-SQL 演示项目，
也可以作为接入企业数据仓库的基础模板：替换业务表与 `conf/meta_config.yaml` 中的语义配置后，即可适配新的数据域。

与只依赖 LLM 直接生成 SQL 的方式不同，本项目在生成前加入了元数据检索和字段值检索：Qdrant 用于理解“销售额”“客单价”等业务语义，
Elasticsearch 用于召回地区、品牌、品类等具体取值，MySQL 元数据库保存表、字段和指标定义。这样可以显著缩小 LLM 的可选上下文范围，并让生成 SQL 更贴近实际库表结构。

默认使用本地 Ollama 模型 `qwen2.5:3b`，不依赖云端 LLM API Key。查询接口以 Server-Sent Events（SSE）实时推送各处理步骤和最终结果，前端可展示完整的执行过程。


dw:存订单、客户、商 品、地区等真实业务  数据
meta :存表、字段、指标等语义信息

### 一次查询会发生什么

```text
业务问题
  -> 提取关键词与意图
  -> 召回相关表、字段、指标和字段值
  -> 过滤无关元数据并补充上下文
  -> LLM 生成 SQL
  -> SQL 校验与必要的自动纠错
  -> 查询 MySQL 数据仓库
  -> SSE 流式返回进度与结果
```

### 内置示例问题

```text
total sales amount
华东地区的销售额
苹果品牌的订单量
average order value
```

> 当前实现面向本地开发、学习和原型验证。接入生产数据前，应补充只读数据库账号、SQL 白名单与限流、查询超时和审计日志等安全控制。

## 功能概览

- 自然语言转 SQL，并在数据仓库中执行查询
- 基于 Qdrant 的字段和指标语义检索
- 基于 Elasticsearch 的字段值检索
- 基于 LangGraph 的查询编排、SQL 校验与纠错
- FastAPI 流式 SSE 接口
- Vue 3 前端查询界面
- 支持通过配置文件维护业务表、字段和指标元数据

## 架构

```text
Browser (Vue 3)
       |
       | POST /api/query (SSE)
       v
FastAPI -> LangGraph workflow -> Ollama (local LLM)
                    |        \
                    |         -> MySQL dw (business data)
                    +----------> MySQL meta (metadata)
                    +----------> Qdrant (vector retrieval)
                    +----------> Elasticsearch (value retrieval)
                    +----------> Embedding service
```

查询工作流：关键词提取 -> 字段、指标和值召回 -> 表与指标过滤 -> SQL 生成 -> SQL 校验/纠错 -> SQL 执行。

## 技术栈

| Layer | Components |
| --- | --- |
| Backend | Python 3.12, FastAPI, LangGraph, SQLAlchemy |
| Data services | MySQL 8, Qdrant, Elasticsearch 8, Hugging Face TEI |
| LLM | Ollama + `qwen2.5:3b` |
| Frontend | Vue 3, Vite |

## 目录结构

```text
agent/                 LangGraph 状态、上下文与节点
app/
  api/                 FastAPI 路由、请求模型和生命周期管理
  clients/             MySQL、Qdrant、ES、Embedding 客户端
  repositories/        数据访问层
  services/            查询与元数据构建服务
  scrips/              元数据构建脚本
conf/                  应用和业务元数据配置
docker/                Docker Compose、MySQL 初始化 SQL、ES 镜像
prompts/               LLM 提示词
data-agent-fronted/    Vue 前端
main.py                FastAPI 应用入口
```

## 前置条件

- Python 3.12
- [uv](https://docs.astral.sh/uv/)（推荐，用于同步 Python 依赖）
- Node.js 20+ 与 npm
- Docker Desktop（已启动）
- Ollama（已启动）
- 本地 Embedding 模型文件 `bge-large-zh-v1.5`

验证基础工具：

```powershell
python --version
uv --version
node --version
npm --version
docker version
ollama --version
```

## 快速开始

以下步骤从仓库根目录执行。

### 1. 安装依赖

同步后端依赖：

```powershell
uv sync
```

安装前端依赖：

```powershell
Set-Location data-agent-fronted
npm install
Set-Location ..
```

后续所有 Python 命令均可用 `uv run` 执行；如果已存在项目内 `.venv`，也可将 `uv run` 替换为 `./.venv/Scripts/python.exe`。

### 2. 准备本地 LLM

项目默认配置为本地 Ollama 的 `qwen2.5:3b`。

```powershell
ollama pull qwen2.5:3b
ollama list
```

确认 Ollama HTTP 服务可用：

```powershell
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

### 3. 启动数据服务

Docker Compose 提供 MySQL、Elasticsearch、Kibana、Qdrant 和 Embedding 服务：

```powershell
Set-Location docker
docker compose up -d
Set-Location ..
```

查看容器状态：

```powershell
docker compose -f docker/docker-compose.yaml ps
```

首次启动注意事项：

- MySQL 初始化脚本位于 `docker/mysql/`，仅在数据卷首次创建时执行。
- Embedding 服务挂载 `docker/embedding/bge-large-zh-v1.5`；请在启动前将模型文件放到该目录，否则该服务无法加载模型。
- Compose 默认 MySQL 映射为宿主机 `3306`，而本仓库当前 `conf/app_config.yaml` 配置的是 `3307`。请选择下方一种方式保持端口一致。

#### 方式 A：新环境使用 Compose 默认 MySQL（3306）

将 `conf/app_config.yaml` 中 `db_meta.port` 与 `db_dw.port` 都改为 `3306`，然后执行上面的 Compose 命令。

#### 方式 B：使用已有 MySQL 容器（当前验证环境）

当前验证环境使用容器 `mysql-agent-test`，端口映射为 `127.0.0.1:3307 -> 3306`。保持 `conf/app_config.yaml` 中两个数据库端口为 `3307`，并确认容器已启动：

```powershell
docker ps --filter "name=mysql-agent-test"
```

不要同时在宿主机暴露两个占用同一端口的 MySQL 容器。

### 4. 配置应用

应用配置在 [conf/app_config.yaml](conf/app_config.yaml)，包含 MySQL、Qdrant、Elasticsearch、Embedding 和 LLM 的地址。根据自己的运行环境修改主机、端口和 MySQL 凭据。

关键配置示例：

```yaml
db_dw:
  host: 127.0.0.1
  port: 3307 # 使用 Compose 默认 MySQL 时改为 3306
  user: <your_mysql_user>
  password: <your_mysql_password>
  database: dw

llm:
  model_name: qwen2.5:3b
  api_key: ollama
  base_url: http://127.0.0.1:11434/v1
```

业务元数据位于 [conf/meta_config.yaml](conf/meta_config.yaml)。新增业务表、字段、别名或指标后，需要重新执行下一步的元数据构建。

> `app_config.yaml` 目前包含本地开发凭据。提交到共享仓库或部署到生产环境前，应改为从环境变量或未跟踪的本地配置文件读取敏感信息。

### 5. 构建元数据知识库

该命令从 `dw` 读取表结构和样例值，并将元数据写入 `meta`、Qdrant 和 Elasticsearch：

```powershell
uv run python -m app.scrips.build_meta_knowledge -c conf/meta_config.yaml
```

成功时会输出：

```text
元数据知识库构建完成
```

### 6. 启动后端

```powershell
uv run python -c "import uvicorn; uvicorn.run('main:app', host='127.0.0.1', port=8000)"
```

启动后可访问：

- API 文档：<http://127.0.0.1:8000/docs>
- OpenAPI：<http://127.0.0.1:8000/openapi.json>

### 7. 启动前端

另开一个终端：

```powershell
Set-Location data-agent-fronted
npm run dev -- --host 127.0.0.1 --port 5173
```

浏览器打开 <http://127.0.0.1:5173>。开发服务器会将 `/api` 请求代理到 `http://localhost:8000`。

## 验证

### 服务健康检查

```powershell
Invoke-RestMethod http://127.0.0.1:6333/collections
Invoke-RestMethod http://127.0.0.1:9200
Invoke-RestMethod http://127.0.0.1:11434/api/tags
Invoke-RestMethod -Uri http://127.0.0.1:8081/embed -Method Post -ContentType 'application/json' -Body '{"inputs":"test"}'
```

### API 查询

后端启动后，在新的 PowerShell 窗口执行：

```powershell
Invoke-WebRequest -Uri http://127.0.0.1:8000/api/query `
  -Method Post `
  -ContentType 'application/json' `
  -Body '{"query":"total sales amount"}'
```

接口使用 Server-Sent Events 返回进度和结果。当前示例数据中，`total sales amount` 可生成类似 SQL：

```sql
SELECT SUM(order_amount) AS total_sales_amount
FROM fact_order;
```

已验证结果为 `279159.5`。

### 前端构建

```powershell
Set-Location data-agent-fronted
npm run build
```

构建产物输出到 `data-agent-fronted/dist/`。

## API

### `POST /api/query`

请求体：

```json
{
  "query": "total sales amount"
}
```

响应类型为 `text/event-stream`，事件数据示例：

```text
data: {"type":"progress","step":"执行SQL","status":"running"}

data: {"type":"result","data":[{"total_sales_amount":279159.5}]}
```

## 开发说明

### 修改业务语义

1. 在 `conf/meta_config.yaml` 中维护表、字段、别名和指标定义。
2. 确保 `dw` 中存在对应数据表和字段。
3. 重新执行元数据构建脚本。
4. 通过 `/api/query` 验证自然语言查询结果。

### 修改 SQL 生成规则

LLM 提示词位于 `prompts/`，其中 `generate_sql.prompt` 负责 SQL 生成，`correct_sql.prompt` 负责校正不合法 SQL。修改后应使用接口对典型问题回归测试。

### 日志

运行日志默认写入 `logs/`，该目录已被 Git 忽略。

## 常见问题

### MySQL 连接被拒绝或数据库不存在

先确认 `conf/app_config.yaml` 的端口与实际 MySQL 一致，再检查容器状态和初始化 SQL 是否完成：

```powershell
docker ps
docker logs mysql-agent-test
```

如果使用 Compose 默认容器，将最后一条替换为：

```powershell
docker compose -f docker/docker-compose.yaml logs mysql
```

### Embedding 服务无法启动

通常是 `docker/embedding/bge-large-zh-v1.5` 不存在或模型文件不完整。该目录应包含 Hugging Face TEI 能加载的 `BAAI/bge-large-zh-v1.5` 模型文件。

### Ollama 连接失败或找不到模型

```powershell
ollama list
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

确认配置中的 `llm.base_url` 指向 `http://127.0.0.1:11434/v1`，并已拉取对应 `model_name`。

### Qdrant 版本提示

如果日志提示 Qdrant Client 与 Server 版本不匹配，优先将 `docker/docker-compose.yaml` 中的 Qdrant 镜像版本与 `pyproject.toml` 的 `qdrant-client` 版本调整到兼容组合，再重新验证元数据构建和查询流程。

### Windows 下端口被占用

使用以下命令定位端口占用：

```powershell
Get-NetTCPConnection -LocalPort 3306,3307,8000,8081,9200,11434 -ErrorAction SilentlyContinue
```

然后修改 Docker 端口映射或 `conf/app_config.yaml`，保持二者一致。

## 已验证的本地链路

在当前开发环境中，以下链路已验证通过：本地 Ollama `qwen2.5:3b`、MySQL 容器 `mysql-agent-test`（宿主机端口 `3307`）、Qdrant、Elasticsearch、Embedding、元数据构建、`POST /api/query` 全链路，以及前端生产构建。
