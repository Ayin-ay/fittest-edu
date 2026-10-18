# 上线分享指南（The Fittest）

把本地面板部署成可分享给朋友的 Streamlit 网站：**不公开代码（私有仓库）+ 不买域名 + 应用内密码门**。

## 1. 本地准备

依赖已列在 `requirements.txt`：

```bash
pip install -r requirements.txt
```

本地启动（不带密码门）：

```bash
streamlit run dashboard/app.py
```

或双击 `run_dashboard.bat`。

## 2. 密码门

密码门逻辑在 `dashboard/app.py` 的 `check_password()`：

- **未配置密码** → 直接进入（本地开发默认如此）。
- **配置了密码** → 需输入正确密码才能使用。

密码来源（优先级）：`st.secrets["APP_PASSWORD"]` → 环境变量 `APP_PASSWORD`。

本地文件 `.streamlit/secrets.toml` 已被 `.gitignore` 忽略，默认把 `APP_PASSWORD` 注释掉（不启用密码门）。
想本地测试密码门，取消注释并改成你的密码：

```toml
APP_PASSWORD = "你的密码"
```

> 安全约定：**代码里不写死密码**；密码只放在 `secrets.toml`（本地）或平台 Secrets（线上）。

## 3. 分享、复现与学生进度

- **统一存档就是分享文件**：面板「统一存档 → 💾 保存统一存档」写入
  `archive/runs/<名称>_s<seed>_g<代数>_<时间戳>.tev.json`，把它发给对方即可。
- 对方在侧栏「载入 / 复现」上传该文件，点「用该文件复现」即可还原**完全相同**的模拟
  （同 `engine_version` + 同 seed + 同一注入序列）。
- 兼容旧版：面板旧存档 JSON 与分享摘要仍可上传读取；旧版分享摘要会校验引擎版本，
  不一致时明确报错而不是悄悄给出不同结果。
- 线上部署注意：`archive/runs/` 在 `.gitignore` 中，每个用户的运行只存在本地磁盘；
  面板的存档/载入是本机行为，不跨用户共享。

### 3.1 学生进度：SQLite 名单库 + 加入码

游戏模式的学生进度存在 `archive/roster.sqlite3`（`dashboard/store.py`，已 gitignore）。
一个学生一行，主键是他自己的**加入码**——8 位、不含 I/O/0/1，便于手抄。

**库里存的都是什么事前就定下来的东西**：设置（对手数、每局轮数、种子）、玩家自己的
决策串、可选的逐轮猜测串、是否过完新手教程、班级码、挑战码，以及一个 `demo` 标记。
对手编码、双方比分、逐轮记录、九项测量、得分矩阵**全部不存**，
每次载入时由引擎重算。这条设计依赖的是引擎的确定性——`tools/store_roundtrip.py`
就是验这件事的，跑一遍即可确认"重放出来的是同一局"：

```bash
../.venv/Scripts/python.exe -X utf8 tools/store_roundtrip.py
```

它用临时库，不会碰真实名单。

三条恢复路径，覆盖面依次变宽：

| 场景 | 靠什么 | 说明 |
| :--- | :--- | :--- |
| 刷新 / 新标签页 / 手机锁屏 | 地址栏 `?g=` + `?gc=` | 原有机制，一直保留 |
| 下周换设备回来 | 加入码 | 在游戏模式「接着上次打」输入即可 |
| 重新部署把文件清空了 | 教师导出的 CSV | 见下 |

**隐私底线**：整张表里没有任何能指认到人的列——没有姓名、邮箱、账号、IP。加入码是
随机串，班级码是老师自己起的标签（可留空），都不是学生名册。引入持久化时必须继续
守住这条线：要收集可识别信息，先拿到书面授权。

**名单屏另外设了一道门。** 访问密码是全班共用的，知道密码就能进来，所以首页
「教师端：整批名单导出与恢复」需要 `TEACHER_GATE`（Secrets 或环境变量）才会显示数据；
**没配置时整块名单不渲染**，而不是默认给大家看。没有这道门，任何一个同学都能在首页
看到所有人的加入码，再逐个输入取回别人的报告。

载入时校验 `engine_version`，不一致就明确拒绝重放。改了收益结构或策略生成规则后，
旧决策串会算出一份**看起来完全正常**的新报告——那种错误比报错难发现得多。

### 3.2 演示用模拟名单（`demo = 1`）

教师端那一屏要有东西可讲，但**没有真实班级之前不能假装有一个**。`dashboard/demo_roster.py`
用固定种子在真引擎上跑出几十份提交（两个班、四份预置挑战、几条教科书标准策略各掺不同的
临场翻转率），教师端「演示数据（模拟名单）」里两个按钮负责载入与清除；命令行等价物：

