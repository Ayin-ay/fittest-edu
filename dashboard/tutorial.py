"""A tutorial that is played against a real opponent from the engine.

The previous version invented its own scripted opponent. Two problems followed:
the copy could not react to the player, and the advice had to be defended because
the opponent's behaviour was arbitrary rather than something the player could
actually observe. Here the opponent is the engine's own ``R1-1`` -- retaliate once
-- driven through the same ``PlayerMatchRunner`` the real match uses. Everything
the player is told is computed from the match that just happened, so the text
cannot disagree with the game.

The strategy is not named during play. Revealing "it retaliates once" would turn
the tutorial into pattern-matching instead of observation, which is the habit the
real match is meant to break; the rule is disclosed once, at the end.
"""

from __future__ import annotations

from dataclasses import dataclass, field

C = "C"
D = "D"

TURN = 20
TUTORIAL_TURNS = 5
TUTORIAL_OPPONENT = "R1-1"

POINTS = {
    (C, C): (3, 3),
    (C, D): (0, 5),
    (D, C): (5, 0),
    (D, D): (1, 1),
}

WORDS = {C: "合作", D: "背叛"}


def payoff(mine: str, theirs: str) -> tuple[int, int]:
    return POINTS[(mine, theirs)]


@dataclass
class TutorialState:
    step: int = 0
    mine: list = field(default_factory=list)
    theirs: list = field(default_factory=list)
    points: int = 0
    last_note: str = ""
    done: bool = False

    def history(self) -> tuple[str, str]:
        return "".join(self.mine), "".join(self.theirs)

    def running(self) -> tuple[int, int]:
        mine = their = 0
        for a, b in zip(self.mine, self.theirs):
            m, t = payoff(a, b)
            mine += m
            their += t
        return mine, their


def lesson_advice(turn: int) -> str:
    """What the tutorial wants the player to try on each scripted turn.

    Separate from ``advice_for`` on purpose. The lesson is a teaching
    sequence -- probe once, then make peace -- and it deliberately asks for a
    move that scores lower than the alternative on some turns. Confusing that
    with "which button earns more this round" is exactly what made the earlier
    versions read as though they were arguing with themselves.
    """
    return {0: C, 1: C, 2: D, 3: C, 4: C}.get(turn, C)


def score_line(theirs: str) -> tuple[int, int, str]:
    """Both choices' payoffs against ``theirs``, for the pre-turn prompt."""
    return payoff(C, theirs)[0], payoff(D, theirs)[0], theirs


def advice_for(theirs: str) -> str:
    """The higher-scoring choice this turn.

    Kept next to the scoring helper so the advice and the prices quoted to the
    player are always derived from the same table.
    """
    coop, defect, _ = score_line(theirs)
    return D if defect > coop else C


def opening_note(turn: int, state_mine: list, state_theirs: list) -> str:
    """The teaching point for this turn, written against what actually happened.

    The lessons themselves are scripted, but every sentence about the player's
    own past is read off the real history. An earlier version hardcoded "你连着
    合作两轮" into turn 3, which is simply false for a player who defected --
    the tutorial then described a game that was not being played. Each clause is
    conditional on the actual sequence, and falls back to the advice alone when
    the history does not support it.
    """
    n = len(state_mine)
    mine = "".join(state_mine)
    theirs = "".join(state_theirs)

    if turn == 0:
        return (
            "开局先摸清对方的底。第一轮看不出什么，**先合作**是最稳的开局："
            "你既可能白得 3 分，也可能踩到一次背叛只拿 0 分。"
        )
    if turn == 1:
        return (
            "第二轮仍然**建议合作**。"
            + (
                "一轮数据说明不了问题，连着两轮都合作仍然合作，"
                "才能确认它不是一次性的善意。"
                if n >= 1 and mine[-1] == "C" else
                "上一轮你选了背叛，这一次正好看看它会不会同样还手。"
            )
        )
    if turn == 2:
        if n >= 2 and mine[-2:] == "CC" and theirs[-2:] == "CC":
            return (
                "**这一轮建议背叛一次。** 你连着合作两轮，它也合作两轮——"
                "这时候试一次背叛，代价很小，但你能看清它会怎么反应。"
                "这一步是主动试探，不是为了占便宜。"
            )
        return (
            "**这一轮建议背叛一次。** 你前两轮并不都是合作，"
            "这一步的试探意义比顺水推舟更大："
            "看清它在连续交手之后会怎么反应。"
            + ("（你上一轮是背叛。）" if n >= 1 and mine[-1] == "D" else "")
        )
    if turn == 3:
        if n >= 1 and mine[-1] == "D":
            return (
                "上一轮你背叛了。**这一轮建议合作**，"
                "把这次试探收回来，看对方接不接——"
                "主动示好一次，比一直压着更容易换回合作。"
            )
        return (
            "看上一轮的结果。**这一轮建议合作**，"
            "把这次试探收尾，不要因为刚才赢过一次就继续压。"
        )
    if turn == 4:
        if n >= 1 and mine[-1] == "C" and theirs[-1] == "C":
            return (
                "上一轮双方都选择了合作。**这一轮继续合作**，"
                "把这次试探好好收尾。"
            )
        return (
            "再看你刚拿到的那一轮结果。**这一轮建议合作**，"
            "把这次试探收尾，不要因为刚才赢过一次就继续压。"
        )
    return "继续按你的判断走。"


