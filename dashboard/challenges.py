"""教师下发的挑战：一套固定对手、固定轮数、固定种子，外加几个标准策略当参照线。

为什么要把标准策略一起算进来：学生看到"你排第 3"只知道自己在一批人里的位置，
而看到 R1-1 在这套对手上拿 78 分、在那套上只有 41 分，才知道所谓最佳打法是情境
的函数。这正好是本项目的主题——合作的代价与收益取决于对面是谁。

所以基准与学生对局的条件必须一致：同一串对手编码、同一个轮数、同一份种子。
学生那一局里第 i 个对手用的是 ``seed + 1 + i`` 这条随机流（见
:meth:`dashboard.gameplay.PlayerMatchRunner`），这里给基准策略也按同样的方式配种子，
让它们面对的是同一批对手、同一批随机数源。

隐私：排名只认加入码——一个随机 8 字符，不带姓名、不带账号。老师要把码对到人，
得在纸面上自己完成；这张表里没有、也不该有能指认到人的东西。
"""

from __future__ import annotations

import random

from strategy_engine.strategy_engine import StrategyState, parse_strategy
from trust_evolution_simulation import PAYOFFS

from dashboard.gameplay import PlayerMatchRunner

#: 挑战码的字母表：和加入码一样避开 I/O/0/1，抄在黑板上也不会抄错。
TASK_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
TASK_LENGTH = 6

#: 标准策略参照线。编码都是本站的写法，括号里是教科书名字。
STANDARDS: list[tuple[str, str, str]] = [
    ("S0", "永远合作", "教科书里的 ALLC：始终出合作。"),
    ("SM", "永远背叛", "教科书里的 ALLD：始终出背叛。"),
    ("R1-1", "以牙还牙", "被背叛一轮就还手一轮，即 TFT。"),
    ("R1-2", "双倍报复", "被背叛一轮还两轮，比 TFT 更狠。"),
    ("P2-1", "宽容反击", "累计被单方面背叛两次才反击，即 generous TFT。"),
    ("W", "赢留输变", "Pavlov：这轮占到便宜就照旧，吃了亏就翻转。"),
    ("T2-2", "探子", "先背叛两轮再合作两轮，循环试探。"),
]

#: 预置挑战。老师不用配任何东西就能直接下发；自建挑战走同一套数据结构。
PRESETS: list[dict] = [
    {
        "challenge_id": "P-R1EC",
        "title": "报复生态",
        "blurb": "对手几乎都会还手：R1-1 及其变种。先手背叛在这里基本是纯亏损。",
        "codes": ["R1-1", "R1-2", "R1-M", "S0+R1-1", "P1-1", "K3-1"],
        "turns": 8,
        "seed": 20261001,
    },
    {
        "challenge_id": "P-CPET",
        "title": "合作生态",
        "blurb": "对手以善意为默认值。背叛在这里来钱很快——看它能在总分上换回多少。",
        "codes": ["S0", "B1-2", "RC3-3", "K3-1", "S3", "W"],
        "turns": 8,
        "seed": 20261002,
    },
    {
        "challenge_id": "P-RNDM",
        "title": "随机生态",
        "blurb": "对手带修正槽（神经质 / 心狠 / 失忆），行为里有真正的噪声。"
                 "看你在无法建模的对手面前怎么选。",
        "codes": ["C1", "C2-D", "P1-1+C2", "D1", "AD1", "BS1+M1"],
        "turns": 8,
        "seed": 20261003,
    },
    {
        "challenge_id": "P-BITE",
        "title": "背刺生态",
        "blurb": "对手里有一直合作到末几轮才下手的背刺者，也有明牌恶棍。"
                 "末轮的含金量在这里最高。",
        "codes": ["BS1", "BS2", "BS3", "SM+R1-1", "T2-2", "SM"],
        "turns": 8,
        "seed": 20261004,
    },
    {
        # 六个对手 = 六种活法，一套题把九项读数各自需要的事件都造出来：有善者可占、
        # 有恶棍可躲、有镜子可学、有血仇可怕。刻意让「盲善」和「盲恶」都排在中间名
        # 次之外——这一套要教的是「对面是谁」比「你信什么」更决定分数。
        "challenge_id": "P-SPEC",
        "title": "众生生态",
        "blurb": "六个对手各属一类：老好人、恶棍、还手就翻篇的报复者、被咬一口记到"
                 "底的血仇、先打两轮再示好的探子、照你最近历史出牌的跟风者。"
                 "没有一种打法能通吃。",
        "codes": ["S0", "SM", "R1-1", "R1-M", "T2-2", "D1"],
        "turns": 8,
        "seed": 20261005,
    },
]


def canonical(task_id: str) -> str:
    """The one form a challenge code is stored and looked up in.

    Preset codes are written for the blackboard (``P-R1EC``), but a hyphen is the
    first thing a student drops when retyping it, and a code that half-matches
    silently un-groups a class from its own ranking. So separators are removed on
    the way in everywhere -- write, read, and compare all use this.
    """
    return "".join(ch for ch in (task_id or "").upper() if ch.isalnum())


def new_challenge_id() -> str:
    """A 6-character task code that is not already a preset."""
    taken = {preset_id(item) for item in PRESETS}
    while True:
        code = "".join(random.SystemRandom().choice(TASK_ALPHABET)
                       for _ in range(TASK_LENGTH))
        if code not in taken:
            return code


def preset_id(item: dict) -> str:
    """The lookup key for a built-in challenge, in canonical form."""
    return canonical(item["challenge_id"])


