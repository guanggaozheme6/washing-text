# 文本结构改写降重系统

输入一篇中文文稿 → 分句 → 用**句法结构变换**逐句改写 → 循环遍历至全篇达标 → 输出改写稿 + 评估报告。

> 核心结论：**"换同义词"对连续片段查重几乎无效，"改句法结构"才有效。**
> 本系统的核心是：基于依存/成分的**结构算子** + **保义校验** + **迭代选优** 三件套。

---

## Windows 安装包（分发给别人用）

`dist\WashingText-1.0.2-Setup.exe` 是标准 Windows 安装程序（Inno Setup 打包）：

- 双击安装，默认装到 `C:\Program Files\WashingText`，需管理员确认；
- 安装目录里有 **`WashingText.exe`** —— 双击它就是启动应用，不再是指向 `pythonw.exe` 的快捷方式；
- 自动创建开始菜单项（含「使用说明」），勾选后创建桌面快捷方式；
- 内置 Python 运行时、torch、HanLP 与全部三方依赖，**目标机不用装 Python**；
- 自带的 HanLP 模型放在安装目录 `models\`（由 `HANLP_HOME` 指向），装完即可离线出稿，不需要再下载；
- 启动后浏览器自动打开 `http://127.0.0.1:8777`；重复双击只会再开一个标签页，不会起第二个进程；
- 卸载走「设置 → 应用」或开始菜单的卸载项；`%APPDATA%\WashingText`（API Key、日志）会保留，模型随程序目录一起删除。

首次启动要加载 HanLP 模型，约 40–60 秒，顶栏显示「正在加载模型」，期间别关页面。

### 装完第一件事：填 API Key

页面右上角 **API 设置** → 选服务商（**DeepSeek / OpenAI / Claude**）→ 粘贴对应 Key
→ **测试连接**确认可用 → 保存。

- 三家的接口差异（endpoint、鉴权头、响应结构）在 `operators/llm.py` 的 `PROVIDER_API` 里统一处理；
- 模型名不锁死：界面给建议值，也能直接手填（中转服务/新模型都能用）；
- 切换服务商时会自动把模型带成该家的默认值，避免拿 A 家模型名去敲 B 家 API；
- Key 只写在本机 `%APPDATA%\WashingText\settings.json`，不上传；不填也能用，LLM 子算子会自动跳过。
- 环境变量 `WASHING_DEEPSEEK_KEY` 优先级更高，适合临时覆盖。

### 用完就关，别让模型占内存

常驻的 HanLP 模型占 1 GB 上下内存，两种方式收回：

- 点页面右上角 **停止服务** → 立刻退出，页面显示"服务已停止"；
- 什么都不点也行 → **所有页面关掉 30 秒后自动退出**（刷新、多标签页、切走再切回都不会误杀，
  因为页面每 15 秒有心跳，任何请求都会撤销待定的退出）。

不想自动退（例如频繁开关页面看稿），到 **API 设置** 里关掉「关闭页面后自动停止服务」。
服务退出后再打开页面是连不上的，需要重新双击桌面图标启动（要重新加载模型，约 40–60 秒）。

### 自己重新打包

```bash
.venv/Scripts/python.exe build/package.py      # 组装 build/stage (增量: 依赖没变就只重建 app)
.venv/Scripts/python.exe build/make_icon.py    # 改过图标才需要
build\compile_exe.cmd                          # 改过启动器 C 代码才需要 (需要 MinGW-w64)
"C:\Users\你的用户名\AppData\Local\Programs\Inno Setup 6\ISCC.exe" build\installer.iss
# 产物: dist\WashingText-<版本>-Setup.exe
```

版本号在四处：`build/package.py`、`web/app.py`、`launcher.py`、`build/installer.iss`。
`package.py` 开跑时会校验一致性，不一致直接报错，不会打出"版本各说各话"的包。

---

## 快速开始

### 方式一: Web 工作台 (推荐, 可视化)

```bash
cd 自己电脑位置\washing-text
.venv/Scripts/python.exe web/app.py
# 浏览器打开 http://127.0.0.1:8777
```

界面功能: 文稿编辑(粘贴/拖入 .txt) → 参数面板(轮数/种子/阈值/算子/语料/白名单) →
「先评估」看危险指数 / 「开始改写」看前后对比与逐句明细 (红删绿增高亮) →
一键下载 改写稿.txt / 明细.json / report.md。快捷键 `Ctrl+Enter` 直接改写。

![改写结果](out/shot-rewrite.png)

### 方式二: 命令行

