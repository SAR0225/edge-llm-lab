"""Generate the small, data-only SVG used in README.

The values are the summarized measurements recorded in 实验记录_量化对比.md.
No model files or raw logs are required.
"""

from pathlib import Path


OUT = Path(__file__).resolve().parent / "docs" / "figures" / "performance_summary.svg"


def esc(value):
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(x, y, value, size=16, anchor="start", weight="400", fill="#172033"):
    return (
        f'<text x="{x}" y="{y}" font-family="Segoe UI,Arial,sans-serif" '
        f'font-size="{size}px" text-anchor="{anchor}" font-weight="{weight}" fill="{fill}">{esc(value)}</text>'
    )


def panel(x, y, width, height, title):
    return (
        f'<rect x="{x}" y="{y}" width="{width}" height="{height}" rx="14" fill="#ffffff" stroke="#dbe3ef"/>'
        + text(x + 22, y + 34, title, 18, weight="700")
    )


def bar_chart(x, y, width, height, labels, values, colors, suffix=""):
    result = []
    top = y + 55
    bottom = y + height - 45
    baseline = bottom
    max_value = max(values) * 1.18
    result.append(f'<line x1="{x + 35}" y1="{baseline}" x2="{x + width - 22}" y2="{baseline}" stroke="#94a3b8"/>')
    slot = (width - 78) / len(values)
    bar_width = slot * 0.52
    for index, (label, value, color) in enumerate(zip(labels, values, colors)):
        bx = x + 48 + slot * index + (slot - bar_width) / 2
        bh = (bottom - top) * value / max_value
        by = bottom - bh
        result.append(f'<rect x="{bx:.1f}" y="{by:.1f}" width="{bar_width:.1f}" height="{bh:.1f}" rx="6" fill="{color}"/>')
        result.append(text(bx + bar_width / 2, by - 8, f"{value:g}{suffix}", 13, "middle", "700"))
        result.append(text(bx + bar_width / 2, bottom + 25, label, 13, "middle"))
    return "".join(result)


def line_chart(x, y, width, height, labels, values, colors):
    result = []
    top = y + 55
    bottom = y + height - 48
    left = x + 48
    right = x + width - 24
    max_value = 340
    result.append(f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#94a3b8"/>')
    result.append(f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="#94a3b8"/>')
    for tick in (0, 100, 200, 300):
        ty = bottom - (bottom - top) * tick / max_value
        result.append(f'<line x1="{left}" y1="{ty:.1f}" x2="{right}" y2="{ty:.1f}" stroke="#e8edf5"/>')
        result.append(text(left - 10, ty + 5, str(tick), 11, "end", fill="#64748b"))
    points = []
    for i, (label, value, color) in enumerate(zip(labels, values, colors)):
        px = left + (right - left) * i / (len(values) - 1)
        py = bottom - (bottom - top) * value / max_value
        points.append((px, py))
        result.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="6" fill="{color}" stroke="#ffffff" stroke-width="3"/>')
        result.append(text(px, py - 12, f"{value:g}", 12, "middle", "700"))
        result.append(text(px, bottom + 25, label, 13, "middle"))
    result.insert(1, f'<polyline points="{" ".join(f"{px:.1f},{py:.1f}" for px, py in points)}" fill="none" stroke="#e85d75" stroke-width="4"/>')
    result.append(text(left, top - 14, "first-content latency (ms)", 12, fill="#64748b"))
    return "".join(result)


def main():
    OUT.parent.mkdir(parents=True, exist_ok=True)
    width, height = 1200, 735
    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#f6f8fc"/>',
        text(40, 48, "Edge LLM inference lab — measured trade-offs", 26, weight="700"),
        text(40, 76, "Qwen3-0.6B · llama.cpp · RTX 5070 Ti Laptop GPU · values from the reproducible lab log", 14, fill="#64748b"),
        panel(35, 105, 355, 275, "Quantization: smaller weights"),
        bar_chart(35, 105, 355, 275, ["Q8_0", "Q4_0"], [767.44, 447.35], ["#4f7cff", "#8a5cf6"], " MiB"),
        text(57, 356, "Q4 is 41.7% smaller than the same-source Q8 file.", 12, fill="#475569"),
        panel(422, 105, 355, 275, "Generation benchmark"),
        bar_chart(422, 105, 355, 275, ["Q8_0", "Q4_0"], [475.21, 585.22], ["#4f7cff", "#8a5cf6"], " t/s"),
        text(444, 356, "Q4 tg128 was 23.2% faster in this run.", 12, fill="#475569"),
        panel(809, 105, 355, 275, "Sustained arrival rate"),
        line_chart(809, 105, 355, 275, ["2/s", "4/s", "8/s"], [15.18, 16.35, 297.28], ["#29a36a", "#29a36a", "#e85d75"]),
        text(831, 356, "8/s crossed the 200 ms interaction target.", 12, fill="#475569"),
        panel(35, 420, 1129, 270, "Concurrency: latency versus waiting"),
        text(60, 472, "One long + one short request; median first-content latency", 15, fill="#475569"),
        text(60, 512, "parallel=1", 15, weight="700", fill="#e85d75"),
        text(222, 512, "2851.93 ms", 15, weight="700", fill="#e85d75"),
        f'<rect x="60" y="528" width="{min(1000, 2851.93 / 3.1):.1f}" height="28" rx="8" fill="#e85d75"/>',
        text(60, 602, "parallel=2", 15, weight="700", fill="#29a36a"),
        text(222, 602, "22.91 ms", 15, weight="700", fill="#29a36a"),
        '<rect x="60" y="618" width="22.91" height="28" rx="8" fill="#29a36a"/>',
        text(60, 675, "Two slots removed the long-request queue wait in this controlled comparison; shared GPU compute still needs measurement.", 13, fill="#475569"),
        '</svg>',
    ]
    OUT.write_text("".join(svg), encoding="utf-8")
    print(OUT)


if __name__ == "__main__":
    main()