```bash
../.venv/Scripts/python.exe -X utf8 tools/seed_demo_roster.py --db "$TMP/demo.sqlite3" --dry-run
../.venv/Scripts/python.exe -X utf8 tools/seed_demo_roster.py          # 写入 archive/roster.sqlite3
../.venv/Scripts/python.exe -X utf8 tools/seed_demo_roster.py --clear  # 只删模拟行
../.venv/Scripts/python.exe -X utf8 tools/demo_roster_check.py        # 自检：可复现、可重放、标记不丢
```

三条不可让步的性质：

1. **只多一个标记，不多一列个人信息。** 模拟行走的是和真实提交完全相同的字段，
   唯一的区别是 `runs.demo`。它们同样不含姓名、学号或任何能指认到人的东西。
2. **每一处都标出来。** `demo=1` 会进导出的 CSV；看板的榜上方挂「脚本生成的模拟数据，
   不是真实课堂结果」的警告；榜里每个加入码后面直接跟「（模拟）」；逐份提交表有「来源」列；
   学生端的名次也会说明这批提交里有多少份是演示数据。截图带走任何一块，标注都还在。
3. **只作用于自己。** 载入不动 `demo=0` 的行，`--clear` 只删 `demo=1` 的行，
   两个方向都不是「清空名单」。

写这些行是真的跑出来的，所以点进任何一个模拟加入码，学生端那份报告、九项测量与六条
博弈论读数都照常成立——和真实学生走同一条代码路径。**但它们是脚本，不是课堂**：
参赛材料里不得据此写「已在班级试用」「覆盖 N 名学生」之类的说法。

**免费版文件系统是临时的**：每次重新部署 `archive/` 都会清空，名单库随之消失。因此
首页「教师端：整批名单导出与恢复」提供整表 CSV 下载（UTF-8 带 BOM，Excel 直接打开
不乱码）与回填上传。做法是**每次课后当场导出**，导入后加入码不变，学生仍凭原码回来。
若要长期在线保存名单，需要换持久卷 / 外部数据库，那是部署层的事，本仓库不做假设。

同一个页面还有 `?g=` 那条链接作为对局内的即时兜底：万一名单库写不进去，对局照常
能打，页面顶部会说明这次没能存档。

### 3.3 布置：一道题发给指定班级，刷新收作业

「下发挑战」和「谁该交这份作业」是两张表。`store.py` 里的 `challenges` 记的是题面本身
（对手集合、轮数、种子），**`assignments` 记的是「这道题发给这个班」**，主键
`(challenge_id, class_code)`。同一道题可以布置给好几个班，而它们始终共用同一套对手，
所以各班名次可比——这正是「按班筛选、不按班复制题面」的原因。

老师端首页那一块的用法是一条直线：

1. 选题面 + 填班级码 → 「布置这个班」。这一步**只写布置表，不写任何提交**。
2. 「刷新名单（收作业）」重读名单库：真实提交进来多少算多少。
3. 勾选「演示」时，同一次刷新还会让脚本生成的虚拟学生**交上来一批**（每班一批 7 份、
   最多 6 批、按名单顺序推进），于是「布置 → 有人交 → 榜单变长」这一条能在
   成果展示里当场走完，而不是靠事先塞好的截图。

布置表上每一行显示「已交 x / 22 · 打完 y · 第 N 批」，`demo_round` 就是推进到第几批的
游标，重复布置同一（题面, 班）只改备注、不会把游标退回 0。收满以后按钮再点也不产出
新提交，回显会写「这个班的名单已经交完」。

第三份 CSV：**⬇ 导出布置表 CSV / 恢复这批布置**（`fittest-assignments.csv`）。免费版
重新部署把 `archive/` 清空后，名单表和题面表都能回填，布置表也在一起——否则老师手上
有 80 份提交却不知道哪道题发给过哪个班。导入时批次号原样恢复，接着上一批往下收，
不会把已经交过的那批重收一遍。

`tools/demo_roster_check.py` 验的就是这一节的性质：布置不写提交、游标不被污染、
同一个（挑战, 班, 批次）在两份库里跑出同一批人和同一串决策、批次之间不重交、一批一批
正好交齐一个班、导出的布置表能原样恢复。

```bash
../.venv/Scripts/python.exe -X utf8 tools/demo_roster_check.py
```

### 3.4 老师怎么看单个学生的细分轮次

名单屏底部的「逐份提交与逐轮详情」把每一行只有码、题面参数和决策串的原样列出来；
点某一行的「看逐轮详情」就地展开那一份：逐局逐轮的记录表（含「另一手本可得分」列）、
六条博弈论读数，以及开了逐轮猜测时那份提交自己的命中率与参照线。

