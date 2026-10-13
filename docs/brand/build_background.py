"""Draw the motif used as the game layer's background.

What changed from the earlier attempts, and why:

* The previous sheet was a four-sided border assembled from separate strips,
  but the vertical strips were placed with an X offset only and then the whole
  sheet was repeated down the page -- so the side strips stacked on themselves.
  Two overlapping patterns were visible on the right edge.
* Painting it across the whole viewport put the motif under every control, where
  it competed with the content instead of framing it.

This version is one self-contained sheet with no repeats: a lattice of payoff
cells at even spacing, no borders, so it cannot double up, and it is applied to
the game layer rather than the page. The sheet is sized to be wider and shorter
than the layer it sits in, and the layer crops it.
"""

import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "the-fittest-background.svg")

# Sized to tile behind the game layer without being tiled: the browser draws it
# once, anchored to the top of the layer.
W, H = 1600, 1200

PAPER = ["#FDFAF5", "#FBF7F0", "#F7F1E7"]
COOP = "#2E7DE4"
DEFECT = "#E4572E"
MUTUAL = "#21A179"
NEUTRAL = "#6B6156"

# (action, score, colour) for each of the four outcomes.
CELLS = [
    ("C", 3, MUTUAL),
    ("D", 5, DEFECT),
    ("C", 0, COOP),
    ("D", 1, NEUTRAL),
]

CELL = 88
# Spacing between cells. Wide, because the sheet now tiles across the whole
# page: a dense grid that read as texture on one panel becomes visual noise
# repeated dozens of times down a long page.
GAP_X = 340
GAP_Y = 340
MARGIN_X = 170
MARGIN_Y = 170

# Opacity is deliberately low. This is the page ground, not the game board:
# everything sits on top of it, so it has to stay quieter than the content.
MOTIF_OPACITY = 0.035


def cell(action, score, colour, x, y):
    return (
        '<g transform="translate({x},{y})">'
        '<rect width="{c}" height="{c}" rx="15" fill="none" '
        'stroke="{col}" stroke-width="2"/>'
        '<text x="{h}" y="38" text-anchor="middle" '
        'font-family="Georgia,serif" font-size="27" fill="{col}">{a}</text>'
        '<text x="{h}" y="70" text-anchor="middle" '
        'font-family="Georgia,serif" font-size="23" fill="{col}">{s}</text>'
        "</g>"
    ).format(x=x, y=y, c=CELL, h=CELL / 2, col=colour, a=action, s=score)


def lattice():
    """Even grid of the four outcomes.

    The grid is strictly periodic over the sheet with no per-row offset: the
    browser repeats this tile down the page, and a shifted row would leave a
    visible seam at every tile boundary. Neighbours differ because the four
    outcomes cycle, which keeps the field from reading as stripes without
    breaking the period.
    """
    columns = (W - 2 * MARGIN_X) // GAP_X + 1
    rows = (H - 2 * MARGIN_Y) // GAP_Y + 1
    parts = []
    for row in range(rows):
        for col in range(columns):
            action, score, colour = CELLS[(col + row) % len(CELLS)]
            parts.append(cell(
                action, score, colour,
                MARGIN_X + col * GAP_X,
                MARGIN_Y + row * GAP_Y,
            ))
    return "".join(parts)


def svg():
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        'width="{w}" height="{h}" role="img" '
        'aria-label="The Fittest 游戏图层底纹：收益矩阵">\n'
        "  <defs>\n"
        '    <linearGradient id="paper" x1="0" y1="0" x2="1" y2="1">\n'
        '      <stop offset="0%" stop-color="{p0}"/>\n'
        '      <stop offset="55%" stop-color="{p1}"/>\n'
        '      <stop offset="100%" stop-color="{p2}"/>\n'
        "    </linearGradient>\n"
        '    <radialGradient id="wash-coop" cx="0.14" cy="0.12" r="0.60">\n'
        '      <stop offset="0%" stop-color="{coop}" stop-opacity="0.05"/>\n'
        '      <stop offset="100%" stop-color="{coop}" stop-opacity="0"/>\n'
        "    </radialGradient>\n"
        '    <radialGradient id="wash-defect" cx="0.90" cy="0.24" r="0.58">\n'
        '      <stop offset="0%" stop-color="{defect}" stop-opacity="0.045"/>\n'
        '      <stop offset="100%" stop-color="{defect}" stop-opacity="0"/>\n'
        "    </radialGradient>\n"
        '    <radialGradient id="wash-mutual" cx="0.30" cy="0.94" r="0.68">\n'
        '      <stop offset="0%" stop-color="{mutual}" stop-opacity="0.04"/>\n'
        '      <stop offset="100%" stop-color="{mutual}" stop-opacity="0"/>\n'
        "    </radialGradient>\n"
        "  </defs>\n\n"
        '  <rect width="{w}" height="{h}" fill="url(#paper)"/>\n'
        '  <rect width="{w}" height="{h}" fill="url(#wash-coop)"/>\n'
        '  <rect width="{w}" height="{h}" fill="url(#wash-defect)"/>\n'
        '  <rect width="{w}" height="{h}" fill="url(#wash-mutual)"/>\n\n'
        "  <!-- The payoff matrix, evenly spaced. No border strips: those were\n"
        "       what doubled up when the sheet repeated. -->\n"
        '  <g opacity="{mo}">\n'
        "    {motif}\n"
        "  </g>\n"
        "</svg>\n"
    ).format(
        w=W, h=H, p0=PAPER[0], p1=PAPER[1], p2=PAPER[2],
        coop=COOP, defect=DEFECT, mutual=MUTUAL,
        mo=MOTIF_OPACITY, motif=lattice(),
    )


if __name__ == "__main__":
    with open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(svg())
    size = os.path.getsize(OUT)
    print("已生成 %s（%.1f KB）" % (os.path.basename(OUT), size / 1024))