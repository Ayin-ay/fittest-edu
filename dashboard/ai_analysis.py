"""In-app LLM analysis of a finished game session.

The model receives the *whole* record: every one of the player's decisions with
the opponent's code, both action histories, the payoff earned, the payoff the
alternative would have earned, and the opponent's counterfactual next move. That
last field is what makes step-level reasoning possible rather than hand-waving -
the model can say "here you gave up 1 point to keep the opponent cooperating,
and it did cooperate next turn" because the counterfactual is in the data.

The prompt is deliberately restrictive, because the failure mode of an LLM
asked to "profile a player" is to produce a flattering horoscope. It is told to:

* quote specific matches and turns for every claim;
* reason about the player's likely intent at each cited step, and mark the
  difference between what the data shows and what is inference;
* not emit personality types, trait labels, or "you played like &lt;strategy&gt;";
* report contradictions instead of smoothing them;
* say "the record cannot tell us" when the data is insufficient.
"""

from __future__ import annotations

import json
import os
import re

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
KEY_ENV = "DEEPSEEK_API_KEY"

# 本 App 的公开地址。读者分享结果卡时，二维码与卡面文字都指向这里。
DEFAULT_APP_URL = "https://fittest-edu.streamlit.app/"

# 端点预设。key 的前缀（sk-…、sk-tp-…）标识的是厂商而不是主机名，所以主机要
# 显式指定，不靠猜。``minimax`` 两栏留空是有意的：MiniMax 的模型名按账号和区域
# 不同，猜错的表现和错 key 一样。
PROVIDERS = {
    "DeepSeek 官方": (DEFAULT_BASE_URL, DEFAULT_MODEL),
    "联想百应": ("https://api.baiying.lenovo.com/v1", "deepseek-v4-flash-0731"),
    "MiniMax 开放平台": ("https://api.minimaxi.com/v1", ""),
    "自定义": ("", ""),
}

SYSTEM_PROMPT = """\
你是一位博弈论教师，服务对象是一款囚徒困境教学对局网站：学生刚和若干固定规则的策略
程序对完局。交给你的只有逐轮记录（每一轮的双方出手、你拿到几分、另一手能拿几分、
两条分支下对手下一轮各怎么走）和总分。站内那九项维度结论刻意不发给你：请自己从
逐轮记录里推，不要指望有人把结论递给你。
你的读者是学生本人，不懂博弈论，也不关心策略编码本身。
你的任务是把这串出手讲回课本上的那几条结论，并示范怎么用一条数据去推翻一条定理的
适用条件——不是评价这个人。

【内容边界】

1. 不做心理或人格评价：禁止 MBTI、大五人格、类型代码，禁止「你是一个……的人」这类
   定性句，禁止「利己」「圣人」「控制狂」一类的形容词。你只看得见这几十步出手，
   看不见这个人的性格、动机、生活或职场表现，因此一律不予推断。

2. 禁止相似度匹配：不得说学生「像」某个策略、「接近」某种打法，不得把打法归成某类人。
   策略编码只作为「对手这轮做了什么」的背景出现，而且必须用中文转述。

3. 不得发明站内没测过的东西：推理层级（level-k）、均衡类型、心智理论能力这些都不在
   数据里，说了就是编造。你手上的只有出手序列、支付、对手规则与反事实分支。

4. 严格避免重复。同一件事只说一次；一个结论在第一节写过，后面换个说法再讲一遍也算重复。
   每个数字全文只允许出现一次。禁止用「这说明…」「这一点…」复述前面的数字。

5. 数据里有「如果当时选了另一手，对手会怎样」的字段。如果两种选择下对手的行为完全一样，
   这件事**既不是你的功劳也不是你的过错**，不要拿它当论据，也不要反复提及。

6. 不要把逐轮记录再抄成第二张表。你的任务是把出手接到课本那条条件句上，
   读者点回站内自己能查到每一轮做了什么。

7. 证据不足就直说「这组数据看不出」，并说明要多少局、换什么设计才看得出来。
   样本量小的读数必须带上「n 是多少」。

【输出格式】严格按以下标题输出，不要增删章节。章节从三级标题起、步骤用四级，
与站内的版面层级对齐：

### 这盘棋对应哪几条课本结论
3 到 6 条，一行一条。每条都必须写成条件句，并紧跟支撑它的那个数字：
「只有当……才……（本次数据：n=… 的读数是…）」优先。涉及的结论从这些里挑：
一轮里背叛对合作严格占优（T>R>P>S）、合作剩余只在双方都合作时兑现、
有限期的逆向归纳与终局坍塌、重复博弈里惩罚可信与否取决于贴现因子、
对手上一轮的行为如何决定你这一轮的收益（激励而非说教）、
策略可预测就被利用（ Folk 定理意义上的「能被识别」）。
数字与结论对不上时照实写「与这条结论冲突」，不要圆场。

### 关键轮次的结构分析
挑五到八轮最有信息量的，按下面格式逐步写：

#### 第 N 局 · 第 T 轮
- **这一轮的支付结构**：这一格在矩阵上的位置，你与对手各拿几分，另一手分别能拿几分。
- **它改变了什么**：对手随后几轮的行为差异。若反事实分支相同，直接写「这一手什么都没换来」。
- **它算哪条结论的证据**：这一轮支持或推翻了上面哪一条，一句话说清。

### 哪些读数站得住，哪些只是噪声
逐条说明：本局样本量下哪些测量可靠，哪些因为 n 太小、对手本身带随机数或轮数不够而
几乎不含信息，并给出大致的样本量要求。允许这条节写「这项现在不能用来做任何判断」。

### 下一局可以验证什么
3 到 5 个可证伪的问题，写成「如果……那么这里应该看到……，否则说明……」。
不写建议，不写人生道理，不写该怎么做人。

### 这次数据回答不了什么
列出这组数据无法判断的事情，以及需要多少局、换什么设计才能判断。
"""


