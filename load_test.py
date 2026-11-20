"""测量 N 个短请求同时到达时的首段延迟和总耗时。"""

import argparse
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from statistics import median
from threading import Barrier


def get_props(base_url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(base_url.rstrip("/") + "/props", timeout=10) as response:
        return json.load(response)


def one_request(base_url, model, question, max_tokens, ready):
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": question}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "stream": True,
        "cache_prompt": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    request = urllib.request.Request(
        base_url.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    ready.wait()
    start = time.perf_counter()
    first = None
    parts = []
    finish_reason = None
    try:
        with opener.open(request, timeout=120) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8").strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                if chunk.get("error"):
                    raise RuntimeError(str(chunk["error"]))
                if not chunk.get("choices"):
                    continue
                choice = chunk["choices"][0]
                finish_reason = choice.get("finish_reason") or finish_reason
                text = choice.get("delta", {}).get("content")
                if text:
                    if first is None:
                        first = time.perf_counter()
                    parts.append(text)
        end = time.perf_counter()
        if first is None:
            raise RuntimeError("未收到正文")
        return {
            "ok": True,
            "request": payload,
            "start_monotonic": start,
            "end_monotonic": end,
            "first_content_ms": (first - start) * 1000,
            "total_ms": (end - start) * 1000,
            "finish_reason": finish_reason,
            "answer": "".join(parts),
        }
    except Exception as error:
        return {"ok": False, "error": repr(error), "total_ms": (time.perf_counter() - start) * 1000}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url")
    parser.add_argument("--model", default="qwen-local-q8")
    parser.add_argument("--concurrency", type=int, required=True, choices=[2, 4, 8])
    parser.add_argument("--max-tokens", type=int, choices=range(1, 257), default=256, metavar="1–256")
    args = parser.parse_args()

    props_before = get_props(args.base_url)
    question = "一个10欧姆的电阻通过2安培电流，两端电压是多少？只给出结果和单位。"
    print("预热一次短请求（不计入统计）……", flush=True)
    warmup = one_request(args.base_url, args.model, question, args.max_tokens, Barrier(1))
    if not warmup["ok"]:
        raise SystemExit(f"预热失败：{warmup}")
    barrier = Barrier(args.concurrency)
    results = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [
            executor.submit(one_request, args.base_url, args.model, question, args.max_tokens, barrier)
            for _ in range(args.concurrency)
        ]
        for future in as_completed(futures):
            results.append(future.result())

    values = [item for item in results if item.get("ok")]
    if values:
        first_values = sorted(item["first_content_ms"] for item in values)
        total_values = sorted(item["total_ms"] for item in values)
        stats = {
            "successful": len(values),
            "first_content_median_ms": median(first_values),
            "first_content_min_ms": min(first_values),
            "first_content_max_ms": max(first_values),
            "total_median_ms": median(total_values),
            "total_min_ms": min(total_values),
            "total_max_ms": max(total_values),
        }
    else:
        stats = {"successful": 0}

    stats["first_content_within_200ms"] = sum(item["first_content_ms"] <= 200 for item in values)
    stats["finished_normally"] = sum(item["finish_reason"] == "stop" for item in values)
    stats["truncated"] = sum(item["finish_reason"] == "length" for item in values)
    stats["finished_normally_within_200ms_first_content"] = sum(
        item["finish_reason"] == "stop" and item["first_content_ms"] <= 200 for item in values
    )
    props_after = get_props(args.base_url)

    output_dir = Path(__file__).resolve().parent / "evaluations"
    output_dir.mkdir(exist_ok=True)
    record = {
        "time": datetime.now().isoformat(),
        "endpoint": args.base_url,
        "requested_concurrency": args.concurrency,
        "max_tokens": args.max_tokens,
        "props_before": props_before,
        "props_after": props_after,
        "warmup": warmup,
        "note": "单次同时到达的短请求突发；首段延迟与正常结束分别统计，失败计入总请求分母；正确性另行检查。",
        "question": question,
        "results": results,
        "statistics": stats,
    }
    path = output_dir / f"load_c{args.concurrency}_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
    with path.open("x", encoding="utf-8") as file:
        json.dump(record, file, ensure_ascii=False, indent=2)

    print(f"服务槽位：{props_before.get('total_slots')}；单槽位上下文：{props_before.get('default_generation_settings', {}).get('n_ctx')}")
    print(f"并发请求数：{args.concurrency}；收到正文：{stats['successful']}；正常结束：{stats['finished_normally']}；截断：{stats['truncated']}")
    print(f"首段不超过200ms：{stats['first_content_within_200ms']}/{args.concurrency}；且正常结束：{stats['finished_normally_within_200ms_first_content']}/{args.concurrency}（回答正确性另行检查）")
    if stats.get("successful"):
        print(f"首段延迟中位数：{stats['first_content_median_ms']:.3f} ms（范围 {stats['first_content_min_ms']:.3f}～{stats['first_content_max_ms']:.3f}）")
        print(f"总耗时中位数：{stats['total_median_ms']:.3f} ms（范围 {stats['total_min_ms']:.3f}～{stats['total_max_ms']:.3f}）")
    print(f"结果已保存：{path}")


if __name__ == "__main__":
    main()
