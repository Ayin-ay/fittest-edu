"""Match engine for the game mode: a human against generated strategies.

The point of this module is not to run matches, it is to *record* them finely
enough that a profile can be built from evidence rather than from impression.
Every single decision the player makes is stored together with

* which opponent it was against, and that opponent's decoded modules;
* the full action history on both sides up to that moment;
* the payoff the chosen action earned, and the payoff the alternative would have
  earned in the same state;
* a counterfactual: what the opponent would have played next had the player
  chosen the other action.

The counterfactual is what keeps the downstream analysis honest. "You retaliated
fast" is a label; "on match 4 you switched to D one turn after being defected on,
which cost you 0.00 immediate points but changed the opponent's next move from C
to D" is a measurement.
"""

from __future__ import annotations

import copy
import random
from dataclasses import asdict, dataclass, field
from typing import Callable

from dashboard.theme import apply_chart_theme

from strategy_engine.strategy_engine import (
    StrategyState,
    parse_strategy,
    random_strategy,
)
from trust_evolution_simulation import PAYOFFS

PLAYER = "玩家"
# Short handles for the heatmap axes; the full code stays available on hover and
# in the results table.
GAMEPLAY_SHORT = [
    "策1", "策2", "策3", "策4", "策5", "策6", "策7", "策8", "策9", "策10",
    "策11", "策12",
]


@dataclass
class Decision:
    """One turn of a player match, with everything needed to reason about it."""

    match_index: int
    turn: int
    total_turns: int
    opponent: str
    opponent_label: str
    player_history: str          # e.g. "CDDC"
    opponent_history: str       # e.g. "CCDD"
    action: str
    opponent_action: str
    payoff: float
    alternative: str
    alternative_payoff: float
    immediate_delta: float      # alternative_payoff - payoff
    opponent_next_if_chosen: str
    opponent_next_if_alternative: str
    # Whether the opponent was still "new" from the player's point of view.
    is_first_round: bool = False
    is_final_round: bool = False

    @property
    def provoked(self) -> bool:
        """The opponent defected on the previous turn."""
        return bool(self.opponent_history) and self.opponent_history[-1] == "D"

    @property
    def player_just_defected(self) -> bool:
        return bool(self.player_history) and self.player_history[-1] == "D"


@dataclass
class Match:
    """A finished match between the player and one generated strategy."""

    index: int
    opponent: str
    opponent_label: str
    turns: int
    player_actions: str
    opponent_actions: str
    player_score: float
    opponent_score: float
    opponent_open_rate: float
    opponent_defection_rate: float
    mutual_cooperations: int
    decisions: list[Decision] = field(default_factory=list)

    @property
    def player_coop_rate(self) -> float:
        return self.player_actions.count("C") / max(len(self.player_actions), 1)


def opponent_label(encoding: str) -> str:
    """Readable tag for a strategy, built from its decoded modules."""
    definition = parse_strategy(encoding)
    parts = [definition.default.kind]
    for module in definition.triggers:
        parts.append(module.kind)
    if definition.modifier is not None:
        parts.append(definition.modifier.kind)
    return "+".join(parts)


def _whole(value: float) -> str:
    """Format a payoff without a pointless decimal: 3.0 -> 3, 2.5 -> 2.5."""
    return str(int(value)) if float(value).is_integer() else str(round(value, 2))


def action_badge(action: str, who: str) -> str:
    """One large, unmistakable cell: the letter plus its Chinese name.

    The colours come from ``dashboard.theme`` so the badges match the action
    buttons: cooperation is blue and defection is orange everywhere. They used
    to be GitHub-style green and red, which read as "good" and "bad" and
    disagreed with the buttons sitting right above them.
    """
    from dashboard import theme

    cooperate = action == "C"
    colour = theme.COOP if cooperate else theme.DEFECT
    background = theme.COOP_WASH if cooperate else theme.DEFECT_WASH
    word = "合作" if cooperate else "背叛"
    return (
        "<span style='display:inline-block;min-width:62px;padding:4px 10px;"
        "border-radius:8px;background:{bg};color:{fg};font-weight:700;"
        "font-size:16px;letter-spacing:1px;text-align:center'>"
        "<span style='font-size:18px'>{letter}</span> {word}"
        "<span style='display:none'>{who}</span></span>"
    ).format(bg=background, fg=colour, letter=action, word=word, who=who)


