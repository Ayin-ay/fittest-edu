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

print("\n%d failure(s)" % len(failures))
sys.exit(1 if failures else 0)
