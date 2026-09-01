#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""飞书多维表格双表同步脚本。

将本地台账增量同步到固定飞书多维表格 Base：
- 门店客户商机表：按「商机编号」upsert
- 总部客户档案表：按「客户编号」upsert

依赖 lark-cli（需已登录且对目标 Base 有编辑权限）。
默认 dry-run 只预览不写入；加 --yes 实际写入。

用法：
  python3 scripts/sync_feishu_bitable.py                  # 预览
  python3 scripts/sync_feishu_bitable.py --yes            # 实际写入
  python3 scripts/sync_feishu_bitable.py --json           # JSON 输出
  python3 scripts/sync_feishu_bitable.py --base-token XXX # 指定 Base
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import crm  # noqa: E402

DEFAULT_BASE_TOKEN = "VTdNbS9iJaeqZxsqFS3ccGv8n2f"
DEFAULT_BATCH_SIZE = 50
MAX_BATCH = 200  # 飞书 API 单批上限


# ---------------------------------------------------------------------------
# lark-cli 封装
# ---------------------------------------------------------------------------

def run_lark(args, check=True):
    """运行 lark-cli 命令，返回解析后的 JSON dict。

    失败时：check=True 抛 RuntimeError；check=False 返回含 ok=False 的 dict。
    """
    cmd = ["lark-cli"] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except FileNotFoundError:
        err = {"type": "cli_not_found", "message": "lark-cli 不在 PATH 中，请先安装并登录"}
        if check:
            raise RuntimeError(json.dumps(err, ensure_ascii=False))
        return {"ok": False, "error": err}
    except subprocess.TimeoutExpired:
        err = {"type": "timeout", "message": "lark-cli 执行超时（120s）"}
        if check:
            raise RuntimeError(json.dumps(err, ensure_ascii=False))
        return {"ok": False, "error": err}

    stdout = (result.stdout or "").strip()
    stderr = (result.stderr or "").strip()

    # 尝试解析 stdout 为 JSON
    parsed = None
    if stdout:
        try:
            parsed = json.loads(stdout)
        except json.JSONDecodeError:
            parsed = None

    if result.returncode != 0:
        err = parsed or {"raw_stdout": stdout, "raw_stderr": stderr}
        if check:
            raise RuntimeError(
                f"lark-cli 失败 (exit {result.returncode}): {' '.join(cmd)}\n"
                f"{json.dumps(err, ensure_ascii=False, indent=2)}"
            )
        return {"ok": False, "error": err, "returncode": result.returncode}

    if parsed is not None:
        # 统一：如果有 ok 字段就保留，否则设 ok=True
        if "ok" not in parsed:
            parsed["ok"] = True
        return parsed
    return {"ok": True, "raw": stdout}


def _extract_items(result):
    """从 lark-cli 返回中提取 items 列表，兼容多种包裹结构。"""
    if not isinstance(result, dict):
        return []
    if "items" in result and isinstance(result["items"], list):
        return result["items"]
    data = result.get("data")
    if isinstance(data, dict):
        if "items" in data:
            return data["items"]
        if "tables" in data and isinstance(data["tables"], list):
            return data["tables"]
        if "records" in data and isinstance(data["records"], list):
            return data["records"]
        if "fields" in data and isinstance(data["fields"], list):
            return data["fields"]
    if isinstance(data, list):
        return data
    # record-list 可能返回 records
    if "records" in result and isinstance(result["records"], list):
        return result["records"]
    return []


def _extract_text(value):
    """飞书文本字段可能返回字符串或 [{"text":"..."}] 列表，统一取字符串。"""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = []
        for seg in value:
            if isinstance(seg, dict):
                parts.append(seg.get("text", ""))
            elif isinstance(seg, str):
                parts.append(seg)
        return "".join(parts)
    return str(value)


# ---------------------------------------------------------------------------
# 飞书 Base 只读操作
# ---------------------------------------------------------------------------

