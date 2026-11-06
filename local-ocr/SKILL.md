---
name: local-ocr
description: 用本地 PaddleOCR 把图片、截图、扫描件、PDF 页面里成片的文字批量提取成纯文本或 JSON（GPU 约 0.1–0.4 秒/张，离线、不耗 token）。适合整页文字、清单、价格表、聊天长截图这类排版规整、只要逐字结果的场景；它不理解版式、读不了手写体和路线图，这类请改用模型读图。Use when the user wants bulk verbatim text extraction from images/screenshots/PDFs, offline OCR, or asks to "OCR 一下" / 批量识别图片文字.
---

# local-ocr

本地 OCR = **只出文字**，不理解语义、不分标题层级、不认箭头关系。
它的价值是快和离线，不是"看懂图"。

## 1 先用这张表判断该不该用它

| 场景 | 用什么 |
|---|---|
| 整页文字、清单、价格表、聊天记录长截图、扫描件、PDF 页面 | ✅ 本 skill |
| 几十张图批量要纯文本 / 要机器可读 JSON | ✅ 本 skill |
| 断网、图片不便外发、想省视觉 token | ✅ 本 skill |
| 手写体、书法、艺术字 | ❌ 识别率低，用模型读图 |
| 路线图、地图、箭头流程、多列海报 | ❌ 会串行、丢空间关系，用模型读图 |
| 要判断"这张图在说什么"、要还原标题/正文层级 | ❌ 用模型读图 |
| 只要判断相关性、扫一眼封面 | ❌ 用模型读图，更快更准 |

**拿不准就回模型读图。** 这个 skill 只处理"文字多且排版规整"的图。

## 2 怎么调

```powershell
cd E:\OhMySkills

# 整个目录批量（模型只加载一次，最常用）
python local-ocr\scripts\ocr.py --dir "<图片目录>" --json "<输出>.json"

# 直接产出 markdown 片段：### 01 + ![](相对路径) + 文字
python local-ocr\scripts\ocr.py --dir "<图片目录>" --md

# 指定文件 / 多个文件
python local-ocr\scripts\ocr.py a.jpg b.png --json out\ocr.json

# 更准（慢 3~5 倍）；语言不是中英混排时换 --lang
python local-ocr\scripts\ocr.py --dir "<图片目录>" --model server --lang ch
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--dir` | — | 图片目录，可和位置参数混用 |
| `--recursive` | 关 | 递归子目录 |
| `--model` | `mobile` | `server` 更准更慢 |
| `--device` | `auto` | `gpu:0` / `cpu`；显存被占满时显式写 `cpu` |
| `--lang` | `ch` | 中英混排；纯英文可 `en` |
| `--json` | — | 写 JSON 文件（推荐，别在控制台看中文） |
| `--md` | 关 | 打印 markdown 片段 |

**别一张图调一次**：每次进程都要重新加载模型（约 1.5 s），批量才划算。

## 3 输出

`--json` 的结构：

```json
{
  "engine": "paddleocr", "device": "gpu:0", "model": "mobile", "lang": "ch",
  "count": 8, "elapsed_total": 1.57, "elapsed_avg": 0.2,
  "images": [
    {"path": "...", "text": "按行合并的全文", "lines": ["第一行", "..."],
     "elapsed": 0.18, "boxes": 41, "score": 0.916}
  ]
}
```

- `text` / `lines`：按 y 坐标聚行、行内按 x 排序后的结果；多列排版会串行
- `score` 低于 ~0.85 基本可以判定：图糊、字太艺术、或语言不对 → 回模型读图
- 单张失败不会中断整批，失败项带 `error` 字段，退出码 1

Windows 控制台看中文会乱码，**用 read 工具读 JSON 文件**。

## 4 运行时与环境

```
E:\models\paddleocr\
├─ venv\                        paddlepaddle-gpu 3.3.1 + paddleocr 3.7（约 3.8 GB）
└─ paddlex\official_models\     PP-OCRv5 mobile / server 权重
```

- 运行时**不在本仓库**，也不要提交进 git
- 用系统 `python` 调用时，脚本会自动把自身重新交给那个 venv 执行，不需要你手动指定解释器
- 换盘符/换机器：设 `PADDLE_OCR_HOME=<目录>`，目录下要有 `venv\Scripts\python.exe` 和 `paddlex\official_models`
- 权重下载源默认 ModelScope（HF 在国内常卡在 TLS 握手），可用 `PADDLE_PDX_MODEL_SOURCE=HuggingFace` 覆盖
- 安装方法见仓库 README；**装不好就直接回模型读图**，不要卡在这

## 5 实测与边界

| 场景 | 耗时 |
|---|---|
| 4090 / mobile，8 张信息图 | OCR 合计 1.57 s，墙钟 4.8 s（含模型加载 1.5 s） |
| 4090 / mobile，单张 | 0.09–0.41 s |
| 4090 / server，单张 | 0.62 s（首次加载 17.8 s） |
| CPU / mobile，单张 | 5–6 s |

已知短板：

- 不分标题/正文层级，输出是一行行平铺
- 多列海报、图文混排会把不同栏目串到同一行
- 手写体、艺术字基本失效
- 图上的箭头、路线、连线关系全部丢失
- 地图类图片会把地名和正文混在一起
- CPU 上 paddle 3.3.1 的 oneDNN 会抛 `NotImplementedError`，脚本已自动关掉（`enable_mkldnn=False`）

## 6 和 collect-rednote-info 的分工

- `collect-rednote-info`：抓小红书 + 判断相关性 + 决定保留哪些图，**图片理解默认走模型读图**
- `local-ocr`（本 skill）：只在"文字量大且规整"时被它调用，产出草稿
- 交接规则：OCR 结果**必须模型校对后再写进 md**，不要把 `text` 原样贴过去
