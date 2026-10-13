"""Build The Fittest app icon: the non-transitive cycle.

Three equal-weight arc segments in a ring, each leaning forward so the ring
reads as rotation. Rock-paper-scissors has no winner, and that single shape
carries all three ideas the project needs:

  game      three parties pressing on each other
  evolution the segments travel round the loop; form is constant, position is not
  fitness   whoever leads this generation is behind the next

Why a bevelled edge instead of a triangular arrowhead: a protruding head is
what makes a small icon ragged. At 48px the head's point aliases into a spike
and the outer silhouette stops being a circle, so the icon turns to mush. A
forward-leaning cut keeps the silhouette a clean ring at every size while still
showing which way the cycle runs.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(r"C:\Users\离众\Desktop\Trust Evolution\docs\brand")
OUT.mkdir(parents=True, exist_ok=True)

SIZE = 1024
COLORS = ("#E4572E", "#2E7DE4", "#21A179")
PLATE_TOP = (255, 255, 255)
PLATE_BOTTOM = (237, 241, 246)
SHADOW = (11, 27, 43, 38)
CORNER = 0.2237

RADIUS_F = 0.262      # centreline radius
RIBBON_TAIL = 0.040   # half band width at the trailing end
RIBBON_HEAD = 0.070   # half band width at the leading end
SPAN_DEG = 96.0       # each edge sweeps this far
GAP_OFFSET = 12.0     # rotation so the gaps sit evenly
SHEAR_DEG = 18.0      # both ends lean forward by the same amount


def _ribbon_at(t: float, size: int) -> float:
    """Band half-width along a segment: thin at the tail, fat at the head.

    The taper is what turns a plain ring segment into something that reads as an
    arrow: a uniform band looks like a piece of a pie chart, a wedge looks like
    it is travelling. It also survives 48px better than a protruding head,
    because the silhouette stays a circle.
    """
    return size * (RIBBON_TAIL + (RIBBON_HEAD - RIBBON_TAIL) * t)


def _geometry(size: int):
    """One tapered, sheared annular sector per segment.

    Outer edge from ``outer_start`` to ``outer_end``; leading cut leaning
    forward by ``SHEAR_DEG`` across to the inner radius; inner edge is the same
    sweep shifted by that lean. Shearing both ends by the same amount keeps the
    gap constant at both radii, so the pieces never overlap.
    """
    c = size / 2.0
    r = size * RADIUS_F
    segments = []
    for index, colour in enumerate(COLORS):
        start = -90 + index * 120 + GAP_OFFSET
        segments.append({
            "colour": colour,
            "outer_start": start,
            "outer_end": start + SPAN_DEG,
            "inner_start": start + SHEAR_DEG,
            "inner_end": start + SPAN_DEG + SHEAR_DEG,
        })
    return c, r, segments


def _polygon_points(c, r, seg, size, per_arc=140):
    pts = []

    def add(angle_deg, radius):
        ang = math.radians(angle_deg)
        pts.append((c + radius * math.cos(ang), c + radius * math.sin(ang)))

    span = seg["outer_end"] - seg["outer_start"]
    # Outer edge, clockwise, widening toward the head.
    for step in range(per_arc + 1):
        t = step / per_arc
        add(seg["outer_start"] + span * t, r + _ribbon_at(t, size))
    # Leading cut, leaning forward, straight across to the inner radius.
    add(seg["inner_end"], r - _ribbon_at(1.0, size))
    # Inner edge, anticlockwise back to the inner start, narrowing again.
    for step in range(per_arc + 1):
        t = 1.0 - step / per_arc
        add(seg["inner_start"] + span * t, r - _ribbon_at(t, size))
    # The trailing cut closes the shape back to the outer start.
    return pts


def build_svg(size: int = SIZE) -> str:
    """Emit the same sampled polygons the raster preview uses.

    A tapered band cannot be expressed as one arc with a stroke width, so the
    path is written from the shared point list. That also guarantees the SVG and
    the PNG are the same shape rather than two independent constructions.
    """
    c, r, segments = _geometry(size)
    paths = []
    for seg in segments:
        pts = _polygon_points(c, r, seg, size)
        d = "M " + " L ".join(
            "{:.2f},{:.2f}".format(x, y) for x, y in pts
        ) + " Z"
        paths.append(f'<path d="{d}" fill="{seg["colour"]}"/>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 {size} {size}">'
        f"<defs>"
        f'<linearGradient id="plate" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="#FFFFFF"/>'
        f'<stop offset="1" stop-color="#EDF1F6"/>'
        f"</linearGradient>"
        f'<filter id="lift" x="-25%" y="-25%" width="150%" height="150%">'
        f'<feDropShadow dx="0" dy="{size * 0.010:.2f}" '
        f'stdDeviation="{size * 0.020:.2f}" flood-color="#0B1B2B" flood-opacity="0.16"/>'
        f"</filter>"
        f"</defs>"
        f'<rect x="0" y="0" width="{size}" height="{size}" rx="{size * CORNER:.2f}" '
        f'fill="url(#plate)"/>'
        f'<g filter="url(#lift)">{"".join(paths)}</g>'
        f"</svg>"
    )


def _plate(size: int) -> Image.Image:
    scale = 4
    big = size * scale
    grad = Image.new("RGB", (1, big))
    for y in range(big):
        t = y / max(big - 1, 1)
        grad.putpixel((0, y), tuple(
            int(PLATE_TOP[i] + (PLATE_BOTTOM[i] - PLATE_TOP[i]) * t) for i in range(3)
        ))
    grad = grad.resize((big, big))
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, big - 1, big - 1), radius=big * CORNER, fill=255
    )
    plate = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    plate.paste(grad, (0, 0), mask)
    return plate.resize((size, size), Image.LANCZOS)


def render(size: int, shadow: bool = True) -> Image.Image:
    plate = _plate(size)
    c, r, segments = _geometry(size)
    offset = max(1, round(size * 0.010))
    shapes = [(seg["colour"], _polygon_points(c, r, seg, size))
              for seg in segments]

    if shadow:
        layer = Image.new("RGBA", plate.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        for _, pts in shapes:
            draw.polygon([(x, y + offset) for x, y in pts], fill=SHADOW)
        plate = Image.alpha_composite(plate, layer)

    draw = ImageDraw.Draw(plate)
    for colour, pts in shapes:
        draw.polygon(pts, fill=colour)
    return plate


def main() -> None:
    svg_path = OUT / "the-fittest-icon-1024.svg"
    svg_path.write_text(build_svg(SIZE), encoding="utf-8")
    print("SVG  {}".format(svg_path))

    for size in (1024, 180, 48):
        target = OUT / "the-fittest-icon-{}.png".format(size)
        render(size).save(target)
        print("PNG {:>5}  {}  ({:.1f} KB)".format(
            size, target, target.stat().st_size / 1024))

    sheet = Image.new("RGB", (1024 + 512 + 180 + 96 + 48 + 40 * 4, 1024), (250, 250, 252))
    x = 0
    sheet.paste(render(1024), (x, 0)); x += 1024 + 40
    for size in (512, 180, 96, 48):
        sheet.paste(render(size, shadow=False), (x, (1024 - size) // 2))
        x += size + 40
    sheet_path = OUT / "the-fittest-icon-sizes.png"
    sheet.save(sheet_path)
    print("预览  {}".format(sheet_path))


if __name__ == "__main__":
    main()
