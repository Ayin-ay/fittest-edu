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
    load_document,
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
from dashboard import evolution_analysis  # noqa: E402
from dashboard import theme  # noqa: E402
from dashboard.gameplay import (  # noqa: E402
    PlayerMatchRunner,
    action_cue,
    branch_strip,
    build_results,
    build_results_figure,
    draw_opponents,
    history_table,
    identity_card,
    matches_overview,
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
    first_visit,
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
    events_at,    _display_name,
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


def _configured_password() -> str | None:
    """Read APP_PASSWORD from st.secrets (or env). None means no gate."""
    value = None
    try:
        value = st.secrets.get("APP_PASSWORD")
    except Exception:  # no secrets file configured
        value = None
    return value or os.getenv("APP_PASSWORD") or None


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
    background = st.get_option("theme.backgroundColor")
    if not background:
        background = "#0e1117" if st.get_option("theme.base") == "dark" else "#ffffff"
    return (
        "<style>"
        ".st-key-pinned_panel {"
        "position: sticky; top: 3.75rem; z-index: 1000;"
        "max-height: 82vh; overflow-y: auto;"
        f"background: {background};"
        "box-shadow: 0 6px 18px rgba(0,0,0,0.12); border-radius: 0.5rem;"
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
        st.markdown("**统一存档 / 加载**")
        st.caption(f"暂无已保存的模拟。在「导出分析数据」中保存后，存档会写入 {RUNS_DIR}。")
        return
    st.divider()
    st.markdown("**统一存档 / 加载**")
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
        if st.button("加载该存档", width="stretch"):
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
    st.markdown("**载入 / 复现**")
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
            st.markdown("**统一存档**")
            st.caption(
                f"写入 archive/runs/　引擎 {ENGINE_VERSION}　格式 {RUN_SCHEMA_VERSION}"
            )
            default_name = f"sim_seed{st.session_state.get('seed')}_g{simulation.generation}"
            save_name = st.text_input(
                "存档名称（可留空自动命名）", placeholder=default_name, key="save_name_input"
            )
            save_note = st.text_input("备注（可选）", key="save_note_input")
            if st.button("保存当前模拟", width="stretch"):
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
            st.markdown("**策略库**")
            live_codes = list({item.encoding for item in simulation.species})
            if live_codes:
                pick_code = st.selectbox("选择要保存的策略", live_codes, key="save_strat_pick")
                if st.button("保存到策略库", width="stretch"):
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
    background = st.get_option("theme.backgroundColor")
    if not background:
        background = "#0e1117" if st.get_option("theme.base") == "dark" else "#ffffff"
    return (
        "<style>"
        ".st-key-detail_float {"
        "position: fixed; right: 1rem; bottom: 1rem; width: min(380px, 92vw);"
        "max-height: 72vh; overflow-y: auto; z-index: 100000;"
        f"background: {background};"
        "border: 1px solid rgba(128,128,128,0.35); border-radius: 0.6rem;"
        "box-shadow: 0 8px 28px rgba(0,0,0,0.18); padding: 0.5rem 0.8rem;"
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
            f"{event['color']};background:#fafafa;font-size:13px;'>"
            f"<b style='color:{event['color']}'>{event['事件']}</b>　"
            f"{event['编码']}　"
            f"<span style='color:#888;'>父代 {event['父代']}</span></div>",
            unsafe_allow_html=True,
        )


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

    alive = 0
    for data in record.species_data.values():
        subspecies = data.get("subspecies")
        total = data.get("population_size", 0) + (
            subspecies["size"] if subspecies else 0
        )
        if total > 0:
            alive += 1
    metric_a, metric_b, metric_c = st.columns(3)
    metric_a.metric("存活策略", alive)
    metric_b.metric("平均适应度", f"{record.average_fitness:.2f}")
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
        area.add_vline(x=view_gen, line_color="#333333", line_width=2)
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

        # Saving is kept; the "hand it to the AI" button is not. The creation
        # mode reads the run in place from the visitor's own wallet, so exporting
        # a file and submitting it by hand is now a second way to reach the same
        # report. The code that path used is left below, unused but intact.
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
        if False:
            if st.button("📊 保存并交给 AI", width="stretch"):
                path = save_markdown_report(
                    simulation, st.session_state.get("seed"), simulation.generation,
                    name=run_name or "run",
                    note=run_note or None,
                )
                try:
                    doc = load_document(path)
                    st.session_state["latest_analysis_report"] = {
                        "path": str(path),
                        "text": bundle_to_markdown(doc),
                        "meta": doc["summary"],
                        "engine_version": doc["engine_version"],
                    }
                except Exception as error:  # noqa: BLE001 - surface message to user
                    st.error(f"读取失败：{error}")
                else:
                    st.success(f"已保存统一存档：{path.name}")

        if st.session_state.get("latest_analysis_report"):
            info = st.session_state["latest_analysis_report"]
            with st.expander("📄 已保存的存档（AI 将读这份数据）", expanded=False):
                st.code(info["path"], language="text")
                st.caption(
                    "引擎版本 {}　种子 {}　代数 {}　手动注入 {} 次".format(
                        info.get("engine_version"),
                        (info.get("meta") or {}).get("seed"),
                        (info.get("meta") or {}).get("generations"),
                        (info.get("meta") or {}).get("injections"),
                    )
                )
                st.text_area(
                    "下面是从该存档渲染出的 Markdown 视图（仅供人读；"
                    "AI 直接读同目录的 .tev.json 即可，无需依赖这段文本）：",
                    info["text"],
                    height=240,
                )
        elif st.toggle("预览 Markdown 视图"):
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

    st.markdown(theme.payoff_chips(), unsafe_allow_html=True)

    st.markdown('<div id="tf_about"></div>', unsafe_allow_html=True)
    st.markdown(
        theme.section("这个网站在做什么", "一句话：一个能让你亲手验证「合作划不划算」的模拟器"),
        unsafe_allow_html=True,
    )
    st.markdown(theme.prose_card(LANDING_WHY), unsafe_allow_html=True)
    st.markdown(theme.architecture(LANDING_ARCH), unsafe_allow_html=True)

    st.markdown(
        theme.section("怎么玩", "第一次建议从游戏模式开始，全程约 8 分钟"),
        unsafe_allow_html=True,
    )
    st.markdown(theme.steps(LANDING_STEPS), unsafe_allow_html=True)

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
        theme.section("看到这些词不用慌", "站内术语对照，30 秒扫一遍就够"),
        unsafe_allow_html=True,
    )
    st.markdown(theme.glossary(LANDING_GLOSS), unsafe_allow_html=True)

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

#: URL 参数名，用来把对局进度带在地址栏里。
GAME_PARAM = "g"
_PAYLOAD_VERSION = "v1"


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


def _game_payload() -> str | None:
    """把整局编码成 ``v1.对手数.轮数.种子.各局决策``。

    种子决定对手组合，引擎又是确定性的——实测同种子 + 同决策重放，对手行为、
    双方得分、profile 全部一致。所以只需要存**玩家自己的决策**：URL 长度控制在
    一两百字符，却能让进度扛过刷新、新标签页，以及中途切走再回来。
    """
    setup = st.session_state.get(GAME_SETUP_KEY)
    codes = st.session_state.get(GAME_CODES_KEY)
    if not setup or not codes:
        return None
    acts = [m.player_actions for m in (st.session_state.get(GAME_MATCHES_KEY) or [])]
    runner = st.session_state.get(GAME_RUNNER_KEY)
    if runner is not None:
        acts.append("".join(decision.action for decision in runner.decisions))
    return ".".join(
        [_PAYLOAD_VERSION, str(setup["count"]), str(setup["turns"]), str(setup["seed"])]
        + acts
    )


def _query_value(key: str) -> str | None:
    """``st.query_params`` 对重复键会返回列表，这里统一取单个字符串。"""
    value = st.query_params.get(key)
    if isinstance(value, list):
        value = value[0] if value else None
    return value


def _persist_game() -> None:
    """把当前进度镜像进 URL。值没变时不写，避免多余的重跑。"""
    payload = _game_payload()
    if payload and _query_value(GAME_PARAM) != payload:
        st.query_params[GAME_PARAM] = payload


def _clear_persisted_game() -> None:
    if GAME_PARAM in st.query_params:
        del st.query_params[GAME_PARAM]


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
    if len(parts) < 4 or parts[0] != _PAYLOAD_VERSION:
        _clear_persisted_game()
        return
    try:
        count, turns, seed = int(parts[1]), int(parts[2]), int(parts[3])
    except ValueError:
        _clear_persisted_game()
        return
    acts = parts[4:]

    codes = draw_opponents(count, seed)
    matches: list = []
    done: list = []
    runner = None
    for index, code in enumerate(codes):
        match_runner = PlayerMatchRunner(
            index=index, opponent=code, turns=turns, seed=seed + 1 + index
        )
        for action in (acts[index] if index < len(acts) else ""):
            if match_runner.finished:
                break
            match_runner.play(action)
        if match_runner.finished:
            finished = match_runner.finish()
            matches.append(finished)
            done.append(_match_summary(finished))
        else:
            # 这一局还没打完：恢复成正在进行的对局。
            runner = match_runner
            break

    st.session_state[GAME_SETUP_KEY] = {"count": count, "turns": turns, "seed": seed}
    st.session_state[GAME_CODES_KEY] = codes
    st.session_state[GAME_MATCHES_KEY] = matches
    st.session_state[GAME_DONE_KEY] = done
    st.session_state[GAME_RUNNER_KEY] = runner
    st.session_state["app_mode"] = MODE_GAME
    # 恢复出来的一局必然已经过了教学，否则每刷新一次都要重学一遍。
    st.session_state[GAME_TUTORIAL_DONE] = True

    if len(matches) >= len(codes):
        st.session_state["game_phase"] = "results"
        _game_finish()
    else:
        st.session_state["game_phase"] = "play"


def _game_start(count: int, turns: int, seed: int) -> None:
    """Deal opponents and prime the first match."""
    codes = draw_opponents(count, seed)
    st.session_state[GAME_CODES_KEY] = codes
    st.session_state[GAME_MATCHES_KEY] = []
    st.session_state[GAME_RESULTS_KEY] = None
    st.session_state[GAME_PROFILE_KEY] = None
    st.session_state["game_phase"] = "play"
    st.session_state[GAME_RUNNER_KEY] = PlayerMatchRunner(
        index=0, opponent=codes[0], turns=turns, seed=seed + 1
    )


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


def _render_game_setup() -> None:
    st.markdown("### 第一步：设置这一局")
    st.caption(
        "你将依次与 {} 个随机策略对局，每局 {} 轮。"
        "每一步都要你自己选择合作或背叛——事后分析会逐步检查这些选择。".format(
            st.session_state.get("game_opponents", 10),
            st.session_state.get("game_turns", 10),
        )
    )
    count = st.slider("对手数量", 4, 12, 10, 1, key="game_opponents")
    turns = st.slider("每局轮数", 5, 20, 10, 1, key="game_turns")
    seed_text = st.text_input(
        "随机种子", value=str(random.SystemRandom().randrange(0, 10 ** 9)),
        help="同一种子会生成同一组对手，便于复现。",
        key="game_seed",
    )
    if st.button("开始", type="primary", width="stretch"):
        try:
            seed = int(seed_text.strip())
        except ValueError:
            st.error("种子必须是整数")
            return
        st.session_state[GAME_SETUP_KEY] = {"count": count, "turns": turns, "seed": seed}
        _game_start(count, turns, seed)
        st.rerun()


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
                if st.button("🤝 合作", key="play_c", width="stretch",
                             type="primary"):
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
        _render_completed_match(prompt, runner)
        # The last settlement must not offer 下一局: the run has one screen left,
        # and a player who pressed the always-same label expected another opponent
        # and got a report instead.
        is_last = len(matches) + 1 >= len(codes)
        reveal_col, next_col = st.columns([3, 2], vertical_alignment="bottom")
        with reveal_col:
            st.markdown(identity_card(prompt["opponent"]), unsafe_allow_html=True)
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
                turns=played, highlight=played - 1,
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
                turns=match.turns,
            ),
            unsafe_allow_html=True,
        )
        st.caption(
            "对手编码 `{}`　你 {} 分，它 {} 分。".format(
                match.opponent, int(match.player_score),
                int(match.opponent_score))
        )
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
        st.caption("展开任意一局，可以看双方每一轮选了什么、拿到多少分。")
        for row in done:
            gap = row["你"] - row["对手分"]
            verdict = "领先" if gap > 0 else ("落后" if gap < 0 else "持平")
            with st.expander(
                "第 {} 局　{}　{} : {}　{}".format(
                    row["局次"], row["对手"], row["你"], row["对手分"], verdict),
                expanded=False,
            ):
                _replay_table(row)


