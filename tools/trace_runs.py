"""Trace what actually happened during tournament runs, generation by generation.

Reads the runs back through ``evolution_archive.build_analysis`` -- the same
view the dashboard and the AI skill see -- and pulls out the representative
moments: who led, when the field collapsed, which cascades of extinctions and
subspecies births mattered, and where the diversity curve turned.
"""

from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(r"C:\Users\离众\Desktop\Trust Evolution")
sys.path.insert(0, str(ROOT))

from evolution_archive import build_analysis  # noqa: E402
from trust_evolution_simulation import TOTAL_CAPACITY, TrustEvolution  # noqa: E402
from tools.tournament import (  # noqa: E402
    FILLER_SEATS,
    FILLERS,
    SEAT_LADDER,
    candidate_pool,
    make_groups,
)

GENERATIONS = 250


def run_group(group, seed):
    candidates = [enc for enc in group if enc not in FILLERS]
    rotation = seed % len(SEAT_LADDER)
    sizes = {}
    for position, enc in enumerate(candidates):
        sizes[enc] = SEAT_LADDER[(position + rotation) % len(SEAT_LADDER)]
    for enc in FILLERS:
        sizes[enc] = FILLER_SEATS
    shortfall = TOTAL_CAPACITY - sum(sizes.values())
    if shortfall:
        sizes[candidates[-1]] += shortfall
    sim = TrustEvolution(seed=seed, initial_encodings=list(group),
                         initial_sizes=sizes)
    sim.run(GENERATIONS)
    return sim, sizes, build_analysis(sim)


def trace(label, group, seed):
    sim, sizes, analysis = run_group(group, seed)
    summary = analysis["generation_summary"]
    diversity = analysis["derived"]["diversity"]
    events = analysis["events"]
    counts = analysis["derived"]["event_counts"]

    print()
    print("=" * 74)
    print("【{}】seed={}".format(label, seed))
    print("  初始席位: " + ", ".join(
        "{}={}".format(enc, sizes[enc]) for enc in group))
    print("=" * 74)

    print("  阶段一 G0-49  洗牌期")
    print("    物种数 {} -> {}　平均适应度 {:.2f} -> {:.2f}　Shannon {:.2f} -> {:.2f}".format(
        summary[0]["species_count"], summary[49]["species_count"],
        summary[0]["average_fitness"], summary[49]["average_fitness"],
        diversity[0]["shannon"], diversity[49]["shannon"]))
    early = [e for e in events if e["generation"] < 50]
    print("    事件 {} 个：{}".format(
        len(early), dict(_tally(early))))

    print("  阶段二 G50-149  格局形成")
    print("    物种数 {} -> {}　平均适应度 {:.2f} -> {:.2f}　Shannon {:.2f} -> {:.2f}".format(
        summary[49]["species_count"], summary[149]["species_count"],
        summary[49]["average_fitness"], summary[149]["average_fitness"],
        diversity[49]["shannon"], diversity[149]["shannon"]))
    mid = [e for e in events if 50 <= e["generation"] < 150]
    print("    事件 {} 个：{}".format(len(mid), dict(_tally(mid))))

    print("  阶段三 G150-249  收敛/僵持")
    print("    物种数 {} -> {}　平均适应度 {:.2f} -> {:.2f}　Shannon {:.2f} -> {:.2f}".format(
        summary[149]["species_count"], summary[-1]["species_count"],
        summary[149]["average_fitness"], summary[-1]["average_fitness"],
        diversity[149]["shannon"], diversity[-1]["shannon"]))
    late = [e for e in events if e["generation"] >= 150]
    print("    事件 {} 个：{}".format(len(late), dict(_tally(late))))

    print("  优势物种更替（代表性）")
    previous = object()
    changes = []
    for row in analysis["derived"]["dominance"]:
        if row["dominant"] != previous:
            changes.append("G{}:{}".format(row["generation"], row["dominant"]))
            previous = row["dominant"]
    print("    共 {} 次　{}".format(len(changes), " -> ".join(changes[:8])))

    print("  关键转折：灭绝与独立")
    for kind, label in (("extinction", "物种灭绝"), ("subspecies_extinction", "亚种淘汰"),
                        ("subspecies_independent", "亚种独立")):
        hits = [e for e in events if e["event"] == kind]
        if hits:
            sample = ", ".join("G{}:{}".format(e["generation"], e["encoding"][:16])
                               for e in hits[:4])
            print("    {:<6} {:>2} 次  {}".format(label, len(hits), sample))

    peak = max(diversity, key=lambda r: r["shannon"])
    low = min(diversity[50:], key=lambda r: r["shannon"])
    print("  多样性：峰值 Shannon {:.2f} @G{}　谷值 {:.2f} @G{}　终局 {:.2f}".format(
        peak["shannon"], peak["generation"], low["shannon"], low["generation"],
        diversity[-1]["shannon"]))

    print("  终局格局")
    final = sorted((f for f in analysis["final_state"] if f["population_size"] > 0),
                   key=lambda f: -f["population_size"])
    total = sum(f["population_size"] for f in final) or 1
    for f in final[:5]:
        sub = f["subspecies"]
        print("    {:<26} {:>3} 席 ({:>5.1%}){}".format(
            f["encoding"][:26], f["population_size"],
            f["population_size"] / total,
            "  +亚种 " + sub["encoding"][:18] if sub else ""))
    return analysis


def _tally(events):
    out = {}
    for event in events:
        out[event["event"]] = out.get(event["event"], 0) + 1
    return out


def main():
    pool = candidate_pool()
    groups = make_groups(pool, 7)
    print("候选 {} 个 -> {} 组。以下挑 4 个代表性运行做阶段追踪。".format(
        len(pool), len(groups)))

    # Pick groups that contain the current leaders plus a couple of random ones,
    # so the trace covers both the winners and the also-rans.
    picks = []
    seen = set()
    for group in groups:
        if any(enc.startswith("R1-2") for enc in group) and len(picks) < 1:
            picks.append(("含 R1-2 家族（第 1 组）", group, 10001))
        if any(enc == "S0" or enc == "SM" for enc in group) and len(picks) < 2:
            picks.append(("中段对照组", group, 20002))
    for index, group in enumerate(groups):
        if len(picks) >= 4:
            break
        if group not in [p[1] for p in picks]:
            picks.append(("第 {} 组".format(index + 1), group, 30003 + index))
    for label, group, seed in picks[:4]:
        trace(label, group, seed)

    print()
    print("提示：以上是单次运行的轨迹。跨 seed 的稳定性结论见 "
          "reports/tournament_evolution.json。")


if __name__ == "__main__":
    main()
