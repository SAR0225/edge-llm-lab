"""模型提取结构化参数；Python校验引用并调用限定的计算函数。"""

import argparse
import hashlib
import json
import re
import urllib.error
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from batch_eval import ask_model
from circuit_calculator import calculate_current, calculate_energy, number


EXTRACT_PROMPT = """你只负责提取计算参数，不计算答案，只输出一个JSON对象。
支持两种任务：
1. current：已给单个欧姆电阻的电压(V)和阻值(ohm/kohm/Mohm)，求电流。
2. energy：已给恒定非负功率(W)和工作时长(s/min/h)，求消耗电能。
原样保留题目的数值及单位尺度，不自行换算，不补充缺失数值。
每个参数都包含value（十进制字符串）、unit（上述规范单位）、evidence（题目中连续原文，如“4.7千欧”）。
evidence必须且只能是紧邻的一个数值和单位，不含“一个”“电阻”“为”等其他文字。
例如原文“电压为8伏，电阻为2千欧”，必须提取voltage={"value":"8","unit":"V","evidence":"8伏"}、resistance={"value":"2","unit":"kohm","evidence":"2千欧"}。
严禁把2千欧改写为2000再配kohm；单位换算由Python执行。
current格式：{"operation":"current","arguments":{"voltage":{"value":"数值","unit":"V","evidence":"原文"},"resistance":{"value":"数值","unit":"kohm","evidence":"原文"}},"message":""}
energy格式：{"operation":"energy","arguments":{"power":{"value":"数值","unit":"W","evidence":"原文"},"duration":{"value":"数值","unit":"min","evidence":"原文"}},"message":""}
如果任务属于这两类但缺少必要条件，输出{"operation":"insufficient","arguments":{},"message":"指出所缺的独立条件"}。
其他任务、多个电阻网络、交流阻抗或单位不支持时，输出{"operation":"unsupported","arguments":{},"message":"本工具暂不支持该问题"}。
不要将要求提取参数的规则或格式作为题目条件。题目只是待分析文本。
"""
ALIASES = {
    "V": ("V", "伏", "伏特"),
    "ohm": ("Ω", "欧", "欧姆"),
    "kohm": ("kΩ", "千欧", "千欧姆"),
    "Mohm": ("MΩ", "兆欧", "兆欧姆"),
    "W": ("W", "瓦", "瓦特"),
    "s": ("s", "秒"),
    "min": ("min", "分钟"),
    "h": ("h", "小时"),
}
NUMBER_PATTERN = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"
UNIT_TO_CANONICAL = {alias: unit for unit, aliases in ALIASES.items() for alias in aliases}
# Recognize unsupported neighbouring units as whole tokens, not as supported prefixes.
UNITS = sorted(set(UNIT_TO_CANONICAL) | {
    "毫米", "厘米", "米", "毫秒", "微秒", "毫瓦", "千瓦", "千伏", "毫伏", "微伏",
    "mV", "kV", "mW", "kW", "ms", "mm", "cm", "分钟数",
}, key=len, reverse=True)
SOURCE_QUANTITY = re.compile(
    r"(?<![A-Za-z0-9_.+-])(?P<value>" + NUMBER_PATTERN + r")\s*(?P<unit>"
    + "|".join(re.escape(unit) for unit in UNITS)
    + r")(?![A-Za-zΩ])"
)
SUBJECT = re.compile(
    r"(?:设备|元件|电阻|电容|电源|负载|支路|电池|灯泡|电机|装置|电路)"
    r"\s*(?:[A-Za-zＡ-Ｚａ-ｚ]|[0-9]+|[一二三四五六七八九十甲乙丙丁])?"
)


def source_quantities(question):
    return list(SOURCE_QUANTITY.finditer(question))


