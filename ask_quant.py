import json
import time
import urllib.request

url = "http://127.0.0.1:8080/v1/chat/completions"
question = input("请输入你的问题：")
payload = {
    "temperature": 0,
    "model": "qwen-local-q4",
    "messages": [
    {
        "role": "system",
        "content": (
            "你是电子电路学习助手。"
            "回答前先检查已知条件是否足够。"
            "条件不足时，明确说明无法确定，并指出缺少什么条件。"
            "不得自行假设题目未给出的数值来得出确定答案。"
            "条件充分时，给出公式、计算结果和单位。"
        )
    },
    {"role": "user", "content": question}
],
    "max_tokens": 256,
    "stream": False,
    "chat_template_kwargs": {"enable_thinking": False},
}

data = json.dumps(payload).encode("utf-8")

request = urllib.request.Request(
    url,
    data=data,
    headers={"Content-Type": "application/json"},
    method="POST",
)

start = time.perf_counter()

with urllib.request.urlopen(request, timeout=120) as response:
    body = response.read()

elapsed = time.perf_counter() - start
result = json.loads(body)

print("模型回答：")
print(result["choices"][0]["message"]["content"])
print(f"\n请求总耗时：{elapsed:.3f} 秒")
print("token 用量：", result.get("usage", {}))
print("服务端计时信息：")
print(json.dumps(result.get("timings", {}), indent=2))
from datetime import datetime

record = {
    "time": datetime.now().isoformat(timespec="seconds"),
    "model": payload["model"],
    "messages": payload["messages"],
    "answer": result["choices"][0]["message"]["content"],
    "elapsed_seconds": round(elapsed, 4),
    "usage": result.get("usage", {}),
    "timings": result.get("timings", {}),
}

with open("qa_log.jsonl", "a", encoding="utf-8") as file:
    file.write(json.dumps(record, ensure_ascii=False) + "\n")

print("问答记录已保存到 qa_log.jsonl")