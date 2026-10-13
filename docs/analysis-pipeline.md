# 数据 → AI 分析 完整通道（The Fittest）

从「保存数据」到「提交数据」再到「AI 分析」的端到端流程。

## 0. 统一存档：一次运行一个文件

**唯一事实来源是 `archive/runs/<名称>_s<seed>_g<代数>_<时间戳>.tev.json`。**

这个文件同时满足两个读者：

| 读者 | 读哪部分 |
| :--- | :--- |
| AI / 分析者 | `summary` + `rules` + `analysis`——参数、编码词典、逐代种群与适应度矩阵、事件时间线、谱系、衍生指标，全部预派生，无需重算 |
| 复现 / 续演 | `reproduce`（seed + 初始条件 + 代数 + 手动注入）用于**重跑**；`state`（含 `rng_state`）用于**精确还原并继续** |

Markdown 与 CSV 是从该文件**确定性渲染**的视图，**不落盘**：

```python
import evolution_archive as ea
doc = ea.load_document(path)          # 读统一存档
ea.document_to_markdown(doc)          # 渲染 Markdown 视图
ea.document_to_csv(doc)               # 渲染长表 CSV 视图
```

所以不存在"JSON 更新了但 Markdown 没更新"这类脱节问题。

### 两个版本号

| 字段 | 含义 | 何时变 |
| :--- | :--- | :--- |
| `schema_version` | 文件结构版本，用于决定怎么读 | JSON 布局变化时（`RUN_SCHEMA_VERSION`） |
| `engine_version` | 产生该轨迹的引擎版本 | 任何会改变演化结果的地方：规则值、步骤顺序、变异权重、席位记账修复（`ENGINE_VERSION`） |

**`engine_version` 是跨版本维护的关键**：同一个 seed 只在同一个引擎版本内可复现。
`trust_evolution_simulation.py` 顶部的 `ENGINE_VERSION = "1.0.0"` 是 2026-09-30
席位泄漏修复之后的版本。`list_runs()` 会给旧引擎存档打 `stale_engine` 标记，
面板也会显示"⚠旧引擎"并警告；`reproduce_run()` 遇到版本不一致会直接拒绝重跑，
提示改用 `load_run()` 读取存档状态。

> 跨版本维护动作：改动演化逻辑时，**先把 `ENGINE_VERSION` 往上抬一位**，
> 再重跑需要对比的 seed。旧存档不会失效（仍可读取/续演），只是不能再声称"可重跑复现"。

## 1. 数据保存

**方式 A（推荐，面板，可续演）**
面板推演到想要的轮次后，两处入口都写入同一个统一存档：

- 侧栏「统一存档 → 保存当前模拟」：填名称与备注后保存；
- 主区「统一存档（AI 可直接读取 / 可复现）→ 💾 保存统一存档到 archive/runs/」。

之后在侧栏「统一存档 / 加载」中按名称选择并**加载**（继续推演或回溯），
支持**重命名/删除**，并显示每个存档的引擎版本、注入次数与陈旧标记。
> 加载是"图形界面 + 名称"呈现，不使用系统文件管理器。

**方式 B（命令行）**
```bash
python trust_evolution_simulation.py --seed 42 --generations 80
```
除 PNG 外，同时写出统一存档 `archive/runs/cli_seed_42_s42_g80_<时间戳>.tev.json`
与旧格式 `results/trust_evolution/trust_evolution_seed_42.json`（保留给旧工具）。

**方式 C（分享给他人复现）**
面板「分享 / 复现 → 下载分享摘要」。这是一个极小的 `trust-evolution-share-summary`，
只含 seed / 初始条件 / 代数 + 两个版本号。接收方上传即可重跑。
若版本不一致会明确报错，而不是悄悄给出不同结果。

## 2. 提交数据 → AI 分析

**方式 A（推荐）：交给 opencode 的 skill 直接分析**

对 opencode 说"**开始分析模拟**"或"**分析模拟**"。skill 会自动列出
`archive/runs/` 下所有统一存档的摘要（**名称 / 存档时间 / 种子 / 代数 / 存活物种 /
格式版本 / 引擎版本 / 注入次数**），由你选择**一个或多个**进行分析，
无需给出文件路径、无需文件管理器。

也可以显式指定：

```text
用 trust-evolution-analysis 分析 archive/runs/baseline_s42_g200_20260930-153000.tev.json
```

skill 会做**版本校验**：存档的 `engine_version` 与当前引擎不一致时，会在报告开头显著标注，
并禁止把该存档数据与新版引擎结论混在一起比较。

**方式 B（可选，自动化调 API）**

`tools/submit_analysis.py` 把存档直接发给 OpenAI 兼容接口（默认 DeepSeek），回复存为 Markdown。

```bash
$env:DEEPSEEK_API_KEY="sk-..."   # 密钥只放环境变量，不要入库
.\.venv\Scripts\python.exe tools\submit_analysis.py archive\runs\<name>.tev.json --output analysis.md
.\.venv\Scripts\python.exe tools\submit_analysis.py <file> --dry-run
```

## 3. 结果复用

- Markdown 视图：可直接继续在 opencode 中追问（如"第 184 代优势更替的原因是什么？"）；
- 统一存档本身：供程序化验证、重新渲染视图、或加载后续演；
- 报告建议存到 `reports/`。

## 4. 旧档案

统一之前的四条写出路径（`exports/`、`results/trust_evolution/`、`saved_simulations/`、分享摘要）
已移入 `archive/legacy/<来源>/`，**不删除**，并由 `archive/legacy/MANIFEST.md` 记录
每個文件的位置、时间、大小与关键字段。

这些旧档有两个共同缺陷，引用前必须知道：

1. **没有版本标记**——无法判断是哪个引擎跑的；
2. **可能带 2026-09-30 之前已修复的席位泄漏**——亚种变异回已存在编码并独立时会产生
   同编码的重复物种对象，而按编码聚合的配额表把二者合并成一个键，
   两个对象因此拿到同一份席位，总席位逐代累积（实测可达容量的 171%）。
   由于报告的 `population_matrix` 同样按编码聚合，重复项被静默覆盖，
   **旧档记录的规模合计会小于实际规模，物种份额被高估**。

## 5. 注意事项

- **可复现性**：同 seed + 同 `engine_version` + 同一注入序列 → 完全一致的轨迹
  （含 `summary.injections` 记录的手动注入）。跨 seed 结论应做多次对照并注明。
- **注入会影响结论**：手动注入的策略不是演化产物。分析时看 `summary.injections`，
  >0 就在报告里明确标注，不要把它当作"演化胜出"。
- **密钥安全**：API 密钥只通过环境变量注入，绝不写入代码或提交到仓库。
- **数据规模**：统一存档含每代对局矩阵，数百代约 1–3 MB。
  只需趋势分析时可用 `include_matchups=False` 省略对局矩阵以显著减小体积。
