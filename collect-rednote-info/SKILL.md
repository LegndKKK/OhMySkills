---
name: collect-rednote-info
description: 把小红书主页、单篇笔记或搜索结果抓成可读的 Markdown：目录、正文、图片转文字、评论区。也支持用户只给搜索词 + 目标描述（例：「搜索泉州旅游攻略，4天3晚，喜欢海边和美食」），由 agent 拿这个目标逐条判断结果是否合适。Use when the user pastes a xiaohongshu.com link (主页/笔记/explore/搜索页) or gives a search intent, and wants the content extracted, filtered, archived, or turned into text.
---

# collect-rednote-info

四步半：要地址/搜索词和 Cookie → 出目录、问范围 → 抓取并转写 → **交付汇总** → 问要不要再加工。
`scripts/xhs.py` 负责取数，Markdown 由你写。

## 1 拿地址或搜索词，以及 Cookie

三种入口，用户给哪种走哪种：

| 用户给的 | 走哪个命令 |
|---|---|
| 主页链接 `user/profile/...` | `profile` / `catalog` |
| 笔记链接 `explore/...`、`discovery/item`、`xhslink.com` 短链 | `note` |
| **只给搜索词，或一句需求** | `search` |

用户可能不给链接，直接给一句目标，例如：

> 搜索泉州旅游攻略，4天3晚，喜欢海边和美食

这时**这句话本身就是筛选标准**，先把它拆成可判断的条件：

- 目的地＝泉州
- 时长＝4 天 3 晚（能给出逐日行程/路线图优先）
- 偏好＝海边 + 美食（出现「海边/沙滩/海鲜/小吃/西街」加分）

拆完再自己补搜索词：一个词搜不全就并行搜几个（`泉州旅游攻略`、`泉州 4天3晚`、`泉州 海边 美食`），最后合并去重。
不要反问「请给我链接」——搜索入口就是为了省掉这一步。

Cookie 不是人人都要给：单篇笔记先跑 `note`，成功就不提 Cookie。**搜索、主页总览、翻页、完整评论区必须给**，这样要：

> 请给一份浏览器里的小红书 Cookie：
> 1. Chrome 打开小红书并登录 → `F12` → **Network**
> 2. 刷新页面，点一条 `profile/…`、`explore/…` 或 `search_result/…` 请求
> 3. **Request Headers** 里复制整行 `Cookie:` 的值
>
> 关键是 `a1`、`web_session`、`webId`、`gid`。`web_session` 是 HttpOnly，`document.cookie` 里取不到；少了它搜索页直接跳登录。

拿到后写进 `%TEMP%\xhs\cookie.txt`（UTF-8），**不写进仓库、不在回复里回显**，抓完删掉。

完成标准：有 URL 或搜索词；搜索词要能落到「可判断的条件」；需要登录态时 Cookie 里含 `web_session`。

## 2 出目录，问范围

### 主页

```
python scripts/xhs.py profile <主页URL>
```

读 `%TEMP%\xhs\out\profile.json`，给用户一张表：昵称、粉丝、笔记数、标签，加首屏笔记（序号/标题/赞）。要更多就用浏览器滚动：

```
python scripts/xhs.py catalog <主页URL> --limit 200
```

### 搜索

```
python scripts/xhs.py search "泉州 旅游攻略" --limit 40
```

读 `%TEMP%\xhs\out\search.json`，格式是固定的：

```json
{
  "keyword": "泉州 旅游攻略",
  "searched_at": "2026-11-05 20:31:00",
  "count": 40,
  "notes": [
    {"index": 1, "id": "6aeb…", "title": "…", "author": "…", "time": "10-11",
     "tail": "1.2万 | 收藏", "token": "AB…=", "url": "https://www.xiaohongshu.com/explore/…?xsec_token=…"}
  ]
}
```

给表：序号｜标题｜作者｜时间｜tail。

**然后逐条标相关性——这是搜索场景的核心动作，别只把列表丢给用户：**

- 信息够 → 标「✅ 相关 / ❓ 可能 / ❌ 不相关」，每条附**一句依据**（"标题就写了 4 天 3 晚"、"封面是西街小吃"）。
- 信息不够（标题党、正文空、关键信息在图里）→ 先 `note` 抓正文；正文为空或是图文笔记，就 `--download` 下封面/首图，用 `read` **看图判断**。
  **这一步是模型读图，不是 OCR 关键词匹配**：图上写"崇武古城看海"也算命中"海边"，标题没写"美食"但图里一桌海鲜也算。
- 判不准就标「❓」并写清不确定的原因，把决定权交回给用户，别硬猜。

单篇笔记没有目录，直接报标题、作者、互动数。

### 问范围（每次都要问，不要替用户默认）