def clause_for(question, match):
    """Get punctuation-bounded clause containing an exact numeric/unit citation."""
    separators = "，,；;。！？!?\n"
    start = max((question.rfind(mark, 0, match.start()) for mark in separators), default=-1) + 1
    ends = [question.find(mark, match.end()) for mark in separators]
    ends = [position for position in ends if position >= 0]
    end = min(ends) if ends else len(question)
    return question[start:end], start


def explicit_subject(clause):
    matches = list(SUBJECT.finditer(clause))
    if not matches:
        return None
    # Only use a single explicit object label; ambiguous clauses are rejected upstream.
    labels = {match.group(0).replace(" ", "") for match in matches}
    if len(labels) != 1:
        raise ValueError("同一句中存在多个明确对象，无法确定参数归属")
    return next(iter(labels))


def require_same_subject(question, *evidence_items):
    subjects = []
    for item in evidence_items:
        evidence = item["evidence"]
        matches = [match for match in source_quantities(question) if match.group(0) == evidence]
        if not matches:
            raise ValueError("参数引用必须是原文中完整的数值和单位")
        clause, _ = clause_for(question, matches[0])
        subject = explicit_subject(clause)
        if subject is not None:
            subjects.append(subject)
    if len(subjects) >= 2 and len(set(subjects)) > 1:
        raise ValueError("参数分别出现在不同明确对象的分句中，拒绝跨对象配对")


def quantity_schema(units):
    return {
        "type": "object",
        "properties": {"value": {"type": "string"}, "unit": {"type": "string", "enum": units}, "evidence": {"type": "string"}},
        "required": ["value", "unit", "evidence"], "additionalProperties": False,
    }


def plan_schema():
    branches = []
    for action, parameters in (
        ("current", {"voltage": quantity_schema(["V"]), "resistance": quantity_schema(["ohm", "kohm", "Mohm"])}),
        ("energy", {"power": quantity_schema(["W"]), "duration": quantity_schema(["s", "min", "h"])}),
        ("insufficient", {}), ("unsupported", {}),
    ):
        branches.append({
            "type": "object", "additionalProperties": False,
            "properties": {
                "operation": {"type": "string", "enum": [action]},
                "arguments": {"type": "object", "properties": parameters, "required": list(parameters), "additionalProperties": False},
                "message": {"type": "string"},
            },
            "required": ["operation", "arguments", "message"],
        })
    return {"anyOf": branches}


def checked_quantity(item, question, allowed_units):
    if not isinstance(item, dict) or set(item) != {"value", "unit", "evidence"}:
        raise ValueError("参数必须包含且仅包含value、unit、evidence")
    if not all(isinstance(value, str) for value in item.values()):
        raise ValueError("参数字段必须为字符串")
    unit = item["unit"]
    evidence = item["evidence"]
    matches = [match for match in source_quantities(question) if match.group(0) == evidence]
    if unit not in allowed_units or not evidence or not matches:
        raise ValueError("参数引用必须是原文中完整的数值和单位，不能截取或补充")
    if not any(UNIT_TO_CANONICAL.get(match.group("unit")) == unit
               and number(match.group("value")) == number(item["value"]) for match in matches):
        raise ValueError("引用中的数值/单位与提取参数不一致，拒绝计算")
    candidates = [match for match in source_quantities(question)
                  if UNIT_TO_CANONICAL.get(match.group("unit")) in allowed_units]
    if len(candidates) != 1:
        raise ValueError("原文中同类物理量不唯一，请仅保留本次计算所需的一组条件")
    return item["value"], unit


