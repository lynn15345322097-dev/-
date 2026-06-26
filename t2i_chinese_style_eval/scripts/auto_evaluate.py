"""auto_evaluate.py — 对比法客观评价（Plan A：同 Prompt 多模型排名）

对每条 (prompt_id, replicate_idx)，将 M01/M02/M03 三张图一起送入模型，
在四个维度上排出 1-2-3 名并给出 1-5 分。结果写入 auto_scores.csv。

用法：
    python3 scripts/auto_evaluate.py --dry-run --limit 3
    python3 scripts/auto_evaluate.py --execute --limit 2
    python3 scripts/auto_evaluate.py --execute --evaluator E01
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import random
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

API_TIMEOUT_SEC = 180
MAX_RETRIES = 2
RETRY_BACKOFF_SEC = [5, 15]

LABEL_POOL = ["A", "B", "C"]
DIMS = ["style_fidelity", "element_accuracy", "forbidden_compliance", "overall_score"]


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


def load_evaluator_config(csv_path: Path) -> dict[str, dict]:
    configs = {}
    if not csv_path.exists():
        return configs
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            configs[row["evaluator_id"]] = row
    return configs


def img_to_b64(path: str) -> tuple[str, str]:
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    suffix = Path(path).suffix.lower()
    mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".webp": "image/webp"}
    return b64, mime_map.get(suffix, "image/png")


# ---------------------------------------------------------------------------
# 数据分组
# ---------------------------------------------------------------------------

def build_groups(project_root: Path) -> list[dict]:
    """从 metadata.csv + rating_items.csv 构建对比组。"""
    with open(project_root / "data" / "metadata.csv", encoding="utf-8") as f:
        meta_rows = list(csv.DictReader(f))
    with open(project_root / "data" / "rating_items.csv", encoding="utf-8") as f:
        rating_rows = list(csv.DictReader(f))

    rating_map = {r["image_id"]: r for r in rating_rows}
    blind_dir = project_root / "images" / "blind"

    # 按 (prompt_id, replicate_idx) 分组
    groups_dict = defaultdict(list)
    for m in meta_rows:
        key = (m["prompt_id"], m["replicate_idx"])
        groups_dict[key].append(m)

    groups = []
    for (prompt_id, replicate_idx), members in groups_dict.items():
        images = []
        # 随机打乱避免位置偏差
        shuffled = list(members)
        random.shuffle(shuffled)

        for i, m in enumerate(shuffled):
            img_id = m["image_id"]
            ri = rating_map.get(img_id, {})
            path = blind_dir / m["blind_filename"]
            if path.exists():
                images.append({
                    "label": LABEL_POOL[i],
                    "image_id": img_id,
                    "model_id": m["model_id"],
                    "path": str(path),
                })

        if len(images) < 2:
            continue  # 无法对比，跳过

        # 用第一张图的 rating 信息（同组内相同）
        ref_img = shuffled[0]["image_id"]
        ri = rating_map.get(ref_img, {})

        groups.append({
            "prompt_id": prompt_id,
            "replicate_idx": replicate_idx,
            "target_style": ri.get("target_style", ""),
            "prompt_text": ri.get("prompt_text", ""),
            "expected_elements": ri.get("expected_elements", ""),
            "forbidden_elements": ri.get("forbidden_elements", ""),
            "images": images,
        })

    return groups


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

PLAN_A_PROMPT = """你是图像生成结果的客观评价员。下面是同一条生成任务的 {n} 张结果图，来自不同模型。

任务信息：
- 目标风格：{target_style}
- Prompt：{prompt_text}
- 期望元素：{expected_elements}
- 禁止元素：{forbidden_elements}

请在以下四个维度，分别对这 {n} 张图排出名次，并给出 1-5 评分。

