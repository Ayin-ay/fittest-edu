"""Plotly rendering helpers for The Fittest dashboard.

The functions here only read the public data recorded by the simulation
(``history``, ``fitness_history``, ``generation_records`` and ``events``).
They never touch the simulation algorithm itself.
"""

from __future__ import annotations

# See app.py: import pandas before Plotly so its optional-pandas check never
# observes a partially initialized module.
import pandas  # noqa: F401
import plotly.graph_objects as go

try:  # Import works both as ``dashboard.render_helpers`` and as a flat module.
    from trust_evolution_simulation import TOTAL_CAPACITY, TrustEvolution
except ImportError:  # pragma: no cover - fallback for package-relative imports
    from ..trust_evolution_simulation import TOTAL_CAPACITY, TrustEvolution


_FAMILY_PALETTE = {
    "S": "#d95f5f",
    "P": "#4f81bd",
    "F": "#55a868",
    "T": "#e5ae38",
    "D": "#8064a2",
    "W": "#4fb3bf",
    "B": "#e67e22",
    "R": "#9b59b6",
    "A": "#8c564b",
    "K": "#2ca02c",
    "C": "#7f7f7f",
}
_INDEPENDENT_PALETTE = [
    "#e41a1c",
    "#377eb8",
    "#4daf4a",
    "#984ea3",
    "#ff7f00",
    "#a65628",
    "#f781bf",
    "#17becf",
]

_EVENT_LABELS = {
    "extinction": "物种灭绝",
    "subspecies_extinction": "亚种淘汰",
    "subspecies_birth": "亚种生成",
    "subspecies_independent": "亚种独立",
    "injection": "策略注入",
}


def family_color(encoding: str) -> str:
    """Return the base-strategy color as a hex string."""
    return _FAMILY_PALETTE.get(encoding[:1], "#999999")


def independent_color(encoding: str) -> str:
    """Return a distinct saturated color for an independent species."""
    return _INDEPENDENT_PALETTE[sum(ord(char) for char in encoding) % len(_INDEPENDENT_PALETTE)]


def _independent_encodings(sim: TrustEvolution) -> set[str]:
    return {
        event.encoding
        for event in sim.events
        if event.event == "subspecies_independent"
    }


def _display_name(names: dict[str, str] | None, encoding: str) -> str:
    """Map an encoding to its Chinese display name, falling back to the code."""
    return names.get(encoding, encoding) if names else encoding


def ordered_encodings(sim: TrustEvolution) -> list[str]:
    """All encodings ever seen, earliest born first."""
    all_encodings = {encoding for snapshot in sim.history for encoding in snapshot}
    birth_by_encoding = {
        encoding: next(
            (
                event.generation
                for event in sim.events
                if event.encoding == encoding
                and event.event in {"subspecies_birth", "subspecies_independent"}
            ),
            0,
        )
        for encoding in all_encodings
    }
    return sorted(all_encodings, key=lambda encoding: (birth_by_encoding[encoding], encoding))


_EVENT_STYLE = {
    "subspecies_birth": ("subspecies", "◇ 亚种生成", "#1f77b4"),
    "subspecies_independent": ("independent", "★ 独立为新物种", "#d62728"),
    "extinction": ("species", "× 物种灭绝", "#d62728"),
    "subspecies_extinction": ("subspecies", "× 亚种淘汰", "#ff7f0e"),
    "injection": ("species", "＋ 策略注入", "#2ca02c"),
}


def _add_event_vlines(fig: go.Figure, sim: TrustEvolution) -> None:
    for event in sim.events:
        if event.event == "subspecies_birth":
            fig.add_vline(
                x=event.generation, line_dash="dash", line_color="#1f77b4", line_width=1
            )
        elif event.event == "subspecies_independent":
            fig.add_vline(
                x=event.generation, line_dash="dash", line_color="#d62728", line_width=1.5
            )
        elif event.event == "extinction":
            fig.add_vline(
                x=event.generation, line_dash="dot", line_color="#d62728", line_width=1
            )
        elif event.event == "subspecies_extinction":
            fig.add_vline(
                x=event.generation, line_dash="dot", line_color="#ff7f0e", line_width=1
            )


