"""Behavioural profiling from recorded play.

Design constraints, taken seriously:

* **No type labels.** Nothing here may conclude "you are an altruist" or emit a
  personality type, a letter code, or a trait adjective that could be pasted onto
  any other person. The unit of description is a *measured quantity with its
  evidence*, not a category.

* **No similarity matching.** The profile never says "you play like S0" or
  "closest to R1-1". A player and a strategy can score identically while sharing
  no reasoning, and a per-decision reading is worth more than a nearest
  neighbour. Opponent archetypes are used as a *control condition* -- to test
  whether the player discriminates -- and never as a template to match against.

* **Every claim must be falsifiable from the record.** Each dimension states the
  measurement, the numbers, the turns it rests on, and what observation would
  have refuted it.

* **Contradictions are reported, not smoothed.** If the player punished hard in
  the first three matches and barely at all in the last seven, that shift is the
  finding. An internally consistent story is not required.

* **The opponent's strategy is always in the picture.** "You cooperated after
  being defected on" means something completely different against ``R1-1`` (which
  retaliates) than against ``S0`` (which never retaliates), so every reaction
  measure is conditioned on what the opponent was doing.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field

from dashboard.gameplay import Decision, Match


@dataclass
class Dimension:
    """One measured axis of play, with the evidence that produced it."""

    key: str
    title: str
    measurement: str          # what was counted
    value: str                # the number, formatted for display
    detail: str               # how to read it, in plain language
    evidence: list[str] = field(default_factory=list)
    counterfactual: str = ""  # what would have refuted it
    contradicts: list[str] = field(default_factory=list)
    # Raw numbers behind ``value``, so callers never have to parse prose.
    numbers: dict = field(default_factory=dict)

    def to_markdown(self) -> str:
        lines = ["### {}".format(self.title)]
        lines.append("")
        lines.append("- **测量方式**：{}".format(self.measurement))
        lines.append("- **结果**：{}".format(self.value))
        lines.append("- **含义**：{}".format(self.detail))
        if self.evidence:
            lines.append("- **证据**：")
            for item in self.evidence:
                lines.append("  - {}".format(item))
        if self.contradicts:
            lines.append("- **与之矛盾的数据**：")
            for item in self.contradicts:
                lines.append("  - {}".format(item))
        if self.counterfactual:
            lines.append("- **何种观察可推翻**：{}".format(self.counterfactual))
        lines.append("")
        return "\n".join(lines)


def _opponent_archetype(match: Match) -> str:
    """Group opponents by how they actually behaved in this very match."""
    if match.opponent_defection_rate == 0:
        return "从不背叛"
    if match.opponent_defection_rate < 0.25:
        return "极少背叛"
    if match.opponent_defection_rate < 0.6:
        return "间歇背叛"
    return "频繁背叛"


def _all(matches: list[Match]) -> list[Decision]:
    return [d for m in matches for d in m.decisions]


def _fmt_decision(d: Decision) -> str:
    return "第 {} 场第 {} 轮（对手 {}，标签 {}）：历史 你 {} / 对手 {}，你出 {}".format(
        d.match_index + 1, d.turn, d.opponent, d.opponent_label,
        d.player_history or "—", d.opponent_history or "—", d.action,
    )


def dim_opening(matches: list[Decision]) -> Dimension:
    """How the player opened each match, before any information existed."""
    firsts = [d.action for d in matches if d.is_first_round]
    opens = firsts.count("C")
    evidence = [
        "第 {} 场首轮出 {}".format(d.match_index + 1, d.action)
        for d in matches if d.is_first_round
    ][:6]
    return Dimension(
        key="opening",
        title="开局倾向：在没有任何信息时的第一手",
        measurement="统计 10 场对战的第一轮出招（此时对手尚未展示任何行为）",
        value="{} / {} 场首轮合作（{:.0%}）".format(opens, len(firsts),
                                             opens / max(len(firsts), 1)),
        detail=(
            "首轮不受对手行为影响，是这批数据里唯一真正无条件的观测。"
            "若你在这里选择背叛，说明你的默认倾向是先占便宜；"
            "若选择合作，说明你的默认倾向是先示好。"
            "注意这只描述默认值，不描述后续。"
        ),
        evidence=evidence,
        numbers={"opens": opens, "matches": len(firsts),
                 "rate": opens / max(len(firsts), 1)},
        counterfactual="若某几场首轮不同，说明你的默认倾向受对手编码以外的因素影响（例如你当时在观察上一场的残留印象）",
    )


def dim_retaliation(matches: list[Decision], by_match: dict[int, Match]) -> Dimension:
    """Did the player answer a defection with a defection, and how fast?"""
    provoked = [d for d in matches if d.provoked]
    retaliated = [d for d in provoked if d.action == "D"]
    forgave = [d for d in provoked if d.action == "C"]
    rate = len(retaliated) / max(len(provoked), 1)
    # How many turns of cooperation followed a provoked defection before the
    # player struck back, and how many before returning to cooperation.
    evidence = []
    for d in provoked[:5]:
        evidence.append(
            "{}；选 {} 得 {} 分（改选 {} 可得 {} 分），对手下一轮变为 {}（若改选则变为 {}）".format(
                _fmt_decision(d), d.action, d.payoff, d.alternative,
                d.alternative_payoff,
                d.opponent_next_if_chosen, d.opponent_next_if_alternative,
            )
        )
    if rate >= 0.7:
        detail = "你几乎总是用背叛回应背叛——这是一种同步式反应，代价是把自己也锁进互殴。"
    elif rate <= 0.3:
        detail = ("你在多数情况下选择不回击。注意这不等于宽容：还要看下一条"
                  "「主动剥削」——你是否在对手合作时反而背叛。")
    else:
        detail = "你的回击是有选择性的，不是一律报复，也不是一律忍让。"
    return Dimension(
        key="retaliation",
        title="对背叛的即时反应",
        measurement="统计对手上一轮背叛后、玩家接着出背叛的比例（共 {} 次被背叛）".format(len(provoked)),
        value="{} / {} 次回击（{:.0%}）；另有 {} 次选择继续合作".format(
            len(retaliated), len(provoked), rate, len(forgave)),
        detail=detail,
        evidence=evidence,
        numbers={"retaliated": len(retaliated), "provoked": len(provoked),
                 "rate": rate, "forgave": len(forgave)},
        counterfactual="若这个比例在不同对手类型之间差异很大，说明它不是稳定特质而是情境反应——这一点由「区分度」维度单独检验",
    )


def dim_exploitation(matches: list[Decision]) -> Dimension:
    """Defection while the opponent was cooperating: the part retaliation misses."""
    unprovoked = [d for d in matches if not d.provoked and d.turn > 1]
    exploits = [d for d in unprovoked if d.action == "D"]
    rate = len(exploits) / max(len(unprovoked), 1)
    gained = sum(
        d.immediate_delta for d in exploits if d.immediate_delta > 0
    )
    evidence = [
        "{}；得 {} 分，若改选 {} 则得 {} 分，对手下一轮 {}".format(
            _fmt_decision(d), d.payoff, d.alternative, d.alternative_payoff,
            "转为背叛" if d.opponent_next_if_alternative == "D"
            else "仍合作",
        )
        for d in exploits[:5]
    ]
    if not evidence:
        # No exploits means the evidence is the absence: name the opportunities
        # that were declined, with what they would have paid.
        declined = sorted(unprovoked, key=lambda d: -d.immediate_delta)[:4]
        evidence = [
            "{}；你选择 {} 得 {} 分，而改出 {} 可得 {} 分——你没有出手".format(
                _fmt_decision(d), d.action, d.payoff, d.alternative,
                d.alternative_payoff)
            for d in declined
        ] or ["全部 {} 次机会你都没有主动背叛。".format(len(unprovoked))]
    if rate >= 0.5:
        detail = ("你的背叛多数不是报复性的，而是在对手合作时主动出手。"
                  "这在计分上是占便宜，但它会训练对手进入防御姿态——"
                  "你之后的得分可能因此下降。")
    elif rate <= 0.15:
        detail = "你极少在对手合作时背叛。这意味着你放弃了一些即时收益，也保护了合作空间。"
    else:
        detail = "你在对手合作时也有一定比例的主动出手，但并非主要行为。"
    return Dimension(
        key="exploitation",
        title="主动剥削：在对手合作时出手",
        measurement="统计对手上一轮合作（非第 1 轮）时、玩家出背叛的比例（共 {} 次机会）".format(len(unprovoked)),
        value="{} / {} 次（{:.0%}），这些出手带来的即时净收益合计 {:+.0f} 分".format(
            len(exploits), len(unprovoked), rate, gained),
        detail=detail,
        evidence=evidence,
        numbers={"exploits": len(exploits), "opportunities": len(unprovoked),
                 "rate": rate, "net": gained},
        counterfactual="若这些主动出手并未带来更高总分（见「收益效率」），说明它们是无效攻击而非策略",
    )


def dim_discrimination(matches: list[Decision], by_match: dict[int, Match]) -> Dimension:
    """The important one: does the player behave differently toward different opponents?

    This is what separates a considered player from a fixed habit, and it is
    measured, not inferred. Opponents are grouped by how much they actually
    defected in their own match, and the player's response rate is compared
    across groups.
    """
    buckets: dict[str, list[Decision]] = {}
    for d in matches:
        archetype = _opponent_archetype(by_match[d.match_index])
        buckets.setdefault(archetype, []).append(d)

    rows = []
    for archetype, decisions in sorted(buckets.items()):
        provoked = [d for d in decisions if d.provoked]
        if not provoked:
            rows.append((archetype, 0, 0, 0.0))
            continue
        hits = sum(1 for d in provoked if d.action == "D")
        rows.append((archetype, len(buckets[archetype]), hits, hits / len(provoked)))

    rates = [r[3] for r in rows if r[1] > 0]
    spread = (max(rates) - min(rates)) if len(rates) > 1 else 0.0
    evidence = [
        "对「{}」型对手（共 {} 场）：被背叛 {} 次，其中回击 {:.0%}".format(
            archetype, n, hits, rate) for archetype, n, hits, rate in rows
    ]
    if spread >= 0.35:
        detail = ("你对不同对手的回应明显不同——这说明你的行为依赖对手做了什么，"
                  "而不是固定习惯。反过来说，你也在被对手牵着走。")
    elif spread <= 0.12:
        detail = ("你面对从不背叛、极少背叛、频繁背叛的对手，回击率几乎一样。"
                  "这意味着你的反应由你自己的内在规则驱动，而不是被对手诱导——"
                  "稳定，但也意味着你可能没在区分眼前这个人。")
    else:
        detail = "你的回应随对手有所变化，但差异不大，区分度偏弱。"
    return Dimension(
        key="discrimination",
        title="区分度：对不同对手是否区别对待",
        measurement="按对手在本场的实际背叛率分组，比较玩家「被背叛后回击」的比例",
        value="各组回击率 " + "、".join(
            "{} {:.0%}".format(a, r) for a, _, _, r in rows if _) + "；极差 {:.0%}".format(spread),
        detail=detail,
        evidence=evidence,
        numbers={"spread": spread, "groups": {a: r for a, _, _, r in rows}},
        counterfactual="若各组回击率一致，则你未在区分对手；若差异大且你并未有意为之，说明你容易被对手带动",
    )


def dim_endgame(matches: list[Decision]) -> Dimension:
    """Whether play changes in the last rounds, when retaliation is impossible."""
    final_round = [d for d in matches if d.is_final_round]
    last_three = [d for d in matches if d.turn >= 8]
    early = [d for d in matches if d.turn <= 2]
    final_d = sum(1 for d in final_round if d.action == "D")
    late_rate = (sum(1 for d in last_three if d.action == "D")
                 / max(len(last_three), 1))
    early_rate = sum(1 for d in early if d.action == "D") / max(len(early), 1)
    shift = late_rate - early_rate
    evidence = [
        "第 {} 场末轮：你 {}，对手 {}（此轮后不再有报复机会）".format(
            d.match_index + 1, d.action, d.opponent_action)
        for d in final_round[:5]
    ]
    if shift >= 0.2:
        detail = ("你在最后几轮明显更愿意见机行事。末轮背叛不会被惩罚，"
                  "所以这不是情绪而是算得清的选择——但它同时让对手在第 8-9 轮就转向防御。")
    elif shift <= -0.2:
        detail = "你在最后几轮更倾向合作，即使已经没有合作可续。可能是维持一致，也可能是收尾时松懈。"
    else:
        detail = "你的前段与后段出手频率接近，没有明显的收尾策略。"
    return Dimension(
        key="endgame",
        title="终局意识：明知无后续时的出手",
        measurement="比较第 1-2 轮与第 8-10 轮（及末轮）的背叛率",
        value="前段背叛率 {:.0%}，后段 {:.0%}，末轮 {} / {} 场背叛（变化 {:+.0%}）".format(
            early_rate, late_rate, final_d, len(final_round), shift),
        detail=detail,
        evidence=evidence,
        numbers={"early": early_rate, "late": late_rate, "shift": shift,
                 "final_defect": final_d, "final_matches": len(final_round)},
        counterfactual="若末轮背叛率与前面无差异，说明你没有利用「最后一步不可报复」这一点",
    )


def dim_punishment_duration(by_match: dict[int, Match]) -> Dimension:
    """After striking back, how long does the player stay out?"""
    runs = []
    for match in by_match.values():
        actions = match.player_actions
        index = 0
        while index < len(actions):
            if actions[index] == "D":
                end = index
                while end < len(actions) and actions[end] == "D":
                    end += 1
                if index > 0 and match.opponent_actions[index - 1] == "D":
                    runs.append(end - index)
                index = end
            else:
                index += 1
    mean_run = statistics.fmean(runs) if runs else 0.0
    if runs:
        detail = ("你每次回击后平均维持 {:.1f} 轮背叛。短回击把冲突快速降温，"
                  "长回击则把双方拖进持续互殴。".format(mean_run))
    else:
        detail = "你没有出现过「被背叛后连续多轮背叛」的形态，因此这一项没有数据。"
    return Dimension(
        key="punishment_duration",
        title="回击的持续长度",
        measurement="统计每次「被背叛后转为连续背叛」的段长（共 {} 段）".format(len(runs)),
        value="共 {} 段，平均 {:.1f} 轮，最长 {}".format(
            len(runs), mean_run, max(runs) if runs else 0),
        detail=detail,
        evidence=[
            "第 {} 场你的动作串 {}（对手 {}）".format(
                m.index + 1, m.player_actions, m.opponent_actions)
            for m in list(by_match.values())[:4]
        ],
        numbers={"segments": len(runs), "mean": mean_run,
                 "max": max(runs) if runs else 0},
        counterfactual="若平均段长接近 1，说明你倾向于「以牙还牙一次就翻篇」",
    )


def dim_score_efficiency(matches: list[Decision], by_match: dict[int, Match]) -> Dimension:
    """How much of the available payoff the player actually captured."""
    deltas = [d.immediate_delta for d in matches]
    given_up = sum(-x for x in deltas if x < 0)
    gained = sum(x for x in deltas if x > 0)
    player_total = sum(m.player_score for m in by_match.values())
    ceiling = player_total + given_up
    efficiency = player_total / ceiling if ceiling else 0.0
    evidence = sorted(
        (d for d in matches if d.immediate_delta < 0),
        key=lambda d: d.immediate_delta,
    )[:4]
    return Dimension(
        key="efficiency",
        title="收益效率：单步最优与实际出手的差距",
        measurement="逐步比较所选出手与另一手在同一局面下的即时得分，累加差额",
        value="实际总分 {:.0f}；放弃的即时收益 {:.0f} 分，赚到 {:+.0f} 分；单步最优可达 {:.0f}，你拿到 {:.0%}".format(
            player_total, given_up, gained, ceiling, efficiency),
        detail=(
            "这个数字衡量的是「你每一步是否拿到了当下能拿的最多分数」。"
            "它不评判对错——有时放弃即时收益是投资合作空间。"
            "但如果放弃的量很大，值得追问你在买什么。"
        ),
        evidence=[
            "{}；选 {} 得 {} 分，改选 {} 可得 {} 分（相差 {} 分）".format(
                _fmt_decision(d), d.action, d.payoff, d.alternative,
                d.alternative_payoff, d.immediate_delta)
            for d in evidence
        ],
        numbers={"total": player_total, "given_up": given_up,
                 "ceiling": ceiling, "efficiency": efficiency},
        counterfactual="若你拿到的比例接近 1，说明你几乎不浪费任何一步；若很低，说明你常为长期关系付出短期成本",
    )


def dim_leverage(matches: list[Decision], by_match: dict[int, Match]) -> Dimension:
    """Did the player's choices actually move the opponent's next action?"""
    moved = [d for d in matches
             if d.opponent_next_if_chosen != d.opponent_next_if_alternative]
    toward_d = sum(
        1 for d in moved if d.opponent_next_if_alternative == "D"
        and d.opponent_next_if_chosen == "C"
    )
    toward_c = sum(
        1 for d in moved if d.opponent_next_if_alternative == "C"
        and d.opponent_next_if_chosen == "D"
    )
    evidence = [
        "{}；你的出手使对手下一轮 {}，若改选 {} 则为 {}".format(
            _fmt_decision(d), d.opponent_next_if_chosen, d.alternative,
            d.opponent_next_if_alternative)
        for d in moved[:5]
    ]
    if moved:
        detail = ("在 {} 步上你的选择确实改变了对手的下一手：{} 步把它推向背叛，"
                  "{} 步把它拉回合作。这说明你的行为在改变生态，"
                  "而不只是被动接受。".format(len(moved), toward_d, toward_c))
    else:
        detail = "你的出手从未改变对手的下一手——对手的行为完全由它自己的规则决定，你的影响为零。"
    return Dimension(
        key="leverage",
        title="影响力：你的选择是否真的改变了对手",
        measurement="逐步比较「按你实际出招」与「改出另一手」两种情况下，对手下一轮的动作",
        value="{} / {} 步产生了不同的对手反应（{} 步推向背叛，{} 步拉回合作）".format(
            len(moved), len(matches), toward_d, toward_c),
        detail=detail,
        evidence=evidence,
        numbers={"moved": len(moved), "total": len(matches),
                 "toward_d": toward_d, "toward_c": toward_c},
        counterfactual="若这个数字长期为 0，说明你在这些对手面前没有可撬动之处，胜负完全由对手的固定规则决定",
    )


def dim_consistency(by_match: dict[int, Match]) -> Dimension:
    """Does the player repeat itself in identical situations?

    Opponents behave stochastically when they carry a ``C`` modifier, so
    identical-looking situations recur. Comparing the player's response to
    repeated situations separates a rule-driven player from a noisy one.
    """
    situations: dict[tuple, list[str]] = {}
    for match in by_match.values():
        for d in match.decisions:
            key = (match.opponent_defection_rate > 0.5, d.turn, d.provoked)
            situations.setdefault(key, []).append(d.action)
    repeated = {k: v for k, v in situations.items() if len(v) >= 2}
    consistent = 0
    rate = None
    if repeated:
        consistent = sum(1 for v in repeated.values() if len(set(v)) == 1)
        rate = consistent / len(repeated)
        detail = ("在 {} 个重复出现过的局面里，{} 个你的出手完全一致（{:.0%}）。"
                  "不一致意味着同样的情境你给了不同的答案——这本身不是缺点，"
                  "但它会让别人（和对手）难以预测你。".format(
                      len(repeated), consistent, rate))
    else:
        detail = "本局没有出现完全重复的局面，无法测量一致性。"
    unstable = [
        (key, actions) for key, actions in sorted(repeated.items())
        if len(set(actions)) > 1
    ][:4]
    evidence = [
        "局面（对手{}·第{}轮·是否被背叛={}）重复出现，你的出手分别是 {}".format(
            "高背叛" if key[0] else "低背叛", key[1], key[2], "、".join(actions))
        for key, actions in unstable
    ]
    if not evidence:
        top = sorted(repeated.items(), key=lambda kv: -len(kv[1]))[:3]
        evidence = [
            "局面（对手{}·第{}轮·是否被背叛={}）出现 {} 次，你的出手始终是 {}".format(
                "高背叛" if key[0] else "低背叛", key[1], key[2], len(actions),
                actions[0])
            for key, actions in top
        ] or ["没有可比对的重复局面。"]
    return Dimension(
        key="consistency",
        title="一致性：相同局面下是否重复自己",
        measurement="按（对手类型、本轮次、是否被背叛）分组，找出重复出现的局面并比较出手",
        value=("{} 个重复局面，一致率 {:.0%}".format(len(repeated), rate)
               if rate is not None else "无重复局面"),
        detail=detail,
        evidence=evidence,
        numbers={"repeated": len(repeated), "consistent": consistent,
                 "rate": rate},
        counterfactual="若一致率低，说明你的行为受当下情绪或随机判断影响较大",
    )


def build_profile(matches: list[Match]) -> dict:
    """Assemble every dimension plus the raw evidence bundle."""
    by_match = {m.index: m for m in matches}
    decisions = _all(matches)
    dimensions = [
        dim_opening(decisions),
        dim_retaliation(decisions, by_match),
        dim_exploitation(decisions),
        dim_discrimination(decisions, by_match),
        dim_endgame(decisions),
        dim_punishment_duration(by_match),
        dim_score_efficiency(decisions, by_match),
        dim_leverage(decisions, by_match),
        dim_consistency(by_match),
    ]
    return {
        "matches": matches,
        "decisions": decisions,
        "dimensions": dimensions,
        "player_total": sum(m.player_score for m in matches),
        "player_average": statistics.fmean([m.player_score for m in matches])
        if matches else 0.0,
        "total_defections": sum(1 for d in decisions if d.action == "D"),
        "total_turns": len(decisions),
    }
