# NL2SQL 评测说明

本目录定义本项目自然语言转 SQL 的可复现评测方法。评测的主指标是**端到端结果一致率**：Agent 返回的结果与人工确认的标准 SQL 在同一份 `dw` 数据上的查询结果完全一致。

## 文件与职责

```text
tests/evaluation_cases.jsonl       测试集，每行一个 JSON 用例
scripts/evaluate_queries.py        执行评测、比较结果、生成报告
artifacts/evaluation/              每次运行生成的 CSV、JSON、Markdown 报告
```

`artifacts/evaluation/` 已被 Git 忽略。测试集和评测脚本需要纳入版本控制，运行报告作为每次评测的留痕文件保存。

## 测试集格式

每一行都是一个 JSON 对象，必填字段如下：

```json
{
  "id": "metric_001",
  "category": "指标聚合",
  "query": "总销售额是多少",
  "expected_sql": "SELECT SUM(order_amount) AS total_sales_amount FROM fact_order"
}
```

可选字段：

- `result_order`：`ordered`（默认）或 `unordered`。分组但未要求排序的结果应使用 `unordered`。
- `comparison_mode`：`strict`（默认，字段名和数值均需一致）或 `values_only`（只比较每行数据值，忽略列别名）。使用 `values_only` 时，简历只能写“数值结果一致率”，不能写“严格结果一致率”。
- `expected_tables`、`expected_columns`：人工审核 SQL 语义时使用，当前不参与通过判定。

`expected_sql` 是人工确认过的只读查询。脚本在运行时执行它，得到当前数据库中的标准答案；因此不要把模型生成的 SQL 填入该字段。

## 运行前检查

1. 固定 `dw` 示例数据、`conf/meta_config.yaml`、提示词和 Ollama 模型版本。
2. 已完成元数据构建。
3. Qdrant、Elasticsearch、Embedding、Ollama、MySQL 均已启动。
4. 后端已在 `http://127.0.0.1:8000` 启动。

后端启动命令：

```powershell
uv run python -c "import uvicorn; uvicorn.run('main:app', host='127.0.0.1', port=8000)"
```

## 执行评测

先运行种子集验证链路：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_queries.py --limit 5
```

完整 100 条测试集准备完毕后：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_queries.py --fail-on-error
```

如果后端端口不同：

```powershell
.\.venv\Scripts\python.exe scripts\evaluate_queries.py --url http://127.0.0.1:8001/api/query
```

每次执行会输出：

- CSV：逐条查看问题、期望结果、实际结果、耗时和错误信息
- JSON：供后续统计或可视化使用
- Markdown：便于复盘和作为简历数字的证据

## 统计口径

```text
SQL 执行成功率 = 有 result SSE 事件且没有 error SSE 事件的用例数 / 总用例数
严格结果一致率 = 实际结果与标准 SQL 结果的字段名、行数、行值均一致的用例数 / 总用例数
数值结果一致率 = 实际结果与标准 SQL 结果的行值一致、但忽略列别名的用例数 / 总用例数
```

报告会同时输出严格结果一致率和数值结果一致率。只有在固定环境下跑完整 100 条用例后，才能在简历中填写准确率。建议连续运行 3 轮，报告中同时保留每轮结果和失败样例。

## 扩充到 100 条

当前测试集只含 5 条种子用例，每类 1 条，用于验证评测框架。扩充时按以下 5 类各补充 19 条，共 100 条：

| 类别 | 数量 | 典型问题 |
| --- | ---: | --- |
| 指标聚合 | 20 | 总销售额、平均订单金额、订单量 |
| 维度筛选 | 20 | 华东地区销售额、苹果品牌订单量 |
| 分组统计 | 20 | 各品牌销售额、各地区订单量 |
| 时间分析 | 20 | 2025 年销售额、按月统计销售额 |
| 多表关联与排序 | 20 | 销售额最高品牌、地区 Top 商品 |

新增用例前，先在 Navicat 中执行并审核 `expected_sql`。测试用例应只覆盖当前真实存在的 `dw` 表和字段，不应写入企业信息、风险记录或任务状态等本项目不存在的业务场景。