OVERVIEW_SYSTEM_PROMPT = """\
你是一位博弈论教师，服务对象是一款囚徒困境教学对局网站。你的读者是学生本人，
不懂博弈论，也不关心策略编码本身。站内已经用确定性算术算好了测量数字，
交给你的是这些数字和逐轮记录。

这一轮**只输出「这盘棋对应哪几条课本结论」那一节**，不要输出任何其他章节，
不要写标题，不要写开场白，直接开始列条目。交给你的只有逐轮记录与总分，
站内的维度结论不发给你，请自己从逐轮记录里数。

格式要求：

- 只列 3 到 5 行，一行一条，让人不读下文也能立刻抓住该注意的那几条。
- 每行必须以一个符号开头，用符号标出性质：
  ★ 数据强支持的一条　⚠ 与数据冲突或需要留意的　◆ 这次结构里少见的一条　↓ 样本太小、暂时读不出来的
- 每行必须用**加粗**标出支撑它的那个数字（带上 n），例如
  「⚠ **末轮背叛 4/4 场**，与有限期逆向归纳预测的终局坍塌一致，但前段只有 1/32 轮背叛，n 太小」。
- 全篇 200 字以内。只写看得见的数字与课本结论的关系。

禁止：写建议、推断动机、给人格或性格标签（MBTI、大五人格、「你是一个……的人」这类句式）；
说学生「像」某个策略；提及推理层级、均衡类型、心智理论这类站内没有测量的东西。简体中文书写。
"""

OVERVIEW_USER_SUFFIX = (
    "\n\n这一轮只输出「这盘棋对应哪几条课本结论」，3 到 5 行、200 字以内，"
    "不要输出其他章节。"
)

PLANS = {
    "overview": (OVERVIEW_SYSTEM_PROMPT, OVERVIEW_USER_SUFFIX, 1200),
    # 16384, not 4096.
    #
    # `deepseek-v4-flash` is a reasoning model: it streams `reasoning_content`
    # before any `content`. Measured against this gateway, the full five-section
    # report at 4096 tokens ends with `finish_reason=length` and **zero** content
    # chunks — the whole budget went to thinking. 8192 was still not enough
    # (8190 reasoning chunks, 0 content).
    #
    # 16384 finishes with the report written. It is also non-deterministic: the
    # model occasionally spirals and burns even that. That is why the body also
    # carries `reasoning_effort: low` (see REASONING_EFFORT) — it cut a run from
    # 131-183s down to 32s and all but removes the spiral. The large ceiling
    # stays as the safety net for gateways that ignore the hint.
    #
    # A non-reasoning model never fills either, so neither costs anything there.
    # That ceiling is only about models that actually think -- see
    # REASONING_MARKERS for why the hint is not sent to the others.
    "full": (SYSTEM_PROMPT, "", 16384),
}

