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

from dashboard.theme import (
    COOP,
    DEFECT,
    MUTED,
    MUTUAL,
    SCORE_RAMP,
    apply_chart_theme,
)

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
    # What the player guessed this turn would be, "-" when they skipped the
    # guess. Optional by design: guessing is a second exercise, not a precondition
    # for playing, and a blank must stay distinguishable from a wrong answer.
    prediction: str = "-"

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
    #: One character per turn, aligned with ``player_actions``: the turn's guess,
    #: or "-" where the player did not guess. Kept as a string so it persists and
    #: replays exactly like the decisions do.
    predictions: str = ""

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
    ("C", "C"): ("共赢", MUTUAL),
    ("D", "D"): ("互害", MUTED),
    ("D", "C"): ("背刺", DEFECT),
    ("C", "D"): ("被剥削", COOP),
}


def action_run(mine: str, theirs: str) -> str:
    """Two aligned rows of one-pip-per-turn, for the many-matches overview.

    ``history_table`` spells every turn out in words, which is right for one
    match and far too much for ten. Here the reader only needs the shape of each
    game -- when they cooperated, when the other side defected -- so each turn
    becomes a dot and the two sides stack so columns stay on the same turn.
    """
    from dashboard import theme

    def row(text: str) -> str:
        pips = "".join(
            "<i style='background:{}'></i>".format(
                theme.COOP if mark == "C" else theme.DEFECT)
            for mark in text
        )
        return "<div class='tf-run'>{}</div>".format(pips)

    return (
        "<div class='tf-runs'>"
        "<span class='tf-run__key' style='color:{}'>你</span>{}"
        "<span class='tf-run__key' style='color:{}'>对手</span>{}"
        "</div>"
    ).format(
        theme.INK, row(mine), theme.MUTED, row(theirs),
    )


def _relationship(my_action: str, their_action: str) -> str:
    """Label one round by the pair of actions."""
    label, colour = RELATIONSHIPS[(my_action, their_action)]
    return "<div style='font-weight:700;color:%s'>%s</div>" % (colour, label)


def branch_strip(action: str, live_branch: str | None = None) -> str:
    """What one choice is worth, split by what the opponent does.

    Without this the player has to hold the payoff matrix in mind while picking,
    and the whole point of the game is that the choice is a bet on the other
    side's behaviour rather than a fixed value. ``live_branch`` ("C" or "D", what
    the opponent just played) tints the branch the player is actually living
    with, so the risk is not stated as an abstraction.
    """
    cells = []
    for their_action, label in (("C", "若对手合作"), ("D", "若对手背叛")):
        points = PAYOFFS[(action, their_action)][0]
        cells.append(
            "<div class='tf-branch%s'>"
            "<span class='tf-branch__them'>%s</span>"
            "<span class='tf-branch__mine'>+%s</span>"
            "</div>"
            % (
                " tf-branch--best" if live_branch == their_action else "",
                label, _whole(points),
            )
        )
    return "<div class='tf-branches'>%s</div>" % "".join(cells)


def action_cue(their_action: str) -> str:
    """One line about what the opponent just did, coloured by that action.

    This used to be an ``st.info`` box. Once the branch strip under each button
    tints the branch this move corresponds to, the box restates it and takes a
    block of height on the screen a player stares at ten times per match.
    """
    defect = their_action == "D"
    text = (
        "对手上一轮背叛了 —— 下方高亮的就是它刚选的那条分支。" if defect
        else "对手上一轮合作了。"
    )
    return "<div class='tf-cue%s'><i></i>%s</div>" % (
        " tf-cue--defect" if defect else "", text)