def _add_event_annotations(
    fig: go.Figure,
    sim: TrustEvolution,
    bands: list[dict],
    band_lower: list[list[float]],
    total_generations: int,
    names: dict[str, str] | None = None,
) -> None:
    """Point an arrow from each event label to its band on the chart.

    The annotation anchor ``(x, y)`` is the arrow tip on the band, while
    ``ax``/``ay`` only offset the label box. Combined with the dashboard's
    ``edits.annotationTail`` config, dragging the label keeps the arrow tip
    fixed on the corresponding position.
    """
    label_offsets = [
        (75, -60),
        (100, 50),
        (-75, -60),
        (-100, 50),
        (65, -110),
        (-65, -110),
        (130, -10),
        (-130, -10),
    ]

    def locate(encoding: str, prefer: str, generation: int):
        candidates = [i for i, band in enumerate(bands) if band["encoding"] == encoding]
        if not candidates:
            return None
        chosen = next(
            (i for i in candidates if bands[i]["kind"] == prefer), candidates[0]
        )
        values = bands[chosen]["values"]
        gen = min(max(generation, 0), total_generations - 1)
        if values[gen] <= 0 and gen > 0:
            gen -= 1
        if values[gen] <= 0:
            positives = [g for g, value in enumerate(values) if value > 0]
            if not positives:
                return None
            gen = positives[0]
        lower = band_lower[chosen][gen]
        height = max(values[gen], 1)
        return float(gen), lower + height / 2

    for event_name, (prefer, prefix, color) in _EVENT_STYLE.items():
        events = [event for event in sim.events if event.event == event_name]
        for position, event in enumerate(events):
            anchor = locate(event.encoding, prefer, event.generation)
            if anchor is None and event.parent_encoding:
                anchor = locate(event.parent_encoding, "species", event.generation)
            if anchor is None:
                continue
            offset_x, offset_y = label_offsets[position % len(label_offsets)]
            fig.add_annotation(
                x=anchor[0],
                y=anchor[1],
                text=f"{prefix}<br>{_display_name(names, event.encoding)}",
                showarrow=True,
                arrowhead=2,
                arrowsize=1.1,
                arrowwidth=1,
                arrowcolor=color,
                ax=offset_x,
                ay=offset_y,
                xanchor="center",
                yanchor="middle",
                font=dict(size=8, color=color),
                bgcolor="rgba(255,255,255,0.9)",
                bordercolor=color,
                borderwidth=1,
                borderpad=2,
            )


def _add_band(
    fig: go.Figure,
    x: list[int],
    values: list[int],
    name: str,
    color: str,
    hatched: bool,
    hover_note: str,
) -> None:
    trace = go.Scatter(
        x=x,
        y=values,
        mode="lines",
        stackgroup="one",
        name=name,
        line=dict(color=color, width=0.0, shape="hv"),
        fillcolor=color,
        opacity=0.6 if hatched else 0.9,
        hovertemplate=f"{hover_note}<br>代数 %{{x}}<br>规模 %{{y}}<extra></extra>",
    )
    if hatched:
        # Hatch pattern keeps small subspecies visible. Plotly validates this
        # lazily, so guard against versions that lack the property.
        try:
            trace.fillpattern = dict(
                shape="/", fgcolor="rgba(255,255,255,0.85)", fillmode="overlay"
            )
        except (AttributeError, ValueError):
            pass
    fig.add_trace(trace)


def build_population_area(
    sim: TrustEvolution, names: dict[str, str] | None = None
) -> go.Figure:
    """Stacked area chart that separates the subspecies and independent phases.

    A lineage that becomes independent is drawn in two stacked segments: the
    first uses the family color plus a hatch while it is still a subspecies,
    the second switches to the independent color once it becomes its own
    species. This makes the transition visible instead of painting the whole
    lineage with one color.
    """
    ordered = ordered_encodings(sim)
    x = list(range(len(sim.history)))
    independence = {
        event.encoding: event.generation
        for event in sim.events
        if event.event == "subspecies_independent"
    }
    subspecies_birth = {
        event.encoding: event.generation
        for event in sim.events
        if event.event == "subspecies_birth"
    }
    label = lambda encoding: _display_name(names, encoding)

    bands: list[dict] = []
    for encoding in ordered:
        values = [snapshot.get(encoding, 0) for snapshot in sim.history]
        if not any(values):
            continue
        indep_generation = independence.get(encoding)
        if indep_generation is None:
            is_subspecies = encoding in subspecies_birth
            bands.append(
                {
                    "encoding": encoding,
                    "kind": "subspecies" if is_subspecies else "species",
                    "values": values,
                    "color": family_color(encoding),
                    "hatched": is_subspecies,
                    "name": f"{label(encoding)} (亚种)" if is_subspecies else label(encoding),
                    "hover": f"{label(encoding)}（亚种）" if is_subspecies else label(encoding),
                }
            )
            continue
        pre = [
            value if generation < indep_generation else 0
            for generation, value in enumerate(values)
        ]
        post = [
            value if generation >= indep_generation else 0
            for generation, value in enumerate(values)
        ]
        if any(pre):
            bands.append(
                {
                    "encoding": encoding,
                    "kind": "subspecies",
                    "values": pre,
                    "color": family_color(encoding),
                    "hatched": True,
                    "name": f"{label(encoding)} (亚种)",
                    "hover": f"{label(encoding)}（亚种）",
                }
            )
        if any(post):
            bands.append(
                {
                    "encoding": encoding,
                    "kind": "independent",
                    "values": post,
                    "color": independent_color(encoding),
                    "hatched": False,
                    "name": f"{label(encoding)} (独立)",
                    "hover": f"{label(encoding)}（独立）",
                }
            )

    fig = go.Figure()
    band_lower: list[list[float]] = []
    bottom = [0.0] * len(x)
    for band in bands:
        band_lower.append(list(bottom))
        _add_band(
            fig,
            x,
            band["values"],
            band["name"],
            band["color"],
            band["hatched"],
            band["hover"],
        )
        bottom = [base + value for base, value in zip(bottom, band["values"])]

    _add_event_vlines(fig, sim)
    _add_event_annotations(fig, sim, bands, band_lower, len(x), names=names)
    fig.update_layout(
        height=460,
        yaxis=dict(title="种群规模", range=[0, TOTAL_CAPACITY], fixedrange=True),
        xaxis=dict(title="代数"),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=-0.4, xanchor="left", x=0),
        margin=dict(l=40, r=20, t=30, b=130),
        plot_bgcolor="#fafafa",
    )
    return fig