维度说明：
1. style_fidelity：形式风格一致性 — 图像整体是否符合目标传统视觉风格。重点判断形式语言、构图、色彩特征、线条笔触、媒介感是否接近目标风格，而非高清/精致程度。
2. element_accuracy：对象元素准确性 — 图像是否准确呈现 prompt 和期望元素要求的主要对象和关键元素。对象疑似、形态不完整、位置不清楚，应视为 partial。
3. forbidden_compliance：干扰元素规避程度 — 图像是否避免了禁止元素、以及不服务于当前任务导致风格偏移的无关元素（包括不恰当的泛中国风元素）。分数越高，干扰越少。
4. overall_score：综合评分 — 综合前三项判断任务完成度。

评分基准：3 = 基本完成但存在明显问题；4 = 完成较好，大部分要求满足但有改进空间；5 = 各方面无可挑剔。请严格评分，拉开差距。

只输出 JSON，不要其他文字：

{{
  "style_fidelity": {{
    "rank": [{labels_quoted}],
    "scores": {{ {labels_scores} }},
    "reason": "一句话解释排名理由"
  }},
  "element_accuracy": {{
    "rank": [{labels_quoted}],
    "scores": {{ {labels_scores} }},
    "reason": "..."
  }},
  "forbidden_compliance": {{
    "rank": [{labels_quoted}],
    "scores": {{ {labels_scores} }},
    "reason": "..."
  }},
  "overall_score": {{
    "rank": [{labels_quoted}],
    "scores": {{ {labels_scores} }},
    "reason": "..."
  }}
}}"""


def build_plan_a_prompt(group: dict) -> tuple[str, dict[str, str]]:
    """构建 prompt，返回 (prompt_text, label_to_model_id_map)。"""
    images = group["images"]
    n = len(images)
    labels = [img["label"] for img in images]
    labels_quoted = ", ".join(f'"{l}"' for l in labels)
    labels_scores = ", ".join(f'"{l}": 1' for l in labels)

    label2mid = {img["label"]: img["model_id"] for img in images}

    prompt = PLAN_A_PROMPT.format(
        n=n,
        target_style=group["target_style"],
        prompt_text=group["prompt_text"],
        expected_elements=group["expected_elements"],
        forbidden_elements=group["forbidden_elements"] or "（无）",
        labels_quoted=labels_quoted,
        labels_scores=labels_scores,
    )
    return prompt, label2mid


# ---------------------------------------------------------------------------
# API 后端
# ---------------------------------------------------------------------------

def _parse_json_text(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError(f"模型返回非 JSON:\n{text[:500]}")


def call_gemini(parts: list, api_key: str) -> dict:
    resp = requests.post(
        "https://generativelanguage.googleapis.com/v1beta/"
        "models/gemini-3.5-flash:generateContent",
        params={"key": api_key},
        json={
            "contents": [{"parts": parts}],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
        },
        timeout=API_TIMEOUT_SEC,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"Gemini API 错误: {data['error']}")
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        finish = data.get("candidates", [{}])[0].get("finishReason", "?")
        raise RuntimeError(f"Gemini 响应异常 (finish_reason={finish})")
    return _parse_json_text(text)


def call_glm4v(parts: list, api_key: str) -> dict:
    """智谱 GLM-4V — 把 Gemini 格式 parts 转成 OpenAI 格式。"""
    messages_content = []
    for p in parts:
        if "text" in p:
            messages_content.append({"type": "text", "text": p["text"]})
        elif "inline_data" in p:
            d = p["inline_data"]
            messages_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:{d['mime_type']};base64,{d['data']}"},
            })

    resp = requests.post(
        "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": "glm-4v",
            "messages": [{"role": "user", "content": messages_content}],
            "max_tokens": 2048,
            "temperature": 0.1,
        },
        timeout=API_TIMEOUT_SEC,
    )
    if resp.status_code != 200:
        raise RuntimeError(f"GLM-4V HTTP {resp.status_code}: {resp.text[:300]}")
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"GLM-4V API 错误: {data['error']}")
    return _parse_json_text(data["choices"][0]["message"]["content"])


EVALUATOR_BACKENDS = {
    "E01": {"call_group": call_gemini, "env_key": "GEMINI_API_KEY", "format": "gemini"},
    "E04": {"call_group": call_glm4v, "env_key": "ZHIPU_API_KEY", "format": "openai"},
}


# ---------------------------------------------------------------------------
# 对比评价
# ---------------------------------------------------------------------------

def evaluate_group(group: dict, evaluator_id: str, backend: dict) -> list[dict]:
    """评价一组图片，返回每张图的 auto_scores 行列表。"""
    prompt_text, label2mid = build_plan_a_prompt(group)

    # 构建 Gemini format parts（GLM-4V 会内部转换）
    parts = [{"text": prompt_text}]
    for img in group["images"]:
        b64, mime = img_to_b64(img["path"])
        parts.append({"text": f"\n--- Image {img['label']} ({img['model_id']}) ---"})
        parts.append({"inline_data": {"mime_type": mime, "data": b64}})

    call_fn = backend["call_group"]
    last_err = None
    for attempt in range(1 + MAX_RETRIES):
        try:
            resp = call_fn(parts, backend["api_key"])
            break
        except Exception as e:
            last_err = str(e)
            if attempt < MAX_RETRIES:
                backoff = RETRY_BACKOFF_SEC[attempt]
                print(f"    [RETRY] attempt={attempt+1} wait={backoff}s: {last_err[:100]}")
                time.sleep(backoff)
    else:
        # All retries failed
        rows = []
        for img in group["images"]:
            rows.append({
                "score_id": "", "image_id": img["image_id"],
                "evaluator_id": evaluator_id, "evaluated_at": now_iso(),
                "style_fidelity": "", "element_accuracy": "",
                "context_appropriateness": "", "forbidden_compliance": "",
                "overall_score": "", "expected_hits": "", "forbidden_hits": "",
                "raw_response_json": "",
                "error_message": f"API失败: {last_err[:200]}",
            })
        return rows

    raw_json = json.dumps(resp, ensure_ascii=False)

    # 解析结果
    rows = []
    label2img = {img["label"]: img for img in group["images"]}

    for dim in DIMS:
        dim_data = resp.get(dim)
        if not isinstance(dim_data, dict):
            continue
        scores = dim_data.get("scores", {})
        for label, score in scores.items():
            if label not in label2img:
                continue

    # 按 image_id 聚合
    score_map = defaultdict(dict)
    for dim in DIMS:
        dim_data = resp.get(dim, {})
        if not isinstance(dim_data, dict):
            continue
        scores = dim_data.get("scores", {})
        for label, score in scores.items():
            img = label2img.get(label)
            if img:
                score_map[img["image_id"]][dim] = score

    for img in group["images"]:
        dims = score_map.get(img["image_id"], {})
        rows.append({
            "score_id": "",
            "image_id": img["image_id"],
            "evaluator_id": evaluator_id,
            "evaluated_at": now_iso(),
            "style_fidelity": str(dims.get("style_fidelity", "")),
            "element_accuracy": str(dims.get("element_accuracy", "")),
            "context_appropriateness": "",
            "forbidden_compliance": str(dims.get("forbidden_compliance", "")),
            "overall_score": str(dims.get("overall_score", "")),
            "expected_hits": "",
            "forbidden_hits": "",
            "raw_response_json": raw_json,
            "error_message": "",
        })

    return rows


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

    eval_configs = load_evaluator_config(project_root / "data" / "evaluator_models.csv")

    ap = argparse.ArgumentParser(description="对比法客观评价 (Plan A)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--execute", action="store_true")
    ap.add_argument("--evaluator", default="E01",
                    help=f"评价模型 ID: {', '.join(eval_configs.keys())} (默认 E01)")
    ap.add_argument("--limit", type=_non_negative_int, default=None,
                    help="限制对比组数量")
    ap.add_argument("--prompt-id", default=None, help="只评价指定 prompt")
    ap.add_argument("--seed", type=int, default=42, help="随机种子 (默认 42)")
    args = ap.parse_args()

    random.seed(args.seed)

    if args.evaluator not in eval_configs:
        sys.exit(f"ERROR: 未知评价模型 '{args.evaluator}'")

    eid = args.evaluator
    econfig = eval_configs[eid]
    backend_entry = EVALUATOR_BACKENDS.get(eid)
    if backend_entry is None:
        sys.exit(f"ERROR: '{eid}' 后端未实现")

    api_key = os.environ.get(backend_entry["env_key"], "")
    if not api_key:
        print(f"[WARN] {backend_entry['env_key']} 未设置")
    backend = {"call_group": backend_entry["call_group"], "api_key": api_key}

    # 构建对比组
    all_groups = build_groups(project_root)
    if args.prompt_id:
        all_groups = [g for g in all_groups if g["prompt_id"] == args.prompt_id]
    if args.limit is not None:
        all_groups = all_groups[:args.limit]

    print(f"模型: {eid} ({econfig['evaluator_name']})")
    print(f"对比组: {len(all_groups)} 组, 共 {sum(len(g['images']) for g in all_groups)} 张图")

    if not all_groups:
        print("无匹配组")
        return 0

    # 去重
    scores_path = project_root / "data" / "auto_scores.csv"
    scored_ids = set()
    existing = []
    if scores_path.exists():
        with open(scores_path, encoding="utf-8") as f:
            existing = list(csv.DictReader(f))
        for r in existing:
            if not r.get("error_message") and r["evaluator_id"] == eid:
                scored_ids.add(r["image_id"])

    # 过滤已评组
    pending_groups = []
    for g in all_groups:
        img_ids = {img["image_id"] for img in g["images"]}
        if not img_ids.issubset(scored_ids):
            pending_groups.append(g)

    print(f"已评组: {len(all_groups) - len(pending_groups)}, 待评: {len(pending_groups)}")

    if args.dry_run:
        for g in pending_groups[:5]:
            models = [img["model_id"] for img in g["images"]]
            print(f"  {g['prompt_id']} rep{g['replicate_idx']} | {g['target_style']} "
                  f"| models={models}")
        if len(pending_groups) > 5:
            print(f"  ... 还有 {len(pending_groups)-5} 组")
        print(f"\n[DRY-RUN] 未调用 API")
        return 0

    if not pending_groups:
        print("无待评价组")
        return 0

    if not api_key:
        sys.exit(f"ERROR: {backend_entry['env_key']} 未设置")

    print(f"[EXECUTE] 顺序评价 {len(pending_groups)} 组")

    max_n = 0
    for r in existing:
        s = r.get("score_id", "")
        if s.startswith("S"):
            try:
                max_n = max(max_n, int(s[1:]))
            except ValueError:
                pass

    all_rows = list(existing)
    success_groups = failed_groups = 0

    for idx, group in enumerate(pending_groups):
        models = [img["model_id"] for img in group["images"]]
        print(f"  [{idx+1}/{len(pending_groups)}] {group['prompt_id']} rep{group['replicate_idx']} "
              f"{group['target_style']} ({', '.join(models)})")

        rows = evaluate_group(group, eid, backend)

        any_fail = any(r["error_message"] for r in rows)
        if any_fail:
            failed_groups += 1
        else:
            success_groups += 1

        for row in rows:
            max_n += 1
            row["score_id"] = f"S{max_n:04d}"
            if row["error_message"]:
                print(f"    [FAIL] {row['image_id']}: {row['error_message'][:100]}")
            else:
                print(f"    [OK]  {row['image_id']} ({group['target_style']}) "
                      f"s={row['style_fidelity']} e={row['element_accuracy']} "
                      f"f={row['forbidden_compliance']} → {row['overall_score']}")

        all_rows.extend(rows)

        with open(scores_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=SCORE_FIELDS, extrasaction="ignore")
            w.writeheader()
            w.writerows(all_rows)

    print(f"\n[DONE] groups success={success_groups} failed={failed_groups}")
    print(f"        images scored={success_groups * 3 - sum(1 for r in all_rows[-len(pending_groups)*3:] if r['error_message'])}")

    import subprocess
    subprocess.run([sys.executable, str(project_root / "scripts" / "validate_schema.py")],
                   stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)

    return 0 if failed_groups == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