一次只展开一份，靠的是按钮加 `st.session_state`，不是带状态的 expander——几十个嵌套
expander 的展开状态在重跑时会丢，老师会遇到「标题开了、里面空白」的那一种。只算被点开
的那一条也是必要的：几十份一起重放会让这一屏每点一下卡一次。

这一份详情与学生自己那份报告、与榜单上的分数走的是**同一条重放路径**（`_replay_matches`），
所以三边对不上是结构上不可能的事，不是靠约定同步。库里没有存任何分数。


## 4. 部署到 Streamlit Cloud（免费、无需域名）

### 4.1 上传 GitHub 私有仓库

> 本节是**历史记录**，仓库早已建好：远端为 `https://github.com/Ayin-ay/fittest-edu`，
> 分支 `main`，且**目前是公开仓库**（匿名可 clone/读取 raw 文件）。当年设想的
> 「转私有」并没有执行，下文 4.4 的图标仓库理由也已据此改写。要新建部署，直接看 4.2。

```bash
cd "C:/Users/离众/Desktop/Trust Evolution"
git init
git add .
git commit -m "The Fittest dashboard"
git branch -M main
git remote add origin https://github.com/<你的用户名>/trust-evolution.git
git push -u origin main
```

推完后在 GitHub 仓库 → Settings → 最下方 Danger Zone → Change visibility → **Make private**。

> `.gitignore` 已排除 `.streamlit/secrets.toml`、`saved_simulations/`、`saved_strategies.json`、
> `results/trust_evolution/*.json|*.png`，不会把密码与本地数据传上去。

### 4.2 部署

1. 打开 <https://share.streamlit.io>，用 GitHub 登录并授权访问仓库。
2. New app → 选择 `Ayin-ay/fittest-edu` 仓库与 `main` 分支。
   （首次部署会跳一次 GitHub 授权页，Authorise streamlit 里勾选该仓库。）
3. **Main file path**：`dashboard/app.py`
4. Advanced settings → **Sharing 选 "This app is public"**（不要选 Only specific people，
   这样朋友靠密码即可访问，无需邮箱白名单）。