def build_fitness_chart(
    sim: TrustEvolution, names: dict[str, str] | None = None
) -> go.Figure:
    """Fitness line chart; lines break once a species goes extinct."""
    ordered = ordered_encodings(sim)
    x = list(range(len(sim.fitness_history)))
    independent = _independent_encodings(sim)

    fig = go.Figure()
    for encoding in ordered:
        values = [snapshot.get(encoding) for snapshot in sim.fitness_history]
        if not any(value is not None for value in values):
            continue
        color = independent_color(encoding) if encoding in independent else family_color(encoding)
        display = _display_name(names, encoding)
        fig.add_trace(
            go.Scatter(
                x=x,
                y=values,
                mode="lines+markers",
                name=display,
                line=dict(color=color, width=2),
                marker=dict(size=4),
                connectgaps=False,
                customdata=[encoding] * len(values),
                hovertemplate=(
                    f"{display}<br>编码 %{{customdata}}<br>代数 %{{x}}<br>适应度 %{{y:.2f}}<extra></extra>"
                ),
            )
        )

    for event in sim.events:
        if event.event in {"extinction", "subspecies_extinction"}:
            fig.add_vline(
                x=event.generation,
                line_dash="dot",
                line_color="#888888",
                line_width=1,
            )

    fig.update_layout(
        height=340,
        yaxis=dict(title="适应度", range=[0, 5], fixedrange=True),
        xaxis=dict(title="代数"),
        hovermode="x unified",
        legend=dict(orientation="h", yanchor="bottom", y=-0.45, xanchor="left", x=0),
        margin=dict(l=40, r=20, t=20, b=120),
        plot_bgcolor="#fafafa",
    )
    return fig


def _species_rows(record) -> list[tuple[str, int, dict | None, int]]:
    rows: list[tuple[str, int, dict | None, int]] = []
    for encoding, data in record.species_data.items():
        subspecies = data.get("subspecies")
        population = data.get("population_size", 0)
        total = population + (subspecies["size"] if subspecies else 0)
        if total <= 0:
            continue
        rows.append((encoding, population, subspecies, total))
    rows.sort(key=lambda row: row[3], reverse=True)
    return rows


def build_snapshot_html(
    sim: TrustEvolution,
    generation: int,
    names: dict[str, str] | None = None,
) -> str:
    """Right-column population snapshot with a striped segment for subspecies."""
    generation = max(0, min(generation, len(sim.generation_records) - 1))
    record = sim.generation_records[generation]
    parts: list[str] = []
    for encoding, population, subspecies, total in _species_rows(record):
        color = family_color(encoding)
        bar_width = min(total, TOTAL_CAPACITY)
        display = _display_name(names, encoding)
        if subspecies:
            sub_color = family_color(subspecies["encoding"])
            sub_width = min(subspecies["size"], TOTAL_CAPACITY)
            orig_width = max(0, bar_width - sub_width)
            parts.append(
                f"""
                <div style="margin: 8px 0;">
                    <div style="display: flex; justify-content: space-between; font-size: 12px;">
                        <span><b>{display}</b> <span style="color:#aaa;font-size:10px;">{encoding}</span></span>
                        <span style="color: #666;">{population}+{subspecies['size']}=<b>{total}</b></span>
                    </div>
                    <div style="background: #f0f0f0; height: 18px; border-radius: 4px; overflow: hidden; display: flex;">
                        <div style="width: {orig_width}%; background: {color}; height: 100%;"></div>
                        <div style="width: {sub_width}%; height: 100%; background: repeating-linear-gradient(
                            45deg, {sub_color}, {sub_color} 3px, rgba(255,255,255,0.7) 3px, rgba(255,255,255,0.7) 6px
                        );"></div>
                    </div>
                </div>
                """
            )
        else:
            parts.append(
                f"""
                <div style="margin: 8px 0;">
                    <div style="display: flex; justify-content: space-between; font-size: 12px;">
                        <span><b>{display}</b> <span style="color:#aaa;font-size:10px;">{encoding}</span></span>
                        <span><b>{total}</b></span>
                    </div>
                    <div style="background: #f0f0f0; height: 18px; border-radius: 4px; overflow: hidden;">
                        <div style="width: {bar_width}%; background: {color}; height: 100%;"></div>
                    </div>
                </div>
                """
            )
    if not parts:
        return "<p style='color:#888;'>本代没有存活物种。</p>"
    return "\n".join(parts)


