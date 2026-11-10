#!/usr/bin/env python3
"""Parse the 360 model table (user-supplied text copy of the 360 price page) into a price JSON for mswea_import.

    python3 scripts/prices_360.py /root/api-agent-audit-20261107/qihoo360/360model_20261107.txt \
        --usd-per-cny 0.1408 > scripts/prices-360.json

The table repeats: model name, TPM, RPM, input price, output price. Only per-1M-token prices ("¥X / 1M tokens")
are kept. 360 lists no cache price, so cached input is billed at the input price.
"""
import argparse, json, re, sys
PRICE = re.compile(r"^¥\s*([0-9.]+)\s*/\s*1M tokens$")
ap = argparse.ArgumentParser(); ap.add_argument("table"); ap.add_argument("--usd-per-cny", type=float, required=True)
a = ap.parse_args()
lines = [l.strip() for l in open(a.table, encoding="utf-8") if l.strip()]
models = {}
for i in range(len(lines) - 4):
    pin, pout = PRICE.match(lines[i + 3]), PRICE.match(lines[i + 4])
    if pin and pout and re.fullmatch(r"[0-9,]+", lines[i + 1]) and re.fullmatch(r"[0-9,]+", lines[i + 2]):
        models[lines[i]] = {"input_cny_per_m": float(pin.group(1)), "output_cny_per_m": float(pout.group(1))}
json.dump({"source": a.table, "currency": "CNY", "usd_per_cny": a.usd_per_cny,
           "note": "360 list prices per 1M tokens; cached input billed as input; USD = CNY * usd_per_cny",
           "models": models}, sys.stdout, ensure_ascii=False, indent=1)
print(f"{len(models)} models", file=sys.stderr)