def prediction_note(prediction: str, opponent_action: str,
                    guesses: int, hits: int) -> str:
    """One line about the guess the player just made, next to what actually happened.

    Shown after the turn resolves, never before: the engine can compute the
    opponent's real move (``opponent_next_action``), and displaying anything built
    from that would hand the student the answer to the exercise the guess is.
    """
    if prediction == "-":
        return (
            "<div class='tf-pred'><span>这一轮没有猜。</span>"
            "<span class='tf-pred__score'>本局已猜 %d 次，中 %d 次</span></div>"
            % (guesses, hits)
        )
    names = {"C": "合作", "D": "背叛"}
    hit = prediction == opponent_action
    return (
        "<div class='tf-pred'><span class='tf-pred__mark'>%s</span>"
        "<span>你猜它 %s，它出的是 %s</span>"
        "<span class='tf-pred__score'>本局已猜 %d 次，中 %d 次</span></div>"
        % (
            "猜中了" if hit else "没猜中",
            names.get(prediction, prediction),
            names.get(opponent_action, opponent_action),
            guesses, hits,
        )
    )


def stage_strip(
    match_count: int,
    outcomes: list[tuple[float, float]],
    turn: int,
    turns: int,
    total_score: float,
    help_html: str = "",
) -> str:
    """Where the player is: which matches are done, which turn is live.

    ``outcomes`` is the finished matches as (your score, their score) pairs, so
    the pips can tell a won match from a lost one -- a progress bar could only
    count them.

    ``help_html`` is the caller's in-place ``?`` explainer. It rides the top row
    because that is the row whose colours need explaining; as a block under the
    strip it would read as commentary on the next screen instead.
    """
    pips = []
    for index in range(match_count):
        if index < len(outcomes):
            you, them = outcomes[index]
            state = "win" if you > them else ("loss" if you < them else "draw")
        elif index == len(outcomes):
            state = "here"
        else:
            state = "todo"
        pips.append(
            "<i class='tf-pip%s'></i>"
            % (" tf-pip--" + state if state != "todo" else "")
        )

    done_turns = min(max(turn - 1, 0), turns)
    share = done_turns / max(turns, 1) * 100
    # ``turn`` comes from the runner and keeps counting past the last round, so
    # on the settlement screen it would read 第 11 / 10 轮.
    turn_label = (
        "本局结束" if turn > turns else "本轮第 %d / %d 轮" % (turn, turns))
    # Once the match is over the reveal is on the same screen, so promising
    # secrecy would contradict what the player is looking at.
    secret = (
        "对手身份已在下方揭晓。" if turn > turns
        else "先看它做了什么，再决定你怎么应对。")
    return (
        "<div class='tf-stage'>"
        "<div class='tf-stage__top'>"
        "<span class='tf-stage__kicker'>对局</span>"
        "<span class='tf-stage__count'>第 %d<em> / %d 局</em></span>"
        "<span class='tf-stage__total'>跨局总得分<b>%s</b></span>%s"
        "</div>"
        "<div class='tf-pips'>%s</div>"
        "<div class='tf-track'><div class='tf-track__fill' style='width:%.1f%%'></div></div>"
        "<div class='tf-stage__sub'>"
        "<span class='tf-stage__turn'>%s</span>"
        "<span class='tf-stage__secret'>%s</span>"
        "</div>"
        "</div>"
        % (
            len(outcomes) + 1, match_count, _whole(total_score), help_html,
            "".join(pips), share, turn_label, secret,
        )
    )


