"""持久化回环自检：写入名单库 → 读回 → 用真引擎重放，逐项比对。

用法：
    ../.venv/Scripts/python.exe -X utf8 tools/store_roundtrip.py

用临时库而不是 archive/roster.sqlite3，所以这条命令不会碰真实名单。

它验的是整个 5.1 方案唯一依赖的性质：**库里只存种子和玩家自己的决策，其余一切
重算**。如果这个性质不成立，学生下周凭加入码回来的就不是他上周打的那一局，而
界面上一切看起来都完全正常。
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dashboard import store  # noqa: E402
from dashboard.gameplay import PlayerMatchRunner, draw_opponents  # noqa: E402
from dashboard.profiling import build_profile  # noqa: E402

COUNT, TURNS, SEED = 4, 6, 20261011

# 临时库：这条脚本必须能在老师打完一天之后照常运行，而不把测试数据混进名单。
store.DB_PATH = Path(tempfile.mkdtemp()) / "roundtrip.sqlite3"


def replay(acts):
    """与 ``app._replay_run`` 同一套重放：喂回种子与决策，重建每一局。"""
    codes = draw_opponents(COUNT, SEED)
    matches, runner, index = [], None, 0
    while index < len(codes):
        live = PlayerMatchRunner(index=index, opponent=codes[index], turns=TURNS,
                                 seed=SEED + 1 + index)
        for action in (acts[index] if index < len(acts) else ""):
            if live.finished:
                break
            live.play(action)
        if live.finished:
            matches.append(live.finish())
            index += 1
        else:
            runner = live
            break
    return codes, matches, runner


def decisions(runner):
    return "".join(d.action for d in runner.decisions)


# --- 1. 一整局：每走一步都写一次库 -------------------------------------------
code = store.new_join_code()
store.create_run(code, class_code="自检班", opponent_count=COUNT, turns=TURNS,
                 seed=SEED, engine_version="1.2.0", tutorial_done=True)

live = [PlayerMatchRunner(index=i, opponent=c, turns=TURNS, seed=SEED + 1 + i)
        for i, c in enumerate(draw_opponents(COUNT, SEED))]
acts, played, alternate = [""] * COUNT, 0, "CD"
for i in range(COUNT):
    while not live[i].finished:
        live[i].play(alternate[played % 2])
        played += 1
        acts[i] = decisions(live[i])
        store.save_progress(code, actions=[a for a in acts if a], tutorial_done=True)
direct = [live[i].finish() for i in range(COUNT)]
store.save_progress(code, actions=acts, tutorial_done=True, status="finished")

saved = store.load_run(code)
assert saved["status"] == "finished"
assert saved["class_code"] == "自检班"
assert saved["actions"] == acts
codes2, matches2, runner2 = replay(saved["actions"])

assert runner2 is None, "打完的一局不该重放成进行中"
assert codes2 == [m.opponent for m in direct]
assert [m.opponent_actions for m in matches2] == [m.opponent_actions for m in direct]
assert [(m.player_score, m.opponent_score) for m in matches2] == \
       [(m.player_score, m.opponent_score) for m in direct]
assert [d.numbers for d in build_profile(matches2)["dimensions"]] == \
       [d.numbers for d in build_profile(direct)["dimensions"]]
print("打完的一局　　：对手编码、双方比分、九项测量全部逐字重放一致")

# --- 2. 中途离开：两局完整，第三局打了 3 / 6 轮 -------------------------------
code2 = store.new_join_code()
store.create_run(code2, class_code="", opponent_count=COUNT, turns=TURNS,
                 seed=SEED, engine_version="1.2.0")
store.save_progress(code2, actions=["CCCCCC", "CDC"], tutorial_done=True)
loaded = store.load_run(code2)
codes3, matches3, runner3 = replay(loaded["actions"])
assert len(matches3) == 1 and runner3 is not None
assert len(runner3.decisions) == 3
assert [m.opponent_actions for m in matches3] == \
       [m.opponent_actions for m in direct[:1]]
print("打到一半回来：第 1 局比分一致，第 2 局停在第 3 轮，接着打即可")

# --- 3. 手抄码：大小写、空格、连字符都要认 ------------------------------------
assert store.load_run(store.normalize_code(" " + code2.lower() + "-")) is not None
assert store.load_run("QQQQQQQQ") is None
print("手抄的加入码　：大小写 / 空格 / 连字符不影响命中，不存在的码返回 None")

# --- 4. CSV 导出去再进回来：免费版重新部署清空文件后的唯一出路 ----------------
dump = store.export_csv()
assert dump.startswith(b"\xef\xbb\xbf"), "Excel 需要的 UTF-8 BOM"
assert "自检班".encode("utf-8") in dump
fresh = store.DB_PATH
store.DB_PATH = Path(fresh.parent) / "second.sqlite3"
assert store.import_csv(dump) == 2
assert store.load_run(code)["actions"] == acts
assert store.load_run(code)["class_code"] == "自检班"
print("CSV 往返　　　：重新部署后导入，加入码不变，学生照常凭原码回来")

print("OK")
