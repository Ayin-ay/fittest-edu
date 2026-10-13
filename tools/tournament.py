"""Find the strategy with the highest *stable* win rate in The Fittest.

Why not a plain head-to-head tournament
---------------------------------------
The payoff matrix is the classic Axelrod ``(T, R, P, S) = (5, 3, 0, 1)``, which
is **not zero-sum**: mutual cooperation pays 6 in total, mutual defection only
2. Scoring candidates against a fixed opponent pool therefore rewards whoever
exploits cooperators hardest. Measured that way ``SM`` (always defect) tops the
table with 19 wins and 0 losses, purely because short-retaliation opponents
such as ``R1-1`` forgive after a single turn and hand it 5 points per round.
That is an artifact of the metric, not a property worth having.

What "stable win rate" means here
---------------------------------
The simulation's own fitness process is the only measure that matters: a
strategy is good if it can *hold population share against a diverse, evolving
ecosystem*, and good reliably if it does so across many independent seeds. So
candidates compete inside the real engine under real selection pressure, and
they are ranked on

* ``mean_share``     - average population share over the measured window
* ``final_share``    - share at the last generation
* ``survival``       - fraction of seeds where it is still alive at the end
* ``dominance``      - fraction of seeds where it was ever the top species
* ``worst_share``    - its worst single seed (the stability term)

Ranking is by survival first, then mean share, then worst case, so a strategy
that only wins on the easy seeds cannot outrank one that holds up everywhere.

Every candidate in a group starts on the same number of seats, and the groups
share the same filler opponents, so the comparison is not biased by draw order
or by an easy or hostile field.
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evolution_archive import build_analysis, build_rules  # noqa: E402
from strategy_engine.strategy_engine import parse_strategy  # noqa: E402
from trust_evolution_simulation import (  # noqa: E402
    TOTAL_CAPACITY,
    TrustEvolution,
)

# Every group carries the same two reference strategies so the fields stay
# comparable: the pure cooperator and the pure defector bracket the scale.
FILLERS = ["S0", "SM"]
FILLER_SEATS = 13

# Starting-seat ladder. A uniform start makes the experiment useless: with
# EXTINCTION_SIZE = 3 nobody is ever culled, and with MUTATION_MIN_SIZE = 10 a
# species needs *more* than 10 seats to mutate, so a flat 10-seat start traps
# every strategy in a pure allocation game with no culling and no innovation.
# The ladder guarantees both pressures exist. The assignment is rotated per seed
# (see run_group) so no candidate is systematically given the smallest start.
SEAT_LADDER = [4, 6, 8, 10, 12, 14, 20]


def merge_equivalent(pool: list[str], equivalence_json: str) -> list[str]:
    """Keep one representative per behaviour class.

    Half of the raw candidate pool is aliases -- ``R1-3`` and ``R1-3+M2`` play
    identically, so a field containing both is spending two of its seven slots
    on the same strategy and diluting every other contestant. Collapsing them
    first makes each group a genuinely distinct field. Ranking by behaviour
    rather than by spelling is the point, so this is on by default for a rerun
    after the engine changed.
    """
    path = Path(equivalence_json)
    if not path.exists():
        print("[注意] 未找到 {}，跳过等价归并".format(path.name))
        return pool
    data = json.loads(path.read_text(encoding="utf-8"))
    keeper_of: dict[str, str] = {}
    for members in data["classes"]:
        representative = members[0]
        for member in members:
            keeper_of[member] = representative
    kept: list[str] = []
    for encoding in pool:
        representative = keeper_of.get(encoding, encoding)
        if representative not in kept:
            kept.append(representative)
    dropped = len(pool) - len(kept)
    print("等价归并：{} -> {}（合并掉 {} 个别名编码）".format(
        len(pool), len(kept), dropped))
    return kept


def cross_layer_pool() -> list[str]:
    """Full sweep over combinations *across* the encoding's slots.

    Earlier pools swept one layer at a time -- the ``R`` family got the densest
    grid, and default-slot modules were only ever combined with modifiers. That
    missed whole regions, most importantly ``BS{N}`` (defect the final turns)
    paired with a retaliatory trigger, which measured as the single largest
    effect in the whole study: +129% to +212% share. A layer-by-layer sweep
    cannot find those, so the pool is now generated as a product over the slots.

    Size is kept tractable by taking a full product over defaults x triggers for
    the defaults most likely to matter, and a trigger x modifier product for the
    rest, rather than a blind three-way cross of ~3200 candidates.
    """
    pool: list[str] = []

    defaults = [
        "S0", "S1", "S2", "S3", "F1-1", "F1-2", "F2-3", "F3-1",
        "T1-1", "T1-2", "T2-1", "D0", "D1", "D2", "AD0", "AD1",
        "W", "BS1", "BS2", "BS3",
    ]
    triggers = [
        "R1-1", "R1-2", "R1-3", "R1-M", "R2-2", "R3-3",
        "P1-1", "P2-1", "P2-2", "H2-1", "H2-M", "H3-2",
        "B1-2", "B1-3", "B1-M", "K1-2", "K1-3", "K2-2", "RC1-1", "RC1-2", "RC1-M",
    ]
    modifiers = ["", "+M1", "+M2", "+M3", "+C2", "+C4-C", "+C4-D",
                 "+RPT1-1", "+RPT1-M", "+RPT2-M"]

    # Layer 1: bare defaults, so every default family is represented.
    pool.extend(defaults)

    # Layer 2: every default x every trigger (the cross that was missing).
    for default in defaults:
        for trigger in triggers:
            pool.append(default + "+" + trigger)

    # Layer 3: every default x a rotating subset of modifiers, to reach three and
    # four module encodings without a 2000-candidate pool.
    for index, default in enumerate(defaults):
        for offset, modifier in enumerate(modifiers):
            if not modifier:
                continue
            if (index + offset) % 3 == 0:
                pool.append(default + modifier)

    # Layer 4: three-module shapes on the most promising defaults x triggers.
    strong_defaults = ["S0", "S1", "F1-1", "D0", "W", "BS1", "BS3"]
    strong_triggers = ["R1-1", "R1-2", "R1-M", "P1-1", "RC1-1", "K1-2"]
    for default in strong_defaults:
        for trigger in strong_triggers:
            for modifier in ("+RPT1-1", "+C2", "+M2", ""):
                pool.append(default + "+" + trigger + modifier)

    seen: list[str] = []
    for enc in pool:
        if enc in seen or enc in FILLERS:
            continue
        try:
            parse_strategy(enc)
        except Exception:  # noqa: BLE001
            continue
        seen.append(enc)
    return seen


def candidate_pool() -> list[str]:
    """Systematic sweep of the encoding space, not a hand-picked shortlist.

    Layered by the four slots the format allows (default / trigger / trigger /
    modifier), so the search covers whole families instead of the shapes that
    happened to be worth trying first. The earlier narrower sweep found the
    whole ``R`` family dominating, which is exactly the kind of result that
    should be re-checked against a wider net before being believed.
    """
    pool: list[str] = []

    # Layer 1: retaliation family (trigger threshold x length x modifier).
    # This is the family that won the first pass, so it gets the densest grid.
    for a in (1, 2, 3):
        for b in ("1", "2", "3", "M"):
            base = "R{}-{}".format(a, b)
            pool.append(base)
            for mod in ("M1", "M2", "M3", "C2", "C4-C", "C4-D",
                        "RPT1-1", "RPT1-M", "RPT2-M"):
                pool.append(base + "+" + mod)

    # Layer 2: other responsive triggers, each with the modifiers that plausibly
    # interact with them.
    for base in ("P1-1", "P2-1", "P2-2", "P3-1",
                 "H2-1", "H3-2", "H2-M",
                 "B1-2", "B1-3", "B1-M",
                 "K1-2", "K1-3", "K2-2", "K1-M",
                 "RC1-1", "RC1-2", "RC1-M"):
        pool.append(base)
        for mod in ("RPT1-1", "M2", "C2"):
            pool.append(base + "+" + mod)

    # Layer 3: default-slot families on their own, and with forgiveness.
    for base in ("S0", "S1", "S2", "S3", "F1-1", "F1-2", "F2-3", "F3-1",
                 "T1-1", "T1-2", "T2-1", "D0", "D1", "D2", "AD0", "AD1",
                 "W", "BS1", "BS2", "BS3"):
        pool.append(base)
        for mod in ("RPT1-1", "M2", "C2"):
            pool.append(base + "+" + mod)

    # Layer 4: hybrids, i.e. a non-retaliating default plus a trigger.
    for base in ("F1-1+RC1-1", "F1-1+P1-1", "F2-3+RC1-1", "F1-1+K1-2",
                 "S1+P1-1", "S1+K1-2", "S1+B1-2", "T1-1+RPT1-1",
                 "F1-1+RC1-M", "D0+R1-1", "D0+K1-2", "AD1+K1-2"):
        pool.append(base)
        for mod in ("RPT1-1", "RPT1-M", "M2", "C2"):
            pool.append(base + "+" + mod)

    # Layer 5: three-module shapes built from the strongest two-module parents.
    for first in ("R1-2", "R1-M", "R1-1", "R2-2"):
        for extra in ("+M2+RPT1-1", "+M2+RPT1-M", "+C2+RPT1-1",
                      "+M3+RPT1-M", "+RC1-1+RPT1-1"):
            pool.append(first + extra)

    seen: list[str] = []
    for enc in pool:
        # Fillers appear in every group, so they must not also compete as
        # candidates or their per-group tallies would be incomparable.
        if enc in seen or enc in FILLERS:
            continue
        try:
            parse_strategy(enc)
        except Exception:  # noqa: BLE001
            continue
        seen.append(enc)
    return seen


def make_groups(candidates: list[str], group_size: int) -> list[list[str]]:
    """Split candidates into comparable fields, each carrying the fillers."""
    width = min(group_size, len(SEAT_LADDER))
    return [
        candidates[i:i + width] + list(FILLERS)
        for i in range(0, len(candidates), width)
        if candidates[i:i + width]
    ]


def run_group(group: list[str], seed: int, generations: int) -> dict[str, dict]:
    """One simulation of ``group`` under a rotated, unequal starting field.

    The seat ladder is rotated by the seed so that across the seed sweep every
    candidate receives every rung of the ladder equally often. Without that
    counterbalancing whoever sits at the bottom of the ladder is penalised for
    its slot rather than for its behaviour.

    All metrics are read back through ``evolution_archive.build_analysis`` --
    the same analysis view the dashboard and the AI skill consume -- so the
    ranking can never disagree with what a saved run actually shows.
    """
    candidates = [enc for enc in group if enc not in FILLERS]
    fillers = [enc for enc in group if enc in FILLERS]
    rotation = seed % len(SEAT_LADDER)

    sizes: dict[str, int] = {}
    for position, enc in enumerate(candidates):
        sizes[enc] = SEAT_LADDER[(position + rotation) % len(SEAT_LADDER)]
    for enc in fillers:
        sizes[enc] = FILLER_SEATS

    shortfall = TOTAL_CAPACITY - sum(sizes.values())
    if shortfall:  # only when the ladder leaves the field slightly short
        sizes[candidates[-1]] += shortfall

    sim = TrustEvolution(seed=seed, initial_encodings=list(group), initial_sizes=sizes)
    sim.run(generations)
    analysis = build_analysis(sim)

    encodings = analysis["encodings"]
    index = {enc: position for position, enc in enumerate(encodings)}
    matrix = analysis["population_matrix"]
    window = max(1, len(matrix) // 2)

    shares: dict[str, list[float]] = {enc: [] for enc in group}
    for row in matrix[window:]:
        total = sum(row) or 1
        for enc in group:
            position = index.get(enc)
            shares[enc].append(row[position] / total if position is not None else 0.0)

    extinct_at = {
        row["encoding"]: row["extinction_generation"] for row in analysis["lineages"]
    }
    ever_top = {row["dominant"] for row in analysis["derived"]["dominance"]}

    result: dict[str, dict] = {}
    for enc in group:
        series = shares[enc]
        result[enc] = {
            "mean_share": statistics.fmean(series) if series else 0.0,
            "final_share": series[-1] if series else 0.0,
            "survived": extinct_at.get(enc) is None,
            "was_top": enc in ever_top,
            "start_seats": sizes[enc],
        }
    return result


def _job(task: tuple[int, list[str], int, int]) -> tuple[int, int, dict[str, dict]]:
    """Worker entry point: one (group, seed) simulation."""
    group_index, group, seed, generations = task
    return group_index, seed, run_group(group, seed, generations)


def finals(source_json: str, top: int, seeds: int, generations: int,
           out_path: str) -> None:
    """Put the strongest candidates in one field and let them fight directly.

    The main sweep ranks each candidate only against six others, so a high
    dominance rate there is a group-relative statement. The finals round puts
    the leaders in the *same* field, and repeats the whole thing under two
    different seat ladders so a result that only holds for one ladder ordering
    is visible as such.
    """
    data = json.loads(Path(source_json).read_text(encoding="utf-8"))
    fillers = data.get("fillers", FILLERS)
    leaders = [row["encoding"] for row in data["rows"]
               if row["encoding"] not in fillers][:top]
    if len(leaders) < len(SEAT_LADDER):
        raise SystemExit("决赛轮需要至少 {} 个候选，当前只有 {} 个".format(
            len(SEAT_LADDER), len(leaders)))

    group = leaders + list(fillers)
    print("决赛轮：{} 个策略同场竞技（+ 填充 {}）".format(len(leaders), fillers))
    print("  " + "  ".join(leaders))
    print()

    configs = [
        ("基准阶梯 " + str(SEAT_LADDER), list(SEAT_LADDER), FILLER_SEATS),
        ("高起始 " + str([6, 8, 10, 12, 14, 17, 21]),
         [6, 8, 10, 12, 14, 17, 21], 12),
        ("低起始 " + str([4, 5, 6, 7, 8, 9, 11]),
         [4, 5, 6, 7, 8, 9, 11], 16),
    ]

    all_rows = []
    workers = min(8, os.cpu_count() or 1)
    for label, ladder, filler_seats in configs:
        t0 = time.time()
        tasks = [(group, ladder, filler_seats, 1000 + index, generations)
                 for index in range(seeds)]
        context = mp.get_context("spawn")
        with context.Pool(processes=workers) as handle:
            partials = handle.map(_ladder_job, tasks)
        merged: dict[str, dict] = {}
        for partial in partials:
            for enc, b in partial.items():
                slot = merged.setdefault(enc, {"shares": [], "finals": [],
                                                "survived": 0, "was_top": 0, "runs": 0})
                slot["shares"].extend(b["shares"])
                slot["finals"].extend(b["finals"])
                slot["survived"] += b["survived"]
                slot["was_top"] += b["was_top"]
                slot["runs"] += b["runs"]
        rows = []
        for enc, b in merged.items():
            runs = max(b["runs"], 1)
            rows.append({
                "encoding": enc,
                "config": label,
                "mean_share": round(statistics.fmean(b["shares"]), 5),
                "mean_final": round(statistics.fmean(b["finals"]), 5),
                "survival": round(b["survived"] / runs, 3),
                "dominance": round(b["was_top"] / runs, 3),
                "worst_share": round(min(b["shares"]), 5),
                "stdev": round(statistics.pstdev(b["shares"]), 5) if len(b["shares"]) > 1 else 0.0,
                "runs": runs,
            })
        rows.sort(key=lambda r: (-r["survival"], -r["mean_share"], -r["worst_share"]))
        all_rows.extend(rows)
        print("--- {}　{} seed　{:.0f}s ---".format(label, seeds, time.time() - t0))
        for row in rows:
            marker = "  (填充)" if row["encoding"] in fillers else ""
            print("  {:<22}{:>8.4f}{:>8.4f}{:>7.0%}{:>7.0%}{:>8.4f}{:>7.4f}{}".format(
                row["encoding"], row["mean_share"], row["mean_final"],
                row["survival"], row["dominance"], row["worst_share"],
                row["stdev"], marker))
        print()

    Path(out_path).write_text(json.dumps({
        "top": top, "seeds": seeds, "generations": generations,
        "leaders": leaders, "fillers": fillers,
        "configs": [c[0] for c in configs],
        "rows": all_rows, "rules": build_rules(),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print("结果已存 {}".format(out_path))


def _ladder_job(task):
    group, ladder, filler_seats, seed, generations = task
    candidates = [enc for enc in group if enc not in FILLERS]
    fillers = [enc for enc in group if enc in FILLERS]
    rotation = seed % len(ladder)
    sizes = {}
    for position, enc in enumerate(candidates):
        sizes[enc] = ladder[(position + rotation) % len(ladder)]
    for enc in fillers:
        sizes[enc] = filler_seats
    shortfall = TOTAL_CAPACITY - sum(sizes.values())
    if shortfall:
        sizes[candidates[-1]] += shortfall
    sim = TrustEvolution(seed=seed, initial_encodings=list(group),
                         initial_sizes=sizes)
    sim.run(generations)
    analysis = build_analysis(sim)
    index = {enc: position for position, enc in enumerate(analysis["encodings"])}
    matrix = analysis["population_matrix"]
    window = max(1, len(matrix) // 2)
    shares = {enc: [] for enc in group}
    for row in matrix[window:]:
        total = sum(row) or 1
        for enc in group:
            position = index.get(enc)
            shares[enc].append(row[position] / total if position is not None else 0.0)
    extinct = {row["encoding"]: row["extinction_generation"]
               for row in analysis["lineages"]}
    ever_top = {row["dominant"] for row in analysis["derived"]["dominance"]}
    out = {}
    for enc in group:
        out[enc] = {
            "shares": [statistics.fmean(shares[enc]) if shares[enc] else 0.0],
            "finals": [shares[enc][-1] if shares[enc] else 0.0],
            "survived": int(extinct.get(enc) is None),
            "was_top": int(enc in ever_top),
            "runs": 1,
        }
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seeds", type=int, default=10)
    parser.add_argument("--generations", type=int, default=200)
    parser.add_argument("--group-size", type=int, default=10)
    parser.add_argument("--workers", type=int, default=0,
                        help="进程数，0 = 自动（最多 8）")
    parser.add_argument("--out", default=str(ROOT / "reports" / "tournament_evolution.json"))
    parser.add_argument("--finals", type=int, default=0,
                        help="决赛轮：把前 N 名放进同一组正面对决")
    parser.add_argument("--finals-seeds", type=int, default=60)
    parser.add_argument("--source", default=str(ROOT / "reports" / "tournament_evolution.json"))
    parser.add_argument("--equivalence",
                        default=str(ROOT / "reports" / "equivalence_all.json"))
    parser.add_argument("--pool", choices=("cross", "family"), default="cross",
                        help="cross = 跨层组合全扫描（默认）；family = 分层扫描（旧）")
    parser.add_argument("--no-merge", action="store_true",
                        help="不按行为等价归并，直接用原始编码池")
    args = parser.parse_args()

    if args.finals:
        finals(args.source, args.finals, args.finals_seeds, args.generations,
               str(ROOT / "reports" / "tournament_finals.json"))
        return

    pool = cross_layer_pool() if args.pool == "cross" else candidate_pool()
    raw_size = len(pool)
    if not args.no_merge:
        pool = merge_equivalent(pool, args.equivalence)
    else:
        print("按要求跳过等价归并，使用全部 {} 个编码".format(len(pool)))
    groups = make_groups(pool, args.group_size)
    tasks = []
    for group_index, group in enumerate(groups, 1):
        for seed_index in range(args.seeds):
            # Deterministic, distinct seeds; no two runs share an rng stream.
            seed = 10_000 * group_index + seed_index * 7 + 1
            tasks.append((group_index, group, seed, args.generations))

    workers = args.workers or min(8, os.cpu_count() or 1)
    print("候选 {} 个 -> {} 组，每组 {} 个策略（含 {} 个填充）".format(
        len(pool), len(groups), args.group_size, len(FILLERS)))
    print("{} 个 seed × {} 代 = 共 {} 次演化，{} 进程并行".format(
        args.seeds, args.generations, len(tasks), workers))
    print()

    tally: dict[str, dict] = {}

    def bucket_for(enc: str) -> dict:
        if enc not in tally:
            tally[enc] = {"shares": [], "finals": [], "survived": 0,
                          "was_top": 0, "runs": 0}
        return tally[enc]

    t0 = time.time()
    done = 0
    if workers > 1:
        # Each worker imports the engine fresh; spawn keeps Windows happy.
        context = mp.get_context("spawn")
        with context.Pool(processes=workers) as handle:
            for _, _, result in handle.imap_unordered(_job, tasks):
                for enc, row in result.items():
                    bucket = bucket_for(enc)
                    bucket["shares"].append(row["mean_share"])
                    bucket["finals"].append(row["final_share"])
                    bucket["survived"] += int(row["survived"])
                    bucket["was_top"] += int(row["was_top"])
                    bucket["runs"] += 1
                done += 1
                if done % 10 == 0 or done == len(tasks):
                    rate = done / max(time.time() - t0, 1e-6)
                    left = (len(tasks) - done) / rate if rate else 0
                    print("  {}/{} 完成　已用 {:.0f}s　预计剩余 {:.0f}s".format(
                        done, len(tasks), time.time() - t0, left))
    else:
        for task in tasks:
            _, _, result = _job(task)
            for enc, row in result.items():
                bucket = bucket_for(enc)
                bucket["shares"].append(row["mean_share"])
                bucket["finals"].append(row["final_share"])
                bucket["survived"] += int(row["survived"])
                bucket["was_top"] += int(row["was_top"])
                bucket["runs"] += 1
            done += 1
            print("  {}/{} 完成　已用 {:.0f}s".format(done, len(tasks), time.time() - t0))

    rows = []
    for enc, bucket in tally.items():
        runs = max(bucket["runs"], 1)
        rows.append({
            "encoding": enc,
            "mean_share": round(statistics.fmean(bucket["shares"]), 5) if bucket["shares"] else 0.0,
            "final_share": round(statistics.fmean(bucket["finals"]), 5) if bucket["finals"] else 0.0,
            "survival": round(bucket["survived"] / runs, 3),
            "dominance": round(bucket["was_top"] / runs, 3),
            "worst_share": round(min(bucket["shares"]), 5) if bucket["shares"] else 0.0,
            "best_share": round(max(bucket["shares"]), 5) if bucket["shares"] else 0.0,
            "runs": bucket["runs"],
        })

    rows.sort(key=lambda r: (-r["survival"], -r["mean_share"], -r["worst_share"]))

    # Quality gate. A ranking is only meaningful if the experiment actually
    # separated the field. These two checks caught a broken design earlier: with
    # a flat 10-seat start nothing was ever culled and every mean share sat on
    # 1/n, so the "winner" was noise.
    cand_rows = [r for r in rows if r["encoding"] not in FILLERS]
    shares = sorted((r["mean_share"] for r in cand_rows), reverse=True)
    gap = (shares[0] - shares[1]) if len(shares) > 1 else 0.0
    all_survive = all(r["survival"] == 1.0 for r in cand_rows)
    print()
    print("=== 实验区分度自检 ===")
    print("  候选存活率: 100% 的有 {}/{}".format(
        sum(1 for r in cand_rows if r["survival"] == 1.0), len(cand_rows)))
    print("  平均份额范围: {:.4f} ~ {:.4f}".format(
        min(shares), max(shares)))
    print("  冠军领先第二名: {:.4f}".format(gap))
    warnings = []
    if all_survive:
        warnings.append("全部候选 100% 存活：淘汰压不足，存活率无法区分")
    if gap < 0.01:
        warnings.append("冠亚军差距 {:.4f} < 0.01：排名可能只是噪声".format(gap))
    if warnings:
        print("  [注意] " + "；".join(warnings))
    else:
        print("  [通过] 淘汰压与份额差异均存在，排名有区分度")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({
        "seeds": args.seeds,
        "generations": args.generations,
        "group_size": args.group_size,
        "fillers": FILLERS,
        "rules": build_rules(),
        "rows": rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("=== 稳定胜率排名（{} 次演化，{:.0f}s）===".format(len(tasks), time.time() - t0))
    header = "{:<24}{:>9}{:>9}{:>8}{:>9}{:>9}".format(
        "策略", "平均份额", "终局份额", "存活率", "夺冠率", "最差种子")
    print(header)
    print("-" * 70)
    for row in rows[:20]:
        print("{:<24}{:>9.4f}{:>9.4f}{:>8.0%}{:>9.0%}{:>9.4f}".format(
            row["encoding"], row["mean_share"], row["final_share"],
            row["survival"], row["dominance"], row["worst_share"]))
    print()
    print("结果已存 {}".format(out))


if __name__ == "__main__":
    main()
