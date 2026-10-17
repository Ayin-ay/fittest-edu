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
你是一位人际博弈行为分析师，服务对象是一款「与策略对局后分析玩家决策」的网站。
你的读者是本人，不懂博弈论，也不关心策略编码本身。

【写作硬性要求】

1. 以简体中文为主体写作。禁止**整节、整段**用英文代替中文——那等于没有分析。
   但行内出现英文专有名词（模型名、策略编码原文、英文缩写）是允许的，
   前提是紧跟中文说明，且不能成为段落的主要内容。例如
   「对手 `R1-1`，也就是被背叛一回合就还手一回合的那种」可以；
   整节写成英文表格或英文要点列表不可以。
   不要把数据里的程序字段名（形如 opp_next_actual、customdata、prompt）
   当作术语写进正文——那是在展示数据结构，不是在分析人。

2. 严格避免重复。同一件事只说一次；如果一个结论在「总体判断」里已经写过，
   后面的章节就不要换个说法再讲一遍。禁止用「这说明…」「这一点…」反复复述
   前面已给出的数字。每个数据点全文只允许出现一次。

3. 数据里有「如果当时选了另一手，对手会怎样」的字段。如果两种选择下
   对手的行为完全一样，这件事**既不是你的功劳也不是你的过错**，
   不要拿它当论据，也不要反复提及。

4. 不要贴「统计维度」里的原始结论，你的任务是解释它们背后的原因，
   而不是把它们抄一遍。

【内容边界】

5. 不得使用人格类型或性格标签：禁止 MBTI、大五人格、类型代码，
   禁止「你是一个……的人」这类定性句，禁止使用「利己」「圣人」「控制狂」
   「控制狂人格」等形容词定性。

6. 禁止相似度匹配：不得说玩家「像」某个策略，「接近」某种打法，
   不得把玩家归入某类人。策略编码只作为「对手在做什么」的背景出现，
   而且必须用中文转述。

7. 你的结论要**落到现实**：每条行为模式都必须对应到真实的人际关系或
   工作场景（例如：面对突然翻脸的同事、谈判中的对方、长期合作中的伙伴），
   讲清它在那里会带来什么后果。只讲游戏内机制的分析不合格。

8. 证据不足就直说「这局数据看不出」。不要为了篇幅编造动机。

【输出格式】严格按以下标题输出，不要增删章节。章节从三级标题起、步骤用四级，
与站内的版面层级对齐：

### 关键特征
**这一节必须放在最前面，是全文唯一允许「不展开」的部分。**

- 只写 3 到 5 行，一行一条，让人不读下文也能立刻知道该注意什么。
- 每行必须以一个符号开头，用符号标出性质：
  ★ 明显高于常人的地方　⚠ 需要留意的地方　◆ 独特但不常见的选择　↓ 明显回避的地方
- 每行必须用**加粗**标出支撑它的那个数字，例如
  「★ **10 局全部首轮合作**（10/10），在陌生情境下先垫付资源」。
- 禁止在这一节写建议或推断动机，只写看得见的现象及其数字。

### 关键步骤剖析
挑五到八步最有信息量的，按下面格式逐步写：

#### 第 N 局 · 第 T 轮
- **当时的局面**：双方前几轮做了什么，一句话说清。
- **你的选择与代价**：你出了什么，这一手拿到了几分、另一手能拿几分。
- **你可能在想什么**：一到两句推断，必须用「可能是」「看起来像」这类措辞，
  并给出推断依据。
- **换到现实里**：同样的选择如果发生在工作中或人际关系里，会出现什么。

### 你的行为模式
去重后的清单，每条包含：观察到的现象（一句话）＋支撑数据（只给一次）＋
它意味着什么。不要与其他条目重复。

### 诊断
分两部分，都要具体：
- **优势**：这个反应方式在什么场合是有用的（举一个现实例子）。
- **代价**：它在什么场合会造成损失（举一个现实例子，优先用这次数据里
  真实发生过的场景）。

### 生活与工作中的建议
分「立刻可以做的」和「长期要练的」两组，每条都要能直接照着做，
并说明预期效果和可能的风险。

### 这次数据回答不了什么
列出这局数据无法判断的事情，以及需要多少局、换什么设计才能判断。
"""


OVERVIEW_SYSTEM_PROMPT = """\
你是一位人际博弈行为分析师，服务对象是一款「与策略对局后分析玩家决策」的网站。
你的读者是本人，不懂博弈论，也不关心策略编码本身。

这一轮**只输出「结论速览」一节**，不要输出任何其他章节，不要写标题，
不要写开场白，直接开始列条目。

格式要求：

- 只列 3 到 5 行，一行一条，让人不读下文也能立刻知道该注意什么。
- 每行必须以一个符号开头，用符号标出性质：
  ★ 明显高于常人的地方　⚠ 需要留意的地方　◆ 独特但不常见的选择　↓ 明显回避的地方
- 每行必须用**加粗**标出支撑它的那个数字。
- 全篇 200 字以内。只写看得见的现象及其数字，**不要写建议、不要推断动机**。

