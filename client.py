import json
import time
import urllib.request

url = "http://127.0.0.1:8080/v1/chat/completions"

payload = {
    "model": "local-qwen",
    "messages": [
        {"role": "user", "content": "请用三句话解释什么是边缘计算。"}
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