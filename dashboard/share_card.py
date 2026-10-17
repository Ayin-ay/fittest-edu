"""出牌风格卡：把九项测量归纳成一个可分享的结论。

## 它是什么，不是什么

这张卡片给的是一个**出牌风格**——"你在这十局里怎么出牌"，不是"你是什么人"。
这条界线是有意的，也是项目原本的设计约束（见 ``profiling.py`` 顶部：不接受人格
类型标签、不输出可贴到别人身上的特质形容词）。所以：

* 名字全部是**动作短语**（"从不收手"、"还手只一下的"），不是特质词；
* 卡面明确写"不是心理诊断"，并标出依据的是多少步决策；
* 免费版与 AI 版共用同一套风格体系，差别只在结论句的精细程度。

## 为什么能出"几十种"

名字由两段拼成：``修饰 + 原型``。

* **原型 10 个**——由"开局/回击/剥削"这个核心三角（外加区分度、一致性、影响力）
  的加权距离选出，代表你的基本立场；
* **修饰 9 个**——从原型没用到的维度里，取最极端的那一项（偏离中性 ≥ 0.18），
  代表你最突出的偏科。

10 × 9 = 90 种组合名，实际大部分对局会落在其中几十种上。

## 匹配度

``匹配度 = 1 - 加权平均距离``，取值 0~1，卡面显示为百分比。纯确定性计算：同样的
对局一定得到同一个风格，不需要 AI、不联网、毫秒出结果。
"""

from __future__ import annotations

import io
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from dashboard import theme
from dashboard.visuals import dimension_scores

# --------------------------------------------------------------------------
# 调色与尺寸：与 App、宣传片同一套品牌色，卡片才像是同一个产品出来的
# --------------------------------------------------------------------------

W, H = 1080, 1440
# 能对上主题令牌的都在这里对上：卡片和页面各写一份"差不多的米色"，改一处就漏一处。
BG = theme.GROUND
INK = theme.INK
ACCENT = theme.COOP
RULE = theme.LINE
PANEL = theme.RAISED
MUTE = theme.FAINT
#: 卡片独有的两档：介于正文与次级文字之间的墨色，以及比面板再浅一档的九宫格底。
#: 页面上没有对应角色，所以留在卡面这一侧，不塞进主题里充数。
INK2 = "#4A423A"
PANEL2 = "#FFFCF6"

DEFAULT_URL = "fittest-edu.streamlit.app"

#: 二维码里必须放完整 URL。
#:
#: 早先直接把 ``DEFAULT_URL`` 编进二维码，也就是没有 ``https://`` 的裸域名——
#: 微信扫出来只是一串文字，不会当成链接，点了没反应。卡面显示仍然用短形式，
#: 因为「the-fittest.streamlit.app」比带协议的版本好读，但扫码那一路必须是完整地址。
QR_URL = "https://fittest-edu.streamlit.app/"

# --------------------------------------------------------------------------
# 字体
#
# 两端都要能跑：本地是 Windows（微软雅黑），Streamlit Cloud 是 Linux。
# 云端由仓库根目录的 ``packages.txt`` 装上 ``fonts-noto-cjk``，所以这里按顺序找。
# 找不到任何中文字体时抛错而不是静默退化——静默退化会输出一排豆腐块。
# --------------------------------------------------------------------------

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Regular.otf",
]

_BOLD_CANDIDATES = [
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKsc-Bold.otf",
]

_font_cache: dict[tuple[bool, int], ImageFont.FreeTypeFont] = {}


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    key = (bold, size)
    if key in _font_cache:
        return _font_cache[key]
    for path in (_BOLD_CANDIDATES if bold else []) + FONT_CANDIDATES:
        try:
            font = ImageFont.truetype(path, size)
            _font_cache[key] = font
            return font
        except OSError:
            continue
    raise RuntimeError(
        "找不到可用的中文字体。本地需要系统自带（Windows 有微软雅黑）；"
        "云端需要仓库根目录的 packages.txt 提供 fonts-noto-cjk。"
    )


