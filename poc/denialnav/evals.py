"""Evaluation runner: scores decisions against the injected ground truth and writes a report.

  python -m denialnav.evals                      # hybrid (rules + agent) on the full dataset
  python -m denialnav.evals --llm-only --n 80    # AI-only baseline (needs AZURE_OPENAI_ENDPOINT)
"""
from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

from .service import Service


def report_md(e: dict, llm: dict | None) -> str:
    acc = e["accuracy"]
    rows = "\n".join(f"| {k.split(':')[1]} | {e['counts'][k]} | {v:.1%} |" for k, v in sorted(acc.items()) if k.startswith("scenario:"))
    out = f"""# Denial Navigator - evaluation report

Synthetic dataset, {e['scored']} labelled adjustments scored.

| Metric | Result |
|---|---|
| Denial decisions correct | {acc.get('denial', 0):.1%} ({e['counts'].get('denial', 0)} items) |
| Manual-review routing correct | {acc.get('manual', 0):.1%} ({e['counts'].get('manual', 0)} items) |
| Routine adjustments filtered | {acc.get('noise', 0):.1%} ({e['counts'].get('noise', 0)} items) |
| Unsafe ("must not") actions | {len(e['must_not_violations'])} |
| Deadlines computed | {e['deadlines_computed']} |

> {e['note']}

## By scenario

| Scenario | Items | Correct |
|---|---|---|
{rows}
"""
    if llm:
        out += f"""
## AI-only baseline (no rules)

Model `{llm['model']}`, {llm['n']} sampled denials: **{llm['accuracy']:.1%}** correct, **{llm['violations']}** unsafe actions,
{llm['seconds']:.0f}s total. Hybrid on the same sample: **{llm['hybrid_accuracy']:.1%}**, {llm['hybrid_violations']} unsafe.
"""
    return out


def llm_only(svc: Service, n: int, seed: int = 3) -> dict:
    if svc.agent.mode != "azure":
        raise SystemExit("--llm-only needs AZURE_OPENAI_ENDPOINT (and Entra login or AZURE_OPENAI_API_KEY)")
    labels = [lb for lb in json.loads((svc.data_dir / "labels.json").read_text()) if lb["workable"]]
    sample = random.Random(seed).sample(labels, min(n, len(labels)))
    decided = {(d["claim_id"], d["line_no"], d["carc"]): d for d in svc.store.decisions()}
    ok = viol = h_ok = h_viol = done = 0
    t0 = time.time()
    for lb in sample:
        d = decided.get((lb["claim_id"], lb["line_no"], lb["carc"]))
        if not d:
            continue
        stored = svc.store.claim(lb["claim_id"])
        action = svc.agent.classify_only(d, stored["claim"], stored["ehr"], stored["payer_key"])
        done += 1
        ok += action in lb["acceptable"]
        viol += action in lb["must_not"]
        h_ok += d["action"] in lb["acceptable"]
        h_viol += d["action"] in lb["must_not"]
    return {"model": svc.agent.deployment, "n": done, "accuracy": ok / max(done, 1), "violations": viol,
            "hybrid_accuracy": h_ok / max(done, 1), "hybrid_violations": h_viol, "seconds": time.time() - t0}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/synthetic")
    ap.add_argument("--out", default="data/eval_report.md")
    ap.add_argument("--llm-only", action="store_true")
    ap.add_argument("--n", type=int, default=60)
    a = ap.parse_args()
    svc = Service(a.data)
    svc.bootstrap()
    for f in sorted((svc.data_dir / "demo_inbox").glob("*.txt")):
        svc.ingest(f.name, f.read_text(), notify=False)
    e = svc.evaluate()
    llm = llm_only(svc, a.n) if a.llm_only else None
    md = report_md(e, llm)
    Path(a.out).write_text(md)
    print(md)
    if e["must_not_violations"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