def build_fitness_html(sim: TrustEvolution, generation: int) -> str:
    """Right-column fitness list with up/down/flat trend arrows."""
    generation = max(0, min(generation, len(sim.fitness_history) - 1))
    snapshot = sim.fitness_history[generation]
    previous = sim.fitness_history[generation - 1] if generation > 0 else {}
    rows = sorted(
        ((encoding, value) for encoding, value in snapshot.items() if value is not None),
        key=lambda row: row[1],
        reverse=True,
    )
    parts: list[str] = []
    for encoding, fitness in rows:
        if generation == 0 or encoding not in previous:
            trend, trend_color = "─", "#888888"
        else:
            diff = fitness - previous[encoding]
            if diff > 0.05:
                trend, trend_color = "▲", "#2ca02c"
            elif diff < -0.05:
                trend, trend_color = "▼", "#d62728"
            else:
                trend, trend_color = "─", "#888888"
        parts.append(
            f"""
            <div style="display: flex; justify-content: space-between; padding: 3px 0; font-size: 12px;">
                <span><b>{encoding}</b></span>
                <span>{fitness:.2f} <span style="color: {trend_color};">{trend}</span></span>
            </div>
            """
        )
    if not parts:
        return "<p style='color:#888;'>暂无适应度数据。</p>"
    return "\n".join(parts)


def build_matchup_heatmap(
    sim: TrustEvolution,
    generation: int,
    names: dict[str, str] | None = None,
) -> go.Figure:
    """Heatmap of the pairwise average score recorded for one generation."""
    generation = max(0, min(generation, len(sim.generation_records) - 1))
    matrix = sim.generation_records[generation].matchup_matrix
    if not matrix:
        fig = go.Figure()
        fig.update_layout(
            height=420,
            title="对战矩阵（该代暂无数据）",
            plot_bgcolor="#fafafa",
        )
        return fig

    axis = sorted(matrix.keys())
    axis_labels = [_display_name(names, encoding) for encoding in axis]
    z = [[matrix[row].get(column) for column in axis] for row in axis]
    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=axis_labels,
            y=axis_labels,
            colorscale="RdYlGn",
            colorbar=dict(title="平均得分"),
            hovertemplate="本方 %{y}<br>对方 %{x}<br>得分 %{z:.2f}<extra></extra>",
        )
    )
    fig.update_layout(
        height=max(360, 40 * len(axis) + 160),
        title=f"第 {generation} 代对战矩阵（行=本方，列=对方）",
        xaxis=dict(title="对手策略", tickangle=-45),
        yaxis=dict(title="本方策略", autorange="reversed"),
        margin=dict(l=40, r=20, t=60, b=120),
        plot_bgcolor="#fafafa",
    )
    return fig


# Row height and top-margin ceilings for the fullscreen heatmap. Upright labels
# buy length with height, so an unusually long strategy name would otherwise
# stretch the figure to several screens; past these caps the labels elide.
# 96px holds ten characters at 9px, which keeps a 13-strategy matrix near two
# phone screens rather than three.
MAX_ROW_HEIGHT = 96
MAX_TOP_MARGIN = 130


def _clip_label(text: str, limit: int) -> str:
    """Shorten a label for the crowded axis, keeping the informative head."""
    if limit <= 0 or len(text) <= limit:
        return text
    return text[: max(1, limit - 1)] + "…"


