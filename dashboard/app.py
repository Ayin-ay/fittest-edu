"""The Fittest step-by-step dashboard.

Run from the repository root with:

    streamlit run dashboard/app.py

The simulation is not pre-computed: each click of "next generation" advances
exactly one step, and earlier generations are replayed from the saved history.
"""

from __future__ import annotations

import json
import os
import random
import sqlite3
import sys
import zlib
from pathlib import Path

# Import pandas up front. Streamlit imports pandas lazily (e.g. inside
# st.dataframe), and while that import is in flight Plotly's validator can see
# a partially initialized ``pandas`` module in sys.modules, raising
# "partially initialized module 'pandas' has no attribute 'Series'". Loading it
# eagerly here guarantees Plotly always sees a complete module.
import pandas  # noqa: F401
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trust_evolution_simulation import (  # noqa: E402
    ENGINE_VERSION,
    PAYOFFS,
    RUN_SCHEMA_VERSION,
    TOTAL_CAPACITY,
    EvolutionEvent,
    TrustEvolution,
    parse_strategy,
)
from dashboard.content import (  # noqa: E402
    INTRO_MARKDOWN,
    LANDING_ARCH,
    LANDING_GLOSS,
    LANDING_STEPS,
    LANDING_WHY,
    STRATEGY_MARKDOWN,
)
try:
    from dashboard.responsive import (  # noqa: E402
        MODE_AUTO,
        MODE_HELP,
        MODE_LABELS,
        MODE_MOBILE,
        fullscreen_css,
        is_forced_mobile,
        responsive_css,
    )
except ImportError:  # pragma: no cover
    # Responsive styling is cosmetic: a missing or half-synced module must not
    # take the whole simulation down. Fall back to the desktop layout, and say
    # so on screen instead of failing at import time.
    MODE_AUTO, MODE_MOBILE, MODE_DESKTOP = "auto", "mobile", "desktop"
    MODE_LABELS = {
        MODE_AUTO: "自动（按屏幕宽度）",
        MODE_MOBILE: "手机",
        MODE_DESKTOP: "桌面",
    }
    MODE_HELP = {
        MODE_AUTO: "窄屏自动切换成手机版式，桌面保持原样。",
        MODE_MOBILE: "强制手机版式，便于在电脑上预览调试。",
        MODE_DESKTOP: "保持原有桌面版式，不注入任何适配样式。",
    }

    def is_forced_mobile(mode: str) -> bool:
        return mode == MODE_MOBILE

    def responsive_css(mode: str) -> str:
        return ""

    def fullscreen_css() -> str:
        return ""
from dashboard.strategylib import (  # noqa: E402
    delete_strategy,
    load_strategies,
    save_strategy,
)
from dashboard.export import (  # noqa: E402
    RUNS_DIR,
    build_export_bundle,
    bundle_to_markdown,
    save_markdown_report,
)
from dashboard.saveload import (  # noqa: E402
    delete_saved,
    list_saved_simulations,
    load_simulation_from_data,
    load_simulation_from_file,
    rename_saved,
    save_simulation,
)
from dashboard.ai_analysis import (  # noqa: E402
    card_verdict as ai_card_verdict,
    configured_provider_label as ai_provider_label,
    probe_connection as ai_probe,
    server_config as ai_config,
    stream_text as ai_stream_text,
    stream_analysis as ai_stream,
)
from dashboard import challenges  # noqa: E402
from dashboard import evolution_analysis  # noqa: E402
from dashboard import store  # noqa: E402
from dashboard import theme  # noqa: E402
from dashboard.gameplay import (  # noqa: E402
    Match,
    PlayerMatchRunner,
    action_cue,
    branch_strip,
    build_results,
    build_results_figure,
    draw_opponents,
    history_table,
    identity_card,
    matches_overview,
    prediction_note,
    stage_strip,
    strategy_tournament,
)
from dashboard.profiling import build_profile  # noqa: E402
from dashboard.share_card import (  # noqa: E402
    classify as classify_play_style,
    build_card as build_play_card,
    share_text as play_card_text,
)
from dashboard.tutorial import (  # noqa: E402
    CLOSING as TUTORIAL_CLOSING,
    INTRO as TUTORIAL_INTRO,
    RULES as TUTORIAL_RULES,
    TUTORIAL_OPPONENT,
    TUTORIAL_TURNS,
    TutorialState,
    describe_last as tutorial_describe_last,
    lesson_advice as tutorial_lesson_advice,
    opening_note as tutorial_opening_note,
    outcome_note as tutorial_outcome_note,
    reacted_note as tutorial_reacted_note,
    play as tutorial_play,
    score_line as tutorial_scores,
    tutorial_progress,
)
from dashboard.visuals import (  # noqa: E402
    build_action_map,
    build_field_standing,
    build_radar,
    build_rate_bars,
    build_score_cards,
    build_score_trend,
    dimension_scores,
)
from dashboard.loading import (  # noqa: E402
    SPLASH_CSS,
    analysis_loading,
)
from dashboard.strategy_detail import parse_strategy_detail  # noqa: E402
from dashboard.render_helpers import (  # noqa: E402
    build_change_rows,
    build_distribution_bar,
    build_distribution_pie,
    build_evolution_tree,
    build_fitness_rows,
    build_heatmap_detail,
    build_matchup_heatmap,
    build_population_area,
    build_snapshot_html,
    events_at,
    _display_name,
)

from dashboard.naming import build_name_map  # noqa: E402

DEFAULT_CUSTOM = "S1,25\nS2,20\nF1-1,15\nF2-3,15\nT1-2,10\nD0,10\nW,5"

PIN_OPTIONS = {
    "不锁定": None,
    "物种分布（柱状图 + 饼图）": "distribution",
    "物种规模列表": "sizes",
    "对局热力图": "heatmap",
    "适应度": "fitness",
    "策略增减": "changes",
}
PIN_LABELS = {value: label for label, value in PIN_OPTIONS.items() if value}


def _configured_secret(name: str) -> str | None:
    """Read a secret from st.secrets (or the environment). None means unset."""
    value = None
    try:
        value = st.secrets.get(name)
    except Exception:  # no secrets file configured
        value = None
    return value or os.getenv(name) or None


def _configured_password() -> str | None:
    """Read APP_PASSWORD from st.secrets (or env). None means no gate."""
    return _configured_secret("APP_PASSWORD")


def check_password() -> bool:
    """Simple in-app password gate. Disabled when no password is configured."""
    expected = _configured_password()
    if not expected:
        return True
    if st.session_state.get("password_correct"):
        return True
    st.title("The Fittest")
    st.caption("请输入访问密码")
    password = st.text_input("密码", type="password", label_visibility="collapsed")
    if st.button("进入", type="primary"):
        if password == expected:
            st.session_state["password_correct"] = True
            st.rerun()
        else:
            st.error("密码错误")
    return False


def pin_css() -> str:
    """Make the keyed container stick to the top of the viewport."""
    background = st.get_option("theme.backgroundColor") or theme.GROUND
    return (
        "<style>"
        ".st-key-pinned_panel {"
        "position: sticky; top: 3.75rem; z-index: 1000;"
        "max-height: 82vh; overflow-y: auto;"
        f"background: {background};"
        f"box-shadow: {theme.SHADOW_PIN}; border-radius: 0.5rem;"
        "}"
        "</style>"
    )


@st.dialog("项目说明", width="large")
def intro_dialog() -> None:
    st.markdown(INTRO_MARKDOWN)


@st.dialog("策略模块说明", width="large")
def strategies_dialog() -> None:
    st.markdown(STRATEGY_MARKDOWN)



def parse_custom(text: str) -> tuple[list[str], dict[str, int]]:
    encodings: list[str] = []
    sizes: dict[str, int] = {}
    for line in text.splitlines():
        if not line.strip():
            continue
        encoding, size_text = [part.strip() for part in line.split(",", 1)]
        parse_strategy(encoding)
        size = int(size_text)
        if size <= 0 or encoding in sizes:
            raise ValueError("策略编码不能重复，规模必须为正整数")
        encodings.append(encoding)
        sizes[encoding] = size
    if not encodings:
        raise ValueError("至少需要一个策略")
    return encodings, sizes


def _append_library_strategy() -> None:
    """on_click handler: append a library strategy line to the custom text area."""
    encoding = st.session_state.get("custom_lib_add")
    size = st.session_state.get("custom_lib_size")
    if not encoding:
        return
    current = st.session_state.get("custom_text_value", DEFAULT_CUSTOM).rstrip()
    st.session_state["custom_text_value"] = (
        current + "\n" if current else ""
    ) + f"{encoding},{int(size)}"


def _inject_strategy() -> None:
    """on_click handler: inject a strategy into the current frontier generation."""
    simulation = st.session_state.get("sim")
    if simulation is None:
        return
    encoding = st.session_state.get("inject_lib")
    if not encoding or encoding == "（手输编码）":
        encoding = (st.session_state.get("inject_typed") or "").strip()
    size = int(st.session_state.get("inject_size", 20))
    try:
        parse_strategy(encoding)
    except Exception as error:  # noqa: BLE001 - surface message to user
        st.session_state["inject_error"] = f"策略编码无效：{error}"
        return
    simulation.inject_strategy(encoding, size)
    simulation.events.append(EvolutionEvent(simulation.generation, "injection", encoding))
    simulation.re_record_frontier()
    st.session_state["view_gen"] = simulation.generation
    st.session_state["gen_jump"] = simulation.generation
    st.session_state.pop("export_cache_key", None)
    st.session_state["inject_error"] = None


def _render_saved_simulations() -> None:
    """Always-visible browse / load / rename / delete for saved runs."""
    saved_list = list_saved_simulations()
    if not saved_list:
        st.divider()
        st.subheader("统一存档 / 加载")
        st.caption(f"暂无已保存的模拟。在「导出分析数据」中保存后，存档会写入 {RUNS_DIR}。")
        return
    st.divider()
    st.subheader("统一存档 / 加载")
    options = {}
    for item in saved_list:
        flag = " ⚠旧引擎" if item.get("stale_engine") else ""
        note = f" · {item['note']}" if item.get("note") else ""
        label = (
            f"{item['name']}{note}（seed={item['seed']}，{item['generations']} 代，"
            f"引擎 {item.get('engine_version')}{flag}）"
        )
        options[label] = item["file"]
    try:
        selected_file = options[st.selectbox("选择存档", list(options), key="saved_select")]
    except KeyError:
        selected_file = next(iter(options.values()))
    chosen = next(
        (item for item in saved_list if item["file"] == selected_file), None
    )
    if chosen:
        st.caption(
            "保存于 {}　存活 {}　注入 {} 次　引擎 {}（格式 {}）".format(
                chosen.get("created_at"),
                chosen.get("surviving_species"),
                chosen.get("injections"),
                chosen.get("engine_version"),
                chosen.get("schema_version"),
            )
        )
        if chosen.get("stale_engine"):
            st.warning(
                "该存档由引擎 {} 生成，与当前引擎不一致：可读取与继续，但用同 seed 重跑"
                "不会得到相同轨迹。".format(chosen.get("engine_version"))
            )
    load_col, delete_col = st.columns(2)
    with load_col:
        if st.button("加载该存档", width="stretch", type="primary"):
            loaded = load_simulation_from_file(selected_file)
            st.session_state["sim"] = loaded
            st.session_state["seed"] = chosen.get("seed") if chosen else None
            st.session_state["view_gen"] = loaded.generation
            st.session_state["gen_jump"] = loaded.generation
            st.session_state.pop("export_cache_key", None)
            st.rerun()
    with delete_col:
        if st.button("删除存档", width="stretch"):
            delete_saved(selected_file)
            st.rerun()
    new_saved_name = st.text_input("重命名为", key="rename_new_name")
    if st.button("重命名该存档", width="stretch"):
        if new_saved_name.strip():
            rename_saved(selected_file, new_saved_name.strip())
            st.rerun()


def _strategy_names(sim: TrustEvolution) -> dict[str, str] | None:
    """Return the Chinese name map, or None when the system encoding is active."""
    if st.session_state.get("strategy_lang", "中文") != "中文":
        return None
    encodings: list[str] = []
    for snapshot in sim.history:
        encodings.extend(snapshot.keys())
    for event in sim.events:
        encodings.append(event.encoding)
        if event.parent_encoding:
            encodings.append(event.parent_encoding)
    return build_name_map(list(dict.fromkeys(encodings)))


def _render_share() -> None:
    """Upload a unified archive to reproduce someone else's run.

    There is no separate "share" download any more: the unified archive already
    carries everything needed to reproduce a run, so it *is* the share file.
    """
    st.divider()
    st.subheader("载入 / 复现")
    st.caption(
        "上传统一存档（archive/runs/*.tev.json）即可还原并继续演化；"
        "旧版分享摘要与面板存档仍可读取。"
    )
    uploaded = st.file_uploader(
        "上传统一存档复现", type=["json"], key="share_upload"
    )
    if uploaded is not None:
        try:
            data = json.loads(uploaded.getvalue().decode("utf-8"))
        except Exception as error:  # noqa: BLE001 - surface message to user
            st.error(f"解析失败：{error}")
            data = None
        if data is not None and st.button("用该文件复现", type="primary", width="stretch"):
            try:
                simulation = load_simulation_from_data(data)
            except Exception as error:  # noqa: BLE001 - surface message to user
                st.error(f"复现失败：{error}")
            else:
                seed = data.get("seed")
                if seed is None and isinstance(data.get("meta"), dict):
                    seed = data["meta"].get("seed")
                if seed is None and isinstance(data.get("summary"), dict):
                    seed = data["summary"].get("seed")
                st.session_state["sim"] = simulation
                st.session_state["seed"] = seed
                st.session_state["init_encodings"] = data.get("initial_encodings") or (
                    data.get("reproduce", {}).get("initial_encodings")
                    if isinstance(data.get("reproduce"), dict)
                    else None
                )
                st.session_state["init_sizes"] = data.get("initial_sizes") or (
                    data.get("reproduce", {}).get("initial_sizes")
                    if isinstance(data.get("reproduce"), dict)
                    else None
                )
                st.session_state["view_gen"] = simulation.generation
                st.session_state["gen_jump"] = simulation.generation
                st.session_state.pop("export_cache_key", None)
                st.rerun()


def render_sidebar() -> dict | None:
    with st.sidebar:
        st.title("The Fittest")
        st.caption("🎛 创造模式 · 演化模拟工作台")
        if st.button("← 切换模式", key="back_to_modes", width="stretch"):
            st.session_state["app_mode"] = None
            st.rerun()

        st.radio("策略命名", ["中文", "系统编码"], index=0, key="strategy_lang", horizontal=True)

        layout_mode = st.radio(
            "页面适配",
            [MODE_AUTO, MODE_MOBILE, "desktop"],
            format_func=lambda value: MODE_LABELS.get(value, value),
            index=0,
            key="layout_mode",
            help="\n\n".join(
                "{}：{}".format(MODE_LABELS[key], MODE_HELP[key])
                for key in (MODE_AUTO, MODE_MOBILE, "desktop")
            ),
        )
        # The radio already publishes its value under ``layout_mode``; writing it
        # back into session_state would raise, since a widget may not be
        # reassigned from behind Streamlit's back.

        info_col, strategy_col = st.columns(2)
        with info_col:
            if st.button("项目说明", width="stretch"):
                intro_dialog()
        with strategy_col:
            if st.button("策略说明", width="stretch"):
                strategies_dialog()

        st.divider()
        mode = st.radio("初始种群", ["随机生成", "使用种子", "自定义"], index=0)

        seed: int | None = None
        seed_valid = True
        if mode == "使用种子":
            seed_text = st.text_input(
                "随机种子",
                value="42",
                help="可输入任意大小整数（最大可到 2^63），支持粘贴从「随机生成」看到的种子。",
            )
            try:
                seed = int(seed_text.strip())
            except ValueError:
                st.error("随机种子必须是整数。")
                seed_valid = False

        encodings: list[str] | None = None
        sizes: dict[str, int] | None = None
        valid = True
        if mode == "自定义":
            custom_text = st.text_area(
                "自定义策略（每行：编码,规模）",
                value=DEFAULT_CUSTOM,
                height=180,
                key="custom_text_value",
            )
            try:
                encodings, sizes = parse_custom(custom_text)
                if sum(sizes.values()) != TOTAL_CAPACITY:
                    st.error(
                        f"规模总和必须为 {TOTAL_CAPACITY}，当前为 {sum(sizes.values())}"
                    )
                    valid = False
            except Exception as error:  # noqa: BLE001 - surface message to user
                st.error(f"解析失败：{error}")
                valid = False
            strategy_library = load_strategies()
            if strategy_library:
                st.divider()
                add_encoding = st.selectbox(
                    "从策略库添加",
                    [s["encoding"] for s in strategy_library],
                    key="custom_lib_add",
                )
                add_size = st.number_input(
                    "该策略规模", min_value=1, max_value=50, value=15, step=1, key="custom_lib_size"
                )
                if st.button("加入自定义列表", width="stretch", on_click=_append_library_strategy):
                    pass

        running = "sim" in st.session_state
        if st.button(
            "重新开始" if running else "开始模拟",
            type="primary",
            width="stretch",
        ):
            if not valid or not seed_valid:
                return None
            if seed is None:
                seed = random.SystemRandom().randrange(0, 2**63)
            return {"seed": seed, "encodings": encodings, "sizes": sizes}

        if running:
            simulation = st.session_state["sim"]
            st.caption(f"已模拟 {simulation.generation} 轮")
            st.caption(f"种子 {st.session_state.get('seed', '-')}")
            st.divider()
            labels = list(PIN_OPTIONS)
            current = st.session_state.get("pin_label", "不锁定")
            choice = st.selectbox(
                "锁定模块",
                labels,
                index=labels.index(current) if current in labels else 0,
            )
            st.session_state["pin_label"] = choice
            st.session_state["pin"] = PIN_OPTIONS[choice]

            st.divider()
            st.subheader("统一存档")
            st.caption(
                f"写入 archive/runs/　引擎 {ENGINE_VERSION}　格式 {RUN_SCHEMA_VERSION}"
            )
            default_name = f"sim_seed{st.session_state.get('seed')}_g{simulation.generation}"
            save_name = st.text_input(
                "存档名称（可留空自动命名）", placeholder=default_name, key="save_name_input"
            )
            save_note = st.text_input("备注（可选）", key="save_note_input")
            if st.button("保存当前模拟", width="stretch", type="primary"):
                saved_meta = save_simulation(
                    simulation,
                    save_name.strip() or default_name,
                    seed=st.session_state.get("seed"),
                    initial_encodings=st.session_state.get("init_encodings"),
                    initial_sizes=st.session_state.get("init_sizes"),
                    note=save_note.strip() or None,
                )
                st.success(
                    f"已保存：{saved_meta['filename']}"
                    f"（seed={saved_meta['seed']}，{saved_meta['generations']} 代，"
                    f"引擎 {saved_meta['engine_version']}）"
                )

            st.divider()
            st.subheader("策略库")
            live_codes = list({item.encoding for item in simulation.species})
            if live_codes:
                pick_code = st.selectbox("选择要保存的策略", live_codes, key="save_strat_pick")
                if st.button("保存到策略库", width="stretch", type="primary"):
                    if save_strategy(pick_code):
                        st.success(f"已保存：{pick_code}")
                    else:
                        st.info("该策略已在库中。")
            library = load_strategies()
            if library:
                lib_by_encoding = {s["encoding"]: s for s in library}
                lib_codes = list(lib_by_encoding)
                lib_sel = st.selectbox("策略库", lib_codes, key="lib_pick")
                if st.button("从库中删除", width="stretch"):
                    delete_strategy(lib_sel)
                    st.rerun()

        _render_saved_simulations()
        _render_share()
    return None


