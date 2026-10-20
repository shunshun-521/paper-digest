# 论文日报部署说明

这份说明只使用浏览器。代码由 GitHub Actions 每天运行，你不需要在自己的电脑上安装 Python。

推送内容是 3 到 5 篇中文新闻式论文简报，每篇尽量带一张方法图。主渠道是 HTML 邮件（图片嵌在邮件里），网页归档在 Cloudflare Pages，微信只发标题列表。

## 你需要准备的账号

| 用途 | 去哪里 | 得到什么 |
|---|---|---|
| 代码与定时任务 | GitHub | 仓库，以及下面这些 Secrets |
| 个性化论文流 | [alphaXiv](https://www.alphaxiv.org) → Settings → API Keys | `ALPHAXIV_API_KEY`。没有它时自动改用 Hugging Face 和 arXiv |
| 写稿 | [DeepSeek 开放平台](https://platform.deepseek.com) → API keys | `DEEPSEEK_API_KEY` |
| 发信 | QQ 邮箱或 163 邮箱的 SMTP 授权码 | `SMTP_HOST`、`SMTP_PORT`、`SMTP_USER`、`SMTP_PASSWORD`、`MAIL_TO` |
| 微信提醒 | [Server酱](https://sct.ftqq.com) 或 [PushPlus](https://www.pushplus.plus) | `SERVERCHAN_SENDKEY` 或 `PUSHPLUS_TOKEN` |
| 网页 | Cloudflare | `CLOUDFLARE_API_TOKEN`、`CLOUDFLARE_ACCOUNT_ID`、`CF_PAGES_PROJECT` |

模型名不写死。默认在 `config/settings.yaml` 的 `llm.model`，当前是 `deepseek-flash`。如果接口报模型不存在，在 GitHub 网页上改成控制台里实际可用的名字，例如 `deepseek-chat`。

## 1. 把仓库放到 GitHub

把本目录推到一个你自己的 GitHub 仓库（私有即可）。

## 密钥放哪里？

**只放在 GitHub Secrets，不要写进代码、不要发到聊天、不要放进 `config/*.yaml`。**

路径：

1. 打开你的 GitHub 仓库页面  
2. **Settings**（仓库设置，不是账号设置）  
3. 左侧 **Secrets and variables → Actions**  
4. **New repository secret**  
5. Name 填下表里的英文名，Value 填密钥本身

本机调试若要用真实密钥，可以另建 `.env`（已在 `.gitignore` 里），但正式推送以 GitHub Secrets 为准。

逐个新建，名字必须完全一致。

### alphaXiv

1. 打开 alphaXiv，登录。
2. 进入 Settings → API Keys，创建一把 key。
3. Secret 名：`ALPHAXIV_API_KEY`。

### DeepSeek

1. 打开 [platform.deepseek.com](https://platform.deepseek.com)，创建 API key。
2. Secret 名：`DEEPSEEK_API_KEY`。
3. 在同一页确认模型 ID，必要时改仓库里的 `config/settings.yaml`。

### QQ 邮箱

1. 登录 mail.qq.com → 设置 → 账号 → 开启 SMTP，按页面生成授权码（不是邮箱登录密码）。
2. 填这些 Secret：
   - `SMTP_HOST` = `smtp.qq.com`
   - `SMTP_PORT` = `465`
   - `SMTP_USER` = 你的完整 QQ 邮箱
   - `SMTP_PASSWORD` = 授权码
   - `MAIL_TO` = 收件地址，多个用英文逗号分隔

### 163 邮箱

1. mail.163.com → 设置 → POP3/SMTP/IMAP → 开启 SMTP，获取授权码。
2. `SMTP_HOST` = `smtp.163.com`，`SMTP_PORT` = `465`，其余同上。

### Server酱（默认）

1. 打开 [sct.ftqq.com](https://sct.ftqq.com)，用微信登录，复制 SendKey。
2. Secret 名：`SERVERCHAN_SENDKEY`。
3. `config/settings.yaml` 里 `notify.wechat_provider` 保持 `serverchan`。

### PushPlus

1. 打开 [pushplus.plus](https://www.pushplus.plus)，复制 token。
2. Secret 名：`PUSHPLUS_TOKEN`。
3. 把 `notify.wechat_provider` 改成 `pushplus`。

### Cloudflare（按这个做，忽略其它选项）

Cloudflare 控制台选项很多。本项目**只需要 Pages 静态站点 + 一把 API Token**，不要去建 Workers、不要绑域名、不要选 Git 连接。

#### A. 记下 Account ID

1. 打开 [dash.cloudflare.com](https://dash.cloudflare.com) 并登录。
2. 左侧点 **Workers 和 Pages**（英文界面是 Workers & Pages）。
3. 右侧概览里有一串 **Account ID**，复制。  
   Secret 名：`CLOUDFLARE_ACCOUNT_ID`。

#### B. 创建一个空的 Pages 项目

1. 仍在 **Workers 和 Pages**。
2. 点 **创建应用** / **Create**。
3. 选 **Pages**。
4. 你会看到两种接入方式：
   - **连接 Git** —— **不要选**
   - **直接上传** / **Upload assets** / **Direct Upload** —— **选这个**
5. 项目名填例如 `paper-digest`（小写、可带连字符）。
6. 如果页面要求先上传一个文件才能创建：随便建个本地 `index.html` 拖进去一次即可；之后由 GitHub Actions 覆盖。
7. 创建成功后，记下项目名。  
   Secret 名：`CF_PAGES_PROJECT`，值就是这个名字（例如 `paper-digest`）。

暂时不用填自定义域名，也不用改构建设置。Actions 会直接把仓库里的 `site/` 目录推上去。

#### C. 创建 API Token（最容易点错的地方）

1. 右上角头像 → **我的个人资料** / **My Profile**。
2. 左侧 **API 令牌** / **API Tokens** → **创建令牌** / **Create Token**。
3. 不要选「Global API Key」。用下面两种之一：

**方式一（推荐，最快）**

- 找模板 **Edit Cloudflare Workers** → **使用模板**。
- Account Resources：选你的账号。
- Zone Resources：若必填，选 **All zones** 即可（本项目其实不用域名）。
- 继续 → 创建 → **立刻复制 token**（只显示一次）。

**方式二（权限更小）**

- **Create Custom Token**。
- Permissions 只加这一条：  
  **Account** → **Cloudflare Pages** → **Edit**
- Account Resources：选你的账号。
- 创建并复制。

Secret 名：`CLOUDFLARE_API_TOKEN`。

#### D. 填回 GitHub，再改网址

1. 把上面三个值加到 GitHub Secrets。
2. 在 Actions 里手动跑一次 **Daily Paper Digest**（`dry_run` 关掉）。
3. 打开 Cloudflare Pages 项目，看 **Deployments**，点最新一次，复制类似  
   `https://paper-digest.pages.dev` 的地址。
4. 回到 GitHub，编辑仓库里的 `config/settings.yaml`，把  
   `deploy.site_base_url` 填成这个地址（不要末尾斜杠也行）。  
   之后邮件和微信里的「网页版」链接才会正确。

没有这三个 Secret 时，Actions 会跳过部署，邮件和微信仍然发送。

## 2. 手动跑一次

1. 打开仓库的 **Actions**。
2. 左侧选 **Daily Paper Digest**。
3. 右侧 **Run workflow**。`dry_run` 留空（false）才会真的发信。
4. 点进这次运行，展开 **Run digest** 看日志。在日志搜索框输入 `今日数据源状态` 或 `exit`。
5. 成功后：微信是标题 + 论文链接提醒；完整图文在 Cloudflare Pages 网页。邮件需先配置 SMTP 并把 `notify.email` 设为 `true`。

定时规则已经写在工作流里：北京时间周一到周五 12:30（UTC 04:30）。

## 3. 改兴趣主题

在 GitHub 打开 `config/topics.yaml`，点铅笔图标直接编辑。

- 仓库里已配置 11 个主题；网页上都能勾选。
- 当前默认（邮件会筛这些）：**模型可解释性**、**AI 智能体**。
- 想某天也看别的主题：把对应项的 `default` 改成 `true`，或只在网页复选框里临时勾选。
- `description` 用自然语言写兴趣，打分靠这段描述。

篇数、模型、是否发邮件/微信，都在 `config/settings.yaml`。

## 4. 常见问题

**没收到邮件。** 先看垃圾箱。QQ/163 必须填授权码，不能填登录密码。Actions 日志里如果写 `email skipped` 或 `email send failed`，对照 Secret 名字和端口：465 走 SSL，587 走 STARTTLS。

**某一天篇数很少。** 已经推送过的论文记在 `data/seen.json`，不会再出现。上游 feed 当天也可能没有新论文。状态栏出现 ⚠ 表示某个源降级了，邮件仍应发出。

**模型名失效。** 只改 `config/settings.yaml` 的 `llm.model`，不用改代码。`llm.base_url` 也可以换成别的 OpenAI 兼容接口。

**alphaXiv key 失效。** 流水线会改用 Hugging Face Daily Papers，仍不行再用 arXiv 分类列表。状态栏里 For You / Hot 会标 ⚠。只有所有来源都空、最终 0 篇时，任务才会失败，并尝试发一条微信：「今日推送失败，请查看 Actions 日志」。

**想先看版式、不发信。** 在 Actions 里手动运行，把 `dry_run` 设为 true。这次使用仓库里的样例数据，只在日志对应的产物里生成 HTML，不改 `data/`。

## 5. 本地预览（可选）

部署本身不需要本地环境。如果你想在浏览器里先看样例邮件和网页：

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m digest run --dry-run
```

然后打开 `out/email.html` 和 `out/2026-10-19/index.html`（日期以参数为准）。这条命令不访问网络，也不发送。
