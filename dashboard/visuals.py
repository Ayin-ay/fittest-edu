"""Charts for the game-mode behaviour report.

The Markdown profile states what happened; these figures are what a player can
actually read at a glance. Four views, each answering a different question:

* **radar** - the nine measured dimensions at once, so a shape is visible rather
  than a list of numbers;
* **score trend** - per-match score against the field, which separates "did well
  throughout" from "one big win then decline";
* **action map** - every decision as a cell (player action x opponent action) in
  match/turn order, so the shape of the whole session is a picture;
* **rate bars** - the handful of rates that carry the interpretation, with the
  gap between "punished" and "exploited" made explicit.

No chart here assigns a label; the titles are the measured quantity itself.
"""

from __future__ import annotations

import plotly.graph_objects as go

from dashboard.profiling import Dimension
from dashboard.theme import apply_chart_theme

# Radar axes need a common 0-1 scale, so each dimension contributes a value that
# is meaningful in isolation. The scale for each is chosen so that 0.5 is the
# neutral middle for that behaviour, not an arbitrary midpoint.
RADAR_SPECS = [
    # (key, label, fn(dimension) -> 0..1)
    ("opening", "开局合作", lambda n: n.get("rate", 0.0)),
    ("retaliation", "回击倾向", lambda n: n.get("rate", 0.0)),
    ("exploitation", "主动剥削", lambda n: n.get("rate", 0.0)),
    ("discrimination", "对手区分度", lambda n: n.get("spread", 0.0)),
    ("endgame", "终局转向", lambda n: min(max(n.get("shift", 0.0) + 0.5, 0.0), 1.0)),
    ("punishment_duration", "回击长度", lambda n: min(n.get("mean", 0.0) / 4.0, 1.0)),
    ("efficiency", "单步收益效率", lambda n: n.get("efficiency", 0.0)),
    ("leverage", "影响力", lambda n: n.get("moved", 0.0) / max(n.get("total", 1), 1)),
    ("consistency", "情境一致性", lambda n: n.get("rate", 0.0) or 0.0),
]

# The "opening" radar axis is cooperation (high = opens friendly) while the two
# aggression axes are defection (high = strikes first). Mixing those directions in
# one filled shape would read as a personality blob, so the caption states the
# direction of each axis explicitly.
RADAR_DIRECTION = {
    "opening": "高=先示好",
    "retaliation": "高=被背叛必还手",
    "exploitation": "高=对方合作也出手",
    "discrimination": "高=按对手区别对待",
    "endgame": "高=越到后面越硬",
    "punishment_duration": "高=报复拖得久",
    "efficiency": "高=不浪费单步收益",
    "leverage": "高=能撬动对手",
    "consistency": "高=同情境同答案",
}


def dimension_scores(profile: dict) -> list[dict]:
    """The nine dimensions as comparable 0-1 scores, plus what high means.

    Reused by the score cards so the at-a-glance numbers and the radar shape
    can never disagree. Direction matters: a high number is good on some axes
    and bad on others, so every card carries its own reading.
    """
    by_key = {d.key: d for d in profile["dimensions"]}
    rows = []
    for key, label, extract in RADAR_SPECS:
        dimension = by_key.get(key)
        numbers = dimension.numbers if dimension else {}
        try:
            value = float(extract(numbers)) if numbers else 0.0
        except (TypeError, ValueError, ZeroDivisionError):
            value = 0.0
        value = min(max(value, 0.0), 1.0)
        rows.append({
            "key": key,
            "label": label,
            "title": dimension.title if dimension else label,
            "value": round(value, 3),
            "percent": int(round(value * 100)),
            "direction": RADAR_DIRECTION.get(key, ""),
            "measured": dimension.value if dimension else "",
        })
    return rows