def start_simulation(settings: dict) -> None:
    simulation = TrustEvolution(
        seed=settings["seed"],
        initial_encodings=settings["encodings"],
        initial_sizes=settings["sizes"],
    )
    st.session_state["sim"] = simulation
    st.session_state["seed"] = settings["seed"]
    st.session_state["init_encodings"] = settings["encodings"]
    st.session_state["init_sizes"] = settings["sizes"]
    st.session_state["view_gen"] = 0
    st.session_state["gen_jump"] = 0


_EVENT_MARK = {
    "subspecies_birth": "◇",
    "subspecies_independent": "★",
    "extinction": "×",
    "subspecies_extinction": "✕",
    "injection": "＋",
}


def generation_label(sim: TrustEvolution, generation: int) -> str:
    """Label for the jump menu, with one marker per special event."""
    marks = "".join(
        _EVENT_MARK.get(event.event, "")
        for event in sim.events
        if event.generation == generation
    )
    return f"第 {generation} 轮" + (f"　{marks}" if marks else "")


def _set_generation(value: int) -> None:
    st.session_state["view_gen"] = value
    st.session_state["gen_jump"] = value


def _go_previous() -> None:
    _set_generation(max(0, st.session_state["view_gen"] - 1))


def _go_next(sim: TrustEvolution) -> None:
    current = st.session_state["view_gen"]
    if current < sim.generation:
        _set_generation(current + 1)
    else:
        sim.step()
        _set_generation(sim.generation)


def _go_next_ten(sim: TrustEvolution) -> None:
    for _ in range(10):
        if not sim.species:
            break
        sim.step()
    _set_generation(sim.generation)


def _jump_selected() -> None:
    st.session_state["view_gen"] = st.session_state["gen_jump"]


def _layout_mode() -> str:
    return st.session_state.get("layout_mode", MODE_AUTO)


def _mobile() -> bool:
    """True when the mobile layout is forced, not merely auto-detected."""
    return is_forced_mobile(_layout_mode())


def _chart_config() -> dict:
    """Plotly config; the mode bar is noise on a small screen."""
    if _mobile():
        return {"displayModeBar": False, "scrollZoom": True}
    return {}


def render_navigation(sim: TrustEvolution) -> None:
    view_gen = st.session_state["view_gen"]
    frontier = sim.generation
    if "gen_jump" not in st.session_state:
        st.session_state["gen_jump"] = view_gen
    if st.session_state["gen_jump"] > frontier:
        st.session_state["gen_jump"] = view_gen
    labels = {generation: generation_label(sim, generation) for generation in range(frontier + 1)}

    if _mobile():
        # Four controls across a phone are unusable, and "下十轮" is the button
        # that gets pressed most, so it takes the full second row.
        previous, following = st.columns(2)
        with previous:
            st.button(
                "◀ 上一轮",
                disabled=view_gen <= 0,
                width="stretch",
                on_click=_go_previous,
            )
        with following:
            st.button(
                "下一轮 ▶",
                type="primary",
                width="stretch",
                disabled=not sim.species,
                on_click=_go_next,
                args=(sim,),
            )
        st.selectbox(
            "跳到轮次",
            options=list(range(frontier + 1)),
            format_func=lambda generation: labels[generation],
            key="gen_jump",
            on_change=_jump_selected,
            label_visibility="collapsed",
        )
        st.button(
            "下十轮 ▶▶",
            width="stretch",
            disabled=not sim.species,
            on_click=_go_next_ten,
            args=(sim,),
        )
        return

    previous, middle, following, following_ten = st.columns([1, 2, 1, 1])
    with previous:
        st.button(
            "◀ 上一轮",
            disabled=view_gen <= 0,
            width="stretch",
            on_click=_go_previous,
        )
    with middle:
        st.selectbox(
            "跳到轮次",
            options=list(range(frontier + 1)),
            format_func=lambda generation: labels[generation],
            key="gen_jump",
            on_change=_jump_selected,
            label_visibility="collapsed",
        )
    with following:
        st.button(
            "下一轮 ▶",
            type="primary",
            width="stretch",
            disabled=not sim.species,
            on_click=_go_next,
            args=(sim,),
        )
    with following_ten:
        st.button(
            "下十轮 ▶▶",
            width="stretch",
            disabled=not sim.species,
            on_click=_go_next_ten,
            args=(sim,),
        )


def render_distribution(
    sim: TrustEvolution, names: dict[str, str] | None = None
) -> None:
    """Bar and pie charts for the current generation."""
    view_gen = st.session_state["view_gen"]
    bar = build_distribution_bar(sim, view_gen, names)
    pie = build_distribution_pie(sim, view_gen, names)
    if _mobile():
        st.plotly_chart(bar, width="stretch", config=_chart_config())
        st.plotly_chart(pie, width="stretch", config=_chart_config())
        return
    bar_col, pie_col = st.columns([3, 2])
    with bar_col:
        st.plotly_chart(bar, width="stretch")
    with pie_col:
        st.plotly_chart(pie, width="stretch")


def _heatmap_species_count(sim: TrustEvolution, generation: int) -> int:
    generation = max(0, min(generation, len(sim.generation_records) - 1))
    matrix = sim.generation_records[generation].matchup_matrix
    return len(matrix) if matrix else 0


def render_heatmap_fullscreen(
    sim: TrustEvolution,
    generation: int,
    names: dict[str, str] | None = None,
) -> None:
    """Whole-page heatmap viewer.

    A Streamlit dialog is never truly full screen: it keeps a title bar, a close
    button and the dimmed page behind it, and on a phone that chrome costs a
    meaningful slice of the viewport. Taking over the page instead means the
    chart is the only thing rendered, the top bar and sidebar are hidden, and
    the whole screen is available to the matrix.

    One finger pans and two fingers pinch-zoom come from Plotly natively, so no
    gesture hints are shown.
    """
    title_col, close_col = st.columns([9, 2])
    with title_col:
        # Just the generation: the chart's own title was removed to give the
        # top labels their vertical room, so the header is the only place the
        # number appears.
        st.markdown(f"**第 {generation} 代**")
    with close_col:
        if st.button("✕ 退出", key="heatmap_fullscreen_exit", width="stretch"):
            st.session_state["heatmap_fullscreen"] = None
            st.rerun()
    figure = build_heatmap_detail(sim, generation, names)
    st.plotly_chart(
        figure,
        width="stretch",
        config={
            "displayModeBar": False,
            "displaylogo": False,
            "scrollZoom": True,
            "responsive": True,
        },
    )


def render_heatmap(
    sim: TrustEvolution,
    generation: int,
    names: dict[str, str] | None = None,
) -> None:
    """Render the matchup heatmap.

    On the desktop layout this is the chart on its own. On a phone a grid of
    many long strategy names collapses into unreadable colour blocks, so the
    chart is capped and paired with an enlarge button that takes over the page.
    """
    figure = build_matchup_heatmap(sim, generation, names)
    if not _mobile():
        st.plotly_chart(figure, width="stretch")
        return

    count = _heatmap_species_count(sim, generation)
    if count > 6:
        st.caption(
            f"共 {count} 个策略，缩略图只用于看整体色块分布；"
            "点下方按钮可全屏查看并缩放。"
        )
    st.plotly_chart(figure, width="stretch", config=_chart_config())
    if st.button("🔍 放大热力图（全屏 · 可缩放）", width="stretch"):
        st.session_state["heatmap_fullscreen"] = generation
        st.rerun()


def render_module(
    name: str,
    sim: TrustEvolution,
    generation: int,
    names: dict[str, str] | None = None,
) -> None:
    """Render one pinnable module."""
    if name == "distribution":
        render_distribution(sim, names)
    elif name == "sizes":
        st.markdown(build_snapshot_html(sim, generation, names), unsafe_allow_html=True)
    elif name == "heatmap":
        render_heatmap(sim, generation, names)
    elif name == "fitness":
        _rows = build_fitness_rows(sim, generation, names)
        _event = st.dataframe(
            _rows,
            key="pinned_fitness_rows",
            on_select="rerun",
            selection_mode="single-row",
            width="stretch",
            hide_index=True,
            height=280,
        )
        _sync_detail_from_selection(_event, _rows, "pinned_fitness")
    elif name == "changes":
        _rows = build_change_rows(sim, generation, names)
        _event = st.dataframe(
            _rows,
            key="pinned_change_rows",
            on_select="rerun",
            selection_mode="single-row",
            width="stretch",
            hide_index=True,
            height=280,
        )
        _sync_detail_from_selection(_event, _rows, "pinned_changes")


def _all_encodings(sim: TrustEvolution) -> list[str]:
    encs: list[str] = []
    for snapshot in sim.history:
        encs.extend(snapshot.keys())
    for event in sim.events:
        encs.append(event.encoding)
        if event.parent_encoding:
            encs.append(event.parent_encoding)
    return list(dict.fromkeys(encs))


def _selection_rows(event) -> list[int]:
    sel = getattr(event, "selection", None)
    if not sel:
        return []
    if isinstance(sel, dict):
        return list(sel.get("rows", []) or [])
    return list(getattr(sel, "rows", []) or [])


def _sync_detail_from_selection(event, rows: list[dict], source_key: str) -> None:
    """Show the clicked strategy; hide the detail when its row is deselected."""
    sel = list(_selection_rows(event))
    last_key = f"detail_last_{source_key}"
    if sel == st.session_state.get(last_key):
        return
    st.session_state[last_key] = sel
    if sel and 0 <= sel[0] < len(rows):
        st.session_state["detail_selected"] = rows[sel[0]]["策略"]
        st.session_state["detail_source"] = source_key
        st.rerun()
    elif not sel and st.session_state.get("detail_source") == source_key:
        st.session_state["detail_selected"] = None
        st.session_state["detail_source"] = None
        st.rerun()


def _detail_float_css() -> str:
    """Pin the detail container to the viewport as a floating window.

    In the responsive (auto/mobile) modes ``responsive_css`` already turns this
    into a bottom sheet, so the inline rule must not fight it. Only the desktop
    layout gets the floating corner treatment.
    """
    background = st.get_option("theme.backgroundColor") or theme.GROUND
    return (
        "<style>"
        ".st-key-detail_float {"
        "position: fixed; right: 1rem; bottom: 1rem; width: min(380px, 92vw);"
        "max-height: 72vh; overflow-y: auto; z-index: 100000;"
        f"background: {background};"
        f"border: 1px solid {theme.EDGE}; border-radius: 0.6rem;"
        f"box-shadow: {theme.SHADOW_FLOAT}; padding: 0.5rem 0.8rem;"
        "}"
        "</style>"
    )


def _resolve_strategy_target(
    sim: TrustEvolution,
    names: dict[str, str] | None,
    generation: int,
    display: str,
) -> tuple[str | None, str | None]:
    """Resolve ``display`` into ``(sub_raw, main_raw)``. ``sub_raw`` is None when the
    selected row is the parent species itself.
    """
    display = display.lstrip("　 ")
    prefix = "└ 亚种 "
    if display.startswith(prefix):
        sub_display = display[len(prefix):]
        for main_enc, data in sim.generation_records[generation].species_data.items():
            sub = data.get("subspecies")
            if sub and _display_name(names, sub["encoding"]) == sub_display:
                return sub["encoding"], main_enc
        return None, None
    for main_enc, data in sim.generation_records[generation].species_data.items():
        if _display_name(names, main_enc) == display:
            return None, main_enc
    return None, None


def render_strategy_detail_float(
    sim: TrustEvolution,
    names: dict[str, str] | None,
    selected: str | None,
    view_gen: int = 0,
) -> None:
    """Show the selected strategy's detail.

    On the desktop layout this is a floating window pinned to the bottom-right
    corner. In the responsive modes the same container is restyled as a bottom
    sheet by ``responsive_css``, which keeps it reachable without covering the
    content underneath.
    """
    if not selected:
        return
    sub_raw, main_raw = _resolve_strategy_target(sim, names, view_gen, selected)
    st.markdown(_detail_float_css(), unsafe_allow_html=True)
    with st.container(key="detail_float"):
        head_left, head_right = st.columns([6, 1])
        with head_left:
            head_label = (
                f"策略详情 · {_display_name(names, main_raw)} └ 亚种 · {_display_name(names, sub_raw)}"
                if (main_raw and sub_raw)
                else f"策略详情 · {_display_name(names, main_raw)}"
                if main_raw
                else "策略详情"
            )
            st.markdown(f"**{head_label}**")
        with head_right:
            if st.button("✕", key="detail_float_close", help="关闭"):
                st.session_state["detail_selected"] = None
                st.session_state["detail_source"] = None
                st.rerun()
        if not main_raw:
            st.caption("该策略已不在当前模拟中。")
            return
        st.caption(f"主编码：`{main_raw}`")
        st.markdown("**主策略模块**")
        for slot, module_name, text in parse_strategy_detail(main_raw):
            st.markdown(f"- **[{slot}] {module_name}** — {text}")
        if sub_raw:
            record = sim.generation_records[view_gen].species_data.get(main_raw, {})
            sub_data = record.get("subspecies", {})
            sub_fitness = sub_data.get("fitness")
            st.markdown("---")
            st.caption(f"亚种编码：`{sub_raw}`")
            st.markdown("**亚种模块**")
            for slot, module_name, text in parse_strategy_detail(sub_raw):
                st.markdown(f"- **[{slot}] {module_name}** — {text}")
            if sub_fitness is not None:
                st.markdown(f"亚种适应度：**{sub_fitness:.2f}**")


def render_events(
    sim: TrustEvolution,
    generation: int,
    names: dict[str, str] | None = None,
) -> None:
    events = events_at(sim, generation, names)
    st.subheader("本轮特殊事件")
    if not events:
        st.caption("本轮没有特殊事件。")
        return
    for event in events:
        st.markdown(
            f"<div style='padding:5px 10px;margin:3px 0;border-left:4px solid "
            f"{event['color']};background:{theme.RAISED};font-size:13px;'>"
            f"<b style='color:{event['color']}'>{event['事件']}</b>　"
            f"{event['编码']}　"
            f"<span style='color:{theme.MUTED};'>父代 {event['父代']}</span></div>",
            unsafe_allow_html=True,
        )


def _alive_count(record) -> int:
    """Species still standing in one generation record."""
    alive = 0
    for data in record.species_data.values():
        subspecies = data.get("subspecies")
        total = data.get("population_size", 0) + (
            subspecies["size"] if subspecies else 0
        )
        if total > 0:
            alive += 1
    return alive


def render_main() -> None:
    simulation = st.session_state.get("sim")
    if simulation is None:
        st.title("The Fittest — 逐轮演化")
        st.info("在左侧配置初始种群，点击「开始模拟」。")
        return

    names = _strategy_names(simulation)

    # Full-page heatmap viewer. It takes over the whole page, so it short
    # circuits before any of the normal modules render.
    fullscreen_generation = st.session_state.get("heatmap_fullscreen")
    if fullscreen_generation is not None:
        fullscreen_generation = max(
            0, min(fullscreen_generation, simulation.generation)
        )
        render_heatmap_fullscreen(simulation, fullscreen_generation, names)
        return

    st.title("The Fittest — 逐轮演化")
    pin = st.session_state.get("pin")
    if pin:
        st.markdown(pin_css(), unsafe_allow_html=True)
        with st.container(key="pinned_panel", border=True):
            render_navigation(simulation)
            view_gen = st.session_state["view_gen"]
            st.caption(f"已锁定：{PIN_LABELS.get(pin, pin)}")
            render_module(pin, simulation, view_gen, names)
    else:
        render_navigation(simulation)

    view_gen = st.session_state["view_gen"]
    record = simulation.generation_records[view_gen]

    alive = _alive_count(record)
    previous = (
        simulation.generation_records[view_gen - 1] if view_gen > 0 else None)
    metric_a, metric_b, metric_c = st.columns(3)
    # Both carry the change against the previous round. ``delta_color="off"`` for
    # 存活策略 on purpose: one fewer strategy standing is extinction, which is the
    # subject of the simulation, not a failure of it -- and the plain grey of
    # ``delta_color`` keeps the two from reading as good and bad news.
    metric_a.metric(
        "存活策略", alive,
        delta=None if previous is None else "{:+d} 较上一轮".format(
            alive - _alive_count(previous)),
        delta_color="off",
    )
    metric_b.metric(
        "平均适应度", "{:.2f}".format(record.average_fitness),
        delta=None if previous is None else "{:+.2f} 较上一轮".format(
            record.average_fitness - previous.average_fitness),
    )
    metric_c.metric("本轮特殊事件", len(events_at(simulation, view_gen, names)))

    render_events(simulation, view_gen, names)

    if view_gen == simulation.generation:
        with st.expander("手动注入策略（其余物种等比缩小）", expanded=False):
            library = load_strategies()
            lib_picker = ["（手输编码）"] + [s["encoding"] for s in library]
            inject_from_lib = st.selectbox("从策略库选择", lib_picker, key="inject_lib")
            inject_typed = st.text_input(
                "或手动输入策略编码",
                value="",
                placeholder="如 S1+P1-1",
                key="inject_typed",
            )
            inject_size = st.slider("注入规模", min_value=1, max_value=90, value=20, key="inject_size")
            if st.button("注入到当前代", type="primary", on_click=_inject_strategy):
                pass
            inject_error = st.session_state.pop("inject_error", None)
            if inject_error:
                st.error(inject_error)
    else:
        st.caption(f"手动注入仅在最新一轮可用（当前查看第 {view_gen} 轮）。")

    with st.expander("大模型解读这场演化", expanded=False):
        _render_creation_ai(simulation, names)

    st.subheader("物种分布")
    if pin == "distribution":
        st.caption("该模块已锁定到页面上方。")
    else:
        render_distribution(simulation, names)

    st.subheader("策略增减")
    if pin == "changes":
        st.caption("该模块已锁定到页面上方。")
    else:
        st.caption("对比上一轮；点击任意一行查看该策略说明。")
        _change_rows = build_change_rows(simulation, view_gen, names)
        _change_event = st.dataframe(
            _change_rows,
            key="detail_change_rows",
            on_select="rerun",
            selection_mode="single-row",
            width="stretch",
            hide_index=True,
        )
        _sync_detail_from_selection(_change_event, _change_rows, "detail_changes")

    st.subheader("对局与适应度")
    fitness_block = st.container()
    heatmap_block = st.container()
    if _mobile():
        # A 1:2 split leaves the heatmap -- the denser, harder-to-read chart --
        # with a third of a phone's width. Stack them at full width instead.
        fitness_target, heatmap_target = fitness_block, heatmap_block
    else:
        fitness_col, heatmap_col = st.columns([1, 2])
        fitness_target, heatmap_target = fitness_col, heatmap_col

    with fitness_target:
        if pin == "fitness":
            st.caption("该模块已锁定到页面上方。")
        else:
            _fitness_rows = build_fitness_rows(simulation, view_gen, names)
            _fitness_event = st.dataframe(
                _fitness_rows,
                key="detail_fitness_rows",
                on_select="rerun",
                selection_mode="single-row",
                width="stretch",
                hide_index=True,
                height=320,
            )
            _sync_detail_from_selection(_fitness_event, _fitness_rows, "detail_fitness")
    with heatmap_target:
        if pin == "heatmap":
            st.caption("该模块已锁定到页面上方。")
        else:
            render_heatmap(simulation, view_gen, names)

    with st.expander("演化全景（面积图 / 演化树）", expanded=False):
        st.caption(
            "◇ 亚种生成　★ 独立为新物种　× 灭绝/亚种淘汰；"
            "标注框可拖动，拖动后箭头仍指向对应位置。"
        )
        area = build_population_area(simulation, names)
        area.add_vline(x=view_gen, line_color=theme.INK, line_width=2)
        # Dragging annotations needs the mode bar, which a phone has no room
        # for; keep the chart editable on desktop and read-only on mobile.
        area_config = {
            "editable": True,
            "edits": {"annotationPosition": False, "annotationTail": True},
            "displayModeBar": True,
        }
        if _mobile():
            area_config = {"editable": False, "displayModeBar": False, "scrollZoom": True}
        st.plotly_chart(area, width="stretch", config=area_config)
        st.plotly_chart(
            build_evolution_tree(simulation, names), width="stretch",
            config=_chart_config(),
        )

    with st.expander("统一存档（AI 可直接读取 / 可复现）", expanded=False):
        st.caption(
            "**只有一种保存方式**：写入 `archive/runs/*.tev.json`。"
            "该文件同时满足分析与复现——内含格式版本、引擎版本、规则、策略编码词典、"
            "预派生分析视图，以及可回放状态（含 RNG 与手动注入序列）。"
            "面板上的图表与下方预览都是从同一份数据渲染的视图，不存在第二份数据，"
            "因此不会与 AI 读到的内容脱节。"
            f"　当前引擎 {ENGINE_VERSION}，格式 {RUN_SCHEMA_VERSION}。"
        )

        run_name = st.text_input(
            "存档名称", value="run", key="archive_name",
            help="会成为文件名前缀，便于在 archive/runs/ 中辨认。",
        )
        run_note = st.text_input("备注（可选）", key="archive_note")

        cache_key = (id(simulation), simulation.generation)
        if st.session_state.get("export_cache_key") != cache_key:
            bundle = build_export_bundle(
                simulation,
                seed=st.session_state.get("seed"),
                name=run_name or "run",
                note=run_note or None,
                initial_encodings=st.session_state.get("init_encodings"),
                initial_sizes=st.session_state.get("init_sizes"),
            )
            st.session_state["export_cache_key"] = cache_key
            st.session_state["export_doc"] = bundle
            st.session_state["export_md"] = bundle_to_markdown(bundle)

        # Saving is the only action here: the run is already in session state, so
        # 大模型解读这场演化 reads it in place. Exporting a file and submitting it
        # by hand would be a second way to reach the same report.
        if st.button("💾 保存统一存档", width="stretch", type="primary"):
            saved = save_markdown_report(
                simulation, st.session_state.get("seed"),
                simulation.generation,
                name=run_name or "run",
                note=run_note or None,
            )
            st.success(f"已保存：{saved.name}")
            st.caption(
                f"位置 {saved}　引擎 {ENGINE_VERSION}。"
                "这个文件也可以直接分享——对方上传即可复现。"
            )

        # The preview comes from the bundle built above, not from a file that was
        # written and read back -- one source, so the panel and the preview
        # cannot drift apart.
        if st.toggle("预览 Markdown 视图"):
            st.markdown(st.session_state["export_md"])

    render_strategy_detail_float(
        simulation, names, st.session_state.get("detail_selected"),
        st.session_state.get("view_gen", 0),
    )


