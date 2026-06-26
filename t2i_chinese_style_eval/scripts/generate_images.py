"""generate_images.py — T2I 批量生成

模式：
  --dry-run   只打印将要执行的 job 与预估成本，不调 API、不写文件
  --execute   真实调用 API；当前支持 M01（OpenAI gpt-image-2）和 M02（DashScope wan2.7-image-pro）

CLI 组合：
  --execute --job-id Jxxxx         单 job 执行
  --execute --limit N              批量执行最多 N 条 pending
  --execute --model-id M01         只跑某模型的 pending
  --execute --limit N --model-id M01   组合
  --execute --retry-failed         重置 failed/timeout 的 job 后批量重跑（不重置 safety_blocked）

行为约定：
  顺序执行：每个 job 之间 sleep 1 秒，避免突发触发频控
  失败重试：单个 job 内对网络/超时/5xx 自动重试最多 2 次（attempts 上限 3）
            指数退避 5s -> 15s；不重试 safety_blocked 和 InvalidParameter
  断点续跑：success / safety_blocked 永远跳过；failed / timeout 默认跳过（需 --retry-failed）
  中断保护：每完成一个 job 立即写回 generation_jobs.csv；Ctrl+C 当前 job 跑完再退出
  日志：    logs/generate_<timestamp>.log 写每个 job 的开始/结束/耗时/状态

回填规则（status 决定其他字段语义）：
  成功:     status=success,        safety_blocked=false, raw_image_path=<path>
  安全拦截: status=safety_blocked, safety_blocked=true,  revision_reason=<msg>, raw_image_path=空
  超时:     status=timeout,        safety_blocked=false, timeout_sec=90,        raw_image_path=空
  其他失败: status=failed,         safety_blocked=false, error_code/error_message 写清楚
"""

from __future__ import annotations

import argparse
import base64
import csv
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = PROJECT_ROOT / "images" / "raw"
LOGS_DIR = PROJECT_ROOT / "logs"

JOBS_CSV = DATA_DIR / "generation_jobs.csv"
MODELS_CSV = DATA_DIR / "models.csv"

JOB_FIELDS = [
    "job_id", "prompt_id", "model_id", "replicate_idx", "seed",
    "status", "attempts",
    "original_prompt", "revised_prompt", "revision_reason",
    "raw_image_path", "error_code", "error_message",
    "timeout_sec", "safety_blocked",
    "created_at", "started_at", "finished_at",
]

TIMEOUT_SEC = 90  # 单 job 调用 + 轮询硬上限
POLL_INTERVAL_SEC = 3
INTER_JOB_SLEEP_SEC = 1
MAX_RETRIES_PER_JOB = 2  # 不含首次，总尝试 3 次
RETRY_BACKOFFS_SEC = [5, 15]  # 第 1 / 第 2 次重试前等待

# 每模型每张图的预估成本（人民币元）；用于 dry-run 提示
COST_PER_IMAGE_CNY = {"M01": 1.50, "M02": 0.60}

# OpenAI / DashScope 错误码中表示安全策略拦截的关键词
SAFETY_ERROR_HINTS = ("DataInspection", "InvalidContent", "InappropriateContent",
                      "RiskInput", "content_policy", "policy_violation",
                      "moderation_blocked", "safety", "禁止")

# 永不重试的错误码（明确的客户端错误）
NON_RETRYABLE_ERROR_CODES = ("InvalidParameter", "InvalidApiKey", "missing_api_key",
                             "unknown_model", "unsupported_model", "not_implemented",
                             "parse_response_error", "download_failed", "save_image_failed")


# ------------------------------------------------------------------
# .env 加载
# ------------------------------------------------------------------

