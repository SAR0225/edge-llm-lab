import json
import time
import urllib.request

url = "http://127.0.0.1:8080/v1/chat/completions"

text = "设备在本地分析传感器数据，并将摘要发送给服务器。\n" * 40

payload = {
    "model": "local-qwen",
    "messages": [
        {
            "role": "user",
            "content": text + "请用一句话概括上述处理方式。"
        }
    ],
    "max_tokens": 64,
    "temperature": 0,
    "stream": False,
    "cache_prompt": True,
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