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

## 3. 分享与复现

- **统一存档就是分享文件**：面板「统一存档 → 💾 保存统一存档」写入
  `archive/runs/<名称>_s<seed>_g<代数>_<时间戳>.tev.json`，把它发给对方即可。
- 对方在侧栏「载入 / 复现」上传该文件，点「用该文件复现」即可还原**完全相同**的模拟
  （同 `engine_version` + 同 seed + 同一注入序列）。
- 兼容旧版：面板旧存档 JSON 与分享摘要仍可上传读取；旧版分享摘要会校验引擎版本，
  不一致时明确报错而不是悄悄给出不同结果。
- 线上部署注意：`archive/runs/` 在 `.gitignore` 中，每个用户的运行只存在本地磁盘；
  面板的存档/载入是本机行为，不跨用户共享。

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

   > 密钥只存在于 Cloud Secrets 与服务器环境变量中，不会进版本库，
   > 也不会下发到浏览器。

6. Deploy，等待构建完成，得到形如 `https://<app>.streamlit.app` 的网址。
   本仓库约定的子域是 **`fittest-edu`**，即 `https://fittest-edu.streamlit.app`
   ——与 `ai_analysis.DEFAULT_APP_URL`、`share_card.QR_URL` 一致。**该应用尚未创建**，
   建的时候就把子域填成这个；若同名已被占用，改掉子域后必须同步这三处。

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

## 6. 相关文件

- 面板入口：`dashboard/app.py`（含密码门与分享/复现）
- 存档/复现逻辑：`dashboard/saveload.py`
- 导出（JSON/Markdown/CSV）：`dashboard/export.py`
- 依赖：`requirements.txt`
- 主题/设置：`.streamlit/config.toml`；密钥模板：`.streamlit/secrets.toml.example`
- 应用图标：`docs/brand/`（源文件）、`dashboard/static/`（本地静态服务用）、公开仓库 `Ayin-ay/the-fittest-assets`
