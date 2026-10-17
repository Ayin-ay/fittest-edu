"""Game-theory readings over the same recorded decisions as :mod:`dashboard.profiling`.

Profiling answers *what did you do*; this module answers *what does the game say
about that*. Every reading is:

* computed locally from the stored per-turn decisions -- no model, no network;
* tied to one textbook statement, quoted in the reading's own ``rule`` field so a
  student can check the arithmetic against the claim;
* falsifiable: ``falsifier`` names the observation that would refute it.

Two limits are stated here rather than in the UI, because they bound what any of
these numbers may be used for:

* The payoffs are the fixed teaching matrix (T=5, R=3, P=1, S=0). The discount
  factor arithmetic in :func:`reading_deterrence` is a one-shot-deviation
  comparison under an explicitly stated punishment stream, not a subgame-perfect
  equilibrium computation for this game.
* Opponents here are fixed rules that do not learn. :func:`reading_predictability`
  therefore measures a property of the player's *sequence*, and says nothing about
  whether some real adaptive opponent would have exploited it.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from dashboard.gameplay import Decision, Match
from trust_evolution_simulation import PAYOFFS

#: The teaching matrix, named the way the textbook names it.
T = PAYOFFS[("D", "C")][0]   # 背叛对方合作时的 temptation
R = PAYOFFS[("C", "C")][0]   # 互相合作的 reward
P = PAYOFFS[("D", "D")][0]   # 互相背叛的 punishment
S = PAYOFFS[("C", "D")][0]   # 合作被背叛时的 sucker payoff

#: The two thresholds a student should be able to quote after this page:
#: grim trigger is sustainable at delta >= (T-R)/(T-P); tit-for-tat at
#: delta >= (T-R)/(R-S). Axelrod (1988) takes the larger of the two.
DELTA_GRIM = (T - R) / (T - P)
DELTA_TFT = (T - R) / (R - S)


@dataclass
class Reading:
    """One textbook concept, measured on this run."""

    key: str
    concept: str        # the name a textbook would use
    rule: str           # the statement being tested, in the student's own numbers
    value: str          # the measurement, formatted for display
    verdict: str        # what this run says about that rule
    evidence: list[str] = field(default_factory=list)
    falsifier: str = ""
    numbers: dict = field(default_factory=dict)


def _decisions(matches: list[Match]) -> list[Decision]:
    return [d for m in matches for d in m.decisions]


def _episode(turn: int, match_index: int, opponent: str) -> str:
    return "第 {} 场第 {} 轮（对手 {}）".format(match_index + 1, turn, opponent)


def reading_stage(decisions: list[Decision]) -> Reading:
    """Strict dominance in the one-shot game, and what choosing C costs."""
    against_c = [d for d in decisions if d.opponent_action == "C"]
    against_d = [d for d in decisions if d.opponent_action == "D"]
    coop_turns = [d for d in decisions if d.action == "C"]
    forgone = sum(d.immediate_delta for d in coop_turns if d.immediate_delta > 0)
    return Reading(
        key="stage",
        concept="严格占优策略",
        rule=(
            "把支付矩阵按对手两种可能各比一遍：对方合作时背叛多 {} 分（{}−{}），"
            "对方背叛时背叛多 {} 分（{}−{}）。两种情况下背叛都更高，所以在这个"
            "一次性博弈里背叛是严格占优策略。".format(
                int(T - R), int(T), int(R), int(P - S), int(P), int(S))
        ),
        value="这 {} 步里你出了 {} 步合作；只看当下一步，这些步每步都比背叛少拿 "
              "{} 或 {} 分，合计让出 {:.0f} 分".format(
                  len(decisions), len(coop_turns), int(T - R), int(P - S), forgone),
        verdict=(
            "占优策略说的是「只看这一步」，不是「只看这一局」。你让掉的那 {:.0f} 分"
            "买的是下一轮：对面要是根本不记得你上一轮做了什么，这笔交易就是纯亏。".format(forgone)
        ),
        evidence=[
            "{}：你出 {} 得 {} 分，改出 {} 可得 {} 分（差 {} 分）".format(
                _episode(d.turn, d.match_index, d.opponent), d.action,
                int(d.payoff), d.alternative, int(d.alternative_payoff),
                int(d.immediate_delta))
            for d in sorted(
                (x for x in coop_turns if x.immediate_delta > 0),
                key=lambda x: -x.immediate_delta)[:4]
        ] or ["你全程出背叛，没有让过任何一分——占优策略被你执行到底了。"],
        falsifier="若某一步出合作并没有少拿分，这一项就得重算：那说明支付矩阵被改过。",
        numbers={"against_c": len(against_c), "against_d": len(against_d),
                 "forgone": forgone, "coop_turns": len(coop_turns)},
    )


def reading_joint(decisions: list[Decision]) -> Reading:
    """Efficiency: what the two of you actually produced per turn out of 6."""
    if not decisions:
        return Reading(
            key="joint", concept="合作剩余与效率", rule="", value="没有数据",
            verdict="这一版没有可算的轮次。", numbers={},
        )
    pairs = [(d.action, d.opponent_action) for d in decisions]
    totals = [PAYOFFS[pair][0] + PAYOFFS[pair][1] for pair in pairs]
    average = statistics.fmean(totals)
    mutual_c = pairs.count(("C", "C"))
    mutual_d = pairs.count(("D", "D"))
    split = len(pairs) - mutual_c - mutual_d
    best = R + R          # 6 -- both cooperate
    worst = P + P         # 2 -- both defect
    return Reading(
        key="joint",
        concept="合作剩余（效率前沿）",
        rule=(
            "两人合计每轮最多 {} 分（都合作），最少 {} 分（都背叛），"
            "一出一进是 {} 分。都合作比都背叛每轮多 {} 分，这 {} 分就是合作剩余——"
            "它不存在于任何一格里，只存在于两个人之间。".format(
                int(best), int(worst), int(T + S), int(best - worst),
                int(best - worst))
        ),
        value="每轮平均合计 {:.2f} 分（满分 {} 的 {:.0%}）；"
              "互合作 {} 轮、互背叛 {} 轮、一出一进 {} 轮".format(
                  average, int(best), average / best, mutual_c, mutual_d, split),
        verdict=(
            "这 {} 轮里，效率损失只来自互背叛的那 {} 轮（每轮合计 {} 分，双方一起少拿）；"
            "一出一进的 {} 轮合计 {} 分，蛋糕没变小，只是全落进了一个人的口袋。"
            "前者是效率问题，后者是分配问题——混在一起看就读错了。".format(
                len(pairs), mutual_d, int(worst), split, int(T + S))
        ),
        evidence=[
            "{}：都出合作，合计 {} 分（这一轮没有输家）".format(
                _episode(d.turn, d.match_index, d.opponent),
                int(d.payoff + PAYOFFS[(d.action, d.opponent_action)][1]))
            for d in decisions if (d.action, d.opponent_action) == ("C", "C")
        ][:4] or [
            "{}：都出背叛，合计 {} 分".format(
                _episode(d.turn, d.match_index, d.opponent), int(worst))
            for d in decisions if (d.action, d.opponent_action) == ("D", "D")
        ][:4] or ["没有任何一轮是双方同时出手的。"],
        falsifier="若把每一轮的合计分数逐轮相加与这里的平均值不一致，说明统计口径有问题。",
        numbers={"average_joint": average, "share": average / best,
                 "mutual_c": mutual_c, "mutual_d": mutual_d, "split": split},
    )


def _transitions(matches: list[Match]) -> dict[str, tuple[int, int]]:
    """Return, per state ``"C"`` / ``"D"`` (what the opponent did last turn),
    ``(how many turns followed it, how many of those the player cooperated)``.

    Only transitions inside a match count: the first turn of a match has no
    previous round, and stitching two matches together would invent one.
    """
    out: dict[str, list[int]] = {}
    for match in matches:
        player, opponent = match.player_actions, match.opponent_actions
        for index in range(1, len(player)):
            state = opponent[index - 1]
            out.setdefault(state, [0, 0])
            out[state][0] += 1
            out[state][1] += int(player[index] == "C")
    return {state: (count, coops) for state, (count, coops) in out.items()}


def reading_reciprocity(matches: list[Match]) -> Reading:
    """Conditional cooperation: p(C | opponent played C) - p(C | opponent played D)."""
    table = _transitions(matches)
    after_cc = table.get("C")   # opponent cooperated last turn
    after_dc = table.get("D")   # opponent defected last turn
    if not after_cc or not after_dc:
        return Reading(
            key="reciprocity",
            concept="条件合作 / 互惠指数",
            rule="在上一轮对手合作后你再合作的概率，减去在上一轮对手背叛后你合作的概率。",
            value="样本不足，无法计算",
            verdict="这一版没有同时出现「对手合作后」和「对手背叛后」两种局面。",
            numbers={},
        )
    p_coop_after_opponent_c = after_cc[1] / after_cc[0]
    p_coop_after_opponent_d = after_dc[1] / after_dc[0]
    index = p_coop_after_opponent_c - p_coop_after_opponent_d
    return Reading(
        key="reciprocity",
        concept="条件合作（互惠指数）",
        rule=(
            "互惠不是一个态度，是一个差：对手上一轮合作后你合作的概率，减去对手上一轮"
            "背叛后你还合作的概率。差为 1 表示「你只回报善意」，为 0 表示对手的出手"
            "完全不影响你，为负表示你反过来——它合作你才下手。"
        ),
        value="对手合作后你合作 {:.0%}（{} 次里 {} 次），"
              "对手背叛后你合作 {:.0%}（{} 次里 {} 次）；互惠指数 {:+.2f}".format(
                  p_coop_after_opponent_c, after_cc[0], after_cc[1],
                  p_coop_after_opponent_d, after_dc[0], after_dc[1], index),
        verdict=(
            "互惠指数就是「对手的行为在你这儿值多少权重」。指数越接近 1，"
            "你越像一个只跟合作者合作的人；越接近 0，你越像在用同一套动作对所有人——"
            "后者对固定规则的对手很稳，对一个会读你的对手就是漏洞。"
        ),
        evidence=[
            "{}：对手上一轮 {}，这一轮你 {}；对手下一轮 {}".format(
                _episode(d.turn, d.match_index, d.opponent),
                "合作" if d.opponent_history and d.opponent_history[-1] == "C" else "背叛",
                d.action,
                d.opponent_next_if_chosen)
            for d in _decisions(matches)
            if d.turn > 1 and d.opponent_history
        ][:4],
        falsifier="两个概率必须有各自的样本：如果对手整场只出合作（或只出背叛），"
                  "这条差其实只数了一类轮次，读数不成立。",
        numbers={"after_c": p_coop_after_opponent_c,
                 "after_d": p_coop_after_opponent_d, "index": index},
    )


def _retaliation_episodes(matches: list[Match]) -> tuple[list[tuple[Match, int, int]], int]:
    """Walk every provocation and return ``[(match, delay, length), ...]`` plus the
    count of provocations that were never answered.

    A provocation is a turn where the opponent defected while the player had just
    cooperated. ``delay`` is how many turns until the player's next defection,
    ``length`` how many consecutive defections that answer ran for.
    """
    episodes: list[tuple[Match, int, int]] = []
    unanswered = 0
    for match in matches:
        player, opponent = match.player_actions, match.opponent_actions
        index = 1
        while index < len(player):
            provoked = opponent[index] == "D" and player[index - 1] == "C"
            if not provoked:
                index += 1
                continue
            answer = None
            scan = index + 1
            while scan < len(player):
                if player[scan] == "D":
                    answer = scan
                    break
                scan += 1
            if answer is None:
                unanswered += 1
                index += 1
                continue
            end = answer
            while end < len(player) and player[end] == "D":
                end += 1
            episodes.append((match, answer - index, end - answer))
            index = end
    return episodes, unanswered


def _delta_threshold(delay: float, length: float) -> float | None:
    """Smallest delta at which a one-shot cheat stops paying, given the punishment.

    Cheat now for ``T-R``; the punishment stream costs the cheat ``(R-P)`` per
    round, starting after ``delay`` rounds and running ``length`` rounds. Bisect
    the indifference point on (0, 1); None means even a fully patient opponent is
    not deterred.
    """
    if length <= 0:
        return None

    def gap(delta: float) -> float:
        if delta <= 0:
            return -(T - R)
        if delta >= 1:
            stream = length
        else:
            stream = delta ** delay * (1 - delta ** length) / (1 - delta)
        return stream * (R - P) - (T - R)

    if gap(0.9999) < 0:
        return None
    low, high = 0.0, 0.9999
    for _ in range(60):
        mid = (low + high) / 2
        if gap(mid) < 0:
            low = mid
        else:
            high = mid
    return high


def reading_deterrence(matches: list[Match]) -> Reading:
    """How patient the opponent has to be before your punishment deters it."""
    episodes, unanswered = _retaliation_episodes(matches)
    if not episodes:
        return Reading(
            key="deterrence",
            concept="贴现因子与惩罚的可信度",
            rule=(
                "冷酷策略在 δ ≥ {} 时是均衡，以牙还牙在 δ ≥ {} 时是均衡"
                "（δ 是「未来值多少」）。两者都要求：背叛你一次现在多拿的分，"
                "小于之后被惩罚的分折现回来。".format(
                    "{:.2f}".format(DELTA_GRIM), "{:.2f}".format(DELTA_TFT)),
            ),
            value="没有出现「对手背叛你之后你回击」的段落",
            verdict=(
                "没有回击就没有惩罚流可言：在这些对手面前，背叛你的成本是 0。"
                "它现在不惩罚你，是因为这些规则不学习——换成一个会学习的对手，"
                "这就是可利用之处。"
            ),
            evidence=[
                "{}：对手出 {}，你到终局都没有回击".format(
                    _episode(d.turn, d.match_index, d.opponent), d.opponent_action)
                for d in _decisions(matches) if d.provoked and d.action == "C"
            ][:4],
            falsifier="若「未回击」其实是你主动的合作（比如你测试对手会不会自己收手），"
                      "这条读数会把你的实验读成软弱。",
            numbers={"unanswered": unanswered},
        )
    mean_delay = statistics.fmean([episode[1] for episode in episodes])
    mean_length = statistics.fmean([episode[2] for episode in episodes])
    threshold = _delta_threshold(mean_delay, mean_length)
    if threshold is None:
        where = "δ≈1（几乎镇不住）"
        verdict = (
            "平均隔 {:.1f} 轮才回击、只打 {:.1f} 轮就翻篇：这样一条惩罚流折现回来，"
            "连对手背叛当下多拿的那 {} 分都抵不平，所以只有把未来看得和现在一样重"
            "（δ≈1）的对手才会因此收手。想让门槛降下来，要么回击更快，要么惩罚更长——"
            "这正是冷酷策略（0.50）比以牙还牙（0.67）更能吓住人的原因。".format(
                mean_delay, mean_length, int(T - R))
        )
    elif threshold > DELTA_TFT:
        where = "δ ≥ {:.2f}".format(threshold)
        verdict = (
            "你的惩罚节奏比课本的以牙还牙门槛（δ ≥ {:.2f}）还苛刻：只有非常在乎"
            "未来的对手才怕你。回击再快一点、或者多撑一轮，门槛就会明显下降。".format(DELTA_TFT)
        )
    else:
        where = "δ ≥ {:.2f}".format(threshold)
        verdict = (
            "你的惩罚已经落在两个课本门槛之内（冷酷 {:.2f}、以牙还牙 {:.2f}）："
            "一个稍微在乎未来的对手，背叛你在它自己算下来就是不划算的。".format(
                DELTA_GRIM, DELTA_TFT)
        )
    return Reading(
        key="deterrence",
        concept="贴现因子与惩罚的可信度",
        rule=(
            "背叛你一次，对手当下多拿 {} 分（{}−{}）；被你惩罚，它每轮少拿 {} 分"
            "（{}−{}）。惩罚从你回击那一轮起算，所以要折现。课本给的是两个特例："
            "你从此再也不合作（冷酷策略，惩罚无限长、且下一轮就开始），"
            "门槛是 δ ≥ (T−R)/(T−P) = {:.2f}；你只打一轮就翻篇（以牙还牙，"
            "惩罚路径更短），门槛抬到 δ ≥ (T−R)/(R−S) = {:.2f}。"
            "δ 越大代表对手越在乎以后。".format(
                int(T - R), int(T), int(R), int(R - P), int(R), int(P),
                DELTA_GRIM, DELTA_TFT)
        ),
        value="你的回击平均延迟 {:.1f} 轮、持续 {:.1f} 轮，"
              "对应门槛 {}（另有 {} 次被背叛你没回击）".format(
                  mean_delay, mean_length, where, unanswered),
        verdict=verdict,
        evidence=[
            "第 {} 场（对手 {}）：对手背叛后你延迟 {} 轮回击，之后连打 {} 轮".format(
                match.index + 1, match.opponent, delay, length)
            for match, delay, length in episodes[:3]
        ],
        falsifier="这里的惩罚流假设「你回击的那几轮对手一直陪着互背叛」。"
                  "如果对手在你回击的第一轮就回到合作，实际损失比算的少，门槛要重算。",
        numbers={"delay": mean_delay, "length": mean_length,
                 "threshold": threshold, "unanswered": unanswered,
                 "episodes": len(episodes)},
    )


def reading_endgame(decisions: list[Decision]) -> Reading:
    """Backward induction: the last round has no future to protect."""
    final = [d for d in decisions if d.is_final_round]
    early = [d for d in decisions if not d.is_final_round]
    if not final or not early:
        return Reading(
            key="endgame", concept="逆向归纳与终局坍塌",
            rule="已知终点的有限次重复博弈，唯一子博弈完美均衡是全程背叛。",
            value="轮次太少，前段与末轮无法比较",
            verdict="这一串对局没有可比的前段轮次。", numbers={},
        )
    late_rate = sum(1 for d in final if d.action == "D") / len(final)
    before_rate = sum(1 for d in early if d.action == "D") / len(early)
    shift = late_rate - before_rate
    return Reading(
        key="endgame",
        concept="逆向归纳 / 终局坍塌",
        rule=(
            "最后一轮背叛不会被报复，所以最后一轮理性人出 D；既然最后一轮必定 D，"
            "倒数第二轮的「以后」也完了，于是 D 一路往前推——这是逆向归纳，"
            "它给出的预测是全程背叛。实验里的人并不这样：末轮背叛率明显高于前段，"
            "但前段仍然大量合作。差距本身就是「有限期 + 公共知识」这条前提的账单。"
        ),
        value="末轮背叛率 {:.0%}（{} 场里 {} 场），此前各轮 {:.0%}，"
              "差 {:+.0%}".format(
                  late_rate, len(final), sum(1 for d in final if d.action == "D"),
                  before_rate, shift),
        verdict=(
            "你在末轮的出手比前段更硬，说明你确实用上了「这一步没人能报复你」；"
            "如果前段与末轮一样，那要么你从一开始就在背叛，要么你根本没把终点当回事。"
            if shift > 0.05 else
            "末轮与前段几乎没有差别。逆向归纳要的「知道终点」这条前提，在你的行为里"
            "没有兑现——这也正是课本模型和真人对不上的地方。"
        ),
        evidence=[
            "{}：末轮你出 {}，对手出 {}（之后不再有报复）".format(
                _episode(d.turn, d.match_index, d.opponent), d.action,
                d.opponent_action)
            for d in final if d.action == "D"
        ][:4] or ["你的末轮全部选了合作。"],
        falsifier="若终点轮次本身不可比（不同场轮数不同、或你当时不知道还有几轮），"
                  "这个差就混进了别的东西，不能算终局意识。",
        numbers={"late": late_rate, "before": before_rate, "shift": shift,
                 "finals": len(final)},
    )


def reading_predictability(matches: list[Match]) -> Reading:
    """Can your sequence be predicted from its own previous turn?"""
    pairs_same = 0
    pairs_total = 0
    repeats: list[list[int]] = []
    for match in matches:
        player = match.player_actions
        if len(player) < 2:
            continue
        series = [1 if mark == "C" else 0 for mark in player]
        same = sum(1 for a, b in zip(series, series[1:]) if a == b)
        pairs_same += same
        pairs_total += len(series) - 1
        repeats.append(series)
    if not pairs_total:
        return Reading(
            key="predictability", concept="可预测性与被利用",
            rule="若下一手和上一手相同的比例明显偏离 50%，序列就有可利用的结构。",
            value="轮次不足", verdict="这一串对局太短，测不出结构。", numbers={},
        )
    stickiness = pairs_same / pairs_total
    # Runs test, per match then summed: a random sequence with n_C cooperations
    # and n_D defections averages 2*n_C*n_D/n + 1 runs. Fewer runs than that means
    # clustering, more means flipping. Summing across a flattened list would count
    # a run that never happened, since one match's last turn does not follow the
    # next match's first turn.
    runs = 0
    expected_runs = 0.0
    for series in repeats:
        size = len(series)
        ones = series.count(1)
        zeros = size - ones
        runs += 1 + sum(1 for a, b in zip(series, series[1:]) if a != b)
        if ones and zeros:
            expected_runs += 2 * ones * zeros / size + 1
    if stickiness >= 0.65:
        note = "你有一半以上的轮次在重复上一手——这是「惯性」，也是最好读的信号。"
    elif stickiness <= 0.35:
        note = "你几乎每轮都在翻转上一手——这同样可预测，只是周期是 2。"
    else:
        note = "接近无记忆：知道你的上一手，几乎猜不出这一手。"
    return Reading(
        key="predictability",
        concept="可预测性（可被利用的程度）",
        rule=(
            "一阶可预测性就是问：只告诉对手你的上一手，它能猜中你这一手的概率有多高。"
            "完全无记忆时是 50%；只要「重复上一手」或「必翻转」成立，"
            "一个会读序列的对手就能把每一轮都压到你的 S 分那一格上。"
        ),
        value="与上一手相同的比例 {:.0%}（{} 对里 {} 对）；"
              "游程 {} 段，随机序列的期望 {:.1f} 段".format(
                  stickiness, pairs_total, pairs_same, runs, expected_runs),
        verdict=note + "（注意：本站的对手是固定规则，它们不学习，所以这是你的序列的性质，"
                       "不是某个对手已经利用了它的证据。）",
        evidence=[
            "第 {} 场你的动作串 {}：其中 {} 对与上一手相同".format(
                match.index + 1, match.player_actions,
                sum(1 for a, b in zip(match.player_actions,
                                      match.player_actions[1:]) if a == b))
            for match in matches if len(match.player_actions) >= 2
        ][:4],
        falsifier="把不同场次的首轮接在一起算会虚增游程数，所以这里的自相关只在场内部统计。",
        numbers={"stickiness": stickiness, "runs": runs,
                 "expected_runs": expected_runs, "pairs": pairs_total},
    )


def readings(matches: list[Match]) -> list[Reading]:
    """All readings, in the order a lesson would take them."""
    decisions = _decisions(matches)
    return [
        reading_stage(decisions),
        reading_joint(decisions),
        reading_reciprocity(matches),
        reading_deterrence(matches),
        reading_endgame(decisions),
        reading_predictability(matches),
    ]