def build_heatmap_detail(
    sim: TrustEvolution,
    generation: int,
    names: dict[str, str] | None = None,
) -> go.Figure:
    """Heatmap re-laid-out as a landscape matrix for reading on a phone.

    A portrait heatmap cannot work on a narrow screen: with a dozen strategies
    the names are 10-14 Chinese characters, and whichever axis they sit on they
    either pile up or get clipped. A previous attempt rotated the left labels
    vertical, which traded clipping for overlap -- vertical text needs
    ``len(label) * font`` of *vertical* space, and a row is only ~30px tall.

    So the matrix is turned on its side, which is what makes the space work out:

    * **本方 moves to the top.** The top margin is free to be tall, and a label
      standing upright there only needs ~10px of *horizontal* room per column,
      which every column can spare. Full names fit.
    * **对方 moves to the left**, upright like the old left labels, and is
      shortened to what one row can actually hold. The full name is still one
      tap away in the tooltip, and the order matches the top axis, so row *i*
      on the left is column *i* on the top.
    * The grid therefore spreads horizontally and reads left-to-right, like a
      chart in landscape, while the device itself stays in portrait.

    One finger pans and two fingers pinch-zoom come from Plotly natively.
    """
    generation = max(0, min(generation, len(sim.generation_records) - 1))
    matrix = sim.generation_records[generation].matchup_matrix
    axis = sorted(matrix) if matrix else []
    if not axis:
        fig = go.Figure()
        fig.update_layout(
            height=420, title="对战矩阵（该代暂无数据）", plot_bgcolor="#fafafa"
        )
        return fig

    full = [_display_name(names, encoding) for encoding in axis]
    count = len(axis)
    longest = max((len(text) for text in full), default=1)

    # Transpose so 本方 (previously the rows) runs along the top.
    z = [[matrix[column].get(row) for column in axis] for row in axis]
    custom = [[[full[col], full[row]] for col in range(count)] for row in range(count)]

    # Both axes are upright, reading the same way, so a label spends a single
    # character's width per column/row. The left axis is therefore almost free
    # horizontally, and its length is bought with height instead: a row has to
    # be as tall as the text standing in it. There is unused room below the grid
    # on a phone, so the rows are stretched until each name fits whole.
    left_font = 9
    row_height = min(MAX_ROW_HEIGHT, longest * left_font + 8)
    left_chars = max(3, int((row_height - 8) / left_font))
    left = [_clip_label(text, left_chars) for text in full]

    # The top axis gets the same treatment, with the margin sized to its names.
    top_font = 9
    top_margin = min(MAX_TOP_MARGIN, longest * top_font + 16)
    top_chars = max(6, int((top_margin - 16) / top_font))
    top = [_clip_label(text, top_chars) for text in full]

    # Upright text only needs one character's width per row, so the left margin
    # stays small and every column fits on screen -- no range clipping, no
    # horizontal panning, and no numeric range on a category axis (which made
    # Plotly mis-type the axis and render a stray "undefined" tick).
    left_margin = 30
    right_margin = 18
    colorbar_allowance = 44
    bottom_margin = 24

    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=top,
            y=left,
            customdata=custom,
            colorscale="RdYlGn",
            colorbar=dict(
                title=dict(text="得分", font=dict(size=10)),
                thickness=10,
                # Pixels, not a fraction: the figure is now tall enough that a
                # proportional length would stretch the bar into a full-height
                # column.
                len=240,
                lenmode="pixels",
                x=1.02,
                y=0.5,
                yanchor="middle",
                tickfont=dict(size=9),
            ),
            hovertemplate=(
                "本方 %{customdata[0]}<br>对方 %{customdata[1]}<br>"
                "得分 %{z:.2f}<extra></extra>"
            ),
            # Left-aligned so the two names start on the same line and the
            # label reads as a wide strip rather than a tall narrow box.
            hoverlabel=dict(align="left"),
        )
    )
    fig.update_layout(
        # No title: it sat inside the plot and cost vertical room that the top
        # labels need. The page header already states the generation.
        title=None,
        height=row_height * count + top_margin + bottom_margin,
        margin=dict(
            l=left_margin, r=right_margin, t=top_margin, b=bottom_margin
        ),
        xaxis=dict(
            title=None,
            # 90 (not -90): on a top axis a negative angle makes Plotly draw
            # the glyphs mirrored, so the names came out upside down.
            tickangle=90,
            side="top",
            tickfont=dict(size=top_font),
            ticks="",
            # Let Plotly grow the margins to whatever the labels actually need.
            # Without this the upright names are silently clipped at the top of
            # the figure and only their last characters survive.
            automargin=True,
            showgrid=True,
            gridcolor="rgba(255,255,255,0.9)",
            gridwidth=1,
            fixedrange=False,
        ),
        yaxis=dict(
            title=None,
            autorange="reversed",
            # Upright like the top axis, so both read the same way.
            tickangle=90,
            tickfont=dict(size=left_font),
            ticks="",
            automargin=True,
            showgrid=True,
            gridcolor="rgba(255,255,255,0.9)",
            gridwidth=1,
            fixedrange=False,
        ),
        # Panning is the gesture people reach for on a phone; with the default
        # "zoom" dragmode a chart that already fits everything refuses to move.
        dragmode="pan",
        font=dict(size=11),
    )
    return fig


