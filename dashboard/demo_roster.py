"""演示用模拟名单：脚本生成一批「学生提交」，让教师端那一屏能被讲清楚。

为什么要有这个东西：参赛要展示「老师看得到全班打到哪儿了、榜怎么排、参照线怎么用」，
而本地库里只有几份自己点出来的测试记录。空看板讲不出任何教学故事，现场手点二十次又
不可复现，所以这里用固定种子一次性写出几十份提交。

三条硬约束：

1. **不采集任何个人信息**。模拟行走的是和真实提交完全相同的字段：随机加入码、老师自己
   起的班级码、题面参数、决策串。没有姓名，没有学号，也不假装有一张学生名单。
2. **每一行都标成模拟**。写进 ``runs.demo``，导出 CSV 时带着这一列，看板上出现任何一份
   模拟提交就整屏挂一块「模拟数据，非真实课堂」的牌子。这份数据不能也不能被截图时
   误读成一次真实试点——参赛材料里同样不得写「已在班级试用」。
3. **完全可复现**。同一个 seed 跑出同一批人、同一串决策；换 seed 换一批人。分数不是编的
   数字，而是 :class:`dashboard.gameplay.PlayerMatchRunner` 在题面的那套对手与那串随机流
   上真打出来的，所以老师点进任何一个模拟加入码，看到的报告、九项测量与博弈论读数都是
   按同一份决策重算出来的——演示的和真实对局走的是同一条代码路径。

学生不是从某个「性格库」里抽的：这里给的只是几条教科书标准策略（永远合作、永远背叛、
以牙还牙……）各自掺不同比例的临场翻转，用来把榜拉出层次。它是策略的分布，不是人的分布。
"""

from __future__ import annotations

import hashlib
import random

from strategy_engine.strategy_engine import StrategyState, parse_strategy
from trust_evolution_simulation import ENGINE_VERSION

from dashboard import challenges, store
from dashboard.gameplay import PlayerMatchRunner, draw_opponents

#: 默认种子。改它等于换一批人；同一 seed 两次写入得到同一批决策串。
SEED = 20261017

#: 班级码由老师自己起，所以演示用的这两个刻意写成一眼假的形状。
CLASSES = ("DEMO-A", "DEMO-B")

#: 每个班多少人。两个班共约 :data:`PER_CLASS` x len(CLASSES) 份挑战提交。
PER_CLASS = 22

#: 一个班的打法分布：几条标准策略各占若干人，每人再掺不同的临场翻转率。
#: 计数只是权重，加起来不必等于 ``PER_CLASS``——差的人会由前面几条补齐。
ARCHETYPES: tuple[tuple[str, int], ...] = (
    ("R1-1", 6),    # 以牙还牙
    ("S0", 4),      # 永远合作
    ("P2-1", 4),    # 宽容反击
    ("W", 4),       # 赢留输变
    ("SM", 3),      # 永远背叛
    ("T2-2", 3),    # 探子
    ("R1-2", 2),    # 双倍报复
)

#: 猜测那一栏的三种「信念」：读上一手、默认合作、默认背叛。
#: 它们是被猜的策略，不是被评价的人。
GUESS_STYLES = ("last", "always_c", "always_d")

#: 布置之后每刷新一次交上来的份数。一个真实班级不会在老师点刷新那一秒全班交完，
#: 所以按批放；``BATCH`` 就是「一批大约多少人」，不是「一共多少人」。
BATCH = 7

#: 一道题 × 一个班最多收几批。名单本身只有 :data:`PER_CLASS` 人，交完之后刷新
#: 返回 0；这个上限只是再兜一层，让演示数据不会随着手痒连点无限长大。
MAX_ROUNDS = 6


def _students(rng: random.Random) -> list[str]:
    """Expand :data:`ARCHETYPES` into ``PER_CLASS`` encodings, then shuffle."""
    pool: list[str] = []
    for encoding, weight in ARCHETYPES:
        pool.extend([encoding] * weight)
    while len(pool) < PER_CLASS:
        pool.append(rng.choice([item[0] for item in ARCHETYPES]))
    picked = pool[:PER_CLASS]
    rng.shuffle(picked)
    return picked


def _guess(style: str, last: str | None) -> str:
    if style == "always_c":
        return "C"
    if style == "always_d":
        return "D"
    return last or "C"


def _match(
    index: int, code: str, turns: int, seed: int, encoding: str,
    rng: random.Random, noise: float, guess_style: str | None, guess_rate: float,
) -> tuple[str, str]:
    """Play one scripted match; return the action string and the guess string.

    The opponent is the one the challenge names, fed the same ``seed + 1 + index``
    random stream a real player met, so replaying this row later scores exactly
    what the board shows.
    """
    runner = PlayerMatchRunner(index, code, turns, seed + 1 + index)
    policy = StrategyState(
        parse_strategy(encoding), turns, rng=random.Random(rng.randrange(1 << 30)))
    theirs: list[str] = []
    actions: list[str] = []
    guesses: list[str] = []
    while not runner.finished:
        action = policy.decide(list(theirs))
        if rng.random() < noise:
            action = "D" if action == "C" else "C"
        if guess_style is None or rng.random() > guess_rate:
            guess = None
        else:
            guess = _guess(guess_style, theirs[-1] if theirs else None)
        runner.set_prediction(guess)
        decision = runner.play(action)
        theirs.append(decision.opponent_action)
        actions.append(action)
        guesses.append(guess or "-")
    return "".join(actions), "".join(guesses)