```bash
cd 自己电脑位置\washing-text

# 1) 只评估不改写 (先看稿子的"危险程度")
.venv/Scripts/python.exe cli.py demo.txt --dry-run --corpus data/corpus/

# 2) 改写一篇文稿 (默认 2 轮, 种子可复现)
.venv/Scripts/python.exe cli.py demo.txt --out out/ --rounds 2 --seed 42 --corpus data/corpus/ --report

# 3) 指定算子 + 白名单
.venv/Scripts/python.exe cli.py demo.txt \
    --ops split,shift,attrib,connector,voice \
    --protect data/whitelist.txt \
    --corpus data/corpus/ --report --max-run 10
```

### CLI 参数

| 参数 | 说明 |
|---|---|
| `input` | 输入 .txt |
| `--out` | 输出目录, 默认 `out/` |
| `--rounds` | 迭代轮数, 默认 2, 上限 3 |
| `--seed` | 随机种子, 保证可复现 |
| `--ops` | 启用的算子: `split,shift,attrib,connector,voice,merge,synonym` |
| `--protect` | 术语白名单文件 |
| `--corpus` | 比对语料目录 |
| `--max-run` | 最长连续重合阈值, 默认 10 |
| `--report` | 输出 `report.md` |
| `--dry-run` | 只评估不改写 |

### 输出 (`out/`)

| 文件 | 内容 |
|---|---|
| `<name>.txt` | 改写后正文 (毛坯稿, 需人工通读) |
| `<name>.json` | 逐句明细: 原句/新句/算子/三个分数/前后重合 |
| `report.md` | 全篇评估: 超阈句数、平均最长重合、前后对比、最危险 TOP5 |

---

## 系统架构 (七层管线)

```
[0] 资产层    术语白名单 / 同义词表 / 比对语料库(data/)
      ↓
[1] 预处理    分句 → 段落结构保持 → 句序编号          rewriter/segmenter.py
      ↓
[2] 分析      HanLP 批量: tok / pos / dep / srl / ner rewriter/parser.py
      ↓
[3] 保护区    术语白名单 / 引文 / 数字 / 专名          rewriter/protect.py
      ↓
[4] 算子层    逐句匹配可用结构算子 → 随机组合 → 候选池  rewriter/operators/
      ↓
[5] 打分层    novelty / fidelity / fluency + 硬约束选优 rewriter/scorer.py
      ↓
[6] 组装层    段落回填 → 短句合并 → 标点统一           rewriter/pipeline.py
      ↓
[7] 报告层    out.txt + out.json + report.md          rewriter/overlap.py
```

内层循环在 [4]→[5] (单句候选池选优), 外层全篇循环控制轮次与早停。

## 结构算子清单

| # | 算子 | 变换示例 | 收益 | 文件 |
|---|---|---|---|---|
| S1 | **长句拆分** | "A，从而B。" → "A。由此B。" | ★★★ | `operators/split.py` |
| S2 | **状位移位** | "在一定的关系下，X才成为Y" ↔ "X在一定的关系下才成为Y" | ★★★ | `operators/shift.py` |
| S3 | **语态变换** | "生产资料被一部分人垄断" → "一部分人垄断了生产资料"；短被动删"被" | ★★☆ | `operators/voice.py` |
| S4 | **定语展开/后置** | "能实现…通信的各种理论和方法" → "各种理论和方法，它们能实现…通信" | ★★★ | `operators/attrib.py` |
| S5 | **连接词重写** | "因为A，所以B" → "A，因此B"；"因此"→"由此可见" | ★★☆ | `operators/connector.py` |
| S6 | **短句合并** | "工人创造了机器。工人占有了产品。" → "工人创造了机器，并且占有了产品。" | ★★☆ | `operators/merge.py` |
| S7 | **名词化切换** | "实现分配是目标" → "分配的实现是目标" | ★★☆ | `operators/attrib.py` |
| S8 | **同义替换** | 词级替换 (默认关, 风险收益比最差) | ★☆☆ | `operators/synonym.py` |
| S9 | **生成式兜底** | SimBERT / LLM / 回译 (默认关, 需自行配置) | ★★★ | `operators/generative.py` |
| S10 | **大模型整句重写** | 整句重构, 保持原意换句法 (DeepSeek / OpenAI / Claude) | ★★★ | `operators/llm.py` |

建议实施顺序: S1 → S2 → S4 → S5 → S3 → S6 → S7 → S8 → S9 (已在 `config.yaml` 默认启用前六个)。

### S10 大模型算子 (llm)

规则算子对真实学术长句的覆盖率上限约 25%~35%，S10 是唯一能把这个数字拉到 70% 以上的手段。

- **开关**：`config.yaml` → `llm.enabled: true`（Web 界面的「API 设置」也能改, 覆盖优先级更高）
- **服务商**：`llm.provider` 可选 `deepseek` / `openai` / `claude`，模型名自由填
- **密钥**（按优先级）：环境变量 `WASHING_DEEPSEEK_KEY`（三家通用）→ 界面「API 设置」保存的 key
  (`%APPDATA%\WashingText\settings.json`) → 旧的 `~/Desktop/WASHING.txt`