MODE_CREATION = "creation"
MODE_GAME = "game"

# Order is the argument: a first-time visitor should take the game mode, so it
# leads the row and is the only one whose button is filled.
LANDING_MODES = [
    {
        "mode": MODE_GAME,
        "slot": "tf_mode_play",
        "icon": "play",
        "title": "游戏模式",
        "subtitle": "与策略对局，然后看懂自己的选择",
        "bullets": [
            "五轮教学对局先把规则走一遍，随时可跳过",
            "与 10 个行为各异的随机策略各战 10 轮，每步自己决定合作或背叛",
            "结束后拿到 11×11 得分热力图、九项维度得分与逐步解读报告",
        ],
        "tags": ["约 8 分钟", "无需配置", "含解读报告"],
        "badge": "推荐先玩",
        "cta": "进入游戏模式",
    },
    {
        "mode": MODE_CREATION,
        "slot": "tf_mode_lab",
        "icon": "lab",
        "title": "创造模式",
        "subtitle": "演化模拟工作台",
        "bullets": [
            "配置初始种群与策略组合，逐轮推进演化",
            "观察种群数量与适应度变化、策略热力图与谱系分析",
            "整次运行保存为 AI 可直接读取的统一存档",
        ],
        "tags": ["沙盒", "谱系分析", "统一存档 v{}".format(RUN_SCHEMA_VERSION)],
        "badge": "",
        "cta": "进入创造模式",
    },
]


def _enter_mode(mode: str) -> None:
    st.session_state["app_mode"] = mode
    st.rerun()


#: 教师端那一屏的就地解释。和 GAME_HELP 一样：写下的每一句都能在屏幕上找到对应
#: 的东西，尤其不能写成"我们已经做过课堂试点"。
BOARD_HELP = [
    ("这一屏是给谁的",
     "给带一次课的老师：一个班打完之后，在这里看有多少份提交、打完的有几份、"
     "同一套题面前谁高谁低。学生那一侧看不到别人的加入码，只看到自己的名次。"),
    ("为什么只有加入码",
     "这张表里没有姓名、没有账号、也没有任何能指认到人的列。加入码是一个随机 8 字符，"
     "它同时是学生取回自己报告的唯一凭据。要把码对回人，只能老师在纸面上自己记。"),
    ("榜单是怎么算出来的",
     "库里存的只有设置和每一步决策。每一份提交都在这里按同一套对手、同一颗子重放一遍，"
     "分数是当场算的——所以榜上不会出现一个和决策脱节的存档数字。"),
    ("只有同一挑战码才放在一起排",
     "换一套对手就是换一道题。自由打的局没有共同题面，不进榜；把它们和某套题的提交排在"
     "一张表里，排的是运气。"),
    ("「参照」那几行是什么",
     "S0（永远合作）、SM（永远背叛）、R1-1（以牙还牙）等标准策略，在同一串对手、同一个"
     "轮数、同一份种子下打出的总分。它们不是标准答案，只是一条对照线：同一套题面上，"
     "换个打法能拿多少。"),
    ("看不到任何东西时",
     "免费版每次重新部署都会清空存档文件。学生提交还在的话，先导出两份 CSV（名单 + 挑战表）"
     "再重新部署，然后原样导入——加入码不变，学生照常凭码回来。"),
]

#: 全班参照线里在榜单上露面的条数：太多会把学生的名次挤出视野。
BOARD_BASELINES = 4


def _task_link(challenge_id: str) -> str:
    """把挑战码带在地址栏里的完整链接。

    学生点开这个链接就已经锁好题面，不需要自己输码；地址取本站当前的外部 URL，
    读不到就退回相对形式（同一个部署下仍然有效）。
    """
    try:
        base = (st.context.external_url or "").split("?")[0]
    except Exception:  # noqa: BLE001 - context 在少数嵌入环境下不可用
        base = ""
    tail = "{}={}".format(GAME_TASK_PARAM, challenge_id)
    return "{}?{}".format(base, tail) if base else tail


def _rank_table(board: dict) -> list[dict]:
    """Submissions and reference lines in one score-ordered table.

    名次用的是并列名次（同分同名，下一名跳号）：全班用同一套策略时应该读成"并列"，
    而不是被任意地排出先后。
    """
    scored = [
        (row["score"], "第 {} 名".format(
            sum(1 for other in board["rows"] if other["score"] > row["score"]) + 1),
         row["join_code"], row["updated_at"])
        for row in board["rows"]
    ]
    for line in board["baselines"][:BOARD_BASELINES]:
        scored.append((
            line["score"],
            "第 {} 名".format(line["above"] + 1),
            "参照 · {}（{}）".format(line["label"], line["code"]),
            "",
        ))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        {"名次": place, "提交": who, "总分": "{:g}".format(score),
         "更新时间": stamp or "—"}
        for score, place, who, stamp in scored
    ]


def _render_board_summary(runs: list[dict]) -> None:
    """这个班现在打到哪儿了：份数、打完的、还在打的、一共走了多少步。

    只数提交和决策步数——这两个数决定了榜能不能算、一节课够不够打完，而且它们不需要
    重放，所以这一排数字是即时的。
    """
    playing = sum(1 for run in runs if run["status"] == "playing")
    steps = sum(sum(len(a) for a in run["actions"]) for run in runs)
    guessed = sum(
        sum(1 for mark in part if mark in ("C", "D"))
        for run in runs for part in run.get("predictions", [])
    )
    count_col, done_col, live_col, step_col = st.columns(4)
    count_col.metric("提交份数", len(runs))
    done_col.metric("已打完", len(runs) - playing)
    live_col.metric("进行中", playing)
    step_col.metric(
        "决策步数", steps,
        help="全部提交里已经落子的轮数总和。开了「每轮先猜对手出什么」的那些轮，"
             "另有 {} 次猜测记录。".format(guessed) if guessed else
             "全部提交里已经落子的轮数总和。",
    )


def _render_challenge_board(runs: list[dict]) -> None:
    """Per-challenge standings for the filtered set of runs."""
    groups: dict[str, list[dict]] = {}
    for run in runs:
        if run["challenge_id"]:
            groups.setdefault(run["challenge_id"], []).append(run)
    if not groups:
        st.caption(
            "这批提交里没有挑战局的记录。自由打的局各用各的对手集合，没有共同分母，"
            "所以不进榜——要排名，先在下面发一份挑战出去。")
        return
    for task_id, group in groups.items():
        challenge = _resolve_challenge(task_id)
        st.markdown("**挑战 {}**　{} 份提交".format(
            task_id, len(group)))
        if challenge is None:
            st.caption(
                "这份挑战的题面不在这里（可能是另一个实例自建的，或已被删除），"
                "无法重放评分。导入挑战表 CSV 就能恢复它。")
            continue
        try:
            board = challenges.ranking(challenge, group)
        except (sqlite3.Error, OSError, ValueError) as error:
            st.warning("这一份算不出来：{}".format(error))
            continue
        if not board["rows"]:
            st.caption("这个挑战下还没有一份打完的提交——上面那几行是参照线本身。")
        st.dataframe(_rank_table(board), width="stretch", hide_index=True)
        st.caption(
            "题面：{} 局 × 每局 {} 轮 = {} 步，种子 {}。全部提交都在同一套对手上重放算出。".format(
                len(challenge["codes"]), challenge["turns"],
                challenges.steps(challenge), challenge["seed"]))


def _render_issue_desk() -> None:
    """下发：预置挑战的链接，和老师自己编的一份挑战。"""
    st.markdown("**下发一份挑战**")
    for preset in challenges.PRESETS:
        name_col, link_col = st.columns([4, 6], gap="small")
        with name_col:
            st.markdown(
                "<div style='padding:.2rem 0'><b>{}</b>"
                "<div style='font-size:.78rem;color:{}'>{}</div></div>".format(
                    preset["title"], theme.FAINT,
                    "{} 局 × {} 轮".format(
                        len(preset["codes"]), preset["turns"])),
                unsafe_allow_html=True,
            )
        with link_col:
            st.text_input(
                "链接", value=_task_link(preset["challenge_id"]),
                key="link_{}".format(preset["challenge_id"]),
                label_visibility="collapsed",
                help="发给学生点开就已经锁好题面。挑战码 {}。".format(
                    preset["challenge_id"]),
            )

    with st.expander("自己编一份题面", expanded=False):
        st.caption(
            "一行一个对手编码（本站的写法，例如 R1-1、S0+R1-1、BS2）。"
            "编码会先解析一遍再存：读不通的题面不会半成品地上线——"
            "两班拿到同一标题却不同的对手集合，比报错更难查。")
        own_title = st.text_input("标题", placeholder="例如 我们班的第三课", key="own_title")
        own_codes = st.text_area(
            "对手编码", placeholder="R1-1\nS0\nBS2\nC1", key="own_codes", height=140)
        own_note = st.text_input(
            "简介（学生开局前看得到）",
            placeholder="这一套对手的行为倾向……", key="own_note", max_chars=120)
        turns_col, seed_col = st.columns(2)
        with turns_col:
            own_turns = st.slider("每局轮数", 5, 20, 8, key="own_turns")
        with seed_col:
            own_seed = st.number_input(
                "随机种子", value=20261017, step=1, key="own_seed",
                help="同一份种子 + 同一串编码 = 全班同一道题。")
        own_class = st.text_input("班级码（可留空）", key="own_class", max_chars=24)
        if st.button("保存这份挑战", type="primary", width="stretch"):
            try:
                codes = challenges.validate_codes(own_codes)
                challenge = {
                    "challenge_id": challenges.new_challenge_id(),
                    "title": own_title.strip()[:40] or "未命名挑战",
                    "class_code": own_class.strip()[:24],
                    "codes": codes,
                    "turns": int(own_turns),
                    "seed": int(own_seed),
                    "note": own_note.strip()[:120],
                }
                store.create_challenge(challenge)
            except (ValueError, sqlite3.Error, OSError) as error:
                st.error("没能保存：{}".format(error))
            else:
                st.session_state["own_created"] = challenge
                st.rerun()

        made = st.session_state.get("own_created")
        if made:
            st.success("已保存：{}（挑战码 {}）".format(
                made["title"], made["challenge_id"]))
            st.text_input(
                "链接", value=_task_link(made["challenge_id"]),
                key="link_new", label_visibility="collapsed")

        try:
            saved = store.list_challenges()
        except (sqlite3.Error, OSError) as error:
            st.warning("自建挑战读不出来：{}".format(error))
            saved = []
        if saved:
            st.markdown("**已自建的{}份**".format(len(saved)))
            for item in saved:
                row_a, row_b = st.columns([5, 7], gap="small")
                with row_a:
                    st.markdown(
                        "<div style='padding:.2rem 0'><b>{}</b>"
                        "<div style='font-size:.78rem;color:{}'>{} · {} 局 × {} 轮 · 种子 {}{}</div></div>".format(
                            item["title"], theme.FAINT, item["challenge_id"],
                            len(item["codes"]), item["turns"], item["seed"],
                            "　" + item["class_code"] if item["class_code"] else ""),
                        unsafe_allow_html=True,
                    )
                with row_b:
                    st.text_input(
                        "链接", value=_task_link(item["challenge_id"]),
                        key="link_saved_{}".format(item["challenge_id"]),
                        label_visibility="collapsed")


def _render_roster_panel() -> None:
    """名单导出 / 导入——免费版文件系统是临时的，这条路径是唯一的兜底。

    需要 ``TEACHER_GATE`` 才展开。名单里每一行都是一个学生取回自己报告的唯一凭据，
    而访问密码是全班共用的：不加这道门，任何一个同学都能在这里看到（并逐个输入）
    所有人的加入码。没配教师码时整块数据都不渲染，而不是"默认给大家看"。

    刻意不做账号体系，也不在这张表里放任何能指认到人的列：导出的 CSV 只有加入码、
    班级码、设置和决策串。九项测量和比分不落库，收到 CSV 的人重新算即可，所以这份
    文件既是备份，也不会变成一份"看起来像心理档案"的数据。
    """
    gate = _configured_secret("TEACHER_GATE")
    with st.expander("教师端：整批名单导出与恢复", expanded=False):
        if not gate:
            st.caption(
                "未配置教师码（Secrets 或环境变量 ``TEACHER_GATE``），名单默认不公开。"
                "加入码是学生取回自己报告的唯一凭据，而访问密码全班共用，所以这一屏"
                "单独设一道门。"
            )
            return
        if st.session_state.get("teacher_unlocked") is not True:
            code_col, button_col = st.columns([3, 1], vertical_alignment="bottom")
            with code_col:
                typed = st.text_input(
                    "教师码", type="password", key="teacher_gate_input",
                    label_visibility="collapsed", placeholder="教师码",
                )
            with button_col:
                if st.button("解锁", key="teacher_gate_btn", width="stretch"):
                    if typed == gate:
                        st.session_state["teacher_unlocked"] = True
                        st.rerun()
                    else:
                        st.error("教师码不对")
            return

        st.markdown(
            theme.heading(
                "教师端：班级看板与名单", 3,
                help_blocks=BOARD_HELP, help_label="这一屏怎么用",
            ),
            unsafe_allow_html=True,
        )
        _render_issue_desk()

        try:
            runs = store.list_runs()
        except (sqlite3.Error, OSError) as error:
            st.warning("名单库暂时读不出来：{}".format(error))
            return

        if not runs:
            st.caption("名单库还是空的。学生开始一局后这里就会有记录。")
        else:
            classes = sorted({run["class_code"] for run in runs if run["class_code"]})
            picked = st.selectbox(
                "班级码", ["全部班级"] + classes, key="board_class",
                help="只筛选，不改变任何数据。没有填班级码的提交在「全部班级」下看。")
            shown = [
                run for run in runs
                if picked == "全部班级" or run["class_code"] == picked
            ]
            _render_board_summary(shown)
            _render_challenge_board(shown)
            with st.expander("逐份提交（加入码原样列出）", expanded=False):
                st.caption(
                    "这一张表里只有码、题面参数和决策串。九项测量与比分都不在库里，"
                    "拿到这行数据的人要重算才有——所以它不是一份档案。")
                st.dataframe(
                    [
                        {
                            "加入码": run["join_code"],
                            "班级码": run["class_code"] or "—",
                            "挑战码": run["challenge_id"] or "—",
                            "状态": "已完成" if run["status"] == "finished" else "进行中",
                            "局数": run["count"],
                            "每局轮数": run["turns"],
                            "已打决策": sum(len(a) for a in run["actions"]),
                            "更新时间": run["updated_at"],
                        }
                        for run in shown
                    ],
                    width="stretch", hide_index=True,
                )

        out_col, in_col = st.columns(2)
        with out_col:
            st.download_button(
                "⬇ 导出名单 CSV",
                data=store.export_csv(),
                file_name="fittest-roster.csv",
                mime="text/csv",
                width="stretch",
                disabled=not runs,
                help="UTF-8 带 BOM，Excel 直接打开不乱码。",
            )
        with in_col:
            upload = st.file_uploader("上传此前导出的 CSV", type="csv", key="roster_csv")
            if upload is not None and st.button("恢复这批名单", key="roster_import"):
                try:
                    count = store.import_csv(upload.getvalue())
                except (ValueError, sqlite3.Error, OSError) as error:
                    st.error("导入失败：{}".format(error))
                else:
                    st.success(
                        "已恢复 {} 条记录。加入码不变，学生照常凭码回来。".format(count))

        # 两张表要一起备份：名单里的 challenge_id 指的是挑战表里的题面，只导一份的话
        # 恢复回来的提交会挂在一份不存在的题面上，榜算不出来，而页面看不出为什么。
        task_out, task_in = st.columns(2)
        with task_out:
            try:
                payload = store.export_challenges_csv()
                problem = ""
            except (sqlite3.Error, OSError) as error:
                payload = b""
                problem = str(error)
            st.download_button(
                "⬇ 导出挑战表 CSV",
                data=payload,
                file_name="fittest-challenges.csv",
                mime="text/csv",
                width="stretch",
                disabled=not payload,
                help=problem or "老师和预置之外的自建题面都在这里。",
            )
        with task_in:
            task_upload = st.file_uploader(
                "上传此前导出的挑战表 CSV", type="csv", key="challenge_csv")
            if task_upload is not None and st.button("恢复这批挑战", key="challenge_import"):
                try:
                    saved = store.import_challenges_csv(task_upload.getvalue())
                except (ValueError, sqlite3.Error, OSError) as error:
                    st.error("导入失败：{}".format(error))
                else:
                    st.success(
                        "已恢复 {} 份题面。学生手里的挑战码重新可用，榜单也能重放了。".format(saved))


