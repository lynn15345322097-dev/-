"""test_dashscope_key.py — 验证 DashScope API Key 是否合法

发一次最便宜的 qwen-turbo 文本调用（"你好"），用来确认：
  1. .env 里的 DASHSCOPE_API_KEY 能被读到
  2. key 在服务端是有效的
  3. 网络可达

成本约 ¥0.001，不调任何图像 API，不写任何文件。

用法：
    python scripts/test_dashscope_key.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def load_env(env_path: Path) -> None:
    if not env_path.exists():
        sys.exit(f"ERROR: 找不到 {env_path}")
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())


def main() -> int:
    project_root = Path(__file__).resolve().parent.parent
    load_env(project_root / ".env")

    key = os.environ.get("DASHSCOPE_API_KEY", "")
    if not key or key.startswith("sk-xxxx"):
        sys.exit("ERROR: DASHSCOPE_API_KEY 未设置或仍为占位值")

    print(f"DASHSCOPE_API_KEY: 长度={len(key)}, 前缀={key[:6]}***")
    print("发送测试请求：qwen-turbo / messages=[{'role':'user','content':'你好'}]")
    print()

    import dashscope
    from dashscope import Generation

    dashscope.api_key = key

    try:
        resp = Generation.call(
            model="qwen-turbo",
            messages=[{"role": "user", "content": "你好"}],
            result_format="message",
        )
    except Exception as e:
        sys.exit(f"ERROR: 请求异常：{type(e).__name__}: {e}")

    print(f"HTTP status: {resp.status_code}")
    print(f"request_id : {getattr(resp, 'request_id', '?')}")

    if resp.status_code != 200:
        print(f"code       : {getattr(resp, 'code', '?')}")
        print(f"message    : {getattr(resp, 'message', '?')}")
        sys.exit(1)

    try:
        content = resp.output.choices[0].message.content
    except Exception:
        content = str(resp.output)
    usage = getattr(resp, "usage", None)

    print(f"reply      : {content[:80]}")
    print(f"usage      : {usage}")
    print()
    print("OK: DASHSCOPE_API_KEY 验证通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
