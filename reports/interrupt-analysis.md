# minimax 任务中断分析报告

## 根因
- 会话中曾发生 minimax 流错误 → opencode 触发 `AbortError` → 当前 run `f3a08948` 被终止 → 后续工具调用全部失效 → 助手输出截断/中断。
- 触发的 minimax 错误是常见的网络/连接问题：ECONNRESET、Connect Timeout、AbortError 等。
- 助手在 Bash 工具中用 `python -c "..."` 输出长文本存在被 PowerShell `write-output` 或终端缓冲截断的风险。

## 恢复路径
1. **立即恢复**：在 opencode 界面用其他可用 provider（deepseek、learnings_campus）继续同一会话。
2. **长期预防**：在 `opencode.jsonc` 中将 `model` 从 `minimax-cn-coding-plan` 切到 `deepseek`；按 `docs/minimax-troubleshooting.md` 调整代理/直连规则。
3. **助手输出优化**：将长输出写入临时文件，再用工具读取，避免控制台缓冲截断。

## 结论
本次中断的真实原因不是 minimax 模型本身的问题，而是其流式连接不稳定触发 opencode 中止 run，导致助手工具调用失去宿主。修复办法以更换 provider 与代理设置为主，与 minimax 模型本身无关。