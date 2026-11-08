# xhs-cover-aisisi

> 技能名 `xhs-tech-cover`。装进 skill 目录时，目录名要与 `SKILL.md` 里的 `name` 一致，克隆后重命名即可：`mv xhs-cover-aisisi xhs-tech-cover`。

小红书竖版 3:4（1080×1440）科技未来感封面制作技能，用于 AI Agent（Claude Code / 豆包 / 任意支持 SKILL.md 的运行时）。

**核心思路：字不让 AI 画。** AI 只出无字背景图，标题由 Python 脚本用真实中文字体叠上去——这样中文永远不会糊、不会缺笔画、不会被模型改成乱码。叠完自动出 220px 缩略图并报告对比度、字号占比、行数告警。

主视觉固定用**你自己的真人照片**做锚点，同一账号所有封面共用一张脸。

## 效果示例

下面三张是这个技能跑出来的真实成品：同一个主角，三种配色与版式。换成你自己的照片，版式、字号、留白规则一个字都不用改，只有脸变成你的。

| 暖白轻科技 · 正面操作式 | 冷曜蓝 · 正面操作式 |
|---|---|
| ![暖白轻科技](docs/preview/15-cream-light-v4.jpg) | ![冷曜蓝正面操作](docs/preview/04-cyan-action-v1.jpg) |
| 标题 136px、2 行、占宽 12.6%、对比度 8.9 | 标题 124px、占宽 11.5%、顶部 20% 干净 |

| 冷曜蓝 · 上字下人 | 渲染自动产出的缩略预检 |
|---|---|
| ![冷曜蓝上字下人](docs/preview/03-cyan-toptext-v1.jpg) | ![220px 缩略图](docs/preview/thumb-220.jpg) |
| 标题 111px，压在上部 40% 的暗区 | 220px 宽。手机上读不清，说明字号还不够 |

三张的文案都是「把人生发给 / AI 分析」，只换了版式与配色——这也是技能建议的出稿方式：同一句话出 2 稿让人挑。

**想直接复现**：`examples/` 里有这三张的 spec 和对应底图，克隆后直接跑：

```bash
python3 scripts/compose_cover.py examples/spec-cream-v4.json
```

## 它解决什么

AI 直接生成带中文的封面，常见三种崩：字形缺笔画、大小失控、以及模型自作主张在顶部排一行拼不出来的英文刊头。这个技能把三件事拆开：

| 环节 | 谁来干 | 为什么 |
|---|---|---|
| 场景与人像 | 图像模型（`image_edit`） | 真人质感只有模型能给 |
| 留白 | 提示词里写死方位与比例 | 不写死就一定会被元素吃掉 |
| 中文标题 | `scripts/compose_cover.py` | 真实字体渲染，100% 可控 |
| 验收 | 220px 缩略预检 + 对比度/字号告警 | 手机上读不清等于没做 |

## 前置条件

- Python 3
- Pillow：`python3 -c "import PIL"` 能跑通
- 一个中文字体（脚本会按常见路径找；找不到时在 spec 里给 `font_path`，**不要用英文占位**）
- 一个能调图像生成工具的 Agent 运行时

## 快速开始

```bash
# 1. 把技能放进你的 skill 目录（示例）
cp -R xhs-tech-cover ~/.agent/skills/

# 2. 放你的照片
#    assets/persona/persona-anchor.jpg  <- 正面、正对镜头、光线均匀
#    并按 assets/persona/face-card.md 填一遍面部特征

# 3. 让 Agent 生成无字背景，然后叠字
python3 scripts/compose_cover.py spec.json
python3 scripts/compose_cover.py spec.json --safe-debug   # 核安全区
python3 scripts/compose_cover.py spec.json --thumb-only    # 只出缩略图，快速迭代
```

输出 `<名>.png` 与 `<名>_thumb-220.jpg`。stdout 是每段字的字号、占宽比、行数、对比度；stderr 是告警。

## 工作流（7 步）

1. **定选题** — 出 3 个候选标题，定版式与配色
2. **生成无字背景** — 按 `references/prompt-engine.md` 的 Nexus 六段式写提示词
3. **验收背景** — 有没有伪文字、脸对不对、留白够不够、手有没有畸形
4. **写 spec** — 坐标 0-1 归一化，标题必须带 `auto_fit`
5. **渲染** — `compose_cover.py`
6. **处理告警** — 不许忽略
7. **交付** — 看缩略图，出 2 稿对比

## 四套配色 × 四种版式

| 配色 | 基底 | 适用 |
|---|---|---|
| 冷曜蓝 CYAN-VOID（默认） | `#05070F → #0B1524`，青 `#35E0FF` | AI 工具、教程、干货 |
| 霓虹洋红 NEON-MAGENTA | `#07060E → #140A1C` | 观点、争议、情绪型 |
| 银灰硬件 SILVER-HARDWARE | `#0E1116 → #1A2029` | 测评、硬件、高级感 |
| 暖白轻科技 CREAM-LIGHT | `#FDFBF6 → #EDE7DC`，墨色字 | 人生、情感、复盘、高客单 |

| 版式 | 人物 | 文字区 |
|---|---|---|
| 1 左字右人（默认） | 右 2/5 | 左侧 0-55% |
| 2 上字下人 | 居中下 2/3 | 顶部 0-40% |
| 3 全息破框 | 中心偏右、破框 | 左侧或底部 |
| 4 正面操作式 | 正中偏下、正面直视、双手操作 | 头顶上方暗带 |

实测最好用的两组：**正面操作式 + 暖白轻科技**（人生/复盘类）、**正面操作式 + 冷曜蓝**（AI 工具类）。

## 目录结构

```
xhs-tech-cover/
├── SKILL.md
├── assets/
│   ├── spec-template.json          冷曜蓝·左字右人
│   ├── spec-template-cream.json    暖白·顶部大标题
│   └── persona/                    你的照片与特征卡（不进仓库）
├── docs/preview/                   README 用的效果图（三张成品 + 一张缩略预检）
├── examples/                       可直接复现的三份 spec + 对应底图
├── references/
│   ├── prompt-engine.md            Nexus 六段式 + 场景弹药库 + 表现力配方
│   ├── style-system.md             四套配色 / 光 / 科技元素 / 四种版式
│   ├── persona-lock.md             放图流程 + 面部特征卡 + 锁脸句式
│   └── copy-formulas.md            标题公式与文案规则
└── scripts/compose_cover.py        背景处理 + 中文叠字 + 缩略预检 + 告警
```

## 三条最容易踩的坑

1. **写"杂志 / magazine / editorial"会得到一排乱码英文刊头**（实测形如 `LOMLAIHON`）。改成"商业人像摄影"，并把 `文字、字母、单词、刊头、排版元素` 摊到词一级写进 Negative，两个动作一起做。
2. **"保持面部不变"锁不住脸**。要列具体特征（脸型/眼型/鼻型/唇型/一处痣），再加一句"不要改成网红脸"。
3. **复杂场景会吃掉留白**。同时要求"悬浮面板群/控制台/数据流"时，"左侧干净"基本不生效——换版式，或者把元素写死在人物右侧与身后。

## 许可

MIT。

`docs/preview/` 里的三张成品用的是技能作者本人的形象，已授权公开，仅作效果参考。`assets/persona/` 不放任何照片——你把自己的照片放进去后，`.gitignore` 会挡住它，不会被提交。