def build_evolution_tree(
    sim: TrustEvolution, names: dict[str, str] | None = None
) -> go.Figure:
    """Timeline tree: one row per encoding, edges from parent to subspecies.

    Subspecies are drawn with a dashed lifeline in the family color and a
    diamond birth marker. Once a subspecies becomes independent its lifeline
    turns solid and switches to the independent color, with a star marker and
    an explicit "独立" label.
    """
    ordered = ordered_encodings(sim)
    index = {encoding: position for position, encoding in enumerate(ordered)}
    total_rows = len(ordered)
    independence = {
        event.encoding: event.generation
        for event in sim.events
        if event.event == "subspecies_independent"
    }
    subspecies_birth = {
        event.encoding: event.generation
        for event in sim.events
        if event.event == "subspecies_birth"
    }
    extinction = {
        event.encoding: event.generation
        for event in sim.events
        if event.event in {"extinction", "subspecies_extinction"}
    }
    fig = go.Figure()

    for encoding in ordered:
        generations = [
            generation
            for generation, snapshot in enumerate(sim.history)
            if snapshot.get(encoding, 0) > 0
        ]
        if not generations:
            continue
        birth, death = generations[0], generations[-1]
        peak = max(sim.history[generation].get(encoding, 0) for generation in generations)
        y = total_rows - index[encoding]
        family = family_color(encoding)
        display = _display_name(names, encoding)
        is_subspecies = encoding in subspecies_birth
        indep_generation = independence.get(encoding)

        if indep_generation is not None and birth < indep_generation:
            fig.add_trace(
                go.Scatter(
                    x=[birth, indep_generation],
                    y=[y, y],
                    mode="lines",
                    line=dict(color=family, width=2, dash="dash"),
                    showlegend=False,
                    hoverinfo="skip",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=[indep_generation, death],
                    y=[y, y],
                    mode="lines",
                    line=dict(color=independent_color(encoding), width=3),
                    showlegend=False,
                    hoverinfo="skip",
                )
            )
        else:
            color = (
                independent_color(encoding)
                if indep_generation is not None
                else family
            )
            fig.add_trace(
                go.Scatter(
                    x=[birth, death],
                    y=[y, y],
                    mode="lines",
                    line=dict(color=color, width=2, dash="dash" if is_subspecies else "solid"),
                    showlegend=False,
                    hoverinfo="skip",
                )
            )

        fig.add_trace(
            go.Scatter(
                x=[birth],
                y=[y],
                mode="markers",
                marker=dict(
                    symbol="diamond" if is_subspecies else "circle",
                    size=min(30, 10 + peak * 0.4),
                    color=family,
                    line=dict(color="black", width=1),
                ),
                showlegend=False,
                hovertemplate=(
                    f"{display}<br>编码 {encoding}<br>诞生 G{birth}"
                    + ("（亚种）" if is_subspecies else "")
                    + f"<br>存活至 G{death}<br>峰值规模 {peak}<extra></extra>"
                ),
            )
        )
        fig.add_annotation(
            x=birth,
            y=y,
            text=f"◇ {display}" if is_subspecies else display,
            showarrow=False,
            xanchor="left",
            yanchor="bottom",
            xshift=8,
            yshift=6,
            font=dict(size=9, color="#1f77b4" if is_subspecies else "#333333"),
            bgcolor="rgba(255,255,255,0.75)",
        )

        if indep_generation is not None:
            fig.add_trace(
                go.Scatter(
                    x=[indep_generation],
                    y=[y],
                    mode="markers",
                    marker=dict(
                        symbol="star",
                        size=16,
                        color=independent_color(encoding),
                        line=dict(color="black", width=1),
                    ),
                    showlegend=False,
                    hovertemplate=(
                        f"{display}<br>编码 {encoding}<br>★ 独立 G{indep_generation}<extra></extra>"
                    ),
                )
            )
            fig.add_annotation(
                x=indep_generation,
                y=y,
                text=f"★ 独立 G{indep_generation}",
                showarrow=True,
                arrowhead=2,
                ax=0,
                ay=-22,
                font=dict(size=9, color="#d62728"),
                bgcolor="rgba(255,245,245,0.85)",
            )

        if encoding in extinction:
            fig.add_annotation(
                x=extinction[encoding],
                y=y,
                text=f"× 灭绝 G{extinction[encoding]}",
                showarrow=True,
                arrowhead=2,
                ax=0,
                ay=22,
                font=dict(size=9, color="#d62728"),
                bgcolor="rgba(255,245,245,0.85)",
            )

    for event in sim.events:
        if event.event not in {"subspecies_birth", "subspecies_independent"}:
            continue
        parent = event.parent_encoding
        if parent not in index or event.encoding not in index:
            continue
        independent_child = event.event == "subspecies_independent"
        fig.add_trace(
            go.Scatter(
                x=[event.generation, event.generation],
                y=[total_rows - index[parent], total_rows - index[event.encoding]],
                mode="lines",
                line=dict(
                    color="#d62728" if independent_child else "#888888",
                    width=2 if independent_child else 1,
                    dash="solid" if independent_child else "dash",
                ),
                showlegend=False,
                hoverinfo="skip",
            )
        )

    fig.update_layout(
        height=max(340, 64 * total_rows + 140),
        title=(
            "演化树（◇=亚种生成，★=独立为新物种，虚线=亚种，实线=独立，"
            "节点大小=峰值规模）"
        ),
        xaxis=dict(title="代数"),
        yaxis=dict(showticklabels=False, range=[-0.2, total_rows + 1.4]),
        margin=dict(l=40, r=180, t=60, b=40),
        plot_bgcolor="#fafafa",
    )
    return fig


def event_rows(sim: TrustEvolution) -> list[dict]:
    """Flatten the event log into rows for a table."""
    return [
        {
            "代数": event.generation,
            "事件": _EVENT_LABELS.get(event.event, event.event),
            "编码": event.encoding,
            "父代": event.parent_encoding or "-",
        }
        for event in sim.events
    ]


def _independence_generation(sim: TrustEvolution, encoding: str) -> int | None:
    generations = [
        event.generation
        for event in sim.events
        if event.event == "subspecies_independent" and event.encoding == encoding
    ]
    return min(generations) if generations else None


def lineage_color(sim: TrustEvolution, encoding: str, generation: int) -> str:
    """Color for an encoding as of a given generation."""
    independence = _independence_generation(sim, encoding)
    if independence is not None and independence <= generation:
        return independent_color(encoding)
    return family_color(encoding)


def _delta(value: int) -> str:
    if value > 0:
        return f"▲{value}"
    if value < 0:
        return f"▼{abs(value)}"
    return "─"