# --------------------------------------------------------------------------
# 风格表
#
# 每个原型是一组"期望值"：key 是 dimension_scores 里的维度，值是它希望看到的
# 0~1 分数。选中的原型是加权距离最小的那个。
#
# 两条约束是有原因的：
#
# 1. **每个原型必须恰好 3 个维度。** 评分是"平均距离"，定义维度少的原型会因为
#    只参加了一两项而占便宜——早先有个只用两个维度的原型，把明明更贴切的其他
#    风格全挤掉了。
# 2. **只写极端值（接近 0 或 1），不写 0.5。** 0.5 的意思是"这个维度我不关心"，
#    而表达"不关心"的正确方式是**不列这个维度**；写成 0.5 会让它参与打分，
#    等于要求玩家在中性附近，与风格本身无关。
# --------------------------------------------------------------------------

ARCHETYPES: list[dict[str, Any]] = [
    {
        "name": "从不先手",
        "target": {"opening": 0.95, "exploitation": 0.05, "retaliation": 0.15},
        "line": "你开局总是先给善意（{opening}%），也几乎不趁人之危（剥削 {exploitation}%）。",
    },
    {
        "name": "先礼后兵",
        "target": {"opening": 0.90, "retaliation": 0.90, "exploitation": 0.10},
        "line": "你先伸手，但只要被捅一刀，{retaliation}% 会还手——而且不占人便宜（剥削 {exploitation}%）。",
    },
    {
        "name": "寸土不让",
        "target": {"retaliation": 0.95, "punishment_duration": 0.90, "endgame": 0.85},
        "line": "被背叛后你 {retaliation}% 还手，一还就是好几轮（回击长度 {punishment_duration}%），越到结尾越硬。",
    },
    {
        "name": "从不手软",
        "target": {"exploitation": 0.90, "retaliation": 0.15, "opening": 0.20},
        "line": "对手合作时你也出手（{exploitation}%），而且不打算为过去的事报复（回击 {retaliation}%）。",
    },
    {
        "name": "见好就收",
        "target": {"opening": 0.85, "exploitation": 0.80, "endgame": 0.90},
        "line": "你先合作，但会在收尾前把便宜占掉——终局转向 {endgame}%，是全场最硬的时段。",
    },
    {
        "name": "开局就翻脸",
        "target": {"opening": 0.10, "retaliation": 0.85, "consistency": 0.70},
        "line": "第一手你就出手（开局合作仅 {opening}%），之后谁碰你你都还（回击 {retaliation}%）。",
    },
    {
        "name": "见人说人话",
        "target": {"discrimination": 0.90, "leverage": 0.85, "consistency": 0.20},
        "line": "你在不同对手面前几乎是两个人——区分度 {discrimination}%，能撬动对手 {leverage}%。",
    },
    {
        "name": "一套打到底",
        "target": {"consistency": 0.90, "discrimination": 0.15, "leverage": 0.30},
        "line": "相同局面下你 {consistency}% 出同一手，不因为对面是谁而改主意。",
    },
    {
        "name": "来回横跳",
        "target": {"consistency": 0.10, "discrimination": 0.30, "leverage": 0.35},
        "line": "同样局面你也会换招（一致性仅 {consistency}%），节奏一直在变。",
    },
    {
        "name": "牵着对手走",
        "target": {"leverage": 0.95, "exploitation": 0.15, "retaliation": 0.30},
        "line": "你出手不多，但对手会跟着你变——{leverage}% 的落子改变了对方下一手。",
    },
]

#: 修饰：high 词用于该维度偏高，low 词用于偏低。阈值 0.18 是为了不让"接近中性"
#: 的维度也硬派一个修饰。
#:
#: 用词要求：**读者不需要猜**。早先用「留一线的」「还手只一下的」这种文学化写法，
#: 卡面上反而看不懂——风格名是给别人看的一句话，不是诗。
MODIFIERS: dict[str, tuple[str, str]] = {
    "punishment_duration": ("还手拖很久", "还手一下就停"),
    "efficiency": ("每分都要算", "不太在意小分"),
    "endgame": ("最后几轮变狠", "最后也不变脸"),
    "consistency": ("套路固定", "打法多变"),
    "discrimination": ("看人下菜", "对谁都一样"),
    "leverage": ("能带节奏", "影响不了对手"),
    "opening": ("总是先示好", "先看看再说"),
    "retaliation": ("有仇必报", "不爱计较"),
    "exploitation": ("爱占便宜", "不占便宜"),
}

