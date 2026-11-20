import json
import time
import urllib.request

payload = {
    "model": "local-qwen",
    "messages": [
        {"role": "user", "content": "请用三句话解释什么是边缘计算。"}
    ],
    "max_tokens": 256,
    "stream": True,
    "chat_template_kwargs": {"enable_thinking": False},
}

request = urllib.request.Request(
    "http://127.0.0.1:8080/v1/chat/completions",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)

first_output_time = None
print("模型回答：")
start = time.perf_counter()

with urllib.request.urlopen(request, timeout=120) as response:
    for raw_line in response:
        line = raw_line.decode("utf-8").strip()

        if not line.startswith("data:"):
            continue

        data = line[5:].strip()
        if data == "[DONE]":
            break

        chunk = json.loads(data)
        if not chunk.get("choices"):
            continue

        text = chunk["choices"][0].get("delta", {}).get("content")
        if text:
            if first_output_time is None:
                first_output_time = time.perf_counter()
            print(text, end="", flush=True)

elapsed = time.perf_counter() - start

print()
if first_output_time is not None:
    print(f"首个正文片段延迟：{first_output_time - start:.3f} 秒")
else:
    print("未收到正文内容")
print(f"流式请求总耗时：{elapsed:.3f} 秒")
import csv

if first_output_time is not None:
    first_ms = (first_output_time - start) * 1000
    total_ms = elapsed * 1000

    with open("stream_results.csv", "a", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)

        if file.tell() == 0:
            writer.writerow(["first_content_ms", "total_ms"])

        writer.writerow([round(first_ms, 3), round(total_ms, 3)])

    print("计时结果已追加到 stream_results.csv")