"""Evaluate the reply classifier against a hand-labeled set.

Usage (from backend/):
    .venv/Scripts/python evals/run_classifier_eval.py
    .venv/Scripts/python evals/run_classifier_eval.py --repeat 3   # measure variance

Reports overall accuracy, per-label precision/recall, and a confusion matrix so the
dominant failure mode is visible rather than guessed at.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from app.services.classify import LABELS, classify_reply  # noqa: E402

CASES_FILE = Path(__file__).parent / "reply_classifier_cases.json"
ORDER = ["interview_request", "recruiter_reply", "rejection", "other"]


def run_once(cases: list[dict]) -> list[tuple[dict, str]]:
    results = []
    for i, case in enumerate(cases, 1):
        pred = classify_reply(case["from"], case["text"])["label"]
        results.append((case, pred))
        mark = "ok " if pred == case["label"] else "MISS"
        print(f"  [{i:2}/{len(cases)}] {mark} gold={case['label']:18} pred={pred}")
    return results


def report(results: list[tuple[dict, str]]) -> float:
    total = len(results)
    correct = sum(1 for c, p in results if c["label"] == p)
    acc = correct / total if total else 0.0

    confusion: dict[str, Counter] = defaultdict(Counter)
    for case, pred in results:
        confusion[case["label"]][pred] += 1

    print(f"\nAccuracy: {correct}/{total} = {acc:.1%}\n")

    width = max(len(x) for x in ORDER) + 2
    print("Confusion matrix (rows = gold, cols = predicted):")
    print(" " * width + "".join(f"{c[:12]:>14}" for c in ORDER))
    for gold in ORDER:
        row = "".join(f"{confusion[gold][p]:>14}" for p in ORDER)
        print(f"{gold:<{width}}{row}")

    print("\nPer-label precision / recall:")
    for label in ORDER:
        tp = confusion[label][label]
        gold_n = sum(confusion[label].values())
        pred_n = sum(confusion[g][label] for g in ORDER)
        prec = tp / pred_n if pred_n else 0.0
        rec = tp / gold_n if gold_n else 0.0
        print(f"  {label:<20} P={prec:5.1%}  R={rec:5.1%}  (n={gold_n})")

    misses = [(c, p) for c, p in results if c["label"] != p]
    if misses:
        print(f"\nMisclassifications ({len(misses)}):")
        for case, pred in misses:
            print(f"  #{case['id']} gold={case['label']} -> pred={pred}")
            print(f"      {case['text'][:100]}...")
    return acc


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repeat", type=int, default=1, help="runs, to gauge variance")
    args = ap.parse_args()

    cases = [c for c in json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"] if "label" in c]
    bad = [c for c in cases if c["label"] not in LABELS]
    if bad:
        raise SystemExit(f"Bad gold labels in eval set: {[c['id'] for c in bad]}")

    print(f"Evaluating classifier on {len(cases)} hand-labeled cases "
          f"({args.repeat} run{'s' if args.repeat > 1 else ''})\n")

    accs = []
    for run in range(1, args.repeat + 1):
        if args.repeat > 1:
            print(f"--- run {run} ---")
        accs.append(report(run_once(cases)))

    if args.repeat > 1:
        print(f"\nAcross {args.repeat} runs: mean={sum(accs)/len(accs):.1%} "
              f"min={min(accs):.1%} max={max(accs):.1%}")


if __name__ == "__main__":
    main()
