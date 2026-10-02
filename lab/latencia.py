"""Battery 3 aggregation. The chapter mandates pandas, not percentile_cont."""
import sys
import pandas as pd

df = pd.read_csv(sys.argv[1])
lat = df["latencia_ms"]
print(f"n={len(lat)}")
print(f"media_ms={lat.mean():.3f}")
print(f"p50_ms={lat.quantile(0.50):.3f}")
print(f"p95_ms={lat.quantile(0.95):.3f}")
print(f"p99_ms={lat.quantile(0.99):.3f}")
print(f"min_ms={lat.min():.3f}")
print(f"max_ms={lat.max():.3f}")
print(f"negativos={int((lat < 0).sum())}")
