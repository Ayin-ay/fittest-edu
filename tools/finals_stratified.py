"""Finals round over stratified fields, with welfare as a second axis.

The previous finale was seven near-relatives of the same strategy: 100% of the
field shared one trigger module (R), 6 of 7 shared one default module, and only
one of the seven had three or more modules. The engine's own random generator
produces 95% multi-module strategies and spreads its six trigger kinds evenly.
So that round answered "which R1 variant is best against other R1 variants",
which is a self-fulfilling conclusion: the champion came out of a pool the search
had already biased toward R.

Four fields are run here instead, and the point is comparison *between* fields:

A. trigger stratified -- one strategy per trigger kind (R/P/B/K/H/RC) plus a
   multi-module hybrid, i.e. one representative of every behaviour paradigm the
   engine can express;
B. default stratified -- one strategy per default-slot family (S/F/T/D/AD/W/BS);
C. random baseline    -- seven encodings drawn from the engine's own
   ``random_strategy``, i.e. what a user gets from "random start". If carefully
   constructed strategies cannot beat this, the construction is not earning its
   keep;
D. search champions   -- the leaders the tournament picked, kept as a control so
   the new numbers are comparable with the old round.

Every field is run under two seat ladders (a high-start and a low-start ladder)
across many seeds. Two axes are reported: the usual share/survival ranking, and
the ecosystem's absolute ``average_fitness``. The second axis matters because a
behaviour can raise a strategy's own score while lowering everyone's -- share
alone is blind to that.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import random
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evolution_archive import build_analysis  # noqa: E402
from strategy_engine.strategy_engine import random_strategy  # noqa: E402
from trust_evolution_simulation import TOTAL_CAPACITY, TrustEvolution  # noqa: E402

FILLERS = ["S0", "SM"]
FILLER_SEATS = 13

LADDERS = [
    ("高起始 [6,8,10,12,14,17,21]", [6, 8, 10, 12, 14, 17, 21], 12),
    ("低起始 [4,5,6,7,8,9,11]", [4, 5, 6, 7, 8, 9, 11], 16),
]

FIELDS = {
    "A 触发家族分层": [
        "R1-1",       # 报复
        "P1-1",       # 被剥削即报复
        "B1-3",       # 互殴后求和
        "K1-2",       # 奖赏连续合作
        "H2-1",       # 累计伤害后报复
        "RC1-1",      # 以牙还牙变体
        "F1-1+RC1-1",  # 多模块混合
    ],
    "B 默认槽分层": [
        "S1", "F2-3", "T1-2", "D0", "AD1", "W", "BS3",
    ],
}

RANDOM_SEED = 20261002


def random_field(count: int = 7) -> list[str]:
    """Seven encodings from the engine's own generator, reproducible."""
    rng = random.Random(RANDOM_SEED)
    picked: list[str] = []
    while len(picked) < count:
        code = random_strategy(rng).code
        if code not in picked:
            picked.append(code)
    return picked


def search_champions(path: Path, count: int = 7) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    fillers = data.get("fillers", FILLERS)
    rows = [r["encoding"] for r in data["rows"] if r["encoding"] not in fillers]
    return rows[:count]