#: Hint asking a reasoning model not to over-think. Accepted by this gateway
#: (verified: no 400, ~4-5x faster). Not every provider supports it, so a 400
#: mentioning it drops the key and retries, exactly like the temperature override.
REASONING_EFFORT = "low"

#: Names that say the model thinks before it writes. The hint is only sent to
#: those, because on a hybrid endpoint the hint *is* the thinking switch:
#: measured against DeepSeek's official API, ``deepseek-chat`` with
#: ``reasoning_effort: low`` streamed 36 ``reasoning_content`` chunks and one
#: content chunk, and the same request without it streamed zero reasoning. In
#: other words, asking a non-reasoning model to reason less made it start
#: reasoning — and a long five-section report then spends the whole token
#: ceiling on thinking and arrives as ``finish_reason=length`` with no body.
REASONING_MARKERS = ("reasoner", "r1", "think", "qwq", "v4-flash", "o1-", "o3-")


def wants_reasoning_hint(model: str) -> bool:
    """True when ``reasoning_effort`` should be sent for this model name."""
    name = (model or "").lower()
    return any(marker in name for marker in REASONING_MARKERS)


# Some gateways reject anything but ``temperature: 1`` with a 400, so a model
# that would otherwise work becomes unusable. Retry once without the override
# before reporting a failure, because the request body is otherwise identical.
TEMPERATURE_RETRY_STATUS = 400


def _looks_like_temperature_rejection(body: str) -> bool:
    low = body.lower()
    return "temperature" in low


def _looks_like_unsupported(body: str, field: str) -> bool:
    """True when a 400 is complaining about ``field`` specifically.

    Gateways word this differently ("unknown parameter", "unsupported",
    "not permitted"), so match on the field name appearing at all rather than on
    a particular phrase.
    """
    return field.lower() in body.lower()


def build_session_payload(profile: dict, results: dict) -> dict:
    """Everything the model needs, in a compact form.

    Keys are Chinese on purpose. The previous version shipped English field
    names and the model quoted them verbatim in its report ("opp_next_actual
    = 合作"), which leaked straight into the player's report. The pre-computed
    dimension list is deliberately *not* sent: the model restated it almost
    word for word, which produced exactly the repetition the report was meant
    to avoid.
    """
    matches = []
    for match in profile["matches"]:
        steps = []
        for d in match.decisions:
            steps.append({
                "轮次": d.turn,
                "你之前的出手": d.player_history or "（无）",
                "对手之前的出手": d.opponent_history or "（无）",
                "对手上一轮": (
                    "无" if not d.opponent_history else
                    ("背叛" if d.opponent_history[-1] == "D" else "合作")
                ),
                "你的选择": "合作" if d.action == "C" else "背叛",
                "对手这一轮": "合作" if d.opponent_action == "C" else "背叛",
                "你拿到几分": d.payoff,
                "另一手能拿几分": d.alternative_payoff,
                "另一手是什么": "背叛" if d.alternative == "D" else "合作",
                "按你的选择对手下一轮": (
                    "合作" if d.opponent_next_if_chosen == "C" else "背叛"
                ),
                "若换另一手对手下一轮": (
                    "合作" if d.opponent_next_if_alternative == "C" else "背叛"
                ),
            })
        # The opponent is described by what it did rather than by its encoding,
        # so the report reads as prose instead of a code listing. The encoding is
        # still available to the model for a passing inline mention, because the
        # prompt allows naming a strategy as long as Chinese does the explaining.
        pattern = []
        if match.opponent_defection_rate == 0:
            pattern.append("全程未背叛")
        elif match.opponent_defection_rate < 0.25:
            pattern.append("极少背叛")
        elif match.opponent_defection_rate < 0.6:
            pattern.append("间歇性背叛")
        else:
            pattern.append("频繁背叛")
        if match.opponent_actions.startswith("C" * max(len(match.opponent_actions) - 2, 1)):
            pattern.append("开局连续合作")
        if match.opponent_actions.endswith("D"):
            pattern.append("最后一轮背叛")
        matches.append({
            "局次": match.index + 1,
            "对手特征": "、".join(pattern),
            "对手编码": match.opponent,
            "对手完整出手": match.opponent_actions,
            "你的完整出手": match.player_actions,
            "你的得分": match.player_score,
            "对手得分": match.opponent_score,
            "逐轮": steps,
        })

    return {
        "规则": "每局 {} 轮。收益：双方合作各得 3 分；你合作它背叛，你得 0、它得 5；"
                "双方背叛各得 1 分。".format(results["turns"]),
        "总成绩": {
            "总分": round(profile["player_total"], 1),
            "每局平均": round(profile["player_average"], 2),
            "这些对手彼此对战的平均分": round(results["field_average"], 2),
            "你出手背叛的次数": "{} / {}".format(
                profile["total_defections"], profile["total_turns"]
            ),
        },
        "对局明细": matches,
    }


