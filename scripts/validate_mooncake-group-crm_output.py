#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校验一条抽取记录是否符合 references/output-schema.json（draft-07 子集 + 跨字段规则）。

纯标准库，不依赖 jsonschema。
退出码：0=通过；1=校验失败（打印具体错误路径）；2=用法/读文件错误。

用法：
    python3 validate_mooncake-group-crm_output.py <record.json>
    cat record.json | python3 validate_mooncake-group-crm_output.py -
"""
import json
import re
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SCHEMA_PATH = SKILL_DIR / "references" / "output-schema.json"

_TYPE_CHECKS = {
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "null": lambda v: v is None,
}


def _validate_node(value, schema, path, errors):
    """递归校验 value 对 schema（draft-07 子集）。错误累积到 errors。"""
    stype = schema.get("type")
    if stype:
        types = stype if isinstance(stype, list) else [stype]
        if not any(_TYPE_CHECKS[t](value) for t in types if t in _TYPE_CHECKS):
            errors.append(f"{path}: 类型应为 {'/'.join(types)}，实际为 {type(value).__name__}（值={value!r}）")
            return  # 类型不符，不再深入

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: 值 {value!r} 不在枚举 {schema['enum']} 内")

    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: 长度 {len(value)} < minLength {schema['minLength']}")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append(f"{path}: 长度 {len(value)} > maxLength {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: 值 {value!r} 不匹配 pattern {schema['pattern']!r}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: 值 {value} < minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: 值 {value} > maximum {schema['maximum']}")

    if isinstance(value, dict):
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in value:
                errors.append(f"{path}.{req}: 缺少必填字段")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in props:
                    errors.append(f"{path}.{key}: 出现未定义字段（additionalProperties=false）")
        for key, sub in props.items():
            if key in value:
                _validate_node(value[key], sub, f"{path}.{key}", errors)

    if isinstance(value, list):
        items = schema.get("items")
        if isinstance(items, dict):
            for i, item in enumerate(value):
                _validate_node(item, items, f"{path}[{i}]", errors)


def _cross_field(record, errors):
    """draft-07 不便表达的跨字段条件。"""
    intent = record.get("intent")
    customer = record.get("customer") or {}
    opportunity = record.get("opportunity") or {}
    follow_up = record.get("follow_up") or {}
    deal = record.get("deal") or {}
    match = record.get("match") or {}

    if intent == "add_customer":
        if not customer.get("name"):
            errors.append("customer.name: add_customer 必须提供客户名称")
        if not customer.get("contact_phone"):
            errors.append("customer.contact_phone: add_customer 必须提供联系电话/微信（至少一种），缺失应先追问")
        if not record.get("source"):
            errors.append("source: add_customer 必须提供线索来源（新获客/老客转介绍/老客续费），缺失应先追问")
        if not opportunity.get("customer_address"):
            errors.append("opportunity.customer_address: add_customer 必须提供公司地址（联系人所在地址，非配送地址），缺失应先追问")
        if not opportunity.get("demand_category"):
            errors.append("opportunity.demand_category: add_customer 必须提供需求类别（散装/68礼盒/98礼盒/138礼盒/定制礼盒/待定），缺失应先追问")
        if not opportunity:
            errors.append("opportunity: add_customer 必须提供商机信息")
        elif not opportunity.get("intent_level"):
            errors.append("opportunity.intent_level: add_customer 必须明确意向等级 A/B/C/D（缺失时应先追问，不要猜）")

    if intent in ("update_opportunity", "log_followup", "close_deal", "set_next"):
        if not any(match.get(k) for k in ("opp_id", "cust_id", "customer_name", "contact_phone")):
            errors.append("match: %s 必须提供定位目标（opp_id/cust_id/customer_name/contact_phone 至少一项）" % intent)

    if intent == "log_followup":
        if not follow_up.get("content"):
            errors.append("follow_up.content: log_followup 必须提供本次跟进内容")

    if intent == "set_next":
        if not opportunity.get("next_follow_date"):
            errors.append("opportunity.next_follow_date: set_next 必须提供下次跟进日期")

    if intent == "close_deal":
        if not deal:
            errors.append("deal: close_deal 必须提供成交/流失信息")
        stage = opportunity.get("stage")
        if stage is not None and stage not in ("已签约", "已回款", "已流失"):
            errors.append("opportunity.stage: close_deal 的阶段应为 已签约/已回款/已流失，实际 %r" % stage)
        if stage == "已流失" and not deal.get("lost_reason"):
            errors.append("deal.lost_reason: 阶段=已流失 时应提供流失原因（缺失则先追问）")


def validate_record(record, schema):
    errors = []
    _validate_node(record, schema, "$", errors)
    if not errors:  # 结构通过后再跑跨字段，避免噪声
        _cross_field(record, errors)
    return errors


def main(argv):
    if len(argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    src = argv[1]
    try:
        if src == "-":
            raw = sys.stdin.read()
        else:
            raw = Path(src).read_text(encoding="utf-8")
        record = json.loads(raw)
    except FileNotFoundError:
        print(f"错误: 找不到文件 {src}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"错误: JSON 解析失败 — {e}", file=sys.stderr)
        return 2

    try:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"错误: 缺少契约文件 {SCHEMA_PATH}", file=sys.stderr)
        return 2

    errors = validate_record(record, schema)
    if errors:
        print(f"❌ 校验失败：{len(errors)} 处问题")
        for e in errors:
            print(f"  - {e}")
        return 1
    print("✅ 校验通过")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
