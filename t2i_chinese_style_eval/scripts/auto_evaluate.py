"""auto_evaluate.py — Gemini 3.5 Flash 客观评价

三个子模块（A/B/C）：
  A. 文本—图像对齐 → element_accuracy
  B. 风格候选分类 → style_fidelity
  C. 文化错配规则 → context_appropriateness + forbidden_compliance
  D. 综合分 → overall_score (加权)

模型只做离散判断，不直接输出 1-5 分；分数由确定性公式计算。

约束：
  - 仅读盲评数据（rating_items.csv + images/blind/），不接触 metadata.csv / model_id
  - 文化规则从 cultural_rules.yaml 注入，每个 target_style 一组
  - 强制 evidence 字段，原始 JSON 存入 raw_response_json 留审计

用法：
    python3 scripts/auto_evaluate.py --dry-run --limit 3
    python3 scripts/auto_evaluate.py --execute --image-id img_0001
    python3 scripts/auto_evaluate.py --execute
    python3 scripts/auto_evaluate.py --execute --limit 5
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import yaml

# ---------------------------------------------------------------------------
# 评分常量（用户定义）
# ---------------------------------------------------------------------------

# 综合分权重
W_STYLE = 0.35
W_ELEMENT = 0.30
W_CONTEXT = 0.20
W_FORBIDDEN = 0.15

# 文本-图像对齐：每元素权重
ELEMENT_WEIGHT = {"present": 1.0, "partial": 0.5, "missing": 0.0}

# 风格候选标签
STYLE_CANDIDATES = [
    "水墨山水",
    "敦煌壁画",
    "民间年画",
    "京剧脸谱",
    "现代国风插画",
    "写实摄影",
    "西方奇幻/游戏概念图",
    "普通数字插画",
]

# API 配置
API_TIMEOUT_SEC = 120
MAX_RETRIES = 2
RETRY_BACKOFF_SEC = [5, 15]
GEMINI_ENDPOINT = (
    "https://generativelanguage.googleapis.com/v1beta/"
    "models/gemini-3.5-flash:generateContent"
)


# ---------------------------------------------------------------------------
# 工具
# ---------------------------------------------------------------------------

def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


def _non_negative_int(value: str) -> int:
    n = int(value)
    if n < 0:
        raise argparse.ArgumentTypeError("limit must be >= 0")
    return n


# ---------------------------------------------------------------------------
# 文化规则
# ---------------------------------------------------------------------------

def load_cultural_rules(yaml_path: Path) -> dict:
    if not yaml_path.exists():
        print(f"[WARN] {yaml_path} 不存在，文化规则检查将跳过")
        return {}
    with open(yaml_path) as f:
        return yaml.safe_load(f) or {}


# ---------------------------------------------------------------------------
# 确定性评分公式
# ---------------------------------------------------------------------------

def compute_element_accuracy(results: dict) -> tuple:
    """present=1, partial=0.5, missing=0 → score=round(1+4×hit_rate)"""
    total = 0.0
    hits = []
    misses = []
    for elem, status in results.items():
        s = str(status).strip().lower()
        if s == "present":
            total += 1.0
            hits.append(elem)
        elif s == "partial":
            total += 0.5
            hits.append(f"{elem}(partial)")
        else:
            misses.append(elem)
    if not results:
        return (3, [], [])
    hit_rate = total / len(results)
    score = max(1, min(5, round(1 + 4 * hit_rate)))
    return (score, hits, misses)


def compute_style_fidelity(target_match: bool, target_rank: int, confidence: int) -> int:
    if target_match or target_rank == 1:
        return max(1, min(5, confidence))
    if target_rank == 2:
        return max(1, min(3, confidence))
    if target_rank == 3:
        return max(1, min(2, confidence))
    return 1


def compute_context_appropriateness(rule_results: list[dict]) -> int:
    severities = [r.get("severity", 0) for r in rule_results if r.get("triggered")]
    return max(1, 5 - (max(severities) if severities else 0))


def compute_forbidden_compliance(rule_results: list[dict]) -> tuple:
    triggered = [r for r in rule_results if r.get("triggered")]
    if not triggered:
        return (5, [])
    sev_sum = sum(r.get("severity", 0) for r in triggered)
    score = max(1, 5 - min(4, sev_sum))
    hits = [f"{r['rule_id']}(s={r.get('severity', 0)})" for r in triggered]
    return (score, hits)


def compute_overall(style: int, element: int, context: int, forbidden: int) -> float:
    return round(
        W_STYLE * style
        + W_ELEMENT * element
        + W_CONTEXT * context
        + W_FORBIDDEN * forbidden,
        1,
    )


# ---------------------------------------------------------------------------
# Prompt 构造
# ---------------------------------------------------------------------------

PROMPT_TEMPLATE = """你是一个中国文化视觉艺术评价专家。请仔细查看这张图像，按要求逐项判断。