def build_user_message(payload: dict) -> str:
    return (
        "以下是一名学生与 {} 个自动生成对手（固定规则的策略程序）的完整对局记录，"
        "共 {} 步选择；每轮都带上这一手拿到几分、另一手能拿几分，"
        "以及两条分支下对手下一轮各怎么走。\n\n"
        "请按系统提示的章节顺序输出，全文使用简体中文。\n"
        "注意：那些对手是程序生成的固定规则，不会学习、没有意图，只是用来制造"
        "不同的博弈情境；它们不代表真实的人，学生的行为也不反映真实人格。\n\n"
        "记录数据（JSON）：\n{}".format(
            len(payload["对局明细"]),
            sum(len(m["逐轮"]) for m in payload["对局明细"]),
            json.dumps(payload, ensure_ascii=False, indent=1),
        )
    )


def available_key() -> str | None:
    return server_config()["key"]


def server_config() -> dict:
    """Resolve the site-wide analysis credentials.

    Every visitor shares one key, so it lives on the server and is never shown
    to, or typed by, a player. Sources are tried in order:

    1. ``st.secrets`` -- Streamlit Cloud Secrets, or ``.streamlit/secrets.toml``
       locally. This is the intended place; the file is gitignored.
    2. environment variables -- convenient for local runs.
    3. nothing -- the feature then reports itself as unconfigured.
    """
    import os as _os

    def from_secrets(name: str) -> str:
        try:
            import streamlit as st

            value = st.secrets.get(name, "")
            return str(value).strip() if value else ""
        except Exception:  # noqa: BLE001 - no secrets file, or not running in Streamlit
            return ""

    key = (
        from_secrets("ANALYSIS_API_KEY")
        or from_secrets("DEEPSEEK_API_KEY")
        or from_secrets("OPENAI_API_KEY")
        or _os.getenv("ANALYSIS_API_KEY", "").strip()
        or _os.getenv("DEEPSEEK_API_KEY", "").strip()
        or _os.getenv("OPENAI_API_KEY", "").strip()
    )
    base_url = (
        from_secrets("ANALYSIS_BASE_URL")
        or _os.getenv("ANALYSIS_BASE_URL", "").strip()
    )
    model = (
        from_secrets("ANALYSIS_MODEL")
        or _os.getenv("ANALYSIS_MODEL", "").strip()
    )
    proxy = (
        from_secrets("ANALYSIS_PROXY")
        or _os.getenv("ANALYSIS_PROXY", "").strip()
    )
    app_url = (
        from_secrets("ANALYSIS_APP_URL")
        or _os.getenv("ANALYSIS_APP_URL", "").strip()
        or DEFAULT_APP_URL
    )
    # A bare key is useless without a host and a model name, so fall back to the
    # documented default only when neither was configured. The host is *not*
    # inferred from the key's prefix: the prefixes in play (sk-tp-… on 联想百应,
    # sk-<digits>… on TokenDance) identify different vendors and do not imply a
    # host, so a gateway must be selected by setting ANALYSIS_BASE_URL.
    if key and not base_url:
        base_url = DEFAULT_BASE_URL
    if key and not model:
        model = DEFAULT_MODEL
    return {
        "key": key,
        "base_url": base_url,
        "model": model,
        "proxy": proxy,
        "app_url": app_url,
        "ready": bool(key and base_url and model),
    }