def run_one(members, ladder, filler_seats, seed, generations):
    candidates = [e for e in members if e not in FILLERS]
    fillers = [e for e in members if e in FILLERS]
    rotation = seed % len(ladder)
    sizes = {}
    for position, encoding in enumerate(candidates):
        sizes[encoding] = ladder[(position + rotation) % len(ladder)]
    for encoding in fillers:
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
    tail = summary[len(summary) // 2:]
    welfare = statistics.fmean(r["average_fitness"] for r in tail)
    diversity_rows = analysis["derived"]["diversity"][len(analysis["derived"]["diversity"]) // 2:]
    diversity = statistics.fmean(r["shannon"] for r in diversity_rows)

    out = {"per": {}, "welfare": welfare, "diversity": diversity}
    for encoding in members:
        series = shares[encoding]
        out["per"][encoding] = (
            statistics.fmean(series) if series else 0.0,
            series[-1] if series else 0.0,
            int(extinct.get(encoding) is None),
            int(encoding in ever_top),
        )
    return out


def _job(task):
    field_name, members, ladder, filler_seats, seed, generations = task
    return field_name, run_one(members, ladder, filler_seats, seed, generations)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=30)
    parser.add_argument("--generations", type=int, default=250)
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--source",
                        default=str(ROOT / "reports" / "tournament_evolution_v12.json"))
    parser.add_argument("--out",
                        default=str(ROOT / "reports" / "finals_stratified.json"))
    args = parser.parse_args()

    fields = dict(FIELDS)
    fields["C 纯随机基线"] = random_field()
    fields["D 搜索冠军"] = search_champions(Path(args.source))

    for name, members in fields.items():
        print("=== {} ===".format(name))
        for encoding in members:
            print("    " + encoding)
        print()

    tasks = []
    for field_name, members in fields.items():
        group = list(members) + FILLERS
        for _, ladder, filler_seats in LADDERS:
            for index in range(args.seeds):
                seed = 20_000 + len(tasks) * 3 + 1
                tasks.append((field_name, group, ladder, filler_seats,
                              seed, args.generations))

    print("共 {} 次演化（{} 阵容 × {} 阶梯 × {} seed），{} 进程并行".format(
        len(tasks), len(fields), len(LADDERS), args.seeds, args.workers))
    print()

    context = mp.get_context("spawn")
    results = {}
    t0 = time.time()
    done = 0
    with context.Pool(processes=args.workers) as handle:
        for field_name, result in handle.imap_unordered(_job, tasks):
            bucket = results.setdefault(field_name, {"per": {}, "welfare": [],
                                                     "diversity": []})
            for encoding, (share, final, alive, top) in result["per"].items():
                slot = bucket["per"].setdefault(
                    encoding, {"share": [], "final": [], "alive": 0, "top": 0})
                slot["share"].append(share)
                slot["final"].append(final)
                slot["alive"] += alive
                slot["top"] += top
            bucket["welfare"].append(result["welfare"])
            bucket["diversity"].append(result["diversity"])
            done += 1
            if done % 20 == 0 or done == len(tasks):
                rate = done / max(time.time() - t0, 1e-9)
                print("  {}/{} 完成　已用 {:.0f}s　预计剩余 {:.0f}s".format(
                    done, len(tasks), time.time() - t0,
                    (len(tasks) - done) / rate if rate else 0))

    report = {"seeds": args.seeds, "generations": args.generations,
              "ladders": [c[0] for c in LADDERS], "fields": {}}
    for field_name, bucket in results.items():
        rows = []
        for encoding, slot in bucket["per"].items():
            runs = max(len(slot["share"]), 1)
            rows.append({
                "encoding": encoding,
                "mean_share": round(statistics.fmean(slot["share"]), 5),
                "mean_final": round(statistics.fmean(slot["final"]), 5),
                "survival": round(slot["alive"] / runs, 3),
                "dominance": round(slot["top"] / runs, 3),
                "worst_share": round(min(slot["share"]), 5),
                "is_filler": encoding in FILLERS,
            })
        rows.sort(key=lambda r: (-r["survival"], -r["mean_share"]))
        report["fields"][field_name] = {
            "members": [e for e in fields[field_name]],
            "rows": rows,
            "welfare": round(statistics.fmean(bucket["welfare"]), 4),
            "diversity": round(statistics.fmean(bucket["diversity"]), 4),
        }

    print()
    for field_name, data in report["fields"].items():
        print("--- {}　生态适应度 {:.4f}　平均 Shannon {:.3f} ---".format(
            field_name, data["welfare"], data["diversity"]))
        print("  {:<22}{:>8}{:>8}{:>7}{:>7}".format(
            "策略", "平均份额", "终局份额", "存活率", "夺冠率"))
        for row in data["rows"]:
            tag = "  (填充)" if row["is_filler"] else ""
            print("  {:<22}{:>8.4f}{:>8.4f}{:>7.0%}{:>7.0%}{}".format(
                row["encoding"], row["mean_share"], row["mean_final"],
                row["survival"], row["dominance"], tag))
        print()

    print("=== 生态适应度对比（第二根轴：谁让所有人变好/变坏）===")
    for field_name, data in sorted(report["fields"].items(),
                                   key=lambda kv: -kv[1]["welfare"]):
        print("  {:<18} 适应度 {:.4f}　Shannon {:.3f}".format(
            field_name, data["welfare"], data["diversity"]))

    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print()
    print("结果已存 {}".format(args.out))


if __name__ == "__main__":
    main()
