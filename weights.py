params = 600_000_000

for bits in [32, 16, 8, 4]:
    size_gb = params * bits / 8 / 1_000_000_000
    print(f"{bits} bit：权重理论大小 {size_gb:.2f} GB")