def render_mode_select() -> None:
    """Entry screen: what this site is, then which way in."""
    st.markdown(SPLASH_CSS, unsafe_allow_html=True)
    st.markdown(
        theme.landing_hero(
            "Iterated Prisoner&rsquo;s Dilemma · 演化模拟",
            "The Fittest",
            "十个策略，一个席位池：谁能在背叛与合作之间活下来",
            "每个策略都是一个物种，在重复囚徒困境中与另外十个物种竞争席位。"
            "<b>适者不是最狠的那个，而是活得最久的那个。</b>",
            "第一次来？30 秒看懂这个网站在做什么",
            "tf_about",
        ),
        unsafe_allow_html=True,
    )

    # A button cannot be nested inside the hero markup, so this row copies the
    # hero's own column split and lands the two CTAs under the lede.
    lead, _art = st.columns([1.05, 0.95], gap="large")
    with lead:
        play_cta, lab_cta = st.columns(2, gap="small")
        # Each button sits in its own keyed container: the entry styling in
        # theme.py is scoped to those keys so it cannot leak onto every other
        # button in the app.
        with play_cta, play_cta.container(key="tf_cta_play"):
            if st.button(
                "→ 开始一局（约 8 分钟）", key="landing_play", type="primary", width="content"
            ):
                _enter_mode(MODE_GAME)
        with lab_cta, lab_cta.container(key="tf_cta_lab"):
            if st.button("打开演化工作台", key="landing_lab", width="content"):
                _enter_mode(MODE_CREATION)

    st.markdown(
        theme.payoff_chips(help_html=theme.help_chip(
            GAME_HELP["payoff"], label="这些数字怎么读",
        )),
        unsafe_allow_html=True,
    )

    st.markdown('<div id="tf_about"></div>', unsafe_allow_html=True)
    # Three collapsible blocks instead of three screens of prose. The heading
    # stays on the page so a reader can see what is behind each click, and the
    # body waits inside a ``<details>`` -- which opens without a server rerun,
    # unlike an expander widget. 选择模式 below is deliberately *not* folded: it
    # carries the two entry buttons, and hiding the way in to save scroll would
    # be a bad trade.
    st.markdown(
        theme.fold(
            "这个网站在做什么",
            theme.prose_card(LANDING_WHY) + theme.architecture(LANDING_ARCH),
            hint="不点也能直接开始",
        ),
        unsafe_allow_html=True,
    )

    st.markdown(
        theme.fold(
            "怎么玩",
            theme.steps(LANDING_STEPS),
            hint="第一次建议从游戏模式开始，全程约 8 分钟",
        ),
        unsafe_allow_html=True,
    )

    st.markdown(
        theme.section("选择模式", "进入后可在侧栏随时切回"), unsafe_allow_html=True
    )
    for column, card in zip(st.columns(2), LANDING_MODES):
        with column, st.container(key=card["slot"]):
            st.markdown(
                theme.mode_card(
                    card["icon"],
                    card["title"],
                    card["subtitle"],
                    card["bullets"],
                    card["tags"],
                    badge=card["badge"],
                ),
                unsafe_allow_html=True,
            )
            if st.button(
                card["cta"],
                key="enter_{}".format(card["mode"]),
                width="stretch",
                type="primary" if card["mode"] == MODE_GAME else "secondary",
            ):
                _enter_mode(card["mode"])

    st.markdown(
        theme.fold(
            "看到这些词不用慌",
            theme.glossary(LANDING_GLOSS),
            hint="站内术语对照，30 秒扫一遍就够",
        ),
        unsafe_allow_html=True,
    )

    _render_roster_panel()

    st.divider()
    st.caption(
        "引擎 {}　存档格式 {}　进入后可在侧栏切回模式选择。".format(
            ENGINE_VERSION, RUN_SCHEMA_VERSION
        )
    )



GAME_SETUP_KEY = "game_setup"
GAME_CODES_KEY = "game_codes"
GAME_RUNNER_KEY = "game_runner"
GAME_MATCHES_KEY = "game_matches"
GAME_DONE_KEY = "game_done"
GAME_RESULTS_KEY = "game_results"
GAME_PROFILE_KEY = "game_profile"
GAME_AI_KEY = "game_ai_report"
#: AI 写的那张卡的结论与关键手。没有它时风格卡走本地计算的版本。
GAME_CARD_KEY = "game_card_verdict"
GAME_AI_OVERVIEW_KEY = "game_ai_overview"
GAME_TUTORIAL_KEY = "game_tutorial"
GAME_TUTORIAL_DONE = "game_tutorial_done"
TUTORIAL_RUNNER_KEY = "game_tutorial_runner"
#: 学生凭以回来继续的加入码。由 :mod:`dashboard.store` 分配，只存在这一处。
GAME_JOIN_KEY = "game_join_code"
#: 「用加入码继续」输入框。
RESUME_CODE_KEY = "resume_code"
#: 设置页上的班级码输入框。
CLASS_CODE_KEY = "class_code"
#: 名单库最近一次写入失败的原因，用于在界面上一句话说明，而不是让对局崩掉。
STORE_ERROR_KEY = "store_error"

#: URL 参数名，用来把对局进度带在地址栏里。
GAME_PARAM = "g"
#: 第二个参数：加入码。没有它的话，刷新一次就只剩 URL 能救这一局、名单库不再更新。
GAME_JOIN_PARAM = "gc"
#: 第三个参数：挑战码。老师下发的链接带着它，学生点开就已经锁好题面。
GAME_TASK_PARAM = "task"
_PAYLOAD_VERSION = "v1"
#: 挑战局的载荷只带决策——对手集合、轮数、种子都在挑战那一行里，重复一遍就会
#: 出现两处不一致。所以载荷版本号不同，恢复时也必须同时带 task。
_PAYLOAD_VERSION_TASK = "v2"
#: 当前这一局是不是在打某个挑战；存的是解析出来的挑战字典。
GAME_TASK_KEY = "game_challenge"
#: 「挑战码」输入框。
TASK_CODE_KEY = "task_code"
#: 可选练习：每轮先猜对手出什么。开关本身不进载荷，只跟着这一局走。
PREDICT_KEY = "game_predict"

#: 就地解释。每一段挂在它自己那个标题旁边，而不是攒成页顶的一篇说明文——
#: 读者是在读到某一屏时才产生疑问的，把答案放在别处等于没有答案。
#: 文案必须与代码实际行为一致：这里写的每一个数字、每一种颜色，都能在上面那屏找到。
GAME_HELP = {
    "setup": [
        ("这块在做什么",
         "开局前的三个选择：对手数量、每局轮数、随机种子。默认 10 局 × 10 轮，"
         "也就是 100 步由你自己做的决定。"),
        ("为什么要自己选",
         "局数少、轮数短，两分钟就能打完，但 20 步看不出什么模式；"
         "100 步是能看出倾向的最短路径。时间紧就调小，只是后面的分析会跟着变粗。"),
        ("随机种子是干什么的",
         "同一种子生成同一组对手。想和同学比同一套题、或想让评委复现你的结果，"
         "把种子报给对方就行——决策不同，结果才不同。"),
        ("学习目标",
         "先决定要从这段对局里读出什么，再决定局数与轮数：样本长度是测量的"
         "一部分，不是设置项。"),
    ],
    "tutorial": [
        ("这块在做什么",
         "五轮明牌练习：每轮结束直接告诉你各得几分，但不告诉你对手是谁。"),
        ("为什么要先明牌",
         "正式对局里你只能靠对手的行为去猜。教学先把「猜」这件事单独练五轮，"
         "你才有精力在正式局里做决策。"),
        ("可以直接跳过吗",
         "可以。规则就三行（都合作各 3、被背叛 0、都背叛各 1），"
         "跳过不影响任何结果，也不会记进你的成绩。"),
        ("学习目标",
         "把支付矩阵读成条件句——「若它合作我拿几分、若它背叛我拿几分」，"
         "并练一次在对手身份未知时按行为下注。"),
    ],
    "play": [
        ("这一排在说什么",
         "一格一局：绿色是你这局分高，橙色是分低，灰色是打平，蓝色是正在打的这局，"
         "浅米色还没开。右边那个数是跨局总得分。"),
        ("本轮第 N / M 轮",
         "本局的进度。分数只在每一轮双方都出完之后才结算，所以本轮的分还没算进去。"),
        ("按钮下面那两个数",
         "每个按钮下面写着两种情形各拿几分：「若对手合作 +3」「若对手背叛 +0」。"
         "高亮的那一条是它上一轮刚做过的那件事——所以按钮上的数字不是承诺，"
         "是一个条件句，赌的是它下一轮接着这么干。"),
        ("为什么不告诉你对手是谁",
         "正式局里对手身份要等这一局打完才揭晓。你先看到的只有它上一轮做了什么——"
         "按行为决策，别按名字决策。"),
        ("学习目标",
         "在信息不完整的前提下做决策，并在事后把行为对回规则：本局的对手身份"
         "打完才揭晓，揭晓后它会指出自己是在哪几轮按规则行动的。"),
    ],
    "results": [
        ("这张矩阵怎么读",
         "行是「本方」，列是「对方」，格子里是行方那一方的得分。"
         "有「你」的那一行是你对各策略的成绩，那一列是各策略对你的成绩，"
         "其余格子是策略彼此对局。空白＝这一对没交过手。"),
        ("颜色深浅",
         "由浅到深是得分由低到高，不是好与坏——这是分数矩阵，不是对错矩阵。"),
        ("上面三个数",
         "总局分是你全部局的总分；每局平均旁边那个差值，是它与「策略平均」的差距；"
         "策略平均是这些策略两两对局后的平均总分，只当参照线用。"),
        ("学习目标",
         "把自己的分数放进参照系里读：赢了几局是感受，与策略平均的差距才是"
         "位置。参照线不是标准答案，它只是这批策略彼此对局的平均水平。"),
    ],
    "average": [
        ("两列的差别",
         "「对其他策略」是该策略与其余策略对局的平均得分；"
         "「对你」是它在你手上拿到的平均得分。"),
        ("为什么要分开看",
         "一个策略可以打赢全场却在你这儿拿低分——那说明它克制的是别人，"
         "不是你的打法有问题。反过来也一样。"),
        ("背叛倾向",
         "它在全部对局里出背叛的比例，与它对你做了什么无关，是它整体的风格。"),
        ("学习目标",
         "同一策略在不同情境里的价值可以相反。判断一个打法好不好，先问它"
         "面对的是谁——这正是下面「逐局记录」和「行为分析」要分开看的原因。"),
    ],
    "matches": [
        ("蓝点橙点",
         "蓝点＝那一格出的是合作，橙点＝背叛。每一格里有两行：上面那行是你，"
         "下面那行是对手，同一列就是同一轮——所以同一列上下两个蓝点就是都合作。"),
        ("这一列没有颜色，只有数字",
         "得分那格里粗体是你的分，灰色是对手的分；「互相合作轮数」是双方都出合作"
         "的轮数，也就是各拿 3 分的那些轮。"),
        ("想看逐轮明细",
         "逐轮表在每一局结束的那一刻就出现在屏幕上；这一屏只给形状。"
         "具体轮次还会在「行为分析」每一项的证据里被点名。"),
        ("学习目标",
         "从十行的形状里读出自己的转折点：哪一轮你开始还手、哪一轮开始收手，"
         "比记住任何一局的胜负更重要。"),
    ],
    "profile": [
        ("这些数字是什么",
         "全部来自对你这 100 步决策的确定性计算：本地算的，不经过大模型。"
         "每一项都附具体场次轮次的证据，并写明什么观察能推翻它。"),
        ("这些数字不是什么",
         "不是心理诊断，也不给人格类型。「出牌风格」只是这些测量的归纳说法，"
         "描述你在这几局里怎么出牌，换个种子就可能换个说法。"),
        ("想看得更准怎么办",
         "单次 100 步够看出倾向，不够看出稳定。要比稳定性，就换种子多打几局，"
         "或者把轮数调长。"),
        ("学习目标",
         "读一个测量报告该有的样子：先看它凭什么数字算出来，再看它自己写的"
         "「何种观察可推翻」。做不到这两步，就不算读懂了它。"),
    ],
    "dimensions": [
        ("先看哪一层",
         "上面那张图是九项归到同一 0-100 刻度后的整体位置，先在这儿找哪一项偏离最多；"
         "下面的卡片才是单项。"),
        ("每项方向不同",
         "「回击倾向」高＝被背叛必还手；「单步收益效率」高＝不浪费机会；"
         "「主动剥削」高＝对方合作时你也出手。高低本身不判好坏，"
         "要看你面对的是什么对手。"),
        ("依据在哪",
         "每张卡片标题旁的 ⓘ 里写着该维度的定义、方向和实际测量口径，"
         "数字怎么来的都在那儿。"),
        ("学习目标",
         "九个方向不同的指标放在同一刻度上时，比较的是「位置」不是「好坏」。"
         "真正的判断要回到你在哪几轮做了什么。"),
    ],
    "payoff": [
        ("这三行数字是什么",
         "一轮里只会发生三种结果：双方都合作，各拿 3 分；一方背叛，背叛的一方拿 5 分、"
         "另一方 0 分；双方都背叛，各拿 1 分。蓝点代表合作，橙点代表背叛。"),
        ("为什么每一轮背叛都更划算",
         "对手合作时，背叛比合作多得 2 分（5 而不是 3）；对手背叛时，背叛比合作少亏 1 分"
         "（1 而不是 0）。只看一轮的话，背叛在任何情形下都不比合作差——这不是设计失误，"
         "这正是囚徒困境的定义。"),
        ("那为什么还有人一直合作",
         "因为一局不止一轮：对手会根据你上一轮做了什么来调整它下一轮的动作。这一轮少拿的"
         "2 分，如果换来它此后连续几轮都合作，总分反而更高。谁在什么条件下划得来，"
         "就是这个网站要测的东西。"),
        ("学习目标",
         "把这三行读成条件句而不是三个数字：先说出「若它这轮合作我拿几分、若它背叛我拿几"
         "分」，再决定自己出什么。说不出条件句的时候，先别急着点按钮。"),
    ],
    "prediction": [
        ("这一屏在说什么",
         "开了「每轮先猜对手出什么」之后，每一轮你先选一次「它这轮出合作还是背叛」，"
         "再决定你自己出什么。这里只算猜中的比例，与你得几分、你出的是哪一手都无关。"),
        ("为什么要单独量这一项",
         "打得好和看得准是两件事。有人一路背叛也能拿高分，因为对手恰好不还手；"
         "有人把对手猜得很准，却仍然选择背叛。把猜测单独记下来，才知道自己缺的是判断"
         "还是决断。"),
        ("猜不准说明什么",
         "只说明一件事：那个对手的行为里有你还没识别出来的规则，或者它本身带噪声"
         "（带神经质、心狠、失忆这类修正槽的策略，行为里真的有随机数）。两者都不说明"
         "别的什么，也不是能力评价。"),
        ("和九项维度的关系",
         "九项维度量的是你做了什么；这一屏量的是你以为对手会做什么。一个是行为测量，"
         "一个是心智模型的准确度，刻意不合并。"),
        ("学习目标",
         "把你对对手的判断写成可以被推翻的预测——每一轮它就是一次检验。猜错的那些轮，"
         "去「已完成的局」里回看它当时按哪条规则出牌，比记住自己的错误更有用。"),
    ],
    "record": [
        ("「另一手」那一列在说什么",
         "同一局面下，如果你出的是另一手，本轮能拿几分、比这一手多还是少。"
         "它是引擎当场结算的分支，不是事后补的说法。"),
        ("「若改选，它下轮出 X」",
         "引擎把对手这一轮出牌前的状态复制一份，先让它把这轮的牌出完，再问它"
         "下一轮怎么回答你没出的那一手。只有两条分支的答案不一样时才写这一行。"),
        ("为什么要分开看",
         "当场少拿 2 分却让对手下一轮转回合作，和当场少拿 2 分却什么都没换来，"
         "是两个完全不同的决定。这张表把它们分开。"),
        ("学习目标",
         "用一个决定在另一条分支上的代价来衡量它：把「我选错了」换成"
         "「我为了什么放弃了什么」。"),
    ],
    "rank": [
        ("这一屏是给谁的",
         "只在打了老师下发的挑战时出现。同一份题面（同一串对手、同一个轮数、同一份种子）"
         "下的提交才放在一起排，排的是选择，不是运气。"),
        ("看得到别人什么",
         "只有总分和一个随机加入码。看不到别人的姓名、九项测量或任何一局的决策。"),
        ("名次为什么会有并列",
         "同分算同一名次，下一名跳号。两个班用同一套打法打出同一个分，就该读成并列。"),
        ("下面那几行参照线",
         "永远合作、永远背叛、以牙还牙这些标准策略在这套题面上的总分。它们不是答案，"
         "是对照：同一套对手里，换一种打法能拿多少分。"),
        ("学习目标",
         "先找到自己的名次与中位分的差距，再去参照线里找打得更高的那一行，"
         "然后说出它和你差在哪一条规则上——而不是「我这次运气不好」。"),
    ],
    "task": [
        ("这一屏和平时有什么不同",
         "题面是老师锁定的：对手编码、每局轮数、种子都不再可调。全班打的是同一套题，"
         "所以成绩可以放在一起排。"),
        ("为什么不能自己调",
         "对手集合一定，分数才有共同的分母。换一套对手就是换一道题，把两次的分放在"
         "一张榜上排，排的是运气而不是选择。"),
        ("打完会多出什么",
         "成绩页会多一块「这张挑战卷」：你在这批提交里的名次、这批提交的中位数与"
         "四分位，以及几个标准策略在同一套对手上拿到的分。"),
        ("学习目标",
         "把自己的分放进同一套题的参照系里看——既与同学比，也与标准策略比。"),
    ],
    "rank": [
        ("名次是怎么算的",
         "只统计这份挑战码下的提交。每一份都由存下来的决策重放算分——引擎是"
         "确定性的，所以榜单和你当时屏幕上看到的总分必然一致。没打完的不计入。"),
        ("为什么有并列",
         "同分共享一个名次，下一个名次要跳过。这批人做的是同样的选择，硬排先后"
         "只是在制造噪音。"),
        ("标准策略那一栏",
         "它们是同一套对手、同一份种子下的自动对局，不是给你的答案。看的是"
         "「第一名换人」这件事：同一套打法换一批对手，可能从最好变成最差。"),
        ("这张榜里有什么、没有什么",
         "只有随机加入码和分数——没有姓名，也没有任何能指认到人的东西。"
         "码与人对上，是老师在自己那份纸面上做的事。"),
        ("学习目标",
         "读一张有条件的榜：先问「这套题里第一是谁」，再问「换一套题他还第一吗」。"),
    ],
}