5. **Secrets** 里填：

   ```toml
   APP_PASSWORD = "你的访问密码"
   ```

   如果要让游戏模式的「大模型深度解读」可用，再加下面三项。
   **所有访问者共用这一份密钥，页面上不出现任何密钥输入框**：

   ```toml
   ANALYSIS_API_KEY = "sk-..."
   ANALYSIS_BASE_URL = "https://api.deepseek.com"
   ANALYSIS_MODEL = "deepseek-chat"
   ```

   `base_url` 与 `model` 必须与你的账户一致；只填密钥时回退到 DeepSeek 官方
   地址与 `deepseek-chat`。若该接口需要代理才能连通，再加一项
   `ANALYSIS_PROXY = "http://127.0.0.1:7890"`（使用者无需感知）。
   不配置这三项时，该功能显示为「尚未开通」，其余功能不受影响。

   要把学生名单收起来看、或导出 CSV 交作业分析，再加一项教师码（详见
   [3.1](#31-学生进度sqlite-名单库--加入码)）：

   ```toml
   TEACHER_GATE = "只有老师知道的码"
   ```

   > 密钥只存在于 Cloud Secrets 与服务器环境变量中，不会进版本库，
   > 也不会下发到浏览器。

6. Deploy，等待构建完成，得到形如 `https://<app>.streamlit.app` 的网址。
   本仓库约定的子域是 **`fittest-edu`**，即 `https://fittest-edu.streamlit.app`
   ——与 `ai_analysis.DEFAULT_APP_URL` 一致。**该应用尚未创建**，
   建的时候就把子域填成这个；若同名已被占用，改掉子域后必须同步这两处。

   > 子域名在 Cloud 后台应用 Settings 里单独修改，**与 GitHub 仓库名无关**；
   > 改子域名会让旧网址失效，请尽早确定并只对外发布最终地址。
   >
   > 另一个地址 `the-fittest.streamlit.app` 属于**另一个项目**，与本仓库无关，
   > 不要写进任何对外材料。

### 4.3 分享文案模板

```
The Fittest 策略进化模拟
网址：https://fittest-edu.streamlit.app
密码：<你的访问密码>
首次打开约需 30 秒唤醒，之后流畅使用。
```

### 4.4 应用图标

图标另托管在公开仓库 `Ayin-ay/the-fittest-assets`：

```
https://raw.githubusercontent.com/Ayin-ay/the-fittest-assets/main/icon.png
```

为什么另起一个仓库：主仓库目前是**公开**的，直链可用；但把品牌资产单独放一个
仓库，主仓库将来转私有也不会让图标链接忽然失效。仍需注意：

- GitHub 的 `.../blob/...` 链接返回的是**网页**（`text/html`），不是图片，
  要直链必须用 `raw.githubusercontent.com`；
- Streamlit Cloud **实测不提供**文档所写的静态文件服务——`app/static/*` 会命中
  边缘节点的通用外壳（`text/html`）。同一路径在本地 `streamlit run` 下正常
  （见 `dashboard/static/` 与 `config.toml` 的 `enableStaticServing`），但线上不可依赖。
  首页插画因此在 `theme.hero_art()` 里读文件内联，而不是 `<img src="app/static/…">`。

因此任何需要「图标 URL」的第三方表单，都填上面那个公开仓库的直链。

### 4.5 线上状态怎么确认，以及怎么让合作者进来

**不要用 HTTP 探测来判断某个 `*.streamlit.app` 是否存在。** 实测一个必然不存在
的子域（`zz-definitely-not-a-real-app-9x7q`）与真实应用返回完全相同的响应：

- `GET /` → 303，跳 `https://share.streamlit.io/-/auth/app?redirect_uri=…`；
- `GET /healthz` → 200。

带浏览器 User-Agent 结果也一样。这两条只是 Cloud 边缘节点的通用行为，既不证明
应用存在，也不证明它被设成了「仅成员可见」。**唯一可靠的确认方式是登录 Cloud 后台
看应用列表。** 截至本次记录，本仓库在 Cloud 上还没有对应应用，
`https://fittest-edu.streamlit.app` 只是代码与本文档约定的目标地址。

应用建好之后，让合作者进来有两条路：

- **加成员**：Cloud 后台 → 工作区 → Settings → Members → 邀请对方的 GitHub 账号。
  网址保持仅成员可见。注意同一个工作区里的应用会一起可见——若不希望合作者看到
  `the-fittest` 那个项目，两个应用要分属不同工作区。
- **改公开**：该应用 → Settings → Who can access this app → Public。任何拿到
  网址的人都可直接进入，无需登录。

另外，若线上 Secrets 设了 `APP_PASSWORD`，进入页面后还要再输一次访问密码，
需一并发给对方。

## 5. 常见问题

| 问题 | 处理 |
| :--- | :--- |
| 打开是空白/一直转圈 | Streamlit Cloud 冷启动，等 30–60 秒 |
| 提示未配置密码 | 线上在 Secrets 填 `APP_PASSWORD`；本地可留空（不启用） |
| 部署报缺依赖 | 确认 `requirements.txt` 在仓库根目录 |
| 页面闪烁 | 已用 Plotly（非 Matplotlib）渲染交互图；静态 PNG 仅在命令行路径使用 |
| 想让朋友自己复现 | 发给他你的「分享摘要 JSON」，让他在侧栏上传 |
| 表单要填「图标 URL」 | 用公开仓库直链，见 [4.4](#44-应用图标)；不要用主仓库的 blob / raw 链接 |
| 点了「刷新名单（收作业）」没有新提交 | 回显会说清楚是哪种：这个班的虚拟名单已经交完（第 6 批之后不再有），还是这一条布置没勾「演示」——真实班级本来就只能等学生自己交 |
| 重新部署后布置不见了 | 导入课后导出的**布置表 CSV**；批次号会原样恢复，接着上一批往下收 |

## 6. 相关文件

- 面板入口：`dashboard/app.py`（含密码门与分享/复现）
- 存档/复现逻辑：`dashboard/saveload.py`
- 学生名单库（SQLite + 加入码）：`dashboard/store.py`，回环自检 `tools/store_roundtrip.py`
- 布置表（`assignments`：一道题 → 哪些班、收第几批）：同上 `store.py` 的
  `assign_challenge` / `advance_assignment` / `export_assignments_csv`
- 演示用虚拟名单与按批上交：`dashboard/demo_roster.py`，自检 `tools/demo_roster_check.py`
- 老师看单个学生的逐轮详情：`dashboard/app.py` 的 `_replay_matches` / `_render_run_detail`
  （与学生报告、榜单同一条重放路径）
- 导出（JSON/Markdown/CSV）：`dashboard/export.py`
- 依赖：`requirements.txt`
- 主题/设置：`.streamlit/config.toml`；密钥模板：`.streamlit/secrets.toml.example`
- 应用图标：`docs/brand/`（源文件）、`dashboard/static/`（本地静态服务用）、公开仓库 `Ayin-ay/the-fittest-assets`
