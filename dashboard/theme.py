"""Visual layer for The Fittest.

The palette is warm rather than the cold white Streamlit ships with: a paper
ground (#FBF7F0) with ink-brown text, which suits a page you read and scroll
through rather than a dashboard you glance at. The three accent colours are the
ones already in the brand icon -- a non-transitive cycle in orange / blue /
green. That cycle is also the subject matter, so the same three carry the same
meanings here: orange is defection, blue is cooperation, green is a settled
mutual outcome.

Every colour is derived from ``GROUND``/``INK`` below rather than repeated as
literals, so re-theming stays a matter of editing six values.

The choice buttons carry more than colour: the icon and the word are in the
label, so the action is still unambiguous in greyscale, on a phone, or for a
reader who cannot rely on hue.
"""

from __future__ import annotations

# Warm paper ground, not the default cool white.
GROUND = "#FBF7F0"
SURFACE = "#FFFFFF"
RAISED = "#F5EFE4"
INK = "#241F1A"
MUTED = "#6B6156"
LINE = "#E4DACA"

# The brand triad. Mirrors docs/brand/build_icon.py.
COOP = "#2E7DE4"
DEFECT = "#E4572E"
MUTUAL = "#21A179"

# Washes used behind badges and the highlight row, kept light enough that the
# label inside them still meets contrast on the paper ground.
COOP_WASH = "#E7F0FC"
DEFECT_WASH = "#FCEAE2"
MUTUAL_WASH = "#E4F3EE"

FONT_STACK = (
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', "
    "'Hiragino Sans GB', 'Microsoft YaHei', 'Source Han Sans SC', "
    "'Noto Sans CJK SC', serif"
)


# The payoff-matrix motif. Injected into the document head rather than through
# st.markdown: Streamlit renders widgets inside a shadow root, so a stylesheet
# written by st.markdown cannot reach the page containers at all.
BACKGROUND_SVG = "app/static/background.svg"

# Page ground: the motif runs across the whole page, but so faintly that it
# reads as paper tooth rather than decoration. The previous version confined it
# to the game layer, which left a hard rectangular edge and wide empty margins;
# the layer now carries a frame instead, so the two combine into a board set on
# a textured page rather than a picture cut out of a blank one.
BACKGROUND_CSS = "\n".join([
    "html, body, .stApp, [data-testid=\"stAppViewContainer\"] {",
    "  background-image: url(\"%s\");" % BACKGROUND_SVG,
    "  background-repeat: repeat;",
    "  background-position: center top;",
    "  background-size: min(1440px, 100%) auto;",
    "  background-attachment: scroll;",
    "  background-color: #FBF7F0;",
    "}",
    "[data-testid=\"stSidebar\"] {",
    "  background-color: rgba(251, 247, 240, .94);",
    "}",
])

# The game layer sits on the page as a framed board: it clears the texture to
# its own paper tone, so the play area stays quiet, and takes a thin border to
# mark where the board begins.
#
# A keyed container is rendered as a class (`st-key-<name>`), not as a
# data-testid, so the selector has to match the class.
GAME_BACKGROUND_CSS = "\n".join([
    ".st-key-tf_game_layer {",
    "  background-image: none;",
    "  background-color: rgba(253, 250, 245, .82);",
    "  border: 1px solid #E4DACA;",
    "  border-radius: 18px;",
    "  box-shadow: 0 1px 3px rgba(60,45,25,.05);",
    "  padding: 1.25rem 1.4rem 1.5rem;",
    "}",
])


def inject_background() -> None:
    """Attach the motif to the document head, outside any shadow root."""
    import json

    import streamlit as st

    script = (
        "(function(){var s=document.getElementById('tf-background');"
        "if(!s){s=document.createElement('style');"
        "s.id='tf-background';document.head.appendChild(s);}"
        "s.textContent=%s;})();" % json.dumps(
            BACKGROUND_CSS + "\n" + GAME_BACKGROUND_CSS)
    )
    try:
        st.components.html("<script>%s</script>" % script, height=0)
        return
    except Exception:
        pass
    st.markdown(
        "<style id='tf-background'>%s</style>"
        % (BACKGROUND_CSS + "\n" + GAME_BACKGROUND_CSS),
        unsafe_allow_html=True,
    )