def _match_summary(finished) -> dict:
    """一局的摘要，供"已完成的局"列表用。

    ``_game_advance`` 和 URL 恢复共用它，这样重开恢复出来的一局和一路打下来的
    完全一样，不会出现两处字段漂移。
    """
    return {
        "局次": finished.index + 1,
        "对手": finished.opponent_label,
        "编码": finished.opponent,
        "你": int(finished.player_score),
        "对手分": int(finished.opponent_score),
        "记录": finished.player_actions + "/" + finished.opponent_actions,
        # The whole Match, so the per-turn record stays available: the flat
        # "CDDC/CCDD" string above can rebuild the scoreboard but not the
        # decisions that produced it.
        "match": finished,
    }


def _played_actions() -> list[str]:
    """玩家自己的决策，每局一段，最后一段可能还没打完。

    URL 恢复和 SQLite 名单存的是同一份东西——两者都只是重放的种子，比分和
    九项测量一律重新算出来。分开写就会出现"地址栏里那局和数据库里那局不是
    同一局"这种查无可查的分歧。
    """
    acts = [m.player_actions for m in (st.session_state.get(GAME_MATCHES_KEY) or [])]
    runner = st.session_state.get(GAME_RUNNER_KEY)
    if runner is not None:
        acts.append("".join(decision.action for decision in runner.decisions))
    return acts


def _played_predictions() -> list[str]:
    """玩家每一轮的猜测，每局一段，与 :func:`_played_actions` 逐位对齐。

    没猜的那些轮记成 ``-``，而不是干脆跳过——否则第 3 局的一次猜测会落进第 2 局
    的位置上。整段为空表示这一局根本没开预测。
    """
    def pad(turns: int, given: str) -> str:
        return (given + "-" * turns)[:turns]

    preds = [
        pad(len(match.player_actions), match.predictions)
        for match in (st.session_state.get(GAME_MATCHES_KEY) or [])
    ]
    runner = st.session_state.get(GAME_RUNNER_KEY)
    if runner is not None:
        played = "".join(decision.action for decision in runner.decisions)
        preds.append(pad(len(played), "".join(runner.prediction_history)))
    return preds


def _game_payload() -> str | None:
    """把整局编码成 ``v1.对手数.轮数.种子.各局决策``；挑战局是 ``v2.各局决策``。

    种子决定对手组合，引擎又是确定性的——实测同种子 + 同决策重放，对手行为、
    双方得分、profile 全部一致。所以只需要存**玩家自己的决策**：URL 长度控制在
    一两百字符，却能让进度扛过刷新、新标签页，以及中途切走再回来。
    """
    setup = st.session_state.get(GAME_SETUP_KEY)
    codes = st.session_state.get(GAME_CODES_KEY)
    if not setup or not codes:
        return None
    challenge = st.session_state.get(GAME_TASK_KEY)
    if challenge:
        # 题面在挑战那一行里，URL 只需要说"打到第几步"。把 count/turns/seed 再抄
        # 一遍就会出现地址栏和题面不一致的那类 bug。
        return ".".join([_PAYLOAD_VERSION_TASK] + _played_actions())
    return ".".join(
        [_PAYLOAD_VERSION, str(setup["count"]), str(setup["turns"]), str(setup["seed"])]
        + _played_actions()
    )


def _replay_run(count: int, turns: int, seed: int, acts: list[str], *,
                join_code: str | None = None,
                challenge: dict | None = None,
                predictions: list[str] | None = None) -> None:
    """从"设置 + 玩家决策"重放出一局，填好 session_state。

    地址栏恢复和加入码恢复共用它：确定性的引擎意味着只要喂回同样的种子和同样
    的决策，重放出来的对手、比分与九项测量必然和原局一致——所以存的从来不是
    报告，而是产生报告的那几步选择。

    ``challenge`` 是挑战局的情形：对手集合由挑战给定（不再是种子的函数），所以
    载荷里只留决策。计数以挑战为准，避免"题面 6 个对手、榜上按 10 个算"。
    """
    if challenge is not None:
        codes = list(challenge["codes"])
        count, turns, seed = len(codes), challenge["turns"], challenge["seed"]
    else:
        codes = draw_opponents(count, seed)
    matches: list = []
    done: list = []
    runner = None
    for index, code in enumerate(codes):
        match_runner = PlayerMatchRunner(
            index=index, opponent=code, turns=turns, seed=seed + 1 + index
        )
        given = predictions[index] if predictions and index < len(predictions) else ""
        # ``play`` reads the pending guess and clears it, so restoring means
        # re-offering each turn's guess one step ahead of the action it belonged
        # to. A "-" (or a missing character) is simply "this turn was not guessed".
        for step, action in enumerate(acts[index] if index < len(acts) else ""):
            if match_runner.finished:
                break
            guess = given[step] if step < len(given) else "-"
            match_runner.set_prediction(
                guess if guess in ("C", "D") else None)
            match_runner.play(action)
        if match_runner.finished:
            finished = match_runner.finish()
            matches.append(finished)
            done.append(_match_summary(finished))
        else:
            # 这一局还没打完：恢复成正在进行的对局。
            runner = match_runner
            break

    st.session_state[GAME_SETUP_KEY] = {
        "count": count, "turns": turns, "seed": seed,
        # 猜牌那一屏要不要出来，跟着"这一局有没有留下猜测"走：库里那段串存在，
        # 说明学生开过这个开关，刷新之后不该莫名其妙关掉它。
        "predict": bool(predictions),
    }
    st.session_state[GAME_TASK_KEY] = challenge
    st.session_state[GAME_CODES_KEY] = codes
    st.session_state[GAME_MATCHES_KEY] = matches
    st.session_state[GAME_DONE_KEY] = done
    st.session_state[GAME_RUNNER_KEY] = runner
    st.session_state["app_mode"] = MODE_GAME
    if join_code:
        st.session_state[GAME_JOIN_KEY] = join_code
    # 恢复出来的一局必然已经过了教学，否则每刷新一次都要重学一遍。
    st.session_state[GAME_TUTORIAL_DONE] = True

    if len(matches) >= len(codes):
        st.session_state["game_phase"] = "results"
        _game_finish()
    else:
        st.session_state["game_phase"] = "play"


def _resolve_challenge(task_id: str) -> dict | None:
    """挑战码 → 题面。先认代码里预置的那几张，再查老师自建的表。

    预置不入库，改预设就不必迁移数据；自建挑战只有一套编码和几个数字，里面没有
    任何能指认到人的东西。
    """
    code = store.normalize_code(task_id or "")
    if not code:
        return None
    preset = challenges.preset(code)
    if preset is not None:
        return preset
    try:
        return store.load_challenge(code)
    except (sqlite3.Error, OSError) as error:
        st.session_state[STORE_ERROR_KEY] = str(error)
        return None


def _ensure_join_row(join_code: str | None, *, count: int, turns: int,
                     seed: int, challenge_id: str = "") -> str | None:
    """地址栏里的加入码可能已经不在库里（免费版每次重新部署都清空文件）。

    这串码是那一局唯一的凭据，所以按 URL 自带的题面重新登记，之后的进度才有人
    接着收。登记失败就放弃这一路的持久化，但绝不打断重放——学生至少能把这局打完。
    """
    if not join_code:
        return None
    try:
        if store.load_run(join_code) is None:
            store.create_run(
                join_code, class_code="", opponent_count=count, turns=turns,
                seed=seed, engine_version=ENGINE_VERSION, tutorial_done=True,
                challenge_id=challenge_id,
            )
    except (sqlite3.Error, OSError) as error:
        st.session_state[STORE_ERROR_KEY] = str(error)
        return None
    return join_code


def _stored_predictions(join_code: str | None) -> list[str] | None:
    """地址栏恢复时，从名单库里补回这一局已经猜过的那些轮。

    ``?g=`` 里只有决策，没有猜测：那是刻意不动载荷格式，而不是漏了。所以刷新之后
    猜测还在不在，取决于加入码能不能在库里查到——查得到就照常回填，查不到也只是
    少了这一次练习，对局本身与比分不受影响。
    """
    if not join_code:
        return None
    try:
        run = store.load_run(join_code)
    except (sqlite3.Error, OSError):
        return None
    return run["predictions"] if run else None


def _restore_game_from_url() -> None:
    """把地址栏里带着的一局重放出来。

    没有这一步，刷新或重新打开浏览器就会回到设置页——玩家刚打完的十局连同成绩
    一起消失。这曾经是最难察觉的坑：数据看起来"没了"，而用户以为是自己的问题。
    """
    if st.session_state.get(GAME_SETUP_KEY):
        return
    payload = _query_value(GAME_PARAM)
    if not payload:
        return

    parts = payload.split(".")
    version = parts[0]

    if version == _PAYLOAD_VERSION_TASK:
        challenge = _resolve_challenge(_query_value(GAME_TASK_PARAM) or "")
        if challenge is None:
            # 挑战被删掉了：这一局的题面无从恢复，宁可回到设置页，也不把学生的
            # 决策重放到另一套对手上——那份报告看起来完全正常，却答的是别的题。
            st.error(
                "地址栏里的挑战码「{}」在这里查不到了，这一局没法接着打。"
                "请向老师要一份新的链接。".format(
                    _query_value(GAME_TASK_PARAM) or "（空）")
            )
            _clear_persisted_game()
            return
        join_code = _ensure_join_row(
            _query_value(GAME_JOIN_PARAM),
            count=len(challenge["codes"]), turns=challenge["turns"],
            seed=challenge["seed"],
            challenge_id=challenge["challenge_id"],
        )
        _replay_run(0, challenge["turns"], challenge["seed"], parts[1:],
                    join_code=join_code, challenge=challenge,
                    predictions=_stored_predictions(join_code))
        return

    if len(parts) < 4 or version != _PAYLOAD_VERSION:
        _clear_persisted_game()
        return
    try:
        count, turns, seed = int(parts[1]), int(parts[2]), int(parts[3])
    except ValueError:
        _clear_persisted_game()
        return

    join_code = _ensure_join_row(
        _query_value(GAME_JOIN_PARAM),
        count=count, turns=turns, seed=seed,
    )
    _replay_run(count, turns, seed, parts[4:], join_code=join_code,
                predictions=_stored_predictions(join_code))


def _persist_store() -> None:
    """把当前进度写进名单库。

    和 :func:`_persist_game` 在同一个位置调用，因此两条恢复路径的覆盖范围一致。
    每步决策后都会重跑，所以这里不需要单独找地方"另存"。
    """
    code = st.session_state.get(GAME_JOIN_KEY)
    setup = st.session_state.get(GAME_SETUP_KEY)
    codes = st.session_state.get(GAME_CODES_KEY)
    if not code or not setup or not codes:
        return
    matches = st.session_state.get(GAME_MATCHES_KEY) or []
    try:
        store.save_progress(
            code,
            actions=_played_actions(),
            predictions=_played_predictions(),
            tutorial_done=bool(st.session_state.get(GAME_TUTORIAL_DONE)),
            status="finished" if len(matches) >= len(codes) else "playing",
        )
    except (sqlite3.Error, OSError) as error:
        # 写不进库不能打断对局：进度还在地址栏里，学生至少能打完这一轮。
        st.session_state[STORE_ERROR_KEY] = str(error)


def _query_value(key: str) -> str | None:
    """``st.query_params`` 对重复键会返回列表，这里统一取单个字符串。"""
    value = st.query_params.get(key)
    if isinstance(value, list):
        value = value[0] if value else None
    return value


def _persist_game() -> None:
    """把当前进度镜像进 URL。值没变时不写，避免多余的重跑。

    加入码跟着一起走 ``gc`` 参数：刷新后如果只恢复了局面、没恢复那个码，这一局
    就又回到"只活在会话里"，名单库里那行会永远停在中断时的进度。
    """
    payload = _game_payload()
    if payload and _query_value(GAME_PARAM) != payload:
        st.query_params[GAME_PARAM] = payload
    code = st.session_state.get(GAME_JOIN_KEY)
    if code and _query_value(GAME_JOIN_PARAM) != code:
        st.query_params[GAME_JOIN_PARAM] = code
    # 挑战码也要一起走：v2 载荷只带决策，没有 task 参数就没人知道这套决策是
    # 在答哪道题。反过来，自由局要把它删干净，免得残留的 task 把 v1 载荷
    # 错认成挑战局。
    task = (st.session_state.get(GAME_TASK_KEY) or {}).get("challenge_id", "")
    if task:
        if _query_value(GAME_TASK_PARAM) != task:
            st.query_params[GAME_TASK_PARAM] = task
    elif GAME_TASK_PARAM in st.query_params:
        del st.query_params[GAME_TASK_PARAM]


def _clear_persisted_game() -> None:
    for param in (GAME_PARAM, GAME_JOIN_PARAM, GAME_TASK_PARAM):
        if param in st.query_params:
            del st.query_params[param]


def _game_start(count: int, turns: int, seed: int, class_code: str = "",
                codes: list[str] | None = None,
                challenge: dict | None = None) -> None:
    """Deal opponents, prime the first match, and register the run in the store.

    The join code is allocated here rather than at the first decision because a
    student who opens the page and gets diverted still has something to come
    back with -- and because the code is the only handle they ever get on their
    own data.

    ``codes`` / ``challenge`` 是挑战局的情形：对手集合来自题面而不是种子，而
    challenge_id 是这张榜的分组键——只有同一挑战码下的提交才会被放在一起排。
    """
    if codes is None:
        codes = draw_opponents(count, seed)
    st.session_state[GAME_CODES_KEY] = codes
    st.session_state[GAME_TASK_KEY] = challenge
    st.session_state[GAME_MATCHES_KEY] = []
    st.session_state[GAME_DONE_KEY] = []
    st.session_state[GAME_RESULTS_KEY] = None
    st.session_state[GAME_PROFILE_KEY] = None
    st.session_state[GAME_AI_KEY] = None
    st.session_state["game_phase"] = "play"
    st.session_state[GAME_RUNNER_KEY] = PlayerMatchRunner(
        index=0, opponent=codes[0], turns=turns, seed=seed + 1
    )
    # 分不到码就照常开局：对局本身不依赖名单库，缺的只是"下周还能回来"。
    try:
        join_code = store.new_join_code()
        store.create_run(
            join_code, class_code=class_code, opponent_count=len(codes),
            turns=turns, seed=seed, engine_version=ENGINE_VERSION,
            tutorial_done=bool(st.session_state.get(GAME_TUTORIAL_DONE)),
            challenge_id=(challenge or {}).get("challenge_id", ""),
        )
        st.session_state[GAME_JOIN_KEY] = join_code
    except (sqlite3.Error, OSError, RuntimeError) as error:
        st.session_state[STORE_ERROR_KEY] = str(error)


def _game_advance() -> None:
    """Close the current match and deal the next one, or finish the run."""
    matches = st.session_state[GAME_MATCHES_KEY]
    finished = st.session_state[GAME_RUNNER_KEY].finish()
    matches.append(finished)
    st.session_state[GAME_MATCHES_KEY] = matches
    # Keep a per-match summary so a finished round's score stays on screen once
    # the next one starts. It used to live only inside the live match view, so
    # pressing "next" made the round you had just played disappear.
    done = st.session_state.get(GAME_DONE_KEY) or []
    done.append(_match_summary(finished))
    st.session_state[GAME_DONE_KEY] = done
    codes = st.session_state[GAME_CODES_KEY]
    setup = st.session_state[GAME_SETUP_KEY]
    if len(matches) < len(codes):
        nxt = len(matches)
        st.session_state[GAME_RUNNER_KEY] = PlayerMatchRunner(
            index=nxt, opponent=codes[nxt], turns=setup["turns"],
            seed=setup["seed"] + 1 + nxt,
        )
    else:
        st.session_state[GAME_RUNNER_KEY] = None
        st.session_state["game_phase"] = "results"


def _game_finish(placeholder=None) -> None:
    """Tournament among the generated strategies, then merge with the player.

    Called as soon as the last match ends rather than when the player asks for
    the report, so the click that opens the results is instant.
    """
    setup = st.session_state[GAME_SETUP_KEY]
    codes = st.session_state[GAME_CODES_KEY]
    matches = st.session_state[GAME_MATCHES_KEY]
    if placeholder is not None:
        placeholder.markdown(analysis_loading(), unsafe_allow_html=True)
    tournament = strategy_tournament(codes, setup["turns"], setup["seed"] + 5000)
    st.session_state[GAME_RESULTS_KEY] = build_results(
        matches, tournament, setup["turns"]
    )
    st.session_state[GAME_PROFILE_KEY] = build_profile(matches)


def _challenge_card(challenge: dict, *, issued: bool = False) -> str:
    """题面卡：这套题有多少步、是什么生态，但不含编码。

    对手编码刻意不列出来——正式局里身份要等一局打完才揭晓，把清单印在开局前
    等于把答案写在卷子上。简介（``blurb`` / ``note``）说的是这一类对手的行为
    倾向，那正是老师想让学生带着进对局的东西。
    """
    steps = challenges.steps(challenge)
    minutes = steps * 5 / 60
    return (
        "<div class='tf-ident'>"
        "<div class='tf-ident__head'>"
        "<span class='tf-ident__kicker'>挑战</span>"
        "<b class='tf-ident__name'>{title}</b>"
        "<span class='tf-ident__label'>{code}</span>"
        "</div>"
        "<div class='tf-rule'><div class='tf-rule__body'>"
        "<b>{n} 局 × 每局 {t} 轮 = {s} 步</b><span>约 {m:.0f} 分钟。"
        "题面已锁定：对手集合、轮数与种子都由这份挑战给定，"
        "所以同一次课的每一份提交算的是同一道题。</span>"
        "</div></div>"
        "<div class='tf-rule'><div class='tf-rule__body'>"
        "<b>这一套对手</b><span>{blurb}</span></div></div>"
        "<div class='tf-ident__note'>{foot}</div>"
        "</div>"
    ).format(
        title=challenge["title"],
        code=challenge["challenge_id"],
        n=len(challenge["codes"]), t=challenge["turns"], s=steps, m=minutes,
        blurb=challenge.get("blurb") or challenge.get("note")
        or "老师没有写简介。",
        foot=(
            "对手的编码仍然要一局打完才揭晓。" if not issued
            else "把这段链接发给全班，点开就已经选好题面。"
        ),
    )


def _predict_toggle() -> bool:
    """The optional "guess first" exercise, offered before the run starts.

    Deliberately a toggle rather than a forced step: guessing is a second object
    of measurement (how well you model the other side) and it must never gate the
    first one (what you actually play). It is off by default so a student who has
    never seen the game gets the plain decision screen.
    """
    return bool(st.toggle(
        "每轮先猜对手出什么",
        key=PREDICT_KEY,
        help="开了之后，每一轮在两个按钮上面多一行：先选你猜它出合作还是背叛，"
             "再决定你自己出什么。猜不猜都不影响比分——引擎只看你出的那一手，"
             "猜测只用来在成绩页算「预测命中率」。",
    ))


