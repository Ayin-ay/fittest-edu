"""Loading states and preloading for the game mode.

Measured on this project, the wait is almost never Python:

* every post-game calculation together takes ~110 ms;
* the seven figures are ~53 KB of JSON, and 44.5 KB of that sits inside panels
  the player has not opened yet -- ``st.expander`` and ``st.tabs`` only hide the
  DOM, the code still runs and the payload still goes over the websocket.

So the work here is about not doing invisible work, and about making the few
moments that do take time say something useful while they happen.
"""

from __future__ import annotations

import html

from dashboard import theme

# Rendered the moment the app starts, before any simulation exists. It exists to
# replace a blank white screen with something that explains what is loading.
#
# Colours come from ``theme`` rather than being written out here: this block is
# injected on top of the landing page, and the previous cold-grey-blue version
# sat on the warm paper ground looking like somebody else's app.
SPLASH_CSS = f"""
<style>
@keyframes te-pulse {{ 0%,100% {{ opacity:.35 }} 50% {{ opacity:1 }} }}
@keyframes te-slide {{ 0% {{ transform:translateX(-100%) }} 100% {{ transform:translateX(320%) }} }}
@keyframes te-sway {{ 0%,100% {{ transform:translateY(0) }} 50% {{ transform:translateY(-4px) }} }}
.te-wrap {{ font-family: {theme.FONT_STACK}; color: {theme.INK}; }}
.te-badge {{ display:inline-flex; align-items:center; gap:.5rem;
             color:{theme.MUTED}; font-size:.9rem; letter-spacing:.02em; }}
.te-dot {{ width:9px; height:9px; border-radius:50%; background:{theme.COOP};
           animation:te-pulse 1.3s ease-in-out infinite; }}
.te-title {{ font-size:2rem; font-weight:700; color:{theme.INK}; margin:.2rem 0 .6rem; }}
.te-bar {{ position:relative; height:5px; width:min(320px,70vw); border-radius:99px;
           background:{theme.LINE}; overflow:hidden; margin:.7rem 0; }}
.te-bar > i {{ position:absolute; inset:0 auto 0 0; width:34%; border-radius:99px;
               background:linear-gradient(90deg,{theme.COOP_WASH},{theme.COOP});
               animation:te-slide 1.25s ease-in-out infinite; }}
.te-steps {{ margin:.5rem 0 0; padding:0; list-style:none; color:{theme.MUTED};
             font-size:.92rem; line-height:1.9; }}
.te-steps li::before {{ content:"·"; margin-right:.55rem; color:{theme.LINE}; }}
.te-chess {{ font-size:1.7rem; letter-spacing:.35rem; color:{theme.MUTUAL};
             animation:te-sway 2.4s ease-in-out infinite; }}
.te-note {{ color:{theme.MUTED}; font-size:.85rem; margin-top:.9rem; }}
</style>
"""


def splash(title: str, steps: list[str], note: str = "") -> str:
    """Branded loading block; safe to render as one markdown blob."""
    items = "".join("<li>{}</li>".format(html.escape(step)) for step in steps)
    return (
        '<div class="te-wrap">'
        '<div class="te-badge"><span class="te-dot"></span>正在准备</div>'
        '<div class="te-title">{}</div>'
        '<div class="te-bar"><i></i></div>'
        '<div class="te-chess">♟ ♟ ♟</div>'
        '<ul class="te-steps">{}</ul>'
        '<div class="te-note">{}</div>'
        "</div>".format(
            html.escape(title), items, html.escape(note)
        )
    )


def analysis_loading() -> str:
    """Shown between the last match and the report."""
    return splash(
        "正在读你的 100 步选择",
        [
            "把 10 个随机策略两两对局，算出完整得分矩阵",
            "逐轮还原你当时的局面、得分和「换一手会怎样」",
            "统计九项维度得分与全部决策热图",
        ],
        "只有十几步的计算，通常一闪而过；图表会在你点开时才加载。",
    )