# What the round was, from the player's side: the four combinations, each named
# for what it did rather than for the score it produced.
RELATIONSHIPS = {
    ("C", "C"): ("共赢", "#21A179"),
    ("D", "D"): ("互害", "#6B6156"),
    ("D", "C"): ("背刺", "#E4572E"),
    ("C", "D"): ("被剥削", "#2E7DE4"),
}


def _relationship(my_action: str, their_action: str) -> str:
    """Label one round by the pair of actions, with the running score beneath."""
    label, colour = RELATIONSHIPS[(my_action, their_action)]
    gap = ""
    return (
        "<div style='font-weight:700;color:%s'>%s</div>"
        "<div style='font-size:12px;color:%s'>%s</div>"
        % (colour, label, "#6B6156", gap)
    )


def history_table(
    mine: str,
    theirs: str,
    turns: int | None = None,
    highlight: int | None = None,
) -> str:
    """Per-turn history as a readable table.

    The bare ``CDDDC`` string is unreadable on its own: the letters have to be
    decoded, the two sides sit on one line, and there is no sign of who scored
    what. This lays it out one turn per row with the words 合作/背叛, the
    payoff for that round, and a running total.
    """
    from dashboard import theme
    from trust_evolution_simulation import PAYOFFS

    count = turns if turns is not None else max(len(mine), len(theirs))
    if count == 0:
        return (
            "<div style='color:%s;padding:6px 0'>还没有任何一轮记录。</div>"
            % theme.MUTED
        )

    my_running = 0
    their_running = 0
    body = []
    for turn in range(count):
        my_action = mine[turn] if turn < len(mine) else None
        their_action = theirs[turn] if turn < len(theirs) else None
        if my_action and their_action:
            my_points, their_points = PAYOFFS[(my_action, their_action)]
            my_running += my_points
            their_running += their_points
            outcome = _relationship(my_action, their_action)
            points = "<b style='color:%s'>+%s</b> / %s" % (
                theme.INK, _whole(my_points), _whole(their_points))
        else:
            outcome = "<span style='color:%s'>未进行</span>" % theme.MUTED
            points = "<span style='color:%s'>—</span>" % theme.MUTED

        row_style = ("background:%s;" % theme.RAISED) if highlight == turn else ""
        my_cell = action_badge(my_action, "你") if my_action else "—"
        their_cell = action_badge(their_action, "对手") if their_action else "—"
        body.append(
            "<tr style='{row}'>"
            "<td style='text-align:center;color:{muted}'>{turn}</td>"
            "<td style='text-align:center'>{mine}</td>"
            "<td style='text-align:center'>{theirs}</td>"
            "<td style='text-align:center'>{points}</td>"
            "<td style='text-align:center'>{outcome}</td>"
            "</tr>".format(
                row=row_style, turn=turn + 1, mine=my_cell,
                theirs=their_cell, points=points, outcome=outcome,
                muted=theme.MUTED,
            )
        )

    def head_cell(label: str) -> str:
        return (
            "<th style='border-bottom:2px solid " + theme.LINE
            + ";padding:6px 4px;color:" + theme.MUTED
            + ";font-weight:600'>" + label + "</th>"
        )

    headers = (
        head_cell("轮次")
        + head_cell("你的选择")
        + head_cell("对手选择")
        + head_cell("本轮得分<br>你/对手")
        + head_cell("累计")
    )
    return (
        "<div style='overflow-x:auto;margin:0.4rem 0 0.8rem'>"
        "<table style='border-collapse:collapse;width:100%;max-width:640px;"
        "font-size:15px'>"
        "<thead><tr>" + headers + "</tr></thead>"
        "<tbody>" + "".join(body) + "</tbody></table>"
        "<div style='color:" + theme.MUTED + ";font-size:14px;margin-top:4px'>"
        "合计　你 <b style='font-size:16px'>" + str(_whole(my_running)) + "</b> 分　"
        "对手 <b style='font-size:16px'>" + str(_whole(their_running)) + "</b> 分"
        "</div></div>"
    )