def inject() -> None:
    """Apply the stylesheet. Safe to call on every rerun."""
    import streamlit as st

    st.markdown("<style>%s</style>" % stylesheet(), unsafe_allow_html=True)


def stylesheet() -> str:
    return """
<style>
/* The page ground. Streamlit sets this on .stApp and on several nested
   wrappers, so each is covered explicitly. */
html, body, [data-testid="stAppViewContainer"],
.stApp, .main, [data-testid="stMainBlockContainer"] {
  background: #FBF7F0;
  color: #241F1A;
}

html, body, .stApp, [class*="css"] {
  font-family: %(font)s;
  color: #241F1A;
}

/* --- Masthead ---------------------------------------------------------- */
.tf-hero {
  position: relative;
  border: 1px solid #E4DACA;
  border-left: 5px solid #2E7DE4;
  border-radius: 4px 16px 16px 4px;
  padding: 1.7rem 1.9rem 1.5rem;
  background:
    linear-gradient(120deg, rgba(46,125,228,.06) 0%%,
                            rgba(228,87,46,.05) 55%%,
                            rgba(33,161,121,.05) 100%%),
    #FFFFFF;
  margin-bottom: 1.5rem;
  box-shadow: 0 1px 3px rgba(60,45,25,.05);
}
.tf-hero h1 {
  margin: 0 0 .4rem 0;
  font-size: 2.25rem;
  line-height: 1.12;
  letter-spacing: -.02em;
  font-weight: 700;
  color: #241F1A;
}
.tf-hero p {
  margin: 0;
  color: #6B6156;
  font-size: 1.03rem;
  line-height: 1.65;
  max-width: 62ch;
}
.tf-eyebrow {
  display: inline-block;
  font-size: .73rem;
  letter-spacing: .18em;
  text-transform: uppercase;
  color: #6B6156;
  font-weight: 700;
  margin-bottom: .55rem;
}
.tf-rule {
  display: inline-flex;
  gap: 1.3rem;
  flex-wrap: wrap;
  margin-top: 1.1rem;
  padding-top: .95rem;
  border-top: 1px solid #E4DACA;
  font-size: .88rem;
  color: #6B6156;
}
.tf-rule b { color: #241F1A; font-weight: 650; }
.tf-dot {
  display: inline-block;
  width: .62rem; height: .62rem;
  border-radius: 50%%;
  margin-right: .4rem;
  vertical-align: baseline;
}
.tf-dot--coop { background: #2E7DE4; }
.tf-dot--defect { background: #E4572E; }
.tf-dot--mutual { background: #21A179; }

/* --- Typography -------------------------------------------------------- */
h1, h2, h3, h4 { color: #241F1A; letter-spacing: -.012em; }
h2 {
  margin-top: 1.9rem;
  padding-bottom: .45rem;
  border-bottom: 2px solid #E4DACA;
  font-weight: 680;
}
/* `label` is deliberately excluded here. Streamlit renders a button's caption
   inside a <label>, so setting line-height on it made the caption taller than
   the fixed min-height on the button and the text was clipped away, leaving the
   bare emoji. */
p, li { color: #241F1A; font-size: .97rem; line-height: 1.7; }
.stCaption, [data-testid="stCaptionContainer"] { color: #6B6156; }
a { color: #2E7DE4; }

/* --- Buttons ----------------------------------------------------------- */
.stButton > button, .stDownloadButton > button, .stLinkButton > a {
  border-radius: 10px;
  font-weight: 620;
  color: #241F1A;
  background: #FFFFFF;
  border: 1px solid #E4DACA;
  transition: transform .08s ease, box-shadow .15s ease,
              background .15s ease, border-color .15s ease;
  box-shadow: 0 1px 2px rgba(60,45,25,.06);
}
/* Streamlit renders a button's caption inside a <label> nested in the button,
   and its wrapper has changed between releases -- a `button > label` rule
   matched for a while and then silently stopped applying, which is why the
   caption was clipped down to a bare emoji. Rather than keep guessing the
   wrapper, these rules match the label through its parent test id and reset
   every box metric that could push it out of a fixed-height button. The
   `!important` is deliberate: this has to beat Streamlit's own component
   stylesheet, which is what was doing the clipping. */
[data-testid="stButton"] label,
[data-testid="stDownloadButton"] label,
[data-testid="stLinkButton"] label {
  line-height: 1.3 !important;
  padding: 0 !important;
  margin: 0 !important;
  font-weight: inherit !important;
  font-size: inherit !important;
  color: inherit !important;
  height: auto !important;
  min-height: 0 !important;
  max-height: none !important;
  overflow: visible !important;
  display: inline-block !important;
  vertical-align: middle !important;
}
[data-testid="stButton"] > button,
[data-testid="stDownloadButton"] > button,
[data-testid="stLinkButton"] > a {
  overflow: hidden;
  white-space: nowrap;
  align-items: center;
}
.stButton > button:hover {
  transform: translateY(-1px);
  box-shadow: 0 3px 10px rgba(60,45,25,.10);
  border-color: #D8CBB4;
}
.stButton > button:active { transform: translateY(0); }
.stButton > button:focus-visible {
  outline: 2px solid #2E7DE4;
  outline-offset: 2px;
}
.stButton > button[kind="primary"] {
  background: #2E7DE4;
  color: #FFFFFF;
  border-color: #2E7DE4;
}
.stButton > button[kind="primary"]:hover {
  background: #2469C7;
  border-color: #2469C7;
  color: #FFFFFF;
}

/* The two in-match choices.
   Neither keeps a permanent tint: cooperation used to be solid blue
   whatever the advice, so the two never looked like peers. Hover fills
   the button with its own action colour; the advised one is filled
   without hovering, driven by the badge class -- swapping the
   container key does not work, since Streamlit reuses the element when
   only its key changes. */
.st-key-tf_move_coop button,
.st-key-tf_move_defect button {
  min-height: 3.5rem !important;
  height: auto !important;
  padding-top: .75rem !important;
  padding-bottom: .75rem !important;
  font-size: 1.03rem !important;
  border-width: 1.5px !important;
  background: #FFFFFF !important;
  background-color: #FFFFFF !important;
  border-color: #D8CBB4 !important;
  color: #6B6156 !important;
}
.st-key-tf_move_coop button:hover {
  background: #2E7DE4 !important;
  background-color: #2E7DE4 !important;
  border-color: #2E7DE4 !important;
  color: #FFFFFF !important;
}
.st-key-tf_move_defect button:hover {
  background: #E4572E !important;
  background-color: #E4572E !important;
  border-color: #E4572E !important;
  color: #FFFFFF !important;
}
.st-key-tf_move_coop:has(.tf-rec--on) button {
  background: #2E7DE4 !important;
  background-color: #2E7DE4 !important;
  border-color: #2E7DE4 !important;
  color: #FFFFFF !important;
  box-shadow: 0 3px 14px rgba(46,125,228,.3) !important;
}
.st-key-tf_move_defect:has(.tf-rec--on) button {
  background: #E4572E !important;
  background-color: #E4572E !important;
  border-color: #E4572E !important;
  color: #FFFFFF !important;
  box-shadow: 0 3px 14px rgba(228,87,46,.3) !important;
}
.st-key-tf_move_coop button {
  background: #2E7DE4;
  color: #FFFFFF;
  border-color: #2E7DE4;
  box-shadow: 0 2px 8px rgba(46,125,228,.24);
}
.st-key-tf_move_coop button:hover {
  background: #2469C7;
  border-color: #2469C7;
  color: #FFFFFF;
}
.st-key-tf_move_defect button {
  background: #FFFFFF;
  color: #E4572E;
  border: 1.5px solid #E4572E;
}
.st-key-tf_move_defect button:hover {
  background: #E4572E;
  color: #FFFFFF;
}

/* Running score. A player wants this after every turn, and it used to live
   only inside the history table further down the page. */
.tf-score {
  display: flex;
  align-items: baseline;
  gap: .55rem;
  flex-wrap: wrap;
  padding: .6rem .9rem;
  margin: .5rem 0 .7rem;
  border: 1px solid #E4DACA;
  border-radius: 10px;
  background: #FFFFFF;
  font-variant-numeric: tabular-nums;
}
.tf-score__label {
  font-size: .74rem;
  letter-spacing: .1em;
  color: #6B6156;
  text-transform: uppercase;
  margin-right: .3rem;
}
.tf-score__you, .tf-score__them {
  font-size: .95rem;
  color: #241F1A;
}
.tf-score__you b { font-size: 1.4rem; color: #2E7DE4; }
.tf-score__them b { font-size: 1.4rem; color: #E4572E; }
.tf-score__colon {
  font-size: 1.2rem;
  color: #6B6156;
}
.tf-score__lead {
  font-size: .82rem;
  font-weight: 700;
  margin-left: .2rem;
}
.tf-score__turn {
  margin-left: auto;
  font-size: .78rem;
  color: #6B6156;
}

/* "建议" badge, placed directly under the button it marks. Both columns render
   one, so the two buttons keep identical vertical position. */
.tf-rec {
  display: inline-block;
  font-size: .74rem;
  letter-spacing: .06em;
  font-weight: 700;
  color: #FFFFFF;
  background: #241F1A;
  border-radius: 999px;
  padding: .2rem .62rem;
  margin-top: .4rem;
}
/* The reserved slot on the side without a recommendation. */
.tf-rec--off {
  visibility: hidden;
}

/* --- Cards and containers ---------------------------------------------- */
div[data-testid="stMetric"] {
  background: #FFFFFF;
  border: 1px solid #E4DACA;
  border-radius: 12px;
  padding: .9rem 1.05rem 1rem;
  box-shadow: 0 1px 2px rgba(60,45,25,.05);
}
div[data-testid="stMetricLabel"] { color: #6B6156; font-size: .82rem; }
div[data-testid="stMetricValue"] { color: #241F1A; font-weight: 680; }

div[data-testid="stVerticalBlockBorderWrapper"],
div[data-testid="stExpander"] {
  border: 1px solid #E4DACA !important;
  border-radius: 12px;
  background: #FFFFFF;
  overflow: hidden;
}
div[data-testid="stExpander"] summary { font-weight: 620; color: #241F1A; }

/* --- Inputs ------------------------------------------------------------ */
div[data-baseweb="select"] > div,
div[data-baseweb="input"] > div,
.stTextInput input, .stNumberInput input {
  background: #FFFFFF !important;
  border-color: #E4DACA !important;
  color: #241F1A !important;
  border-radius: 9px;
}
[data-testid="stSliderTickBarMin"], [data-testid="stSliderTickBarMax"] {
  color: #6B6156;
}

/* --- Tables ------------------------------------------------------------ */
div[data-testid="stDataFrame"], div[data-testid="stTable"] {
  border: 1px solid #E4DACA;
  border-radius: 10px;
  overflow: hidden;
  background: #FFFFFF;
}

/* --- Notices ----------------------------------------------------------- */
div[data-testid="stAlert"] {
  border-radius: 10px;
  border-left-width: 4px;
  background: #FFFFFF;
}
div[data-testid="stAlertInfo"] { background: #E7F0FC; }
div[data-testid="stAlertSuccess"] { background: #E4F3EE; }
div[data-testid="stAlertWarning"] { background: #F5EFE4; }
div[data-testid="stAlertError"] { background: #FCEAE2; }

/* --- Tabs -------------------------------------------------------------- */
button[data-baseweb="tab"] {
  color: #6B6156;
  font-weight: 600;
  padding: .55rem .1rem;
}
button[data-baseweb="tab"][aria-selected="true"] { color: #241F1A; }
div[data-baseweb="tab-highlight"] { background-color: #2E7DE4; }
div[data-baseweb="tab-border"] { background-color: #E4DACA; }

/* --- Sidebar ----------------------------------------------------------- */
section[data-testid="stSidebar"] {
  background: #F5EFE4;
  border-right: 1px solid #E4DACA;
}
section[data-testid="stSidebar"] * { color: #241F1A; }
section[data-testid="stSidebar"] .stCaption { color: #6B6156; }

/* --- Code -------------------------------------------------------------- */
code {
  background: #F5EFE4;
  border: 1px solid #E4DACA;
  border-radius: 5px;
  padding: .06em .36em;
  font-size: .88em;
  color: #241F1A;
}
hr { border-color: #E4DACA; }

/* --- Narrow screens ---------------------------------------------------- */
@media (max-width: 860px) {
  .tf-hero {
    padding: 1.2rem 1.15rem;
    border-radius: 4px 12px 12px 4px;
  }
  .tf-hero h1 { font-size: 1.6rem; }
  .tf-hero p { font-size: .95rem; }
  .tf-rule { gap: .8rem; font-size: .84rem; }
  .tf-move button, .st-key-tf_move_coop button,
  .st-key-tf_move_defect button { min-height: 3.2rem; font-size: .98rem; }
  h2 { font-size: 1.3rem; }
  p, li { font-size: .95rem; }
}
</style>
""" % {
        "ground": GROUND,
        "surface": SURFACE,
        "raised": RAISED,
        "ink": INK,
        "muted": MUTED,
        "line": LINE,
        "coop": COOP,
        "defect": DEFECT,
        "mutual": MUTUAL,
        "coop_wash": COOP_WASH,
        "defect_wash": DEFECT_WASH,
        "mutual_wash": MUTUAL_WASH,
        "font": FONT_STACK,
    }