def load_env(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


# ------------------------------------------------------------------
# CSV 读写
# ------------------------------------------------------------------

def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        sys.exit(f"ERROR: 找不到文件 {path}")
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_jobs(path: Path, jobs: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=JOB_FIELDS)
        writer.writeheader()
        writer.writerows(jobs)


def filter_jobs(jobs: list[dict], job_id: str | None,
                model_id: str | None, limit: int | None) -> list[dict]:
    selected = [j for j in jobs if j.get("status", "").strip() == "pending"]
    if job_id:
        selected = [j for j in selected if j["job_id"] == job_id]
    if model_id:
        selected = [j for j in selected if j["model_id"] == model_id]
    if limit is not None:
        selected = selected[:limit]
    return selected


def render_job_table(jobs: list[dict]) -> str:
    if not jobs:
        return "(无待执行任务)"
    header = f"{'job_id':<8} {'prompt_id':<14} {'model_id':<6} {'rep':<4} {'status':<10} prompt"
    lines = [header, "-" * len(header)]
    for j in jobs:
        prompt = (j.get("original_prompt") or "").strip()
        if len(prompt) > 40:
            prompt = prompt[:37] + "..."
        lines.append(
            f"{j['job_id']:<8} {j['prompt_id']:<14} {j['model_id']:<6} "
            f"{j['replicate_idx']:<4} {j['status']:<10} {prompt}"
        )
    return "\n".join(lines)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------
# M01 调用：OpenAI gpt-image-2
# ------------------------------------------------------------------

def call_m01(job: dict, model_row: dict) -> dict:
    """调用 OpenAI Image API。返回回填字段字典；不抛异常。"""
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key or api_key.startswith("sk-xxxx"):
        return {
            "status": "failed",
            "error_code": "missing_api_key",
            "error_message": "OPENAI_API_KEY 未设置",
        }

    endpoint = (model_row.get("api_endpoint") or "https://api.openai.com/v1/images/generations").strip()
    model_version = model_row["model_version"].strip()
    try:
        default_params = json.loads(model_row.get("default_params") or "{}")
    except json.JSONDecodeError:
        default_params = {}

    payload = {
        "model": model_version,
        "prompt": job["original_prompt"],
        "size": default_params.get("size", "1024x1024"),
        "quality": default_params.get("quality", "high"),
        "output_format": default_params.get("output_format", "png"),
    }
    if default_params.get("background"):
        payload["background"] = default_params["background"]
    if default_params.get("moderation"):
        payload["moderation"] = default_params["moderation"]

    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        code, msg = _parse_openai_error(body, fallback_code=f"HTTP_{e.code}")
        if _looks_like_safety(code, msg):
            return {
                "status": "safety_blocked",
                "safety_blocked": "true",
                "revision_reason": f"{code}: {msg}"[:300],
            }
        return {
            "status": "failed",
            "error_code": code,
            "error_message": msg[:300],
        }
    except TimeoutError:
        return {
            "status": "timeout",
            "timeout_sec": str(TIMEOUT_SEC),
            "error_code": "request_timeout",
            "error_message": f"OpenAI request 在 {TIMEOUT_SEC}s 内未完成",
        }
    except Exception as e:
        return {
            "status": "failed",
            "error_code": type(e).__name__,
            "error_message": str(e)[:300],
        }

    elapsed = time.time() - start
    if elapsed > TIMEOUT_SEC:
        return {
            "status": "timeout",
            "timeout_sec": str(TIMEOUT_SEC),
            "error_code": "request_timeout",
            "error_message": f"OpenAI request 耗时 {elapsed:.1f}s，超过 {TIMEOUT_SEC}s",
        }

    try:
        data = json.loads(raw)
        item = (data.get("data") or [])[0]
        image_base64 = item.get("b64_json")
        revised_prompt = item.get("revised_prompt", "")
        if not image_base64:
            return {
                "status": "failed",
                "error_code": "parse_response_error",
                "error_message": "OpenAI 响应中没有 data[0].b64_json",
            }
        image_bytes = base64.b64decode(image_base64)
    except Exception as e:
        return {
            "status": "failed",
            "error_code": "parse_response_error",
            "error_message": f"无法解析 OpenAI 图片响应: {e}"[:300],
        }

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = RAW_DIR / f"{job['job_id']}_{ts}.png"
    try:
        out_path.write_bytes(image_bytes)
    except Exception as e:
        return {
            "status": "failed",
            "error_code": "save_image_failed",
            "error_message": str(e)[:300],
        }

    result = {
        "status": "success",
        "safety_blocked": "false",
        "raw_image_path": str(out_path.relative_to(PROJECT_ROOT)),
    }
    if revised_prompt:
        result["revised_prompt"] = revised_prompt
    return result


def _parse_openai_error(body: str, fallback_code: str) -> tuple[str, str]:
    try:
        data = json.loads(body)
        err = data.get("error") or {}
        code = err.get("code") or err.get("type") or fallback_code or "openai_error"
        msg = err.get("message") or body
        return str(code), str(msg)
    except Exception:
        return fallback_code or "openai_error", body


# ------------------------------------------------------------------
# M02 调用：DashScope wan2.7-image-pro
# ------------------------------------------------------------------

def call_m02(job: dict, model_row: dict) -> dict:
    """返回回填字段字典；不抛异常，所有错误转成 status。"""
    import dashscope
    from dashscope.aigc.image_generation import ImageGeneration
    from dashscope.api_entities.dashscope_response import Message

    api_key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not api_key or api_key.startswith("sk-xxxx"):
        return {
            "status": "failed",
            "error_code": "missing_api_key",
            "error_message": "DASHSCOPE_API_KEY 未设置",
        }

    dashscope.base_http_api_url = "https://dashscope.aliyuncs.com/api/v1"
    dashscope.api_key = api_key

    model_version = model_row["model_version"]
    try:
        default_params = json.loads(model_row.get("default_params") or "{}")
    except json.JSONDecodeError:
        default_params = {}
    size = default_params.get("size", "2K")
    n = int(default_params.get("n", 1))

    seed = random.randint(1, 2**31 - 1)
    prompt_text = job["original_prompt"]
    message = Message(role="user", content=[{"text": prompt_text}])

    start = time.time()
    try:
        submit_resp = ImageGeneration.async_call(
            model=model_version,
            api_key=api_key,
            messages=[message],
            n=n,
            size=size,
            seed=seed,
            watermark=False,
        )
    except Exception as e:
        return {
            "status": "failed",
            "seed": str(seed),
            "error_code": type(e).__name__,
            "error_message": str(e)[:300],
        }

    if submit_resp.status_code != 200:
        code = (getattr(submit_resp, "code", "") or "").strip()
        msg = (getattr(submit_resp, "message", "") or "").strip()
        if _looks_like_safety(code, msg):
            return {
                "status": "safety_blocked",
                "seed": str(seed),
                "safety_blocked": "true",
                "revision_reason": f"{code}: {msg}"[:300],
            }
        return {
            "status": "failed",
            "seed": str(seed),
            "error_code": code or f"HTTP_{submit_resp.status_code}",
            "error_message": msg[:300],
        }

    task_id = submit_resp.output.task_id

    # 轮询，单 job 90 秒硬上限（含 submit）
    while True:
        elapsed = time.time() - start
        if elapsed > TIMEOUT_SEC:
            return {
                "status": "timeout",
                "seed": str(seed),
                "timeout_sec": str(TIMEOUT_SEC),
                "error_code": "polling_timeout",
                "error_message": f"task {task_id} 在 {TIMEOUT_SEC}s 内未完成",
            }

        time.sleep(POLL_INTERVAL_SEC)
        try:
            fetch_resp = ImageGeneration.fetch(task=task_id, api_key=api_key)
        except Exception as e:
            return {
                "status": "failed",
                "seed": str(seed),
                "error_code": type(e).__name__,
                "error_message": f"fetch failed: {e}"[:300],
            }

        if fetch_resp.status_code != 200:
            return {
                "status": "failed",
                "seed": str(seed),
                "error_code": getattr(fetch_resp, "code", "") or f"HTTP_{fetch_resp.status_code}",
                "error_message": (getattr(fetch_resp, "message", "") or "")[:300],
            }

        task_status = fetch_resp.output.task_status
        if task_status in ("PENDING", "RUNNING"):
            continue

        if task_status == "SUCCEEDED":
            try:
                content = fetch_resp.output.choices[0]["message"]["content"]
                image_url = next(c["image"] for c in content if c.get("type") == "image")
            except Exception as e:
                return {
                    "status": "failed",
                    "seed": str(seed),
                    "error_code": "parse_response_error",
                    "error_message": f"无法从响应中提取图片 URL: {e}"[:300],
                }

            RAW_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            out_path = RAW_DIR / f"{job['job_id']}_{ts}.png"
            try:
                urllib.request.urlretrieve(image_url, out_path)
            except Exception as e:
                return {
                    "status": "failed",
                    "seed": str(seed),
                    "error_code": "download_failed",
                    "error_message": str(e)[:300],
                }
            return {
                "status": "success",
                "seed": str(seed),
                "safety_blocked": "false",
                "raw_image_path": str(out_path.relative_to(PROJECT_ROOT)),
            }

        # FAILED / CANCELED / UNKNOWN
        code = (getattr(fetch_resp, "code", "") or "").strip()
        msg = (getattr(fetch_resp, "message", "") or "").strip()
        if _looks_like_safety(code, msg):
            return {
                "status": "safety_blocked",
                "seed": str(seed),
                "safety_blocked": "true",
                "revision_reason": f"{code}: {msg}"[:300],
            }
        return {
            "status": "failed",
            "seed": str(seed),
            "error_code": code or task_status,
            "error_message": msg[:300] or f"task_status={task_status}",
        }


def _looks_like_safety(code: str, msg: str) -> bool:
    blob = f"{code} {msg}".lower()
    return any(hint.lower() in blob for hint in SAFETY_ERROR_HINTS)


# ------------------------------------------------------------------
# 单 job 执行 + 回填
# ------------------------------------------------------------------

def execute_one_job(job: dict, models_by_id: dict[str, dict]) -> dict:
    model_id = job["model_id"]
    model_row = models_by_id.get(model_id)
    if not model_row:
        return {
            "status": "failed",
            "error_code": "unknown_model",
            "error_message": f"model_id={model_id} 不在 models.csv 中",
        }

    if model_id == "M02":
        return call_m02(job, model_row)

    if model_id == "M01":
        return call_m01(job, model_row)

    return {
        "status": "failed",
        "error_code": "unsupported_model",
        "error_message": f"未支持的 model_id={model_id}",
    }


def apply_result(job: dict, started_at: str, result: dict) -> dict:
    """把 result 字段合并回 job dict，标准化所有相关字段。"""
    job = dict(job)
    job["attempts"] = str(int(job.get("attempts") or 0) + 1)
    job["started_at"] = started_at
    job["finished_at"] = now_iso()

    status = result.get("status", "failed")
    job["status"] = status

    # seed 只在结果里给了才回填
    if result.get("seed"):
        job["seed"] = result["seed"]

    # 按 status 写入字段
    if status == "success":
        job["safety_blocked"] = result.get("safety_blocked", "false")
        job["raw_image_path"] = result.get("raw_image_path", "")
        job["revised_prompt"] = result.get("revised_prompt", "")
        job["error_code"] = ""
        job["error_message"] = ""
        job["timeout_sec"] = ""
        job["revision_reason"] = ""
    elif status == "safety_blocked":
        job["safety_blocked"] = "true"
        job["revision_reason"] = result.get("revision_reason", "safety/policy blocked")
        job["raw_image_path"] = ""
        job["error_code"] = ""
        job["error_message"] = ""
        job["timeout_sec"] = ""
    elif status == "timeout":
        job["safety_blocked"] = "false"
        job["timeout_sec"] = result.get("timeout_sec", str(TIMEOUT_SEC))
        job["raw_image_path"] = ""
        job["error_code"] = result.get("error_code", "polling_timeout")
        job["error_message"] = result.get("error_message", "")
        job["revision_reason"] = ""
    else:  # failed
        job["status"] = "failed"
        job["safety_blocked"] = "false"
        job["raw_image_path"] = ""
        job["error_code"] = result.get("error_code", "unknown_error")
        job["error_message"] = result.get("error_message", "")
        job["timeout_sec"] = ""
        job["revision_reason"] = ""

    return job


# ------------------------------------------------------------------
# 日志
# ------------------------------------------------------------------

class JobLogger:
    """同时写日志文件和打印控制台简要进度。"""

    def __init__(self, log_path: Path) -> None:
        self.log_path = log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = log_path.open("a", encoding="utf-8")
        self.write(f"=== generate_images.py started at {now_iso()} ===")

    def write(self, line: str) -> None:
        self._fh.write(line + "\n")
        self._fh.flush()

    def close(self) -> None:
        self.write(f"=== ended at {now_iso()} ===")
        self._fh.close()


# ------------------------------------------------------------------
# 批量执行（带重试 / 续跑 / 中断保护）
# ------------------------------------------------------------------

def is_retryable(result: dict) -> bool:
    if result.get("status") == "success":
        return False
    if result.get("status") == "safety_blocked":
        return False
    code = (result.get("error_code") or "").strip()
    if code in NON_RETRYABLE_ERROR_CODES:
        return False
    return True


def execute_with_retry(job: dict, models_by_id: dict[str, dict],
                       logger: JobLogger) -> tuple[str, dict]:
    """返回 (started_at_of_first_attempt, final_result)。
    重试在同一个 job 内累积 attempts，但 started_at 用首次尝试的时间。"""
    started_at = now_iso()
    last_result: dict | None = None
    for attempt_idx in range(MAX_RETRIES_PER_JOB + 1):
        if attempt_idx > 0:
            wait = RETRY_BACKOFFS_SEC[min(attempt_idx - 1, len(RETRY_BACKOFFS_SEC) - 1)]
            logger.write(f"  retry {attempt_idx}/{MAX_RETRIES_PER_JOB} after {wait}s "
                         f"(prev: {last_result.get('status')}/{last_result.get('error_code', '')})")
            time.sleep(wait)
        result = execute_one_job(job, models_by_id)
        last_result = result
        if result.get("status") == "success":
            return started_at, result
        if not is_retryable(result):
            return started_at, result
    return started_at, last_result  # type: ignore[return-value]


def reset_failed_and_timeout(jobs: list[dict], logger: JobLogger) -> int:
    """把 failed/timeout 的 job 重置为 pending，attempts 归零。
    safety_blocked 不重置（明确拒绝，无意义）；success 不动。
    返回重置条数。"""
    n = 0
    for j in jobs:
        if j["status"] in ("failed", "timeout"):
            logger.write(f"  reset {j['job_id']} (was {j['status']}) → pending")
            j["status"] = "pending"
            j["attempts"] = "0"
            j["seed"] = ""
            j["raw_image_path"] = ""
            j["error_code"] = ""
            j["error_message"] = ""
            j["timeout_sec"] = ""
            j["safety_blocked"] = ""
            j["revised_prompt"] = ""
            j["revision_reason"] = ""
            j["started_at"] = ""
            j["finished_at"] = ""
            n += 1
    return n


def estimate_cost_cny(jobs: list[dict]) -> float:
    total = 0.0
    for j in jobs:
        total += COST_PER_IMAGE_CNY.get(j["model_id"], 0.0)
    return total


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def _non_negative_int(value: str) -> int:
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"必须为整数：{value!r}")
    if n < 0:
        raise argparse.ArgumentTypeError(f"必须 >= 0：{value!r}")
    return n


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="T2I 批量生成。必须显式传 --dry-run 或 --execute。"
                    "当前支持 M01（OpenAI gpt-image-2）和 M02（DashScope wan2.7-image-pro）。"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true",
                      help="只打印将要执行的 job 与预估成本，不调 API、不写文件")
    mode.add_argument("--execute", action="store_true",
                      help="真实调用 API；可单 job (--job-id) 或批量 (--limit/--model-id)")
    parser.add_argument("--job-id", type=str, default=None,
                        help="单个 job_id")
    parser.add_argument("--model-id", type=str, default=None,
                        help="只跑指定 model_id 的 pending job")
    parser.add_argument("--limit", type=_non_negative_int, default=None,
                        help="最多处理多少条 pending job（必须 >= 0）")
    parser.add_argument("--retry-failed", action="store_true",
                        help="批量前重置 failed/timeout 的 job 为 pending 再跑（不影响 safety_blocked）")
    return parser.parse_args()