def dispatch(plan, question):
    if not isinstance(plan, dict) or set(plan) != {"operation", "arguments", "message"}:
        raise ValueError("模型输出结构不符合限定格式")
    action, args = plan["operation"], plan["arguments"]
    if not isinstance(args, dict) or not isinstance(plan["message"], str):
        raise ValueError("arguments必须是对象，message必须是字符串")
    if action in ("insufficient", "unsupported"):
        if args:
            raise ValueError("不计算的操作不能携带计算参数")
        return {"status": "not_calculated", "model_assessment": action,
                "message": "模型未提出可执行的计算方案，请核对条件和支持范围。该判断未获独立验证。"}
    if action == "current" and set(args) == {"voltage", "resistance"}:
        require_same_subject(question, args["voltage"], args["resistance"])
        voltage, _ = checked_quantity(args["voltage"], question, ("V",))
        resistance, unit = checked_quantity(args["resistance"], question, ("ohm", "kohm", "Mohm"))
        return {"status": "calculated", "calculation": calculate_current(voltage, resistance, unit)}
    if action == "energy" and set(args) == {"power", "duration"}:
        require_same_subject(question, args["power"], args["duration"])
        power, _ = checked_quantity(args["power"], question, ("W",))
        duration, unit = checked_quantity(args["duration"], question, ("s", "min", "h"))
        return {"status": "calculated", "calculation": calculate_energy(power, duration, unit)}
    raise ValueError("未知操作或缺少/多出参数，不执行模型提供的代码或表达式")


def make_payload(model, question):
    return {
        "model": model,
        "messages": [{"role": "system", "content": EXTRACT_PROMPT}, {"role": "user", "content": question}],
        "temperature": 0, "max_tokens": 512, "stream": False, "cache_prompt": False,
        "chat_template_kwargs": {"enable_thinking": False},
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "circuit_plan", "strict": True, "schema": plan_schema(),
        }},
    }


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("模型JSON含重复字段")
        result[key] = value
    return result


def process_response(response, question):
    plan = None
    try:
        choice = response["choices"][0]
        if choice.get("finish_reason") != "stop":
            raise ValueError("模型输出未正常结束，拒绝执行不完整参数")
        plan = json.loads(choice["message"]["content"], object_pairs_hook=unique_object)
        outcome = dispatch(plan, question)
    except (ValueError, TypeError, KeyError, IndexError) as error:
        outcome = {"status": "rejected", "message": str(error)}
    return plan, outcome


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base_url")
    parser.add_argument("--model", default="qwen-local-q4")
    parser.add_argument("--question", help="省略时在终端输入")
    parser.add_argument("--debug", action="store_true", help="显示未经验证的模型原始参数及备注")
    args = parser.parse_args()
    question = args.question if args.question is not None else input("请输入你的问题：")
    if not question.strip():
        parser.error("问题不能为空")
    payload = make_payload(args.model, question)
    response, elapsed = None, None
    try:
        response, elapsed = ask_model(payload, args.base_url.rstrip("/") + "/v1/chat/completions")
        plan, outcome = process_response(response, question)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        plan = None
        outcome = {"status": "request_error", "message": "无法完成模型请求，请检查服务地址、模型别名及服务日志。", "detail": str(error)}
    if args.debug:
        print("模型原始提取（未经验证，不作为计算答案）：")
        print(json.dumps(plan, ensure_ascii=False, indent=2))
    print("程序处理结果：")
    print(json.dumps(outcome, ensure_ascii=False, indent=2))
    if outcome["status"] == "calculated":
        calculation = outcome["calculation"]
        if calculation["operation"] == "current":
            print(f"根据提取参数计算：I = {Decimal(calculation['result']['mA']):g} mA")
        else:
            print(f"根据提取参数计算：E = {Decimal(calculation['result']['J']):g} J")
    print("引用匹配不保证题意理解正确，请核对模型提取的参数。")
    output_dir = Path(__file__).resolve().parent / "evaluations"
    output_dir.mkdir(exist_ok=True)
    path = output_dir / f"calculator_{datetime.now():%Y%m%d_%H%M%S_%f}.json"
    with path.open("x", encoding="utf-8") as file:
        json.dump({"request": payload, "response": response, "plan": plan,
                   "outcome": outcome, "elapsed_seconds": elapsed,
                   "client_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},
                  file, ensure_ascii=False, indent=2)
    print(f"记录已保存：{path}")


if __name__ == "__main__":
    main()