def validate_codes(text: str) -> list[str]:
    """Parse one encoding per line (or comma / space separated) into a code list.

    Rejected here rather than later because a challenge that half-loads would
    hand two classes different opponent sets while showing them the same title.
    """
    tokens = [part.strip() for part in text.replace(",", "\n").splitlines()
              if part.strip()]
    if not tokens:
        raise ValueError("至少需要一个对手编码。")
    if len(tokens) > 12:
        raise ValueError("一套挑战最多 12 个对手（一节课打不完）。")
    codes: list[str] = []
    for token in tokens:
        try:
            parse_strategy(token)
        except Exception as error:  # noqa: BLE001 - engine raises its own types
            raise ValueError("编码「{}」读不通：{}".format(
                token, str(error)[:60])) from error
        if token in codes:
            raise ValueError("编码「{}」重复了。".format(token))
        codes.append(token)
    return codes


def preset(challenge_id: str) -> dict | None:
    """One built-in challenge by code, typed with or without the dash."""
    wanted = canonical(challenge_id)
    for item in PRESETS:
        if preset_id(item) == wanted:
            return dict(item)
    return None


def steps(challenge: dict) -> int:
    return len(challenge["codes"]) * challenge["turns"]


def replay_total(codes: list[str], turns: int, seed: int,
                 actions: list[str]) -> tuple[float, bool]:
    """Re-score a submission and say whether it is complete.

    The engine is deterministic, so a stored action string replays to exactly
    the score the student saw -- which is why only decisions are ever stored.
    An unfinished submission scores nothing rather than a misleading partial.
    """
    total = 0.0
    complete = len(actions) == len(codes)
    for index, code in enumerate(codes):
        given = actions[index] if index < len(actions) else ""
        if len(given) < turns:
            complete = False
            given = given.ljust(turns, "C")[:turns]
        runner = PlayerMatchRunner(
            index=index, opponent=code, turns=turns, seed=seed + 1 + index)
        for action in given:
            runner.play(action if action in ("C", "D") else "C")
        total += runner.finish().player_score
    return total, complete


def _mirror_match(player_code: str, opponent_code: str, turns: int,
                  seed: int) -> float:
    """What ``player_code`` scores against ``opponent_code`` in one match.

    Two independent random streams (one per side) rather than the shared one in
    :func:`dashboard.gameplay.play_auto_match`: the opponent gets ``seed``, which
    is the same value the student's runner handed it, so a baseline and a human
    meet the same dice even though their own choices differ.
    """
    a = StrategyState(parse_strategy(player_code), turns, rng=random.Random(seed + 777))
    b = StrategyState(parse_strategy(opponent_code), turns, rng=random.Random(seed))
    mine: list[str] = []
    theirs: list[str] = []
    score = 0.0
    for _ in range(turns):
        action_a = a.decide(theirs)
        action_b = b.decide(mine)
        mine.append(action_a)
        theirs.append(action_b)
        score += PAYOFFS[(action_a, action_b)][0]
    return score


def baseline_totals(codes: list[str], turns: int, seed: int,
                    standards: list[tuple[str, str, str]] | None = None,
                    ) -> list[dict]:
    """Each standard strategy's total on this challenge, best first."""
    rows = []
    for encoding, label, note in (standards or STANDARDS):
        total = sum(
            _mirror_match(encoding, code, turns, seed + 1 + index)
            for index, code in enumerate(codes)
        )
        rows.append({"code": encoding, "label": label, "note": note,
                     "score": total})
    rows.sort(key=lambda row: row["score"], reverse=True)
    return rows


def _percentile(sorted_values: list[float], fraction: float) -> float:
    """Nearest-rank percentile, good enough for a class-sized sample."""
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, max(0, int(round(fraction * (len(sorted_values) - 1)))))
    return sorted_values[index]


def ranking(challenge: dict, runs: list[dict], join_code: str = "",
            standards: list[tuple[str, str, str]] | None = None) -> dict:
    """Score every submission to one challenge and place them side by side.

    ``runs`` are store rows (join code + action strings); each is replayed here
    rather than read from a stored score, so a ranking can never drift away from
    the decisions it describes.
    """
    codes = challenge["codes"]
    turns = challenge["turns"]
    seed = challenge["seed"]
    rows = []
    for run in runs:
        total, complete = replay_total(codes, turns, seed, run["actions"])
        if not complete:
            continue
        rows.append({
            "join_code": run["join_code"],
            "score": total,
            "updated_at": run.get("updated_at", ""),
        })
    rows.sort(key=lambda row: row["score"], reverse=True)

    scores = [row["score"] for row in rows]
    baselines = baseline_totals(codes, turns, seed, standards)
    for row in baselines:
        row["above"] = sum(1 for score in scores if score > row["score"])

    yours = None
    rank = None
    if join_code:
        for index, row in enumerate(rows):
            if row["join_code"] == join_code:
                yours = row
                # Competition ranking: equal scores share a place, and the next
                # one skips. A class of identical strategies should read as one
                # place, not as an arbitrary ordering of ties.
                rank = sum(1 for score in scores if score > row["score"]) + 1
                break
    return {
        "rows": rows,
        "baselines": baselines,
        "yours": yours,
        "rank": rank,
        "count": len(rows),
        "median": _percentile(scores, 0.5),
        "first_quartile": _percentile(scores, 0.75),
        "top_quartile": _percentile(scores, 0.25),
        "steps": len(codes) * turns,
    }