def _render_completed_match(prompt: dict, runner: PlayerMatchRunner) -> None:
    """The match that just ended: its full per-turn record and the final score."""
    finished = runner.finish()
    st.markdown("---")
    st.markdown("### 本局记录")
    _score_bar(runner, len(runner.decisions))
    st.markdown(
        history_table(
            finished.player_actions, finished.opponent_actions,
            turns=finished.turns, highlight=finished.turns - 1,
        ),
        unsafe_allow_html=True,
    )


def _render_game_results() -> None:
    results = st.session_state[GAME_RESULTS_KEY]
    profile = st.session_state[GAME_PROFILE_KEY]
    st.markdown("### 你的成绩")
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

    st.markdown("### 平均总得分")
    st.caption("「对其他策略」为该策略与其余 {} 个策略的平均得分；「对玩家」为它在你手上的平均得分。".format(
        len(results["table"]) - 1
    ))
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
    st.markdown("### 逐局记录")
    st.caption("蓝点为合作，橙点为背叛。上下两行同一列即同一轮，逐局明细请看每一局的「本局记录」。")
    st.markdown(matches_overview(profile["matches"]), unsafe_allow_html=True)

    st.divider()
    if st.button("查看行为分析", type="primary", width="stretch"):
        st.session_state["game_phase"] = "profile"
        st.rerun()


