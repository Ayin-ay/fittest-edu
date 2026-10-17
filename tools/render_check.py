"""Smoke check: every creation-mode figure and HTML block still builds.

Run with ``python -X utf8 tools/render_check.py`` from the repository root.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from trust_evolution_simulation import TrustEvolution  # noqa: E402
from dashboard import render_helpers as rh  # noqa: E402
from dashboard.naming import build_name_map  # noqa: E402


def main() -> int:
    sim = TrustEvolution(
        seed=7,
        initial_encodings=["S1", "S2", "F1-1", "T1-2", "D0", "W"],
        initial_sizes={"S1": 25, "S2": 20, "F1-1": 15, "T1-2": 15, "D0": 10, "W": 10},
    )
    sim.run(14)
    encodings: list[str] = []
    for snapshot in sim.history:
        encodings.extend(snapshot.keys())
    for event in sim.events:
        encodings.append(event.encoding)
        if event.parent_encoding:
            encodings.append(event.parent_encoding)
    names = build_name_map(list(dict.fromkeys(encodings)))
    last = len(sim.generation_records) - 1
    figures = {
        "population_area": rh.build_population_area(sim, names),
        "matchup_heatmap": rh.build_matchup_heatmap(sim, last, names),
        "heatmap_detail": rh.build_heatmap_detail(sim, last, names),
        "evolution_tree": rh.build_evolution_tree(sim, names),
        "distribution_bar": rh.build_distribution_bar(sim, last, names),
        "distribution_pie": rh.build_distribution_pie(sim, last, names),
        "empty_bar": rh.build_distribution_bar(TrustEvolution(seed=1), 0, None),
    }
    for name, fig in figures.items():
        layout = fig.layout
        print(
            "{}: paper={} plot={} font={} margin l={} r={}".format(
                name,
                layout.paper_bgcolor,
                layout.plot_bgcolor,
                (layout.font or {}).color,
                layout.margin.l,
                layout.margin.r,
            )
        )
    html = rh.build_snapshot_html(sim, last, names)
    print("snapshot html: {} chars, cool greys={}".format(
        len(html), any(token in html for token in ("#aaa", "#666", "#f0f0f0", "#888"))))
    print("rows: change={} fitness={} events={}".format(
        len(rh.build_change_rows(sim, last, names)),
        len(rh.build_fitness_rows(sim, last, names)),
        len(rh.events_at(sim, last, names)),
    ))
    print("event palette:", {k: v[2] for k, v in rh._EVENT_STYLE.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
