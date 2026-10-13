"""Controlled test: does a last-round backstab survive against diverse opponents?

The stratified finals (fields A-D) showed that when the field is diverse, weak
paradigms get wiped out while the R family tops the table. That makes field A the
right arena to test the last-round defection, which measured as a free +0.1 per
turn in two-player duels: against cooperative opponents it simply collects the
last round.

The design holds everything fixed except one slot. Four fields share the *same*
six diverse opponents and the same two fillers; only the seventh slot changes:

    R1-1        the control
    BS1+R1-1    backstab the final turn
    BS2+R1-1    backstab the final two turns
    BS3+R1-1    backstab the final three turns

Any difference in the challenger's share is therefore attributable to the
backstab, not to who it had to beat. The ecosystem's absolute average fitness is
reported alongside, because a backstab that raises its own score while lowering
everyone else's is a transfer, not an improvement.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dashboard.strategy_detail import parse_strategy_detail  # noqa: E402
from evolution_archive import build_analysis  # noqa: E402
from trust_evolution_simulation import TOTAL_CAPACITY, TrustEvolution  # noqa: E402

FILLERS = ["S0", "SM"]
FILLER_SEATS = 13
# Field A's diverse backdrop, unchanged in every run.
BACKDROP = ["P1-1", "B1-3", "K1-2", "H2-1", "RC1-1", "F1-1+RC1-1"]
CHALLENGERS = ["R1-1", "BS1+R1-1", "BS2+R1-1", "BS3+R1-1"]
LADDERS = [
    ("高起始 [6,8,10,12,14,17,21]", [6, 8, 10, 12, 14, 17, 21], 12),
    ("低起始 [4,5,6,7,8,9,11]", [4, 5, 6, 7, 8, 9, 11], 16),
]


def decode(encoding: str) -> list[str]:
    out = []
    for slot, name, text in parse_strategy_detail(encoding):
        out.append("[{}] {} {}".format(slot, name, text))
    return out


def show_rosters():
    print("=== 实验设计：多样对手固定，只换挑战者 ===")
    print()
    print("共同对手（6 个，每个范式一个，来自上一轮 A 组）：")
    for encoding in BACKDROP:
        entries = decode(encoding)
        print("  {:<16} {}".format(encoding, entries[0].split("] ", 1)[-1][:46]))
    print("  {:<16} {}".format("S0 (填充)", decode("S0")[0].split("] ", 1)[-1][:46]))
    print("  {:<16} {}".format("SM (填充)", decode("SM")[0].split("] ", 1)[-1][:46]))
    print()
    print("四个挑战者槽位：")
    for encoding in CHALLENGERS:
        entries = decode(encoding)
        summary = "  +  ".join(e.split("] ", 1)[-1][:40] for e in entries)
        print("  {:<16} {}".format(encoding, summary))
    print()


def run_one(challenger, ladder, filler_seats, seed, generations):
    members = [challenger] + BACKDROP + list(FILLERS)
    candidates = [e for e in members if e not in FILLERS]
    rotation = seed % len(ladder)
    sizes = {}
    for position, encoding in enumerate(candidates):
        sizes[encoding] = ladder[(position + rotation) % len(ladder)]
    for encoding in FILLERS:
        sizes[encoding] = filler_seats
    shortfall = TOTAL_CAPACITY - sum(sizes.values())
    if shortfall:
        sizes[candidates[-1]] += shortfall

    sim = TrustEvolution(seed=seed, initial_encodings=list(members),
                         initial_sizes=sizes)
    sim.run(generations)
    analysis = build_analysis(sim)

    index = {e: i for i, e in enumerate(analysis["encodings"])}
    matrix = analysis["population_matrix"]
    window = max(1, len(matrix) // 2)
    shares = {e: [] for e in members}
    for row in matrix[window:]:
        total = sum(row) or 1
        for encoding in members:
            position = index.get(encoding)
            shares[encoding].append(row[position] / total if position is not None else 0.0)

    extinct = {r["encoding"]: r["extinction_generation"] for r in analysis["lineages"]}
    ever_top = {r["dominant"] for r in analysis["derived"]["dominance"]}
    summary = analysis["generation_summary"]
    diversity = analysis["derived"]["diversity"]
    half = len(matrix) // 2
    welfare = statistics.fmean(r["average_fitness"] for r in summary[half:])
    shannon = statistics.fmean(r["shannon"] for r in diversity[half:])

    per = {}
    for encoding in members:
        series = shares[encoding]
        per[encoding] = (
            statistics.fmean(series) if series else 0.0,
            series[-1] if series else 0.0,
            int(extinct.get(encoding) is None),
            int(encoding in ever_top),
        )
    return per, welfare, shannon


def _job(task):
    challenger, ladder, filler_seats, seed, generations = task
    return challenger, run_one(challenger, ladder, filler_seats, seed, generations)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=40)
    parser.add_argument("--generations", type=int, default=250)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--out", default=str(ROOT / "reports" / "backstab_experiment.json"))
    args = parser.parse_args()

    show_rosters()

    tasks = []
    for challenger in CHALLENGERS:
        for _, ladder, filler_seats in LADDERS:
            for index in range(args.seeds):
                seed = 40_000 + len(tasks) * 5 + 3
                tasks.append((challenger, ladder, filler_seats, seed, args.generations))
    print("共 {} 次演化（{} 挑战者 × {} 阶梯 × {} seed）".format(
        len(tasks), len(CHALLENGERS), len(LADDERS), args.seeds))
    print()

    context = mp.get_context("spawn")
    tally = {c: {"per": {}, "welfare": [], "shannon": []} for c in CHALLENGERS}
    t0 = time.time()
    done = 0
    with context.Pool(processes=args.workers) as handle:
        for challenger, (per, welfare, shannon) in handle.imap_unordered(_job, tasks):
            bucket = tally[challenger]
            for encoding, (share, final, alive, top) in per.items():
                slot = bucket["per"].setdefault(
                    encoding, {"share": [], "final": [], "alive": 0, "top": 0})
                slot["share"].append(share)
                slot["final"].append(final)
                slot["alive"] += alive
                slot["top"] += top
            bucket["welfare"].append(welfare)
            bucket["shannon"].append(shannon)
            done += 1
            if done % 20 == 0 or done == len(tasks):
                rate = done / max(time.time() - t0, 1e-9)
                print("  {}/{} 完成　已用 {:.0f}s　预计剩余 {:.0f}s".format(
                    done, len(tasks), time.time() - t0,
                    (len(tasks) - done) / rate if rate else 0))

    print()
    print("=== 挑战者表现（对手完全相同，只换它自己）===")
    header = "{:<14}{:>9}{:>9}{:>8}{:>8}{:>10}{:>9}".format(
        "挑战者", "平均份额", "终局份额", "存活率", "夺冠率", "最差seed", "生态适应度")
    print(header)
    print("-" * len(header.encode("gbk", "ignore") + b""))
    report = {}
    for challenger in CHALLENGERS:
        slot = tally[challenger]["per"][challenger]
        runs = max(len(slot["share"]), 1)
        row = {
            "encoding": challenger,
            "mean_share": round(statistics.fmean(slot["share"]), 5),
            "mean_final": round(statistics.fmean(slot["final"]), 5),
            "survival": round(slot["alive"] / runs, 3),
            "dominance": round(slot["top"] / runs, 3),
            "worst_share": round(min(slot["share"]), 5),
            "welfare": round(statistics.fmean(tally[challenger]["welfare"]), 4),
            "shannon": round(statistics.fmean(tally[challenger]["shannon"]), 4),
        }
        report[challenger] = row
        print("{:<14}{:>9.4f}{:>9.4f}{:>8.0%}{:>8.0%}{:>10.4f}{:>9.4f}".format(
            challenger, row["mean_share"], row["mean_final"], row["survival"],
            row["dominance"], row["worst_share"], row["welfare"]))

    control = report["R1-1"]
    print()
    print("=== 相对基线 R1-1 的增益 ===")
    for challenger in CHALLENGERS[1:]:
        row = report[challenger]
        print("  {:<12} 份额 {:+.4f}（{:.1%}）　存活率 {:+.0%}　夺冠率 {:+.0%}　"
              "生态适应度 {:+.4f}".format(
                  challenger,
                  row["mean_share"] - control["mean_share"],
                  (row["mean_share"] - control["mean_share"]) / control["mean_share"],
                  row["survival"] - control["survival"],
                  row["dominance"] - control["dominance"],
                  row["welfare"] - control["welfare"]))

    Path(args.out).write_text(json.dumps(
        {"seeds": args.seeds, "generations": args.generations,
         "backdrop": BACKDROP, "fillers": FILLERS, "rows": report},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("结果已存 {}".format(args.out))


if __name__ == "__main__":
    main()
