import random
import sys
from pathlib import Path
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

import matplotlib.pyplot as plt
import numpy as np

RESULTS_DIR = Path(__file__).resolve().parents[1] / "results"


def configure_console_encoding() -> None:
    """Keep Unicode feedback from crashing on Windows GBK consoles."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


configure_console_encoding()

class Strategy(Enum):
    TFT = 1
    ALLD = 2
    ALLC = 3
    GRUDGER = 4
    CHAOS = 5
    PAVLOV = 6
    FORGIVING_TFT = 7
    TESTER = 8
    MAJORITY = 9
    BACKSTABBER = 10
    HYENA = 11
    PROVOCATEUR = 12
    ALTERNATOR = 13
    TROUBLEMAKER = 14
    FATHER = 15
    GAMBLER = 16
    REVENGE = 17


@dataclass
class Agent:
    id: int
    strategy: Strategy
    score: float = 0.0
    history: List[bool] = None
    total_turns: Optional[int] = None
    _hyena_betrayed: bool = False
    _hyena_triggered: bool = False
    _revenge_remaining: int = 0
    _last_opponent_length: int = 0

    def __post_init__(self) -> None:
        if self.history is None:
            self.history = []

    def decide(self, opponent_history: List[bool]) -> bool:
        if self.strategy == Strategy.TFT:
            return opponent_history[-1] if opponent_history else True
        if self.strategy == Strategy.ALLD:
            return False
        if self.strategy == Strategy.ALLC:
            return True
        if self.strategy == Strategy.GRUDGER:
            return False if False in opponent_history else True
        if self.strategy == Strategy.CHAOS:
            return random.choice([True, False])
        if self.strategy == Strategy.PAVLOV:
            if not opponent_history:
                return True
            last_was_successful = self.history[-1] == opponent_history[-1]
            return self.history[-1] if last_was_successful else not self.history[-1]
        if self.strategy == Strategy.FORGIVING_TFT:
            return len(opponent_history) < 2 or all(opponent_history[-2:])
        if self.strategy == Strategy.TESTER:
            if not opponent_history:
                return False
            if len(opponent_history) == 1:
                return True
            retaliated = not opponent_history[0]
            return opponent_history[-1] if retaliated else False
        if self.strategy == Strategy.MAJORITY:
            return opponent_history.count(True) >= opponent_history.count(False)
        if self.strategy == Strategy.BACKSTABBER:
            if self.total_turns is not None and len(self.history) >= self.total_turns - 2:
                return False
            return opponent_history[-1] if opponent_history else True
        if self.strategy == Strategy.HYENA:
            if (
                self._hyena_betrayed
                and not self._hyena_triggered
                and len(opponent_history) > self._last_opponent_length
            ):
                self._hyena_triggered = not opponent_history[-1]
            self._last_opponent_length = len(opponent_history)
            if self._hyena_triggered:
                return False
            if random.random() < 0.2:
                self._hyena_betrayed = True
                return False
            return opponent_history[-1] if opponent_history else True
        if self.strategy == Strategy.PROVOCATEUR:
            return False if not self.history else (
                opponent_history[-1] if opponent_history else True
            )
        if self.strategy == Strategy.ALTERNATOR:
            return len(self.history) % 2 == 0
        if self.strategy == Strategy.TROUBLEMAKER:
            return True if not opponent_history else not opponent_history[-1]
        if self.strategy == Strategy.FATHER:
            return False if opponent_history.count(False) >= 2 else True
        if self.strategy == Strategy.GAMBLER:
            roll = random.random()
            if roll < 0.4:
                return opponent_history[-1] if opponent_history else True
            if roll < 0.7:
                return False
            return True
        if self.strategy == Strategy.REVENGE:
            if (
                len(opponent_history) > self._last_opponent_length
                and opponent_history[-1] is False
            ):
                self._revenge_remaining = 2
            self._last_opponent_length = len(opponent_history)
            if self._revenge_remaining:
                self._revenge_remaining -= 1
                return False
            return opponent_history[-1] if opponent_history else True
        raise ValueError(f"Unsupported strategy: {self.strategy}")

MATCHES_PER_PAIR = 10
TURNS_PER_MATCH = 20
PLAYER_TURNS_DEFAULT = 5


# ==================== 原有函数（保持不变） ====================
def play_match(
    strategy_a: Strategy,
    strategy_b: Strategy,
    turns: int,
) -> float:
    """Play one fresh match and return the row strategy's average score."""
    agent_a = Agent(id=0, strategy=strategy_a, total_turns=turns)
    agent_b = Agent(id=1, strategy=strategy_b, total_turns=turns)

    for _ in range(turns):
        decision_a = agent_a.decide(agent_b.history)
        decision_b = agent_b.decide(agent_a.history)
        agent_a.history.append(decision_a)
        agent_b.history.append(decision_b)

        # 收益矩阵：合作各得 2，双方背叛各得 0，单方背叛得 3/-1。
        if decision_a and decision_b:
            agent_a.score += 2
            agent_b.score += 2
        elif decision_a and not decision_b:
            agent_a.score -= 1
            agent_b.score += 3
        elif not decision_a and decision_b:
            agent_a.score += 3
            agent_b.score -= 1
        # 双方背叛不加分（保持0）

    return agent_a.score / turns


