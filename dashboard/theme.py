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

from pathlib import Path

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

# The stack ends in sans-serif, not serif, and carries an emoji family before
# it. Titles use decorative emoji (🎮 / 🎛); with a serif fallback Windows
# renders them as tofu or desaturated monochrome, and the size and baseline
# drift against the surrounding text.
FONT_STACK = (
    "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', "
    "'Hiragino Sans GB', 'Microsoft YaHei', 'Source Han Sans SC', "
    "'Noto Sans CJK SC', 'Segoe UI Emoji', 'Apple Color Emoji', "
    "'Noto Color Emoji', sans-serif"
)

#: Where the heading sizes land. Streamlit's own scale puts ``h3`` above the
#: ``h1`` on views that render a plain markdown heading rather than the hero, so
#: the whole page reads inside-out. These four values are the ones the layout
#: was designed against and have to stay strictly decreasing.
H1_SIZE = "2.6rem"
H2_SIZE = "1.42rem"
H3_SIZE = "1.16rem"
H4_SIZE = "1.02rem"

#: Measure for the main column. Streamlit's centered layout is narrower than a
#: chart needs and its wide layout is a full browser window, which puts ~1400px
#: of text on one line; this is the width the page was laid out at.
CONTENT_WIDTH = "1280px"


# The landing illustration, read off disk and inlined. An ``<img>`` pointed at
# ``app/static/hero.svg`` only resolves under local ``streamlit run``: on Streamlit
# Cloud that path hits the edge node's generic shell instead of the file (see
# docs/deployment.md 4.4), so the first screen would ship a broken image. The SVG
# travels inside the repository, so a server-side read needs no static serving.
HERO_PATH = Path(__file__).parent / "static" / "hero.svg"