def _lineage_groups(sim: TrustEvolution, generation: int) -> list[tuple]:
    """Lineages of one generation, largest total first.

    Each tuple is ``(encoding, parent_size, subspecies, subspecies_size, total)``.
    """
    generation = max(0, min(generation, len(sim.generation_records) - 1))
    record = sim.generation_records[generation]
    groups: list[tuple] = []
    for encoding, data in record.species_data.items():
        parent = data.get("population_size", 0)
        subspecies = data.get("subspecies")
        sub_size = subspecies["size"] if subspecies else 0
        total = parent + sub_size
        if total > 0:
            groups.append((encoding, parent, subspecies, sub_size, total))
    groups.sort(key=lambda group: group[4], reverse=True)
    return groups


def _bar_entries(
    sim: TrustEvolution, generation: int, names: dict[str, str] | None = None
) -> list[tuple]:
    """Bar entries (label, code, size, color, hatched) with the subspecies
    pinned directly below its parent."""
    entries: list[tuple] = []
    for encoding, parent, subspecies, sub_size, _ in _lineage_groups(sim, generation):
        color = lineage_color(sim, encoding, generation)
        display = _display_name(names, encoding)
        if parent > 0:
            entries.append((display, encoding, parent, color, False))
        if subspecies and sub_size > 0:
            entries.append(
                (
                    f"　└ {_display_name(names, subspecies['encoding'])}",
                    subspecies["encoding"],
                    sub_size,
                    family_color(subspecies["encoding"]),
                    True,
                )
            )
    return entries


def _pie_entries(
    sim: TrustEvolution, generation: int, names: dict[str, str] | None = None
) -> list[tuple]:
    """Pie slices (label, code, size, color, hatched); subspecies shade the parent."""
    entries: list[tuple] = []
    for encoding, parent, subspecies, sub_size, _ in _lineage_groups(sim, generation):
        color = lineage_color(sim, encoding, generation)
        display = _display_name(names, encoding)
        if parent > 0:
            entries.append((display, encoding, parent, color, False))
        if subspecies and sub_size > 0:
            entries.append(
                (
                    f"　└ {_display_name(names, subspecies['encoding'])}",
                    subspecies["encoding"],
                    sub_size,
                    color,
                    True,
                )
            )
    return entries


def build_distribution_bar(
    sim: TrustEvolution,
    generation: int,
    names: dict[str, str] | None = None,
) -> go.Figure:
    """Horizontal bar chart of every species and subspecies at one generation.

    Each subspecies bar sits directly below its parent, not sorted by size.
    """
    entries = _bar_entries(sim, generation, names)
    if not entries:
        fig = go.Figure()
        fig.update_layout(height=320, title="该轮没有存活策略", plot_bgcolor="#fafafa")
        return fig

    labels = [entry[0] for entry in entries]
    codes = [entry[1] for entry in entries]
    values = [entry[2] for entry in entries]
    colors = [entry[3] for entry in entries]
    patterns = ["/" if entry[4] else "" for entry in entries]
    fig = go.Figure(
        go.Bar(
            x=values,
            y=labels,
            orientation="h",
            marker=dict(
                color=colors,
                pattern=dict(shape=patterns, fgcolor="white", fillmode="overlay"),
            ),
            text=[str(value) for value in values],
            textposition="outside",
            customdata=codes,
            hovertemplate="%{y}<br>编码 %{customdata}<br>规模 %{x}<extra></extra>",
        )
    )
    fig.update_layout(
        height=max(320, 34 * len(labels) + 120),
        title=f"第 {generation} 轮物种分布",
        xaxis=dict(title="规模", range=[0, TOTAL_CAPACITY], fixedrange=True),
        yaxis=dict(title="", autorange="reversed"),
        margin=dict(l=10, r=40, t=50, b=40),
        plot_bgcolor="#fafafa",
    )
    return fig


def build_distribution_pie(
    sim: TrustEvolution,
    generation: int,
    names: dict[str, str] | None = None,
) -> go.Figure:
    """Pie of lineages; non-independent subspecies shade their parent's region."""
    entries = _pie_entries(sim, generation, names)
    if not entries:
        fig = go.Figure()
        fig.update_layout(height=340, title="该轮没有存活策略")
        return fig
    labels = [entry[0] for entry in entries]
    codes = [entry[1] for entry in entries]
    values = [entry[2] for entry in entries]
    colors = [entry[3] for entry in entries]
    patterns = ["/" if entry[4] else "" for entry in entries]
    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=values,
            customdata=codes,
            marker=dict(
                colors=colors,
                line=dict(color="#ffffff", width=1),
                pattern=dict(shape=patterns, fgcolor="rgba(255,255,255,0.85)", fillmode="overlay"),
            ),
            hole=0.45,
            sort=False,
            textinfo="label+percent",
            hovertemplate="%{label}<br>编码 %{customdata}<br>规模 %{value}<extra></extra>",
        )
    )
    fig.update_layout(
        height=360,
        title=f"第 {generation} 轮构成",
        margin=dict(l=10, r=10, t=50, b=10),
        showlegend=False,
    )
    return fig