def list_tables(base_token):
    """列出 Base 中所有数据表，返回 {表名: table_id}。"""
    result = run_lark([
        "base", "+table-list",
        "--base-token", base_token,
        "--format", "json",
        "--limit", "100",
    ])
    tables = {}
    for item in _extract_items(result):
        name = item.get("name") or item.get("table_name")
        tid = item.get("table_id") or item.get("id")
        if name and tid:
            tables[name] = tid
    return tables


def list_fields(base_token, table_id):
    """列出表中所有字段，返回 {字段名: {field_id, type, ui_type, raw}}。"""
    result = run_lark([
        "base", "+field-list",
        "--base-token", base_token,
        "--table-id", table_id,
        "--format", "json",
        "--limit", "200",
    ])
    fields = {}
    for item in _extract_items(result):
        name = item.get("field_name") or item.get("name")
        fid = item.get("field_id") or item.get("id")
        ftype = item.get("type")
        ui_type = item.get("ui_type") or item.get("property", {}).get("formatter")
        if name:
            fields[name] = {"field_id": fid, "type": ftype, "ui_type": ui_type, "raw": item}
    return fields


def list_all_primary_keys(base_token, table_id, primary_key_field):
    """分页拉取表中所有记录的主键值和 record_id，返回 {主键值: record_id}。

    lark-cli +record-list 返回格式：
    {"data": {"data": [[val1], [val2], ...], "record_id_list": ["recXXX", ...]}}
    """
    mapping = {}
    offset = 0
    page_size = 200
    while True:
        result = run_lark([
            "base", "+record-list",
            "--base-token", base_token,
            "--table-id", table_id,
            "--field-id", primary_key_field,
            "--format", "json",
            "--limit", str(page_size),
            "--offset", str(offset),
        ])
        data = result.get("data", {})
        if isinstance(data, dict):
            record_ids = data.get("record_id_list", [])
            rows = data.get("data", [])
        else:
            record_ids = []
            rows = []
        if not record_ids:
            break
        for i, rid in enumerate(record_ids):
            pk_val = None
            if i < len(rows) and isinstance(rows[i], list) and len(rows[i]) > 0:
                pk_val = _extract_text(rows[i][0])
            if pk_val and rid:
                mapping[str(pk_val).strip()] = rid
        if not data.get("has_more", False):
            break
        offset += page_size
    return mapping


# ---------------------------------------------------------------------------
# 字段值转换
# ---------------------------------------------------------------------------

# 飞书字段类型字符串常量（lark-cli 返回的 field.type 为字符串）
FIELD_TYPE_TEXT = "text"
FIELD_TYPE_NUMBER = "number"
FIELD_TYPE_SELECT = "single_select"
FIELD_TYPE_MULTI_SELECT = "multi_select"
FIELD_TYPE_DATETIME = "datetime"
FIELD_TYPE_CHECKBOX = "checkbox"
FIELD_TYPE_PHONE = "phone"
FIELD_TYPE_URL = "url"
FIELD_TYPE_ATTACHMENT = "attachment"
FIELD_TYPE_LINK = "link"
FIELD_TYPE_FORMULA = "formula"
FIELD_TYPE_DUPLEX_LINK = "duplex_link"
FIELD_TYPE_LOCATION = "location"
FIELD_TYPE_GROUP = "group"
FIELD_TYPE_CREATED_TIME = "created_time"
FIELD_TYPE_MODIFIED_TIME = "last_modified_time"
FIELD_TYPE_CREATED_USER = "created_user"
FIELD_TYPE_MODIFIED_USER = "modified_user"
FIELD_TYPE_AUTO_NUMBER = "auto_number"

# 不可写入的系统/计算字段
READONLY_TYPES = {
    FIELD_TYPE_FORMULA, FIELD_TYPE_DUPLEX_LINK,
    FIELD_TYPE_CREATED_TIME, FIELD_TYPE_MODIFIED_TIME,
    FIELD_TYPE_CREATED_USER, FIELD_TYPE_MODIFIED_USER,
    FIELD_TYPE_AUTO_NUMBER,
}