# Page ground: warm paper with two faint washes of the brand colours, one at the
# top-right and one at the bottom-left. The tiled payoff-matrix motif that used
# to sit here read as a watermark behind the text and made the first screen look
# grey, so the texture now stays inside the cards instead of the page.
BACKGROUND_CSS = "\n".join([
    "html, body, .stApp, [data-testid=\"stAppViewContainer\"] {",
    "  background-image:",
    "    radial-gradient(circle at 88% -6%, rgba(46,125,228,.07), transparent 46%),",
    "    radial-gradient(circle at 4% 104%, rgba(228,87,46,.06), transparent 44%);",
    "  background-repeat: no-repeat;",
    "  background-attachment: fixed;",
    "  background-color: #FBF7F0;",
    "}",
    "[data-testid=\"stMainBlockContainer\"] { background-color: transparent; }",
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

    # ``stylesheet()`` already carries its own <style> wrapper. Wrapping it
    # again is not harmless: inside a style element everything up to the first
    # ``</style>`` is raw text, so the nested opening tag becomes a leading
    # garbage selector and CSS error recovery discards the first real rule with
    # it.
    st.markdown(stylesheet(), unsafe_allow_html=True)


def stylesheet() -> str:
    return """
<style>
/* The page ground -- colour and washes -- is set by BACKGROUND_CSS on the
   document head, which is the only place that can reach <html> reliably. This
   block deliberately carries no ``background`` shorthand, because a later
   ``background: #FBF7F0`` here would reset those washes away. */
html, body, [data-testid="stAppViewContainer"],
.stApp, .main {
  color: #241F1A;
}

html, body, .stApp, [class*="css"] {
  font-family: %(font)s;
  color: #241F1A;
}

/* One measure for the whole page. Without it the wide layout runs a line of
   body text the full width of the window, and nothing on the page has a left
   edge to line up against. */
[data-testid="stMainBlockContainer"] {
  max-width: %(content_width)s;
  margin-left: auto;
  margin-right: auto;
  padding-top: 2.6rem;
  padding-bottom: 5rem;
}

/* The floating toolbar is translucent and carries no page colour of its own, so
   it must not paint over the paper; the reduced top padding above assumes the
   same. */
[data-testid="stHeader"] {
  background: transparent;
}

/* --- Landing ----------------------------------------------------------- */
/* Text left, illustration right, no enclosing card: the hero has to read as
   the top of a document, not as one more panel in a dashboard. */
.tf-hero {
  display: grid;
  grid-template-columns: minmax(0, 1.05fr) minmax(0, .95fr);
  gap: 44px;
  align-items: center;
  padding: .5rem 0 1.4rem;
}
.tf-hero .tf-title {
  margin: 0 0 .85rem 0 !important;
  font-size: clamp(2.3rem, 5vw, 3.15rem) !important;
  line-height: 1.08 !important;
  letter-spacing: -.028em;
  font-weight: 750 !important;
  color: #241F1A !important;
}
.tf-h1sub {
  display: block;
  font-size: .44em !important;
  font-weight: 600 !important;
  letter-spacing: -.01em;
  color: #6B6156 !important;
  margin-top: .5rem;
  line-height: 1.25 !important;
}
.tf-lede {
  margin: 0 0 .7rem 0 !important;
  color: #6B6156 !important;
  font-size: 1.12rem !important;
  line-height: 1.65 !important;
  max-width: 46ch;
}
.tf-lede b { color: #241F1A; font-weight: 650; }

/* "What is this" jump. An inline link here is easy to miss and reads as part of
   the paragraph, so it is a pill instead -- but deliberately an outline one:
   the filled mode button below it has to stay the loudest thing on the screen. */
.tf-jump {
  display: inline-flex;
  align-items: center;
  gap: .5rem;
  margin-top: .45rem;
  padding: .52rem 1.05rem .52rem .9rem;
  border: 1px solid #D9CDB9;
  border-radius: 999px;
  background: #FFFDF9;
  color: #241F1A !important;
  font-size: .96rem;
  font-weight: 650;
  text-decoration: none !important;
  box-shadow: 0 1px 2px rgba(60,45,25,.05);
  transition: transform .15s ease, box-shadow .18s ease,
              border-color .18s ease, background .18s ease;
}
.tf-jump:hover {
  transform: translateY(-1px);
  border-color: #2E7DE4;
  background: #F2F7FE;
  color: #2469C7 !important;
  box-shadow: 0 7px 18px rgba(46,125,228,.16);
}
.tf-jump:active { transform: translateY(0); }
.tf-jump:focus-visible { outline: 2px solid #2E7DE4; outline-offset: 3px; }
.tf-jump svg {
  width: 15px; height: 15px; flex: none;
  stroke: currentColor; fill: none;
  stroke-width: 2.1; stroke-linecap: round; stroke-linejoin: round;
  transition: transform .18s ease;
}
.tf-jump:hover svg { transform: translateY(2px); }
.tf-art {
  width: 100%%;
  height: auto;
  display: block;
  border: 1px solid #E4DACA;
  border-radius: 18px;
  background: #FFFDF9;
  box-shadow: 0 1px 3px rgba(60,45,25,.05);
}
.tf-eyebrow {
  display: inline-block;
  font-size: .78rem !important;
  line-height: 1.4 !important;
  letter-spacing: .2em;
  text-transform: uppercase;
  color: #6B6156 !important;
  font-weight: 700 !important;
  margin: 0 0 .7rem 0 !important;
}

/* The two entry buttons.
   The reference site's flat fill reads as an ordinary control at this size, so
   the primary one is built up instead: a diagonal fill with a lit top edge, a
   coloured glow that widens on hover, and a highlight that sweeps across the
   face. Everything is on the keyed container so no other button in the app
   picks it up. */
.st-key-tf_cta_play .stButton > button,
.st-key-tf_cta_lab .stButton > button {
  position: relative;
  overflow: hidden;
  min-height: 3.5rem;
  padding: 0 1.9rem;
  border-radius: 14px;
  font-size: 1.1rem;
  font-weight: 700;
  letter-spacing: -.012em;
  transition: transform .14s ease, box-shadow .2s ease,
              background .2s ease, border-color .2s ease, color .2s ease;
}
.st-key-tf_cta_play .stButton > button > div { position: relative; z-index: 1; }

/* `[kind="primary"]` is load-bearing, not decoration: the generic primary-button
   rule further down has the same specificity without it, and being later in the
   sheet it would flatten this fill back to a solid colour. */
.st-key-tf_cta_play .stButton > button[kind="primary"] {
  border: 1px solid #1F5FC4;
  color: #FFFFFF !important;
  background: linear-gradient(135deg, #4A92F2 0%%, #2E7DE4 46%%, #1F5FC4 100%%);
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,.3),
    0 2px 5px rgba(31,95,196,.22),
    0 14px 30px rgba(46,125,228,.28);
}
.st-key-tf_cta_play .stButton > button::after {
  content: "";
  position: absolute;
  top: -10%%; left: -70%%;
  width: 45%%; height: 120%%;
  background: linear-gradient(100deg, transparent, rgba(255,255,255,.38), transparent);
  transform: skewX(-18deg);
  transition: left .55s ease;
  pointer-events: none;
}
.st-key-tf_cta_play .stButton > button[kind="primary"]:hover {
  transform: translateY(-2px);
  border-color: #1B53AC;
  color: #FFFFFF !important;
  background: linear-gradient(135deg, #5C9EF6 0%%, #3A87EC 46%%, #2469C7 100%%);
  box-shadow:
    inset 0 1px 0 rgba(255,255,255,.36),
    0 4px 9px rgba(31,95,196,.24),
    0 20px 42px rgba(46,125,228,.36);
}
.st-key-tf_cta_play .stButton > button:hover::after { left: 130%%; }
.st-key-tf_cta_play .stButton > button:active { transform: translateY(0); }

.st-key-tf_cta_lab .stButton > button {
  border: 1px solid #CFC3AE;
  color: #241F1A !important;
  background: #FFFDF9;
  box-shadow: 0 1px 2px rgba(60,45,25,.06);
}
.st-key-tf_cta_lab .stButton > button:hover {
  transform: translateY(-2px);
  border-color: #21A179;
  color: #17795B !important;
  background: #F1F9F5;
  box-shadow: 0 10px 24px rgba(33,161,121,.18);
}
.st-key-tf_cta_lab .stButton > button:active { transform: translateY(0); }

/* The three payoff outcomes, as cards rather than as a line of text. The
   reader has to feel the asymmetry (3 / 5-0 / 1) before the modes make sense. */
.tf-payoffs {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin: 0 0 .4rem;
  padding-top: 1.4rem;
  border-top: 1px solid #E4DACA;
}
.tf-pay {
  display: flex;
  align-items: center;
  gap: 13px;
  padding: .8rem .95rem;
  background: #FFFDF9;
  border: 1px solid #E4DACA;
  border-radius: 13px;
}
.tf-pay svg { width: 34px; height: 34px; flex: none; }
.tf-pay p { font-size: .88rem; line-height: 1.45; color: #6B6156; margin: 0; }
.tf-pay p b {
  display: block;
  color: #241F1A;
  font-size: .98rem;
  font-weight: 680;
  font-variant-numeric: tabular-nums;
}

/* Section header: heading plus its one-line gloss on the same baseline. The
   top margin is the rhythm between landing sections. */
.tf-sec {
  display: flex;
  align-items: baseline;
  gap: 14px;
  flex-wrap: wrap;
  margin: 2.9rem 0 1.1rem;
}
.tf-sec h2 { margin: 0; border-bottom: 0; padding: 0 !important; }
.tf-sec i { font-style: normal; font-size: .92rem; color: #6B6156; }

/* Three layers of the product, divided by hairlines instead of by boxes. */
.tf-arch {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0;
}
.tf-arch > div { padding: 0 1.4rem; border-left: 1px solid #E4DACA; }
.tf-arch > div:first-child { border-left: 0; padding-left: 0; }
.tf-arch h4 { margin: 0 0 .35rem; font-weight: 700; }
.tf-arch p { font-size: .93rem; color: #6B6156; margin: 0; }
.tf-arch p.tf-kicker {
  font-size: .74rem;
  font-weight: 750;
  letter-spacing: .14em;
  text-transform: uppercase;
  color: #6B6156;
  margin-bottom: .5rem;
}

/* Numbered run of steps. */
.tf-steps { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 18px; }
.tf-steps > div { font-size: .94rem; color: #6B6156; }
.tf-steps b {
  display: block;
  color: #241F1A;
  font-size: 1rem;
  font-weight: 680;
  margin-bottom: .2rem;
}
.tf-steps em {
  font-style: normal;
  display: inline-grid;
  place-items: center;
  width: 21px; height: 21px;
  border-radius: 50%%;
  background: #241F1A;
  color: #FBF7F0;
  font-size: .72rem;
  font-weight: 700;
  margin-bottom: .55rem;
}

/* Mode cards. The box lives on the keyed container rather than on the markup
   inside it, because the enter button is a Streamlit widget that cannot be
   nested into the markdown block -- it has to be a sibling, so the card is the
   element that wraps both. ``--tf-accent`` is set here and inherits down into
   the icon tile, the bullet markers and the top rule. */
.st-key-tf_mode_play, .st-key-tf_mode_lab {
  position: relative;
  display: flex;
  flex-direction: column;
  background: #FFFDF9;
  border: 1px solid #E4DACA;
  border-radius: 18px;
  padding: 1.5rem 1.5rem 1.3rem;
  box-shadow: 0 1px 3px rgba(60,45,25,.05);
  transition: .18s ease;
  overflow: hidden;
}
.st-key-tf_mode_play { --tf-accent: #2E7DE4; --tf-tint: #E7F0FC; }
.st-key-tf_mode_lab { --tf-accent: #21A179; --tf-tint: #E4F3EE; }
.st-key-tf_mode_play::before, .st-key-tf_mode_lab::before {
  content: "";
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 3px;
  background: var(--tf-accent);
  opacity: .85;
}
.st-key-tf_mode_play:hover, .st-key-tf_mode_lab:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 26px rgba(60,45,25,.09);
  border-color: #D8CBB4;
}
.tf-mode { display: flex; flex-direction: column; }
.tf-mode .tf-ico {
  width: 40px; height: 40px;
  border-radius: 11px;
  background: var(--tf-tint, #E7F0FC);
  display: grid;
  place-items: center;
  margin-bottom: .9rem;
}
.tf-mode .tf-ico svg {
  width: 21px; height: 21px;
  stroke: var(--tf-accent, #2E7DE4);
  fill: none;
  stroke-width: 1.9;
  stroke-linecap: round;
  stroke-linejoin: round;
}
.tf-mode h3 { margin: 0 0 .3rem; font-size: 1.3rem !important; }
.tf-mode p.tf-sub { color: #6B6156; font-size: .96rem; margin: 0 0 1rem; }
.tf-mode ul { margin: 0 0 1.1rem; padding: 0; list-style: none; display: grid; gap: .55rem; }
.tf-mode li {
  position: relative;
  padding-left: 20px;
  font-size: .96rem;
  line-height: 1.55;
  color: #3B342C;
}
.tf-mode li::before {
  content: "";
  position: absolute;
  left: 2px; top: .6em;
  width: 7px; height: 7px;
  border-radius: 50%%;
  background: var(--tf-accent, #2E7DE4);
  opacity: .55;
}
.tf-badge {
  position: absolute;
  top: 1.35rem; right: 1.4rem;
  font-size: .75rem;
  font-weight: 700;
  letter-spacing: .06em;
  color: var(--tf-accent, #2E7DE4);
  background: var(--tf-tint, #E7F0FC);
  border-radius: 999px;
  padding: .25rem .6rem;
}
.tf-tags { display: flex; gap: 7px; flex-wrap: wrap; margin-bottom: 1.1rem; }
.tf-tag {
  display: inline-block;
  font-size: .78rem;
  font-weight: 650;
  letter-spacing: .03em;
  color: #6B6156;
  background: rgba(36,31,26,.045);
  border: 1px solid #E4DACA;
  border-radius: 999px;
  padding: .18rem .55rem;
}

/* Glossary, two columns of term/definition. */
.tf-gloss {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 34px;
  margin: 0;
  padding: 1.3rem 1.5rem 1.4rem;
  background: #FFFDF9;
  border: 1px solid #E4DACA;
  border-radius: 16px;
}
.tf-gloss dt { font-weight: 700; font-size: .98rem; margin-top: .8rem; }
.tf-gloss dt:first-child { margin-top: 0; }
.tf-gloss dd { margin: .1rem 0 0; font-size: .93rem; color: #6B6156; }
.tf-card {
  margin-bottom: 1.1rem;
  padding: 1.5rem 1.6rem;
  background: #FFFDF9;
  border: 1px solid #E4DACA;
  border-radius: 16px;
  box-shadow: 0 1px 3px rgba(60,45,25,.05);
}
/* Inside a card the line is meant to run long -- it is prose, not the hero's
   one-line pitch. */
.tf-card .tf-lede { max-width: 70ch; margin-bottom: .8rem; }
.tf-card .tf-lede:last-child { margin-bottom: 0; }
.tf-card p { max-width: 70ch; }
.tf-hl {
  font-style: normal;
  background: linear-gradient(transparent 62%%, rgba(33,161,121,.24) 0);
  padding: 0 .1em;
}

/* --- Typography -------------------------------------------------------- */
/* Sizes, not just colour: Streamlit's default scale makes h3 larger than a
   plain markdown h1, which inverts the hierarchy on every view that does not
   render the hero. !important is needed to beat the component stylesheet. */
h1, h2, h3, h4 { color: #241F1A; letter-spacing: -.012em; }
/* Streamlit puts vertical padding on every heading it renders, including the
   ones nested inside a custom block, which is where it reads as random gaps. */
h1, h2, h3, h4 { padding-top: 0 !important; }
h3, h4 { padding-bottom: 0 !important; }
h1 { font-size: %(h1)s !important; line-height: 1.15; letter-spacing: -.024em; font-weight: 750; margin: 0 0 .8rem 0 !important; }
h2 {
  margin-top: 1.9rem;
  padding-bottom: .45rem;
  border-bottom: 2px solid #E4DACA;
  font-size: %(h2)s !important;
  font-weight: 700;
  letter-spacing: -.016em;
}
h3 { font-size: %(h3)s !important; font-weight: 700; }
h4 { font-size: %(h4)s !important; font-weight: 700; }
/* `label` is deliberately excluded here. Streamlit renders a button's caption
   inside a <label>, so setting line-height on it made the caption taller than
   the fixed min-height on the button and the text was clipped away, leaving the
   bare emoji. */
p, li { color: #241F1A; font-size: 1.02rem; line-height: 1.7; }
/* Streamlit wraps a button's caption in a <p>, so the rule above reaches into
   the button and paints a primary label dark on its own blue fill. Buttons own
   their text colour; everything inside one has to inherit it. */
.stButton > button :is(p, span, div, label),
.stDownloadButton > button :is(p, span, div, label),
.stLinkButton > a :is(p, span, div, label) {
  color: inherit !important;
  font-size: inherit !important;
  line-height: inherit !important;
  margin: 0 !important;
}
.stButton > button, .stDownloadButton > button, .stLinkButton > a {
  font-size: .98rem;
}
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
   Neither gets a solid fill: cooperation used to be permanent blue while
   defection stayed outlined, so the two never looked like the same kind of
   decision -- one read as the safe default. They now share the same paper
   button and differ only in the colour of their own label, and hover fills
   either with its action colour. In the tutorial the advised one is filled
   without hovering, driven by the badge class -- swapping the container key
   does not work, since Streamlit reuses the element when only its key
   changes. */
.st-key-tf_move_coop button,
.st-key-tf_move_defect button {
  min-height: 3.5rem !important;
  height: auto !important;
  padding-top: .75rem !important;
  padding-bottom: .75rem !important;
  font-size: 1.06rem !important;
  font-weight: 700 !important;
  letter-spacing: .01em;
  border-width: 1.5px !important;
  background: #FFFDF9 !important;
  background-color: #FFFDF9 !important;
  border-color: #D8CBB4 !important;
}
.st-key-tf_move_coop button { color: #2469C7 !important; }
.st-key-tf_move_defect button { color: #C7492A !important; }
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

/* What each choice is worth, shown under the button it belongs to. A player
   picking blind otherwise has to remember the payoff matrix from the intro. */
.st-key-tf_move_coop .tf-branches,
.st-key-tf_move_defect .tf-branches {
  display: flex;
  gap: .4rem;
  margin-top: .45rem;
}
.st-key-tf_move_coop .tf-branch,
.st-key-tf_move_defect .tf-branch {
  flex: 1 1 0;
  text-align: center;
  padding: .38rem .3rem .42rem;
  border: 1px solid #E4DACA;
  border-radius: 9px;
  background: #FFFDF9;
}
.st-key-tf_move_coop .tf-branch { font-size: .76rem; }
.tf-branch__them {
  display: block;
  color: #6B6156;
  letter-spacing: .01em;
  white-space: nowrap;
}
.tf-branch__mine {
  display: block;
  margin-top: .16rem;
  font-size: 1.02rem;
  font-weight: 700;
  color: #241F1A;
  font-variant-numeric: tabular-nums;
}
.st-key-tf_move_coop .tf-branch--best { border-color: #A9CFF5; background: #F2F7FE; }
.st-key-tf_move_defect .tf-branch--best { border-color: #F5C3AC; background: #FDF3EE; }

/* Where the player is in the run. Replaces a bare st.progress plus a heading
   plus a caption, which read as three unrelated fragments stacked above the
   actual decision. */
.tf-stage {
  padding: .78rem 1rem .85rem;
  margin-bottom: .75rem;
  border: 1px solid #E4DACA;
  border-radius: 12px;
  background: #FFFFFF;
  box-shadow: 0 1px 2px rgba(60,45,25,.05);
}
.tf-stage__top {
  display: flex;
  align-items: baseline;
  gap: .5rem;
  flex-wrap: wrap;
}
.tf-stage__kicker {
  font-size: .74rem;
  letter-spacing: .12em;
  text-transform: uppercase;
  font-weight: 700;
  color: #6B6156;
}
.tf-stage__count {
  font-size: 1.32rem;
  font-weight: 750;
  letter-spacing: -.02em;
  color: #241F1A;
  font-variant-numeric: tabular-nums;
}
.tf-stage__count em {
  font-style: normal;
  font-size: .82rem;
  font-weight: 600;
  color: #6B6156;
}
.tf-stage__total {
  margin-left: auto;
  font-size: .84rem;
  color: #6B6156;
  font-variant-numeric: tabular-nums;
}
.tf-stage__total b {
  font-size: 1.14rem;
  color: #241F1A;
  margin-left: .22rem;
}
/* One segment per match in the run: won in green, lost in orange, drawn in
   grey, with the live match standing out. The scoreboard a player checks
   between matches, so it belongs on the play screen rather than only in
   已完成的局. */
.tf-pips {
  display: flex;
  gap: .3rem;
  margin: .6rem 0 .72rem;
}
.tf-pip {
  width: 1.3rem;
  height: .34rem;
  border-radius: 999px;
  background: #E7DCC9;
}
.tf-pip--win { background: #21A179; }
.tf-pip--loss { background: #E4572E; }
.tf-pip--draw { background: #B9AE9D; }
.tf-pip--here {
  background: #2E7DE4;
  box-shadow: 0 0 0 3px rgba(46,125,228,.16);
}
.tf-track {
  height: .4rem;
  border-radius: 999px;
  background: #EFE6D6;
  overflow: hidden;
}
.tf-track__fill {
  height: 100%%;
  border-radius: 999px;
  background: linear-gradient(90deg, #4A92F2, #2E7DE4);
  transition: width .25s ease;
}
.tf-stage__sub {
  display: flex;
  gap: .65rem;
  align-items: baseline;
  flex-wrap: wrap;
  margin-top: .52rem;
  font-size: .84rem;
}
.tf-stage__turn {
  font-weight: 700;
  color: #241F1A;
  font-variant-numeric: tabular-nums;
}
.tf-stage__secret { color: #6B6156; }

/* What the opponent just did, one line above the score. */
.tf-cue {
  display: flex;
  align-items: center;
  gap: .45rem;
  margin: -.2rem 0 .7rem;
  font-size: .9rem;
  color: #6B6156;
}
.tf-cue i {
  width: .5rem;
  height: .5rem;
  border-radius: 50%%;
  background: #2E7DE4;
  flex: none;
}
.tf-cue--defect { color: #B4451F; font-weight: 600; }
.tf-cue--defect i { background: #E4572E; }

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
  margin-left: auto;
  font-size: .82rem;
  font-weight: 700;
}
/* The two scores as one bar. Two numbers side by side say who is ahead; the
   split says by how much and how far there is left to go. */
.tf-score__split {
  flex-basis: 100%%;
  display: flex;
  height: .42rem;
  border-radius: 999px;
  overflow: hidden;
  background: #EFE6D6;
  margin-top: .3rem;
}
.tf-score__you-bar {
  background: linear-gradient(90deg, #4A92F2, #2E7DE4);
  transition: width .25s ease;
}
.tf-score__them-bar {
  background: linear-gradient(90deg, #E4572E, #F07A52);
  transition: width .25s ease;
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
  /* Illustration above the text: it explains the page, so on a phone it earns
     the first screen and the lede follows. */
  .tf-hero { grid-template-columns: 1fr; gap: 28px; padding: .25rem 0 1rem; }
  .tf-hero .tf-art { order: -1; }
  .tf-hero .tf-title { font-size: 1.85rem !important; }
  .tf-lede { font-size: .95rem; }
  .tf-payoffs, .tf-arch, .tf-steps, .tf-gloss { grid-template-columns: 1fr; }
  .tf-payoffs { margin-bottom: 2rem; }
  .tf-arch > div { border-left: 0; padding: 1rem 0; border-top: 1px solid #E4DACA; }
  .tf-arch > div:first-child { border-top: 0; padding-top: 0; }
  .tf-move button, .st-key-tf_move_coop button,
  .st-key-tf_move_defect button { min-height: 3.2rem; font-size: .98rem; }
  h2 { font-size: 1.3rem !important; }
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
        "h1": H1_SIZE,
        "h2": H2_SIZE,
        "h3": H3_SIZE,
        "h4": H4_SIZE,
        "content_width": CONTENT_WIDTH,
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


def section(title: str, gloss: str = "") -> str:
    """A heading with its one-line gloss on the same baseline."""
    tail = '<i>{}</i>'.format(gloss) if gloss else ""
    return '<div class="tf-sec"><h2>{}</h2>{}</div>'.format(title, tail)


# The three rows of the payoff matrix, drawn as two dots and the relation
# between them. An emoji in a heading goes tofu on a machine with no emoji
# font; these stay unambiguous in greyscale because the geometry differs.
PAYOFF_ICONS = (
    (
        '<svg viewBox="0 0 40 40" aria-hidden="true">'
        '<rect x="1" y="1" width="38" height="38" rx="10" fill="none" stroke="#E4DACA"/>'
        '<circle cx="14" cy="14" r="4.5" fill="#2E7DE4"/>'
        '<circle cx="26" cy="26" r="4.5" fill="#2E7DE4"/>'
        '<path d="M17 17l6 6" stroke="#21A179" stroke-width="2" stroke-linecap="round"/>'
        "</svg>",
        "双方合作", "各得 3 分",
    ),
    (
        '<svg viewBox="0 0 40 40" aria-hidden="true">'
        '<rect x="1" y="1" width="38" height="38" rx="10" fill="none" stroke="#E4DACA"/>'
        '<circle cx="14" cy="14" r="4.5" fill="#2E7DE4"/>'
        '<circle cx="26" cy="26" r="4.5" fill="#E4572E"/>'
        '<path d="M26 14V9M26 11l-3 3M26 11l3 3" stroke="#E4572E" stroke-width="1.8"'
        ' fill="none" stroke-linecap="round"/>'
        "</svg>",
        "一方背叛", "5 分 与 0 分",
    ),
    (
        '<svg viewBox="0 0 40 40" aria-hidden="true">'
        '<rect x="1" y="1" width="38" height="38" rx="10" fill="none" stroke="#E4DACA"/>'
        '<circle cx="14" cy="14" r="4.5" fill="#E4572E"/>'
        '<circle cx="26" cy="26" r="4.5" fill="#E4572E"/>'
        '<path d="M17 17l6 6" stroke="#6B6156" stroke-width="2" stroke-linecap="round"'
        ' stroke-dasharray="2 3"/>'
        "</svg>",
        "双方背叛", "各得 1 分",
    ),
)

MODE_ICONS = {
    "play": (
        '<svg viewBox="0 0 24 24" aria-hidden="true">'
        '<path d="M6 11h12a2 2 0 0 1 2 2l-.6 4.2A2.4 2.4 0 0 1 15 18l-1.4-1.6h-3.2'
        'L9 18a2.4 2.4 0 0 1-4.4-.8L4 13a2 2 0 0 1 2-2Z"/>'
        '<path d="M8.5 8V4.5M15.5 8V4.5"/>'
        '<circle cx="8.5" cy="3.5" r="1.3"/><circle cx="15.5" cy="3.5" r="1.3"/>'
        "</svg>"
    ),
    "lab": (
        '<svg viewBox="0 0 24 24" aria-hidden="true">'
        '<path d="M4 19V5M4 19h16"/>'
        '<path d="M8 15l3.2-4.4L14.5 13 19 6.5"/>'
        '<circle cx="8" cy="15" r="1.4"/><circle cx="14.5" cy="13" r="1.4"/>'
        "</svg>"
    ),
}

#: The arrow inside the "explain this to me" pill. An inline link there is read
#: as part of the sentence; the arrow is what turns it into an affordance.
JUMP_ARROW = (
    '<svg viewBox="0 0 24 24" aria-hidden="true">'
    '<path d="M12 4.5v13"/><path d="M6.5 12l5.5 5.5L17.5 12"/></svg>'
)


def hero_art() -> str:
    """The illustration markup, with ``.tf-art`` grafted onto the root node."""
    return HERO_PATH.read_text(encoding="utf-8").replace(
        "<svg ", '<svg class="tf-art" ', 1)


def landing_hero(
    eyebrow: str,
    title: str,
    title_sub: str,
    lede: str,
    jump_label: str,
    jump_anchor: str,
) -> str:
    """The masthead: the pitch on the left, the subject matter on the right.

    The illustration is concatenated rather than passed through ``format``: SVG
    is full of braces and quotes, and a placeholder here would break on the next
    edit to the drawing.
    """
    words = (
        '<div class="tf-hero">'
        "<div>"
        '<p class="tf-eyebrow">{}</p>'
        '<p class="tf-title">{}<span class="tf-h1sub">{}</span></p>'
        '<p class="tf-lede">{}</p>'
        '<a class="tf-jump" href="#{}">{}{}</a>'
        "</div>"
    ).format(
        eyebrow, title, title_sub, lede, jump_anchor, jump_label, JUMP_ARROW,
    )
    return words + hero_art() + "</div>"


def payoff_chips() -> str:
    cells = "".join(
        '<div class="tf-pay">{}<p>{}<b>{}</b></p></div>'.format(icon, label, value)
        for icon, label, value in PAYOFF_ICONS
    )
    return '<div class="tf-payoffs">{}</div>'.format(cells)


def mode_card(
    icon_key: str,
    title: str,
    subtitle: str,
    bullets: list[str],
    tags: list[str],
    badge: str = "",
) -> str:
    """The upper part of a mode card; the enter button is a widget below it.

    A Streamlit button cannot be nested inside this block, so the keyed
    container wrapping both carries the card box, the top rule and the accent
    colours, and the button is stretched to sit flush with its bottom edge.
    """
    return (
        '<div class="tf-mode">{badge}'
        '<span class="tf-ico">{icon}</span>'
        "<h3>{title}</h3>"
        '<p class="tf-sub">{subtitle}</p>'
        "<ul>{bullets}</ul>"
        '<div class="tf-tags">{tags}</div>'
        "</div>"
    ).format(
        badge='<span class="tf-badge">{}</span>'.format(badge) if badge else "",
        icon=MODE_ICONS[icon_key],
        title=title,
        subtitle=subtitle,
        bullets="".join("<li>{}</li>".format(line) for line in bullets),
        tags="".join('<span class="tf-tag">{}</span>'.format(tag) for tag in tags),
    )


def architecture(layers: list[tuple[str, str, str]]) -> str:
    """The three layers of the product, separated by hairlines."""
    cells = "".join(
        '<div><p class="tf-kicker">{}</p><h4>{}</h4><p>{}</p></div>'.format(*layer)
        for layer in layers
    )
    return '<div class="tf-card"><div class="tf-arch">{}</div></div>'.format(cells)


def steps(items: list[tuple[str, str, str]]) -> str:
    """A numbered run of steps, each with a one-line gloss."""
    cells = "".join(
        "<div><em>{}</em><b>{}</b>{}</div>".format(*item) for item in items
    )
    return '<div class="tf-steps">{}</div>'.format(cells)


def glossary(columns: list[list[tuple[str, str]]]) -> str:
    """Term/definition pairs, balanced across as many columns as are given."""
    blocks = "".join(
        "<div>{}</div>".format(
            "".join("<dt>{}</dt><dd>{}</dd>".format(term, mean) for term, mean in column)
        )
        for column in columns
    )
    return '<dl class="tf-gloss">{}</dl>'.format(blocks)


def prose_card(paragraphs: list[str]) -> str:
    """A card of prose. Used by the landing pitch, where a plain markdown
    paragraph reads as filler next to the cards around it."""
    body = "".join('<p class="tf-lede">{}</p>'.format(p) for p in paragraphs)
    return '<div class="tf-card">{}</div>'.format(body)

