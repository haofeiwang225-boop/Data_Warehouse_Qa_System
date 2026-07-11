"""Run end-to-end NL2SQL evaluation cases against the local Data Agent API."""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import math
import re
import sys
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import text

from app.clients.mysql_client_manager import dw_mysql_client_manager


REQUIRED_CASE_FIELDS = {"id", "category", "query", "expected_sql"}
DISALLOWED_SQL_KEYWORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|replace|grant|revoke)\b",
    re.IGNORECASE,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate NL2SQL cases through POST /api/query and compare result sets."
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=PROJECT_ROOT / "tests" / "evaluation_cases.jsonl",
        help="JSONL test-case file.",
    )
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:8000/api/query",
        help="Running Data Agent query endpoint.",
    )
    parser.add_argument("--limit", type=int, help="Only evaluate the first N cases.")
    parser.add_argument("--timeout", type=float, default=90.0, help="HTTP timeout in seconds.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "artifacts" / "evaluation",
        help="Directory for generated CSV, JSON, and Markdown reports.",
    )
    parser.add_argument(
        "--fail-on-error",
        action="store_true",
        help="Return a non-zero exit code when any case is not correct.",
    )
    return parser.parse_args()


def load_cases(path: Path, limit: int | None) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(f"Test-case file does not exist: {path}")

    cases: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            case = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON on line {line_number}: {exc.msg}") from exc

        missing = REQUIRED_CASE_FIELDS.difference(case)
        if missing:
            raise ValueError(f"Case on line {line_number} is missing fields: {sorted(missing)}")
        if case["id"] in seen_ids:
            raise ValueError(f"Duplicate test-case id: {case['id']}")
        if not isinstance(case["query"], str) or not case["query"].strip():
            raise ValueError(f"Case {case['id']} has an empty query")
        if case.get("result_order", "ordered") not in {"ordered", "unordered"}:
            raise ValueError(f"Case {case['id']} has an invalid result_order value")
        if case.get("comparison_mode", "strict") not in {"strict", "values_only"}:
            raise ValueError(f"Case {case['id']} has an invalid comparison_mode value")

        validate_expected_sql(case["expected_sql"], case["id"])
        seen_ids.add(case["id"])
        cases.append(case)

    if limit is not None:
        if limit < 1:
            raise ValueError("--limit must be greater than zero")
        cases = cases[:limit]
    if not cases:
        raise ValueError("No evaluation cases were loaded")
    return cases


def validate_expected_sql(sql: str, case_id: str) -> None:
    statement = sql.strip().rstrip(";").strip()
    if not re.match(r"^(select|with)\b", statement, re.IGNORECASE):
        raise ValueError(f"Case {case_id} expected_sql must be a read-only SELECT statement")
    if DISALLOWED_SQL_KEYWORDS.search(statement):
        raise ValueError(f"Case {case_id} expected_sql contains a disallowed SQL keyword")


def normalize_value(value: Any, precision: int = 6) -> Any:
    if isinstance(value, Decimal):
        return round(float(value), precision)
    if isinstance(value, float):
        return round(value, precision)
    if isinstance(value, dict):
        return {key: normalize_value(value[key], precision) for key in sorted(value)}
    if isinstance(value, list):
        return [normalize_value(item, precision) for item in value]
    return value


def normalize_rows(rows: list[dict[str, Any]], result_order: str) -> list[dict[str, Any]]:
    normalized = normalize_value(rows)
    if result_order == "unordered":
        return sorted(
            normalized,
            key=lambda row: json.dumps(row, ensure_ascii=False, sort_keys=True, default=str),
        )
    return normalized


def normalize_row_values(rows: list[dict[str, Any]], result_order: str) -> list[list[Any]]:
    normalized_rows = normalize_rows(rows, result_order)
    values = [
        sorted(row.values(), key=lambda value: json.dumps(value, ensure_ascii=False, default=str))
        for row in normalized_rows
    ]
    if result_order == "unordered":
        return sorted(values, key=lambda row: json.dumps(row, ensure_ascii=False, default=str))
    return values