LABELS = {
    "opening": "开局合作",
    "retaliation": "回击倾向",
    "exploitation": "主动剥削",
    "discrimination": "对手区分度",
    "endgame": "终局转向",
    "punishment_duration": "回击长度",
    "efficiency": "单步收益效率",
    "leverage": "影响力",
    "consistency": "情境一致性",
}

#: 偏离中性到这个幅度才值得当修饰。
MODIFIER_MARGIN = 0.18
#: 匹配度低于此值时，宁可只报原型也不硬套一个不准的结论。
MIN_MATCH = 0.55


def classify(profile: dict) -> dict[str, Any]:
    """把一份 profile 归纳成出牌风格。纯计算，不用 AI。"""
    rows = dimension_scores(profile)
    values = {row["key"]: row["value"] for row in rows}

    best: dict[str, Any] | None = None
    for style in ARCHETYPES:
        total = 0.0
        used = 0
        for key, want in style["target"].items():
            if key in values:
                total += abs(values[key] - want)
                used += 1
        if used == 0:
            continue
        score = 1.0 - total / used
        if best is None or score > best["score"]:
            best = {"style": style, "score": score}

    if best is None:
        best = {"style": ARCHETYPES[0], "score": 0.0}

    style = best["style"]
    match = max(0.0, min(1.0, best["score"]))

    # 修饰：只在原型没用到的维度里挑，且必须足够极端。
    candidates = [
        (key, val) for key, val in values.items()
        if key not in style["target"] and key in MODIFIERS
    ]
    candidates.sort(key=lambda kv: -abs(kv[1] - 0.5))
    modifier = None
    if candidates:
        key, val = candidates[0]
        if abs(val - 0.5) >= MODIFIER_MARGIN:
            modifier = {"key": key, "word": MODIFIERS[key][0 if val > 0.5 else 1],
                        "value": val}

    # 名字分成两段，卡面上分开排：原型当主标题，修饰当副标题。
    #
    # 早先把两段拼成一个长词（「留一线的一套打到底」），读者要自己断句才看得懂。
    # 拆开之后主标题只有四个字，修饰单独一行，含义一眼就明白；分享文案里再用
    # 中点把两段连起来。
    if modifier:
        name = "{} · {}".format(style["name"], modifier["word"])
    else:
        name = style["name"]

    # 卡面上的九个数字：全部展示，但把偏离中性最远的四项排在前面，让每个人
    # 第一眼看到的重点都不一样。
    ordered = sorted(values.items(), key=lambda kv: -abs(kv[1] - 0.5))
    nine = [{"key": k, "label": LABELS[k], "value": v} for k, v in ordered]

    return {
        "name": name,
        "archetype": style["name"],
        "modifier": modifier,
        "match": match,
        "values": values,
        "highlight": nine[:4],
        "dimensions": nine,
        "conclusion": style["line"].format(**{
            k: int(round(v * 100)) for k, v in values.items()
        }),
        "turns": profile.get("total_turns", 0),
    }


# --------------------------------------------------------------------------
# 画卡
# --------------------------------------------------------------------------


#: 折行后可能被孤立到单独一行的句末标点。只有这些字符时才并回上一行。
_ORPHAN_PUNCT = "。，、；：！？）》”’…·.,;:!?)]}"


