"""Independent cross-check of costs per project.

Deliberately shares no code with the `whatisworth` package: it reads the
transcripts itself, deduplicates itself and prices with the official
Anthropic table in official_prices.json. It then compares per project folder
with the ledger and, if given, a `ccusage claude session --json` export.

    python3 scripts/verify_projects.py [ccusage-sessions.json]
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRICES = {k: v for k, v in json.loads((HERE / "official_prices.json").read_text()).items() if not k.startswith("_")}
PROJECTS = Path.home() / ".claude" / "projects"
LEDGER = Path.home() / ".local" / "share" / "what-is-worth" / "ledger.sqlite"
FAST = {"claude-opus-5-5", "claude-opus-5", "claude-opus-4-8"}


def price(model: str, u: dict) -> float:
    rates = PRICES[re.sub(r"-\d{8}$", "", model)]
    split = u.get("cache_creation") or {}
    cw = u.get("cache_creation_input_tokens") or 0
    s1h, s5m = split.get("ephemeral_1h_input_tokens") or 0, split.get("ephemeral_5m_input_tokens") or 0
    w1h = min(s1h, cw) if s1h + s5m <= cw else round(cw * s1h / (s1h + s5m))
    w5m = cw - w1h
    inp, out, read = u.get("input_tokens") or 0, u.get("output_tokens") or 0, u.get("cache_read_input_tokens") or 0
    if "above_100k" in rates and inp + read + w5m + w1h > 100_000:
        rates = rates["above_100k"]
    usd = (inp * rates["input"] + out * rates["output"] + read * rates["read"]
           + w5m * rates["write_5m"] + w1h * rates["write_1h"]) / 1e6
    if u.get("speed") == "fast" and re.sub(r"-\d{8}$", "", model) in FAST:
        usd *= 2
    if u.get("inference_geo") not in (None, "", "global", "not_available"):
        usd *= 1.1
    usd += ((u.get("server_tool_use") or {}).get("web_search_requests") or 0) * 0.01
    return usd


def scan() -> dict[str, float]:
    best: dict[str, tuple] = {}  # message id -> (is_main, output, total, project, cost)
    for path in PROJECTS.rglob("*.jsonl"):
        project = path.relative_to(PROJECTS).parts[0]
        with path.open("rb") as handle:
            for line in handle:
                if b'"usage"' not in line or b'"assistant"' not in line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                m = r.get("message") or {}
                u = m.get("usage")
                if r.get("type") != "assistant" or not isinstance(u, dict) or m.get("model") in (None, "", "<synthetic>"):
                    continue
                key = m.get("id") if str(m.get("id", "")).startswith("msg_") else f"{m.get('id')}|{r.get('requestId')}"
                total = sum((u.get(k) or 0) for k in ("input_tokens", "output_tokens",
                            "cache_read_input_tokens", "cache_creation_input_tokens"))
                cand = (not r.get("isSidechain"), u.get("output_tokens") or 0, total, project, price(m["model"], u))
                if key not in best or cand[:3] > best[key][:3]:
                    best[key] = cand
    per_project: dict[str, float] = defaultdict(float)
    for _, _, _, project, cost in best.values():
        per_project[project] += cost
    return per_project


def main() -> None:
    independent = scan()
    db = sqlite3.connect(LEDGER)
    ledger = dict(db.execute("SELECT project_key, SUM(cost_usd) FROM events GROUP BY project_key"))
    ccusage: dict[str, float] = defaultdict(float)
    if len(sys.argv) > 1:
        for s in json.loads(Path(sys.argv[1]).read_text())["sessions"]:
            ccusage[s["projectPath"]] += s["totalCost"]
    projects = sorted(set(independent) | set(ledger) | set(ccusage), key=lambda p: -(ledger.get(p) or 0))
    worst = 0.0
    print(f"{'Projektordner':<58}{'Datenbuch':>12}{'Prüfskript':>12}{'ccusage':>12}{'max Δ':>9}")
    for p in projects:
        a, b, c = ledger.get(p, 0.0), independent.get(p, 0.0), ccusage.get(p, 0.0)
        vals = [a, b] + ([c] if ccusage else [])
        delta = (max(vals) - min(vals)) / max(max(vals), 1e-9) * 100
        worst = max(worst, delta if max(vals) >= 1 else 0)
        flag = "" if delta < 0.01 or max(vals) < 1 else "  <--"
        print(f"{p[:58]:<58}{a:>12.2f}{b:>12.2f}{c:>12.2f}{delta:>8.3f}%{flag}")
    print(f"\nSumme  Datenbuch {sum(ledger.values()):.2f}  Prüfskript {sum(independent.values()):.2f}"
          + (f"  ccusage {sum(ccusage.values()):.2f}" if ccusage else ""))
    print(f"Größte Abweichung bei Projekten ab 1 $: {worst:.3f} %")


if __name__ == "__main__":
    main()
