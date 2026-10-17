"""录制前体检：AI 解读那一段现在能不能真跑通。

用法：
    ../.venv/Scripts/python.exe -X utf8 tools/check_analysis.py

退出码 0 = 通，1 = 不通。不通时把原因分成三类打印出来，因为这三类的修法完全不同：
密钥没配、域名解析不到、端点返回错误。

之所以要先看 DNS：这台机器常年挂着 FlClash，它用 fake-ip 接管解析（198.18.0.0/16）。
校内网关那类域名只在校内 DNS 里有记录，被 fake-ip 一接管就变成"看着解析成功、
握手却直接失败"，报出来的是一句 SSL 错误，很容易被误判成密钥或代码的问题。
"""

from __future__ import annotations

import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dashboard import ai_analysis  # noqa: E402

# Clash / Surge 一类的 fake-ip 段：出现它就说明解析被本地代理接管了。
FAKE_IP_PREFIX = "198.18."
def resolve(host: str) -> list[str]:
    try:
        return sorted({info[4][0] for info in socket.getaddrinfo(host, 443)})
    except socket.gaierror as error:
        print("  ✗ 解析不到 {}：{}".format(host, error))
        return []


def main() -> int:
    config = ai_analysis.server_config()
    print("接口：{}　模型：{}".format(
        ai_analysis.configured_provider_label(config), config["model"] or "（未填）"))
    print("密钥：{}".format("已配置" if config["key"] else "未配置"))
    print("代理：{}".format(config["proxy"] or "未配置（直连）"))

    if not config["ready"]:
        print("\n结论：不通——三件套（密钥 / 地址 / 模型名）没配齐。")
        print("修法：python .streamlit/setup_secrets.py <provider> --from-opencode")
        return 1

    url = config["base_url"].strip()
    host = url.split("//")[-1].split("/")[0]
    addresses = resolve(host)
    print("解析：{} → {}".format(host, "、".join(addresses) or "（无）"))
    if any(ip.startswith(FAKE_IP_PREFIX) for ip in addresses):
        print("　　　！这是本地代理的 fake-ip 地址，不是真实 IP。该域名若在代理的"
              "分流规则里没有可用的直连出口，握手就会失败。")
    if config["proxy"]:
        print("（本次探测走 ANALYSIS_PROXY 配置的代理，由下面的实际请求验证。）")

    try:
        answer = ai_analysis.probe_connection()
    except RuntimeError as error:
        detail = str(error)
        print("\n结论：不通——{}".format(detail))
        if detail.startswith("无法连接"):
            # 连不上是网络层的事：fake-ip 接管、或这个域名根本不在当前网络上。
            print("修法：确认本地代理已彻底退出（只关系统代理不够，TUN 与 fake-ip DNS"
                  "还在），并连上该域名所属的网络，再跑一次这条命令。")
        else:
            # 拿到状态码说明路是通的，问题在密钥、额度或模型名。
            print("修法：请求已经到达端点，所以网络是通的。按上面那句错误原文处理"
                  "（多为密钥失效、套餐过期或模型名不对），必要时换一个 provider 重配：\n"
                  "    python .streamlit/setup_secrets.py <provider> --from-opencode")
        return 1

    print("试调用：模型回了「{}」".format(answer.strip()[:20]))
    print("\n结论：通，可以开录。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