- **界面配置**：顶栏「API 设置」可换服务商/填 Key/换模型/调超时/测连通性, 保存后下一次改写立即生效, 不用重启服务
- **成本**：每句最多 2 次调用，一篇 500 句约 1000 次；`MAX_CALLS_PER_TEXT` 可调
- **降级**：连续失败 3 次自动熔断，本进程内退回规则算子，不会让整篇失败
- **输出仍受硬约束**：术语 / 数字 / NER / 否定词 / 引文由 `scorer.hard_check` 统一校验，LLM 不享特权
- 不开这个开关时，行为与本轮改造前一致（纯规则算子）

## 打分与硬约束

```
total = 0.45 × novelty + 0.30 × fidelity + 0.25 × fluency
```

- **novelty** = `1 - max_run / len(候选)`，`max_run` = 与【比对语料+原文】的最长连续公共子串
- **fidelity** = `0.5 × SRL包含率 + 0.5 × 依存三元组包含率` (关系标签先归一化，被动改主动不误杀)
- **fluency** = 句长合理 + 标点合理 + 无重复连接词

**硬约束** (不过直接丢弃)：否定词集合一致 / 数字原样保留 / 专名与白名单术语零改动 / 句长 0.6~1.8 倍 / 引文零改动。

**采用规则**：含标点口径的重合必须下降，且忽略标点口径不得变差；拆分是算法无损变换 (token 全保留)，保义门槛单独放宽。

## 两条评估口径

- **含标点** (主指标, PLAN §8 口径)：标点计入连续重合
- **忽略标点** (参考)：模拟查重后台常见口径

两个口径在报告里都给出。

## 迭代与早停 (⚠️ 防语义漂移)

- `rounds ≤ 3`，默认 2
- 每轮只处理"未达标句"，已达标句冻结
- 全篇平均重合改善 < 5% 立即早停
- 引文占比 > 50% 的句子直接冻结，不做任何改写

## 保护区 (🔒 三条铁律)

1. **术语不改** —— `data/whitelist.txt` 人工维护 (马原等术语密集文本必填)
2. **引文不动** —— 引号内容锁死，整句引文直接冻结
3. **数字不动** —— 百分比、年份、金额精确保留

---

## 目录结构

```
自己电脑位置\washing-text\
├── .venv\                    虚拟环境 (Python 3.13 + hanlp 2.1.5 + torch + flask)
├── HanLP\                    HanLP 源码
├── PLAN.md                   设计方案
├── README.md                 本文件
├── cli.py                    命令行入口
├── config.yaml               配置
├── demo.py / wash.py         原有示例 (保留)
├── demo.txt / sample.txt     演示输入
├── test_ops.py               算子冒烟测试
├── debug_funnel.py           单句候选池诊断工具
│
├── web\                      Web 工作台 (Flask)
│   ├── app.py                控制器: 路由 + 输入校验 + 错误映射
│   ├── service.py            服务层: 包装 rewriter, 模型预热, 任务串行
│   ├── templates\index.html  页面
│   └── static\style.css|app.js
│
├── tools\
│   └── web_shot.mjs          CDP 截图工具 (零依赖, 用于 UI 验收)
│
├── rewriter\                 核心包
│   ├── pipeline.py           编排 [1]→[7]
│   ├── segmenter.py          分句 + 段落结构保持
│   ├── parser.py             HanLP 封装 (批量 + 缓存)
│   ├── protect.py            保护区
│   ├── operators\            9 个结构算子
│   ├── scorer.py             三维打分 + 硬约束
│   ├── verifier.py           保义校验
│   ├── overlap.py            重合度计算
│   ├── synonyms.py           同义词资源加载
│   └── config.py             配置加载
│
├── data\
│   ├── whitelist.txt         术语白名单 (人工维护!)
│   ├── synonyms.json         自有同义词补充表
│   └── corpus\               比对语料 (重点: 老师给的材料原文必须放进来)
│       ├── CCT001_L1~L5.txt  马克思主义基本原理 课件
│       ├── CCT007_L1~L5.txt  大学成长课 预习材料
│       ├── CCT011_L1~L8.txt  毛中特 各专题复习材料
│       └── material.txt / textbook.txt
│
├── tools\
│   ├── pdf_to_corpus.py      课件 PDF -> 语料 txt (支持整目录批量/自动去重)
│   └── web_shot.mjs          网页截图
│
└── out\                      输出目录
```

课件 PDF 批量入库（自动接回硬换行、丢页码、清理排版空格）：

```bash
.venv/Scripts/python.exe tools/pdf_to_corpus.py "D:\某课\01_Slides" --prefix CCT011
```

---

## Web API (内部接口)