def build_matchup_table(
    matches_per_pair: int = MATCHES_PER_PAIR,
    turns_per_match: int = TURNS_PER_MATCH,
) -> Dict[Strategy, Dict[Strategy, float]]:
    """Return the row strategy's average score against each column strategy."""
    table: Dict[Strategy, Dict[Strategy, float]] = {}
    strategies: List[Strategy] = list(Strategy)

    for strategy_a in strategies:
        table[strategy_a] = {}
        for strategy_b in strategies:
            total_score = 0.0
            for _ in range(matches_per_pair):
                total_score += play_match(
                    strategy_a,
                    strategy_b,
                    turns_per_match,
                )
            table[strategy_a][strategy_b] = total_score / matches_per_pair

    return table


def print_matchup_table(
    table: Dict[Strategy, Dict[Strategy, float]],
    human_scores: Optional[Dict[str, float]] = None,
) -> None:
    """
    Print the row strategy's average score against each column strategy.
    If human_scores is provided, add a "Human" row at the bottom.
    """
    strategies = list(Strategy)
    headers = ["Row \\ Column"] + [strategy.name for strategy in strategies]
    widths = [max(len(header), 12) for header in headers]

    # 如果有人类数据，额外加一行
    if human_scores is not None:
        headers.append("Human")
        widths.append(12)

    # 计算列宽（先对策略列）
    for strategy_a in strategies:
        for strategy_b in strategies:
            cell = f"{table[strategy_a][strategy_b]:.2f}"
            index = strategies.index(strategy_b) + 1
            widths[index] = max(widths[index], len(cell))

    # 如果有人类数据，更新人类列宽
    if human_scores is not None:
        for strat in strategies:
            cell = f"{human_scores.get(strat.name, 0.0):.2f}"
            widths[-1] = max(widths[-1], len(cell))

    print("Average score per turn (row player against column opponent)")
    print(" | ".join(header.ljust(width) for header, width in zip(headers, widths)))
    print("-+-".join("-" * width for width in widths))

    # 打印 AI 行
    for strategy_a in strategies:
        cells = [strategy_a.name.ljust(widths[0])]
        for index, strategy_b in enumerate(strategies, start=1):
            cells.append(f"{table[strategy_a][strategy_b]:.2f}".ljust(widths[index]))
        print(" | ".join(cells))

    # 打印人类行（如果有）
    if human_scores is not None:
        cells = ["Human".ljust(widths[0])]
        for index, strategy_b in enumerate(strategies, start=1):
            cells.append(f"{human_scores.get(strategy_b.name, 0.0):.2f}".ljust(widths[index]))
        print(" | ".join(cells))