def _render_game_profile() -> None:
    profile = st.session_state[GAME_PROFILE_KEY]
    results = st.session_state[GAME_RESULTS_KEY]
    st.markdown("### 行为分析")
    st.caption(
        "以下每一项都是对你 {} 步决策的测量，附具体场次轮次证据，"
        "并写明什么观察能推翻它。下面的「出牌风格」是这些测量的归纳，"
        "描述你在这十局里怎么出牌——不是心理诊断，也不给人格类型。".format(
            profile["total_turns"]
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

    # The score cards come first on purpose. A player should be able to read
    # where they stand before reading a single paragraph about why.
    st.markdown("### 你的九项维度")
    st.caption(
        "先看整体位置，再往下看细节。**注意每项方向不同**："
        "「回击倾向」高表示被背叛必还手，「单步收益效率」高才表示不浪费机会。"
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
    st.markdown("## 新手教程")
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
    lead_word = "领先 %d 分" % abs(int(margin)) if margin else "持平"
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
    # 每次渲染都把进度镜像进地址栏。放在最前面，是因为下面每一处 return 都会
    # 提前离开，写在这里才能覆盖所有分支（对战中、成绩页、行为分析页）。
    _persist_game()
    # The motif belongs to this layer rather than the page: on the page it
    # ran under every control, and the border version of the sheet doubled
    # up where its strips overlapped.
    with st.container(key="tf_game_layer"):
        st.markdown("## 🎮 游戏模式")
        st.caption(
            "与 {} 个随机生成的策略对局，逐步自己选择；结束后得到得分矩阵和行为分析。"
            .format(st.session_state.get("game_opponents", 10))
        )
        top_col, mid_col, end_col = st.columns(3)
        with top_col:
            if st.button("← 返回模式选择", key="game_back", width="stretch"):
                for key in (GAME_SETUP_KEY, GAME_CODES_KEY, GAME_RUNNER_KEY,
                            GAME_MATCHES_KEY, GAME_DONE_KEY, GAME_RESULTS_KEY, GAME_PROFILE_KEY,
                            GAME_AI_KEY, GAME_CARD_KEY, GAME_TUTORIAL_KEY,
                            GAME_TUTORIAL_DONE, TUTORIAL_RUNNER_KEY):
                    st.session_state.pop(key, None)
                st.session_state["app_mode"] = None
                _clear_persisted_game()
                st.rerun()
        with mid_col:
            if st.session_state.get(GAME_MATCHES_KEY) and st.button(
                "重新开始", key="game_restart", width="stretch"
            ):
                for key in (GAME_SETUP_KEY, GAME_CODES_KEY, GAME_RUNNER_KEY,
                            GAME_MATCHES_KEY, GAME_DONE_KEY, GAME_RESULTS_KEY, GAME_PROFILE_KEY,
                            GAME_AI_KEY, GAME_CARD_KEY, GAME_TUTORIAL_DONE):
                    st.session_state.pop(key, None)
                _clear_persisted_game()
                st.rerun()
        with end_col:
            phase = st.session_state.get("game_phase", "setup")
            st.caption("当前阶段：{}".format({
                "setup": "设置", "play": "对战中", "results": "成绩", "profile": "行为分析",
            }.get(phase, phase)))

        st.divider()
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

    # 地址栏里带着一局的话，先把它重放回 session_state，再决定渲染哪个模式。
    # 必须在读 ``app_mode`` 之前，否则会先落到模式选择页。
    _restore_game_from_url()

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
    # The sidebar radio has run by now, so the chosen mode is known.
    stylesheet = responsive_css(_layout_mode())
    if stylesheet:
        st.markdown(stylesheet, unsafe_allow_html=True)
    # Injected after the responsive sheet on purpose: the viewer must win the
    # specificity contest over the compact 320px chart cap.
    if st.session_state.get("heatmap_fullscreen") is not None:
        st.markdown(fullscreen_css(), unsafe_allow_html=True)
    render_main()


if __name__ == "__main__":
    main()
