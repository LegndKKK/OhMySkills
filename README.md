# OhMySkills

自用 agent skills 合集。每个子目录是一个独立 skill，遵循 `SKILL.md` + `scripts/` 的结构。

## 收录

| skill | 说明 |
|---|---|
| [`collect-rednote-info`](collect-rednote-info/SKILL.md) | 抓小红书主页 / 单篇笔记 / 搜索结果，输出目录、正文、图片转文字、评论区；支持只给一句搜索需求，由 agent 按目标逐条判断相关性 |

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

## 约定

- 输出统一 UTF-8 JSON；Windows 控制台看中文会乱码，用编辑器打开文件
- `--headless` 会被小红书踢回登录页，用有头浏览器