def _start_challenge(challenge: dict, class_code: str) -> None:
    st.session_state[GAME_SETUP_KEY] = {
        "count": len(challenge["codes"]),
        "turns": challenge["turns"],
        "seed": challenge["seed"],
        "predict": bool(st.session_state.get(PREDICT_KEY)),
    }
    _game_start(
        len(challenge["codes"]), challenge["turns"], challenge["seed"],
        class_code, codes=list(challenge["codes"]), challenge=challenge,
    )


def _render_challenge_setup(challenge: dict) -> None:
    """锁题的那一屏：没有滑块，只有题面、班级码和一个开始键。"""
    st.markdown(
        theme.heading("第一步：这套题已经锁好了", 3, help_blocks=GAME_HELP["task"]),
        unsafe_allow_html=True,
    )
    st.markdown(_challenge_card(challenge), unsafe_allow_html=True)
    st.text_input(
        "班级码（可留空）",
        placeholder=challenge.get("class_code") or "例如 计科231",
        help="只用于把同一批人的对局归到一起；榜单按挑战码分组，班级码是可选的第二层筛选。",
        key=CLASS_CODE_KEY,
    )
    _predict_toggle()
    if st.button("开始这一局挑战", type="primary", width="stretch"):
        _start_challenge(challenge, (st.session_state.get(CLASS_CODE_KEY) or "").strip()[:24])
        st.rerun()


def _render_game_setup() -> None:
    challenge = st.session_state.get(GAME_TASK_KEY)
    if challenge:
        _render_challenge_setup(challenge)
        return
    st.markdown(
        theme.heading("第一步：设置这一局", 3, help_blocks=GAME_HELP["setup"]),
        unsafe_allow_html=True,
    )
    count = st.slider("对手数量", 4, 12, 10, 1, key="game_opponents")
    turns = st.slider("每局轮数", 5, 20, 10, 1, key="game_turns")
    seed_text = st.text_input(
        "随机种子", value=str(random.SystemRandom().randrange(0, 10 ** 9)),
        help="同一种子会生成同一组对手，便于复现。",
        key="game_seed",
    )

    # Below the sliders, not above them: the summary used to sit on top and read
    # the values out of session state, so on the very first paint it reported the
    # defaults and then never matched what the player had just dragged to.
    steps = count * turns
    st.caption(
        "共 {} 步决策（{} 局 × 每局 {} 轮）。按每步约 5 秒估算，约 {:.0f} 分钟。"
        "每一步都要你自己选合作或背叛——事后分析会逐步检查这些选择。".format(
            steps, count, turns, steps * 5 / 60)
    )
    # The stakes, at the moment they commit to them.
    st.markdown(
        theme.payoff_chips(help_html=theme.help_chip(
            GAME_HELP["payoff"], label="这些数字怎么读",
        )),
        unsafe_allow_html=True,
    )

    # 老师自己起的分组标签，用来把同一次课的名单聚到一起。它不是学生名册：这张
    # 表里没有、也不该有姓名之类能指认到人的东西。
    class_code = st.text_input(
        "班级码（可留空）",
        placeholder="例如 计科231 或 10-14下午班",
        help="只用于把同一批人的对局归到一起，教师端看板按它筛选。不填也能玩。",
        key=CLASS_CODE_KEY,
    )
    predict = _predict_toggle()

    if st.button("开始这一局", type="primary", width="stretch"):
        try:
            seed = int(seed_text.strip())
        except ValueError:
            st.error("种子必须是整数")
            return
        st.session_state[GAME_SETUP_KEY] = {
            "count": count, "turns": turns, "seed": seed, "predict": predict,
        }
        _game_start(count, turns, seed, class_code.strip()[:24])
        st.rerun()

    # 挑战码收在滑块下面：绝大多数人是来自由打一局的，那三行选择是他们要做的决定；
    # 而被下发了码的人只需要输一次码。
    with st.expander("老师下发了挑战码？", expanded=False):
        st.caption(
            "输入挑战码，题面（对手集合、每局轮数、种子）就替你锁定；这一局的"
            "成绩才会和同批提交排在同一张榜上。码显示在老师那份页面上。")
        task_col, btn_col = st.columns([3, 1], vertical_alignment="bottom")
        with task_col:
            task_input = st.text_input(
                "挑战码", placeholder="例如 P-R1EC", key=TASK_CODE_KEY,
                label_visibility="collapsed",
            )
        with btn_col:
            if st.button("进入挑战", key="enter_task", width="stretch"):
                resolved = _resolve_challenge(task_input or "")
                if resolved is None:
                    st.error(
                        "查不到挑战码「{}」。核对有没有抄错——I、O、0、1 这四个"
                        "字符不会出现在挑战码里。".format(
                            store.normalize_code(task_input or "") or "（空）"))
                else:
                    st.session_state[GAME_TASK_KEY] = resolved
                    st.rerun()


def _render_resume_box() -> None:
    """凭加入码回来继续：不需要账号、密码，也不需要姓名。

    没有活动对局时就显示，包括教学之前——上周打到一半的学生这周不该为了输一串
    码而重新学一遍规则。
    """
    st.markdown("#### 接着上次打")
    code = st.text_input(
        "加入码", placeholder="8 位字母数字，形如 K7QM2XNB",
        key=RESUME_CODE_KEY,
        help="开始对局后页面会给出加入码；抄下这串码，或收藏当时那个链接，都能回来继续。",
    )
    if st.button("用加入码继续", key="resume_run"):
        if not (code or "").strip():
            st.error("先输入加入码再点这张按钮。码显示在游戏页顶部，形如 WC4PX2YC。")
            return
        try:
            run = store.load_run(code)
        except (sqlite3.Error, OSError) as error:
            st.error("名单库现在读不出来：{}".format(error))
            return
        if run is None:
            st.error(
                "找不到加入码「{}」。核对一下有没有抄错——I、O、0、1 这四个字符不会出现在加入码里。".format(
                    store.normalize_code(code))
            )
            return
        if run["engine_version"] != ENGINE_VERSION:
            # 跨版本的存档不重放：引擎改了收益或生成规则，同一串决策会算出一份
            # 不同的报告，而那份看起来完全正常的错误报告比报错更难发现。
            st.error(
                "这局记录在引擎 {} 上，当前版本是 {}。为保证每个数字都对得上，不做跨版本重放。".format(
                    run["engine_version"], ENGINE_VERSION)
            )
            return
        challenge = None
        if run["challenge_id"]:
            challenge = _resolve_challenge(run["challenge_id"])
            if challenge is None:
                # 和版本不一致那一路同样的道理：把决策重放到另一套对手上，会得到
                # 一份看起来完全正常、却答错了题的报告。
                st.error(
                    "这一局挂的挑战「{}」在这里查不到了（可能已被删除或这个实例"
                    "还没导入挑战表）。不做重放——向老师要一份新的链接吧。".format(
                        run["challenge_id"])
                )
                return
        _replay_run(
            run["count"], run["turns"], run["seed"], run["actions"],
            join_code=run["join_code"], challenge=challenge,
            predictions=run.get("predictions"),
        )
        st.rerun()


def _lock_challenge_from_url() -> None:
    """老师下发的链接：``?task=P-R1EC`` 点开就已经锁好题面，学生不必自己输码。

    只在没有正在恢复的局时生效——带着 ``?g=`` 的链接里已经有题面了，两处都读就会
    出现地址栏和题面不一致。挑战码查不到时说明题面丢了，宁可回到自由局设置页，
    也不要把学生引到另一套对手上去。
    """
    if (st.session_state.get(GAME_SETUP_KEY)
            or st.session_state.get(GAME_TASK_KEY)
            or _query_value(GAME_PARAM)):
        return
    task = _query_value(GAME_TASK_PARAM)
    if not task:
        return
    challenge = _resolve_challenge(task)
    if challenge is None:
        st.error(
            "链接里的挑战码「{}」在这里查不到（可能这份题面还没导入这个实例）。"
            "先按普通一局打，或向老师要一份新的链接。".format(task))
        return
    st.session_state[GAME_TASK_KEY] = challenge
    st.session_state["app_mode"] = MODE_GAME


def _prediction_line(runner: PlayerMatchRunner, decision) -> None:
    """上一轮那一次猜测的回显，就地写在下一轮的猜测栏上面。

    读的是 ``runner.decisions``，不是 ``game_last``：每步决策后 ``_persist_game``
    都要改写地址栏里的 ``?g=``，那会再触发一次重跑，而 ``game_last`` 在那次重跑里
    已经被取走。只有从 runner 反读，这一行才真的留在屏幕上——否则学生点完就看不见
    自己刚才猜中了没有。
    """
    guesses = sum(1 for mark in runner.prediction_history if mark in ("C", "D"))
    hits = sum(
        1 for item in runner.decisions
        if item.prediction == item.opponent_action
        and item.prediction in ("C", "D")
    )
    st.markdown(
        prediction_note(decision.prediction, decision.opponent_action,
                        guesses, hits),
        unsafe_allow_html=True,
    )


def _render_game_play() -> None:
    runner = st.session_state[GAME_RUNNER_KEY]
    matches = st.session_state[GAME_MATCHES_KEY]
    codes = st.session_state[GAME_CODES_KEY]
    setup = st.session_state[GAME_SETUP_KEY]
    prompt = runner.prompt()

    # One strip for where the run and the match stand. The progress bar, the
    # heading and the caption it replaces were three separate blocks that each
    # restated the same position, and the bar could only count finished matches
    # -- it said nothing about whether they went well.
    st.markdown(
        stage_strip(
            len(codes),
            [(m.player_score, m.opponent_score) for m in matches],
            prompt["turn"], prompt["total_turns"],
            sum(m.player_score for m in matches),
            help_html=theme.help_chip(
                GAME_HELP["play"], label="这一排点怎么读",
            ),
        ),
        unsafe_allow_html=True,
    )

    # The C/D string was unreadable: the letters had to be decoded and the two
    # sides sat on one line. A table with the words and the per-round payoff
    # makes the sequence obvious at a glance.
    _render_done_matches()
    played = len(runner.decisions)
    last = prompt["last_opponent"]

    # Everything below is the *decision* panel, so it stops the moment the match
    # ends. Left running, the settlement screen got a second 本局比分 -- its own
    # plus this one -- and a cue pointing at buttons that were no longer there.
    if not runner.finished:
        if last is not None:
            st.markdown(action_cue(last), unsafe_allow_html=True)

        _score_bar(runner, played)

        # 先猜再选：猜的是对手的行为，选的是自己的立场，两件事分开做才量得出来。
        # 猜测在点下合作/背叛的那一刻被 ``play`` 取走，所以这一行不需要任何提交动作。
        if setup.get("predict"):
            if runner.decisions:
                _prediction_line(runner, runner.decisions[-1])
            guessed = st.pills(
                "你猜对手这一轮出什么",
                ["合作", "背叛", "不猜"],
                selection_mode="single",
                default=["不猜"],
                key="guess_{}_{}".format(runner.index, prompt["turn"]),
                help="可跳过。猜与不猜都不影响这一轮的比分——引擎只看你出的那一手；"
                     "猜中的那些轮会在成绩页单独算一个命中率。",
            )
            runner.set_prediction(
                {"合作": "C", "背叛": "D"}.get(guessed))

        # The action buttons used to sit below the running history, so every extra
        # turn pushed them further down the page and the player had to scroll to
        # keep choosing. The primary decision now comes first and stays put; the
        # history grows underneath it.
        # The two branches under each button price the choice: picking without
        # seeing them means betting on a behaviour the player has to recall from
        # the intro. The branch matching the opponent's last move is tinted, so
        # the risk being taken is the one in front of them, not an abstraction.
        coop_col, defect_col = st.columns(2)
        with coop_col:
            with st.container(key="tf_move_coop"):
                # Both buttons stay the neutral paper variant: making 合作 the
                # primary would tell a first-time player which move the site
                # prefers, and this page measures what they choose.
                if st.button("🤝 合作", key="play_c", width="stretch"):
                    decision = runner.play("C")
                    st.session_state["game_last"] = decision
                    st.rerun()
                st.markdown(branch_strip("C", last), unsafe_allow_html=True)
        with defect_col:
            with st.container(key="tf_move_defect"):
                if st.button("💥 背叛", key="play_d", width="stretch"):
                    decision = runner.play("D")
                    st.session_state["game_last"] = decision
                    st.rerun()
                st.markdown(branch_strip("D", last), unsafe_allow_html=True)

    # The match finishing does *not* advance. Advancing here skipped the
    # settlement screen entirely: the next opponent's empty table appeared
    # together with the identity of the opponent just beaten, so the two
    # belonged to different matches. The run now stops here, reveals this
    # match's identity and score, and only deals the next one when the player
    # presses 进入下一局.
    #
    # (The fall-through below still renders the finished turn, which is what
    # drives the settlement panel.)

    last = st.session_state.pop("game_last", None)
    if last is None and runner.finished:
        # Rebuild the final decision so the settlement panel survives a rerun.
        # It used to come only from ``game_last``, which is popped one line
        # above -- so after the rerun that follows the last turn the panel had
        # nothing to show and the player was dropped straight onto an empty
        # table for a match they had not started.
        last = runner.decisions[-1] if runner.decisions else None

    if last is not None and last.is_final_round:
        # Settlement: the reveal, the score and the full record, and only then
        # the button to move on. The live table below is skipped in this branch
        # -- rendering both produced two copies of the same record on one page.
        finished = _render_completed_match(prompt, runner)
        # 末轮那一次猜测在这里补上：这一支提前 return，走不到下面那段，而这一局
        # 的命中率里确实算上了它。
        if setup.get("predict"):
            _prediction_line(runner, last)
        # The last settlement must not offer 下一局: the run has one screen left,
        # and a player who pressed the always-same label expected another opponent
        # and got a report instead.
        is_last = len(matches) + 1 >= len(codes)
        # [7, 3] rather than an even split: the card is the reading material of
        # this screen, and the button beside it only ever says 下一局.
        reveal_col, next_col = st.columns([7, 3], vertical_alignment="bottom")
        with reveal_col:
            st.markdown(
                identity_card(prompt["opponent"], finished),
                unsafe_allow_html=True,
            )
        with next_col:
            label = "查看成绩与行为分析" if is_last else "进入下一局"
            if st.button(label, type="primary", width="stretch"):
                _game_advance()
                st.rerun()
        return

    # Mid-match: the running table, and the live action buttons come after it.
    if played:
        st.markdown("---")
        st.markdown("**本局已完成的 {} 轮**".format(played))
        st.markdown(
            history_table(
                runner.player_actions_view(), runner.opponent_actions_view(),
                turns=played, highlight=played - 1, decisions=runner.decisions,
            ),
            unsafe_allow_html=True,
        )
    else:
        st.info("这是第一轮，你还没有任何信息。")

    if last is not None:
        mine, theirs = PAYOFFS[(last.action, last.opponent_action)]
        other = last.alternative
        st.markdown("---")
        st.markdown(
            "**你 {}，对手 {}**　你得 {:.0f} 分（若改选 {} 则为 {:.0f} 分）".format(
                "合作" if last.action == "C" else "背叛",
                "合作" if last.opponent_action == "C" else "背叛",
                mine, "背叛" if other == "D" else "合作", last.alternative_payoff,
            )
        )
        moved = last.opponent_next_if_chosen != last.opponent_next_if_alternative
        if moved and not last.is_final_round:
            st.caption(
                "这一手改变了对手的下一轮：会出 {}；若你改出 {}，它会出 {}。".format(
                    "背叛" if last.opponent_next_if_chosen == "D" else "合作",
                    "背叛" if other == "D" else "合作",
                    "背叛" if last.opponent_next_if_alternative == "D" else "合作",
                )
            )
        # The final round is handled above, which returns before reaching here.
        time_left = prompt["total_turns"] - last.turn
        st.caption("本局还剩 {} 轮。".format(time_left))


def _render_done_matches() -> None:
    """Every match already finished, with its score.

    Read out of session state rather than from the live match, so it survives
    advancing to the next opponent.
    """
    done = st.session_state.get(GAME_DONE_KEY) or []
    if not done:
        return

    def _replay_table(row: dict) -> None:
        """The per-turn record of one finished match."""
        match = row.get("match")
        if match is None:
            # Written before matches were kept whole; fall back to the flat
            # action string so older entries still render something.
            mine, _, theirs = row["记录"].partition("/")
            st.markdown(
                history_table(mine, theirs, turns=len(mine) or None),
                unsafe_allow_html=True,
            )
            return
        st.markdown(
            history_table(
                match.player_actions, match.opponent_actions,
                turns=match.turns, decisions=match.decisions,
            ),
            unsafe_allow_html=True,
        )
        # The same card the settlement screen shows: 回看 is where a student goes
        # to work out why they lost, and the rule text is where the answer is.
        st.markdown(
            identity_card(match.opponent, match), unsafe_allow_html=True)
    st.markdown("### 已完成的局")
    head = (
        "<div style='overflow-x:auto;margin:0.2rem 0 0.6rem'>"
        "<table style='border-collapse:collapse;width:100%;max-width:520px;font-size:15px'>"
        "<thead><tr>"
        "<th style='text-align:left;padding:5px 6px;border-bottom:2px solid " + theme.LINE
        + ";color:" + theme.MUTED + "'>局</th>"
        "<th style='text-align:left;padding:5px 6px;border-bottom:2px solid " + theme.LINE
        + ";color:" + theme.MUTED + "'>对手</th>"
        "<th style='text-align:center;padding:5px 6px;border-bottom:2px solid " + theme.LINE
        + ";color:" + theme.MUTED + "'>比分</th>"
        "</tr></thead><tbody>"
    )
    body = []
    for row in done:
        gap = row["你"] - row["对手分"]
        colour = theme.MUTUAL if gap > 0 else (
            theme.DEFECT if gap < 0 else theme.MUTED)
        body.append(
            "<tr>"
            "<td style='padding:4px 6px;color:" + theme.MUTED + "'>{}</td>"
            "<td style='padding:4px 6px'>{}</td>"
            "<td style='padding:4px 6px;text-align:center;font-weight:700;"
            "color:{}'>{} : {}</td>"
            "</tr>".format(row["局次"], row["对手"], colour, row["你"],
                           row["对手分"])
        )
    # No 累计 line here: the stage strip above already carries the running total,
    # and this ledger's job is the per-opponent split the strip cannot show.
    st.markdown(head + "".join(body) + "</tbody></table></div>",
                unsafe_allow_html=True)

    with st.expander("回看每一局的决策记录", expanded=False):
        st.caption("展开任意一局，可以看双方每一轮选了什么、拿到多少分、改选另一手本可拿多少，"
                   "以及对手的规则是在哪几轮显形的。")
        for row in done:
            gap = row["你"] - row["对手分"]
            verdict = "领先" if gap > 0 else ("落后" if gap < 0 else "持平")
            with st.expander(
                "第 {} 局　{}　{} : {}　{}".format(
                    row["局次"], row["对手"], row["你"], row["对手分"], verdict),
                expanded=False,
            ):
                _replay_table(row)


