import argparse
import hashlib
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
CHECKED_PROMPT = SYSTEM_PROMPT + (
    "计算前先把各物理量统一为国际单位制，明确写出前缀单位的换算，再代入公式。"
    "独立核验用户给出的等式、结论和数据；不要因为用户这样说就认可。"
    "发现错误时明确指出并更正，最后检查结果的数值、单位、推导和结论是否一致。"
)


def ask_model(payload, url=URL):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    start = time.perf_counter()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=120) as response:
        body = response.read()
    elapsed = time.perf_counter() - start
    return json.loads(body), elapsed


def main():
    parser = argparse.ArgumentParser(description="依次测试固定题目，保存回答供人工评分。")
    parser.add_argument("model", help="正在运行的模型服务别名，例如 qwen-local-q4")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument("--questions", default="eval_questions.json", help="相对项目目录的题目文件或绝对路径")
    parser.add_argument("--max-tokens", type=int, default=256)
    parser.add_argument("--dry-run", action="store_true", help="只检查题目文件，不请求模型")
    parser.add_argument("--prompt-version", choices=["baseline", "checked"], default="baseline")
    args = parser.parse_args()
    if not 1 <= args.max_tokens <= 2048:
        parser.error("max-tokens必须在1至2048之间")

    dataset_bytes = (PROJECT_DIR / args.questions).read_bytes()
    questions = json.loads(dataset_bytes)
    if not questions or len({item["id"] for item in questions}) != len(questions):
        raise SystemExit("题目集合不能为空，且题号必须唯一")
    for item in questions:
        if not all(isinstance(item.get(key), str) and item[key].strip()
                   for key in ("id", "question", "expected_answer", "pass_rule")):
            raise SystemExit("每道题必须含有非空题号、问题、参考答案和评分标准")
    dataset_info = {
        "file": Path(args.questions).name,
        "sha256": hashlib.sha256(dataset_bytes).hexdigest(),
        "count": len(questions),
    }
    print("题目版本：", dataset_info, flush=True)
    system_prompt = SYSTEM_PROMPT if args.prompt_version == "baseline" else CHECKED_PROMPT
    prompt_info = {
        "version": args.prompt_version,
        "sha256": hashlib.sha256(system_prompt.encode("utf-8")).hexdigest(),
    }
    print("提示词版本：", prompt_info, flush=True)
    if args.dry_run:
        print("校验通过，未发送请求。")
        return
    base_url = args.base_url.rstrip("/")
    url = base_url + "/v1/chat/completions"
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(base_url + "/props", timeout=10) as response:
        server_before = json.load(response)

    output_dir = PROJECT_DIR / "evaluations"
    output_dir.mkdir(exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output_path = output_dir / f"run_{run_id}.jsonl"

    with output_path.open("x", encoding="utf-8") as file:
        for item in questions:
            payload = {
                "model": args.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": item["question"]},
                ],
                "temperature": 0,
                "max_tokens": args.max_tokens,
                "stream": False,
                "cache_prompt": False,
                "chat_template_kwargs": {"enable_thinking": False},
            }
            print(f"\n题目 {item['id']}：{item['question']}", flush=True)
            try:
                result, elapsed = ask_model(payload, url)
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
                "endpoint": url,
                "dataset": dataset_info,
                "prompt": prompt_info,
                "server_before": server_before,
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