给完目录/相关性表，**一次问清三项**，第二项是多选：

1. **范围**：全部 / 前 N 篇 / 序号区间 / 只要这一篇 / 只要标 ✅ 的
2. **每篇要什么**（多选，可以一项都不要）：
   - **图片**：保留原图 / 图片转文字 / 只看封面判断相关性后就够
   - **正文**：`desc` 原文
   - **评论区**：前 N 条 / 全部
   - 互动数据（赞/藏/评，默认给）
3. **存哪**：默认 `%TEMP%\xhs\out\<账号或关键词>_<日期>\`

用户答完**先复述一遍再动手**，例如：

> 收到：3 篇（序号 1、4、7），要正文 + 图片转文字，不抓评论，存 `xhs_info/泉州/`。

如果用户只挑了一项，**要说出漏掉的那两项会缺什么**，让他确认是有意省略：

> 只抓正文的话，这 3 篇的行程都写在图上，正文只有一句导语，等于什么都没拿到。

完成标准：范围、字段、路径三项都有明确回答；已复述；搜索场景下必须有一张标了相关性的表。

## 3 抓取与转写

每篇走一遍：

1. `python scripts/xhs.py note <笔记URL> --download <目录>/images`
2. 读 `note.json`：标题、`desc` 正文、标签、互动
3. 勾了「图片转文字」就**逐张** `read` 下载好的 `images/NN.jpg`，把图上文字完整抄下来；公式保留符号，表格式内容保持行列。

   **默认是模型读图**。图多且文字规整（清单、价格表、整页正文型长图）时，可以先用本地 PaddleOCR 出草稿再让模型校对，见「OCR 后端（可选）」；但 OCR 只出文字、不分层级、读不了手写和箭头路线，**别把它的输出直接贴进 md**。
4. 勾了「评论区」：`python scripts/xhs.py comments <笔记URL>`，再读 `comments.json`

   **评论区默认只看文字**：不下载、不转写评论里夹带的图片（`comments` 命令本身也只取文本块）。用户明确要"评论区的图"时再单独处理，别默认把评论图算进"图片转文字"的工作量里。
5. 按下述结构写 `<目录>/NN-<标题>.md`

```markdown
# <标题>

- 来源 / 链接 / 作者 / 发布时间 / IP / 互动数据

## 正文

## 图片文字

### 01

## 评论区
```

搜索场景的两个补充：

- `search.json` 里的 `url` 已经是 `/explore/<id>?xsec_token=…`，可以直接喂 `note`。
- 图文笔记的正文经常为空或只有一句导语，**信息在图上**：即使用户没勾"图片转文字"，只要需要判断相关性，也至少读一次封面。

完成标准：范围内每篇都有 md；勾选的字段都非空；md 里的图片页数与 `note.json` 的 `images` 数一致，缺页要明说。

## 4 交付汇总（必做）

抓完先给一张表，再问要不要加工。表里按第 1 步拆的目标维度逐项打勾，**别笼统写"符合"**：

| # | 篇目 | 命中目标 | 正文 | 图片 | 评论 | 状态 |
|---|---|---|---|---|---|---|
| 1 | 泉州 4 天 3 晚（西街+崇武） | 时长 ✅ / 海边 ✅ / 美食 ❓ | 820 字 | 9 张（已转写） | 12 条 | 完成 |
| 2 | 泉州 citywalk | 时长 ❌ / 海边 ❓ | 120 字 | 3 张（未转写） | — | 不完整 |

- **缺什么必须明说**：图片页数对不上、正文为空、评论没滚到底（`saw_end: false`）、抓取失败/被风控，全部写进「状态」列，不要用一句"已完成"糊过去。
- **字段覆盖要对照第 2 步的回答**：用户要了图片转文字就报"转写了 N/9 页"，要了评论就报条数；没勾的字段标「未抓（按要求）」。
- 用户中途改口径（"评论区还是抓一下吧"）→ **增量抓**，别把整轮重跑一遍。

## 5 问要不要再加工

交稿后问一句：合并成长文、提炼要点/面试问答、翻译、还是写进 `knowledge_base`。用户说不就停。

## 脚本速查

| 命令 | 用途 | 前提 |
|---|---|---|
| `profile <url>` | 账号信息 + 首屏约 31 条 | 需 Cookie |
| `catalog <url> --limit N` | 滚动加载主页目录（带 xsec_token 的链接） | 需 Cookie；有头 Chrome |
| `search "<关键词>" --limit N` | 搜索页滚动取结果（固定格式 JSON） | 需 Cookie；有头 Chrome |
| `note <url> --download DIR` | 正文、标签、图片 | 多数免登录 |
| `comments <url> --limit N` | 评论区 | 有头 Chrome；不登录只看得到部分 |
| `ocr.py --dir DIR` | 本地 PaddleOCR 批量转写（可选加速） | `.venv` 已装；见「OCR 后端」 |

- `search` 额外参数：`--limit`（默认 40）、`--max-scroll`（默认 20）、`--interval`（默认 2.2s，**别调太小，会触发风控**）、`--wait`（首屏等待，默认 9s）
- Cookie 默认读 `%TEMP%\xhs\cookie.txt`，也可 `--cookie-file` / `--cookie`
- 输出统一是 UTF-8 JSON：**Windows 控制台会把中文显示成乱码，用 read 工具看文件**
- 浏览器依赖 `pip install selenium` + 本机 Chrome；`--headless` 会被踢回登录页，别加
- 报「笔记不在 noteDetailMap」= `xsec_token` 过期，回主页/搜索页重新取链接

## OCR 后端（可选）

**默认走模型读图**（视觉理解：懂版式、箭头路线、手写字、能判断"这张图在讲什么"）。
本地 PaddleOCR 是**可选的加速通道**，只在文字量大且排版规整时开，跑完仍要让模型校对一遍。

| 场景 | 用哪个 |
|---|---|
| 判断相关性、手写体、路线图、多列海报、需要理解语义 | **模型读图（默认）** |
| 整页文字/清单/价格表，量大，只要逐字文字 | PaddleOCR 出草稿 → 模型校对 |
| 批量重跑、机器可读的纯文本归档 | PaddleOCR |

```powershell
# 一次进程批量跑（模型只加载一次），结果写 JSON
.\.venv\Scripts\python.exe scripts\ocr.py --dir "<images目录>" --json "out\ocr.json"