def _center(draw: ImageDraw.ImageDraw, y: int, text: str, font, fill) -> int:
    """居中画一行，返回这一行底部的 y。"""
    width = draw.textlength(text, font=font)
    draw.text(((W - width) / 2, y), text, font=font, fill=fill)
    box = draw.textbbox((0, 0), text, font=font)
    return y + (box[3] - box[1])


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    """按像素宽度折行。中文没有空格，只能逐字量。"""
    lines, current = [], ""
    for ch in text:
        if draw.textlength(current + ch, font=font) <= max_width:
            current += ch
        else:
            lines.append(current)
            current = ch
    if current:
        lines.append(current)
    # 中文句末标点很容易被挤成单独一行（正文占满一行，句号掉到下一行），
    # 在卡面上看着像凭空多了一个空行。只有标点时并回上一行——多出这一个字的
    # 宽度可以忽略，留白带来的突兀感不值得。
    if len(lines) >= 2 and lines[-1] and all(ch in _ORPHAN_PUNCT for ch in lines[-1]):
        orphan = lines.pop()
        lines[-1] += orphan
    return lines


def build_card(
    profile: dict,
    url: str = DEFAULT_URL,
    *,
    qr_payload: str = QR_URL,
    conclusion: str | None = None,
    evidence: list[str] | None = None,
) -> bytes:
    """渲染出牌风格卡，返回 PNG 字节。

    ``conclusion`` / ``evidence`` 只给 AI 版用：结论句换成模型针对这一局写的，
    另外多两三行"关键手"。风格名和匹配度始终来自本地计算，所以免费版和 AI 版
    是同一套体系，不会各说各话。
    """
    style = classify(profile)
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)

    # 外框：和 App 的卡片语言一致，先画底板再画边
    draw.rectangle([40, 40, W - 40, H - 40], fill=PANEL, outline=RULE, width=2)

    y = 96
    draw.text((96, y), "THE FITTEST", font=_font(28, True), fill=ACCENT)
    draw.text((96 + draw.textlength("THE FITTEST", font=_font(28, True)) + 18, y + 4),
              "出牌风格", font=_font(26), fill=MUTE)
    y += 62
    draw.line([96, y, W - 96, y], fill=ACCENT, width=4)
    y += 40

    # 主标题＝原型；副标题＝修饰。分开排，读者不用自己断句。
    size = 96
    while size > 52 and draw.textlength(style["archetype"], font=_font(size, True)) > W - 260:
        size -= 6
    y = _center(draw, y, style["archetype"], _font(size, True), INK)
    y += 14

    if style["modifier"]:
        y = _center(draw, y, style["modifier"]["word"], _font(44, True), ACCENT)
        y += 10

    y = _center(draw, y, "匹配度 {}%".format(int(round(style["match"] * 100))),
                _font(30), MUTE)
    y += 34

    # 结论句
    body = _font(34)
    text = conclusion or style["conclusion"]
    for line in _wrap(draw, text, body, W - 220):
        y = _center(draw, y, line, body, INK2)
        y += 48
    y += 22

    foot_y = H - 208

    # 九项维度：3×3 全部列出。免费卡的信息量主要来自这里——四项不够说明问题，
    # 而九项排成网格只占三行。
    #
    # 有 AI 证据时格子压矮一档：证据是付费版真正多出来的东西，读法是补充说明，
    # 空间不够时优先保证据。
    has_evidence = bool(evidence)
    cell_h = 74 if has_evidence else 112
    draw.text((96, y), "九项测量（偏离中性越远排得越前）",
              font=_font(26, True), fill=ACCENT)
    y += 50
    cell_w, gap = (W - 192 - 2 * 20) // 3, 20
    for index, item in enumerate(style["dimensions"]):
        col, row = index % 3, index // 3
        cx = 96 + col * (cell_w + gap)
        cy = y + row * (cell_h + gap)
        standout = index < 4
        draw.rectangle([cx, cy, cx + cell_w, cy + cell_h],
                       fill=PANEL2, outline=ACCENT if standout else RULE,
                       width=2 if standout else 1)
        if has_evidence:
            draw.text((cx + 18, cy + 12), item["label"], font=_font(21), fill=MUTE)
            draw.text((cx + 18, cy + 36),
                      "{}%".format(int(round(item["value"] * 100))),
                      font=_font(28, True), fill=ACCENT if standout else INK)
            bx, bw = cx + 110, cell_w - 128
            draw.rectangle([bx, cy + 44, bx + bw, cy + 52], fill=RULE)
            draw.rectangle([bx, cy + 44, bx + int(bw * item["value"]), cy + 52],
                           fill=ACCENT if standout else INK2)
        else:
            draw.text((cx + 18, cy + 16), item["label"], font=_font(23), fill=MUTE)
            draw.text((cx + 18, cy + 46),
                      "{}%".format(int(round(item["value"] * 100))),
                      font=_font(36, True), fill=ACCENT if standout else INK)
            bx, bw = cx + 18, cell_w - 36
            draw.rectangle([bx, cy + 92, bx + bw, cy + 100], fill=RULE)
            draw.rectangle([bx, cy + 92, bx + int(bw * item["value"]), cy + 100],
                           fill=ACCENT if standout else INK2)
    y += 3 * cell_h + 2 * gap + 20

    if not has_evidence:
        # 读法：九项方向不同，这条说明是必要的——否则读者会把"高"一律理解成"好"。
        # 它同时把免费卡下方的空间填成一个有内容的区块，而不是留白。
        draw.line([96, y, W - 96, y], fill=RULE, width=2)
        y += 24
        how = ("九项方向不同：回击倾向高＝被背叛必还手，主动剥削高＝对方合作也出手，"
               "单步收益效率高＝不浪费分。数值高低不代表好坏。")
        for line in _wrap(draw, how, _font(23), W - 192):
            draw.text((96, y), line, font=_font(23), fill=MUTE)
            y += 34

    # AI 版的关键手：先算得下几条，一条都放不下就整块不画。
    if evidence:
        limit = foot_y - 66
        room = limit - (y + 50)
        fits, used = [], 0
        for item in evidence[:3]:
            h = len(_wrap(draw, "· " + item, _font(26), W - 240)) * 38 + 6
            if used + h > room:
                break
            fits.append(item)
            used += h
        if fits:
            draw.text((96, y), "关键手", font=_font(26, True), fill=ACCENT)
            y += 46
            for item in fits:
                for line in _wrap(draw, "· " + item, _font(26), W - 240):
                    draw.text((112, y), line, font=_font(26), fill=INK2)
                    y += 38
                y += 6

    # 页脚
    draw.line([96, foot_y - 30, W - 96, foot_y - 30], fill=RULE, width=2)
    draw.text((96, foot_y),
              "基于 {} 步决策 · 不是心理诊断".format(style["turns"]),
              font=_font(24), fill=MUTE)
    draw.text((96, foot_y + 42), url, font=_font(36, True), fill=ACCENT)

    # 二维码编的是**完整 URL**（见 QR_URL），卡面文字才是短形式。
    try:
        qr = _qr(qr_payload)
        if qr is not None:
            img.paste(qr, (W - 96 - qr.width, foot_y - 8))
    except Exception:  # noqa: BLE001 - 二维码是加分项，画不出来不该让整张卡失败
        pass

    buffer = io.BytesIO()
    img.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _qr(text: str, box: int = 168):
    """把地址画成二维码。没装 qrcode 就返回 None，卡片照常出。"""
    try:
        import qrcode
    except ImportError:
        return None
    code = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=1,
    )
    code.add_data(text)
    code.make(fit=True)
    img = code.make_image(fill_color=INK, back_color=PANEL).convert("RGB")
    return img.resize((box, box), Image.NEAREST)


def share_text(profile: dict, url: str = DEFAULT_URL) -> str:
    """一键复制的纯文本版本，适配没有图片的地方（B站评论、群聊）。"""
    style = classify(profile)
    lines = [
        "我在 The Fittest 打了十局，出牌风格是「{}」（匹配度 {}%）。".format(
            style["name"], int(round(style["match"] * 100))),
        style["conclusion"],
        "九项测量：{}".format("、".join(
            "{} {}%".format(d["label"], int(round(d["value"] * 100)))
            for d in style["dimensions"])),
        "你也来试试：{}".format(url),
    ]
    return "\n".join(lines)