禁止使用人格类型或性格标签（MBTI、大五人格、「你是一个……的人」这类句式），
禁止说玩家「像」某个策略。简体中文书写。
"""

OVERVIEW_USER_SUFFIX = (
    "\n\n这一轮只要「结论速览」，3 到 5 行、200 字以内，不要输出其他章节。"
)

PLANS = {
    "overview": (OVERVIEW_SYSTEM_PROMPT, OVERVIEW_USER_SUFFIX, 1200),
    # 16384, not 4096.
    #
    # `deepseek-v4-flash` is a reasoning model: it streams `reasoning_content`
    # before any `content`. Measured against this gateway, the six-section full
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
    "full": (SYSTEM_PROMPT, "", 16384),
}

#: Hint asking a reasoning model not to over-think. Accepted by this gateway
#: (verified: no 400, ~4-5x faster). Not every provider supports it, so a 400
#: mentioning it drops the key and retries, exactly like the temperature override.
REASONING_EFFORT = "low"

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
        "以下是一名玩家与 {} 个自动生成对手的完整对局记录，共 {} 步选择。\n\n"
        "请按系统提示的章节顺序输出分析，全文使用简体中文。\n"
        "注意：这些对手是程序随机生成的固定规则程序，它们只是用来制造不同的"
        "人际情境，不代表真实的人。\n\n记录数据（JSON）：\n{}".format(
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
        "reasoning_effort": REASONING_EFFORT,
    }
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
        "reasoning_effort": REASONING_EFFORT,
    }
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


# --------------------------------------------------------------------------
# 风格卡上的那段结论
#
# 这是**另一次独立调用**，不是放开主报告的禁令。主报告仍然禁止任何定性结论；
# 这里只放开了"对出牌行为下一句评价"这一件事，人格类型、MBTI、"你是……的人"
# 依旧禁止。理由是卡片需要一个收得住的结论，而主报告的价值恰恰在于逐轮举证。
#
# 输出要求写成 JSON，因为卡片要的是两个确定字段，不是一段散文：散文没法排版，
# 也没法保证长度。
# --------------------------------------------------------------------------

CARD_SYSTEM_PROMPT = """\
你在给一位刚玩完 The Fittest 的玩家写一张分享卡上的结论。

输出**一个 JSON 对象**，不要任何其他文字、不要代码块围栏：
{"conclusion": "……", "evidence": ["……", "……", "……"]}

conclusion：一句到两句，**不超过 60 个字**。它要能独立成立——读者只看这一句
也要明白这个人是怎么出牌的。写他在什么时候出手、什么时候收手、对谁不一样，
不要评价他"是什么样的人"。

evidence：3 条，每条**不超过 40 个字**，必须引用具体局次轮次，例如
"第 3 轮你 D · 它 C 拿到 5 分"。挑最能说明上面那句结论的三手。

硬性禁止（与主报告一致，只是这里允许你下结论）：
1. 禁止人格类型与性格标签：不得出现 MBTI、大五人格、类型代码，
   不得写「你是一个……的人」，不得用「利己」「圣人」「控制狂」这类形容词定性。
2. 禁止说你"像"某个策略，也禁止把玩家归入某类人。
3. 不要复述九项维度的分数，那部分卡片上已经有了。
4. 证据不足就写得更保守，不要为了凑字数编造轮次。
"""

CARD_USER_SUFFIX = """

请严格按上面的 JSON 格式输出。"""


def card_verdict(
    profile: dict,
    results: dict,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    proxy: str | None = None,
    app_url: str | None = None,
    visitor_key: str | None = None,
    read_timeout: int = 180,
) -> dict:
    """要一段能放在风格卡上的结论，返回 ``{"conclusion": str, "evidence": [str]}``。

    调用方式和主报告完全一样（同一个钱包、同一个归因头），只是换了 prompt。
    输出不是合法 JSON 时返回空 dict，让卡片退回本地计算的结论——卡片是分享
    入口，不该因为模型抖一下就整块消失。
    """
    config = server_config()
    key = visitor_key or api_key or config["key"]
    if not key:
        raise RuntimeError("本站尚未配置分析密钥，请联系维护者。")
    url = (base_url or config["base_url"] or "").strip()
    chosen = (model or config["model"] or "").strip()
    if not url or not chosen:
        raise RuntimeError("本站的接口地址或模型名未配置。")

    payload = build_session_payload(profile, results)
    body = {
        "model": chosen,
        "messages": [
            {"role": "system", "content": CARD_SYSTEM_PROMPT},
            {"role": "user", "content": build_user_message(payload) + CARD_USER_SUFFIX},
        ],
        "temperature": 0.4,
        # Same reasoning-model arithmetic as the full plan: the visible answer is
        # only a short JSON, but the model may think for thousands of tokens
        # first, and a 500-token ceiling would let it run out before answering.
        "max_tokens": 4096,
        "stream": True,
        "reasoning_effort": REASONING_EFFORT,
    }
    text = "".join(_stream_body(
        url.rstrip("/") + "/chat/completions", body, key, config, "card",
        30, read_timeout, proxy, app_url,
    ))
    return _parse_card_json(text)


def _parse_card_json(text: str) -> dict:
    """从模型输出里取出那个 JSON 对象，取不到就返回空 dict。"""
    import json as _json

    cleaned = text.strip()
    # 模型有时会套一层 ```json 围栏，先剥掉。
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1] if "```" in cleaned[3:] else cleaned[3:]
        cleaned = cleaned.lstrip("json").strip() if cleaned.lstrip().startswith("json") else cleaned
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = _json.loads(cleaned[start:end + 1])
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    conclusion = str(data.get("conclusion") or "").strip()
    evidence = data.get("evidence") or []
    if isinstance(evidence, str):
        evidence = [evidence]
    evidence = [str(item).strip() for item in evidence if str(item).strip()]
    if not conclusion:
        return {}
    return {"conclusion": conclusion, "evidence": evidence[:3]}
