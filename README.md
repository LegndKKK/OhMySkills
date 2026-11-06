# OhMySkills

自用 agent skills 合集。每个子目录是一个独立 skill，遵循 `SKILL.md` + `scripts/` 的结构。

## 收录

| skill | 说明 |
|---|---|
| [`collect-rednote-info`](collect-rednote-info/SKILL.md) | 抓小红书主页 / 单篇笔记 / 搜索结果，输出目录、正文、图片转文字、评论区；支持只给一句搜索需求，由 agent 按目标逐条判断相关性 |
| [`local-ocr`](local-ocr/SKILL.md) | 本地 PaddleOCR 批量逐字转写（图片/截图/扫描件/PDF 页面），GPU 约 0.1–0.4 秒/张，离线不耗 token |

## 用法

```bash
# 依赖：python + selenium + 本机 Chrome
pip install selenium

# 单篇笔记
python collect-rednote-info/scripts/xhs.py note <笔记URL> --download ./images

# 搜索（需登录 Cookie）
python collect-rednote-info/scripts/xhs.py search "泉州 旅游攻略" --limit 40
```

Cookie 默认从 `%TEMP%\xhs\cookie.txt` 读取，不要提交进仓库。

### 可选：本地 PaddleOCR（`local-ocr`）

图片转文字默认由模型读图（懂版式、手写、路线图）。文字规整的长图想跑得快，用 `local-ocr` skill：

```powershell
# 装到 E:\models\paddleocr（不要放进 skill 目录，别提交进仓库）
$home = "E:\models\paddleocr"
python -m venv "$home\venv"
"$home\venv\Scripts\python.exe" -m pip install paddlepaddle-gpu==3.3.1 --index-url https://www.paddlepaddle.org.cn/packages/stable/cu126/
"$home\venv\Scripts\python.exe" -m pip install paddleocr

# 批量转写（脚本会自动切到该 venv）
python local-ocr/scripts/ocr.py --dir ./images --json out/ocr.json
```

没有 NVIDIA 显卡就把 `paddlepaddle-gpu` 换成 `paddlepaddle`，或直接 `--device cpu`。
权重缓存在 `E:\models\paddleocr\paddlex`，换路径时设 `PADDLE_OCR_HOME`。
结果不分层级、读不了手写和箭头，落进 md 之前仍要让模型校对一遍。详见 [`local-ocr/SKILL.md`](local-ocr/SKILL.md)。

## 约定

- 输出统一 UTF-8 JSON；Windows 控制台看中文会乱码，用编辑器打开文件
- `--headless` 会被小红书踢回登录页，用有头浏览器
