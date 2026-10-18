"""模拟名单自检：可复现、能被重放评分、CSV 带标记、真实行不受影响。

用法：
    ../.venv/Scripts/python.exe -X utf8 tools/demo_roster_check.py

全程跑在临时库里，不碰 archive/roster.sqlite3。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dashboard import challenges, demo_roster, game_theory, store  # noqa: E402
from dashboard.gameplay import PlayerMatchRunner, draw_opponents  # noqa: E402
from dashboard.profiling import build_profile  # noqa: E402

store.DB_PATH = Path(tempfile.gettempdir()) / "demo_check.sqlite3"
if store.DB_PATH.exists():
    store.DB_PATH.unlink()

failures = []


def check(label, ok, detail=""):
    print(("  ok  " if ok else " FAIL ") + label + ("" if ok else " :: " + str(detail)[:260]))
    if not ok:
        failures.append(label)


first = demo_roster.build()
second = demo_roster.build()
check("同一 seed 两次跑出同一批决策",
      [r["actions"] for r in first] == [r["actions"] for r in second],
      len(first))
check("换 seed 换一批人",
      [r["actions"] for r in demo_roster.build(seed=99)] != [r["actions"] for r in first])
check("份数够讲一个班", len(first) >= 40, len(first))
check("两个班都有", {r["class_code"] for r in first} == set(demo_roster.CLASSES),
      {r["class_code"] for r in first})

written = demo_roster.load()
runs = store.list_runs()
check("写入份数与 build 一致", written == len(runs) == len(first), (written, len(runs)))
check("全部标成模拟", all(run["demo"] for run in runs),
      [run["join_code"] for run in runs if not run["demo"]][:4])
check("加入码互不重复", len({run["join_code"] for run in runs}) == len(runs))
check("没有一份带姓名类字段",
      set(runs[0]) <= {"join_code", "class_code", "challenge_id", "created_at",
                       "updated_at", "engine_version", "count", "turns", "seed",
                       "actions", "predictions", "tutorial_done", "status", "demo"},
      sorted(runs[0]))

# 重放：决策串必须能被题面重新算出分数，且不报错。
finished = [run for run in runs if run["status"] == "finished"]
check("多数已打完", len(finished) > len(runs) * 0.7, (len(finished), len(runs)))
spread = {}
for task_id in ("PR1EC", "PCPET", "PRNDM", "PBITE"):
    challenge = challenges.preset(task_id)
    group = [run for run in finished if run["challenge_id"] == task_id]
    if not group:
        continue
    board = challenges.ranking(challenge, group)
    scores = [row["score"] for row in board["rows"]]
    spread[task_id] = (len(scores), min(scores), max(scores))
    check("挑战 {} 榜能算且拉得开".format(task_id),
          len(scores) == len(group) and max(scores) > min(scores), spread[task_id])
    check("挑战 {} 参照线在场".format(task_id), bool(board["baselines"]))

# 每份决策串的长度必须和题面对得上，否则重放时会静默补 C。
for run in runs:
    if run["challenge_id"]:
        challenge = challenges.preset(run["challenge_id"])
        want = len(challenge["codes"])
        check("题面 {} 局数对得上 {}".format(run["challenge_id"], run["join_code"]),
              len(run["actions"]) == want, (len(run["actions"]), want))
        break
bad = [
    run["join_code"] for run in runs
    for part in run["actions"] if len(part) > run["turns"] or not part
]
check("没有超长或空的决策串", not bad, bad[:4])

# 猜测栏：形状与 actions 位置对齐。
misaligned = [
    run["join_code"] for run in runs
    if run["predictions"] and any(
        len(guess) != len(played)
        for guess, played in zip(run["predictions"], run["actions"]))
]
check("猜测串与决策串等长", not misaligned, misaligned[:4])
guessed = sum(
    1 for run in runs for part in run["predictions"] for mark in part if mark in "CD")
check("确实有一批猜测记录", guessed > 200, guessed)

# 恢复到报告页：一份模拟加入码要能重放出对局，并算出九项维度与六条读数。
sample = finished[0]
if sample["challenge_id"]:
    codes = challenges.preset(sample["challenge_id"])["codes"]
else:
    codes = draw_opponents(sample["count"], sample["seed"])
restored = []
for index, code in enumerate(codes[:len(sample["actions"])]):
    runner = PlayerMatchRunner(index, code, sample["turns"],
                               sample["seed"] + 1 + index)
    played = sample["actions"][index]
    guessed = sample["predictions"][index] if index < len(sample["predictions"]) else ""
    for offset, action in enumerate(played):
        mark = guessed[offset] if offset < len(guessed) else "-"
        runner.set_prediction(None if mark not in ("C", "D") else mark)
        runner.play(action)
    restored.append(runner.finish())
profile = build_profile(restored)
check("模拟提交能重放出九项维度", len(profile["dimensions"]) == 9,
      len(profile["dimensions"]))
check("博弈论读数六条齐全", len(game_theory.readings(profile["matches"])) == 6,
      len(game_theory.readings(profile["matches"])))
guess_marks = sum(1 for part in sample["predictions"] for mark in part if mark in "CD")
check("这份样例的猜测记录与读数同源",
      guess_marks == sum(len([d for d in m.decisions if d.prediction in ("C", "D")])
                         for m in profile["matches"]),
      (guess_marks, len(sample["predictions"])))

# CSV：带 demo 列，且往返后标记不丢。
dump = store.export_csv()
header = dump.decode("utf-8-sig").splitlines()[0]
check("导出 CSV 有 demo 列", "demo" in header, header)
store.clear_demo_runs()
check("清除后库里为空", store.list_runs() == [], len(store.list_runs()))
back = store.import_csv(dump)
check("CSV 往返恢复", back == len(first) and len(store.list_runs()) == len(first)
      and all(r["demo"] for r in store.list_runs()),
      (back, len(store.list_runs()), [r["demo"] for r in store.list_runs()][:4]))

# 真实行不受影响：demo=0 的一份提交在 --clear 之后还在。
store.create_run("REALTEST", class_code="C1", opponent_count=4, turns=8, seed=5,
                 engine_version="test", tutorial_done=True)
store.save_progress("REALTEST", actions=["CCCCCCCC"] * 4, tutorial_done=True,
                    status="finished")
kept = demo_roster.clear()
survivors = [run["join_code"] for run in store.list_runs()]
check("清除只删模拟行", kept == len(first) and survivors == ["REALTEST"],
      (kept, survivors[:4]))
check("真实行的 demo 是 0", store.load_run("REALTEST")["demo"] is False)
check("重放对得上：全合作对全局分", challenges.replay_total(
    ["S0"] * 4, 8, 5, ["CCCCCCCC"] * 4)[0] == 96.0)

# --- 布置与「刷新一次收一批」 ------------------------------------------------
#
# 这一段换成全新的库：布置表记的是「哪道题发给哪个班、虚拟上交到第几批」，批次号一旦
# 被上面那些行污染，就再也验不出「交完之后不会重复交」这一条了。
TEMP = store.DB_PATH.parent


def fresh(name):
    path = TEMP / name
    if path.exists():
        path.unlink()
    store.DB_PATH = path
    return path


challenge = challenges.preset("PBITE")
klass = "DEMO-C"
# 布置表、名单行里的挑战码都是规范化以后的形状（去掉连字符），拿题面自己那个
# 「P-BITE」去比会一路对不上，而两边看起来都完全正常。
task = challenges.preset_id(challenge)
first_db = fresh("assign_check.sqlite3")
item = store.assign_challenge(task, klass, note="第三课", demo_fill=True)
check("布置写进独立一张表", item["challenge_id"] == task
      and item["demo_round"] == 0 and item["demo_fill"], item)
check("布置这一步不写任何提交", store.list_runs() == [], store.list_runs())
store.assign_challenge(task, klass, note="改了备注", demo_fill=True)
again = store.list_assignments(klass)[0]
check("改布置不会把批次号退回 0",
      again["demo_round"] == 0 and again["note"] == "改了备注" and again["demo_fill"],
      again)
try:
    store.assign_challenge(task, "   ")
    check("没有班级码的布置被拒绝", False, "居然存进去了")
except ValueError as error:
    check("没有班级码的布置被拒绝", "班级码" in str(error), error)

# 同一道题发给两个班：两条布置各自独立，榜仍然按同一套对手算——这是「可比」的前提。
store.assign_challenge(task, "DEMO-D", demo_fill=True)
check("一道题可以布置给好几个班",
      {(a["challenge_id"], a["class_code"]) for a in store.list_assignments()} ==
      {(task, klass), (task, "DEMO-D")}, store.list_assignments())

# 可复现：同一个 (挑战, 班, 批次) 在两份库里跑出同一批人、同一串决策。单独两份库，
# 免得这里的三轮污染上面那条「一批一批正好交齐一个班」。
sizes_repro = []
for name in ("repro_a.sqlite3", "repro_b.sqlite3"):
    fresh(name)
    store.assign_challenge(task, klass, demo_fill=True)
    batched = []
    for index in (1, 2, 3):
        batched.append(demo_roster.submit_batch(challenge, klass, index))
        sizes_repro.append(sorted(
            (r["join_code"], r["actions"]) for r in store.list_runs()))
check("刷新收上来的是同一批虚拟学生（换一个库不换人）",
      sizes_repro[0] == sizes_repro[3] and sizes_repro[1] == sizes_repro[4]
      and sizes_repro[2] == sizes_repro[5],
      [len(x) for x in sizes_repro])
check("批次之间不重交：第 2 批是名单里另外几个人",
      len(sizes_repro[5]) == demo_roster.BATCH * 3
      and len({c for c, _ in sizes_repro[5]}) == demo_roster.BATCH * 3,
      len(sizes_repro[5]))
store.DB_PATH = first_db

# 交完之后不再有：一批一批推进到整班交齐，再多点几次刷新就是 0 份。
sizes = []
for _ in range(demo_roster.MAX_ROUNDS + 2):
    index = store.advance_assignment(task, klass)
    sizes.append(demo_roster.submit_batch(challenge, klass, index))
runs = store.list_runs()
check("一批一批正好交齐一个班",
      sizes[0] == demo_roster.BATCH and sum(sizes) == demo_roster.PER_CLASS
      and sizes[-1] == 0, sizes)
check("整班一人一份，加入码不重复",
      len(runs) == demo_roster.PER_CLASS
      and len({r["join_code"] for r in runs}) == len(runs),
      (len(runs), len({r["join_code"] for r in runs})))
check("虚拟上交全部带模拟标记", all(run["demo"] for run in runs),
      [r["join_code"] for r in runs if not r["demo"]][:4])
check("虚拟上交挂在被布置的那道题和那个班上",
      {r["challenge_id"] for r in runs} == {task}
      and {r["class_code"] for r in runs} == {klass},
      {(r["challenge_id"], r["class_code"]) for r in runs})
check("题面参数按挑战走", all(
    r["count"] == len(challenge["codes"]) and r["turns"] == challenge["turns"]
    and r["seed"] == challenge["seed"] for r in runs))
check("决策串长度都不超轮数", all(
    0 < len(part) <= challenge["turns"] for r in runs for part in r["actions"]),
    [len(p) for r in runs for p in r["actions"]][:8])

# 榜：进行中的必须被跳过，而不是按半局算成分数。
# 老师点开的那一份：逐局重放之和必须等于榜上的总分（两边是同一条路径，不是两份算法）。
def replay_all(task_row, row):
    """按题面把一份提交重放成一串 ``Match``，与 ``app._replay_matches`` 同一条路径。"""
    out = []
    for index, code in enumerate(task_row["codes"]):
        runner = PlayerMatchRunner(
            index, code, task_row["turns"], task_row["seed"] + 1 + index)
        given = row["actions"][index] if index < len(row["actions"]) else ""
        marks = row["predictions"][index] if index < len(row["predictions"]) else ""
        for step, action in enumerate(given):
            mark = marks[step] if step < len(marks) else "-"
            runner.set_prediction(
                None if mark not in ("C", "D") else mark)
            runner.play(action)
        if runner.finished:
            out.append(runner.finish())
    return out


finished = [r for r in runs if r["status"] == "finished"]
board = challenges.ranking(challenge, runs)
check("虚拟上交打完的那些都进了榜", len(board["rows"]) == len(finished) > 0,
      (len(board["rows"]), len(finished), len(runs)))

# 一个班总有几分停在半路上。这一批没抽到的话就现场造一份：它不能进榜，但老师点开
# 它得看得见「停在哪一轮」——那正是逐轮详情要回答的问题。
store.create_run("PARTIAL01", class_code=klass, opponent_count=len(challenge["codes"]),
                 turns=challenge["turns"], seed=challenge["seed"],
                 engine_version="test", tutorial_done=True, challenge_id=task, demo=True)
half = list(finished[0]["actions"])
half[-1] = half[-1][: max(1, len(half[-1]) // 2)]
store.save_progress("PARTIAL01", actions=half, tutorial_done=True, status="playing")
partial_row = store.load_run("PARTIAL01")
board2 = challenges.ranking(challenge, store.list_runs())
check("进行中的那份不进榜",
      len(board2["rows"]) == len(finished)
      and "PARTIAL01" not in {row["join_code"] for row in board2["rows"]},
      (len(board2["rows"]), len(finished)))
check("半局那份重放得出停在第几局",
      len(replay_all(challenge, partial_row)) == len(challenge["codes"]) - 1,
      len(replay_all(challenge, partial_row)))
mismatch = []
for row in board["rows"][:5]:
    replayed = replay_all(challenge, store.load_run(row["join_code"]))
    if abs(sum(m.player_score for m in replayed) - row["score"]) > 1e-6:
        mismatch.append((row["join_code"], row["score"],
                         sum(m.player_score for m in replayed)))
check("老师点开的逐局之和就是榜上那个总分", not mismatch, mismatch)
readings = game_theory.readings(replay_all(challenge, store.load_run(
    board["rows"][0]["join_code"])))
check("读数在同一份虚拟上交上算得出六条", len(readings) == 6, len(readings))
check("虚拟那份确实留下了猜测记录", sum(
    1 for r in runs for part in r["predictions"] for mark in part if mark in "CD") > 0)

# 布置表 CSV：批次号得跟着走，否则重新部署以后会把同一批虚拟学生再交一遍。
dump = store.export_assignments_csv()
check("布置表 CSV 带 BOM 与批次号",
      dump.startswith(b"\xef\xbb\xbf") and "demo_round" in dump.decode("utf-8-sig"),
      dump[:70])
round_before = {a["class_code"]: a["demo_round"] for a in store.list_assignments()}
fresh("assign_check3.sqlite3")
check("布置表 CSV 恢复条数", store.import_assignments_csv(dump) == 2)
back = {a["class_code"]: a for a in store.list_assignments()}
check("恢复回来的批次号不变",
      all(back[k]["demo_round"] == v for k, v in round_before.items())
      and all(a["demo_fill"] for a in back.values()), (back, round_before))
next_round = store.advance_assignment(task, klass)
check("恢复以后接着下一批交，不重交已交的",
      next_round == round_before[klass] + 1
      and demo_roster.submit_batch(
          challenges.preset("PBITE"), klass, next_round) == 0,
      (next_round, round_before[klass]))
try:
    store.import_assignments_csv(b"a,b\n1,2\n")
    check("不像本站布置表的 CSV 会被拒绝", False, "居然收了")
except ValueError as error:
    check("不像本站布置表的 CSV 会被拒绝", "challenge_id" in str(error), error)

print("\n%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)
