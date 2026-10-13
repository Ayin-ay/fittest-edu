"""Detect behaviourally equivalent strategy encodings.

Two different encodings can be the same strategy. ``M{N}`` narrows the history
window a modifier reads, and when the trigger it modifies already only looks at
the opponent's last turn, the window is irrelevant -- so ``R1-M+M2`` behaves
exactly like ``R1-2``. Treating those as two independent strategies inflates a
tournament with duplicate entries and lets a meaningless "win" over an alias
look like a finding.

Equivalence is decided by behaviour, not by reading the encoding: every
candidate is played against a common probe set and its full action vector is
recorded. Encodings whose vectors agree on every probe, under several rng seeds,
are the same strategy and are reported as one class.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from strategy_engine.strategy_engine import StrategyState, parse_strategy  # noqa: E402
from trust_evolution_simulation import TURNS_PER_MATCH  # noqa: E402

# Probes must span the behavioural space: unconditional cooperators and
# defectors, conditional retaliators, forgiving variants, and noisy strategies
# whose stochasticity only shows up across seeds.
PROBES = [
    "S0", "S1", "S2", "SM",
    "F1-1", "F2-3", "F3-1", "T1-1", "T1-2",
    "D0", "D1", "AD1", "W", "BS2", "BS3",
    "R1-1", "R1-2", "R1-3", "R1-M",
    "R2-2", "R1-1+RPT1-1", "S1+P1-1", "K1-2", "B1-3", "H2-1", "RC1-1",
    "S0+C2", "R1-1+C2", "F2-3+C4-C",
]
SEEDS_PER_PROBE = 3


def action_vector(encoding: str, seeds_per_probe: int) -> list[str]:
    """Exact per-turn actions of ``encoding`` against every probe, per seed.

    The signature is the behaviour itself, not a score: two strategies can match
    on average score while playing completely differently, and then they are not
    equivalent.
    """
    vector: list[str] = []
    for probe_index, probe in enumerate(PROBES):
        for run in range(seeds_per_probe):
            rng = random.Random(9_000 + probe_index * 131 + run * 17)
            state = StrategyState(parse_strategy(encoding), TURNS_PER_MATCH, rng=rng)
            other = StrategyState(parse_strategy(probe), TURNS_PER_MATCH, rng=rng)
            mine: list = []
            theirs: list = []
            for _ in range(TURNS_PER_MATCH):
                # Both sides must act on the *other's* history; feeding our own
                # actions back in as the opponent's makes every strategy face a
                # mirror of itself, which never triggers a retaliator and makes
                # all encodings look identical.
                my_action = state.decide(theirs)
                their_action = other.decide(mine)
                mine.append("C" if my_action == "C" else "D")
                theirs.append("C" if their_action == "C" else "D")
            vector.append("".join(mine))
    return vector


def group_equivalences(encodings: list[str], seeds_per_probe: int) -> list[list[str]]:
    """Partition encodings into behaviourally identical classes."""
    signatures: dict[tuple, list[str]] = defaultdict(list)
    for encoding in encodings:
        signatures[tuple(action_vector(encoding, seeds_per_probe))].append(encoding)
    return [sorted(members) for members in signatures.values()]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-tournament",
                        default=str(ROOT / "reports" / "tournament_evolution.json"))
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument("--all", action="store_true",
                        help="check every candidate rather than only the top N")
    parser.add_argument("--explicit", nargs="*", default=None,
                        help="check an explicit list of encodings")
    parser.add_argument("--seeds-per-probe", type=int, default=SEEDS_PER_PROBE)
    parser.add_argument("--out", default=str(ROOT / "reports" / "equivalence.json"))
    args = parser.parse_args()

    if args.explicit:
        encodings = list(args.explicit)
        source = "命令行指定"
    else:
        data = json.loads(Path(args.from_tournament).read_text(encoding="utf-8"))
        fillers = data.get("fillers", [])
        rows = [r["encoding"] for r in data["rows"] if r["encoding"] not in fillers]
        encodings = rows if args.all else rows[:args.top]
        source = "{} 的前 {} 名".format(
            Path(args.from_tournament).name, len(encodings))

    print("检查 {} 个编码（来源：{}），探针 {} 个 × {} seed".format(
        len(encodings), source, len(PROBES), args.seeds_per_probe))
    print()

    classes = group_equivalences(encodings, args.seeds_per_probe)
    classes.sort(key=len, reverse=True)

    merged = [c for c in classes if len(c) > 1]
    print("=== 行为等价类 ===")
    print("{} 个类，其中 {} 个编码与他人行为完全相同（可合并）".format(
        len(classes), sum(len(c) - 1 for c in merged)))
    for members in classes:
        if len(members) > 1:
            print("  等价: " + "  ==  ".join(members))
    print()
    singletons = [c[0] for c in classes if len(c) == 1]
    print("唯一行为 {} 个".format(len(singletons)))
    if singletons:
        print("  " + ", ".join(singletons[:24]))
        if len(singletons) > 24:
            print("  ... 其余 {} 个".format(len(singletons) - 24))

    Path(args.out).write_text(json.dumps({
        "probes": PROBES,
        "seeds_per_probe": args.seeds_per_probe,
        "source": source,
        "classes": classes,
        "merged_count": sum(len(c) - 1 for c in merged),
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print("结果已存 {}".format(args.out))


if __name__ == "__main__":
    main()