def build_score_cards(profile: dict) -> "go.Figure":
    """A compact bar per dimension, ordered so the extremes are easy to spot."""
    rows = dimension_scores(profile)
    fig = go.Figure(
        data=go.Bar(
            x=[r["percent"] for r in rows],
            y=[r["label"] for r in rows],
            orientation="h",
            marker_color=[
                "#d62728" if r["percent"] >= 70 else
                "#ff7f0e" if r["percent"] >= 40 else
                "#2ca02c" if r["percent"] > 0 else "#cccccc"
                for r in rows
            ],
            text=["{}%　{}".format(r["percent"], r["direction"]) for r in rows],
            textposition="auto",
            hovertemplate="%{y}<br>得分 %{x}%<extra></extra>",
        )
    )
    fig.update_layout(
        xaxis=dict(title="该维度上的位置（高不一定更好，看右侧说明）",
                   range=[0, 118], tickformat=".0%"),
        height=max(320, 34 * len(rows) + 90),
        showlegend=False,
        margin=dict(l=110, r=210, t=20, b=50),
    )
    return apply_chart_theme(fig)


def build_radar(profile: dict) -> go.Figure:
    by_key = {d.key: d for d in profile["dimensions"]}
    labels, values, directions = [], [], []
    for key, label, extract in RADAR_SPECS:
        dimension: Dimension | None = by_key.get(key)
        numbers = dimension.numbers if dimension else {}
        labels.append(label)
        values.append(extract(numbers) if numbers else 0.0)
        directions.append(RADAR_DIRECTION.get(key, ""))
    closed = labels + [labels[0]]
    closed_values = values + [values[0]]
    fig = go.Figure(
        data=go.Scatterpolar(
            r=closed_values,
            theta=closed,
            fill="toself",
            name="本次",
            line=dict(color="#1f77b4"),
        )
    )
    fig.update_layout(
        polar=dict(
            radialaxis=dict(visible=True, range=[0, 1], tickvals=[0, 0.5, 1]),
        ),
        title="九项指标（数值越大不等于越好，请看下方方向说明）",
        height=480,
        showlegend=False,
        margin=dict(l=60, r=60, t=70, b=40),
        annotations=[{
            "text": "　".join(
                "{}：{}".format(l, d) for l, d in zip(labels, directions)
            ),
            "showarrow": False, "xref": "paper", "yref": "paper",
            "x": 0.5, "y": -0.06, "font": {"size": 10},
        }],
    )
    return apply_chart_theme(fig)


def build_score_trend(profile: dict, results: dict) -> go.Figure:
    matches = profile["matches"]
    codes = results["detail_axis"][1:]
    player = [m.player_score for m in matches]
    opponent = [m.opponent_score for m in matches]
    best_field = sorted(
        results["table"][1:], key=lambda r: -r["vs_others"]
    )[0]["vs_others"] if len(results["table"]) > 1 else 0.0

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=list(range(1, len(matches) + 1)),
        y=player, mode="lines+markers", name="你",
        line=dict(color="#1f77b4", width=2.5),
        text=[c[:18] for c in codes[:len(matches)]],
        hovertemplate="第 %{x} 局<br>你 %{y} 分<br>对手 %{customdata}<extra></extra>",
        customdata=[o for o in opponent],
    ))
    fig.add_trace(go.Scatter(
        x=list(range(1, len(matches) + 1)),
        y=opponent, mode="lines+markers", name="对手",
        line=dict(color="#d62728", width=1.5, dash="dot"),
    ))
    fig.add_hline(
        y=best_field, line_dash="dash", line_color="#888",
        annotation_text="策略平均分 {:.1f}".format(best_field),
        annotation_position="top left",
    )
    fig.update_layout(
        title="逐局得分（悬停看对手编码）",
        xaxis=dict(title="第几局", dtick=1),
        yaxis=dict(title="本局得分"),
        height=380,
        margin=dict(l=60, r=20, t=50, b=40),
        legend=dict(orientation="h", y=1.12),
    )
    return apply_chart_theme(fig)


