measurements = [
    (128, 22831.41),
    (512, 32198.81),
    (2048, 29020.28),
]

for tokens, speed in measurements:
    time_ms = tokens / speed * 1000
    print(f"输入 {tokens} token，估算处理时间 {time_ms:.2f} ms")