def configured_provider_label(config: dict) -> str:
    """Human label for whatever host is configured, for the status line."""
    if not config.get("base_url"):
        return "未配置"
    host = config["base_url"].split("//")[-1].split("/")[0]
    for name, (url, _) in PROVIDERS.items():
        if url and host in url:
            return name
    return host


def _sanitize(text: str, api_key: str | None = None) -> str:
    """Strip anything key-shaped out of text that will be shown on screen.

    Auth endpoints like to echo the tail of the offending key back in their
    error bodies, and that text ends up in the browser. Redact both the exact key
    we were given and any generic ``sk-…`` run.
    """
    cleaned = text
    if api_key:
        cleaned = cleaned.replace(api_key, "***")
    cleaned = re.sub(r"sk-[A-Za-z0-9_\-]{6,}", "sk-***", cleaned)
    return cleaned


def _proxies(proxy: str | None) -> dict | None:
    """Route the call through an explicit HTTP proxy, if one is given.

    Direct egress to the API hosts is blocked on some networks (GitHub and the
    overseas model endpoints alike), so a local proxy such as FlClash has to be
    passed through explicitly -- ``requests`` only picks up proxies it can
    discover from the environment or the Windows registry.
    """
    target = (proxy or os.getenv("ANALYSIS_PROXY") or "").strip()
    if not target:
        return None
    if "://" not in target:
        target = "http://" + target
    return {"http": target, "https": target}


def _headers(key: str, app_url: str | None = None) -> dict:
    headers = {
        "Authorization": "Bearer {}".format(key),
        "Content-Type": "application/json",
    }
    target = (app_url or "").strip()
    if target:
        headers["X-App-URL"] = target
    return headers


def _post(url: str, body: dict, key: str, timeout, proxy: str | None = None,
          app_url: str | None = None):
    import requests

    return requests.post(
        url,
        headers=_headers(key, app_url),
        json=body,
        timeout=timeout,
        proxies=_proxies(proxy),
    )


def _body_text(response) -> str:
    """Read an error body as UTF-8.

    网关经常返回 UTF-8 的中文错误却不声明 charset，requests 于是按 latin-1 解，
    屏幕上只剩一串乱码——而这句话恰恰是人判断"该改什么"的唯一线索。
    """
    if "charset" not in (response.headers.get("Content-Type") or "").lower():
        response.encoding = "utf-8"
    return response.text


def _call_error(response, url: str, key: str) -> str:
    """Explain a failed call in terms of what the reader can act on.

    本站统一提供解读额度，访客不需要自备钱包，所以错误提示要落到"站点配置"
    和"稍后重试"上，而不是引导去某个充值页面——那是上一个版本的设定。
    """
    status = response.status_code
    if status == 401:
        return "接口拒绝了本站的密钥（{}）。请稍后再试，或联系管理员更换密钥。".format(
            _sanitize(_body_text(response)[:200], key)
        )
    if status == 402:
        return "本站的调用额度已用尽，请稍后再试。"
    if status == 429:
        return "请求过于频繁，请稍后再试。"
    return "接口返回 {}：{}".format(status, _sanitize(_body_text(response)[:300], key))


def probe_connection(timeout: int = 45, key: str | None = None) -> str:
    """Confirm the site's own credentials work, so a failure here is not blamed on
    the player.

    There is no key field any more: the site shares one, so this check only
    verifies reachability and that the configured model name is accepted.
    ``key`` lets the check run against a visitor's own wallet instead.
    """
    config = server_config()
    key = key or config["key"]
    if not key:
        raise RuntimeError("本站尚未配置分析密钥，请联系维护者。")
    url = config["base_url"].strip()
    chosen = config["model"].strip()
    if not url or not chosen:
        raise RuntimeError("本站的接口地址或模型名未配置完整。")
    request_url = url.rstrip("/") + "/chat/completions"
    try:
        response = _post(
            request_url,
            {"model": chosen,
             "messages": [{"role": "user", "content": "回复两个字：可用"}],
             "max_tokens": 8},
            key, (15, timeout), config["proxy"], config.get("app_url"),
        )
    except Exception as error:  # noqa: BLE001 - report reachability clearly
        raise RuntimeError(
            "无法连接 {}：{}。若该地址需要代理，请由维护者在服务端配置 "
            "ANALYSIS_PROXY。".format(url, _sanitize(str(error), key))
        ) from error
    if response.status_code >= 400:
        raise RuntimeError("{}：{}".format(
            response.status_code, _sanitize(_body_text(response)[:400], key)))
    return response.json()["choices"][0]["message"]["content"]


