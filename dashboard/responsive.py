"""Responsive styling for The Fittest dashboard.

The desktop layout is the reference: a pinned module stuck to the top of the
viewport and a detail window floating over the bottom-right corner. Both are
excellent on a wide screen and unusable on a phone -- they cover the content
you are trying to read.

Three modes are offered in the sidebar:

``auto``
    (default) injects every rule inside a ``@media (max-width: 860px)`` block, so
    a phone gets the mobile treatment and a desktop is untouched. Structural
    changes that CSS cannot express still follow Streamlit's own behaviour, which
    already stacks columns vertically on narrow viewports.
``mobile``
    forces the same rules without the media query, so the mobile layout can be
    previewed and debugged on a desktop browser.
``desktop``
    injects nothing; the original desktop layout.
"""

from __future__ import annotations

from dashboard import theme

# Below this width (CSS px) the auto mode switches to the phone treatment.
MOBILE_BREAKPOINT = 860

MODE_AUTO = "auto"
MODE_MOBILE = "mobile"
MODE_DESKTOP = "desktop"

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
    """True when the mobile layout must be applied regardless of screen width."""
    return mode == MODE_MOBILE


def _body_rules() -> str:
    """Everything that only makes sense to restyle, not to restructure."""
    return """
/* Larger tap targets and readable body text on a phone. */
.stMainBlockContainer, .stBlockContainer {
    padding-left: 0.6rem; padding-right: 0.6rem;
    padding-top: 3.2rem; padding-bottom: 2rem;
}
.stMainBlockContainer p, .stMarkdown, .stMarkdown p {
    font-size: 0.95rem; line-height: 1.65;
}
h1, .stMarkdown h1 { font-size: 1.35rem !important; }
h2, .stMarkdown h2 { font-size: 1.15rem !important; }
h3, .stMarkdown h3 { font-size: 1.02rem !important; }
/* Streamlit renders buttons at a fixed 2.6rem; grow them for thumbs. */
.stButton button, .stDownloadButton button, .stLinkButton a {
    min-height: 2.9rem; font-size: 0.95rem; padding: 0.35rem 0.6rem;
}
.stTextInput input, .stNumberInput input, .stTextArea textarea {
    font-size: 1rem; min-height: 2.7rem;
}
/* Selectboxes and the generation jump are the most-used controls. */
div[data-baseweb="select"] > div { font-size: 0.95rem; min-height: 2.7rem; }

/* Metrics sit three-across on desktop; shrink them so they stay legible. */
div[data-testid="stMetric"] {
    padding: 0.35rem 0.45rem; min-height: 4.4rem;
}
div[data-testid="stMetricValue"] { font-size: 1.25rem !important; }
div[data-testid="stMetricLabel"] { font-size: 0.72rem !important; }

/* Dataframes keep their columns but get a compact font and an obvious
   horizontal scroll affordance instead of silently clipping. */
div[data-testid="stDataFrame"] { font-size: 0.8rem; }
div[data-testid="stDataFrame"] * { font-size: 0.8rem; }
div[data-testid="stDataFrame"] .glide-data-grid {
    scrollbar-width: thin;
}

/* The sidebar eats a phone's whole width; let it overlay instead of squeeze. */
section[data-testid="stSidebar"] {
    max-width: 88vw; z-index: 100001;
}
section[data-testid="stSidebar"] .block-container {
    padding-top: 3rem;
}

/* Dialogs (project notes, strategy notes) go full width on a phone. */
div[role="dialog"] { max-width: 94vw !important; }

/* Plotly mode bars take a lot of a small screen; tap-to-zoom still works. */
.js-plotly-plot .modebar { display: none !important; }
"""


def _pin_rules() -> str:
    """The pinned module must not hover over the page on a phone."""
    return f"""
/* Pinned module: on a phone a sticky overlay hides the content it points at,
   so it collapses to a static block the user scrolls to deliberately. */
.st-key-pinned_panel {{
    position: static !important;
    top: auto !important;
    max-height: none !important;
    overflow-y: visible !important;
    box-shadow: none !important;
    border: 1px solid {theme.EDGE} !important;
    border-radius: 0.5rem;
}}
"""