def plot_matchup_table(
    table: Dict[Strategy, Dict[Strategy, float]],
    human_scores: Optional[Dict[str, float]] = None,
    save_path: str = str(RESULTS_DIR / "strategy_matchup_heatmap.png"),
) -> None:
    """
    Plot the row player's average score against each column opponent.
    If human_scores is provided, add an extra "Human" row.
    """
    strategies = list(Strategy)
    human_differences: Optional[np.ndarray] = None
    # 基础矩阵（AI vs AI）
    values = np.array(
        [
            [table[strategy_a][strategy_b] for strategy_b in strategies]
            for strategy_a in strategies
        ]
    )

    # 如果有人类数据，保留实际得分，并把与该列 AI 平均分的差值放入标注
    if human_scores is not None:
        human_row = np.array([human_scores.get(s.name, 0.0) for s in strategies]).reshape(1, -1)
        ai_average_row = np.array(
            [np.mean([table[row][column] for row in strategies]) for column in strategies]
        )
        human_differences = human_row[0] - ai_average_row
        values = np.vstack([values, human_row])
        row_labels = [s.name for s in strategies] + ["Human"]
    else:
        row_labels = [s.name for s in strategies]

    col_labels = [s.name for s in strategies]

    figure_width = max(10, len(strategies) * 1.25)
    figure, axis = plt.subplots(figsize=(figure_width, figure_width * 0.8))
    image = axis.imshow(values, cmap="RdYlGn", aspect="auto", vmin=-3, vmax=3)
    figure.colorbar(image, ax=axis, label="Average score per turn")

    axis.set_xticks(range(len(strategies)))
    axis.set_yticks(range(len(row_labels)))
    axis.set_xticklabels(col_labels, rotation=45, ha="right")
    axis.set_yticklabels(row_labels)
    axis.set_xlabel("Opponent strategy")
    axis.set_ylabel("Player strategy")
    axis.set_title("Strategy Matchup Average Scores and Human-AI Differences")

    human_row_index = len(strategies)
    for row in range(values.shape[0]):
        for column in range(values.shape[1]):
            cell_value = values[row, column]
            # Near-zero cells are pale yellow in RdYlGn, so use black text.
            text_color = "black" if abs(cell_value) < 0.5 else (
                "white" if cell_value < 0.8 else "black"
            )
            is_human_cell = row == human_row_index and human_differences is not None
            if is_human_cell:
                difference = human_differences[column]
                cell_text = f"{cell_value:.2f}\n({difference:+.2f})"
            else:
                cell_text = f"{cell_value:.2f}"
            axis.text(
                column,
                row,
                cell_text,
                ha="center",
                va="center",
                color=text_color,
                fontsize=7 if is_human_cell else 9,
            )

    figure.tight_layout()
    if save_path:
        figure.savefig(save_path, dpi=150, bbox_inches="tight")
    # Do not block Tkinter's event loop while displaying the result window.
    plt.show(block=False)
    plt.pause(0.1)