def _open_stream(route: str, key: str, body: dict, app_url: str | None,
                 connect_timeout: int, read_timeout: int, proxies):
    import requests

    return requests.post(
        route,
        headers=_headers(key, app_url),
        json=body,
        timeout=(connect_timeout, read_timeout),
        proxies=proxies,
        stream=True,
    )


def _stream_body(route: str, body: dict, key: str, config: dict,
                 plan: str = "full",
                 connect_timeout: int = 30, read_timeout: int = 600,
                 proxy: str | None = None, app_url: str | None = None):
    """Send one streaming request and yield its text chunks.

    Both report types go through here so the wallet key, the App URL attribution
    header, the temperature retry and the SSE decoding exist once: two copies of
    that would drift, and the divergence is invisible until a call silently
    stops being attributed.
    """
    import requests

    proxies = _proxies(proxy or config["proxy"])
    effective_app_url = app_url or config.get("app_url")
    try:
        response = _open_stream(route, key, body, effective_app_url,
                                connect_timeout, read_timeout, proxies)
        # Two independent compatibility escapes. A gateway may reject the
        # temperature override, or the reasoning hint, or both; each retry drops
        # one key and keeps everything else identical, so the call that finally
        # succeeds is still the same request in every other respect.
        for dropped in ("temperature", "reasoning_effort"):
            if response.status_code != TEMPERATURE_RETRY_STATUS or dropped not in body:
                break
            if dropped == "temperature" and not _looks_like_temperature_rejection(response.text):
                break
            if dropped == "reasoning_effort" and not _looks_like_unsupported(response.text, dropped):
                break
            body.pop(dropped, None)
            response = _open_stream(route, key, body, effective_app_url,
                                    connect_timeout, read_timeout, proxies)
    except requests.exceptions.ConnectTimeout as error:
        raise RuntimeError(
            "连接 {} 超时。若该地址需要代理，请由维护者在服务端配置 "
            "ANALYSIS_PROXY。".format(route)
        ) from error
    except requests.exceptions.RequestException as error:
        raise RuntimeError(
            "网络错误：{}".format(_sanitize(str(error), key))) from error

    if response.status_code >= 400:
        raise RuntimeError(_call_error(response, route, key))

    # A provider without SSE answers with ordinary JSON despite the request.
    content_type = response.headers.get("Content-Type", "")
    if "text/event-stream" not in content_type:
        try:
            yield response.json()["choices"][0]["message"]["content"]
            return
        except Exception as error:  # noqa: BLE001 - any shape of bad payload
            raise RuntimeError(
                "返回格式异常（可能不是 OpenAI 兼容接口）：{}".format(
                    _sanitize(response.text[:200], key))
            ) from error

    emitted = False
    reasoning_only = False
    finish_reason = None
    for line in response.iter_lines(decode_unicode=False):
        # Decode explicitly: the gateway sends SSE without a charset, and
        # requests would fall back to ISO-8859-1 and split every three-byte
        # Chinese character into three mojibake symbols.
        if isinstance(line, bytes):
            try:
                line = line.decode("utf-8")
            except UnicodeDecodeError:
                line = line.decode("utf-8", errors="replace")
        if not line or not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        try:
            chunk = json.loads(data)
            choice = chunk["choices"][0]
            delta = choice.get("delta", {})
            if choice.get("finish_reason"):
                finish_reason = choice["finish_reason"]
            text = delta.get("content")
            # Reasoning models stream `reasoning_content` first. It is NOT the
            # answer, so it is never yielded -- but its presence has to be
            # recorded, otherwise a starved run looks identical to a broken
            # endpoint.
            if delta.get("reasoning_content") or delta.get("reasoning"):
                reasoning_only = True
        except (ValueError, KeyError, IndexError):
            continue
        if text:
            emitted = True
            # Once real content starts arriving, the run is not reasoning-only.
            reasoning_only = False
            yield text
    if not emitted:
        if reasoning_only and finish_reason == "length":
            raise RuntimeError(
                "模型把 token 预算全部用在了推理上，还没写到正文就被截断了。"
                "这是推理模型遇到长任务时的常见行为。完整版的上限已经调高；"
                "若仍失败，请在服务端换用非推理模型，或改用「结论速览」。"
            )
        raise RuntimeError(
            "接口返回了空内容。若所配置的模型不支持该接口，"
            "请由维护者更换模型名。"
        )