def _alternative_cell(decision: Decision | None) -> str:
    """One turn's counterfactual, in the same row as the turn it belongs to.

    The engine already records what the unchosen move paid and what it would have
    done to the opponent's next round (``Decision`` fields 9-13), but that only
    ever reached the nine measurements and the last turn's caption. Seeing it per
    turn is the point of the exercise: a "mistake" that bought the opponent's
    cooperation next round is not the same mistake as one that bought nothing.

    The numbers stay in ``INK`` on purpose. Colour here means cooperation or
    defection and nothing else, so a green/red delta would read as 对/错 --
    this is a score table, not a verdict.
    """
    from dashboard import theme

    if decision is None:
        return "<span style='color:{}'>—</span>".format(theme.MUTED)

    other = decision.alternative
    word = "合作" if other == "C" else "背叛"
    hue = theme.COOP if other == "C" else theme.DEFECT
    delta = decision.immediate_delta
    if delta > 0:
        gap = "多 {} 分".format(_whole(delta))
    elif delta < 0:
        gap = "少 {} 分".format(_whole(-delta))
    else:
        gap = "同分"
    cell = (
        "<div><b style='color:{}'>{}</b> 可得 {}，<b>{}</b></div>".format(
            hue, word, _whole(decision.alternative_payoff), gap)
    )
    moved = (
        not decision.is_final_round
        and decision.opponent_next_if_chosen
        != decision.opponent_next_if_alternative
    )
    if moved:
        # Only the branch that *changes* something gets a second line: ten rows
        # of 它下一轮不变 would bury the two turns where the choice mattered.
        # 若改选 is spelled out because the line sits under a number that is
        # already about the other move -- readers took it for a forecast.
        cell += "<div><span style='color:{}'>若改选，它下轮出{}</span></div>".format(
            theme.DEFECT if decision.opponent_next_if_alternative == "D"
            else theme.COOP,
            "背叛" if decision.opponent_next_if_alternative == "D" else "合作")
    return cell