## 基本信息
- 目标风格：{target_style}
- Prompt 原文：{prompt_text}
- 期望出现的元素：{expected_elements}

## 任务A：文本—图像对齐
对上述每个期望元素，判断其是否出现在图像中。
选择："present"（清晰出现）、"partial"（部分出现或模糊）、"missing"（未出现）。

## 任务B：风格识别
判断图像风格最接近哪个标签。

候选标签：{style_labels}

请根据图像视觉特征输出：
- top_label：最匹配的候选标签（必须从候选列表中选一个）
- target_match：top_label 是否等于目标风格 "{target_style}"（true/false）
- target_rank：目标风格在所有候选标签中的排名（1=最佳，2=第二，3=第三，0=不在前三）
- target_confidence：目标风格与图像的匹配程度（整数1-5，5=高度匹配）
- confusable_labels：最容易混淆的1-2个其他标签

## 任务C：文化错配规则检查
对以下每条规则，判断是否触发，给出严重度和证据。

{rules_text}

## 输出格式要求
只返回 JSON，不要任何其他文字。JSON 结构：

{{
  "element_alignment": {{
    "元素名": "present/partial/missing"
  }},
  "style_recognition": {{
    "top_label": "标签名",
    "target_match": true/false,
    "target_rank": 1-3或0,
    "target_confidence": 1-5的整数,
    "confusable_labels": ["标签1"]
  }},
  "cultural_rules": [
    {{"rule_id": "规则ID", "triggered": true/false, "severity": 0-3, "evidence": "证据"}}
  ],
  "evidence_summary": "用2-3句中文概括整体判断依据"
}}

