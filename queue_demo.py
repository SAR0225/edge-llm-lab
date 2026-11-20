"""比较短请求独立运行、与长请求竞争时的客户端延迟。"""

import argparse
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from threading import Event


def read_server_config(base_url):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(base_url.rstrip("/") + "/props", timeout=10) as response:
            props = json.load(response)
        return {
            "observed_at": datetime.now().isoformat(),
            "total_slots": props.get("total_slots"),
            "context_per_slot": props.get("default_generation_settings", {}).get("n_ctx"),
            "model_path": props.get("model_path"),
        }
    except (OSError, ValueError) as error:
        return {"observation_error": str(error)}


def stream_request(base_url, model, question, max_tokens, started=None):
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
    # 实验目标是局域网服务器，直接连接，不经过系统代理。
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    start = time.perf_counter()
    first = None
    parts = []
    finish_reason = None
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
                    if started is not None:
                        started.set()
                parts.append(text)
    end = time.perf_counter()
    if first is None:
        raise RuntimeError("请求未返回非空正文，无法测首个正文片段延迟。")
    return {
        "request": payload,
        "start_monotonic": start,
        "end_monotonic": end,
        "first_content_ms": (first - start) * 1000,
        "total_ms": (end - start) * 1000,
        "finish_reason": finish_reason,
        "answer": "".join(parts),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url", help="服务地址，例如 http://127.0.0.1:8080")
    parser.add_argument("--model", default="qwen-local-q8")
    args = parser.parse_args()
    server_before = read_server_config(args.base_url)
    print("服务配置：", server_before, flush=True)
    short_question = "一个10欧姆的电阻通过2安培电流，两端电压是多少？只给出结果和单位。"
    long_question = (
        "请详细讲解电子电路入门知识，按20个编号段落依次介绍电压、电流、电阻、"
        "功率、串联、并联、基尔霍夫定律等，每段至少写三句话并举例。不要省略后续段落。"
    )
    print("预热一次短请求（不计入对比）……", flush=True)
    stream_request(args.base_url, args.model, short_question, 64)
    print("测量短请求单独运行……", flush=True)
    baseline = stream_request(args.base_url, args.model, short_question, 64)
    print("启动长请求，等它开始输出后提交同一个短问题……", flush=True)
    started = Event()
    with ThreadPoolExecutor(max_workers=1) as executor:
        long_future = executor.submit(
            stream_request, args.base_url, args.model, long_question, 1024, started
        )
        # 短间隔等待，以便长请求失败时立即报告，而非一直等到超时。
        deadline = time.perf_counter() + 120
        while not started.wait(0.1):
            if long_future.done():
                long_future.result()
                raise RuntimeError("长请求没有开始输出。")
            if time.perf_counter() > deadline:
                raise TimeoutError("等待长请求开始输出超时。")
        competing = stream_request(args.base_url, args.model, short_question, 64)
        long_result = long_future.result()

    overlap = competing["start_monotonic"] < long_result["end_monotonic"]
    record = {
        "time": datetime.now().isoformat(),
        "endpoint": args.base_url,
        "server_before": server_before,
        "server_after": read_server_config(args.base_url),
        "baseline": baseline,
        "competing": competing,
        "long_request": long_result,
        "short_submitted_before_long_received_end": overlap,
        "note": "客户端首正文片段延迟，不是纯服务端排队时间；单轮观察。",
    }
    output_dir = Path(__file__).resolve().parent / "evaluations"
    output_dir.mkdir(exist_ok=True)
    path = output_dir / f"queue_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
    with path.open("x", encoding="utf-8") as file:
        json.dump(record, file, ensure_ascii=False, indent=2)
    print(f"\n单独运行：首正文 {baseline['first_content_ms']:.3f} ms，总耗时 {baseline['total_ms']:.3f} ms")
    print(f"竞争槽位：首正文 {competing['first_content_ms']:.3f} ms，总耗时 {competing['total_ms']:.3f} ms")
    print(f"竞争时短请求回答：{competing['answer']}")
    print(f"长请求结束原因：{long_result['finish_reason']}")
    if not overlap:
        print("长请求已先结束，本轮没有形成预期的重叠，需要重试。")
    print(f"结果已保存：{path}")


if __name__ == "__main__":
    main()
