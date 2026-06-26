"""validate_schema.py — 账本完整性校验（只读，不改）

检查项：
  1. 文件存在 + 表头与 schema 期望一致
  2. 必填字段非空
  3. ID 唯一性
  4. 枚举值合法（prompt_level / status / role）
  5. 外键引用完整性（9 条关系）
  6. 盲评隔离硬约束：rating_items.csv 不得包含敏感字段
  7. 数值类型 / 范围
       replicate_idx int >= 1
       attempts      int >= 0
       timeout_sec   int >= 0 (非空时)
       seed          int       (非空时)
       image_width/image_height int > 0 (非空时)
       auto_scores 评分 1-5；overall_score float in [1, 5]
       human_scores 评分 1-5；overall_score int 1-5
       safety_blocked ∈ {true, false, ""}
  8. ISO8601 时间字段（非空时）：
       fromisoformat(value.replace("Z", "+00:00")) 必须成功

退出码：
    0 — 全部通过或仅 WARN
    1 — 出现任何 ERROR

输出格式：
    [LEVEL] file:line  field=<name>  issue=<type>  value=<value>
            → 修复建议
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"

# ------------------------------------------------------------------
# Schema 定义
# ------------------------------------------------------------------

EXPECTED_HEADERS: dict[str, list[str]] = {
    "prompts.csv": [
        "prompt_id", "target_style", "prompt_level", "prompt_text",
        "expected_elements", "forbidden_elements",
    ],
    "models.csv": [
        "model_id", "model_name", "provider", "api_endpoint",
        "model_version", "default_params", "notes",
    ],
    "evaluator_models.csv": [
        "evaluator_id", "evaluator_name", "provider", "api_endpoint",
        "model_version", "role", "notes",
    ],
    "generation_jobs.csv": [
        "job_id", "prompt_id", "model_id", "replicate_idx", "seed",
        "status", "attempts",
        "original_prompt", "revised_prompt", "revision_reason",
        "raw_image_path", "error_code", "error_message",
        "timeout_sec", "safety_blocked",
        "created_at", "started_at", "finished_at",
    ],
    "metadata.csv": [
        "image_id", "blind_filename", "job_id", "prompt_id", "model_id",
        "replicate_idx", "seed",
        "original_prompt", "revised_prompt", "revision_reason",
        "raw_image_path", "blind_image_path",
        "image_width", "image_height", "generated_at",
    ],
    "rating_items.csv": [
        "image_id", "blind_filename", "target_style", "prompt_level",
        "prompt_text", "expected_elements", "forbidden_elements",
    ],
    "auto_scores.csv": [
        "score_id", "image_id", "evaluator_id", "evaluated_at",
        "style_fidelity", "element_accuracy", "context_appropriateness",
        "forbidden_compliance", "overall_score",
        "expected_hits", "forbidden_hits", "raw_response_json", "error_message",
    ],
    "human_scores.csv": [
        "rating_id", "image_id", "rater_id", "rated_at",
        "style_fidelity", "element_accuracy", "context_appropriateness",
        "overall_score", "error_tags", "comment",
    ],
}

PRIMARY_KEYS: dict[str, str] = {
    "prompts.csv": "prompt_id",
    "models.csv": "model_id",
    "evaluator_models.csv": "evaluator_id",
    "generation_jobs.csv": "job_id",
    "metadata.csv": "image_id",
    "auto_scores.csv": "score_id",
    "human_scores.csv": "rating_id",
}

REQUIRED_FIELDS: dict[str, list[str]] = {
    "prompts.csv": ["prompt_id", "target_style", "prompt_level", "prompt_text"],
    "models.csv": ["model_id", "model_name", "provider"],
    "evaluator_models.csv": ["evaluator_id", "evaluator_name", "provider", "role"],
    "generation_jobs.csv": ["job_id", "prompt_id", "model_id", "replicate_idx", "status", "attempts"],
    "metadata.csv": ["image_id", "blind_filename", "job_id", "prompt_id", "model_id"],
    "rating_items.csv": ["image_id", "blind_filename", "target_style", "prompt_level", "prompt_text"],
    "auto_scores.csv": ["score_id", "image_id", "evaluator_id"],
    "human_scores.csv": ["rating_id", "image_id", "rater_id"],
}

ALLOWED_PROMPT_LEVELS = {"L1", "L2"}
ALLOWED_JOB_STATUS = {"pending", "running", "success", "failed", "timeout", "safety_blocked"}
ALLOWED_EVALUATOR_ROLES = {"primary", "reserved_for_v1", "reserved_cultural_supplement"}
ALLOWED_BOOL = {"true", "false", ""}

# 盲评隔离硬约束：rating_items.csv 禁含字段
FORBIDDEN_RATING_FIELDS = {
    "model_id", "model_name", "seed", "job_id",
    "original_prompt", "revised_prompt", "raw_image_path",
}

# ISO8601 时间字段
TIME_FIELDS: dict[str, list[str]] = {
    "generation_jobs.csv": ["created_at", "started_at", "finished_at"],
    "metadata.csv": ["generated_at"],
    "auto_scores.csv": ["evaluated_at"],
    "human_scores.csv": ["rated_at"],
}

# 评分字段（统一 1-5）
SCORE_FIELDS_INT_1_5 = [
    "style_fidelity", "element_accuracy",
    "context_appropriateness", "forbidden_compliance",
]

# ------------------------------------------------------------------
# Report
# ------------------------------------------------------------------

class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def error(self, file: str, line: int | str, field: str, issue: str, value: str, fix: str) -> None:
        self.errors.append(self._format("ERROR", file, line, field, issue, value, fix))

    def warn(self, file: str, line: int | str, field: str, issue: str, value: str, fix: str) -> None:
        self.warnings.append(self._format("WARN", file, line, field, issue, value, fix))

    @staticmethod
    def _format(level: str, file: str, line: int | str, field: str, issue: str, value: str, fix: str) -> str:
        return (
            f"[{level}] {file}:{line}  field={field}  issue={issue}  value={value!r}\n"
            f"        → {fix}"
        )

    def render(self) -> int:
        for w in self.warnings:
            print(w)
        for e in self.errors:
            print(e)
        print()
        print(f"summary: {len(self.errors)} error(s), {len(self.warnings)} warning(s)")
        return 1 if self.errors else 0

# ------------------------------------------------------------------
# 工具
# ------------------------------------------------------------------

def load(name: str, report: Report) -> tuple[list[str], list[dict]]:
    path = DATA_DIR / name
    if not path.exists():
        report.error(name, "-", "-", "missing_file", str(path), f"创建 {path}")
        return [], []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames or []
        rows = list(reader)
    return header, rows


def check_header(name: str, header: list[str], report: Report) -> None:
    expected = EXPECTED_HEADERS.get(name)
    if expected is None:
        return
    if header != expected:
        missing = [c for c in expected if c not in header]
        extra = [c for c in header if c not in expected]
        report.error(
            name, 1, "header",
            "header_mismatch",
            f"got={header}",
            f"应为 {expected}；缺少={missing}；多余={extra}",
        )


def check_required(name: str, rows: list[dict], report: Report) -> None:
    for idx, row in enumerate(rows, start=2):
        for col in REQUIRED_FIELDS.get(name, []):
            if not (row.get(col) or "").strip():
                report.error(name, idx, col, "empty_required",
                             row.get(col, ""), f"补齐 {col} 字段")


def check_unique(name: str, rows: list[dict], report: Report) -> None:
    pk = PRIMARY_KEYS.get(name)
    if not pk:
        return
    seen: dict[str, int] = {}
    for idx, row in enumerate(rows, start=2):
        v = (row.get(pk) or "").strip()
        if not v:
            continue
        if v in seen:
            report.error(name, idx, pk, "duplicate_id", v,
                         f"与第 {seen[v]} 行重复；改为唯一值")
        else:
            seen[v] = idx


def check_enum(name: str, rows: list[dict], field: str, allowed: set[str], report: Report) -> None:
    for idx, row in enumerate(rows, start=2):
        v = (row.get(field) or "").strip()
        if v and v not in allowed:
            report.error(name, idx, field, "invalid_enum", v,
                         f"必须 ∈ {sorted(allowed)}")


def check_fk(child_name: str, child_rows: list[dict], child_field: str,
             parent_ids: set[str], report: Report,
             allow_empty: bool = False) -> None:
    for idx, row in enumerate(child_rows, start=2):
        v = (row.get(child_field) or "").strip()
        if not v:
            if not allow_empty:
                report.error(child_name, idx, child_field, "empty_fk", v,
                             "外键不可为空")
            continue
        if v not in parent_ids:
            report.error(child_name, idx, child_field, "fk_not_found", v,
                         "在父表中找不到该引用")


def check_rating_items_isolation(header: list[str], report: Report) -> None:
    leaked = [c for c in header if c in FORBIDDEN_RATING_FIELDS]
    if leaked:
        report.error(
            "rating_items.csv", 1, ",".join(leaked),
            "blind_isolation_violation", str(leaked),
            "盲评隔离硬约束：从 rating_items.csv 移除上述字段；它们只能存在于 metadata.csv",
        )


# ------------------------------------------------------------------
# 数值 / 类型 / 时间 校验
# ------------------------------------------------------------------

def _parse_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_iso8601(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return True
    except (TypeError, ValueError):
        return False


def check_int_field(name: str, rows: list[dict], field: str,
                    min_value: int | None, allow_empty: bool,
                    report: Report) -> None:
    for idx, row in enumerate(rows, start=2):
        v = (row.get(field) or "").strip()
        if not v:
            if not allow_empty:
                report.error(name, idx, field, "empty_required", v, f"必须为整数")
            continue
        n = _parse_int(v)
        if n is None:
            report.error(name, idx, field, "not_int", v, "必须为整数")
        elif min_value is not None and n < min_value:
            report.error(name, idx, field, "out_of_range", v, f"必须 >= {min_value}")


def check_score_int_1_5(name: str, rows: list[dict], field: str, report: Report) -> None:
    for idx, row in enumerate(rows, start=2):
        v = (row.get(field) or "").strip()
        if not v:
            continue
        n = _parse_int(v)
        if n is None:
            report.error(name, idx, field, "not_int", v, "评分必须为整数")
        elif not (1 <= n <= 5):
            report.error(name, idx, field, "out_of_range", v, "评分必须在 1-5")


def check_score_float_1_5(name: str, rows: list[dict], field: str, report: Report) -> None:
    for idx, row in enumerate(rows, start=2):
        v = (row.get(field) or "").strip()
        if not v:
            continue
        f = _parse_float(v)
        if f is None:
            report.error(name, idx, field, "not_float", v, "必须为浮点数")
        elif not (1.0 <= f <= 5.0):
            report.error(name, idx, field, "out_of_range", v, "必须在 [1, 5]")


def check_bool_field(name: str, rows: list[dict], field: str, report: Report) -> None:
    for idx, row in enumerate(rows, start=2):
        v = (row.get(field) or "").strip()
        if v not in ALLOWED_BOOL:
            report.error(name, idx, field, "not_bool", v, "必须为 true / false / 空")


def check_time_field(name: str, rows: list[dict], field: str, report: Report) -> None:
    for idx, row in enumerate(rows, start=2):
        v = (row.get(field) or "").strip()
        if not v:
            continue  # 空值允许
        if not _parse_iso8601(v):
            report.error(name, idx, field, "invalid_iso8601", v,
                         "必须为 ISO8601 字符串（支持 'Z' 结尾或 +00:00 时区，或无时区）")


def check_numeric_and_time(data: dict[str, tuple[list[str], list[dict]]], report: Report) -> None:
    # generation_jobs.csv
    jobs = data["generation_jobs.csv"][1]
    check_int_field("generation_jobs.csv", jobs, "replicate_idx", min_value=1, allow_empty=False, report=report)
    check_int_field("generation_jobs.csv", jobs, "attempts", min_value=0, allow_empty=False, report=report)
    check_int_field("generation_jobs.csv", jobs, "timeout_sec", min_value=0, allow_empty=True, report=report)
    check_int_field("generation_jobs.csv", jobs, "seed", min_value=None, allow_empty=True, report=report)
    check_bool_field("generation_jobs.csv", jobs, "safety_blocked", report)

    # metadata.csv
    meta = data["metadata.csv"][1]
    check_int_field("metadata.csv", meta, "replicate_idx", min_value=1, allow_empty=False, report=report)
    check_int_field("metadata.csv", meta, "seed", min_value=None, allow_empty=True, report=report)
    check_int_field("metadata.csv", meta, "image_width", min_value=1, allow_empty=True, report=report)
    check_int_field("metadata.csv", meta, "image_height", min_value=1, allow_empty=True, report=report)

    # auto_scores.csv
    auto = data["auto_scores.csv"][1]
    for fld in SCORE_FIELDS_INT_1_5:
        check_score_int_1_5("auto_scores.csv", auto, fld, report)
    check_score_float_1_5("auto_scores.csv", auto, "overall_score", report)

    # human_scores.csv
    human = data["human_scores.csv"][1]
    for fld in ["style_fidelity", "element_accuracy", "context_appropriateness", "overall_score"]:
        check_score_int_1_5("human_scores.csv", human, fld, report)

    # ISO8601 时间字段
    for file, fields in TIME_FIELDS.items():
        rows = data[file][1]
        for fld in fields:
            check_time_field(file, rows, fld, report)


# ------------------------------------------------------------------
# 主流程
# ------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="检查 data/ 下所有 CSV 账本的完整性（只读，不修改）。"
                    "出现 ERROR 退出码 1；仅 WARN 或全通过退出码 0。"
    )
    return parser.parse_args()


def main() -> int:
    parse_args()
    report = Report()

    data: dict[str, tuple[list[str], list[dict]]] = {}
    for name in EXPECTED_HEADERS:
        data[name] = load(name, report)

    for name, (header, _) in data.items():
        check_header(name, header, report)

    for name, (_, rows) in data.items():
        check_required(name, rows, report)
        check_unique(name, rows, report)

    check_enum("prompts.csv", data["prompts.csv"][1], "prompt_level", ALLOWED_PROMPT_LEVELS, report)
    check_enum("generation_jobs.csv", data["generation_jobs.csv"][1], "status", ALLOWED_JOB_STATUS, report)
    check_enum("evaluator_models.csv", data["evaluator_models.csv"][1], "role", ALLOWED_EVALUATOR_ROLES, report)

    prompt_ids = {(r.get("prompt_id") or "").strip() for r in data["prompts.csv"][1]}
    model_ids = {(r.get("model_id") or "").strip() for r in data["models.csv"][1]}
    evaluator_ids = {(r.get("evaluator_id") or "").strip() for r in data["evaluator_models.csv"][1]}
    job_ids = {(r.get("job_id") or "").strip() for r in data["generation_jobs.csv"][1]}
    image_ids = {(r.get("image_id") or "").strip() for r in data["metadata.csv"][1]}

    check_fk("generation_jobs.csv", data["generation_jobs.csv"][1], "prompt_id", prompt_ids, report)
    check_fk("generation_jobs.csv", data["generation_jobs.csv"][1], "model_id", model_ids, report)
    check_fk("metadata.csv", data["metadata.csv"][1], "job_id", job_ids, report)
    check_fk("metadata.csv", data["metadata.csv"][1], "prompt_id", prompt_ids, report)
    check_fk("metadata.csv", data["metadata.csv"][1], "model_id", model_ids, report)
    check_fk("rating_items.csv", data["rating_items.csv"][1], "image_id", image_ids, report)
    check_fk("auto_scores.csv", data["auto_scores.csv"][1], "image_id", image_ids, report)
    check_fk("auto_scores.csv", data["auto_scores.csv"][1], "evaluator_id", evaluator_ids, report)
    check_fk("human_scores.csv", data["human_scores.csv"][1], "image_id", image_ids, report)

    check_rating_items_isolation(data["rating_items.csv"][0], report)
    check_numeric_and_time(data, report)

    return report.render()


if __name__ == "__main__":
    raise SystemExit(main())
