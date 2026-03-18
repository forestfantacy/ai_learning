#!/usr/bin/env python3
"""会话助手使用分析看板查询脚本。"""

import argparse
import csv
import json
import os
import re
import subprocess
import time
from datetime import datetime


METRIC_NAMES = [
    "提问量",
    "会话数",
    "会话量",
    "知识命中数",
    "机器人拦截率",
    "转人工会话数",
    "转人工率",
    "参评会话量",
    "参评会话率",
    "点赞数",
    "未识别量",
    "用户数",
    "活跃用户数",
    "解决量",
    "解决率",
    "满意度",
]

ALL_CHANNEL_PLAN = [
    ("全部渠道", None, "all_channels"),
    ("B端客户", ["title=B端客户", "B端客户"], "b_channel"),
    ("C端客户", ["title=C端客户", "C端客户", "title=C端", "C端"], "c_channel"),
]

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUTPUT_ROOT = os.path.join(SCRIPT_DIR, "outputs")
DEFAULT_TMP_ROOT = os.path.join(SCRIPT_DIR, "tmp")
OUTPUT_ENV = "KUDI_REPORT_OUTPUT_DIR"
TMP_ENV = "KUDI_REPORT_TMP_DIR"


def run_browser_use(command, verbose=True):
    home = os.path.expanduser("~")
    cmd = f"source {home}/browser-use/.venv/bin/activate && browser-use {command}"
    if verbose:
        print(f"$ {command}")
    result = subprocess.run(
        cmd,
        shell=True,
        executable="/bin/bash",
        capture_output=True,
        text=True,
        env={**os.environ, "PATH": f"{home}/.local/bin:" + os.environ.get("PATH", "")},
    )
    if verbose and result.stdout:
        print(result.stdout)
    if verbose and result.stderr:
        print(result.stderr)
    return result


def get_state():
    return run_browser_use("state", verbose=False).stdout or ""


def _extract_index_from_context(lines, i):
    m = re.search(r"\[(\d+)\]<", lines[i])
    if m:
        return int(m.group(1))
    for j in range(i - 1, max(-1, i - 4), -1):
        m = re.search(r"\[(\d+)\]<", lines[j])
        if m:
            return int(m.group(1))
    for j in range(i + 1, min(len(lines), i + 3)):
        m = re.search(r"\[(\d+)\]<", lines[j])
        if m:
            return int(m.group(1))
    return None


def find_indices_by_text(state_text, text):
    indices = []
    lines = state_text.splitlines()
    for i, line in enumerate(lines):
        if text in line:
            idx = _extract_index_from_context(lines, i)
            if idx is not None:
                indices.append(idx)
    return indices


def find_first_index_by_fragments(state_text, fragments):
    lines = state_text.splitlines()
    for fragment in fragments:
        for i, line in enumerate(lines):
            if fragment in line:
                idx = _extract_index_from_context(lines, i)
                if idx is not None:
                    return idx
    return None


def find_query_button_index(state_text):
    lines = state_text.splitlines()
    for i, line in enumerate(lines):
        m = re.search(r"\[(\d+)\]<button", line)
        if not m:
            continue
        if "查 询" in " ".join(lines[i : i + 4]):
            return int(m.group(1))
    for i, line in enumerate(lines):
        if "查 询" in line:
            for j in range(max(0, i - 3), i + 1):
                m = re.search(r"\[(\d+)\]<button", lines[j])
                if m:
                    return int(m.group(1))
    return None


def parse_metric_value(state_text, metric_name):
    lines = state_text.splitlines()
    for i, line in enumerate(lines):
        if metric_name in line:
            for j in range(i + 1, min(i + 8, len(lines))):
                s = lines[j].strip()
                m = re.match(r"^([0-9][0-9,]*(?:\.\d+)?(?:%|个)?)$", s)
                if m:
                    return m.group(1)
    return None


def collect_metrics(state_text):
    metrics = {}
    for name in METRIC_NAMES:
        value = parse_metric_value(state_text, name)
        if value is not None:
            metrics[name] = value
    return metrics


def click_success(idx, desc):
    if idx is None:
        return False
    result = run_browser_use(f"click {idx}")
    ok = "clicked" in (result.stdout or "")
    if not ok:
        print(f"[WARN] click failed: {desc} ({idx})")
    return ok