def stream_text(system_prompt: str, user_prompt: str, *,
                visitor_key: str | None = None,
                plan: str = "full",
                connect_timeout: int = 30,
                read_timeout: int = 600):
    """Stream a completion for an arbitrary system/user pair.

    ``stream_analysis`` is specialised for the game report: it builds the session
    payload itself and uses the fixed behaviour prompt. The creation mode needs
    the same transport -- the visitor's wallet, the attribution header, the SSE
    decoding -- over a different payload, so this exposes the plumbing and lets
    the caller supply the two prompts.
    """
    config = server_config()
    # An explicit empty visitor key means "no wallet connected", and must not
    # fall through to the site's own key: that would spend the site's balance
    # for a visitor who never authorised anything.
    if visitor_key is not None and not visitor_key.strip():
        raise RuntimeError("尚未连接 Token 钱包，无法发起分析。")
    key = visitor_key or config["key"]
    if not key:
        raise RuntimeError("本站尚未配置分析密钥，请联系维护者。")
    url = (config["base_url"] or "").strip()
    model = (config["model"] or "").strip()
    if not url or not model:
        raise RuntimeError(
            "本站的接口地址或模型名未配置。模型名因服务商与账号而异，"
            "需由维护者填写。"
        )
    _, _, max_tokens = PLANS.get(plan, PLANS["full"])
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.5,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if wants_reasoning_hint(model):
        body["reasoning_effort"] = REASONING_EFFORT
    return _stream_body(
        url.rstrip("/") + "/chat/completions", body, key, config, plan,
        connect_timeout, read_timeout,
    )


def stream_analysis(
    profile: dict,
    results: dict,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    proxy: str | None = None,
    app_url: str | None = None,
    visitor_key: str | None = None,
    plan: str = "full",
    connect_timeout: int = 30,
    read_timeout: int = 600,
):
    """Yield the report token by token so long generations are not silent.

    ``visitor_key`` is the Key the player authorised on their own wallet. When
    present it pays for the call, so the site never spends its own balance; the
    App URL header is still sent, so the call is attributed either way.

    ``plan`` selects the prompt: ``overview`` asks only for a short verdict, so
    the reader sees a conclusion in seconds while ``full`` is still being
    generated.

    Falls back to a single-shot request when the endpoint does not stream, so a
    provider without SSE support still works.
    """
    config = server_config()
    key = visitor_key or api_key or config["key"]
    if not key:
        raise RuntimeError("本站尚未配置分析密钥，请联系维护者。")
    system_prompt, suffix, max_tokens = PLANS.get(plan, PLANS["full"])
    url = (base_url or config["base_url"] or "").strip()
    chosen = (model or config["model"] or "").strip()
    if not url:
        raise RuntimeError("本站的接口地址未配置。")
    if not chosen:
        raise RuntimeError(
            "本站的模型名未配置。模型名因服务商与账号而异，需由维护者填写。"
        )
    payload = build_session_payload(profile, results)
    body = {
        "model": chosen,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": build_user_message(payload) + suffix},
        ],
        "temperature": 0.5,
        "max_tokens": max_tokens,
        "stream": True,
    }
    if wants_reasoning_hint(chosen):
        body["reasoning_effort"] = REASONING_EFFORT
    return _stream_body(
        url.rstrip("/") + "/chat/completions", body, key, config, plan,
        connect_timeout, read_timeout, proxy, app_url,
    )

def analyse(
    profile: dict,
    results: dict,
    *,
    timeout: int = 300,
) -> str:
    """Collect a full streamed report into one string, using the site's key."""
    return "".join(stream_analysis(
        profile, results, read_timeout=timeout + 300,
    ))