def _streak(seq: str) -> int:
    """How many identical actions in a row the sequence ends with."""
    if not seq:
        return 0
    last = seq[-1]
    n = 0
    for ch in reversed(seq):
        if ch != last:
            break
        n += 1
    return n


def _describe_pattern(mine: str) -> str:
    """A truthful phrase for what the player has been doing so far.

    The previous wording asserted a fixed story regardless of history, so a
    player who defected twice was told their cooperation had been punished.
    """
    if not mine:
        return "目前还没有任何记录"
    coop = mine.count("C")
    defect = mine.count("D")
    if defect == 0:
        return "你到目前为止一直合作，没有背叛过"
    if coop == 0:
        return "你到目前为止一直在背叛，没有合作过"
    tail = ""
    run = _streak(mine)
    if run >= 2:
        tail = "，而且最近连续 {} 轮都是{}".format(
            run, "合作" if mine[-1] == "C" else "背叛")
    elif mine[-1] == "D":
        tail = "，上一轮你刚刚背叛"
    return "你到现在合作 {} 轮、背叛 {} 轮{}".format(coop, defect, tail)


def outcome_note(state_mine: list, state_theirs: list,
                 action: str, theirs: str, step: int) -> str:
    """What just happened, read off the turn that was really played.

    Every sentence about the player's own past is derived from ``state_mine``;
    nothing is asserted that the sequence does not support.
    """
    mine_pts, their_pts = payoff(action, theirs)
    n = len(state_mine)
    prior = state_mine[:-1]
    score = "这一轮你 {} 分、它 {} 分。".format(mine_pts, their_pts)

    if n == 1:
        if theirs == C:
            return (
                "它也选择合作，各得 {} 分。"
                "开局没有冲突——但这还不能说明它接下来会怎么做。".format(mine_pts)
            )
        return (
            "它第一轮就背叛，你只拿到 {} 分。"
            "开局并不总是友善的。".format(mine_pts)
        )

    prev_me = prior[-1]

    if prev_me == "C" and theirs == "D":
        lead = ("你连续两轮合作，" if _streak(prior) >= 2
                else "你上一轮的合作，")
        return (
            "它上一轮合作，这一轮却**背叛**——"
            "{}换来的是一次突袭。它不是随机出手，"
            "它在跟着你最近一次的选择走。".format(lead) + score
        )
    if prev_me == "D" and theirs == "D":
        return (
            "你上一轮背叛，它这一轮**原样还给你**。"
            "它没有惩罚你，也没有原谅你，只是把你的动作退了回来——"
            "这正是它记住你的方式。" + score
        )
    if prev_me == "D" and theirs == "C":
        return (
            "你上一轮背叛，它这一轮却**合作**——"
            "在连续对局里这是一种让步，你把机会递回去了。" + score
        )
    if prev_me == "C" and theirs == "C":
        return (
            "你上一轮合作，它这一轮**继续合作**。"
            "它不是在奖励你，只是跟着你最近一次的选择走。" + score
        )

    if theirs == "D" and action == "C":
        return (
            "你选择合作，它选择背叛——你颗粒无收，它拿到 {} 分。"
            "这一次是你把决定权交给了对方。".format(their_pts)
        )
    if theirs == "D" and action == "D":
        return (
            "你们互相背叛，各得 {} 分。"
            "这是这一轮能拿到的最好结果。".format(mine_pts)
        )
    if theirs == "C" and action == "D":
        return (
            "它选择合作，你选择背叛，拿到了这一轮最高的 {} 分。"
            "分数上你赢了，接下来它怎么回应，取决于它有没有记住。".format(
                mine_pts)
        )
    return "它这一轮选择合作，各得 {} 分。{}".format(mine_pts, score)