# ------------------------------------------------------------------
# 单 job 执行流程
# ------------------------------------------------------------------

def run_single_job(jobs: list[dict], idx: int, models_by_id: dict[str, dict],
                   logger: JobLogger) -> dict:
    """执行 jobs[idx] 一个 job（含重试），并持久化整张 CSV。返回更新后的 job 行。"""
    job = jobs[idx]
    t0 = time.time()
    started_at, result = execute_with_retry(job, models_by_id, logger)
    elapsed = time.time() - t0
    new_job = apply_result(job, started_at, result)
    jobs[idx] = new_job
    write_jobs(JOBS_CSV, jobs)
    suffix = ""
    if new_job["status"] == "success":
        suffix = f" → {new_job['raw_image_path']}"
    elif new_job["status"] in ("failed", "timeout"):
        suffix = f" [{new_job['error_code']}] {new_job['error_message'][:80]}"
    elif new_job["status"] == "safety_blocked":
        suffix = f" [{new_job['revision_reason'][:80]}]"
    logger.write(f"  {new_job['job_id']} {new_job['model_id']} "
                 f"attempts={new_job['attempts']} {new_job['status']} {elapsed:.1f}s{suffix}")
    return new_job


def main() -> int:
    args = parse_args()
    load_env(PROJECT_ROOT / ".env")

    all_jobs = read_csv(JOBS_CSV)
    models_by_id = {r["model_id"]: r for r in read_csv(MODELS_CSV)}

    # ---------------- DRY RUN ----------------
    if args.dry_run:
        selected = filter_jobs(all_jobs, args.job_id, args.model_id, args.limit)
        cost = estimate_cost_cny(selected)
        print(f"[DRY-RUN] 共 {len(all_jobs)} 条 job，筛选后将执行 {len(selected)} 条")
        print(f"          filters: job_id={args.job_id!r}, model_id={args.model_id!r}, limit={args.limit!r}")
        print(f"          预估成本: ¥{cost:.2f}  (M02 单价 ¥{COST_PER_IMAGE_CNY['M02']}, M01 单价 ¥{COST_PER_IMAGE_CNY['M01']})")
        print()
        print(render_job_table(selected))
        print()
        print("[DRY-RUN] 未调用任何 API；未修改任何文件。")
        return 0

    # ---------------- EXECUTE ----------------
    log_path = LOGS_DIR / f"generate_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.log"
    logger = JobLogger(log_path)
    print(f"[LOG] {log_path.relative_to(PROJECT_ROOT)}")

    try:
        # 单 job 路径
        if args.job_id:
            if args.retry_failed or args.limit is not None or args.model_id:
                logger.write("WARN: --job-id 模式下忽略 --retry-failed / --limit / --model-id")
                print("WARN: --job-id 模式下忽略 --retry-failed / --limit / --model-id")
            target_idx = next((i for i, j in enumerate(all_jobs) if j["job_id"] == args.job_id), -1)
            if target_idx < 0:
                sys.exit(f"ERROR: job_id={args.job_id} 不存在")
            job = all_jobs[target_idx]
            if job["status"] != "pending":
                sys.exit(f"ERROR: job_id={args.job_id} 当前 status={job['status']}，不是 pending；"
                         "若要重跑，用 --retry-failed（批量）或先手动重置")
            print(f"[EXECUTE] {args.job_id} {job['prompt_id']} {job['model_id']} "
                  f"rep={job['replicate_idx']}  timeout={TIMEOUT_SEC}s")
            print(f"          {job['original_prompt'][:80]}")
            logger.write(f"single-job {args.job_id} {job['prompt_id']} {job['model_id']}")
            new_job = run_single_job(all_jobs, target_idx, models_by_id, logger)
            print(f"[RESULT]  status={new_job['status']}  attempts={new_job['attempts']}")
            if new_job["status"] == "success":
                print(f"          raw_image_path={new_job['raw_image_path']}")
            elif new_job["status"] == "safety_blocked":
                print(f"          revision_reason={new_job['revision_reason']}")
            elif new_job["status"] == "timeout":
                print(f"          timeout_sec={new_job['timeout_sec']}  msg={new_job['error_message']}")
            else:
                print(f"          error_code={new_job['error_code']}  msg={new_job['error_message']}")
            return 0 if new_job["status"] == "success" else 1

        # 批量路径
        if args.retry_failed:
            n_reset = reset_failed_and_timeout(all_jobs, logger)
            if n_reset > 0:
                write_jobs(JOBS_CSV, all_jobs)
            print(f"[RETRY-FAILED] 重置 {n_reset} 条 failed/timeout → pending")

        selected = filter_jobs(all_jobs, None, args.model_id, args.limit)
        if not selected:
            print("[EXECUTE] 无待执行 pending job，退出")
            return 0

        cost = estimate_cost_cny(selected)
        print(f"[EXECUTE] 将顺序执行 {len(selected)} 条 pending job，预估成本 ¥{cost:.2f}")
        print(f"          filters: model_id={args.model_id!r}, limit={args.limit!r}")
        logger.write(f"batch start: {len(selected)} jobs, est ¥{cost:.2f}, "
                     f"model_id={args.model_id}, limit={args.limit}")

        ok = fail = blocked = timeout_n = 0
        interrupted = False
        for i, job in enumerate(selected, 1):
            idx = next((k for k, j in enumerate(all_jobs) if j["job_id"] == job["job_id"]), -1)
            if idx < 0:
                continue
            print(f"  [{i}/{len(selected)}] {job['job_id']} {job['model_id']} {job['prompt_id']} rep={job['replicate_idx']}")
            try:
                new_job = run_single_job(all_jobs, idx, models_by_id, logger)
            except KeyboardInterrupt:
                logger.write(f"INTERRUPTED after {job['job_id']}")
                print("\n[INTERRUPTED] 当前 job 已完成并落盘；剩余 job 中止。")
                interrupted = True
                break
            status = new_job["status"]
            if status == "success":
                ok += 1
            elif status == "safety_blocked":
                blocked += 1
            elif status == "timeout":
                timeout_n += 1
            else:
                fail += 1
            if i < len(selected):
                time.sleep(INTER_JOB_SLEEP_SEC)

        print()
        print(f"[DONE]    success={ok}  failed={fail}  timeout={timeout_n}  safety_blocked={blocked}"
              + ("  (interrupted)" if interrupted else ""))
        logger.write(f"batch done: ok={ok} fail={fail} timeout={timeout_n} blocked={blocked} "
                     f"interrupted={interrupted}")
        return 0 if (fail == 0 and timeout_n == 0 and not interrupted) else 1

    finally:
        logger.close()


if __name__ == "__main__":
    raise SystemExit(main())