def history_table(
    mine: str,
    theirs: str,
    turns: int | None = None,
    highlight: int | None = None,
    decisions: list[Decision] | None = None,
) -> str:
    """Per-turn history as a readable table.

    The bare ``CDDDC`` string is unreadable on its own: the letters have to be
    decoded, the two sides sit on one line, and there is no sign of who scored
    what. This lays it out one turn per row with the words 合作/背叛, the
    payoff for that round, and a running total.

    ``decisions`` -- the turn's :class:`Decision` objects, in order -- adds the
    另一手 column. Callers that only have the two action strings (the tutorial,
    records written before matches were kept whole) simply leave it out.
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
        if my_action and their_action:
            running = "<b style='color:%s'>%s</b> <span style='color:%s'>/ %s</span>" % (
                theme.INK, _whole(my_running), theme.MUTED, _whole(their_running))
        else:
            running = "<span style='color:%s'>—</span>" % theme.MUTED
        given = (
            decisions[turn]
            if decisions is not None and turn < len(decisions) else None
        )
        body.append(
            "<tr style='{row}'>"
            "<td style='text-align:center;color:{muted}'>{turn}</td>"
            "<td style='text-align:center'>{mine}</td>"
            "<td style='text-align:center'>{theirs}</td>"
            "<td style='text-align:center'>{points}</td>"
            "<td style='text-align:center'>{outcome}</td>"
            "<td style='text-align:center'>{running}</td>"
            "{alternative}"
            "</tr>".format(
                row=row_style, turn=turn + 1, mine=my_cell,
                theirs=their_cell, points=points, outcome=outcome,
                running=running,
                alternative=(
                    "<td style='text-align:left;font-size:14px;white-space:nowrap;"
                    "padding-left:10px'>{}</td>".format(_alternative_cell(given))
                    if decisions is not None else ""
                ),
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
        + head_cell("本轮结果")
        + head_cell("本局累计<br>你/对手")
        + (head_cell("另一手<br>本可得分") if decisions is not None else "")
    )
    # The margin rather than a repeat of the totals: the last row of the 本局累计
    # column already gives both numbers, so a 合计 line underneath only doubled it.
    margin = my_running - their_running
    if margin:
        word = "你领先 %s 分" if margin > 0 else "你落后 %s 分"
        colour = theme.MUTUAL if margin > 0 else theme.DEFECT
        summary = word % _whole(abs(margin))
    else:
        colour, summary = theme.MUTED, "双方持平"
    return (
        "<div style='overflow-x:auto;margin:0.4rem 0 0.8rem'>"
        "<table style='border-collapse:collapse;width:100%;max-width:"
        + str(880 if decisions is not None else 760)
        + "px;font-size:15px'>"
        "<thead><tr>" + headers + "</tr></thead>"
        "<tbody>" + "".join(body) + "</tbody></table>"
        "<div style='color:" + colour + ";font-size:14px;font-weight:600;"
        "margin-top:4px'>" + summary + "</div></div>"
    )


def matches_overview(matches: list[Match]) -> str:
    """All finished matches in one compact table, the sequence drawn as pips.

    The scores page used to hand ``st.dataframe`` the raw ``CDDCC`` strings,
    which put back the very thing ``history_table`` exists to remove: a reader
    has to decode each letter and cannot line the two rows up. Ten full
    turn-by-turn tables would be just as unusable, so each match collapses to
    one paired-pip line next to its numbers.
    """
    from dashboard import theme

    def head_cell(label: str) -> str:
        return (
            "<th style='border-bottom:2px solid " + theme.LINE
            + ";padding:6px 8px 6px 4px;color:" + theme.MUTED
            + ";font-weight:600;text-align:left'>" + label + "</th>"
        )

    rows = []
    for match in matches:
        margin = match.player_score - match.opponent_score
        verdict, colour = (
            ("领先", theme.MUTUAL) if margin > 0
            else ("落后", theme.DEFECT) if margin < 0
            else ("持平", theme.MUTED)
        )
        rows.append(
            "<tr>"
            "<td style='padding:7px 8px 7px 4px;text-align:center;color:"
            + theme.MUTED + "'>{}</td>"
            "<td style='padding:7px 8px'><b>{}</b><div style='color:{};"
            "font-size:13px'>{}</div></td>"
            "<td style='padding:7px 8px'>{}</td>"
            "<td style='padding:7px 8px;white-space:nowrap'><b style='color:{}'>{}</b>"
            "<span style='color:{}'> / {}</span></td>"
            "<td style='padding:7px 8px;color:{};font-weight:600;white-space:nowrap'>{}</td>"
            "<td style='padding:7px 8px;text-align:right'>{}</td>"
            "</tr>".format(
                match.index + 1, match.opponent, theme.MUTED, match.opponent_label,
                action_run(match.player_actions, match.opponent_actions),
                theme.INK, _whole(match.player_score),
                theme.MUTED, _whole(match.opponent_score),
                colour, verdict, match.mutual_cooperations,
            )
        )

    return (
        "<div style='overflow-x:auto;margin:0.4rem 0 0.8rem'>"
        "<table style='border-collapse:collapse;width:100%;font-size:15px'>"
        "<thead><tr>"
        + head_cell("局") + head_cell("对手") + head_cell("出牌<br>你 / 对手")
        + head_cell("得分<br>你 / 对手") + head_cell("结果") + head_cell("互相<br>合作轮数")
        + "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
    )


def _echo_move(action: str) -> str:
    """One action word, coloured the same way as every other action on the page."""
    return "<i class='tf-echo__act tf-echo__act--{}'>{}</i>".format(
        "c" if action == "C" else "d", "合作" if action == "C" else "背叛")


#: Three pointers are enough to show a rule running; ten rows nobody reads.
ECHO_LIMIT = 3


def rule_echo(match: Match) -> list[tuple[str, str]]:
    """The turns where the opponent's own rule is visible in this match.

    Read off the two action strings the match already stores, so every line here
    is something the table above it shows: 第 N 轮它出了什么，你上一轮出了什么. It says
    紧跟 / 对应, never 因为它想 -- the rule text above the list is what carries intent,
    and a revealed rule is still a rule, not a motive.
    """
    mine, theirs = match.player_actions, match.opponent_actions
    if not mine or not theirs:
        return []

    marks: dict[str, tuple[int, str]] = {}

    def note(kind: str, turn: int, text: str) -> None:
        if kind not in marks:
            marks[kind] = (turn, text)

    for index, their_action in enumerate(theirs):
        turn = index + 1
        previous_mine = mine[index - 1] if index else None
        previous_theirs = theirs[index - 1] if index else None
        if their_action == "D" and previous_mine != "D":
            if previous_mine is None:
                note("主动出手", turn, "开局第一轮它就出了{}——那时你手上没有任何信息。".format(
                    _echo_move("D")))
            else:
                note("主动出手", turn, "它出{}，而你上一轮出的是{}。".format(
                    _echo_move("D"), _echo_move(previous_mine)))
        elif their_action == "D":
            note("回应你的背叛", turn, "它出{}，紧跟在你第 {} 轮的{}之后。".format(
                _echo_move("D"), index, _echo_move("D")))
        elif their_action == "C" and previous_theirs == "D":
            note("回到合作", turn, "它转回{}，而你这轮出的是{}。".format(
                _echo_move("C"), _echo_move(mine[index])))

    if not marks:
        return [("全程", "它这 {} 轮一次也没有{}过。".format(
            len(theirs), _echo_move("D")))]
    ordered = sorted(marks.items(), key=lambda item: item[1][0])[:ECHO_LIMIT]
    return [
        ("第 {} 轮".format(turn), "{}：{}".format(kind, text))
        for kind, (turn, text) in ordered
    ]


def identity_card(code: str, match: Match | None = None) -> str:
    """The opponent's identity, revealed once its match is over.

    It used to be a ``st.container(border=True)`` holding a bullet list, which
    read as raw parser output -- 默认槽 / 触发槽1 as list items, no visual
    grouping, and the code string lost at the end of a caption. Here the code
    and the label come first as the card's spine, and each module is a row with
    its slot as a chip so the three kinds stay distinguishable at a glance.

    ``match`` adds the 回指 list: the same rule text, but pointing at the two or
    three turns of this match where it can be seen running.
    """
    from dashboard.naming import generate_name
    from dashboard.strategy_detail import parse_strategy_detail

    rows = []
    for slot, module_name, text in parse_strategy_detail(code):
        rows.append(
            "<div class='tf-rule'>"
            "<span class='tf-rule__slot'>{}</span>"
            "<div class='tf-rule__body'><b>{}</b><span>{}</span></div>"
            "</div>".format(slot, module_name, text)
        )
    echo = ""
    if match is not None:
        lines = rule_echo(match)
        if lines:
            echo = (
                "<div class='tf-echo'><div class='tf-echo__k'>"
                "它的规则在这一局里出现在</div>{}</div>"
            ).format(
                "".join(
                    "<div class='tf-echo__row'><span class='tf-echo__turn'>{}</span>"
                    "<div><em>{}</em></div></div>".format(turn, text)
                    for turn, text in lines
                )
            )
    return (
        "<div class='tf-ident'>"
        "<div class='tf-ident__head'>"
        "<span class='tf-ident__kicker'>本局对手</span>"
        "<b class='tf-ident__name'>{}</b>"
        "<span class='tf-ident__code'>{}</span>"
        "<span class='tf-ident__label'>{}</span>"
        "</div>{}{}<div class='tf-ident__note'>"
        "规则在它这一局结束前一直保密；现在可以对照上面的「本局记录」回看它每一步为什么这么出。</div>"
        "</div>"
    ).format(
        generate_name(code), code, opponent_label(code), "".join(rows), echo,
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
        self.prediction_history: list[str] = []
        self.pending_prediction: str | None = None
        self._pending_snapshot: StrategyState | None = None
        self._pending_opponent_action: str | None = None

    def set_prediction(self, action: str | None) -> None:
        """Record what the player thinks the opponent will play this turn.

        The guess has to be read at click time rather than stored on a rerun: it
        belongs to the turn that is about to be resolved, and a turn the player
        passed on must stay empty rather than inherit the previous guess.
        """
        if action is not None and action not in ("C", "D"):
            raise ValueError("prediction must be 'C', 'D' or None")
        self.pending_prediction = action

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
        prediction = self.pending_prediction or "-"
        self.pending_prediction = None
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
            prediction=prediction,
        )
        self.decisions.append(decision)
        self.prediction_history.append(prediction)

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
            predictions="".join(self.prediction_history),
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
            # The shared value ramp, not a red-yellow-green diverging scale: this
            # matrix is scores, and orange already means defection elsewhere.
            colorscale=SCORE_RAMP,
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