def _is_number_field(field_info):
    """判断是否数字类字段。"""
    t = field_info.get("type")
    if t in (FIELD_TYPE_NUMBER,):
        return True
    # ui_type 兜底
    ui = str(field_info.get("ui_type") or "").lower()
    return ui in ("number", "currency", "percent", "rating")


def _is_datetime_field(field_info):
    t = field_info.get("type")
    if t == FIELD_TYPE_DATETIME:
        return True
    ui = str(field_info.get("ui_type") or "").lower()
    return ui in ("datetime", "date", "time")


def _is_select_field(field_info):
    return field_info.get("type") == FIELD_TYPE_SELECT


def _is_multi_select_field(field_info):
    return field_info.get("type") == FIELD_TYPE_MULTI_SELECT


def _is_readonly(field_info):
    return field_info.get("type") in READONLY_TYPES


def convert_field_value(value, field_info):
    """将本地值转换为飞书 CellValue。返回 None 表示跳过该字段。"""
    if value is None or value == "":
        return None
    if field_info is None:
        return str(value)
    if _is_readonly(field_info):
        return None

    # 数字
    if _is_number_field(field_info):
        try:
            return float(value)
        except (ValueError, TypeError):
            return str(value)

    # 日期
    if _is_datetime_field(field_info):
        s = str(value).strip()
        # 已经是 YYYY-MM-DD 或 YYYY-MM-DD HH:mm:ss
        if len(s) == 10:
            return s  # 飞书日期字段接受日期字符串
        return s

    # 单选
    if _is_select_field(field_info):
        return str(value)

    # 多选
    if _is_multi_select_field(field_info):
        if isinstance(value, list):
            return [str(v) for v in value]
        return [str(value)]

    # 默认文本
    return str(value)


# ---------------------------------------------------------------------------
# 单表同步
# ---------------------------------------------------------------------------