def _free_play(rng: random.Random, encoding: str, noise: float) -> dict:
    """A run with no challenge attached: opponents drawn from the run's own seed."""
    count = rng.choice([4, 5, 6, 8])
    turns = rng.choice([8, 10, 12])
    seed = rng.randrange(1_000_000)
    codes = draw_opponents(count, seed)
    guess_style = rng.choice(GUESS_STYLES) if rng.random() < 0.5 else None
    guess_rate = rng.choice([0.4, 0.7, 1.0])
    actions, predictions = [], []
    for index, code in enumerate(codes):
        played, guessed = _match(
            index, code, turns, seed, encoding, rng, noise, guess_style, guess_rate)
        actions.append(played)
        predictions.append(guessed)
    return {
        "challenge_id": "",
        "count": count,
        "turns": turns,
        "seed": seed,
        "actions": actions,
        "predictions": predictions if guess_style else [],
        "status": "finished",
        "tutorial_done": True,
    }


def build(
    seed: int = SEED, classes: tuple[str, ...] = CLASSES,
    presets: tuple[str, ...] = ("P-R1EC", "P-CPET", "P-RNDM", "P-BITE"),
) -> list[dict]:
    """The demo rows, in a shape :func:`load` can write straight to the store.

    Each student plays one or two of the built-in challenges; a minority leave one
    run half-finished, because a class always has someone who closed the tab and
    the board has to show what that looks like.
    """
    rng = random.Random(seed)
    rows: list[dict] = []
    for class_code in classes:
        for encoding in _students(rng):
            noise = rng.choice([0.0, 0.05, 0.1, 0.15, 0.25])
            guess_style = rng.choice(GUESS_STYLES) if rng.random() < 0.55 else None
            guess_rate = rng.choice([0.5, 0.8, 1.0])
            picks = [rng.choice(presets)]
            if rng.random() < 0.3:
                picks.append(rng.choice(presets))
            for task_id in dict.fromkeys(picks):
                challenge = challenges.preset(task_id)
                if challenge is None:
                    continue
                actions, predictions = [], []
                for index, code in enumerate(challenge["codes"]):
                    played, guessed = _match(
                        index, code, challenge["turns"], challenge["seed"],
                        encoding, rng, noise, guess_style, guess_rate)
                    actions.append(played)
                    predictions.append(guessed)
                status = "finished"
                if rng.random() < 0.1:
                    # 半局：最后一份对手只打了几轮，榜会把它跳过。
                    actions[-1] = actions[-1][: max(1, len(actions[-1]) // 2)]
                    predictions[-1] = predictions[-1][:len(actions[-1])]
                    status = "playing"
                rows.append({
                    "class_code": class_code,
                    "challenge_id": challenge["challenge_id"],
                    "count": len(challenge["codes"]),
                    "turns": challenge["turns"],
                    "seed": challenge["seed"],
                    "actions": actions,
                    "predictions": predictions if guess_style else [],
                    "status": status,
                    "tutorial_done": rng.random() > 0.15,
                })
    for _ in range(4):
        rows.append(dict(_free_play(rng, rng.choice([item[0] for item in ARCHETYPES]),
                                    rng.choice([0.0, 0.1, 0.2])),
                         class_code=rng.choice(classes)))
    return rows


def _join_codes(count: int, seed: int) -> list[str]:
    """``count`` unused codes, drawn from a stream keyed to ``seed``.

    Codes are the only handle on a run, so a collision with a real submission is
    not cosmetic: the demo row would overwrite nothing (writes are guarded) but the
    batch would silently come up short. Drawing again until the code is free keeps
    the batch the size the board is going to claim.
    """
    rng = random.Random(seed)
    codes: list[str] = []
    taken: set[str] = set()
    while len(codes) < count:
        for _ in range(400):
            code = "".join(
                rng.choice(store.CODE_ALPHABET) for _ in range(store.CODE_LENGTH))
            if code in taken:
                continue
            if store.load_run(code) is not None:
                continue
            taken.add(code)
            codes.append(code)
            break
        else:
            raise RuntimeError("模拟名单：连续抽不到空闲的加入码，换 seed 再试。")
    return codes


def load(seed: int = SEED, classes: tuple[str, ...] = CLASSES) -> int:
    """Write the demo batch into the store. Returns how many rows were written."""
    rows = build(seed=seed, classes=classes)
    codes = _join_codes(len(rows), seed)
    for row, code in zip(rows, codes):
        row["join_code"] = code
        store.create_run(
            code, class_code=row["class_code"], opponent_count=row["count"],
            turns=row["turns"], seed=row["seed"], engine_version=ENGINE_VERSION,
            tutorial_done=row["tutorial_done"], challenge_id=row["challenge_id"],
            demo=True,
        )
        store.save_progress(
            code, actions=row["actions"], tutorial_done=row["tutorial_done"],
            status=row["status"],
            predictions=row["predictions"] or None,
        )
    return len(rows)


def _key(*parts: object) -> int:
    """A stream keyed to a (班级, 挑战, 批次) triple.

    ``str`` hashing is salted per process, so the class codes and challenge ids
    have to be digested rather than handed to :func:`hash`; otherwise the same
    refresh on a different day would fabricate a different batch of students.
    """
    joined = "|".join(str(part) for part in parts)
    digest = hashlib.sha256(joined.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def roster(class_code: str, seed: int = SEED) -> list[str]:
    """One class's simulated students, in a stable order.

    Order is the whole point: refresh N has to be the N-th slice of this same
    list, not a fresh draw, or the second batch would be a different set of
    people handing in a题面 the first batch already submitted.
    """
    return _students(random.Random(_key("roster", seed, class_code)))


def batch_plan(class_code: str, round_index: int, seed: int = SEED) -> list[str]:
    """The encodings that hand in during ``round_index``; empty once交完了."""
    if not 1 <= round_index <= MAX_ROUNDS:
        return []
    start = (round_index - 1) * BATCH
    return roster(class_code, seed)[start:start + BATCH]


def submit_batch(
    challenge: dict, class_code: str, round_index: int, seed: int = SEED,
) -> int:
    """Write one refresh's worth of hand-ins for an assigned题面.

    「刷新一次收一部分」走的是这条：第 ``round_index`` 批是这个班固定名单里的第
    ``(r-1) * BATCH`` 到 ``r * BATCH`` 个人，所以刷新是接着上一次往下走，而不是把
    同一批人重交一遍；名单交完以后再刷新就是 0 份，教师端据此回显「这次没有新提交」。

    写进去的每一行和 :func:`build`、和一份真实提交走的是同一套东西：同一批策略编码、
    同一个 :class:`~dashboard.gameplay.PlayerMatchRunner`、同一个
    :func:`store.create_run` / :func:`store.save_progress`，并且一律 ``demo=True``。
    """
    picked = batch_plan(class_code, round_index, seed)
    if not picked:
        return 0
    codes = _join_codes(
        len(picked),
        _key("codes", seed, class_code, challenge["challenge_id"], round_index),
    )
    start = (round_index - 1) * BATCH
    for offset, encoding in enumerate(picked):
        rng = random.Random(_key("student", seed, class_code, start + offset))
        noise = rng.choice([0.0, 0.05, 0.1, 0.15, 0.25])
        guess_style = rng.choice(GUESS_STYLES) if rng.random() < 0.55 else None
        guess_rate = rng.choice([0.5, 0.8, 1.0])
        actions: list[str] = []
        predictions: list[str] = []
        for index, code in enumerate(challenge["codes"]):
            played, guessed = _match(
                index, code, challenge["turns"], challenge["seed"],
                encoding, rng, noise, guess_style, guess_rate)
            actions.append(played)
            predictions.append(guessed)
        status = "finished"
        if rng.random() < 0.1:
            # 一个班总有人关了标签页：最后一局只打几轮，榜会把他跳过。
            actions[-1] = actions[-1][: max(1, len(actions[-1]) // 2)]
            predictions[-1] = predictions[-1][:len(actions[-1])]
            status = "playing"
        join_code = codes[offset]
        store.create_run(
            join_code, class_code=class_code, opponent_count=len(challenge["codes"]),
            turns=challenge["turns"], seed=challenge["seed"],
            engine_version=ENGINE_VERSION, tutorial_done=True,
            challenge_id=challenge["challenge_id"], demo=True,
        )
        store.save_progress(
            join_code, actions=actions, tutorial_done=True, status=status,
            predictions=predictions if guess_style else None,
        )
    return len(picked)


def clear() -> int:
    """Remove every simulated row. Real submissions are not touched."""
    return store.clear_demo_runs()


def count() -> int:
    """How many simulated submissions are currently in the store."""
    return store.demo_runs()


def summary(rows: list[dict]) -> list[dict]:
    """Per-class, per-challenge counts for the teacher panel's echo line."""
    grouped: dict[tuple[str, str], int] = {}
    for row in rows:
        key = (row["class_code"], row["challenge_id"] or "自由对局")
        grouped[key] = grouped.get(key, 0) + 1
    return [
        {"班级码": class_code, "挑战码": task_id, "份数": number}
        for (class_code, task_id), number in sorted(grouped.items())
    ]
