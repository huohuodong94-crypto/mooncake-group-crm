#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""手机端适配页生成器（TC-099）：确认卡 + 门店报表，自包含HTML，375px移动优先。
确定性拼装：数据JSON → 锁定模板替换 __MOBILE_DATA__。"""
import argparse, json, sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = SKILL_DIR / "assets" / "mobile-template.html"


def main(argv=None):
    p = argparse.ArgumentParser(description="手机端确认卡+报表页生成")
    p.add_argument("--data", required=True, help="payload JSON（含 confirm_card 与/或 report）")
    p.add_argument("--out", required=True)
    a = p.parse_args(argv)
    payload = json.loads(Path(a.data).read_text(encoding="utf-8"))
    template = TEMPLATE_PATH.read_text(encoding="utf-8")
    encoded = json.dumps(payload, ensure_ascii=False, default=str).replace("</", "<\\/")
    assert "__MOBILE_DATA__" in template, "模板缺少占位符"
    html = template.replace("__MOBILE_DATA__", encoded)
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"✅ 手机端页面已生成：{out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