def draw_opponents(count: int, seed: int) -> list[str]:
    """`count` distinct strategies from the engine's own generator."""
    rng = random.Random(seed)
    picked: list[str] = []
    seen: set[str] = set()
    while len(picked) < count:
        code = random_strategy(rng).code
        if code in seen:
            continue
        seen.add(code)
        picked.append(code)
    return picked


class PlayerMatchRunner:
    """Plays one match turn by turn so the UI can ask the player for each action.

    The opponent's state is snapshotted before every one of its decisions. That
    snapshot is what makes the counterfactual exact: cloning it and advancing
    with the action the player *did not* take gives the opponent's real next move
    on the counterfactual branch, including any probabilistic modifier state.
    """

    def __init__(self, index: int, opponent: str, turns: int, seed: int):
        self.index = index
        self.opponent = opponent
        self.opponent_label = opponent_label(opponent)
        self.turns = turns
        self.rng = random.Random(seed)
        self.state = StrategyState(
            parse_strategy(opponent), turns, rng=self.rng
        )
        self.player_history: list[str] = []
        self.opponent_history: list[str] = []
        self.player_score = 0.0
        self.opponent_score = 0.0
        self.decisions: list[Decision] = []
        self._pending_snapshot: StrategyState | None = None
        self._pending_opponent_action: str | None = None

    @property
    def finished(self) -> bool:
        return len(self.player_history) >= self.turns

    @property
    def turn_number(self) -> int:
        return len(self.player_history) + 1

    def _opponent_state_for_next_move(self) -> StrategyState:
        """Snapshot the opponent right before it would move.

        Called at the start of each round: the opponent's state at that instant
        is exactly what it would use to answer the player's current action.
        """
        snapshot = copy.deepcopy(self.state)
        # Feeding it the current histories makes the clone's ``decide`` start from
        # the live position instead of an empty one.
        snapshot.own_history = list(self.opponent_history)
        snapshot.opponent_history = list(self.player_history)
        return snapshot

    def prompt(self) -> dict:
        """State to show the player before they choose."""
        return {
            "index": self.index,
            "turn": self.turn_number,
            "total_turns": self.turns,
            "opponent": self.opponent,
            "opponent_label": self.opponent_label,
            "player_history": "".join(self.player_history),
            "opponent_history": "".join(self.opponent_history),
            "last_opponent": self.opponent_history[-1] if self.opponent_history else None,
        }

    def _next_reply_under(self, snapshot: StrategyState, player_action: str) -> str:
        """The opponent's *next-round* reply if the player had played ``player_action``.

        The player moves first within a round, so the opponent's reply in the
        current round is already fixed and does not depend on this choice. The
        clone therefore replays that reply unchanged to reach the start of the
        next round, where the counterfactual branch finally matters. Both
        branches go through this same path, so the two recorded replies are
        directly comparable -- comparing this round's reply against next round's
        would mix two different questions.
        """
        clone = copy.deepcopy(snapshot)
        clone.decide(list(self.player_history))
        history = list(self.player_history) + [player_action]
        return clone.decide(history)

    def play(self, action: str) -> Decision:
        """Record the player's action and the opponent's reply."""
        if self.finished:
            raise ValueError("match already finished")
        if action not in ("C", "D"):
            raise ValueError("action must be 'C' or 'D'")

        turn = self.turn_number
        snapshot = self._opponent_state_for_next_move()
        other = "D" if action == "C" else "C"
        next_if_chosen = self._next_reply_under(snapshot, action)
        next_if_alternative = self._next_reply_under(snapshot, other)

        opponent_action = self.state.decide(self.player_history)
        my_points, their_points = PAYOFFS[(action, opponent_action)]
        self.player_score += my_points
        self.opponent_score += their_points

        alternative_payoff = PAYOFFS[(other, opponent_action)][0]

        decision = Decision(
            match_index=self.index,
            turn=turn,
            total_turns=self.turns,
            opponent=self.opponent,
            opponent_label=self.opponent_label,
            player_history="".join(self.player_history),
            opponent_history="".join(self.opponent_history),
            action=action,
            opponent_action=opponent_action,
            payoff=my_points,
            alternative=other,
            alternative_payoff=alternative_payoff,
            immediate_delta=alternative_payoff - my_points,
            opponent_next_if_chosen=next_if_chosen,
            opponent_next_if_alternative=next_if_alternative,
            is_first_round=turn == 1,
            is_final_round=turn == self.turns,
        )
        self.decisions.append(decision)

        self.player_history.append(action)
        self.opponent_history.append(opponent_action)
        return decision

    def _counterfactual_next(self, snapshot: StrategyState, chosen: str) -> str:
        """Deprecated shim kept out of the hot path; see _next_reply_under."""
        return self._next_reply_under(
            snapshot, "D" if chosen == "C" else "C"
        )

    def player_actions_view(self) -> str:
        return "".join(self.player_history)

    def opponent_actions_view(self) -> str:
        return "".join(self.opponent_history)

    def opponent_next_action(self) -> str:
        """What the opponent would play next, without disturbing the match.

        Needed by the tutorial, which has to price both options before the
        player commits. ``StrategyState.decide`` is not safe to call for this:
        it records the move into the engine's own history, so calling it as a
        preview would consume the turn. The state is therefore deep-copied,
        the question asked of the copy, and the original left untouched.
        """
        if self.finished:
            return self.opponent_history[-1] if self.opponent_history else "C"
        probe = copy.deepcopy(self.state)
        return probe.decide(self.player_history)

    def finish(self) -> Match:
        mutual = sum(
            1 for mine, theirs in zip(self.player_history, self.opponent_history)
            if mine == "C" and theirs == "C"
        )
        opponents_defect = sum(1 for a in self.opponent_history if a == "D")
        return Match(
            index=self.index,
            opponent=self.opponent,
            opponent_label=self.opponent_label,
            turns=self.turns,
            player_actions="".join(self.player_history),
            opponent_actions="".join(self.opponent_history),
            player_score=self.player_score,
            opponent_score=self.opponent_score,
            opponent_open_rate=(
                self.opponent_history.count("C") / max(len(self.opponent_history), 1)
            ),
            opponent_defection_rate=opponents_defect / max(len(self.opponent_history), 1),
            mutual_cooperations=mutual,
            decisions=list(self.decisions),
        )


