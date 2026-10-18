"""生成（或清除）演示用的模拟名单：几十份「学生提交」写进本地名单库。

用法（在 ``fittest-edu`` 目录下）：

    ../.venv/Scripts/python.exe -X utf8 tools/seed_demo_roster.py --dry-run
    ../.venv/Scripts/python.exe -X utf8 tools/seed_demo_roster.py
    ../.venv/Scripts/python.exe -X utf8 tools/seed_demo_roster.py --clear
    ../.venv/Scripts/python.exe -X utf8 tools/seed_demo_roster.py --db /tmp/demo.sqlite3

这条命令只往 ``runs`` 表里加 ``demo = 1`` 的行，绝不改 ``demo = 0`` 的真实提交；
``--clear`` 反过来只删 ``demo = 1`` 的那些。两个方向都不是「清空名单」。

和教师端「刷新名单（收作业）」的分工：这里一次把两个班的整批提交灌进去，用来把空看板
填满；布置之后一批一批收上来走的是 ``demo_roster.submit_batch``（每班一批、按批次推进），
用来演示「布置 → 有人交 → 榜变长」这个过程本身。两者写的都是同一套真打出来的行。

为什么要它：教师端那一屏要讲「全班打到哪儿了、榜怎么排、标准策略参照线怎么用」，
而空看板讲不出任何事。这里写出的每一行都是真打的——同一套 :class:`PlayerMatchRunner`、
题面给的同一串对手编码、同一份种子——所以点进任何一个模拟加入码，看到的报告、九项测量
和博弈论读数都是按那份决策重算的，和真实学生走的是同一条代码路径。

为什么它不能被当成成效证据：这些是学生形状的脚本输出，不是课堂。库里的 ``demo`` 标记、
导出 CSV 里的那一列、看板上的那块牌子，三处都在说同一件事。参赛材料里不得据此写
「已在班级试用」或任何用户数。
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dashboard import demo_roster, store  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=demo_roster.SEED,
                        help="换一批人；同一个 seed 两次跑出同一批决策。")
    parser.add_argument("--clear", action="store_true",
                        help="删除全部模拟行（真实提交不动），然后退出。")
    parser.add_argument("--dry-run", action="store_true",
                        help="只算不写，用来先看看会生成什么。")
    parser.add_argument("--db", default="",
                        help="名单库路径。默认用 archive/roster.sqlite3；"
                             "演示前想保住真实名单就指一个临时库。")
    parser.add_argument("--show", type=int, default=6,
                        help="打印多少个加入码，方便现场点进某一份看报告。0 表示不打印。")
    args = parser.parse_args(argv)

    if args.db:
        store.DB_PATH = Path(args.db)
    print("名单库：{}".format(store.DB_PATH))

    if args.clear:
        removed = demo_roster.clear()
        print("已删除 {} 份模拟提交，真实提交未动。剩余总数：{}".format(
            removed, len(store.list_runs())))
        return 0

    if args.dry_run:
        rows = demo_roster.build(seed=args.seed)
        print("将生成 {} 份模拟提交（dry-run，未写入）：".format(len(rows)))
        for line in demo_roster.summary(rows):
            print("  {}　{}　{} 份".format(
                line["班级码"], line["挑战码"], line["份数"]))
        return 0

    already = demo_roster.count()
    if already:
        print("库里已经有 {} 份模拟提交。再跑一次会再写一批；"
              "想先看干净的效果就 --clear。".format(already))
    written = demo_roster.load(seed=args.seed)
    rows = store.list_runs()
    demo_rows = [row for row in rows if row["demo"]]
    print("已写入 {} 份模拟提交。库里现在：模拟 {} 份，真实 {} 份。".format(
        written, len(demo_rows), len(rows) - len(demo_rows)))
    print("班级与题面：")
    for line in demo_roster.summary([
        {"class_code": row["class_code"], "challenge_id": row["challenge_id"]}
        for row in demo_rows
    ]):
        print("  {}　{}　{} 份".format(
            line["班级码"], line["挑战码"], line["份数"]))
    if args.show:
        print("可以先点进去看的加入码（学生端「恢复我的报告」输入即可）：")
        finished = [row for row in demo_rows if row["status"] == "finished"]
        for row in finished[:args.show]:
            print("  {}　{}　挑战 {}".format(
                row["join_code"], row["class_code"], row["challenge_id"] or "自由对局"))
    print("提醒：这些不是课堂数据。看板、导出 CSV 与任何参赛材料都必须保留"
          "「模拟数据，非真实课堂」的标注。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
