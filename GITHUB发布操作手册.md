# GitHub 发布操作手册 —— 把「香港留学指南」做成 HowToLiveBetter 那样的工程

> 配套套件：本目录就是一个**可以直接推上 GitHub 的仓库骨架**（`.github/`、`book/`、`docs/`、`README.md`、`CLAUDE.md` 都已备好）。
> 按「第 1 步 → 第 8 步」顺序做，全程约半天（其中大半是等 AI 写内容，不是等 GitHub）。

---

## 第 0 步：先想清楚 GitHub 的角色（最重要的一步）

HowToLiveBetter 靠 GitHub 拿到 3.4 万星，有个前提我们不具备：**它的读者本来就住在 GitHub 上**（程序员、效率工具爱好者，天天刷 star 榜）。你的读者是考虑去香港读书的学生和家长——**他们不逛 GitHub，而且内地上 GitHub 时快时慢、下载 Release 经常失败**。

所以定位必须摆正：

| GitHub 对它 | GitHub 对你 |
| --- | --- |
| 发布渠道 + 流量来源（读者就在这） | **内容工厂 + 发布流水线**（工程层） |
| README 就是落地页 | README 只是「总目录备份」，落地页在别处 |
| star 是增长引擎 | star 只是存档凭证，流量走平台号 + 自建站 |

**但 GitHub 对你仍然不可替代**，因为它免费给你四样东西：

1. **版本管理**：每条内容每次修改都有记录——「这条 10 月 5 日改过，因为官方文件更新了」本身就是信任证据；
2. **CI 自动出三种格式**：推一次代码，EPUB / PDF / 单文件 HTML 自动生成、自动挂到**永久不变的下载链接**上；
3. **issue 质检**：读者挑错走 issue，处理记录公开可查——把读者变成免费校对员；
4. **单文件 HTML 是微信传播神器**：从 Release 下载下来，直接发微信群、发朋友，不需要对方访问任何网站，**绕开了内地访问 GitHub 的全部问题**。

一句话：**GitHub 管生产，微信和平台号管分发。**

---

## 第 1 步：准备工作（10 分钟）

- 注册 GitHub 账号（如果还没有）。**用户名建议直接用你的对外 IP**（比如 `donghkstudy`），因为仓库 URL、署名都会带它；
- 本机装 git（WorkBuddy 电脑已具备）；
- 可选：装 GitHub 官方命令行 `gh`，能省很多点击。

---

## 第 2 步：建仓库（5 分钟）

在 GitHub 网页上 New repository：

- **仓库名**：`hongkong-study-guide`（或你想用的名字，slug 要短、要英文）；
- **可见性**：Public（必须公开，这是信任链的一部分）；
- 勾选「Add a README」。

然后把本套件的内容推上去（在本目录执行）：

```bash
git init
git add -A
git commit -m "init: 仓库骨架"
git branch -M main
git remote add origin https://github.com/<你的用户名>/hongkong-study-guide.git
git push -u origin main
```

推完这个仓库就已经具备完整骨架：`book/`（正文）、`docs/核实记录/`、`.github/workflows/book.yml`（CI）、`README.md`（落地页）、`CLAUDE.md`（AI 规则）。

---

## 第 3 步：目录结构（已备好，说明用途）

```
hongkong-study-guide/
├── README.md              ← 落地页：目录 + 下载链接 + 核对日期
├── CLAUDE.md              ← 喂给 AI 的规则判例集（每次开工先读）
├── book/                  ← 正文，一条一个 md 文件，编号排序
│   ├── 001-xxx.md
│   └── 002-xxx.md
├── docs/
│   └── 核实记录/          ← 每条「这个数字出自哪份官方文件」的留痕
├── tools/                 ← 质检脚本（引用守恒、链接巡检等，后加）
└── .github/workflows/
    └── book.yml           ← CI：自动出 EPUB / PDF / 单文件 HTML
```

关键纪律（和 HowToLiveBetter 一致）：**book/ 里一条一个文件、文件名带三位编号**。插新条目时中间编号顺延，CI 和质检脚本靠编号做交叉引用校验。

---

## 第 4 步：写作流（AI 干活，规则管住它）

