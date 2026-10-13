"""MiniMax 接口连通性自检（不调用 API、不消耗额度）。

对 api.minimaxi.com:443 连续做 TCP 连接 + TLS 握手，统计成功率、延迟，
并判断证书是否被中间人替换（自签证书），用于定位 minimax 流中断问题。

用法：
    .\\.venv\\Scripts\\python.exe tools\\check_minimax.py [次数]
"""

from __future__ import annotations

import socket
import ssl
import sys
import time

HOST = "api.minimaxi.com"
PORT = 443


def probe(timeout: float = 8.0) -> tuple[str, float, str]:
    """返回 (状态, 毫秒, 说明)。"""
    start = time.perf_counter()
    try:
        with socket.create_connection((HOST, PORT), timeout=timeout) as raw:
            context = ssl.create_default_context()
            with context.wrap_socket(raw, server_hostname=HOST) as tls:
                peer = tls.getpeercert()
        elapsed = (time.perf_counter() - start) * 1000
        subject = dict(x[0] for x in peer.get("subject", [])) if peer else {}
        issuer = dict(x[0] for x in peer.get("issuer", [])) if peer else {}
        note = f"CN={subject.get('commonName', '?')} / 签发者={issuer.get('commonName', '?')}"
        return "ok", elapsed, note
    except ssl.SSLCertVerificationError as error:
        elapsed = (time.perf_counter() - start) * 1000
        return "cert-error", elapsed, f"证书不可信（疑似代理中间人）：{error.verify_message}"
    except (socket.timeout, TimeoutError):
        elapsed = (time.perf_counter() - start) * 1000
        return "timeout", elapsed, "连接/握手超时"
    except ConnectionResetError:
        elapsed = (time.perf_counter() - start) * 1000
        return "reset", elapsed, "连接被重置（ECONNRESET）"
    except OSError as error:
        elapsed = (time.perf_counter() - start) * 1000
        return "error", elapsed, str(error)


def main() -> None:
    rounds = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    print(f"目标：{HOST}:{PORT}，共 {rounds} 次")
    results: dict[str, int] = {}
    latencies: list[float] = []
    for index in range(rounds):
        status, ms, note = probe()
        results[status] = results.get(status, 0) + 1
        if status == "ok":
            latencies.append(ms)
        print(f"  [{index + 1:>2}] {status:<10} {ms:7.0f} ms  {note}")
    print()
    print("汇总：", results)
    if latencies:
        print(
            f"成功延迟：min {min(latencies):.0f} ms / 平均 "
            f"{sum(latencies) / len(latencies):.0f} ms / max {max(latencies):.0f} ms"
        )
    if results.get("cert-error"):
        print("→ 证书不可信：FlClash/代理在做 TLS 中间人，需让 Node 信任系统 CA 或把该域名设为直连。")
    if results.get("reset") or results.get("timeout"):
        print("→ 出现重置/超时：走代理节点时长连接不稳，建议对 minimaxi.com 直连或换稳定节点。")


if __name__ == "__main__":
    main()
