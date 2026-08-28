#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""契约优先 producer 垫片：把店长原话 + 抽取契约打包成一份抽取载荷。

本脚本是确定性的，不调用任何模型。“抽取”由 Agent 按载荷里的 `_output_schema`
产出 JSON，再交给 validate_mooncake-group-crm_output.py 校验。

`_output_schema` 含三要素（契约优先规范）：
  1. schema         —— 完整字段定义（读自 references/output-schema.json）
  2. example        —— 一个正确示例
  3. forbidden_fields —— ❌ 禁止别名清单

用法：
    python3 prepare_extraction.py --text "今天拜访八方金服王总……" --today 2026-07-31 [--store 体验中心店] [--owner 张店长]
    python3 prepare_extraction.py --textfile note.txt --today 2026-07-31
"""
import argparse
import json
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SCHEMA_PATH = SKILL_DIR / "references" / "output-schema.json"
RULES_PATH = SKILL_DIR / "references" / "crm-rules.json"

# 正确示例（须与 references/output-schema.md 的示例保持一致）
EXAMPLE = {
    "intent": "add_customer",
    "recorded_at": "2026-08-10",
    "store": "国金店",
    "owner": "张店长",
    "source": "新获客",
    "customer": {
        "name": "深圳八方科技有限公司",
        "contact": "王经理",
        "contact_phone": "13800000000",
        "customer_type": "企业客户",
    },
    "opportunity": {
        "customer_need": "员工中秋福利，预算约150元/份",
        "demand_category": "68礼盒",
        "quantity": 300,
        "intent_level": "A",
        "expected_amount": 45000,
        "stage": "初次接触",
        "next_follow_date": "2026-08-05",
    },
    "follow_up": {"content": "已发送报价方案，客户内部确认中"},
}

# ❌ 禁止别名清单（须与 references/output-schema.md 保持一致）
FORBIDDEN_FIELDS = [
    "nickname", "customer_name(顶层)", "company", "phone_number", "mobile", "tel",
    "wechat_id", "level", "grade", "state", "status", "step", "amount", "price",
    "money", "budget(顶层)", "need", "demand", "requirement", "next_date",
    "follow_date", "remind_at", "remark", "memo",
]

INSTRUCTIONS = (
    "你是门店团购客户与商机台账的抽取守门人。请把 raw_text 抽取为符合 _output_schema.schema 的单个 JSON 对象。"
    "纪律：① 只使用规范字段名，禁止使用 forbidden_fields 里的任何别名；② 意向等级只能是 A/B/C/D；"
    "当前阶段只能是 V1.2 七态（初次接触/需求确认/方案报价/谈判中/已签约/已回款/已流失），线性流转不可跳级；"
    "需求品类 demand_category 只能是（散装/68礼盒/98礼盒/138礼盒/定制礼盒/待定）；"
    "线索来源 source 只能是 3 值（新获客/老客转介绍/老客续费）；"
    "③ 必填字段缺失或含糊时，不要猜测——输出一条 intent 不变、但在 _missing 字段里列出需向店长追问项的对象，"
    "由上层追问补齐后再重抽；④ 一个对象只表达一个 intent；⑤ 日期一律 YYYY-MM-DD，相对日期（如“下周一”）"
    "按 today 推算成绝对日期。"
    "字段来源（见 field_provenance）：只从话语抽取 voice 字段；opp_id/cust_id/编号 等 system 字段绝不放入记录"
    "（由引擎生成）；store/owner 默认取上下文（system 带出），话语明确提及时可用，否则不要猜；"
    "short_name/customer_type/industry/customer_level/title/tags 等 hq 字段门店首次不录，话语没说到就留空。"
    "确认控制（见 confirm_required）：金额、数量、电话、日期四类字段抽取后须店长显式确认才写入，预览时逐一回读。"
    "推荐语音模板（参考）："
)


def build_payload(raw_text, today, store=None, owner=None):
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    rules = json.loads(RULES_PATH.read_text(encoding="utf-8"))
    voice_template = rules.get("voice_template", "")
    payload = {
        "task": "extract_crm_record",
        "raw_text": raw_text,
        "today": today,
        "instructions": INSTRUCTIONS + voice_template,
        "_output_schema": {
            "schema": schema,
            "example": EXAMPLE,
            "forbidden_fields": FORBIDDEN_FIELDS,
        },
        "field_provenance": rules.get("field_provenance", {}),
        "confirm_required": rules.get("confirm_required", {}),
        "voice_template": voice_template,
    }
    if store:
        payload["store"] = store
    if owner:
        payload["owner"] = owner
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description="打包抽取载荷（契约优先 producer 垫片）")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--text", help="店长原话")
    src.add_argument("--textfile", help="原话所在文件")
    parser.add_argument("--today", required=True, help="今天日期 YYYY-MM-DD（相对日期据此推算）")
    parser.add_argument("--store", help="所属门店（可选，作为默认上下文）")
    parser.add_argument("--owner", help="跟进人（可选）")
    args = parser.parse_args(argv)

    if args.text is not None:
        raw_text = args.text
    else:
        p = Path(args.textfile)
        if not p.exists():
            print(f"错误: 找不到文件 {args.textfile}", file=sys.stderr)
            return 2
        raw_text = p.read_text(encoding="utf-8")

    if not raw_text.strip():
        print("错误: 原话为空", file=sys.stderr)
        return 2
    if not SCHEMA_PATH.exists():
        print(f"错误: 缺少契约文件 {SCHEMA_PATH}", file=sys.stderr)
        return 2

    payload = build_payload(raw_text.strip(), args.today, args.store, args.owner)
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
