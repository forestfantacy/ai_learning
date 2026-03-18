#!/usr/bin/env bash
set -u

RAW_INPUT="${*:-}"
BASE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_PATH="$BASE_DIR/query_session_stats.py"
OUTPUT_ROOT="${OPENCLAW_REPORT_OUTPUT_DIR:-$BASE_DIR/outputs}"
TMP_ROOT="${OPENCLAW_REPORT_TMP_DIR:-$BASE_DIR/tmp}"
LOG_DIR="${OPENCLAW_REPORT_LOG_DIR:-$BASE_DIR/logs}"
FEISHU_MEDIA_DIR="${OPENCLAW_REPORT_MEDIA_DIR:-$BASE_DIR/outputs/staging-media}"
RETENTION_DAYS="${OPENCLAW_REPORT_RETENTION_DAYS:-14}"
TMP_RETENTION_DAYS="${OPENCLAW_REPORT_TMP_RETENTION_DAYS:-3}"
LOG_RETENTION_DAYS="${OPENCLAW_REPORT_LOG_RETENTION_DAYS:-14}"

RUN_ID="$(date +%Y%m%d-%H%M%S)"
DATE_BUCKET="${RUN_ID:0:4}-${RUN_ID:4:2}-${RUN_ID:6:2}"
OUTPUT_DIR="$OUTPUT_ROOT/$DATE_BUCKET"

CSV_PATH="$OUTPUT_DIR/session-stats_summary_${RUN_ID}.csv"
JSON_PATH="$OUTPUT_DIR/session-stats_summary_${RUN_ID}.json"
B_IMG="$OUTPUT_DIR/session-stats_b_channel_${RUN_ID}.png"
C_IMG="$OUTPUT_DIR/session-stats_c_channel_${RUN_ID}.png"
ALL_IMG="$OUTPUT_DIR/session-stats_all_channels_${RUN_ID}.png"
LOG_PATH="$LOG_DIR/kudi-report_${RUN_ID}.log"

if [[ ! -f "$SCRIPT_PATH" ]]; then
  echo "[ERROR] 脚本不存在: $SCRIPT_PATH"
  exit 2
fi

FULL_MODE=0
if [[ "$RAW_INPUT" == *"全渠道"* ]]; then
  FULL_MODE=1
fi

LOWER_INPUT="$(printf '%s' "$RAW_INPUT" | tr '[:upper:]' '[:lower:]')"
if [[ "$LOWER_INPUT" == *"full"* || "$LOWER_INPUT" == *"all"* ]]; then
  FULL_MODE=1
fi

CMD=(python3 "$SCRIPT_PATH")
if [[ "$FULL_MODE" -eq 1 ]]; then
  CMD+=(--full)
fi
CMD+=(--run-id "$RUN_ID" --output-dir "$OUTPUT_ROOT" --tmp-dir "$TMP_ROOT")

echo "[INFO] 触发词: ${RAW_INPUT:-<empty>}"
echo "[INFO] 模式: $([[ "$FULL_MODE" -eq 1 ]] && echo '全渠道' || echo '默认(B端+C端)')"
echo "[INFO] Run ID: $RUN_ID"
echo "[INFO] 输出根目录: $OUTPUT_ROOT"
echo "[INFO] 输出目录: $OUTPUT_DIR"
echo "[INFO] 临时目录根: $TMP_ROOT"
echo "[INFO] 日志文件: $LOG_PATH"
echo "[INFO] 保留策略: outputs=${RETENTION_DAYS}d tmp=${TMP_RETENTION_DAYS}d logs=${LOG_RETENTION_DAYS}d"
echo "[INFO] 执行命令: ${CMD[*]}"

mkdir -p "$OUTPUT_ROOT"
mkdir -p "$TMP_ROOT"
mkdir -p "$LOG_DIR"
mkdir -p "$OUTPUT_DIR"
mkdir -p "$FEISHU_MEDIA_DIR"

python3 - "$OUTPUT_ROOT" "$TMP_ROOT" "$LOG_DIR" "$RETENTION_DAYS" "$TMP_RETENTION_DAYS" "$LOG_RETENTION_DAYS" <<'PY'
import os
import re
import sys
import time
from datetime import datetime