def sync_table(base_token, table_id, table_data, dry_run=True, batch_size=50):
    """同步一张表，返回统计 dict。"""
    table_name = table_data.get("table_name", "")
    primary_key = table_data["primary_key"]
    columns = table_data["columns"]
    records = table_data["records"]
    batch_size = min(batch_size, MAX_BATCH)

    stats = {
        "table": table_name,
        "table_id": table_id,
        "primary_key": primary_key,
        "total_local": len(records),
        "to_create": 0,
        "to_update": 0,
        "created": 0,
        "updated": 0,
        "failed": 0,
        "skipped": 0,
        "existing_remote": 0,
        "missing_fields": [],
        "errors": [],
    }

    # 1. 读取远程字段
    try:
        remote_fields = list_fields(base_token, table_id)
    except RuntimeError as e:
        stats["errors"].append(f"读取字段列表失败: {e}")
        stats["failed"] = len(records)
        return stats

    stats["remote_field_count"] = len(remote_fields)

    # 检查本地字段是否都在远程存在
    missing = [col for col in columns if col not in remote_fields]
    if missing:
        stats["missing_fields"] = missing
        stats["errors"].append(
            f"飞书表「{table_name}」中缺少以下字段（需先在飞书侧创建）: {missing}"
        )
        stats["failed"] = len(records)
        return stats

    # 2. 拉取远程已有记录的主键映射
    try:
        existing = list_all_primary_keys(base_token, table_id, primary_key)
    except RuntimeError as e:
        stats["errors"].append(f"拉取远程记录失败: {e}")
        stats["failed"] = len(records)
        return stats

    stats["existing_remote"] = len(existing)

    # 3. 分类：新增 / 更新
    to_create = []   # list of field_map
    to_update = {}   # record_id -> field_map

    for rec in records:
        key = str(rec["key"]).strip()
        field_map = {}
        for col in columns:
            val = rec["fields"].get(col)
            converted = convert_field_value(val, remote_fields.get(col))
            if converted is not None:
                field_map[col] = converted

        if not field_map:
            stats["skipped"] += 1
            continue

        if key in existing:
            to_update[existing[key]] = field_map
        else:
            to_create.append(field_map)

    stats["to_create"] = len(to_create)
    stats["to_update"] = len(to_update)

    if dry_run:
        return stats

    # 4. 批量新增
    for i in range(0, len(to_create), batch_size):
        batch = to_create[i:i + batch_size]
        payload = {"create_records": batch}
        result = run_lark([
            "base", "+record-batch-create",
            "--base-token", base_token,
            "--table-id", table_id,
            "--json", json.dumps(payload, ensure_ascii=False),
            "--format", "json",
        ], check=False)
        if result.get("ok") is False:
            err_msg = json.dumps(result.get("error", {}), ensure_ascii=False)
            stats["errors"].append(f"批量新增失败 (第 {i // batch_size + 1} 批): {err_msg}")
            stats["failed"] += len(batch)
        else:
            created_items = _extract_items(result)
            stats["created"] += len(created_items) if created_items else len(batch)

    # 5. 批量更新
    update_pairs = list(to_update.items())
    for i in range(0, len(update_pairs), batch_size):
        batch = dict(update_pairs[i:i + batch_size])
        payload = {"update_records": batch}
        result = run_lark([
            "base", "+record-batch-update",
            "--base-token", base_token,
            "--table-id", table_id,
            "--json", json.dumps(payload, ensure_ascii=False),
            "--format", "json",
        ], check=False)
        if result.get("ok") is False:
            err_msg = json.dumps(result.get("error", {}), ensure_ascii=False)
            stats["errors"].append(f"批量更新失败 (第 {i // batch_size + 1} 批): {err_msg}")
            stats["failed"] += len(batch)
        else:
            stats["updated"] += len(batch)

    return stats


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def run_sync(base_token=None, table_opp=None, table_cust=None,
             data=None, rules=None, today=None,
             dry_run=True, batch_size=50, as_json=False):
    """执行双表同步，返回结果 dict。可被 crm.py 调用。"""
    base_token = base_token or DEFAULT_BASE_TOKEN
    table_opp = table_opp or "门店客户商机表"
    table_cust = table_cust or "总部客户档案表"
    data = data or str(crm.DEFAULT_LEDGER)
    rules = rules or str(crm.RULES_PATH)
    today = today or crm.date.today().isoformat()

    rules_obj = crm.load_rules(rules)
    ledger = crm.load_ledger(data)

    # 生成本地记录集
    sync_payload = crm.build_sync_record_sets(ledger, rules_obj, today)
    local_errors = sync_payload.get("errors", [])
    if local_errors:
        return {
            "ok": False,
            "stage": "local_data",
            "error": "本地台账数据有错误",
            "details": local_errors,
        }

    # 列出 Base 中的表
    try:
        remote_tables = list_tables(base_token)
    except RuntimeError as e:
        return {
            "ok": False,
            "stage": "base_access",
            "error": "无法访问飞书 Base",
            "detail": str(e),
            "hint": "请确认：1) lark-cli 已登录；2) 当前账号对该 Base 有至少可查看权限；"
                    "3) Base token 正确。常见错误码 91403 = 无权限，需 Base 所有者共享给当前账号。",
        }

    results = []
    # 按固定顺序：商机表 → 客户档案表
    target_order = [table_opp, table_cust]
    for table_name in target_order:
        if table_name not in sync_payload["tables"]:
            results.append({
                "table": table_name,
                "status": "not_in_local",
                "error": f"本地记录集中没有表「{table_name}」",
            })
            continue

        table_data = dict(sync_payload["tables"][table_name])
        table_data["table_name"] = table_name

        if table_name not in remote_tables:
            results.append({
                "table": table_name,
                "status": "table_not_found",
                "error": f"飞书 Base 中找不到表「{table_name}」",
                "available_tables": list(remote_tables.keys()),
                "hint": "需在飞书 Base 中创建同名数据表，或确认表名是否一致",
            })
            continue

        table_id = remote_tables[table_name]
        table_data["table_id"] = table_id
        try:
            stats = sync_table(base_token, table_id, table_data,
                               dry_run=dry_run, batch_size=batch_size)
            results.append(stats)
        except Exception as e:
            results.append({
                "table": table_name,
                "table_id": table_id,
                "status": "error",
                "error": str(e),
            })

    return {
        "ok": True,
        "mode": "write" if not dry_run else "dry-run",
        "base_token": base_token,
        "results": results,
    }