async def load_expected_results(cases: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    dw_mysql_client_manager.init()
    try:
        expected_results: dict[str, list[dict[str, Any]]] = {}
        async with dw_mysql_client_manager.session_factory() as session:
            for case in cases:
                result = await session.execute(text(case["expected_sql"]))
                expected_results[case["id"]] = [dict(row) for row in result.mappings().fetchall()]
        return expected_results
    finally:
        await dw_mysql_client_manager.close()


def parse_sse(payload: str) -> tuple[list[dict[str, Any]] | None, str | None]:
    final_result: list[dict[str, Any]] | None = None
    error_message: str | None = None
    for event in re.split(r"\r?\n\r?\n", payload):
        data_lines = [line[5:].strip() for line in event.splitlines() if line.startswith("data:")]
        if not data_lines:
            continue
        try:
            data = json.loads("\n".join(data_lines))
        except json.JSONDecodeError:
            error_message = "Received an invalid JSON SSE event"
            continue
        if data.get("type") == "result":
            result_data = data.get("data")
            if isinstance(result_data, list):
                final_result = result_data
            else:
                error_message = "Received a result event with a non-list data field"
        elif data.get("type") == "error":
            error_message = str(data.get("message", "Unknown agent error"))
    return final_result, error_message


def invoke_agent(url: str, query: str, timeout: float) -> tuple[list[dict[str, Any]] | None, str | None, float]:
    request = Request(
        url,
        data=json.dumps({"query": query}, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
    except HTTPError as exc:
        return None, f"HTTP {exc.code}: {exc.reason}", (time.perf_counter() - started) * 1000
    except URLError as exc:
        return None, f"Connection error: {exc.reason}", (time.perf_counter() - started) * 1000
    except TimeoutError:
        return None, f"Timed out after {timeout:.1f}s", (time.perf_counter() - started) * 1000
    return (*parse_sse(payload), (time.perf_counter() - started) * 1000)


def percentile_95(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[math.ceil(len(ordered) * 0.95) - 1]


def evaluate_cases(
    cases: list[dict[str, Any]],
    expected_results: dict[str, list[dict[str, Any]]],
    url: str,
    timeout: float,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        actual_result, error_message, latency_ms = invoke_agent(url, case["query"], timeout)
        expected = normalize_rows(
            expected_results[case["id"]], case.get("result_order", "ordered")
        )
        actual = (
            normalize_rows(actual_result, case.get("result_order", "ordered"))
            if actual_result is not None
            else None
        )
        result_order = case.get("result_order", "ordered")
        comparison_mode = case.get("comparison_mode", "strict")
        expected_values = normalize_row_values(expected_results[case["id"]], result_order)
        actual_values = normalize_row_values(actual_result, result_order) if actual_result is not None else None
        execution_success = actual_result is not None and error_message is None
        strict_result_match = execution_success and actual == expected
        value_result_match = execution_success and actual_values == expected_values
        passed = strict_result_match if comparison_mode == "strict" else value_result_match
        status = "passed" if passed else "wrong_result" if execution_success else "agent_error"
        record = {
            "id": case["id"],
            "category": case["category"],
            "query": case["query"],
            "status": status,
            "passed": passed,
            "execution_success": execution_success,
            "comparison_mode": comparison_mode,
            "strict_result_match": strict_result_match,
            "value_result_match": value_result_match,
            "latency_ms": round(latency_ms, 2),
            "error_message": error_message or "",
            "expected_result": expected,
            "actual_result": actual,
        }
        records.append(record)
        print(
            f"[{index}/{len(cases)}] {case['id']}: {status} "
            f"({record['latency_ms']:.2f} ms)"
        )
    return records


def build_summary(records: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(records)
    successful = [record for record in records if record["execution_success"]]
    passed = [record for record in records if record["passed"]]
    strict_matches = [record for record in records if record["strict_result_match"]]
    value_matches = [record for record in records if record["value_result_match"]]
    categories: dict[str, dict[str, Any]] = {}
    for record in records:
        category = categories.setdefault(record["category"], {"total": 0, "passed": 0})
        category["total"] += 1
        category["passed"] += int(record["passed"])
    for category in categories.values():
        category["accuracy"] = round(category["passed"] / category["total"] * 100, 2)

    latencies = [record["latency_ms"] for record in successful]
    return {
        "total_cases": total,
        "execution_success_count": len(successful),
        "execution_success_rate": round(len(successful) / total * 100, 2),
        "result_match_count": len(passed),
        "result_match_rate": round(len(passed) / total * 100, 2),
        "strict_result_match_rate": round(len(strict_matches) / total * 100, 2),
        "value_result_match_rate": round(len(value_matches) / total * 100, 2),
        "latency_ms": {
            "p50": round(median(latencies), 2) if latencies else None,
            "p95": round(percentile_95(latencies), 2) if latencies else None,
        },
        "categories": categories,
    }


def write_reports(
    output_dir: Path,
    cases_path: Path,
    api_url: str,
    records: list[dict[str, Any]],
    summary: dict[str, Any],
) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = output_dir / f"evaluation_{run_id}.csv"
    json_path = output_dir / f"evaluation_{run_id}.json"
    markdown_path = output_dir / f"evaluation_{run_id}.md"

    with csv_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "id", "category", "query", "status", "passed", "execution_success",
                "comparison_mode", "strict_result_match", "value_result_match",
                "latency_ms", "error_message", "expected_result", "actual_result",
            ],
        )
        writer.writeheader()
        for record in records:
            row = record.copy()
            row["expected_result"] = json.dumps(row["expected_result"], ensure_ascii=False)
            row["actual_result"] = json.dumps(row["actual_result"], ensure_ascii=False)
            writer.writerow(row)

    report_data = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "cases_path": str(cases_path),
        "api_url": api_url,
        "summary": summary,
        "records": records,
    }
    json_path.write_text(json.dumps(report_data, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# NL2SQL Evaluation Report",
        "",
        f"- Generated at: {report_data['generated_at']}",
        f"- Cases: {cases_path}",
        f"- API: {api_url}",
        "",
        "## Overall",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Cases | {summary['total_cases']} |",
        f"| SQL execution success rate | {summary['execution_success_rate']}% ({summary['execution_success_count']}/{summary['total_cases']}) |",
        f"| Selected result match rate | {summary['result_match_rate']}% ({summary['result_match_count']}/{summary['total_cases']}) |",
        f"| Strict result match rate | {summary['strict_result_match_rate']}% |",
        f"| Value-only result match rate | {summary['value_result_match_rate']}% |",
        f"| P50 latency | {summary['latency_ms']['p50']} ms |",
        f"| P95 latency | {summary['latency_ms']['p95']} ms |",
        "",
        "## By Category",
        "",
        "| Category | Passed | Total | Result Match Rate |",
        "| --- | --- | --- | --- |",
    ]
    for name, category in summary["categories"].items():
        lines.append(
            f"| {name} | {category['passed']} | {category['total']} | {category['accuracy']}% |"
        )

    failed_records = [record for record in records if not record["passed"]]
    if failed_records:
        lines.extend(["", "## Failed Cases", ""])
        for record in failed_records:
            lines.extend(
                [
                    f"### {record['id']} ({record['status']})",
                    "",
                    f"- Question: {record['query']}",
                    f"- Error: {record['error_message'] or 'Result mismatch'}",
                    f"- Expected: `{json.dumps(record['expected_result'], ensure_ascii=False)}`",
                    f"- Actual: `{json.dumps(record['actual_result'], ensure_ascii=False)}`",
                    "",
                ]
            )
    markdown_path.write_text("\n".join(lines), encoding="utf-8")
    return csv_path, json_path, markdown_path


def main() -> int:
    args = parse_args()
    try:
        cases = load_cases(args.cases, args.limit)
        print(f"Loading expected results for {len(cases)} cases from MySQL...")
        expected_results = asyncio.run(load_expected_results(cases))
        print(f"Calling agent endpoint: {args.url}")
        records = evaluate_cases(cases, expected_results, args.url, args.timeout)
    except Exception as exc:
        print(f"Evaluation setup failed: {exc}", file=sys.stderr)
        return 2

    summary = build_summary(records)
    csv_path, json_path, markdown_path = write_reports(
        args.output_dir, args.cases, args.url, records, summary
    )
    print("\nEvaluation complete")
    print(
        f"Result match rate: {summary['result_match_rate']}% "
        f"({summary['result_match_count']}/{summary['total_cases']})"
    )
    print(f"CSV report: {csv_path}")
    print(f"JSON report: {json_path}")
    print(f"Markdown report: {markdown_path}")
    return 1 if args.fail_on_error and summary["result_match_count"] != summary["total_cases"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
