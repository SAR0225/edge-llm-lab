import argparse
import json
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parent
URL = "http://127.0.0.1:8080/v1/chat/completions"
SYSTEM_PROMPT = (
    "你是电子电路学习助手。"
    "回答前先检查已知条件是否足够。"
    "条件不足时，明确说明无法确定，并指出缺少什么条件。"
    "不得自行假设题目未给出的数值来得出确定答案。"
    "条件充分时，给出公式、计算结果和单位。"
)


def ask_model(payload):
    request = urllib.request.Request(
        URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    start = time.perf_counter()
    with urllib.request.urlopen(request, timeout=120) as response:
        body = response.read()
    elapsed = time.perf_counter() - start
    return json.loads(body), elapsed


def main():
    parser = argparse.ArgumentParser(description="依次测试固定题目，保存回答供人工评分。")
    parser.add_argument("model", help="正在运行的模型服务别名，例如 qwen-local-q4")
    args = parser.parse_args()

    with (PROJECT_DIR / "eval_questions.json").open(encoding="utf-8") as file:
        questions = json.load(file)

    output_dir = PROJECT_DIR / "evaluations"
    output_dir.mkdir(exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output_path = output_dir / f"run_{run_id}.jsonl"

    with output_path.open("x", encoding="utf-8") as file:
        for item in questions:
            payload = {
                "model": args.model,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": item["question"]},
                ],
                "temperature": 0,
                "max_tokens": 256,
                "stream": False,
                "cache_prompt": False,
                "chat_template_kwargs": {"enable_thinking": False},
            }
            print(f"\n题目 {item['id']}：{item['question']}", flush=True)
            try:
                result, elapsed = ask_model(payload)
            except urllib.error.HTTPError as error:
                detail = error.read().decode("utf-8", errors="replace")
                raise SystemExit(
                    f"服务返回 HTTP {error.code}：{detail}\n已有记录：{output_path}"
                ) from error
            except (urllib.error.URLError, TimeoutError) as error:
                raise SystemExit(
                    f"请求失败：{error}\n请检查模型服务是否运行。已有记录：{output_path}"
                ) from error

            choice = result["choices"][0]
            answer = choice["message"].get("content") or ""
            finish_reason = choice.get("finish_reason")
            record = {
                "run_id": run_id,
                "time": datetime.now().isoformat(timespec="seconds"),
                "endpoint": URL,
                "case": item,
                "request": payload,
                "response": result,
                "elapsed_seconds": round(elapsed, 6),
                "manual_pass": None,
            }
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
            file.flush()

            print("模型回答：", answer)
            print("参考答案：", item["expected_answer"])
            print(f"请求总耗时：{elapsed:.3f} 秒；结束原因：{finish_reason}")
            if finish_reason == "length":
                print("本题输出达到长度限制，可能未回答完整，评分时需注明。")

    print(f"\n完成 {len(questions)} 道题，结果保存在：{output_path}")
    print("本程序自动发送和记录请求，答案仍按预设标准人工评分。")


if __name__ == "__main__":
    main()
