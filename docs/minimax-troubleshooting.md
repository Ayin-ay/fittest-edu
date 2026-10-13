# MiniMax（或其它国内大模型）流中断排查

## 症状
- 对话/任务进行到一半突然停止，输出被截断。
- 面板或 CLI 无报错，但本次回合提前结束。

## 已定位原因（本机实测）
日志（`C:\Users\离众\.local\share\opencode\log\opencode.log`）里出现：

| 错误 | 含义 |
| :--- | :--- |
| `read ECONNRESET` | 连接被对端重置（流中断） |
| `Connect Timeout Error (…:443, 10000ms)` | 连接口超时 |
| `self signed certificate; try --use-system-ca` | TLS 证书被中间人替换（代理 MITM） |
| `Aborted` | 流被中断（用户/系统中止） |

这些错误分布在多天、且与**代理软件（FlClash，默认口 127.0.0.1:7890）**的开关状态相关：
- 走代理节点时长连接容易被重置/超时 → `ECONNRESET` / `Timeout`
- 代理做 TLS 中间人时 Node 不信任其证书 → `self signed certificate`

直连时完全正常：`tools/check_minimax.py` 实测 8/8 成功，延迟 80–129 ms，证书为可信的
`WoTrus DV Server CA`。

## 一键自检
```powershell
.\.venv\Scripts\python.exe tools\check_minimax.py 8
```
- 全部 `ok` → 网络正常，断流多半是代理或偶发；
- `cert-error` → 代理在做中间人 → 让 Node 信任系统 CA，或对该域名直连；
- `reset` / `timeout` → 代理节点对长连接不稳 → 改直连或换节点。

## 解决方案
1. **对该域名直连**（推荐）。在 FlClash 配置里加规则：
   ```yaml
   rules:
     - DOMAIN-SUFFIX,minimaxi.com,DIRECT
     - DOMAIN-SUFFIX,xaminim.com,DIRECT
   ```
   或直接关闭 TUN / 系统代理。

2. **环境变量**（部分依赖会读）：
   ```powershell
   [Environment]::SetEnvironmentVariable(
     "NO_PROXY", "127.0.0.1,localhost,::1,api.minimaxi.com,minimaxi.com,xaminim.com", "User")
   ```

3. **必须走代理时**：
   - 换一个对 SSE 长连接友好的节点；
   - 把代理的 MITM 根证书导入「受信任的根证书颁发机构」，或让 opencode 桌面版使用系统 CA。

4. **复发时取证据**：把断流发生的时间点告知，从日志捞对应 `run=` 的完整 stack（含 HTTP 状态/错误码）。

## 备注
- 其它 provider 也曾出现 stream error（`learnings_campus`、`deepseek`、`baiying`），
  说明是本机到国内大模型的**整体网络/代理环境**问题，minimax 只是暴露得更明显。
- 日志路径：`C:\Users\离众\.local\share\opencode\log\opencode.log`（按 `providerID=`、`stream error`
  关键词过滤即可）。