def _render_completed_match(prompt: dict, runner: PlayerMatchRunner) -> Match:
    """The match that just ended: its full per-turn record and the final score.

    Returns the finished :class:`Match` so the caller can hand it to the identity
    card, which points at the turns where that opponent's rule showed up.
    """
    finished = runner.finish()
    st.markdown("---")
    st.markdown(
        theme.heading(
            "本局记录", 3, help_blocks=GAME_HELP["record"],
            help_label="这张逐轮表怎么读",
        ),
        unsafe_allow_html=True,
    )
    _score_bar(runner, len(runner.decisions))
    st.markdown(
        history_table(
            finished.player_actions, finished.opponent_actions,
            turns=finished.turns, highlight=finished.turns - 1,
            decisions=finished.decisions,
        ),
        unsafe_allow_html=True,
    )
    return finished


def _render_class_rank() -> None:
    """挑战局才有的一屏：你在这批提交里的位置，和标准策略在同一套题面上的分数。

    只把同一 ``challenge_id`` 下的提交放在一起算，别人那一侧看到的也只是加入码与总分
    ——没有姓名，也没有别的同学的九项测量。参照线在这里比名次更重要：它让学生看到
    "最好的打法"取决于对面是谁，这正是这一课的主题。
    """
    challenge = st.session_state.get(GAME_TASK_KEY)
    join_code = st.session_state.get(GAME_JOIN_KEY)
    if not challenge or not join_code:
        return
    try:
        peers = store.list_runs(challenge_id=challenge["challenge_id"])
        board = challenges.ranking(challenge, peers, join_code=join_code)
    except (sqlite3.Error, OSError, ValueError) as error:
        st.warning("这批提交的名次现在算不出来：{}".format(error))
        return
    if board["rank"] is None:
        st.caption(
            "这一局在这一屏没有排名：它要么还没打完，要么没有登记在名单库里"
            "（地址栏恢复的局一定会带着加入码）。成绩与行为分析不受影响。")
        return

    st.markdown(
        theme.heading("这批提交里的位置", 3, help_blocks=GAME_HELP["rank"]),
        unsafe_allow_html=True,
    )
    rank_col, median_col, spread_col = st.columns(3)
    rank_col.metric(
        "你的名次", "{} / {}".format(board["rank"], board["count"]),
        help="同一挑战码下已打完的 {} 份提交里的位置。同分并列，下一名跳号。".format(
            board["count"]),
    )
    median_col.metric(
        "这批的中位分", "{:g}".format(board["median"]),
        help="这批提交总分的中位数。你的分在它上面还是下面，比名次更能说明位置。",
    )
    spread_col.metric(
        "上四分位 / 下四分位",
        "{:g} / {:g}".format(board["top_quartile"], board["first_quartile"]),
        help="半数提交落在这两个数之间。区间很窄说明这套题面的结果对打法不敏感。",
    )
    st.dataframe(
        [
            {
                "名次": "{}".format(line["above"] + 1),
                "打法": "{}（{}）".format(line["label"], line["code"]),
                "总分": "{:g}".format(line["score"]),
                "它是怎么打的": line["note"],
            }
            for line in board["baselines"]
        ],
        width="stretch", hide_index=True,
    )
    st.caption(
        "上面这几行是标准策略在同一串对手、同一个轮数、同一份种子下打出的总分——"
        "不是标准答案，也不会有人来领这个分。看的是它们之间的差：同一套题面上，"
        "换个打法能拿多少分。")


def _render_game_results() -> None:
    results = st.session_state[GAME_RESULTS_KEY]
    profile = st.session_state[GAME_PROFILE_KEY]
    st.markdown(
        theme.heading("你的成绩", 3, help_blocks=GAME_HELP["results"]),
        unsafe_allow_html=True,
    )
    metric_a, metric_b, metric_c = st.columns(3)
    metric_a.metric("总局分", "{:.0f}".format(results["player_total"]))
    metric_b.metric(
        "每局平均", "{:.1f}".format(results["player_average"]),
        delta="{:+.1f} vs 策略平均".format(
            results["player_average"] - results["field_average"]),
        help="你的每局平均分，与 {} 个策略彼此对局平均分的差距。".format(
            len(results["table"]) - 1),
    )
    metric_c.metric(
        "策略平均", "{:.1f}".format(results["field_average"]),
        help="{} 个策略两两对局后的平均总分，作为你的参照线。".format(
            len(results["table"]) - 1),
    )

    st.plotly_chart(build_results_figure(results), width="stretch")

    st.markdown(
        theme.heading("平均总得分", 3, help_blocks=GAME_HELP["average"]),
        unsafe_allow_html=True,
    )
    st.dataframe(
        [{
            "": "玩家" if row["is_player"] else row["name"],
            "编码": "—" if row["is_player"] else row["code"],
            "对其他策略": "{:.1f}".format(row["vs_others"]),
            "对你": "—" if row["is_player"] else "{:.1f}".format(row["vs_player"]),
            "背叛倾向": "{:.0%}".format(row["defection_rate"]),
        } for row in results["table"]],
        width="stretch", hide_index=True,
    )

    st.divider()
    st.markdown(
        theme.heading("逐局记录", 3, help_blocks=GAME_HELP["matches"]),
        unsafe_allow_html=True,
    )
    st.markdown(matches_overview(profile["matches"]), unsafe_allow_html=True)

    st.divider()
    _render_class_rank()

    st.divider()
    if st.button("查看行为分析", type="primary", width="stretch"):
        st.session_state["game_phase"] = "profile"
        st.rerun()


def _prediction_stats(matches: list) -> dict | None:
    """把每一局的猜测与对手实际出的那一手对齐，算出命中率。

    只数真的猜过的那些轮：没猜的那些轮记成 ``-``，它们既不算猜对也不算猜错，否则
    「跳过」会被读成「猜错」。这是本地逐轮比对，不是模型给出的判断。
    """
    rows = []
    guesses = 0
    hits = 0
    for match in matches:
        played = [
            (decision.prediction, decision.opponent_action)
            for decision in match.decisions
            if decision.prediction in ("C", "D")
        ]
        if not played:
            continue
        hit = sum(1 for guess, actual in played if guess == actual)
        guesses += len(played)
        hits += hit
        rows.append({
            "局次": match.index + 1,
            "对手": match.opponent_label,
            "猜了": len(played),
            "猜中": hit,
            "命中率": "{:.0%}".format(hit / len(played)),
        })
    if not rows:
        return None
    return {"rows": rows, "guesses": guesses, "hits": hits}


def _render_prediction_card(profile: dict) -> None:
    """那一屏只有一件事：你猜对手的行为，猜得准不准。"""
    stats = _prediction_stats(profile["matches"])
    if stats is None:
        return

    st.markdown(
        theme.heading(
            "你猜得准吗", 3,
            gloss="只在开了「每轮先猜对手出什么」时出现",
            help_blocks=GAME_HELP["prediction"],
        ),
        unsafe_allow_html=True,
    )
    rate_col, count_col, best_col = st.columns(3)
    rate_col.metric(
        "预测命中率", "{:.0%}".format(stats["hits"] / max(stats["guesses"], 1)),
        help="猜中的轮数 ÷ 猜过的轮数。只算真的猜过的那些轮；跳过的轮不进分母。",
    )
    count_col.metric(
        "猜了 / 全部", "{} / {} 轮".format(
            stats["guesses"], profile["total_turns"]),
        help="剩下那些轮你直接出了牌，没有先猜。",
    )
    top = max(stats["rows"], key=lambda row: row["猜中"] / row["猜了"])
    best_col.metric(
        "猜得最准的一局", "第 {} 局".format(top["局次"]),
        delta="{} {}".format(top["命中率"], top["对手"]),
        delta_color="off",
        help="对手标签是这一局那个策略的行为类别——猜得准往往意味着它的行为有规则可循。",
    )
    st.dataframe(stats["rows"], width="stretch", hide_index=True)


def _render_game_profile() -> None:
    profile = st.session_state[GAME_PROFILE_KEY]
    results = st.session_state[GAME_RESULTS_KEY]
    st.markdown(
        theme.heading("行为分析", 3, help_blocks=GAME_HELP["profile"]),
        unsafe_allow_html=True,
    )
    # The disclaimer stays on the page rather than behind the "?": a reader who
    # never clicks still has to see what these numbers are not. The rest of the
    # how-to-read text moved into the chip.
    st.caption(
        "以下 {} 项都是对你这 {} 步决策的本地测量，不是心理诊断，也不给人格类型。".format(
            len(profile["dimensions"]), profile["total_turns"]
        )
    )

    _render_play_card(profile)

    # Not 总局分 / 每局平均: the player read those on the 成绩 page one click
    # ago. Not the opening or retaliation rates either -- the nine dimension cards
    # directly below already state those as percentages. These three are raw
    # counts of what physically happened across the run, which the conditional
    # rates below cannot show.
    turns_played = profile["total_turns"]
    both_cooperated = sum(
        1 for m in profile["matches"] for d in m.decisions
        if d.action == "C" and d.opponent_action == "C")
    # ``Decision.provoked`` is not this: it asks whether the opponent defected on
    # the *previous* turn, which is the trigger for measuring retaliation, not a
    # count of rounds where the player actually lost out.
    cheated_on = sum(
        1 for m in profile["matches"] for d in m.decisions
        if d.action == "C" and d.opponent_action == "D")
    metric_a, metric_b, metric_c = st.columns(3)
    metric_a.metric("背叛步数", "{} / {}".format(
        profile["total_defections"], turns_played))
    metric_b.metric(
        "互相合作", "{} / {}".format(both_cooperated, turns_played),
        help="你和对手同时出合作的轮数。这是双方都拿 3 分的那些轮。",
        delta="{:.0%}".format(both_cooperated / max(turns_played, 1)),
        delta_color="off",
    )
    metric_c.metric(
        "被单方面背叛", "{} 次".format(cheated_on),
        help="你出合作、对手出背叛的轮数：你拿 0 分，它拿 5 分。"
             "它与「互相合作」「互相背叛」加起来就是全部 {} 轮。".format(
                 turns_played),
    )

    _render_prediction_card(profile)

    # The score cards come first on purpose. A player should be able to read
    # where they stand before reading a single paragraph about why.
    st.markdown(
        theme.heading("你的九项维度", 3, help_blocks=GAME_HELP["dimensions"]),
        unsafe_allow_html=True,
    )
    st.plotly_chart(build_score_cards(profile), width="stretch")
    cards = st.columns(3)
    for index, row in enumerate(dimension_scores(profile)):
        with cards[index % 3]:
            st.metric(
                row["label"], "{}%".format(row["percent"]),
                help="{}\n方向：{}\n实际测量：{}".format(
                    row["title"], row["direction"], row["measured"]),
            )

    # Measured: these six figures are ~44.5 KB of JSON, 84% of everything the
    # page ships. ``st.expander`` and ``st.tabs`` only hide the DOM -- the code
    # still runs and the payload still goes over the socket. A toggle actually
    # skips the branch, so nothing is built or sent until it is asked for.
    if st.toggle("显示详细图表（雷达 / 逐局得分 / 全部决策 / 关键比率 / 排名）",
                 key="show_detail_charts"):
        chart_choice = st.radio(
            "选一张来看", ["九维雷达", "逐局得分", "全部决策", "关键比率", "排名"],
            horizontal=True, key="chart_pick",
        )
        if chart_choice == "九维雷达":
            st.plotly_chart(build_radar(profile), width="stretch")
        elif chart_choice == "逐局得分":
            st.plotly_chart(build_score_trend(profile, results), width="stretch")
        elif chart_choice == "全部决策":
            st.plotly_chart(build_action_map(profile), width="stretch")
            st.caption(
                "每个格子是一轮：深绿=互相合作，深红=互相背叛，"
                "浅色=只有一方合作。横轴是轮次，纵轴是局数。")
        elif chart_choice == "关键比率":
            st.plotly_chart(build_rate_bars(profile), width="stretch")
        else:
            st.plotly_chart(build_field_standing(profile, results), width="stretch")

    with st.expander("逐项细分分析（含证据与可推翻条件）", expanded=False):
        st.caption(
            "每一项都是对你 {} 步决策的测量，附具体场次轮次证据，"
            "并写明什么观察能推翻它。刻意不给人格类型或「像某个策略」的结论。".format(
                profile["total_turns"]))
        for dimension in profile["dimensions"]:
            with st.expander(dimension.title, expanded=False):
                st.markdown(dimension.to_markdown())

    st.divider()
    _render_game_ai(profile, results)

    st.divider()
    if st.button("返回成绩", width="stretch"):
        st.session_state["game_phase"] = "results"
        st.rerun()


CREATION_AI_KEY = "creation_ai_report"


def _render_creation_ai(simulation, names: dict) -> None:
    """Let the model summarise a whole evolution run.

    Same shape as the game mode's analysis: press one button, read the streamed
    report. Nothing is exported and nothing is submitted by hand -- the run
    already lives in session state, so it can go straight to the model.
    """
    st.markdown("### 大模型解读这场演化")

    config = ai_config()

    if not config["ready"]:
        st.info("本站的分析功能尚未开通（服务端未配置分析密钥）。"
                "上面的演化数据与图表不受影响，可照常查看。")
        return
    generations = simulation.generation
    st.caption(
        "会把 {} 代演化的开局、转折与终局，以及份额排名，"
        "整理成一份摘要交给大模型，"
        "让它说明谁赢了、变化发生在哪几代、淘汰的策略有什么共同点。".format(
            generations)
    )

    report = st.session_state.get(CREATION_AI_KEY)
    if report:
        st.markdown(report)
        st.download_button(
            "下载这份解读", data=report,
            file_name="evolution_analysis.md", mime="text/markdown",
        )

    if st.button("生成演化解读", type="primary", width="stretch"):
        placeholder = st.empty()
        try:
            digest = evolution_analysis.build_digest(
                simulation, names or {},
                generations=[generations // 4, generations // 2,
                             generations],
            )
            text = "".join(ai_stream_text(
                evolution_analysis.EVOLUTION_SYSTEM_PROMPT,
                "以下是这场演化模拟的摘要：\n\n" + digest,
            ))
            if not text.strip():
                raise RuntimeError("模型没有返回任何内容。")
            st.session_state[CREATION_AI_KEY] = text
            placeholder.empty()
            st.rerun()
        except Exception as error:  # noqa: BLE001 - surface to the reader
            placeholder.empty()
            st.error("生成失败：{}".format(error))


def _render_play_card(profile: dict) -> None:
    """出牌风格卡：一个能直接发出去的结论。

    这张卡**不依赖 AI**——九项测量一算完就能出。理由是分享这一环必须在免费
    路径上：愿意转发的人远多于愿意付费的人，卡片的传播价值不该锁在付费墙后面。

    卡面只讲"你这十局怎么出牌"，不给人格类型，措辞避开特质形容词。这条界线
    和 ``profiling.py`` 原本的设计约束一致；卡片存在的意义是把测量归纳成一个
    能读、能转发的结论，而不是给读者贴标签。

    AI 版会在同一个位置叠加模型写的结论与关键手——见 ``_render_game_ai``。
    """
    style = classify_play_style(profile)
    verdict = st.session_state.get(GAME_CARD_KEY) or {}

    try:
        png = build_play_card(
            profile,
            conclusion=verdict.get("conclusion"),
            evidence=verdict.get("evidence"),
        )
    except Exception as error:  # noqa: BLE001 - 出图失败不该让整页崩掉
        st.warning("风格卡暂时画不出来：{}".format(error))
        return

    left, right = st.columns([1, 1], gap="large")
    with left:
        st.image(png, width="stretch")
    with right:
        st.markdown("#### 你的出牌风格")
        st.markdown("**{}**　匹配度 {}%".format(
            style["name"], int(round(style["match"] * 100))))
        st.caption(
            "风格名 = 原型 + 你偏离最远的那一项。全站共有 10 个原型 × 9 种修饰，"
            "同样的对局一定得到同一个风格。"
        )
        if verdict.get("conclusion"):
            st.markdown("**AI 版结论**")
            st.write(verdict["conclusion"])
        else:
            st.caption(
                "下面的「用这段解读生成定制风格卡」会让模型只读你的具体轮次，"
                "写一句结论并挑出三条最说明问题的关键手，写进同一张卡。"
                "不点它，卡上就是纯本地测量的结果。"
            )

        st.download_button(
            "下载风格卡（PNG）",
            data=png,
            file_name="fittest-style-{:08x}.png".format(
                zlib.crc32(style["name"].encode("utf-8")) & 0xFFFFFFFF),
            mime="image/png",
            width="stretch",
        )
        with st.expander("复制文字版（发评论 / 群聊用）"):
            st.code(play_card_text(profile), language=None)


def _render_game_ai(profile: dict, results: dict) -> None:
    """In-app LLM reading of the session.

    解读由本站统一提供：访客不需要自备密钥，也不需要注册。测量结论始终由本地
    确定性算法给出，模型只负责把原始决策流水讲成自然语言，两者是分开的。
    """
    st.markdown("### 大模型深度解读")
    st.caption(
        "会把全部 {} 步决策连同反事实数据一起交给大模型，"
        "要求它逐局逐步剖析你的动机，并落到现实场景。".format(
            profile["total_turns"]
        )
    )
    config = ai_config()
    if not config["ready"]:
        st.info(
            "本站的深度解读功能尚未开通（服务端未配置分析密钥）。"
            "上面的图表与行为测量不受影响，可照常查看。"
        )
        return

    status_col, test_col, gen_col = st.columns([3, 2, 3])
    with status_col:
        st.caption(
            "由本站统一提供　服务商 {}　模型 {}".format(
                ai_provider_label(config), config["model"]
            )
        )
    with test_col:
        if st.button("测试可用性", width="stretch"):
            try:
                with st.spinner("测试中…"):
                    reply = ai_probe()
                st.success("可用：{}".format(reply.strip()[:40]))
            except Exception as error:  # noqa: BLE001 - not the player's fault
                st.error("暂时不可用：{}".format(error))
    with gen_col:
        if st.button("生成深度解读", type="primary", width="stretch"):
            try:
                st.caption("正在读你的这一局…")
                overview = st.write_stream(
                    ai_stream(profile, results, plan="overview",
                              ),
                    cursor="▌",
                )
                if isinstance(overview, list):
                    overview = "".join(str(piece) for piece in overview)
                overview = str(overview).strip()
                if not overview:
                    raise RuntimeError("模型没有返回任何内容。")
                st.session_state[GAME_AI_OVERVIEW_KEY] = overview
            except Exception as error:  # noqa: BLE001 - surface to the player
                st.error("调用失败：{}".format(error))

    # Plain markdown rather than a placeholder created inside the button branch:
    # the slot only existed while the button had been pressed, so any later
    # rerun that still had a stored summary raised UnboundLocalError.
    overview_text = st.session_state.get(GAME_AI_OVERVIEW_KEY)
    if overview_text:
        st.markdown("### 结论速览\n\n" + overview_text)
        st.caption("速览到此为止。完整版要读全部 {} 步决策，耗时明显更长，"
                   "费用也更高。".format(profile["total_turns"]))

        # 定制风格卡：另一次独立调用，只问一个收得住的结论 + 三条关键手。
        # 走同一份服务端密钥、同一个归因头；主报告的禁令不受影响。
        if st.button("用这段解读生成定制风格卡", width="stretch"):
            try:
                with st.spinner("正在把结论写进卡片…"):
                    verdict = ai_card_verdict(
                        profile, results,
                    )
                if not verdict:
                    raise RuntimeError("模型没有返回可用的卡片结论。")
                st.session_state[GAME_CARD_KEY] = verdict
                st.rerun()
            except Exception as error:  # noqa: BLE001 - surface to the player
                st.error("生成卡片结论失败：{}".format(error))

        if st.button("展开完整版剖析", width="stretch"):
            try:
                st.caption("正在逐步剖析，可能要等一两分钟…")
                detail = st.write_stream(
                    ai_stream(profile, results, plan="full",
                              ),
                    cursor="▌",
                )
                if isinstance(detail, list):
                    detail = "".join(str(piece) for piece in detail)
                detail = str(detail).strip()
                if not detail:
                    raise RuntimeError("模型没有返回任何内容。")
                st.session_state[GAME_AI_KEY] = detail
                st.rerun()
            except Exception as error:  # noqa: BLE001 - surface to the player
                st.error("调用失败：{}".format(error))

    if st.session_state.get(GAME_AI_KEY):
        st.markdown("### 完整剖析")
        st.markdown(st.session_state[GAME_AI_KEY])
        st.download_button(
            "下载这份解读", data=st.session_state[GAME_AI_KEY],
            file_name="game_analysis.md", mime="text/markdown",
        )