def _detail_rules() -> str:
    """Turn the floating detail window into a dismissable bottom sheet."""
    return f"""
/* Detail window: bottom sheet. Full width, anchored, scrollable, and it never
   covers more than the lower half of the viewport. */
.st-key-detail_float {{
    position: fixed !important;
    left: 0 !important; right: 0 !important; bottom: 0 !important;
    top: auto !important;
    width: 100% !important;
    max-width: 100% !important;
    max-height: 55vh !important;
    overflow-y: auto !important;
    -webkit-overflow-scrolling: touch;
    z-index: 100000;
    border-radius: 0.9rem 0.9rem 0 0 !important;
    border-left: none !important; border-right: none !important;
    border-bottom: none !important;
    box-shadow: {theme.SHADOW_SHEET} !important;
    padding: 0.7rem 0.9rem 1.2rem !important;
}}
.st-key-detail_float::before {{
    content: "";
    display: block; width: 38px; height: 4px; margin: 0 auto 0.5rem;
    border-radius: 2px; background: {theme.GRIP};
}}
/* Leave room for the sheet so the last content row is never trapped. */
.st-key-detail_float ~ * {{ padding-bottom: 0; }}
"""


def _tooltip_rules() -> str:
    """Make the tap readout on a heatmap a wide strip instead of a tall box.

    Plotly sizes the hover label to its text, so on a phone the two long Chinese
    strategy names wrap into a narrow, tall bubble that covers the very cell
    being inspected. Stretching the label to most of the viewport turns it into
    a horizontal strip: the names read left to right, and fewer lines are hidden
    under the finger.
    """
    return """
/* Plotly draws the hover label as an SVG rect + text. Width is a presentation
   attribute in SVG 2 and honoured by current Chrome/Safari, so the label can be
   widened without touching the chart. */
.hoverlayer rect.hoverbg, .hoverlayer g.hovertext rect {
    min-width: 74vw !important;
}
/* Keep the text left-aligned inside the widened box. */
.hoverlayer .hovertext { text-anchor: start !important; }
.hoverlayer text.hovertext { font-size: 12px !important; }
/* Never let the strip run off the side of the screen. */
.hoverlayer { max-width: 100vw !important; }
"""


def _chart_rules() -> str:
    return """
/* Charts need a shorter default height or a phone shows a letterbox strip. */
.js-plotly-plot { height: 320px !important; }
.st-key-detail_float ~ .stPlotlyChart { padding-bottom: 1rem; }
/* Expander headers are primary navigation on a phone. */
details[data-testid="stExpander"] summary { font-size: 0.95rem; padding: 0.5rem 0; }
"""


def fullscreen_css() -> str:
    """Styling for the whole-page heatmap viewer.

    The viewer is not a dialog, so there is no overlay to fight: the page itself
    is the viewer. What is left is Streamlit's own furniture -- the top bar, the
    sidebar and the main container's padding -- all of which steal height and
    width from the matrix on a phone.
    """
    rules = """
/* Hide Streamlit's chrome so the matrix owns the whole screen. */
header[data-testid="stHeader"],
div[data-testid="stToolbar"],
div[data-testid="stDecoration"],
div[data-testid="stStatusWidget"] { display: none !important; }
section[data-testid="stSidebar"],
div[data-testid="stSidebarCollapsedControl"] { display: none !important; }
/* Reclaim the sidebar's reserved width. */
.stMain, .stApp [data-testid="stMainBlockContainer"] { margin-left: 0 !important; }
.stMainBlockContainer, .stBlockContainer {
    padding: 0.25rem 0.3rem !important;
    /* Real headroom, not just the safe-area inset. A mobile browser's own
       header covers roughly 100px of the viewport, and a chart whose top
       margin holds upright tick labels gets clipped behind it otherwise. */
    padding-top: 6rem !important;
    max-width: 100vw !important;
}
/* The compact 320px chart cap must not apply to the viewer: more specific
   selector plus !important, and it comes after the responsive sheet. */
.stMain .js-plotly-plot, .stMain .plot-container { height: auto !important; }
.stMain .stPlotlyChart { width: 100% !important; }
.stMain .modebar { display: none !important; }
/* Keep the exit button a comfortable thumb target. */
.stMain .stButton button { min-height: 2.6rem; }
/* The tap readout has to be a wide strip here too, independently of the
   responsive sheet, since the viewer can be reached from either mode. */
.hoverlayer rect.hoverbg, .hoverlayer g.hovertext rect { min-width: 78vw !important; }
.hoverlayer .hovertext { text-anchor: start !important; }
.hoverlayer text.hovertext { font-size: 12px !important; }
"""
    # Wrapped like responsive_css: st.markdown does not add <style> itself, so
    # returning bare CSS would silently do nothing.
    return "<style>{}</style>".format(rules)


def responsive_css(mode: str) -> str:
    """Return the stylesheet for ``mode`` (empty string for desktop)."""
    if mode == MODE_DESKTOP:
        return ""
    rules = (
        _body_rules()
        + _pin_rules()
        + _detail_rules()
        + _chart_rules()
        + _tooltip_rules()
    )
    if mode == MODE_MOBILE:
        return "<style>{}</style>".format(rules)
    return "<style>@media (max-width: {}px){{{}}}</style>".format(
        MOBILE_BREAKPOINT, rules
    )