def build_change_rows(
    sim: TrustEvolution,
    generation: int,
    names: dict[str, str] | None = None,
) -> list[dict]:
    """Per-strategy size changes between a generation and the previous one."""
    current = sim.generation_records[generation].species_data
    previous = (
        sim.generation_records[generation - 1].species_data if generation > 0 else {}
    )
    events = [event for event in sim.events if event.generation == generation]
    born = {event.encoding for event in events if event.event == "subspecies_birth"}
    independent = {
        event.encoding for event in events if event.event == "subspecies_independent"
    }
    extinct = {event.encoding for event in events if event.event == "extinction"}
    sub_extinct = {
        event.encoding for event in events if event.event == "subspecies_extinction"
    }

    parent_rows: list[dict] = []
    encodings = list(dict.fromkeys([*previous.keys(), *current.keys()]))
    for encoding in encodings:
        prev = previous.get(encoding, {})
        curr = current.get(encoding, {})
        prev_parent = prev.get("population_size", 0)
        curr_parent = curr.get("population_size", 0)
        prev_sub = prev.get("subspecies") or {}
        curr_sub = curr.get("subspecies") or {}
        prev_sub_size = prev_sub.get("size", 0)
        curr_sub_size = curr_sub.get("size", 0)
        prev_total = prev_parent + prev_sub_size
        curr_total = curr_parent + curr_sub_size

        marks: list[str] = []
        if encoding in extinct:
            marks.append("物种灭绝")
        if encoding in independent:
            marks.append("亚种独立为新物种")
        if encoding not in previous and encoding in current and encoding not in independent:
            marks.append("新增策略")

        parent_row = {
            "策略": _display_name(names, encoding),
            "原物种规模": f"{prev_parent} → {curr_parent}  {_delta(curr_parent - prev_parent)}",
            "亚种规模": "—",
            "合计": f"{prev_parent} → {curr_parent}",
            "合计变化": _delta(curr_parent - prev_parent),
            "事件": "、".join(marks),
            "_abs_change": abs(curr_total - prev_total),
            "_sub": None,
        }

        if prev_sub or curr_sub:
            sub_marks: list[str] = []
            if curr_sub.get("encoding") in born:
                sub_marks.append("亚种生成")
            if prev_sub.get("encoding") in sub_extinct:
                sub_marks.append("亚种淘汰")
            if encoding in independent:
                sub_marks.append("独立为新物种")
            sub_encoding = curr_sub.get("encoding") or prev_sub.get("encoding") or ""
            parent_row["_sub"] = {
                "策略": f"　└ 亚种 {_display_name(names, sub_encoding)}",
                "原物种规模": "—",
                "亚种规模": f"{prev_sub_size} → {curr_sub_size}  {_delta(curr_sub_size - prev_sub_size)}",
                "合计": f"{prev_sub_size} → {curr_sub_size}",
                "合计变化": _delta(curr_sub_size - prev_sub_size),
                "事件": "、".join(sub_marks),
            }
        parent_rows.append(parent_row)

    parent_rows.sort(key=lambda row: row["_abs_change"], reverse=True)
    rows: list[dict] = []
    for row in parent_rows:
        sub_row = row.pop("_sub")
        row.pop("_abs_change")
        rows.append(row)
        if sub_row is not None:
            rows.append(sub_row)
    return rows


def build_fitness_rows(
    sim: TrustEvolution,
    generation: int,
    names: dict[str, str] | None = None,
) -> list[dict]:
    """Per-strategy fitness for one generation.

    Species are sorted by fitness, but each subspecies is pinned directly
    beneath its parent. A subspecies is a single population, so its mixed
    fitness equals its own fitness (never ``None``).
    """
    generation = max(0, min(generation, len(sim.generation_records) - 1))
    record = sim.generation_records[generation]
    parent_rows: list[dict] = []
    for encoding, data in record.species_data.items():
        subspecies = data.get("subspecies")
        sub_row = None
        if subspecies:
            sub_fitness = round(subspecies.get("fitness", 0.0), 2)
            sub_row = {
                "策略": f"　└ 亚种 {_display_name(names, subspecies['encoding'])}",
                "适应度": sub_fitness,
                "混合适应度": sub_fitness,
            }
        parent_rows.append(
            {
                "策略": _display_name(names, encoding),
                "适应度": round(data.get("fitness", 0.0), 2),
                "混合适应度": round(data.get("mixed_fitness", 0.0), 2),
                "_sub": sub_row,
            }
        )
    parent_rows.sort(key=lambda row: row["适应度"], reverse=True)
    rows: list[dict] = []
    for row in parent_rows:
        sub_row = row.pop("_sub")
        rows.append(row)
        if sub_row is not None:
            rows.append(sub_row)
    return rows


def events_at(
    sim: TrustEvolution,
    generation: int,
    names: dict[str, str] | None = None,
) -> list[dict]:
    """Special events that created a given generation."""
    rows: list[dict] = []
    for event in sim.events:
        if event.generation != generation:
            continue
        _, label, color = _EVENT_STYLE.get(event.event, ("", event.event, "#333333"))
        rows.append(
            {
                "事件": label,
                "编码": _display_name(names, event.encoding),
                "父代": (
                    _display_name(names, event.parent_encoding)
                    if event.parent_encoding
                    else "-"
                ),
                "color": color,
            }
        )
    return rows