# ==================== 新增人类交互函数 ====================
def play_human_vs_strategy(strategy_b: Strategy, turns: int) -> float:
    """
    Let a human play against a given AI strategy for a fixed number of turns.
    Returns the human's average score per turn.
    """
    human_history = []          # 人类自己的历史（用于可能的策略？但人类是自由的）
    opponent_history = []       # 对手的历史（提供给人类参考）
    human_score = 0.0
    temp_agent = Agent(id=999, strategy=strategy_b, total_turns=turns)

    print(f"\n--- You are playing against {strategy_b.name} for {turns} rounds ---")
    print("Enter 'C' for cooperate, 'D' for defect, or 'q' to quit early.")

    for turn in range(1, turns + 1):
        # 对手先决策（使用其内置逻辑）
        temp_agent.history = opponent_history[:]
        decision_b = temp_agent.decide(human_history)

        # 显示当前轮次信息
        print(f"\nRound {turn}/{turns}")
        print(f"Opponent's move this round: {'Cooperate' if decision_b else 'Defect'}")
        print("Your previous moves:", " ".join(["C" if m else "D" for m in human_history]))
        print("Opponent's previous moves:", " ".join(["C" if m else "D" for m in opponent_history]))

        # 获取人类输入
        while True:
            user_input = input("Your move (C/D/q): ").strip().upper()
            if user_input == 'Q':
                print("Match terminated early.")
                return human_score / (turn - 1) if turn > 1 else 0.0
            if user_input in ('C', 'D'):
                decision_a = (user_input == 'C')
                break
            print("Invalid input. Please enter C, D, or q.")

        # 记录历史
        human_history.append(decision_a)
        opponent_history.append(decision_b)

        # 计算得分
        if decision_a and decision_b:
            human_score += 2
        elif decision_a and not decision_b:
            human_score -= 1
        elif not decision_a and decision_b:
            human_score += 3
        # 双方背叛不加分

        # 显示本轮得分
        print(f"Score this round: {human_score} (cumulative)")

    avg_score = human_score / turns
    print(f"\nMatch finished. Your average score per turn: {avg_score:.2f}")
    return avg_score


def build_human_matchup_table(
    strategies: List[Strategy],
    matches_per_pair: int = 1,
    turns_per_match: int = PLAYER_TURNS_DEFAULT,
) -> Dict[str, float]:
    """
    Let the human play against each strategy for matches_per_pair matches,
    return a dict mapping strategy names to average scores.
    """
    human_scores = {}
    for strategy in strategies:
        print(f"\n{'='*50}")
        print(f"Now playing against {strategy.name}")
        total = 0.0
        for match_idx in range(1, matches_per_pair + 1):
            print(f"\n--- Match {match_idx} of {matches_per_pair} ---")
            avg = play_human_vs_strategy(strategy, turns_per_match)
            total += avg
        human_scores[strategy.name] = total / matches_per_pair
        print(f"Average score against {strategy.name} over {matches_per_pair} matches: {human_scores[strategy.name]:.2f}")
    return human_scores