def play_auto_match(code_a: str, code_b: str, turns: int, seed: int) -> tuple[float, float, str, str]:
    """Two strategies play each other. Returns scores and both action strings."""
    rng = random.Random(seed)
    a = StrategyState(parse_strategy(code_a), turns, rng=rng)
    b = StrategyState(parse_strategy(code_b), turns, rng=rng)
    a_history: list[str] = []
    b_history: list[str] = []
    a_score = b_score = 0.0
    for _ in range(turns):
        action_a = a.decide(b_history)
        action_b = b.decide(a_history)
        a_history.append(action_a)
        b_history.append(action_b)
        points_a, points_b = PAYOFFS[(action_a, action_b)]
        a_score += points_a
        b_score += points_b
    return a_score, b_score, "".join(a_history), "".join(b_history)


def build_results(
    matches: list[Match], tournament: dict, turns: int
) -> dict:
    """Combine the player's row with the strategy-vs-strategy matrix.

    Row/column 0 is the player, 1..n are the generated strategies. The diagonal
    is left empty on purpose: a strategy has never played itself here, and a
    fabricated number there would invite the reader to compare incomparable
    cells.
    """
    codes = tournament["codes"]
    size = len(codes)
    axis = ["玩家"] + [GAMEPLAY_SHORT[i] for i in range(size)]
    detail_axis = ["玩家"] + codes

    z: list[list[float | None]] = [[None] * (size + 1) for _ in range(size + 1)]
    for column, match in enumerate(matches, start=1):
        z[0][column] = round(match.player_score, 1)
        z[column][0] = round(match.opponent_score, 1)
    for i in range(size):
        for j in range(size):
            if i != j:
                z[i + 1][j + 1] = round(tournament["matrix"][i][j], 1)

    player_average = (
        sum(m.player_score for m in matches) / len(matches) if matches else 0.0
    )
    table = [{
        "name": "玩家",
        "code": "—",
        "vs_others": player_average,
        "vs_player": None,
        "defection_rate": (
            sum(1 for m in matches for d in m.decisions if d.action == "D")
            / max(sum(len(m.decisions) for m in matches), 1)
        ),
        "is_player": True,
    }]
    for index, code in enumerate(codes):
        against_field = tournament["mean_against_field"][index]
        column_scores = [m.opponent_score for m in matches]
        table.append({
            "name": GAMEPLAY_SHORT[index],
            "code": code,
            "vs_others": against_field,
            "vs_player": (
                sum(column_scores) / len(column_scores) if column_scores else 0.0
            ),
            "defection_rate": sum(
                m.opponent_defection_rate for m in matches
            ) / max(len(matches), 1),
            "is_player": False,
        })

    return {
        "axis": axis,
        "detail_axis": detail_axis,
        "z": z,
        "turns": turns,
        "table": table,
        "player_average": player_average,
        "player_total": sum(m.player_score for m in matches),
        "field_average": (
            sum(tournament["mean_against_field"]) / size if size else 0.0
        ),
    }


