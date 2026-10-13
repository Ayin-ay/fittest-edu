"""Submit a The Fittest export to an OpenAI-compatible chat API (default DeepSeek).

Primary analysis path is the opencode skill `trust-evolution-analysis`; this
script is an OPTIONAL automation for batch / API-driven analysis.

Requires an API key. Two ways to provide it:
  - environment variable DEEPSEEK_API_KEY (or OPENAI_API_KEY / a custom name)
  - --api-key SECRET
The key is never written to files.

Examples:
  .\\.venv\\Scripts\\python.exe tools\\submit_analysis.py results\\trust_evolution\\seed_42.json --output analysis_seed_42.md
  .\\.venv\\Scripts\\python.exe tools\\submit_analysis.py seed_42.json --dry-run
  .\\.venv\\Scripts\\python.exe tools\\submit_analysis.py seed_42.json --base-url https://api.openai.com/v1 --model gpt-4o-mini
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import requests

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_KEY_ENV = "DEEPSEEK_API_KEY"

SYSTEM_PROMPT = (
    "你是一位演化博弈与复杂系统分析专家。请基于用户提供的 The Fittest "
    "（迭代囚徒困境 + 物种/亚种演化）模拟数据，产出结构化的中文分析报告。"
)

USER_PROMPT_TEMPLATE = """请基于以下模拟数据完成分析：
1. 概括整体演化趋势（种群规模、适应度、多样性 Shannon/Simpson 的变化与阶段）；
2. 找出关键转折点，并结合事件（◇ 亚种生成、★ 亚种独立、× 物种灭绝、✕ 亚种淘汰）解释成因；
3. 分析优势策略/策略家族及其对战机制（可参考对局矩阵），并与 Axelrod 经典结论
   （“以牙还牙”的善意、报复、宽容）对照异同；
4. 评估“善意、报复、宽容”在本生态系统中的实际作用；
5. 指出局限、数据异常与可进一步验证的假设。
请引用具体代数与策略编码作为证据，避免空泛结论。

模拟数据（JSON）：
{data}"""


def load_data(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def build_user_content(data: dict, full: bool) -> str:
    payload = dict(data)
    if not full:
        # Compact mode drops the largest sections; population_matrix stays.
        payload.pop("matchup_matrices", None)
        payload.pop("fitness_matrix", None)
    return USER_PROMPT_TEMPLATE.format(data=json.dumps(payload, ensure_ascii=False))


def send(
    data: dict,
    *,
    model: str,
    base_url: str,
    api_key: str,
    full: bool,
    dry_run: bool,
    timeout: int = 300,
) -> str | None:
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_content(data, full=full)},
        ],
        "temperature": 0.4,
    }
    if dry_run:
        preview = {
            "url": url,
            "headers": {**headers, "Authorization": "Bearer ***"},
            "model": model,
            "user_message_chars": len(body["messages"][1]["content"]),
        }
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return None
    response = requests.post(url, headers=headers, json=body, timeout=timeout)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Submit a The Fittest export to an OpenAI-compatible API "
            "(default DeepSeek) for analysis."
        )
    )
    parser.add_argument("input", help="导出文件路径：完整导出 JSON 或旧版报告 JSON")
    parser.add_argument("--output", help="保存分析结果的文件路径（默认打印到终端）")
    parser.add_argument("--model", default=os.getenv("ANALYSIS_MODEL", DEFAULT_MODEL))
    parser.add_argument("--base-url", default=os.getenv("ANALYSIS_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--api-key", dest="api_key", default=None, help=f"显式密钥（默认读 {DEFAULT_KEY_ENV} 或 OPENAI_API_KEY）")
    parser.add_argument("--summary", action="store_true", help="只发送摘要（去掉对局矩阵与适应度矩阵）")
    parser.add_argument("--dry-run", action="store_true", help="只打印将发送的请求，不调用 API")
    args = parser.parse_args()

    if not Path(args.input).is_file():
        print(f"error: 找不到文件 {args.input}", file=sys.stderr)
        sys.exit(1)
    data = load_data(args.input)

    api_key = args.api_key or os.getenv(DEFAULT_KEY_ENV) or os.getenv("OPENAI_API_KEY")
    if not api_key and not args.dry_run:
        print(
            f"error: 需要 API 密钥。请设置环境变量 {DEFAULT_KEY_ENV}（或 OPENAI_API_KEY 等），"
            "或用 --api-key。",
            file=sys.stderr,
        )
        sys.exit(1)
    api_key = api_key or "UNSET"

    result = send(
        data,
        model=args.model,
        base_url=args.base_url,
        api_key=api_key,
        full=not args.summary,
        dry_run=args.dry_run,
    )
    if args.dry_run:
        print("（dry-run 完成，未发送请求）")
        return
    if not result:
        print("error: 接口未返回内容", file=sys.stderr)
        sys.exit(1)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(result, encoding="utf-8")
        print(f"已保存分析结果到 {args.output}")
    else:
        print(result)


if __name__ == "__main__":
    main()