# 直接出 markdown 片段（### NN + ![](相对路径) + 文字）
.\.venv\Scripts\python.exe scripts\ocr.py --dir "<images目录>" --md

# 更准但慢 3~5 倍；认不出语言时可换 --lang
.\.venv\Scripts\python.exe scripts\ocr.py --dir "<images目录>" --model server --lang ch
```

- 设备默认 `auto`：有可用 CUDA 就走 `gpu:0`，否则 `cpu`；也可显式 `--device cpu`
- 首次运行自动下载 PP-OCRv5 权重到 `.cache/paddlex/`（mobile 约 20 MB，1~2 分钟；server 约 100 MB，首次 20 s 左右起）
- 下载源默认 ModelScope（HF 在国内常卡 TLS 握手），可用 `PADDLE_PDX_MODEL_SOURCE=HuggingFace` 覆盖
- 实测（本机 4090）：mobile 8 张信息图总耗时 1.45 s，单张 0.09–0.39 s，模型加载 1.5 s；CPU 约 5~6 s/张
- `auto` 判断的是"paddle 编译了 CUDA 且能枚举到卡"，不是"显卡空闲"；显存被占满时请显式 `--device cpu`
- 输出 JSON 里每张图有 `text`（按行合并）、`lines`、`boxes`、`elapsed`、`score`；`score` 偏低说明图糊或字太艺术，改回模型读图
- OCR 的已知短板：不分标题/正文层级、多列海报会串行、手写体和艺术字基本失效、图里的箭头关系全丢——**这些情况一律回到模型读图**
- 环境是独立 venv（`.venv/`，已 gitignore），不动系统 Python；PaddleOCR 缺失或跑挂时**直接回落模型读图**，不要卡在这
- 报 `ModuleNotFoundError: paddleocr` / 找不到 `.venv` 就是这个可选后端没装好，按仓库 README 装或跳过，不影响主流程

## 已知边界

- `webfetch` 直接抓小红书只会拿到 SPA 空壳（`userPageData: {}`），别走这条路
- **搜索页必须登录**：无 Cookie 直接跳登录页；结果是无限滚动，滚 3 轮约 40 条，滚太快会返回空列表
- **搜索结果的 `xsec_token` 时效更短**（几十分钟到几小时），当轮就要把正文抓完，隔天全废
- 搜索排序带个性化，同一关键词不同账号结果不同；要更全就换同义词再搜一轮
- 搜索卡片链接是 `/search_result/<id>?xsec_token=…`，脚本已转成 `/explore/<id>`；手动拼链接时别忘了这一步
- 主页首屏只有约 31 条，全量靠滚动；两千多篇的号会滚很久，先用 `--limit` 和用户确认
- 评论区条数受 `--scroll` 限制；`saw_end: false` 说明没滚到底
- **评论区图片不在默认范围内**：只取文字，评论里贴的图不下载、不转写（要的话单独说）
- 视频笔记只拿得到封面与文字描述，视频内容不在范围内