def give_feedback(
    table: Dict[Strategy, Dict[Strategy, float]],
    human_scores: Dict[str, float],
    human_histories: Dict[str, List[bool]],
    opponent_histories: Dict[str, List[bool]],
    score_samples: Optional[Dict[str, List[float]]] = None,
) -> None:
    """Print the specified final assessment for a completed human game."""
    strategies = list(Strategy)
    if score_samples:
        all_scores = [
            score
            for scores in score_samples.values()
            for score in scores
        ]
    else:
        all_scores = list(human_scores.values())
    total_average = sum(all_scores) / len(all_scores)
    levels = [
        (
            2.5,
            "🏆 超凡策略家",
            "你在博弈中近乎完美，懂得在合作与背叛之间精准切换，超越了绝大多数AI。继续保持这种敏锐的直觉！",
        ),
        (
            2.0,
            "🌟 出色的决策者",
            "你善于利用对手的弱点，同时避免被剥削，表现非常稳健。可以尝试挑战更高难度的策略组合。",
        ),
        (
            1.5,
            "👍 不错的玩家",
            "你有良好的博弈直觉，但偶尔会被对手利用。建议多观察对手的模式，适当增加报复性策略。",
        ),
        (
            1.0,
            "📊 一般的表现",
            "你有时会陷入不利局面，需要更谨慎。尝试采用‘以牙还牙’策略，先合作再根据对手反应调整。",
        ),
        (
            0.0,
            "📉 需要提升",
            "你容易被背叛者伤害，尝试不要总是合作，学会在适当时候进行报复。",
        ),
        (
            float("-inf"),
            "❌ 糟糕的表现",
            "你可能过于信任对手，导致被严重剥削。建议从简单的TFT策略开始练习，逐步提高。",
        ),
    ]
    level, advice = next(
        (level, advice) for threshold, level, advice in levels if total_average >= threshold
    )
    ai_average = np.mean(
        [table[row][column] for row in strategies for column in strategies]
    )
    ai_strategy_averages = {
        strategy.name: float(np.mean([table[strategy][opponent] for opponent in strategies]))
        for strategy in strategies
    }
    champion_name = max(ai_strategy_averages, key=ai_strategy_averages.get)
    champion_average = ai_strategy_averages[champion_name]
    champion_difference = total_average - champion_average

    print("=" * 60)
    print("🎮 最终决策水平评估")
    print("=" * 60)
    print(f"您的总平均分（所有AI对手）：{total_average:.2f}")
    print(f"评级：{level}")
    print(f"建议：{advice}")

    difference = total_average - ai_average
    if difference > 0.3:
        print(
            f"✅ 您的得分比所有AI的平均分（{ai_average:.2f}）高出 "
            f"{difference:.2f} 分，表明您的决策能力优于一般AI策略。"
        )
    elif difference < -0.3:
        print(
            f"⚠️ 您的得分比所有AI的平均分（{ai_average:.2f}）低 "
            f"{abs(difference):.2f} 分，AI策略整体上更强。可以考虑参考AI的决策模式。"
        )
    else:
        print(
            f"🔁 您的得分与AI平均分（{ai_average:.2f}）相当，说明您的决策水平与标准AI策略持平。"
        )
    print(
        f"🏆 冠军AI：{champion_name}（平均分 {champion_average:.2f}），"
        f"您的得分与冠军AI的差值为 {champion_difference:+.2f} 分。"
    )

    ai_column_averages = {
        opponent.name: float(np.mean([table[row][opponent] for row in strategies]))
        for opponent in strategies
    }
    score_differences = {
        name: human_scores[name] - ai_column_averages[name]
        for name in human_scores
    }
    best = max(score_differences, key=score_differences.get)
    worst = min(score_differences, key=score_differences.get)
    print(
        f"\n您表现最佳的对手：{best}（得分 {human_scores[best]:.2f}，"
        f"与AI平均分差值 {score_differences[best]:+.2f}）"
    )
    print(
        f"您表现最差的对手：{worst}（得分 {human_scores[worst]:.2f}，"
        f"与AI平均分差值 {score_differences[worst]:+.2f}）"
    )
    if human_scores[worst] < 1.0 and worst in {"ALLD", "TESTER"}:
        print(
            f"💡 提示：您在与 {worst} 对战时得分较低，这类策略经常在开局背叛。"
            "建议您先观察几轮，然后采取相应报复。"
        )
    elif human_scores[worst] < 1.0 and worst == "ALLC":
        print(
            "💡 提示：您在与 ALLC 对战时得分较低，可能是因为您过度背叛。"
            "ALLC 是永远合作的，您应尽量与其合作以获得双赢。"
        )

    human_vector = np.array([human_scores[strategy.name] for strategy in strategies])
    closest = min(
        strategies,
        key=lambda strategy: np.mean(
            [
                abs(
                    human_vector[index]
                    - table[strategy][opponent]
                )
                for index, opponent in enumerate(strategies)
            ]
        ),
    )
    characteristics = {
        "TFT": "TFT策略以“以牙还牙”闻名，先合作再复制对手上一步，善于平衡报复与宽容。",
        "ALLD": "ALLD策略永远背叛，追求短期收益但会破坏长期合作。",
        "ALLC": "ALLC策略永远合作，促进互惠但容易被背叛者利用。",
        "GRUDGER": "GRUDGER策略先合作，一旦遭遇背叛就永久报复。",
        "CHAOS": "CHAOS策略随机选择合作或背叛，行为难以预测。",
        "PAVLOV": "PAVLOV策略在获益时保持行动，受损时切换行动。",
        "FORGIVING_TFT": "FORGIVING_TFT策略会模仿对手，同时容忍短暂的背叛。",
        "TESTER": "TESTER策略先测试对手，再根据对手是否反击决定后续行为。",
        "MAJORITY": "MAJORITY策略根据对手历史行为的多数情况作出决定。",
        "BACKSTABBER": "背刺者前期模仿TFT，最后两回合突然连续背叛。",
        "HYENA": "鬣狗通常模仿TFT，并偶尔背叛；若对手报复，就转为永远背叛。",
        "PROVOCATEUR": "挑衅者开局背叛，之后模仿对手，主动测试对手的反应。",
        "ALTERNATOR": "交替者严格在合作和背叛之间交替。",
        "TROUBLEMAKER": "捣蛋鬼开局合作，之后总是选择与对手上一轮相反的动作。",
        "FATHER": "圣父在累计被背叛两次前始终合作，之后转为永远背叛。",
        "GAMBLER": "赌徒每轮以40%选择TFT、30%选择ALLD、30%选择ALLC。",
        "REVENGE": "报复狂模仿TFT，但每次遭遇背叛后会连续报复两轮。",
    }
    print(
        f"\n您的决策模式最接近 {closest.name} 策略，因为您的得分分布与其最为相似。"
        f"{characteristics[closest.name]}"
    )

    all_human_moves = [move for history in human_histories.values() for move in history]
    all_opponent_moves = [
        move for history in opponent_histories.values() for move in history
    ]
    total_rounds = len(all_human_moves)
    cooperation_rate = (
        sum(all_human_moves) / total_rounds if total_rounds else 0.0
    )
    retaliation_events = [
        index
        for index in range(1, total_rounds)
        if all_opponent_moves[index - 1] is False
    ]
    retaliation_rate = (
        sum(not all_human_moves[index] for index in retaliation_events)
        / len(retaliation_events)
        if retaliation_events
        else 0.0
    )
    forgiveness_events = [
        index
        for index in range(1, total_rounds)
        if all_opponent_moves[index - 1] is True
    ]
    forgiveness_rate = (
        sum(not all_human_moves[index] for index in forgiveness_events)
        / len(forgiveness_events)
        if forgiveness_events
        else 0.0
    )
    print("\n📊 额外个性评价：")
    print(f"- 您的总体合作率为 {cooperation_rate * 100:.0f}%。")
    if cooperation_rate > 0.8:
        print("  您非常愿意合作，这是一个好习惯，但需警惕被ALLD等策略利用。")
    elif cooperation_rate < 0.2:
        print("  您倾向于背叛，虽然短期内可能获利，但长期会损失合作机会。")
    print(f"- 您的报复倾向为 {retaliation_rate * 100:.0f}%。")
    if retaliation_rate > 0.7:
        print("  您对背叛反应强烈，这能有效威慑对手，但可能陷入互殴循环。")
    elif retaliation_rate < 0.3:
        print("  您对背叛较为宽容，有利于修复关系，但容易被反复剥削。")
    print(f"- 您的宽容度为 {forgiveness_rate * 100:.0f}%。")
    print("=" * 60)