注意：
- element_alignment 必须包含每个期望元素，不得遗漏
- cultural_rules 必须覆盖上面列出的全部规则，未触发的也要输出（severity=0）
- severity: 0=未触发, 1=轻微, 2=明显, 3=严重
- evidence_summary 不能为空"""


def build_prompt(target_style: str, prompt_text: str,
                 expected_elements: str, rules: list[dict]) -> str:
    elements_list = "、".join(e.strip() for e in expected_elements.split("；") if e.strip())
    style_labels = "、".join(STYLE_CANDIDATES)

    if rules:
        lines = [f"  {r['id']}: {r['desc']}" for r in rules]
        rules_text = "\n".join(lines)
    else:
        rules_text = "（无规则）"

    return PROMPT_TEMPLATE.format(
        target_style=target_style,
        prompt_text=prompt_text,
        expected_elements=elements_list,
        style_labels=style_labels,
        rules_text=rules_text,
    )


# ---------------------------------------------------------------------------
# Gemini API 调用
# ---------------------------------------------------------------------------

def call_gemini(image_path: str, prompt_text: str, api_key: str) -> dict:
    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")

    suffix = Path(image_path).suffix.lower()
    mime_map = {".png": "image/png", ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg", ".webp": "image/webp"}
    mime_type = mime_map.get(suffix, "image/png")

    body = {
        "contents": [{
            "parts": [
                {"text": prompt_text},
                {"inline_data": {"mime_type": mime_type, "data": image_b64}},
            ]
        }],
        "generationConfig": {
            "temperature": 0.1,
            "responseMimeType": "application/json",
        },
    }

    resp = requests.post(
        GEMINI_ENDPOINT,
        params={"key": api_key},
        json=body,
        timeout=API_TIMEOUT_SEC,
    )

    if resp.status_code != 200:
        raise RuntimeError(f"Gemini API HTTP {resp.status_code}: {resp.text[:300]}")

    data = resp.json()

    if "error" in data:
        raise RuntimeError(f"Gemini API 错误: {data['error']}")

    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as e:
        # 检查 finish_reason
        finish = data.get("candidates", [{}])[0].get("finishReason", "?")
        raise RuntimeError(
            f"无法解析 Gemini 响应 (finish_reason={finish}): "
            f"{json.dumps(data, ensure_ascii=False)[:400]}"
        )

    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError(f"Gemini 返回非 JSON:\n{text[:500]}")


# ---------------------------------------------------------------------------
# 校验返回结构
# ---------------------------------------------------------------------------

def validate_response(resp: dict, expected_elements: list[str],
                      rule_ids: list[str]) -> list[str]:
    issues = []

    ea = resp.get("element_alignment", {})
    if not isinstance(ea, dict):
        issues.append("element_alignment 不是 dict")
    else:
        for elem in expected_elements:
            if elem not in ea:
                issues.append(f"缺少元素: {elem}")

    sr = resp.get("style_recognition", {})
    if not isinstance(sr, dict):
        issues.append("style_recognition 不是 dict")
    else:
        for f in ("top_label", "target_match", "target_rank", "target_confidence"):
            if f not in sr:
                issues.append(f"style_recognition 缺字段: {f}")

    cr = resp.get("cultural_rules", [])
    if not isinstance(cr, list):
        issues.append("cultural_rules 不是 list")
    elif rule_ids:
        got = {r.get("rule_id") for r in cr}
        missing = set(rule_ids) - got
        if missing:
            issues.append(f"缺少规则: {missing}")

    if not resp.get("evidence_summary"):
        issues.append("evidence_summary 为空")

    return issues


# ---------------------------------------------------------------------------
# 主评价流程
# ---------------------------------------------------------------------------

def run_single(item: dict, rules: list[dict],
               api_key: str, blind_dir: Path) -> dict:
    """评价单张图，返回 auto_scores.csv 行 dict。"""
    image_id = item["image_id"]
    image_path = blind_dir / item["blind_filename"]

    empty_row = {
        "score_id": "",
        "image_id": image_id,
        "evaluator_id": "E01",
        "evaluated_at": now_iso(),
        "style_fidelity": "", "element_accuracy": "",
        "context_appropriateness": "", "forbidden_compliance": "",
        "overall_score": "", "expected_hits": "", "forbidden_hits": "",
        "raw_response_json": "", "error_message": "",
    }

    if not image_path.exists():
        empty_row["error_message"] = f"图片不存在: {image_path}"
        return empty_row

    expected = [e.strip() for e in item["expected_elements"].split("；") if e.strip()]
    rule_ids = [r["id"] for r in rules]

    prompt = build_prompt(
        target_style=item["target_style"],
        prompt_text=item["prompt_text"],
        expected_elements=item["expected_elements"],
        rules=rules,
    )

    last_err = None
    for attempt in range(1 + MAX_RETRIES):
        try:
            resp = call_gemini(str(image_path), prompt, api_key)

            issues = validate_response(resp, expected, rule_ids)
            raw_json = json.dumps(resp, ensure_ascii=False)
            if issues:
                empty_row["raw_response_json"] = raw_json
                empty_row["error_message"] = f"结构不完整: {'; '.join(issues)}"
                return empty_row

            # --- A: element_accuracy ---
            ea = resp.get("element_alignment", {})
            elem_score, exp_hits, exp_misses = compute_element_accuracy(ea)

            # --- B: style_fidelity ---
            sr = resp.get("style_recognition", {})
            st_score = compute_style_fidelity(
                target_match=sr.get("target_match", False),
                target_rank=int(sr.get("target_rank", 0)),
                confidence=int(sr.get("target_confidence", 3)),
            )

            # --- C: context + forbidden ---
            cr = resp.get("cultural_rules", [])
            ctx_score = compute_context_appropriateness(cr)
            forb_score, forb_hits = compute_forbidden_compliance(cr)

            # --- D: overall ---
            overall = compute_overall(st_score, elem_score, ctx_score, forb_score)

            return {
                "score_id": "",
                "image_id": image_id,
                "evaluator_id": "E01",
                "evaluated_at": now_iso(),
                "style_fidelity": str(st_score),
                "element_accuracy": str(elem_score),
                "context_appropriateness": str(ctx_score),
                "forbidden_compliance": str(forb_score),
                "overall_score": f"{overall:.1f}",
                "expected_hits": "；".join(exp_hits),
                "forbidden_hits": "；".join(forb_hits),
                "raw_response_json": raw_json,
                "error_message": "",
            }

        except Exception as e:
            last_err = str(e)
            if attempt < MAX_RETRIES:
                backoff = RETRY_BACKOFF_SEC[attempt]
                print(f"    [RETRY] {image_id} attempt={attempt+1} wait={backoff}s: {last_err[:100]}")
                time.sleep(backoff)

    empty_row["error_message"] = f"API失败(重试{MAX_RETRIES}次): {last_err[:300]}"
    return empty_row


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

SCORE_FIELDS = [
    "score_id", "image_id", "evaluator_id", "evaluated_at",
    "style_fidelity", "element_accuracy", "context_appropriateness",
    "forbidden_compliance", "overall_score",
    "expected_hits", "forbidden_hits", "raw_response_json", "error_message",
]


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    load_env(project_root / ".env")

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        print("[WARN] GEMINI_API_KEY 未设置；实际调用会失败")

    ap = argparse.ArgumentParser(description="Gemini 3.5 Flash 客观评价")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--execute", action="store_true")
    ap.add_argument("--limit", type=_non_negative_int, default=None)
    ap.add_argument("--image-id", default=None)
    ap.add_argument("--overwrite", action="store_true",
                    help="重评已存在的行")
    args = ap.parse_args()

    rating_path = project_root / "data" / "rating_items.csv"
    rules_path = project_root / "data" / "cultural_rules.yaml"
    blind_dir = project_root / "images" / "blind"
    scores_path = project_root / "data" / "auto_scores.csv"

    if not rating_path.exists():
        sys.exit("ERROR: rating_items.csv 不存在")

    with open(rating_path, encoding="utf-8") as f:
        all_items = list(csv.DictReader(f))

    rules_map = load_cultural_rules(rules_path)

    # 筛选
    items = all_items
    if args.image_id:
        items = [i for i in items if i["image_id"] == args.image_id]
    if args.limit is not None:
        items = items[:args.limit]

    if not items:
        print("无匹配项")
        return 0

    # 已有评分去重
    existing = []
    scored_keys = set()
    if scores_path.exists():
        with open(scores_path, encoding="utf-8") as f:
            existing = list(csv.DictReader(f))
        for r in existing:
            if not r.get("error_message"):
                scored_keys.add((r["image_id"], r["evaluator_id"]))

    pending = items
    if not args.overwrite:
        pending = [i for i in items if (i["image_id"], "E01") not in scored_keys]

    print(f"筛选 {len(items)} 项, 已评 {len(items)-len(pending)}, 待评 {len(pending)}")

    # dry-run
    if args.dry_run:
        for it in pending[:5]:
            r = rules_map.get(it["target_style"], [])
            print(f"  {it['image_id']} style={it['target_style']} level={it['prompt_level']} "
                  f"rules={len(r)}条")
        if len(pending) > 5:
            print(f"  ... 还有 {len(pending)-5} 项")
        print(f"\n[DRY-RUN] 未调用 API，未修改文件")
        return 0

    if not pending:
        print("无待评价项")
        return 0

    if not api_key:
        sys.exit("ERROR: GEMINI_API_KEY 未设置，无法执行")

    # 执行
    print(f"[EXECUTE] 顺序评价 {len(pending)} 项")

    # max score_id
    max_n = 0
    for r in existing:
        s = r.get("score_id", "")
        if s.startswith("S"):
            try:
                max_n = max(max_n, int(s[1:]))
            except ValueError:
                pass

    all_rows = list(existing)
    success = failed = 0

    for idx, it in enumerate(pending):
        image_id = it["image_id"]
        print(f"  [{idx+1}/{len(pending)}] {image_id} {it['target_style']} {it['prompt_level']}")

        rules = rules_map.get(it["target_style"], [])
        row = run_single(it, rules, api_key, blind_dir)

        max_n += 1
        row["score_id"] = f"S{max_n:04d}"

        if row["error_message"]:
            failed += 1
            print(f"    [FAIL] {row['error_message'][:120]}")
        else:
            success += 1
            print(f"    [OK] style={row['style_fidelity']} elem={row['element_accuracy']} "
                  f"ctx={row['context_appropriateness']} forb={row['forbidden_compliance']} "
                  f"→ {row['overall_score']}")

        all_rows.append(row)

        # 每完成一项写回
        with open(scores_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=SCORE_FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(all_rows)

    print(f"\n[DONE] success={success}  failed={failed}")

    # 跑 schema 校验
    import subprocess
    subprocess.run([sys.executable, str(project_root / "scripts" / "validate_schema.py")])

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