def build_results_figure(results: dict) -> "go.Figure":
    """Heatmap of every score in the session: the player plus all pairings."""
    import plotly.graph_objects as go

    text = []
    for row in results["z"]:
        text.append([
            "" if value is None else "{:.0f}".format(value) for value in row
        ])
    fig = go.Figure(
        data=go.Heatmap(
            z=results["z"],
            x=results["axis"],
            y=results["axis"],
            text=text,
            texttemplate="%{text}",
            colorscale="RdYlGn",
            zmin=0,
            colorbar=dict(title="本方得分", thickness=12, len=0.85, x=1.02),
            hovertemplate=(
                "行 %{" + "y" + "}（%{text}）<br>列 %{x}<br>本方得分 %{z}"
                "<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        height=560,
        title="得分矩阵（行=本方，列=对方；空白=未交手）",
        xaxis=dict(tickangle=-45, tickfont=dict(size=10)),
        yaxis=dict(autorange="reversed", tickfont=dict(size=10)),
        margin=dict(l=110, r=30, t=60, b=130),
    )
    return apply_chart_theme(fig)


def strategy_tournament(
    codes: list[str], turns: int, seed: int
) -> dict:
    """Every ordered pair among the generated strategies, plus the player column.

    Returns the score matrix, the two direction-average views of it, and the
    per-strategy mean score against the field.
    """
    size = len(codes)
    matrix = [[0.0 for _ in range(size)] for _ in range(size)]
    for i, first in enumerate(codes):
        for j, second in enumerate(codes):
            if i == j:
                continue
            a_score, _, _, _ = play_auto_match(
                first, second, turns, seed + 1000 * i + j
            )
            matrix[i][j] = a_score

    mean_against_field = []
    for i in range(size):
        others = [matrix[i][j] for j in range(size) if j != i]
        mean_against_field.append(
            sum(others) / len(others) if others else 0.0
        )
    return {
        "codes": list(codes),
        "labels": [opponent_label(c) for c in codes],
        "turns": turns,
        "matrix": matrix,
        "mean_against_field": mean_against_field,
    }
