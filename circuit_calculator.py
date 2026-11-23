"""Small deterministic calculator: values and units must be supplied explicitly."""

import argparse
import json
from decimal import Decimal, InvalidOperation, localcontext


RESISTANCE_SCALE = {"ohm": Decimal("1"), "kohm": Decimal("1000"), "Mohm": Decimal("1000000")}
TIME_SCALE = {"s": Decimal("1"), "min": Decimal("60"), "h": Decimal("3600")}


def number(value):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise ValueError("输入必须是有效十进制数字") from error
    if not result.is_finite():
        raise ValueError("输入必须是有限数值")
    if len(result.as_tuple().digits) > 28:
        raise ValueError("输入最多支持28位有效十进制数字")
    # Keep this teaching tool within practical decimal ranges.
    if result and not Decimal("1e-18") <= abs(result) <= Decimal("1e18"):
        raise ValueError("非零数值的绝对值必须在1e-18至1e18之间")
    return result


def calculate_current(voltage_v, resistance, resistance_unit):
    if resistance_unit not in RESISTANCE_SCALE:
        raise ValueError("电阻单位必须是ohm、kohm或Mohm")
    voltage = number(voltage_v)
    with localcontext() as context:
        context.prec = 80
        ohms = number(resistance) * RESISTANCE_SCALE[resistance_unit]
    if ohms <= 0:
        raise ValueError("本工具要求电阻严格大于零")
    with localcontext() as context:
        context.prec = 28
        current = voltage / ohms
        return {
            "operation": "current",
            "formula": "I = U / R",
            "normalized_input": {"voltage_V": str(voltage), "resistance_ohm": str(ohms)},
            "result": {"A": str(current), "mA": str(current * 1000)},
            "precision": "28 significant decimal digits for division; repeating results may be rounded",
        }


def calculate_energy(power_w, duration, time_unit):
    if time_unit not in TIME_SCALE:
        raise ValueError("时间单位必须是s、min或h")
    power = number(power_w)
    with localcontext() as context:
        context.prec = 80
        seconds = number(duration) * TIME_SCALE[time_unit]
    if power < 0 or seconds < 0:
        raise ValueError("本工具计算消耗的电能，功率和时长不能为负")
    with localcontext() as context:
        # Enough precision for exact products within the accepted input range.
        context.prec = 80
        energy = power * seconds
        return {
            "operation": "energy",
            "formula": "E = P * t",
            "normalized_input": {"power_W": str(power), "duration_s": str(seconds)},
            "result": {"J": str(energy)},
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    current = commands.add_parser("current", help="给定伏特电压和电阻，计算电流")
    current.add_argument("--voltage", required=True, help="电压，单位V")
    current.add_argument("--resistance", required=True)
    current.add_argument("--resistance-unit", required=True, choices=RESISTANCE_SCALE)
    energy = commands.add_parser("energy", help="给定恒定功率和时长，计算消耗电能")
    energy.add_argument("--power", required=True, help="功率，单位W")
    energy.add_argument("--duration", required=True)
    energy.add_argument("--time-unit", required=True, choices=TIME_SCALE)
    args = parser.parse_args()
    try:
        if args.operation == "current":
            result = calculate_current(args.voltage, args.resistance, args.resistance_unit)
        else:
            result = calculate_energy(args.power, args.duration, args.time_unit)
    except ValueError as error:
        parser.error(str(error))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
