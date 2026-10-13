"""Graphical 10-round manual test for randomly generated strategy codes."""

from __future__ import annotations

import random
import tkinter as tk
from tkinter import messagebox, scrolledtext

from .strategy_engine import StrategyState, random_strategy


TOTAL_TURNS = 10


class StrategyTestApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("策略规则交互测试")
        self.root.geometry("760x680")
        self.root.minsize(640, 560)

        self.strategy = random_strategy(random.Random())
        self.state = StrategyState(self.strategy, TOTAL_TURNS)
        self.player_history: list[str] = []
        self.records: list[dict[str, object]] = []
        self.current_turn = 1

        self._build_widgets()
        self._show_strategy()

    def _build_widgets(self) -> None:
        header = tk.Frame(self.root, padx=12, pady=10)
        header.pack(fill=tk.X)

        tk.Label(
            header,
            text="随机策略代码",
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(anchor=tk.W)
        self.code_label = tk.Label(
            header,
            text="",
            font=("Consolas", 14, "bold"),
            fg="#1f4e79",
        )
        self.code_label.pack(anchor=tk.W, pady=(3, 8))

        tk.Label(
            header,
            text="策略含义",
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(anchor=tk.W)
        self.explanation = tk.Label(
            header,
            text="",
            justify=tk.LEFT,
            anchor=tk.W,
            wraplength=710,
        )
        self.explanation.pack(fill=tk.X)

        self.status_label = tk.Label(
            self.root,
            text="",
            font=("Microsoft YaHei UI", 12, "bold"),
            pady=8,
        )
        self.status_label.pack()

        self.result_label = tk.Label(
            self.root,
            text="请点击按钮选择你的行动",
            font=("Microsoft YaHei UI", 11),
            pady=5,
        )
        self.result_label.pack()

        buttons = tk.Frame(self.root, pady=8)
        buttons.pack()
        self.cooperate_button = tk.Button(
            buttons,
            text="合作（C）",
            width=15,
            height=2,
            command=lambda: self._play_turn("C"),
        )
        self.cooperate_button.grid(row=0, column=0, padx=8)
        self.defect_button = tk.Button(
            buttons,
            text="背叛（D）",
            width=15,
            height=2,
            command=lambda: self._play_turn("D"),
        )
        self.defect_button.grid(row=0, column=1, padx=8)

        tk.Label(
            self.root,
            text="对局记录",
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(anchor=tk.W, padx=12, pady=(8, 2))
        self.record_text = scrolledtext.ScrolledText(
            self.root,
            height=15,
            state=tk.DISABLED,
            font=("Consolas", 10),
        )
        self.record_text.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 10))

    def _show_strategy(self) -> None:
        self.code_label.config(text=self.strategy.code)
        self.explanation.config(text=self.strategy.explain())
        self._update_status()

    def _update_status(self) -> None:
        if self.current_turn <= TOTAL_TURNS:
            self.status_label.config(
                text=f"第 {self.current_turn}/{TOTAL_TURNS} 回合"
            )
        else:
            self.status_label.config(text="对局结束")

    def _play_turn(self, player_action: str) -> None:
        if self.current_turn > TOTAL_TURNS:
            return

        strategy_action = self.state.decide(self.player_history)
        self.player_history.append(player_action)
        record = {
            "回合": self.current_turn,
            "策略行动": strategy_action,
            "玩家行动": player_action,
        }
        self.records.append(record)
        self._append_record(
            f"第{self.current_turn}回合 | "
            f"策略={strategy_action} | 玩家={player_action}\n"
        )
        self.result_label.config(
            text=f"本回合：策略 {strategy_action}，你的行动 {player_action}"
        )

        self.current_turn += 1
        self._update_status()
        if self.current_turn > TOTAL_TURNS:
            self.cooperate_button.config(state=tk.DISABLED)
            self.defect_button.config(state=tk.DISABLED)
            self._ask_consistency()

    def _ask_consistency(self) -> None:
        answer = messagebox.askyesno(
            "规则核查",
            "策略代码与实际表现是否相符？\n\n"
            "选择“否”将显示策略代码、解释和完整对局记录。",
        )
        if answer:
            self.result_label.config(text="已标记为：策略表现相符")
            return

        self.result_label.config(text="已标记为：策略表现不相符")
        self._append_record("\n[规则核查反馈]\n")
        self._append_record(f"策略代码：{self.strategy.code}\n")
        self._append_record("策略解释：\n")
        self._append_record(f"{self.strategy.explain()}\n")
        self._append_record("完整记录：\n")
        for record in self.records:
            self._append_record(f"{record}\n")
        messagebox.showinfo(
            "已记录不一致",
            "完整策略代码和对局记录已显示在窗口下方。",
        )

    def _append_record(self, text: str) -> None:
        self.record_text.config(state=tk.NORMAL)
        self.record_text.insert(tk.END, text)
        self.record_text.see(tk.END)
        self.record_text.config(state=tk.DISABLED)


def main() -> None:
    root = tk.Tk()
    StrategyTestApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