def _render_tutorial() -> None:
    """Teach the rules by playing them, before the real session starts.

    The opponent is a real engine strategy played through the same
    ``PlayerMatchRunner`` the match uses, so the tutorial shows the genuine
    behaviour of a strategy the player will meet again later.
    """
    st.markdown(
        theme.heading("新手教程", 3, help_blocks=GAME_HELP["tutorial"]),
        unsafe_allow_html=True,
    )
    if st.session_state.get(GAME_TUTORIAL_KEY) is None:
        st.session_state[GAME_TUTORIAL_KEY] = TutorialState()
    if st.session_state.get(TUTORIAL_RUNNER_KEY) is None:
        st.session_state[TUTORIAL_RUNNER_KEY] = PlayerMatchRunner(
            index=0, opponent=TUTORIAL_OPPONENT, turns=TUTORIAL_TURNS,
            seed=20251007,
        )
    state: TutorialState = st.session_state[GAME_TUTORIAL_KEY]
    runner: PlayerMatchRunner = st.session_state[TUTORIAL_RUNNER_KEY]

    top_col, skip_col = st.columns([4, 1])
    with top_col:
        step, total = tutorial_progress(state)
        st.progress(step / total, text="教程进度 {}/{}".format(step, total))
    with skip_col:
        if st.button("跳过", key="tut_skip", width="stretch"):
            st.session_state[GAME_TUTORIAL_DONE] = True
            st.rerun()

    if state.done:
        st.markdown("---")
        mine_total, their_total = state.running()
        st.markdown(
            "<div style='text-align:center;font-size:1.1rem'>"
            "五轮结束　<b>{}</b> 分　:　<b>{}</b> 分</div>".format(
                mine_total, their_total),
            unsafe_allow_html=True,
        )
        st.markdown("---")
        st.markdown(TUTORIAL_CLOSING)
        st.markdown("---")
        history_mine, history_theirs = state.history()
        st.markdown("**本教程的完整记录**")
        st.markdown(
            history_table(history_mine, history_theirs),
            unsafe_allow_html=True,
        )
        if st.button("开始正式对局", type="primary", width="stretch"):
            st.session_state[GAME_TUTORIAL_DONE] = True
            st.rerun()
        return

    st.markdown(TUTORIAL_INTRO)
    with st.expander("四种组合分别怎么算分", expanded=False):
        rule_colour = {
            "coop": theme.COOP,
            "defect": theme.DEFECT,
            "mutual": theme.MUTUAL,
        }
        for left, right, key in TUTORIAL_RULES:
            st.markdown(
                "<span style='color:{};'>●</span> **{}** → {}".format(
                    rule_colour.get(key, theme.MUTED), left, right),
                unsafe_allow_html=True,
            )

    # The opponent's next move is derived from what the player has actually played,
    # but it is deliberately **not** announced: saying "it will defect" turns the
    # round into a lookup instead of a judgement, and the real match never gives
    # that away. The two payoffs are shown because they are knowable from the
    # rules alone -- the player can work out the rest.
    st.markdown("**第 {} 轮**　你这一轮打算怎么走？".format(state.step + 1))
    st.caption("对手上一轮的选择：`{}`".format(
        state.theirs[-1] if state.theirs else "（还没有）"))

    # The result card for the turn just played. Exactly one of the two branches
    # ever writes here -- the tailored "you went against the advice" text or the
    # ordinary outcome note -- so the screen cannot show both.
    #
    # Replayed from state rather than printed inline: the run that advances the
    # turn ends in st.rerun(), which discarded anything it had written.
    if state.last_note:
        st.markdown(state.last_note, unsafe_allow_html=True)

    their_move = runner.opponent_next_action()
    coop_score, defect_score, _ = tutorial_scores(their_move)
    advised = tutorial_lesson_advice(state.step)

    # The running score, always visible: it is the one number a player wants
    # after every turn, and it was previously only available by scrolling down
    # to the history table at the bottom of the page.
    my_run, their_run = state.running()
    lead_word = "领先" if my_run > their_run else (
        "落后" if my_run < their_run else "持平")
    lead_colour = (theme.MUTUAL if my_run > their_run
                   else (theme.DEFECT if my_run < their_run else theme.MUTED))
    st.markdown(
        "<div class='tf-score'>"
        "<span class='tf-score__label'>当前比分</span>"
        "<span class='tf-score__you'>你 <b>{}</b></span>"
        "<span class='tf-score__colon'>:</span>"
        "<span class='tf-score__them'>对手 <b>{}</b></span>"
        "<span class='tf-score__lead' style='color:{}'>{}</span>"
        "</div>".format(my_run, their_run, lead_colour, lead_word),
        unsafe_allow_html=True,
    )

    st.markdown("### 第 {} 轮".format(state.step + 1))
    st.markdown("> {}".format(
        tutorial_opening_note(state.step, state.mine, state.theirs)))
    st.markdown(
        "**两个选择**：合作得 {} 分　　背叛得 {} 分".format(
            coop_score, defect_score,
        )
    )
    suggest_cooperate = advised == "C"
    st.markdown(
        "**这一轮，建议你 {}**".format(
            "先合作" if suggest_cooperate else "背叛一次，做一次试探")
    )
    # "建议" rides alongside the button it refers to. Both columns reserve the same
    # vertical space for it -- one shows the badge, the other renders an empty
    # placeholder of identical height -- so the buttons stay level. Showing the
    # badge in only one column is what previously pushed the two buttons to
    # different heights.
    # The recommendation is shown as a badge rather than by recolouring the
    # button. Colouring the recommended *slot* did not work: Streamlit reuses
    # the container element when only its key changes, so from round 3 on the
    # cooperate button kept the "recommended" class while defection was the one
    # being advised. Each button also keeps its own action colour regardless,
    # which is why both looked identical whenever defection was advised.
    # The recommendation is carried by a badge, and the badge also decides the
    # button's colour. Swapping the container key to mark the recommended slot
    # did not work: Streamlit reuses the element when only the key changes, so
    # from round 3 on the cooperate button kept the "recommended" styling while
    # defection was the one being advised. A container whose key changes every
    # turn is the wrong instrument here -- the visible text and this attribute
    # both re-render reliably.
    coop_col, defect_col = st.columns(2)
    with coop_col:
        with st.container(key="tf_move_coop"):
            if st.button(
                "🤝 合作",
                key="tut_c", width="stretch", type="secondary",
            ):
                _tutorial_step(state, "C")
            st.markdown(
                '<span class="tf-rec%s" data-turn="%d">%s</span>'
                % (" tf-rec--on" if suggest_cooperate else " tf-rec--off",
                   state.step,
                   "建议" if suggest_cooperate else "&#8203;"),
                unsafe_allow_html=True,
            )
    with defect_col:
        with st.container(key="tf_move_defect"):
            if st.button(
                "💥 背叛",
                key="tut_d", width="stretch", type="secondary",
            ):
                _tutorial_step(state, "D")
            st.markdown(
                '<span class="tf-rec%s" data-turn="%d">%s</span>'
                % (" tf-rec--on" if not suggest_cooperate else " tf-rec--off",
                   state.step,
                   "建议" if not suggest_cooperate else "&#8203;"),
                unsafe_allow_html=True,
            )

    # The record moved below the buttons for the same reason it did in the real
    # match: it grows every turn, and pushing the choice off-screen each round
    # made the tutorial tiring rather than instructive.
    if state.step:
        st.markdown("---")
        history_mine, history_theirs = state.history()
        st.markdown("**到目前为止的记录**")
        st.markdown(
            history_table(history_mine, history_theirs, highlight=state.step - 1),
            unsafe_allow_html=True,
        )


def _tutorial_step(state: TutorialState, action: str) -> None:
    """Advance the tutorial one turn against the real engine opponent."""
    runner: PlayerMatchRunner = st.session_state[TUTORIAL_RUNNER_KEY]
    advised = tutorial_lesson_advice(state.step)
    followed = action == advised
    decision = runner.play(action)
    mine, their_points, theirs = tutorial_play(
        state, action, decision.opponent_action
    )
    if followed:
        note = tutorial_outcome_note(
            state.mine, state.theirs, action, theirs, state.step - 1
        )
        tag, tag_colour = "按建议行动", theme.MUTUAL
    else:
        note = tutorial_reacted_note(
            state.mine, state.theirs, action, theirs, followed
        )
        tag, tag_colour = "没按建议", theme.DEFECT
    colour = (theme.MUTUAL if mine > their_points
              else (theme.DEFECT if mine < their_points else theme.COOP))
    # The tag is the visible difference between the two branches. The two cards
    # used to look identical apart from one line of small grey text, so a player
    # could not tell which branch had fired.
    badge = (
        "<span style='float:right;font-size:.78rem;font-weight:700;"
        "color:{};border:1px solid {};border-radius:999px;"
        "padding:.1rem .5rem'>{}</span>"
    ).format(tag_colour, tag_colour, tag)
    # Stored, not just printed. ``st.rerun()`` below discards anything written
    # in this run, so a card rendered here flashed for a single frame and then
    # vanished.
    state.last_note = (
        "<div style='border-left:4px solid {colour};padding:0.6rem 0.9rem;"
        "background:{wash};border-radius:0 8px 8px 0;margin-top:0.6rem'>"
        "{badge}"
        "<b>你 {you}，对手 {them}　你得 {mine} 分，对手得 {their} 分</b><br>"
        "<span style='color:{muted}'>{note}</span></div>"
    ).format(
        colour=colour, wash=theme.RAISED, muted=theme.MUTED, badge=badge,
        you="合作" if action == "C" else "背叛",
        them="合作" if theirs == "C" else "背叛",
        mine=mine, their=their_points,
        note=note,
    )
    st.session_state[GAME_TUTORIAL_KEY] = state
    st.rerun()


def _score_bar(runner: PlayerMatchRunner, played: int) -> None:
    """The running score for a live match, above the choice buttons.

    This is the number a player wants after every single turn, and it used to
    live only inside the history table below the fold.
    """
    if not played:
        return
    my_run = runner.player_score
    their_run = runner.opponent_score
    margin = my_run - their_run
    # 领先 / 落后 by sign, not by magnitude: this used to print "领先 5 分" while
    # the score bar itself showed 4 : 9, i.e. it told the player they were ahead
    # exactly when they were behind.
    lead_word = (
        "领先 {} 分".format(abs(int(margin))) if margin > 0
        else ("落后 {} 分".format(abs(int(margin))) if margin < 0 else "持平")
    )
    lead_colour = (theme.MUTUAL if margin > 0
                   else (theme.DEFECT if margin < 0 else theme.MUTED))
    # The bar splits the points the two have actually taken, so the score reads
    # as a race rather than as two unrelated totals. Both sides can only be at
    # zero before the first turn, which the guard above already excludes.
    total = my_run + their_run
    mine_share = my_run / total * 100 if total else 50
    st.markdown(
        "<div class='tf-score'>"
        "<span class='tf-score__label'>本局比分</span>"
        "<span class='tf-score__you'>你 <b>{}</b></span>"
        "<span class='tf-score__colon'>:</span>"
        "<span class='tf-score__them'>对手 <b>{}</b></span>"
        "<span class='tf-score__lead' style='color:{}'>{}</span>"
        "<div class='tf-score__split'>"
        "<div class='tf-score__you-bar' style='width:{:.1f}%'></div>"
        "<div class='tf-score__them-bar' style='width:{:.1f}%'></div>"
        "</div>"
        "</div>".format(
            int(my_run), int(their_run), lead_colour, lead_word,
            mine_share, 100 - mine_share,
        ),
        unsafe_allow_html=True,
    )


def render_game_mode() -> None:
    """Game mode: play the generated opponents, then read the behaviour back."""
    # 每次渲染都把进度同时镜像进地址栏和名单库。放在最前面，是因为下面每一处
    # return 都会提前离开，写在这里才能覆盖所有分支（对战中、成绩页、行为分析页）。
    # 两条路径存的是同一串决策，只是给不同的人用：地址栏给刷新页面的这一次会话，
    # 加入码给下周才回来的那一次。
    _persist_game()
    _persist_store()
    # The motif belongs to this layer rather than the page: on the page it
    # ran under every control, and the border version of the sheet doubled
    # up where its strips overlapped.
    with st.container(key="tf_game_layer"):
        st.markdown("## 🎮 游戏模式")
        # 恢复出来的一局读不到滑块（那是上一个会话的状态），所以以实际发到手
        # 的对手数为准——否则一句"与 10 个策略对局"配着"第 2 / 4 局"。
        setup = st.session_state.get(GAME_SETUP_KEY)
        st.caption(
            "与 {} 个随机生成的策略对局，逐步自己选择；结束后得到得分矩阵和行为分析。"
            .format(setup["count"] if setup else st.session_state.get("game_opponents", 10))
        )
        top_col, mid_col, end_col = st.columns(3)
        with top_col:
            if st.button("← 返回模式选择", key="game_back", width="stretch"):
                for key in (GAME_SETUP_KEY, GAME_CODES_KEY, GAME_RUNNER_KEY,
                            GAME_MATCHES_KEY, GAME_DONE_KEY, GAME_RESULTS_KEY, GAME_PROFILE_KEY,
                            GAME_AI_KEY, GAME_CARD_KEY, GAME_TUTORIAL_KEY,
                            GAME_TUTORIAL_DONE, TUTORIAL_RUNNER_KEY, GAME_JOIN_KEY,
                            "game_phase"):
                    st.session_state.pop(key, None)
                st.session_state["app_mode"] = None
                _clear_persisted_game()
                st.rerun()
        with mid_col:
            if st.session_state.get(GAME_MATCHES_KEY) and st.button(
                "重新开始", key="game_restart", width="stretch"
            ):
                # GAME_JOIN_KEY goes too: the next 开始这一局 allocates a fresh
                # code, and keeping the old one would make this session write
                # over a run another student might still be coming back for.
                for key in (GAME_SETUP_KEY, GAME_CODES_KEY, GAME_RUNNER_KEY,
                            GAME_MATCHES_KEY, GAME_DONE_KEY, GAME_RESULTS_KEY, GAME_PROFILE_KEY,
                            GAME_AI_KEY, GAME_CARD_KEY, GAME_TUTORIAL_DONE, GAME_JOIN_KEY,
                            "game_phase"):
                    st.session_state.pop(key, None)
                _clear_persisted_game()
                st.rerun()
        with end_col:
            phase = st.session_state.get("game_phase", "setup")
            st.caption("当前阶段：{}".format({
                "setup": "设置", "play": "对战中", "results": "成绩", "profile": "行为分析",
            }.get(phase, phase)))

        st.divider()

        # One line, always present, that says how to come back. Without it the
        # join code exists in the database and nowhere a student would look.
        join_code = st.session_state.get(GAME_JOIN_KEY)
        if join_code:
            st.caption(
                "你的加入码：**{}**　关掉页面、换设备，回到这里输入这串码就能接着打。"
                "本站不记录姓名、邮箱或账号，这串码是你取回自己成绩的唯一凭据。".format(join_code)
            )
        if store_error := st.session_state.pop(STORE_ERROR_KEY, None):
            st.warning(
                "进度没能写进名单库（{}），对局本身不受影响；地址栏那条链接仍然能恢复这一局。".format(store_error)
            )

        # Shown whenever no run is active -- including before the tutorial, since
        # a student returning from last week has already learned the rules and
        # should not have to sit through it again to type in a code.
        if not st.session_state.get(GAME_SETUP_KEY):
            _render_resume_box()

        runner = st.session_state.get(GAME_RUNNER_KEY)
        if runner is not None:
            _render_game_play()
            return
        if st.session_state.get(GAME_PROFILE_KEY) is not None and \
                st.session_state.get("game_phase") == "profile":
            _render_game_profile()
            return
        if st.session_state.get(GAME_RESULTS_KEY) is not None:
            _render_game_results()
            return
        if st.session_state.get(GAME_MATCHES_KEY):
            # The last match is done: compute now so the report opens instantly.
            holder = st.empty()
            _game_finish(placeholder=holder)
            holder.empty()
            st.session_state["game_phase"] = "results"
            st.rerun()
            return
        # The tutorial gates the first real session, because the rules are not
        # intuitive and a player who does not know that cooperation scores 3 will
        # read every result wrong.
        if not st.session_state.get(GAME_TUTORIAL_DONE):
            _render_tutorial()
            return
        _render_game_setup()


def main() -> None:
    # A forced mobile layout starts with the sidebar collapsed: on a phone an
    # expanded sidebar takes the whole viewport and hides the run itself.
    initial_sidebar = (
        "collapsed" if st.session_state.get("layout_mode") == MODE_MOBILE else "expanded"
    )
    st.set_page_config(
        page_title="The Fittest",
        layout="wide",
        initial_sidebar_state=initial_sidebar,
    )
    if not check_password():
        st.stop()

    # Injected before any branch renders, because both the mode chooser and game
    # mode return early below and would otherwise miss the theme.
    theme.inject_background()
    theme.inject()
    # Injected once, before the branches, so the phone rules reach every screen:
    # the mode picker, the game the students actually play on a phone, and the
    # creation view. ``layout_mode`` is only set by the creation sidebar, so a
    # session that never opened it falls back to auto and just gets the media
    # query -- which is the point, since the tap-target sizing matters most on
    # the screens that have no sidebar to hide.
    stylesheet = responsive_css(_layout_mode())
    if stylesheet:
        st.markdown(stylesheet, unsafe_allow_html=True)

    # 地址栏里带着一局的话，先把它重放回 session_state，再决定渲染哪个模式。
    # 必须在读 ``app_mode`` 之前，否则会先落到模式选择页。
    _restore_game_from_url()
    # 下发链接里的 ``?task=``：没有正在恢复的局时，它把题面锁好再进对局模式。
    _lock_challenge_from_url()

    mode = st.session_state.get("app_mode")
    if mode is None:
        render_mode_select()
        return
    if mode == MODE_GAME:
        render_game_mode()
        return

    settings = render_sidebar()
    if settings is not None:
        start_simulation(settings)
        st.rerun()
    # Injected after the responsive sheet on purpose: the viewer must win the
    # specificity contest over the compact 320px chart cap.
    if st.session_state.get("heatmap_fullscreen") is not None:
        st.markdown(fullscreen_css(), unsafe_allow_html=True)
    render_main()


if __name__ == "__main__":
    main()