output_root, tmp_root, log_dir, keep_output_days, keep_tmp_days, keep_log_days = sys.argv[1:]


def remove_date_dirs(root: str, keep_days: int) -> None:
    if keep_days < 0 or not os.path.isdir(root):
        return
    now = datetime.now()
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", name):
            continue
        try:
            day = datetime.strptime(name, "%Y-%m-%d")
        except ValueError:
            continue
        age_days = (now - day).days
        if age_days > keep_days:
            for current_root, dirs, files in os.walk(path, topdown=False):
                for filename in files:
                    os.remove(os.path.join(current_root, filename))
                for dirname in dirs:
                    os.rmdir(os.path.join(current_root, dirname))
            os.rmdir(path)


def remove_old_files(root: str, keep_days: int) -> None:
    if keep_days < 0 or not os.path.isdir(root):
        return
    ttl_seconds = keep_days * 86400
    now_ts = time.time()
    for name in os.listdir(root):
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        age_seconds = now_ts - os.path.getmtime(path)
        if age_seconds > ttl_seconds:
            os.remove(path)


remove_date_dirs(output_root, int(keep_output_days))
remove_date_dirs(tmp_root, int(keep_tmp_days))
remove_old_files(log_dir, int(keep_log_days))
PY

"${CMD[@]}" | tee "$LOG_PATH"
RUN_EXIT=${PIPESTATUS[0]}

EXPECTED=("$CSV_PATH" "$JSON_PATH" "$B_IMG" "$C_IMG")
if [[ "$FULL_MODE" -eq 1 ]]; then
  EXPECTED+=("$ALL_IMG")
fi

MISSING=()
for file in "${EXPECTED[@]}"; do
  if [[ ! -f "$file" ]]; then
    MISSING+=("$file")
  fi
done

echo "[INFO] 产物检查:"
for file in "${EXPECTED[@]}"; do
  if [[ -f "$file" ]]; then
    echo "  - OK: $file"
  else
    echo "  - MISSING: $file"
  fi
done

echo "[INFO] 回传建议:"
echo "  - 优先使用消息工具发送文件（media/path/filePath）"
echo "  - 附件路径请使用 $FEISHU_MEDIA_DIR 下文件（命中 feishu mediaLocalRoots）"

stage_for_feishu() {
  local src="$1"
  local base staged
  base="$(basename "$src")"
  staged="$FEISHU_MEDIA_DIR/$base"
  cp -f "$src" "$staged"
  echo "$staged"
}

STAGED_B="$(stage_for_feishu "$B_IMG")"
STAGED_C="$(stage_for_feishu "$C_IMG")"
if [[ "$FULL_MODE" -eq 1 ]]; then
  STAGED_ALL="$(stage_for_feishu "$ALL_IMG")"
fi

STAGED_CSV="$(stage_for_feishu "$CSV_PATH")"
STAGED_JSON="$(stage_for_feishu "$JSON_PATH")"

echo "[INFO] 建议用于飞书发送的附件路径:"
echo "FILE:$STAGED_B"
echo "FILE:$STAGED_C"
if [[ "$FULL_MODE" -eq 1 ]]; then
  echo "FILE:$STAGED_ALL"
fi
echo "FILE:$STAGED_CSV"
echo "FILE:$STAGED_JSON"

echo "[INFO] 若使用内联文本回传，请在最终回复中逐行输出:"
echo "MEDIA:$STAGED_B"
echo "MEDIA:$STAGED_C"
if [[ "$FULL_MODE" -eq 1 ]]; then
  echo "MEDIA:$STAGED_ALL"
fi
echo "MEDIA:$STAGED_CSV"
echo "MEDIA:$STAGED_JSON"

if [[ "$RUN_EXIT" -ne 0 ]]; then
  echo "[ERROR] 报表脚本执行失败，退出码: $RUN_EXIT"
  exit "$RUN_EXIT"
fi

if [[ "${#MISSING[@]}" -gt 0 ]]; then
  echo "[ERROR] 执行完成但存在缺失产物"
  exit 3
fi

echo "[INFO] 库迪助手报表执行成功"