def build_action_map(profile: dict) -> go.Figure:
    """Every decision as a cell, ordered by match then turn."""
    z: list[list[int]] = []
    text: list[list[str]] = []
    for match in profile["matches"]:
        row_z, row_text = [], []
        for d in match.decisions:
            # 0 mutual C, 1 player C only, 2 player D only, 3 mutual D
            if d.action == "C":
                value = 0 if d.opponent_action == "C" else 1
            else:
                value = 2 if d.opponent_action == "C" else 3
            row_z.append(value)
            row_text.append("{}{}".format(
                "你" if d.action == "C" else "你",
                "合" if d.opponent_action == "C" else "背",
            ))
        z.append(row_z)
        text.append(row_text)

    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            text=text,
            texttemplate="%{text}",
            colorscale=[[0, "#2ca02c"], [0.33, "#c7e9c0"], [0.66, "#f7c7c7"], [1, "#d62728"]],
            zmin=0, zmax=3,
            colorbar=dict(
                tickvals=[0, 1, 2, 3],
                ticktext=["互相合作", "你合对手背", "你背对手合", "互相背叛"],
                thickness=12, len=0.7,
            ),
            hovertemplate="第 %{y} 局 第 %{x} 轮<br>%{text}<extra></extra>",
        )
    )
    fig.update_layout(
        title="全部 {} 步决策的落点".format(profile["total_turns"]),
        xaxis=dict(title="第几轮", dtick=1),
        yaxis=dict(title="第几局", dtick=1, autorange="reversed"),
        height=420,
        margin=dict(l=70, r=20, t=50, b=40),
    )
    return apply_chart_theme(fig)


def build_rate_bars(profile: dict) -> go.Figure:
    """The rates that carry the interpretation, side by side."""
    by_key = {d.key: d for d in profile["dimensions"]}
    items = [
        ("被背叛后回击", by_key.get("retaliation")),
        ("对手合作时出手", by_key.get("exploitation")),
        ("对手背叛时忍让", by_key.get("retaliation")),
    ]
    labels, values, colors, texts = [], [], [], []
    retaliation = by_key.get("retaliation")
    exploitation = by_key.get("exploitation")
    if retaliation is not None:
        n = retaliation.numbers
        labels.append("被背叛后回击")
        values.append(n.get("rate", 0.0))
        texts.append("{}/{} 步".format(n.get("retaliated", 0), n.get("provoked", 0)))
        colors.append("#d62728")
        labels.append("被背叛时继续合作")
        values.append(1.0 - n.get("rate", 0.0))
        texts.append("{}/{} 步".format(n.get("forgave", 0), n.get("provoked", 0)))
        colors.append("#2ca02c")
    if exploitation is not None:
        n = exploitation.numbers
        labels.append("对手合作时主动出手")
        values.append(n.get("rate", 0.0))
        texts.append("{}/{} 步".format(n.get("exploits", 0), n.get("opportunities", 0)))
        colors.append("#ff7f0e")
    if by_key.get("opening") is not None:
        n = by_key["opening"].numbers
        labels.append("首轮选择合作")
        values.append(n.get("rate", 0.0))
        texts.append("{}/{} 场".format(n.get("opens", 0), n.get("matches", 0)))
        colors.append("#1f77b4")

    fig = go.Figure(
        data=go.Bar(
            x=values, y=labels, orientation="h",
            marker_color=colors,
            text=[t for t in texts],
            textposition="auto",
            hovertemplate="%{y}<br>比例 %{x:.0%}<br>%{text}<extra></extra>",
        )
    )
    fig.update_layout(
        title="关键比率（回击与主动出手分开看，含义不同）",
        xaxis=dict(title="占全部相关机会的比例", range=[0, 1.15], tickformat=".0%"),
        height=300,
        margin=dict(l=160, r=40, t=50, b=40),
    )
    return apply_chart_theme(fig)


def build_field_standing(profile: dict, results: dict) -> go.Figure:
    """Where the player sits among the eleven, on both measures."""
    table = sorted(results["table"], key=lambda r: -r["vs_others"])
    labels = [r["name"] for r in table]
    values = [r["vs_others"] for r in table]
    is_player = [r["is_player"] for r in table]
    colors = ["#1f77b4" if p else "#cccccc" for p in is_player]
    fig = go.Figure(
        data=go.Bar(
            x=values, y=labels, orientation="h",
            marker_color=colors,
            text=[("你 " if p else "") + "{:.1f}".format(v)
                  for p, v in zip(is_player, values)],
            textposition="auto",
            hovertemplate="%{y}<br>平均总得分 %{x:.1f}<extra></extra>",
        )
    )
    fig.update_layout(
        title="平均总得分排名（蓝=你，灰=生成策略）",
        xaxis=dict(title="对其他策略的平均得分"),
        height=max(340, 26 * len(table) + 120),
        margin=dict(l=90, r=40, t=50, b=40),
    )
    return apply_chart_theme(fig)