def open_channel_dropdown(option_fragments):
    for _ in range(6):
        st = get_state()
        if find_first_index_by_fragments(st, option_fragments) is not None:
            return st

        channel_indices = find_indices_by_text(st, "会话来源渠道")
        placeholder_indices = find_indices_by_text(st, "请选择（单选）")

        channel_candidates = []
        for idx in channel_indices[:2]:
            channel_candidates.extend(
                [
                    idx,
                    idx - 1,
                    idx - 2,
                    idx - 3,
                    idx - 4,
                    idx + 1,
                    idx + 2,
                    idx + 3,
                    idx + 4,
                    idx + 5,
                    idx + 6,
                    idx + 7,
                    idx + 8,
                ]
            )
        channel_candidates.extend([213, 214, 215, 216, 217, 218])

        placeholder_candidates = []
        for idx in placeholder_indices[:2]:
            placeholder_candidates.extend([idx, idx - 1, idx + 1, idx + 2])

        ordered = []
        seen = set()
        for idx in channel_candidates + placeholder_candidates:
            if idx is None or idx <= 0 or idx in seen:
                continue
            seen.add(idx)
            ordered.append(idx)

        for idx in ordered[:8]:
            click_success(idx, "会话来源渠道下拉触发")
            time.sleep(0.2)

        time.sleep(1)

    raise RuntimeError("无法打开会话来源渠道下拉框")


def select_channel(channel_name, option_fragments):
    print(f"\n[渠道] 选择 {channel_name}...")
    st = open_channel_dropdown(option_fragments)
    option_idx = find_first_index_by_fragments(st, option_fragments)
    if option_idx is None:
        raise RuntimeError(f"未找到 {channel_name} 选项")
    if not click_success(option_idx, channel_name):
        raise RuntimeError(f"点击 {channel_name} 失败")
    time.sleep(1)


def click_query_button():
    st = get_state()
    query_idx = find_query_button_index(st)
    if query_idx is None:
        query_candidates = find_indices_by_text(st, "查 询")
        query_idx = query_candidates[0] if query_candidates else 45
    if not click_success(query_idx, "查询按钮"):
        click_success(45, "查询按钮fallback-45")
        click_success(48, "查询按钮fallback-48")
    return query_idx


def wait_for_refresh(previous_ask_value, query_idx):
    refreshed = False
    latest_ask = None
    latest_state = ""

    for _ in range(10):
        time.sleep(1)
        latest_state = get_state()
        latest_ask = parse_metric_value(latest_state, "提问量")
        if previous_ask_value and latest_ask and latest_ask != previous_ask_value:
            refreshed = True
            break

    if not refreshed:
        print("[WARN] 首次查询未检测到提问量变化，重试一次查询")
        click_success(query_idx, "查询按钮重试")
        for _ in range(10):
            time.sleep(1)
            latest_state = get_state()
            latest_ask = parse_metric_value(latest_state, "提问量")
            if previous_ask_value and latest_ask and latest_ask != previous_ask_value:
                refreshed = True
                break

    if not latest_state:
        latest_state = get_state()
        latest_ask = parse_metric_value(latest_state, "提问量")

    return refreshed, latest_ask, latest_state


def format_metrics(metrics):
    if not metrics:
        return "未识别到指标值"
    return "，".join(f"{k}: {v}" for k, v in metrics.items())


def write_csv_summary(rows, csv_path):
    headers = ["渠道"] + METRIC_NAMES
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def write_json_summary(payload, json_path):
    with open(json_path, "w", encoding="utf-8") as file_obj:
        json.dump(payload, file_obj, ensure_ascii=False, indent=2)


def parse_args():
    parser = argparse.ArgumentParser(description="会话助手看板多渠道查询")
    parser.add_argument(
        "--full",
        action="store_true",
        help="启用全量模式：查询 全部渠道 + B端客户 + C端客户",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=f"输出根目录（优先级最高；默认读取 ${OUTPUT_ENV}，否则 {DEFAULT_OUTPUT_ROOT}）",
    )
    parser.add_argument(
        "--tmp-dir",
        default=None,
        help=f"临时目录根路径（默认读取 ${TMP_ENV}，否则 {DEFAULT_TMP_ROOT}）",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="本次运行唯一ID，格式建议 YYYYMMDD-HHMMSS；不传则自动生成",
    )
    return parser.parse_args()


def get_channel_plan(full_mode):
    if full_mode:
        return ALL_CHANNEL_PLAN
    return [
        ("B端客户", ["title=B端客户", "B端客户"], "b_channel"),
        ("C端客户", ["title=C端客户", "C端客户", "title=C端", "C端"], "c_channel"),
    ]


def resolve_output_root(cli_value):
    candidate = cli_value or os.environ.get(OUTPUT_ENV) or DEFAULT_OUTPUT_ROOT
    return os.path.abspath(os.path.expanduser(candidate))


def resolve_tmp_root(cli_value):
    candidate = cli_value or os.environ.get(TMP_ENV) or DEFAULT_TMP_ROOT
    return os.path.abspath(os.path.expanduser(candidate))