CHART_BG = "#FFFFFF"
CHART_PAPER = "#FBF7F0"
CHART_GRID = "#EDE4D6"
CHART_FONT = "#241F1A"
CHART_TICK = "#6B6156"


def apply_chart_theme(fig):
    """Put a Plotly figure on the same paper ground as the page.

    Streamlit renders Plotly with its own light template, which paints a pure
    white card. Against the warm ground that reads as a hole in the page, so the
    paper and plot colours are set from the same values as the stylesheet.
    """
    fig.update_layout(
        paper_bgcolor=CHART_PAPER,
        plot_bgcolor=CHART_BG,
        font=dict(color=CHART_FONT),
        xaxis=dict(gridcolor=CHART_GRID, linecolor=CHART_GRID,
                   zerolinecolor=CHART_GRID, tickfont=dict(color=CHART_TICK)),
        yaxis=dict(gridcolor=CHART_GRID, linecolor=CHART_GRID,
                   zerolinecolor=CHART_GRID, tickfont=dict(color=CHART_TICK)),
        legend=dict(font=dict(color=CHART_TICK)),
        margin=dict(l=60, r=30, t=30, b=50),
    )
    return fig


def hero(eyebrow: str, title: str, lede: str, rules: list[tuple[str, str, str]]) -> str:
    """The masthead block shown at the top of the main views."""
    chips = "".join(
        '<span><span class="tf-dot tf-dot--%s"></span>%s <b>%s</b></span>'
        % (kind, label, value)
        for label, value, kind in rules
    )
    return (
        '<div class="tf-hero">'
        '<span class="tf-eyebrow">%s</span>'
        "<h1>%s</h1><p>%s</p>"
        '<div class="tf-rule">%s</div>'
        "</div>"
    ) % (eyebrow, title, lede, chips)