import csv

results = [
    ["device", "prompt_tokens_per_second", "generation_tokens_per_second"],
    ["GPU", 393.2, 302.3],
    ["CPU", 409.4, 74.9],
]

with open("results.csv", "w", newline="", encoding="utf-8-sig") as file:
    writer = csv.writer(file)
    writer.writerows(results)

speedup = 302.3 / 74.9
print(f"本次生成速度加速比：{speedup:.2f} 倍")
print("实验结果已保存到 results.csv")