"""按固定到达速率发请求；上一条未完成也不会阻止后续调度。"""

import argparse
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from statistics import median
from threading import Barrier, BoundedSemaphore

from load_test import get_props, one_request


QUESTION = "一个10欧姆的电阻通过2安培电流，两端电压是多少？只给出结果和单位。"


def run_schedule(base_url, model, rate, count, max_inflight, max_tokens):
    capacity = BoundedSemaphore(max_inflight)
    futures = []
    records = []
    origin = time.perf_counter()

    def execute(index, planned, submitted):
        try:
            result = one_request(base_url, model, QUESTION, max_tokens, Barrier(1))
            actual = result.get("start_monotonic", submitted)
            result.update({
                "index": index,
                "planned_offset_s": planned - origin,
                "submitted_offset_s": submitted - origin,
                "actual_start_offset_s": actual - origin,
                "client_start_lag_ms": (actual - planned) * 1000,
                "status": "received" if result.get("ok") else "request_error",
                "start_time_source": "measured" if "start_monotonic" in result else "submission_fallback",
            })
            return result
        finally:
            capacity.release()

    with ThreadPoolExecutor(max_workers=max_inflight) as pool:
        for index in range(count):
            planned = origin + index / rate
            remaining = planned - time.perf_counter()
            if remaining > 0:
                time.sleep(remaining)
            submitted = time.perf_counter()
            if not capacity.acquire(blocking=False):
                records.append({
                    "index": index,
                    "planned_offset_s": index / rate,
                    "submitted_offset_s": submitted - origin,
                    "status": "client_capacity_drop",
                    "ok": False,
                })
                continue
            futures.append(pool.submit(execute, index, planned, submitted))
        for future in as_completed(futures):
            records.append(future.result())
    # 固定供给窗口是 count/rate，结束后等候的时间单独纳入观测窗口。
    elapsed = max(count / rate, time.perf_counter() - origin)
    return sorted(records, key=lambda item: item["index"]), elapsed


def summarize(records, rate, elapsed):
    received = [item for item in records if item.get("ok")]
    normal = [item for item in received if item.get("finish_reason") == "stop"]
    lag = [item["client_start_lag_ms"] for item in records if "client_start_lag_ms" in item]
    first = [item["first_content_ms"] for item in received]
    total = [item["total_ms"] for item in received]
    supply_s = len(records) / rate
    return {
        "planned_requests": len(records),
        "sent_requests": len(lag),
        "received_body": len(received),
        "normal_stop": len(normal),
        "truncated": sum(item.get("finish_reason") == "length" for item in received),
        "request_errors": sum(item["status"] == "request_error" for item in records),
        "client_capacity_drops": sum(item["status"] == "client_capacity_drop" for item in records),
        "first_content_within_200ms": sum(item["first_content_ms"] <= 200 for item in received),
        "normal_stop_and_first_within_200ms": sum(item["first_content_ms"] <= 200 for item in normal),
        "first_content_median_ms": median(first) if first else None,
        "first_content_max_ms": max(first) if first else None,
        "total_median_ms": median(total) if total else None,
        "client_start_lag_max_ms": max(lag) if lag else None,
        "supply_window_s": supply_s,
        "observation_with_drain_s": elapsed,
        "normal_completions_per_observation_second": len(normal) / elapsed,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url")
    parser.add_argument("--model", default="qwen-local-q8")
    parser.add_argument("--rate", type=float, default=4, help="每秒计划到达的请求数")
    parser.add_argument("--count", type=int, default=40)
    parser.add_argument("--max-inflight", type=int, default=32, help="客户端最大未完成请求数")
    parser.add_argument("--max-tokens", type=int, default=256)
    args = parser.parse_args()
    if not math.isfinite(args.rate) or not 0 < args.rate <= 100:
        parser.error("rate 必须大于0且不超过100")
    if not 1 <= args.count <= 1000 or not 1 <= args.max_inflight <= 128 or not 1 <= args.max_tokens <= 256:
        parser.error("count范围1–1000；max-inflight范围1–128；max-tokens范围1–256")

    before = get_props(args.base_url)
    print(f"服务槽位：{before.get('total_slots')}；计划速率：{args.rate:g} 请求/秒", flush=True)
    print("先预热一次，不计入统计……", flush=True)
    warmup = one_request(args.base_url, args.model, QUESTION, args.max_tokens, Barrier(1))
    if not warmup["ok"]:
        raise SystemExit(f"预热失败：{warmup}")
    print(f"开始发送 {args.count} 个请求，完成发送后等待所有请求结束……", flush=True)
    records, elapsed = run_schedule(
        args.base_url, args.model, args.rate, args.count, args.max_inflight, args.max_tokens
    )
    stats = summarize(records, args.rate, elapsed)
    try:
        after = get_props(args.base_url)
    except (OSError, ValueError) as error:
        after = {"observation_error": str(error)}
    record = {
        "time": datetime.now().isoformat(),
        "config": vars(args),
        "question": QUESTION,
        "props_before": before,
        "props_after": after,
        "warmup": warmup,
        "results": records,
        "statistics": stats,
        "note": "独立调度固定间隔请求，客户端到首正文片段计时；失败和客户端容量丢弃计入计划请求分母。到达速率不是完成吞吐量。",
    }
    output_dir = Path(__file__).resolve().parent / "evaluations"
    output_dir.mkdir(exist_ok=True)
    path = output_dir / f"rate_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
    with path.open("x", encoding="utf-8") as file:
        json.dump(record, file, ensure_ascii=False, indent=2)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print(f"结果已保存：{path}")


if __name__ == "__main__":
    main()
