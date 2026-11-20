import csv
from statistics import median

with open("stream_results.csv", encoding="utf-8") as file:
    rows = list(csv.DictReader(file))

first_times = [float(row["first_content_ms"]) for row in rows]
total_times = [float(row["total_ms"]) for row in rows]

print(f"测量次数：{len(rows)}")
print(f"首个正文片段延迟中位数：{median(first_times):.3f} ms")
print(f"请求总耗时中位数：{median(total_times):.3f} ms")
print(f"首个正文片段延迟范围：{min(first_times):.3f}～{max(first_times):.3f} ms")