def resolve_run_id(cli_value):
    if cli_value:
        return cli_value
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def run_id_to_date_bucket(run_id):
    match = re.match(r"^(\d{4})(\d{2})(\d{2})-\d{6}$", run_id)
    if match:
        return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"
    return datetime.now().strftime("%Y-%m-%d")


def main():
    args = parse_args()
    channel_plan = get_channel_plan(args.full)

    run_id = resolve_run_id(args.run_id)
    date_bucket = run_id_to_date_bucket(run_id)

    output_root = resolve_output_root(args.output_dir)
    tmp_root = resolve_tmp_root(args.tmp_dir)

    output_dir = os.path.join(output_root, date_bucket)
    tmp_dir = os.path.join(tmp_root, date_bucket)
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(tmp_dir, exist_ok=True)

    url = (
        "https://bi.aliyuncs.com/token3rd/dashboard/view/pc.htm?"
        "pageId=68dc2797-9628-43c7-a1aa-d95f848a15ff&"
        "accessTicket=51eb3946-5a52-4498-b2db-c4e418a836d3&"
        "dd_orientation=auto&qbi_version_param=1"
    )

    print("=" * 60)
    print("会话助手使用分析看板 - 多渠道查询")
    print(
        "输出顺序: 全部渠道 -> B端客户 -> C端客户"
        if args.full
        else "输出顺序: B端客户 -> C端客户 (默认模式)"
    )
    print(f"Run ID: {run_id}")
    print(f"输出目录: {output_dir}")
    print(f"临时目录: {tmp_dir}")
    print("=" * 60)

    print("\n[1] Closing session...")
    run_browser_use("close")
    time.sleep(1)

    print("\n[2] Opening dashboard...")
    run_browser_use(f'open "{url}"')
    time.sleep(5)

    initial_state = get_state()
    previous_ask = parse_metric_value(initial_state, "提问量")
    print(f"Baseline 提问量: {previous_ask}")

    screenshot_paths = []
    csv_rows = []

    for channel_name, option_fragments, file_suffix in channel_plan:
        if option_fragments:
            select_channel(channel_name, option_fragments)
        else:
            print(f"\n[渠道] 使用默认筛选: {channel_name}")

        print("[动作] 点击 查询...")
        query_idx = click_query_button()

        print("[动作] 等待数据刷新...")
        refreshed, latest_ask, latest_state = wait_for_refresh(previous_ask, query_idx)
        if not refreshed:
            print("[WARN] 未检测到提问量变化，将继续输出当前页面数据")

        state_snapshot_path = os.path.join(tmp_dir, f"tmp_state_{file_suffix}_{run_id}.txt")
        with open(state_snapshot_path, "w", encoding="utf-8") as file_obj:
            file_obj.write(latest_state)

        metrics = collect_metrics(latest_state)
        print(f"[统计] {channel_name}: {format_metrics(metrics)}")

        csv_row = {"渠道": channel_name}
        for metric_name in METRIC_NAMES:
            csv_row[metric_name] = metrics.get(metric_name, "")
        csv_rows.append(csv_row)

        screenshot_name = f"session-stats_{file_suffix}_{run_id}.png"
        screenshot_path = os.path.join(output_dir, screenshot_name)
        print(f"[截图] {channel_name}: {screenshot_path}")
        run_browser_use(f"screenshot {screenshot_path}")
        screenshot_paths.append(screenshot_path)

        previous_ask = latest_ask or previous_ask

    csv_name = f"session-stats_summary_{run_id}.csv"
    csv_path = os.path.join(output_dir, csv_name)
    write_csv_summary(csv_rows, csv_path)

    json_name = f"session-stats_summary_{run_id}.json"
    json_path = os.path.join(output_dir, json_name)
    json_payload = {
        "runId": run_id,
        "mode": "full" if args.full else "default",
        "dateBucket": date_bucket,
        "outputDir": output_dir,
        "tmpDir": tmp_dir,
        "rows": csv_rows,
        "screenshots": screenshot_paths,
    }
    write_json_summary(json_payload, json_path)

    manifest_name = f"manifest_{run_id}.json"
    manifest_path = os.path.join(output_dir, manifest_name)
    manifest_payload = {
        "runId": run_id,
        "mode": "full" if args.full else "default",
        "artifacts": {
            "csv": csv_path,
            "json": json_path,
            "images": screenshot_paths,
        },
    }
    write_json_summary(manifest_payload, manifest_path)

    print("\n" + "=" * 60)
    print("Done! 多渠道查询完成")
    for path in screenshot_paths:
        print(f"ARTIFACT:image={path}")
    print(f"ARTIFACT:csv={csv_path}")
    print(f"ARTIFACT:json={json_path}")
    print(f"MANIFEST:{manifest_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
