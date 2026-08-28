#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""契约优先 consumer：把引擎的 summary（+可选 due）渲染成自包含 HTML 复盘周报。

纯渲染，不做统计、不调模型；只消费 summary 的规范字段，缺失字段在页面内兜底为“暂无数据”。

用法：
    python3 crm.py --mode summary --period weekly --json | python3 gen_review_report.py --out /tmp/review.html
    python3 gen_review_report.py --summary summary.json --due due.json --out /tmp/review.html --title 体验中心店
"""
import argparse
import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = SKILL_DIR / "assets" / "review-template.html"


def read_json_arg(path_or_none, allow_stdin=False):
    if path_or_none is None:
        if allow_stdin and not sys.stdin.isatty():
            raw = sys.stdin.read()
            return json.loads(raw) if raw.strip() else None
        return None
    p = Path(path_or_none)
    if not p.exists():
        print(f"错误: 找不到文件 {path_or_none}", file=sys.stderr)
        sys.exit(2)
    return json.loads(p.read_text(encoding="utf-8"))


def main(argv=None):
    parser = argparse.ArgumentParser(description="渲染自包含 HTML 复盘周报")
    parser.add_argument("--summary", help="summary JSON 文件；缺省时读 stdin")
    parser.add_argument("--due", help="可选：crm.py due --json 的输出文件（丰富风险清单）")
    parser.add_argument("--title", help="副标题（如门店名）")
    parser.add_argument("--out", required=True, help="输出 HTML 路径")
    args = parser.parse_args(argv)

    summary = read_json_arg(args.summary, allow_stdin=True)
    if summary is None:
        print("错误: 没有可用的 summary 输入（--summary 或 stdin）", file=sys.stderr)
        return 2
    # 允许直接传 summary，也允许 {"summary":..,"due":..} 包裹
    due = None
    if isinstance(summary, dict) and "summary" in summary and isinstance(summary["summary"], dict):
        due = summary.get("due")
        summary = summary["summary"]
    if args.due:
        d = read_json_arg(args.due)
        due = d if d is not None else due

    if not TEMPLATE_PATH.exists():
        print(f"错误: 缺少模板 {TEMPLATE_PATH}", file=sys.stderr)
        return 2
    template = TEMPLATE_PATH.read_text(encoding="utf-8")

    payload = {"summary": summary, "due": due}
    if args.title:
        payload["generated_for"] = args.title
    encoded = json.dumps(payload, ensure_ascii=False, default=str).replace("</", "<\\/")
    if "__REPORT_DATA__" not in template:
        print("错误: 模板缺少占位符 __REPORT_DATA__", file=sys.stderr)
        return 2
    html = template.replace("__REPORT_DATA__", encoded)

    out_path = Path(args.out).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"✅ 复盘周报已生成：{out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