def _print_human(output):
    """人类可读的同步报告。"""
    if not output.get("ok"):
        print(f"❌ 同步失败（阶段: {output.get('stage', '?')}）")
        print(f"   错误: {output.get('error', output.get('detail', '?'))}")
        if output.get("details"):
            for d in output["details"]:
                print(f"   - {d}")
        if output.get("hint"):
            print(f"   提示: {output['hint']}")
        return

    print(f"同步模式: {'✅ 实际写入' if output['mode'] == 'write' else '🔍 预览（dry-run，未写入）'}")
    print(f"Base token: {output['base_token']}")
    print()

    for r in output["results"]:
        table = r.get("table", "?")
        print(f"━━━ {table} ━━━")
        status = r.get("status")
        if status == "table_not_found":
            print(f"  ❌ 表不存在: {r.get('error')}")
            print(f"  Base 中现有表: {r.get('available_tables', [])}")
            if r.get("hint"):
                print(f"  提示: {r['hint']}")
        elif status == "not_in_local":
            print(f"  ⚠️  {r.get('error')}")
        elif status == "error":
            print(f"  ❌ 错误: {r.get('error')}")
        else:
            print(f"  本地记录数: {r.get('total_local', 0)}")
            print(f"  飞书已有记录: {r.get('existing_remote', '?')}")
            print(f"  待新增: {r.get('to_create', 0)}")
            print(f"  待更新: {r.get('to_update', 0)}")
            if r.get("skipped", 0):
                print(f"  跳过（空记录）: {r['skipped']}")
            if output["mode"] == "write":
                print(f"  已新增: {r.get('created', 0)}")
                print(f"  已更新: {r.get('updated', 0)}")
                print(f"  失败: {r.get('failed', 0)}")
            if r.get("missing_fields"):
                print(f"  ⚠️  缺少字段: {r['missing_fields']}")
            if r.get("errors"):
                print(f"  ❌ 错误:")
                for err in r["errors"]:
                    print(f"     - {err}")
        print()


def main():
    parser = argparse.ArgumentParser(description="飞书多维表格双表同步")
    parser.add_argument("--base-token", default=DEFAULT_BASE_TOKEN,
                        help=f"飞书 Base token（默认 {DEFAULT_BASE_TOKEN}）")
    parser.add_argument("--table-opp", default="门店客户商机表", help="商机表名称")
    parser.add_argument("--table-cust", default="总部客户档案表", help="客户档案表名称")
    parser.add_argument("--data", default=str(crm.DEFAULT_LEDGER), help="本地台账 JSON 路径")
    parser.add_argument("--rules", default=str(crm.RULES_PATH), help="规则文件路径")
    parser.add_argument("--today", default=None, help="基准日期 YYYY-MM-DD（默认系统日期）")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE,
                        help=f"每批写入记录数（默认 {DEFAULT_BATCH_SIZE}，最大 200）")
    parser.add_argument("--yes", action="store_true",
                        help="实际写入飞书（默认 dry-run 只预览）")
    parser.add_argument("--json", action="store_true", help="以 JSON 格式输出结果")
    args = parser.parse_args()

    output = run_sync(
        base_token=args.base_token,
        table_opp=args.table_opp,
        table_cust=args.table_cust,
        data=args.data,
        rules=args.rules,
        today=args.today,
        dry_run=not args.yes,
        batch_size=args.batch_size,
        as_json=args.json,
    )

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    else:
        _print_human(output)

    sys.exit(0 if output.get("ok") else 1)


if __name__ == "__main__":
    main()
