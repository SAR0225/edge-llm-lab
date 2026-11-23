"""离线验证：运算、参数引用、单位边界、拒绝路径与已知语义局限。"""

import json
import unittest
from decimal import Decimal

from ask_with_calculator import dispatch, process_response, checked_quantity
from circuit_calculator import calculate_current, calculate_energy, number


def quantity(value, unit, evidence):
    return {"value": value, "unit": unit, "evidence": evidence}


def energy_plan(power="2", duration="3", evidence="3分钟"):
    return {"operation": "energy", "arguments": {
        "power": quantity(power, "W", power + "瓦"),
        "duration": quantity(duration, "min", evidence),
    }, "message": "这个备注不参与计算"}


class CalculatorValidationTests(unittest.TestCase):
    def test_current_with_prefixes(self):
        for voltage, resistance, unit, amps in [
            ("9.4", "4.7", "kohm", "0.002"), ("5", "0.5", "Mohm", "0.00001"),
        ]:
            with self.subTest(unit=unit):
                self.assertEqual(Decimal(calculate_current(voltage, resistance, unit)["result"]["A"]), Decimal(amps))

    def test_exact_energy_and_context_independence(self):
        self.assertEqual(Decimal(calculate_energy("2", "3", "min")["result"]["J"]), 360)
        self.assertEqual(Decimal(calculate_energy("0.25", "2", "min")["result"]["J"]), 30)
        self.assertEqual(Decimal(calculate_energy("0", "0", "h")["result"]["J"]), 0)

    def test_invalid_physical_and_numeric_inputs(self):
        for value in ("NaN", "Infinity", "bad", "1e19", "1e-19", "0." + "1" * 29):
            with self.subTest(value=value), self.assertRaises(ValueError):
                number(value)
        for call in (lambda: calculate_current("2", "0", "ohm"),
                     lambda: calculate_energy("2", "-1", "s")):
            with self.assertRaises(ValueError):
                call()

    def test_model_commentary_does_not_override_energy(self):
        plan = energy_plan()
        plan["message"] = "结果为6焦耳"
        self.assertEqual(Decimal(dispatch(plan, "2瓦工作3分钟")["calculation"]["result"]["J"]), 360)

    def test_invented_time_is_rejected(self):
        with self.assertRaises(ValueError):
            dispatch(energy_plan(), "元件消耗2瓦，求能量")

    def test_wrong_dimension_is_rejected(self):
        with self.assertRaises(ValueError):
            dispatch(energy_plan(evidence="3毫米"), "元件2瓦，外壳3毫米，求能量")

    def test_value_and_source_mismatch(self):
        with self.assertRaises(ValueError):
            dispatch(energy_plan(duration="30"), "元件2瓦工作3分钟")

    def test_numeric_and_unit_substrings_are_rejected(self):
        for item, question, allowed in [
            (quantity("3", "min", "3分钟"), "工作13分钟", ("min",)),
            (quantity("3", "min", "3分"), "工作3分钟", ("min",)),
            (quantity("2", "W", "2瓦"), "功率2瓦特", ("W",)),
            (quantity("3", "s", "3s"), "时间3seconds", ("s",)),
            (quantity("2", "W", "2W"), "功率-2W", ("W",)),
        ]:
            with self.subTest(question=question), self.assertRaises(ValueError):
                checked_quantity(item, question, allowed)

    def test_multiple_time_candidates_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "不唯一"):
            dispatch(energy_plan(), "设备2瓦，本次工作3分钟，上次工作5分钟")

    def test_explicit_cross_device_parameters_are_rejected(self):
        plan = energy_plan(evidence="3分钟")
        plan["arguments"]["power"]["evidence"] = "2瓦"
        question = "设备A消耗2瓦功率，设备B工作3分钟。求设备A消耗的能量。"
        with self.assertRaisesRegex(ValueError, "不同明确对象"):
            dispatch(plan, question)

    def test_same_device_across_clauses_is_allowed(self):
        plan = energy_plan(evidence="3分钟")
        plan["arguments"]["power"]["evidence"] = "2瓦"
        question = "设备A消耗2瓦功率，设备A工作3分钟。"
        self.assertEqual(Decimal(dispatch(plan, question)["calculation"]["result"]["J"]), 360)

    def test_refusal_text_is_not_treated_as_verified(self):
        outcome = dispatch({"operation": "insufficient", "arguments": {}, "message": "缺少质量"}, "元件2瓦，求能量")
        self.assertEqual(outcome["status"], "not_calculated")
        self.assertNotIn("缺少质量", outcome["message"])

    def test_unknown_actions_cannot_execute(self):
        with self.assertRaises(ValueError):
            dispatch({"operation": "eval", "arguments": {"code": "1+1"}, "message": ""}, "测试")

    def test_incomplete_and_malformed_responses_are_rejected(self):
        responses = [
            {}, {"choices": []},
            {"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]},
            {"choices": [{"finish_reason": "stop", "message": {"content": "not JSON"}}]},
            {"choices": [{"finish_reason": "stop", "message": {"content": '{"operation":"energy","operation":"current"}'}}]},
        ]
        for response in responses:
            with self.subTest(response=response):
                self.assertEqual(process_response(response, "问题")[1]["status"], "rejected")

    def test_known_semantic_gap_remains_visible(self):
        # The lightweight guard recognizes named equipment types, not arbitrary aliases.
        question = "甲消耗2瓦，乙运行3分钟，求甲消耗的能量"
        self.assertEqual(dispatch(energy_plan(), question)["status"], "calculated")


if __name__ == "__main__":
    unittest.main()