| 端点 | 方法 | 说明 |
|---|---|---|
| `/` | GET | 工作台页面 |
| `/api/health` | GET | 存活探测 (返回 `app` + `version`, 供启动器判断端口上是不是自己) |
| `/api/status` | GET | 模型预热状态 + 默认参数 + 忙碌标志 |
| `/api/evaluate` | POST | 只评估: `{text, corpus_dir?, whitelist?, max_run?}` |
| `/api/rewrite` | POST | 改写: `{text, rounds?, seed?, ops?, corpus_dir?, whitelist?, max_run?}` |
| `/api/parse` | POST | 解析上传的 docx/txt |
| `/api/settings` | GET/POST | 大模型设置 (Key / 模型 / 超时 / 开关 / 页面关闭自动退出) |
| `/api/settings/test` | POST | 用当前 Key 真发一次请求验证连通性 |
| `/api/ping` | POST | 页面心跳, 15 秒一次, 阻止自动退出 |
| `/api/bye` | POST | 页面关闭通知, 30 秒宽限后退出 (有请求就撤销) |
| `/api/shutdown` | POST | 主动停止服务, 立即退出释放内存 |

错误统一返回 `{ok:false, error:{code, message}}` (code 用于前端映射友好文案)。服务默认只监听 `127.0.0.1`；端口可用环境变量 `WASHING_PORT` 覆盖。

## 常用命令

```bash
# 算子冒烟测试 (9 个样例句, 看每个算子的产出和硬约束结果)
.venv/Scripts/python.exe test_ops.py

# 单句诊断: 看候选池漏斗 (哪个算子命中/为什么被拦)
.venv/Scripts/python.exe debug_funnel.py "你的句子。"

# Web 工作台
.venv/Scripts/python.exe web/app.py

# UI 截图验收 (需先用 --remote-debugging-port=9222 启动 Edge/Chrome)
node tools/web_shot.mjs "http://127.0.0.1:8777/" out/shot.png [none|evaluate|rewrite]
```

## 环境 (HanLP)

HanLP 2.1.5 已装好，模型已缓存 (`C:\Users\guang\AppData\Roaming\hanlp\`)。
首跑加载约 20 秒。`tasks` 越省越快，本系统默认 `tok,pos,dep,srl,ner`。

**模型下载失败**时用单线程手动拉取：

```bash
curl -L -o "C:/Users/guang/AppData/Roaming/hanlp/mtl/open_tok_pos_ner_srl_dep_sdp_con_electra_small_20201223_035557.zip" \
  "https://file.hankcs.com/hanlp/mtl/open_tok_pos_ner_srl_dep_sdp_con_electra_small_20201223_035557.zip"
```

## 已知限制 (必读)

1. **规则覆盖率有限**：实测学术长句上只有 **25%~35%** 的句子能被纯规则算子改动（短句、标题、已达标句不计），其余必须靠 S10 大模型算子或人工。开启 S10 后可到 70% 上下。
2. **保义校验不是保险箱**：SRL/依存比对只能抓结构性偏差，细微的语气/范围/程度变化会漏；「它是真理的」这类语法成立但指代不清的残句，纯规则也判不出来 → **终稿必须人工通读**。
3. **产出是毛坯**：机械改写痕迹 (拆句过碎、句长均匀) 本身是识别特征，需人工润色。
4. **比对库决定收益上限**：`data/corpus/` 里没放的东西，程序测不出也优化不了；老师给的材料原文一定要放进去。**当前语料库 3548 句（CCT001/CCT007/CCT011 课件原文），自评重复率与知网/维普不可比**，不可直接采信。课件 PDF 可用 `tools/pdf_to_corpus.py` 批量转成语料 txt。
5. **引文该跳过就跳过**：整句照搬材料的引文，正确做法是人工压成长引/短引，程序不做混淆。
6. **超阈句数不一定降到 0**：正文与比对库逐字相同 (最坏情况) 时，受白名单术语约束，单窗口连续重合难以全部压到阈值下——看**平均重合下降**更实在。另外拆句会让「1 句变 2 句」，超阈**句数**可能反而上升，应看「超阈字符数占比」。
7. **输入格式**：支持 `.txt` 与 `.docx`（含 python-docx 与 zipfile 双路径），PDF 硬换行会自动合并、孤立页码会被丢弃。单篇上限 10 万字。
8. **长文耗时**：开启 S10 时每句最多 2 次 API 调用，一篇 3 万字的硕士论文约需 **30~50 分钟**（规则算子约 12 分钟）。Web 台是同步请求，超长文建议改用 CLI 或分段处理，否则网关/浏览器会先超时。
9. **涉密与隐私**：收他人论文前须确认非涉密；用户文本不要留档、不要二次使用、不要加进 `data/corpus/`。

## 参考

- 设计文档: `PLAN.md`
- HanLP 源码: `https://github.com/hankcs/HanLP` / 文档: `https://hanlp.hankcs.com/docs/`