每条条目按设计文档 v0.2 的 **11 字段 Schema** 写。给 AI（Claude Code / WorkBuddy 都行）的开工指令固定成一句话：

> 「读 CLAUDE.md，按它的规则写 book/0XX-<slug>.md，主题是 XXX。写完自查 Schema 11 个字段是否齐全，信源是否全部来自白名单。」

`CLAUDE.md` 模板已备好，包含：11 字段 Schema、信源白名单/黑名单、证据分级 A/B/C、写法红线。**每犯一个新错就把规则追加进去（带日期和事故），这就是「判例集」的积累方式。**

---

## 第 5 步：CI 自动出三种格式（已配好，推代码即生效）

`.github/workflows/book.yml` 已经写好：**每次推代码到 main，GitHub 的服务器自动执行**：

1. 按编号合并 `book/` 全部 md；
2. 用 pandoc 生成 **EPUB + 单文件 HTML**，用 weasyprint 生成 **PDF**（含中文字体）；
3. 全部挂到名为 **`book-latest`** 的 Release 上，覆盖旧版。

最重要的特性：**Release 的下载链接永远不变**——

```
https://github.com/<你的用户名>/hongkong-study-guide/releases/download/book-latest/HKStudyGuide.html
```

这行链接可以印在任何地方（名片、视频简介、公众号菜单），仓库每天更新，链接永远指向最新版。HowToLiveBetter 的 `epub-latest` 就是这么做的。

首次生效去仓库的 **Actions 标签页**看运行状态，绿了就说明三种格式已产出。

---

## 第 6 步：README = 落地页（模板已备好）

模板已按 HowToLiveBetter 的结构写好：标题 → 一句话承诺 → 使用说明 → 目录（含核对日期）→ 下载链接 → 如何提意见。你要做的只是替换里面的占位内容。

三个不可省的元素：

- **「最后更新：2026-XX-XX」放最顶上**——活着的文档才有人信；
- **每条目录后面跟核对日期**——「001 高才通：2026-10 核对入境处原文」；
- **结尾放 issue 入口**——「发现错误？开一个 issue，我们会核对后回复」。

---

## 第 7 步：issue 治理（信任的放大器）

- 仓库 Settings → Features 勾选 Issues，配一个简单模板（哪一条 / 什么问题 / 依据是什么）；
- **答复纪律**：有理的照改并公开致谢；无理的引官方文件原文驳斥；**每条 issue 都要有结论**；
- 每处理一批 issue，往 `CLAUDE.md` 里追加对应规则（判例式积累）。

---

## 第 8 步：分发——GitHub 之外才是战场

| 渠道 | 动作 | 用 GitHub 的什么 |
| --- | --- | --- |
| **微信** | 单文件 HTML/PDF 直接发群、发好友、当「资料包」 | Release 下载链接（人工下载后转发） |
| **抖音/视频号/小红书** | 每条内容出一期视频，简介挂获取方式 | 内容源 + 「可验证」人设 |
| **知乎/公众号** | 每条内容改写成文章，文末放 issue 地址当「开放校对」的证据 | 内容复用 |
| **自建站（后期）** | CI 顺手把 HTML rsync 到你的香港服务器 | 同一份 book/ 源文件 |

**冷启动节奏（照 HowToLiveBetter 的反例调整）**：它发第 1 条就在 GitHub 有了初始曝光，你没有——所以**写到第 3 条就必须有一条视频出去了**，别等 30 条写完。

---

## 常见坑（提前说清）

1. **PDF 中文字体**：workflow 里已装 `fonts-noto-cjk`，如果生成的 PDF 字体不对，去 Actions 日志看 weasyprint 那步；
2. **Release 文件名用英文**（`HKStudyGuide.html`），中文文件名在部分下载器里会乱码；
3. **别用 GitHub Pages 当内地落地页**：`*.github.io` 在内地时通时断，只当海外镜像用；
4. **仓库就是你的公开记录**：commit 信息、issue 回复都会被看到——保持干净，别在里面写任何不想让客户看的东西；
5. **第一次跑 CI 失败很正常**：把 Actions 的报错贴给我，我来修。