def launch_game_gui() -> None:
    """Launch a Tkinter interface for hidden-opponent games."""
    import tkinter as tk
    from tkinter import messagebox, ttk

    class GameWindow:
        def __init__(self, root: tk.Tk) -> None:
            self.root = root
            self.root.title("The Fittest - Iterated Prisoner's Dilemma")
            self.root.geometry("760x600")
            self.ai_agent = Agent(id=1, strategy=Strategy.TFT)
            self.opponent_order: List[Strategy] = []
            self.opponent_index = 0
            self.human_scores: Dict[str, float] = {}
            self.human_score_samples: Dict[str, List[float]] = {}
            self.human_histories: Dict[str, List[bool]] = {}
            self.opponent_histories: Dict[str, List[bool]] = {}
            self.human_history: List[bool] = []
            self.opponent_history: List[bool] = []
            self.human_score = 0
            self.opponent_score = 0
            self.current_turn = 0
            self.game_started = False

            self.turns_var = tk.IntVar(value=PLAYER_TURNS_DEFAULT)
            self.status_var = tk.StringVar(value="请先设置回合数，然后选择是否开始游戏")
            self.score_var = tk.StringVar()
            self.history_var = tk.StringVar()

            self._build_widgets()
            self._set_action_state("disabled")

        def _build_widgets(self) -> None:
            settings = ttk.LabelFrame(self.root, text="对局设置", padding=10)
            settings.pack(fill="x", padx=12, pady=10)

            ttk.Label(settings, text="每场回合数：").grid(row=0, column=0, sticky="w")
            self.turns_box = ttk.Spinbox(
                settings,
                from_=1,
                to=1000,
                textvariable=self.turns_var,
                width=8,
            )
            self.turns_box.grid(row=0, column=1, padx=(4, 18))
            self.start_button = ttk.Button(
                settings, text="开始游戏", command=self.start_game
            )
            self.start_button.grid(row=0, column=2, padx=4)
            self.skip_button = ttk.Button(
                settings, text="跳过游戏，查看热力图", command=self.skip_game
            )
            self.skip_button.grid(row=0, column=3, padx=4)

            ttk.Label(
                self.root,
                textvariable=self.status_var,
                font=("Segoe UI", 14, "bold"),
            ).pack(pady=(8, 4))
            ttk.Label(self.root, textvariable=self.score_var, font=("Segoe UI", 12)).pack()
            ttk.Label(self.root, textvariable=self.history_var).pack(pady=8)

            actions = ttk.Frame(self.root)
            actions.pack(pady=14)
            self.cooperate_button = ttk.Button(
                actions,
                text="合作 (C)",
                command=lambda: self.play_turn(True),
                width=18,
            )
            self.cooperate_button.grid(row=0, column=0, padx=10)
            self.defect_button = ttk.Button(
                actions,
                text="背叛 (D)",
                command=lambda: self.play_turn(False),
                width=18,
            )
            self.defect_button.grid(row=0, column=1, padx=10)

            self.log = tk.Text(self.root, height=18, width=88, state="disabled")
            self.log.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        def _read_turns(self) -> int:
            try:
                turns = int(self.turns_var.get())
            except (TypeError, ValueError):
                turns = PLAYER_TURNS_DEFAULT
                self.turns_var.set(turns)
            if turns < 1:
                turns = 1
                self.turns_var.set(turns)
            return turns

        def start_game(self) -> None:
            turns = self._read_turns()
            self.game_started = True
            self.opponent_order = list(Strategy)
            self.opponent_order.extend(
                random.choice(list(Strategy)) for _ in range(3)
            )
            random.shuffle(self.opponent_order)
            self.opponent_index = 0
            self.human_scores = {}
            self.human_score_samples = {}
            self.human_histories = {}
            self.opponent_histories = {}
            self.start_button.configure(state="disabled")
            self.skip_button.configure(state="disabled")
            self.turns_box.configure(state="disabled")
            self._start_match()

        def skip_game(self) -> None:
            self.start_button.configure(state="disabled")
            self.skip_button.configure(state="disabled")
            self.turns_box.configure(state="disabled")
            self.status_var.set("已跳过人机对局，正在生成 AI 对战热力图")
            self.root.after(50, self._show_heatmap)

        def _start_match(self) -> None:
            if self.opponent_index >= len(self.opponent_order):
                self._finish_all_matches()
                return

            strategy = self.opponent_order[self.opponent_index]
            self.ai_agent = Agent(
                id=1,
                strategy=strategy,
                total_turns=self._read_turns(),
            )
            self.human_history = []
            self.opponent_history = []
            self.human_score = 0
            self.opponent_score = 0
            self.current_turn = 0
            self._set_action_state("normal")
            self.status_var.set(
                f"第 {self.opponent_index + 1}/{len(self.opponent_order)} 场：请选择你的动作"
            )
            self._update_summary()
            self._write_log(
                f"开始第 {self.opponent_index + 1} 场对局（对手身份隐藏）"
            )

        def _finish_all_matches(self) -> None:
            self._set_action_state("disabled")
            self.status_var.set("全部 AI 对局完成，正在生成你的成绩热力图")
            self._write_log("已完成与全部 AI 策略的对局")
            matchup_table = build_matchup_table()
            give_feedback(
                matchup_table,
                self.human_scores,
                self.human_histories,
                self.opponent_histories,
                self.human_score_samples,
            )
            self.root.after(50, lambda: self._show_heatmap(matchup_table))

        def _show_heatmap(
            self,
            matchup_table: Optional[Dict[Strategy, Dict[Strategy, float]]] = None,
        ) -> None:
            if matchup_table is None:
                matchup_table = build_matchup_table()
            plot_matchup_table(
                matchup_table,
                self.human_scores if self.human_scores else None,
            )

        def _set_action_state(self, state: str) -> None:
            self.cooperate_button.configure(state=state)
            self.defect_button.configure(state=state)

        def play_turn(self, human_move: bool) -> None:
            if not self.game_started or self.current_turn >= self._read_turns():
                return

            # The opponent is selected before the game but its identity is hidden.
            opponent_move = self.ai_agent.decide(self.human_history)
            self.human_history.append(human_move)
            self.opponent_history.append(opponent_move)
            self.ai_agent.history.append(opponent_move)
            self.current_turn += 1

            human_points, opponent_points = self._payoff(human_move, opponent_move)
            self.human_score += human_points
            self.opponent_score += opponent_points
            self._write_log(
                f"第 {self.current_turn} 回合："
                f"你={'C' if human_move else 'D'}，"
                f"AI={'C' if opponent_move else 'D'}；"
                f"本回合得分 {human_points}:{opponent_points}"
            )
            self._update_summary()

            if self.current_turn >= self._read_turns():
                self._set_action_state("disabled")
                average_score = self.human_score / self.current_turn
                strategy_name = self.ai_agent.strategy.name
                self.human_score_samples.setdefault(strategy_name, []).append(
                    average_score
                )
                self.human_scores[strategy_name] = sum(
                    self.human_score_samples[strategy_name]
                ) / len(self.human_score_samples[strategy_name])
                self.human_histories.setdefault(strategy_name, []).extend(
                    self.human_history
                )
                self.opponent_histories.setdefault(strategy_name, []).extend(
                    self.opponent_history
                )
                self.opponent_index += 1
                if self.opponent_index < len(self.opponent_order):
                    self.status_var.set(
                        f"本场结束（平均得分 {average_score:.2f}），准备下一场"
                    )
                    self.root.after(500, self._start_match)
                else:
                    self.status_var.set("全部对局完成")
                    self.root.after(500, self._finish_all_matches)
            else:
                self.status_var.set("请选择下一回合动作")

        @staticmethod
        def _payoff(human_move: bool, opponent_move: bool) -> tuple[int, int]:
            if human_move and opponent_move:
                return 2, 2
            if human_move and not opponent_move:
                return -1, 3
            if not human_move and opponent_move:
                return 3, -1
            return 0, 0

        def _update_summary(self) -> None:
            self.score_var.set(
                f"你的得分：{self.human_score}    "
                f"AI 得分：{self.opponent_score}    "
                f"回合：{self.current_turn}/{self._read_turns()}"
            )
            human_moves = " ".join("C" if move else "D" for move in self.human_history)
            opponent_moves = " ".join(
                "C" if move else "D" for move in self.opponent_history
            )
            self.history_var.set(f"你的历史：{human_moves or '-'}    AI 历史：{opponent_moves or '-'}")

        def _write_log(self, message: str) -> None:
            self.log.configure(state="normal")
            self.log.insert("end", message + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")

    root = tk.Tk()
    GameWindow(root)
    root.mainloop()


# ==================== 主程序 ====================
if __name__ == "__main__":
    random.seed(42)
    launch_game_gui()