def reacted_note(state_mine: list, state_theirs: list,
                 action: str, theirs: str, followed: bool) -> str:
    """The opponent's reply, then what it implies for the next turn.

    Only ever called when the player went against the advice, so the tone is
    "you chose differently -- here is what that produced" rather than a
    rebuke. The opponent's reply is described as what was actually observed:
    ``R1-1`` mirrors the player's previous move, so it is written as a reaction
    to *that* move and not as an emotion the strategy cannot have.

    Every clause is derived from the real history. An earlier version asserted
    "two defections in a row" without checking, and said it on a turn where the
    player had gone D, C, C.
    """
    n = len(state_mine)
    mine_pts, their_pts = payoff(action, theirs)
    score = "这一轮你 {} 分、它 {} 分。".format(mine_pts, their_pts)
    previous = state_mine[-2] if n >= 2 else None
    streak = n >= 2 and state_mine[-2] == action == "D"

    if n == 1:
        # The player refused the advice on the opening turn. It still scored
        # the maximum, because the opponent had not moved yet -- but the score
        # is *not* the same as cooperating, and saying so would teach exactly
        # the wrong lesson.
        return (
            "第 1 轮你没有按建议来，直接背叛。这一轮它还没出手，"
            "所以你拿到了最高的 {} 分（合作只有 3 分）。"
            "但这个分数**不是白来的**：它这一轮同样合作，"
            "意味着它把机会留给了你——第 2 轮它会照着你这一手来。".format(mine_pts)
        )

    if theirs == D and previous == D:
        return (
            "它对你上一轮的背叛作出反应，**这一轮也背叛**。"
            + ("你连着两轮都选了背叛，它也在连着两轮还手——"
               "同样地不再合作，是它此刻能给的最直接回应。"
               if streak else
               "它没有因为你上一轮的退让而收手："
               "它只按你最近一次的动作来回应。")
            + score
            + "接下来要么继续把它推到只剩背叛，要么先停手。"
        )

    if theirs == C and previous == C:
        return (
            "你上一轮选了合作，它**这一轮也合作**——你们又开始一起收场了。"
            "这不是它在奖励你，只是它跟着你最近一次的选择走。"
            + score
        )

    if theirs == C and previous == D:
        return (
            "它这一轮**合作**了，哪怕你上一轮背叛过它——"
            "它在连输之后退了回来。这是一个可以重新开始的窗口，"
            "但窗口不会一直开着。"
            + score
        )

    return (
        "它这一轮**背叛**，和你上一轮选的一样。"
        "它没有惩罚你，也没有原谅你，只是把你最近一次的动作退了回来。"
        + score
    )


def describe_last(state_mine: list, state_theirs: list) -> str:
    """What the opponent just did, as an observation only."""
    if not state_theirs:
        return "对手还没出过手。**先看它这一轮怎么做。**"
    theirs = state_theirs[-1]
    mine = state_mine[-1] if state_mine else None
    if theirs == C:
        return "对手这一轮**合作**。它没有因为你上一轮的动作而改变。"
    if mine == D:
        return (
            "对手这一轮**背叛**。你上一轮是合作，"
            "它这一轮却反过来——这不是巧合，它在回应你。"
        )
    return "对手这一轮**背叛**，和你上一轮一样。"


def play(state: TutorialState, action: str, theirs: str) -> tuple[int, int, str]:
    """Record a turn whose opponent move was produced by the real engine."""
    if action not in (C, D):
        raise ValueError("action must be C or D")
    if state.step >= TUTORIAL_TURNS:
        raise ValueError("tutorial already finished")
    mine, their_points = payoff(action, theirs)
    state.mine.append(action)
    state.theirs.append(theirs)
    state.points += mine
    state.step += 1
    if state.step >= TUTORIAL_TURNS:
        state.done = True
    return mine, their_points, theirs


INTRO = (
    "每轮你和对手各自选择 **合作（C）** 或 **背叛（D）**。"
    "你看不到对手的策略，只能靠它的行为判断。\n\n"
    "这五轮我会告诉你每个选择各得多少分，**但不会告诉你对手是谁**。"
    "先和它打五轮，试着从它的动作里看出规律。"
)

RULES = [
    ("你和对手都合作", "各得 3 分", "coop"),
    ("你合作、它背叛", "你 0 分，它 5 分", "defect"),
    ("你背叛、它合作", "你 5 分，它 0 分", "mutual"),
    ("双方都背叛", "各得 1 分", "mutual"),
]

CLOSING = (
    "五轮打完。说回刚才那个对手：它不是随机的，它在**记住你做过什么**。\n\n"
    "正式对局里，对手是 10 个随机策略，有的开局就试探、有的被打一次就报复、"
    "有的连续背叛好几轮才让步，**没有一个统一规则**。"
    "所以别去找公式，要看的是**它刚才做了什么**，以及那件事是不是因为**你**才发生的。\n\n"
    "全部对局打完后，你会先看到六条博弈论读数——每条都是课本上的一句条件句配上"
    "你这次的数据；再往下是九项维度的得分和一张完整的决策热图。"
    "还可以让大模型把这份逐轮记录讲回那几条结论，它只解释数字，不评价人。"
)


def tutorial_progress(state: TutorialState) -> tuple[int, int]:
    return state.step, TUTORIAL_TURNS