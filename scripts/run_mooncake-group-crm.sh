#!/usr/bin/env bash
# 门店团购 CRM 串联脚本（确定性编排）：prepare →(Agent 抽取)→ validate（必经闸口）→ apply 写台账；周期：summary → 渲染 HTML。
# 契约优先：任何写台账之前必须先通过 validate。渲染（HTML 周报）前先产 summary。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="${PYTHON:-python3}"
VALIDATE="$SCRIPT_DIR/validate_mooncake-group-crm_output.py"
PREPARE="$SCRIPT_DIR/prepare_extraction.py"
CRM="$SCRIPT_DIR/crm.py"
GEN="$SCRIPT_DIR/gen_review_report.py"

usage() {
  cat <<'EOF'
用法：
  run_mooncake-group-crm.sh extract --text "店长原话" --today YYYY-MM-DD [--store 门店] [--owner 跟进人]
        → 产出抽取载荷（含契约），交给 Agent 抽成 record.json

  run_mooncake-group-crm.sh apply <record.json> [--confirmed] [--today D] [--data ledger.json] [--json]
        → 先 validate（必经）；通过才 crm.py apply 写台账；失败即停止、不落库
        → 记录含金额/数量/电话/日期时必须加 --confirmed（店长已逐项确认），否则引擎拒写并回 needs_confirmation

  run_mooncake-group-crm.sh validate <record.json>
        → 只校验，不写库

  run_mooncake-group-crm.sh report [--period weekly] [--today D] [--data ledger.json] [--out review.html] [--title 门店]
        → summary（+due）→ 渲染自包含 HTML 周报

  run_mooncake-group-crm.sh due [--today D] [--data ledger.json] [--json]
        → 到期/逾期清单 + 话术
EOF
}

CMD="${1:-}"; shift || true
case "$CMD" in
  extract)
    exec "$PY" "$PREPARE" "$@"
    ;;
  validate)
    REC="${1:?需要 record.json 路径}"
    exec "$PY" "$VALIDATE" "$REC"
    ;;
  apply)
    REC="${1:?需要 record.json 路径}"; shift
    echo "▶ 校验抽取记录：$REC" >&2
    if ! "$PY" "$VALIDATE" "$REC" >&2; then
      echo "✋ 校验未通过，停止写库（不污染台账）。请补齐缺项/改正枚举后重试。" >&2
      exit 1
    fi
    echo "▶ 校验通过，写入台账" >&2
    exec "$PY" "$CRM" --mode apply --record "$REC" "$@"
    ;;
  report)
    PERIOD="weekly"; TODAY=""; DATA=""; OUT="/tmp/mooncake-group-crm-review.html"; TITLE=""
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --period) PERIOD="$2"; shift 2;;
        --today) TODAY="$2"; shift 2;;
        --data) DATA="$2"; shift 2;;
        --out) OUT="$2"; shift 2;;
        --title) TITLE="$2"; shift 2;;
        *) echo "未知参数 $1" >&2; exit 2;;
      esac
    done
    CRM_ARGS=(--mode summary --period "$PERIOD" --json)
    DUE_ARGS=(--mode due --json)
    [[ -n "$TODAY" ]] && { CRM_ARGS+=(--today "$TODAY"); DUE_ARGS+=(--today "$TODAY"); }
    [[ -n "$DATA" ]] && { CRM_ARGS+=(--data "$DATA"); DUE_ARGS+=(--data "$DATA"); }
    TMP="$(mktemp -d)"
    trap 'rm -rf "$TMP"' EXIT
    "$PY" "$CRM" "${CRM_ARGS[@]}" > "$TMP/summary.json"
    "$PY" "$CRM" "${DUE_ARGS[@]}" > "$TMP/due.json"
    GEN_ARGS=(--out "$OUT")
    [[ -n "$TITLE" ]] && GEN_ARGS+=(--title "$TITLE")
    "$PY" -c 'import json,sys; print(json.dumps({"summary":json.load(open(sys.argv[1])),"due":json.load(open(sys.argv[2]))},ensure_ascii=False))' \
      "$TMP/summary.json" "$TMP/due.json" | "$PY" "$GEN" "${GEN_ARGS[@]}"
    ;;
  due)
    exec "$PY" "$CRM" --mode due "$@"
    ;;
  *)
    usage; exit 2;;
esac
