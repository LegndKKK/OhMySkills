#!/usr/bin/env python3
"""collect-rednote-info 的抓取后端。

子命令：
  profile  <主页URL>            账号信息 + 首屏笔记（服务端渲染，约 31 条）
  catalog  <主页URL> [--limit]  滚动加载完整目录（Selenium，有头浏览器）
  note     <笔记URL> [--download DIR]  正文 / 标签 / 图片（免登录优先）
  comments <笔记URL> [--limit]  评论区文字（Selenium，带 Cookie 可看全部）

结果统一写成 UTF-8 的 JSON 文件（Windows 控制台会把中文显示成乱码，别直接看 stdout）。
Cookie 优先级：--cookie > --cookie-file > %TEMP%\\xhs\\cookie.txt
"""
import argparse
import json
import os
import pathlib
import re
import sys
import time
from urllib.parse import quote

import requests

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36")
TMP = pathlib.Path(os.environ.get("TEMP") or os.environ.get("TMPDIR") or "/tmp") / "xhs"
DEFAULT_COOKIE = TMP / "cookie.txt"
LINK_RE = re.compile(r"/(?:explore|discovery/item)/([0-9a-f]{24})|/user/profile/[0-9a-f]+/([0-9a-f]{24})")
ID_RE = re.compile(r"^[0-9a-f]{24}$")


def save(obj, path, extra=None):
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    summary = {"ok": True, "file": str(p)}
    summary.update(extra or {})
    print(json.dumps(summary, ensure_ascii=True))


def read_cookie(args):
    if getattr(args, "cookie", None):
        return args.cookie.strip()
    p = pathlib.Path(getattr(args, "cookie_file", None) or DEFAULT_COOKIE)
    if p.exists():
        return p.read_text(encoding="utf-8-sig").strip()
    return ""


def parse_cookie(cookie):
    out = {}
    for block in cookie.split(";"):
        if "=" in block:
            k, v = block.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def http_get(url, cookie):
    headers = {
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9",
        "Referer": "https://www.xiaohongshu.com/",
    }
    if cookie:
        headers["Cookie"] = cookie
    return requests.get(url, headers=headers, timeout=30)


def raw_state(html):
    m = re.search(r"window\.__INITIAL_STATE__=(.*?)</script>", html, re.S)
    if not m:
        raise SystemExit("页面里没有 __INITIAL_STATE__：可能被风控，或跳到了登录页")
    return m.group(1).strip()


def extract_top(raw, key):
    """取出 __INITIAL_STATE__ 顶层 key 的 JSON 对象（页面里可能混有 new Map(...)，整段无法直接 json.loads）。"""
    pos, depth, instr, esc = 0, 0, False, False
    target = f'"{key}":'
    while pos < len(raw):
        ch = raw[pos]
        if instr:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                instr = False
            pos += 1
            continue
        if ch == '"':
            if depth == 1 and raw.startswith(target, pos):
                start = raw.index("{", pos)
                end = _balanced(raw, start)
                return json.loads(_clean(raw[start:end]))
            instr = True
        elif ch in "{[":
            depth += 1
        elif ch in "}]":
            depth -= 1
        pos += 1
    raise SystemExit(f"__INITIAL_STATE__ 里找不到 {key}")


def _balanced(s, start):
    depth, instr, esc = 0, False, False
    for i in range(start, len(s)):
        ch = s[i]
        if instr:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                instr = False
            continue
        if ch == '"':
            instr = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    raise SystemExit("JSON 括号不配平")


def _clean(text):
    return re.sub(r"(?<![\"\w])undefined(?![\"\w])", "null", text)


def note_id(url):
    m = LINK_RE.search(url)
    if m:
        return m.group(1) or m.group(2)
    if ID_RE.match(url.strip()):
        return url.strip()
    raise SystemExit(f"从 URL 里找不到笔记 ID: {url}")


# ---------------------------------------------------------------- 服务端渲染

def cmd_profile(args):
    r = http_get(args.url, read_cookie(args))
    u = extract_top(raw_state(r.text), "user")
    data = u.get("userPageData") or {}
    if not data:
        raise SystemExit("主页数据为空：Cookie 缺失或已过期（需要含 web_session 的登录态）")
    b = data.get("basicInfo", {})
    notes = []
    for n in (u.get("notes") or [[]])[0]:
        card = n.get("noteCard") or {}
        if card.get("type") == "rec":
            continue
        notes.append({
            "id": n.get("id"),
            "title": card.get("displayTitle") or card.get("title") or "",
            "type": card.get("type"),
            "liked": (card.get("interactInfo") or {}).get("likedCount"),
            "url": f"https://www.xiaohongshu.com/explore/{n.get('id')}?xsec_token={n.get('xsecToken','')}&xsec_source=pc_user",
        })
    save({
        "nickname": b.get("nickname"),
        "red_id": b.get("redId"),
        "desc": b.get("desc"),
        "ip": b.get("ipLocation"),
        "tags": [t.get("name") for t in data.get("tags") or []],
        "interactions": {i.get("name"): i.get("count") for i in data.get("interactions") or []},
        "posted": data.get("posted"),
        "notes": notes,
        "limit_note": "首屏约 31 条；要全量用 catalog 子命令",
    }, args.out or TMP / "out" / "profile.json", {"notes": len(notes)})


def cmd_note(args):
    r = http_get(args.url, read_cookie(args))
    root = extract_top(raw_state(r.text), "note")
    nid = note_id(args.url)
    dm = root.get("noteDetailMap") or {}
    if nid not in dm:
        raise SystemExit("笔记不在 noteDetailMap 里：xsec_token 可能已过期")
    d = dm[nid]["note"]
    images = [{
        "url": im.get("urlDefault") or im.get("url"),
        "width": im.get("width"),
        "height": im.get("height"),
    } for im in d.get("imageList") or []]
    if args.download and images:
        outdir = pathlib.Path(args.download)
        outdir.mkdir(parents=True, exist_ok=True)
        for i, im in enumerate(images, 1):
            p = outdir / f"{i:02d}.jpg"
            if not (p.exists() and p.stat().st_size > 10_000):
                resp = requests.get(im["url"], headers={"User-Agent": UA,
                                                        "Referer": "https://www.xiaohongshu.com/"}, timeout=60)
                resp.raise_for_status()
                p.write_bytes(resp.content)
            im["file"] = str(p)
    interact = d.get("interactInfo") or {}
    save({
        "id": nid,
        "title": d.get("title"),
        "desc": d.get("desc"),
        "type": d.get("type"),
        "time": d.get("time"),
        "ip": d.get("ipLocation"),
        "tags": [t.get("name") for t in d.get("tagList") or []],
        "author": (d.get("user") or {}).get("nickname"),
        "interact": {k: interact.get(k) for k in ("likedCount", "collectedCount", "commentCount", "shareCount")},
        "images": images,
    }, args.out or TMP / "out" / "note.json", {"images": len(images)})


# ------------------------------------------------------------------ Selenium

def make_driver(args):
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options

    o = Options()
    o.add_argument("--window-size=1400,1000")
    o.add_argument("--lang=zh-CN")
    o.add_argument("--disable-blink-features=AutomationControlled")
    o.add_experimental_option("excludeSwitches", ["enable-automation"])
    o.add_experimental_option("useAutomationExtension", False)
    profile = args.profile_dir or str(TMP / "chrome-profile")
    pathlib.Path(profile).mkdir(parents=True, exist_ok=True)
    o.add_argument(f"--user-data-dir={profile}")
    if args.headless:
        o.add_argument("--headless=new")
    d = webdriver.Chrome(options=o)
    d.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument",
                      {"source": "Object.defineProperty(navigator,'webdriver',{get:()=>undefined})"})
    return d


def login(d, cookie):
    d.get("https://www.xiaohongshu.com/404")
    time.sleep(1)
    for k, v in parse_cookie(cookie).items():
        try:
            d.add_cookie({"name": k, "value": v, "domain": ".xiaohongshu.com", "path": "/"})
        except Exception:
            pass


LOGIN_HINT = "被重定向到登录页：Cookie 无效；headless 模式也会被踢回登录，去掉 --headless 再试"


def cmd_catalog(args):
    d = make_driver(args)
    try:
        login(d, read_cookie(args))
        d.get(args.url)
        time.sleep(6)
        if "/login" in d.current_url:
            raise SystemExit(LOGIN_HINT)
        seen, stagnant = {}, 0
        for _ in range(args.max_scroll):
            cards = d.execute_script("""
              return [...document.querySelectorAll('section.note-item')].map(s => {
                const a = s.querySelector('a[href*="xsec_token="]');
                const m = a && a.href.match(/xsec_token=([^&]+)/);
                return {id: s.dataset.noteId,
                        title: (s.innerText || '').split('\\n')[0].trim(),
                        token: m ? decodeURIComponent(m[1]) : null};
              });
            """)
            before = len(seen)
            for c in cards:
                if c["id"] and c["id"] not in seen:
                    c["href"] = (f"https://www.xiaohongshu.com/explore/{c['id']}"
                                 f"?xsec_token={c['token']}&xsec_source=pc_user") if c.get("token") else None
                    seen[c["id"]] = c
            if args.limit and len(seen) >= args.limit:
                break
            stagnant = stagnant + 1 if len(seen) == before else 0
            if stagnant >= 3:
                break
            d.execute_script("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(1.6)
    finally:
        d.quit()
    rows = list(seen.values())
    if args.limit:
        rows = rows[: args.limit]
    for i, r in enumerate(rows, 1):
        r["index"] = i
    save({"count": len(rows), "notes": rows},
         args.out or TMP / "out" / "catalog.json",
         {"count": len(rows), "truncated": bool(args.limit)})


# ------------------------------------------------------------------ 搜索页

JS_SEARCH = """
const out = [];
document.querySelectorAll('section.note-item').forEach(s => {
  const a = s.querySelector('a[href*="xsec_token="]');
  if (!a) return;                       // 跳过「大家都在搜」这类推荐卡（无真链接）
  const href = a.getAttribute('href') || '';
  const m = href.match(/(?:explore|search_result|discovery\\/item)\\/([0-9a-f]{24})/);
  const t = href.match(/xsec_token=([^&]+)/);
  if (!m && !s.dataset.noteId) return;
  // 结构化取值：innerText 会被「文件」标签、置顶标记等插队，顺序不可靠
  const q = sel => { const el = s.querySelector(sel); return el ? (el.innerText || '').trim() : ''; };
  const lines = (s.innerText || '').split('\\n').map(x => x.trim()).filter(Boolean);
  const title = q('a.title span') || q('a.title') || lines[0] || '';
  const author = q('.author .name') || q('.name') || lines[1] || '';
  const time = q('.author .time') || q('.time') || lines[2] || '';
  const like = q('.like-wrapper .count');
  out.push({
    id: (m ? m[1] : null) || s.dataset.noteId || null,
    token: t ? t[1] : null,
    title: title, author: author, time: time, like: like,
    tail: like ? like + ' | 赞' : lines.slice(3).join(' | ')
  });
});
return out;
"""


def cmd_search(args):
    """搜索页取数：关键词 -> 固定格式 JSON（id/标题/作者/时间/token/链接）。

    搜索页是 SPA，必须带登录态 + 有头 Chrome；滚动分页，滚太快会触发风控。
    """
    d = make_driver(args)
    try:
        login(d, read_cookie(args))
        d.get("https://www.xiaohongshu.com/")
        time.sleep(2)
        d.get("https://www.xiaohongshu.com/search_result?keyword="
              + quote(args.keyword) + "&source=web_explore_feed")
        time.sleep(args.wait)
        if "/login" in d.current_url:
            raise SystemExit(LOGIN_HINT)
        seen, stagnant = {}, 0
        for _ in range(args.max_scroll):
            cards = d.execute_script(JS_SEARCH)
            before = len(seen)
            for c in cards:
                if c["id"] and c["id"] not in seen:
                    c["url"] = (f"https://www.xiaohongshu.com/explore/{c['id']}"
                                f"?xsec_token={c['token']}&xsec_source=pc_search") if c.get("token") else None
                    seen[c["id"]] = c
            if args.limit and len(seen) >= args.limit:
                break
            stagnant = stagnant + 1 if len(seen) == before else 0
            if stagnant >= 3:
                break
            d.execute_script("window.scrollTo(0, document.body.scrollHeight)")
            time.sleep(args.interval)
    finally:
        d.quit()
    rows = list(seen.values())
    if args.limit:
        rows = rows[: args.limit]
    for i, r in enumerate(rows, 1):
        r["index"] = i
    save({"keyword": args.keyword, "count": len(rows),
          "searched_at": time.strftime("%Y-%m-%d %H:%M:%S"), "notes": rows},
         args.out or TMP / "out" / "search.json",
         {"count": len(rows), "truncated": bool(args.limit)})


JS_COMMENTS = """const out = [];
document.querySelectorAll('[class*=comment-item]').forEach(el => {
  const t = (el.innerText || '').trim();
  if (t) out.push(t);
});
return out;
"""

JS_EXPAND = """
const btns = [...document.querySelectorAll('[class*=comment] *')]
  .filter(e => /^(展开|展开更多回复|展开更多|查看更多回复)/.test((e.innerText || '').trim()));
btns.slice(0, 30).forEach(b => b.click());
return btns.length;
"""


def cmd_comments(args):
    d = make_driver(args)
    try:
        login(d, read_cookie(args))
        d.get(args.url)
        time.sleep(8)
        if "/login" in d.current_url:
            raise SystemExit(LOGIN_HINT)
        prev = 0
        for _ in range(args.scroll):
            d.execute_script(JS_EXPAND)
            time.sleep(0.8)
            d.execute_script("""
              const el = document.querySelector('[class*=comments-el]');
              if (el) el.scrollTop = el.scrollHeight;
              window.scrollTo(0, document.body.scrollHeight);
            """)
            time.sleep(1.6)
            got = len(set(d.execute_script(JS_COMMENTS)))
            if args.limit and got >= args.limit:
                break
            if got == prev and prev > 0:
                break
            prev = got
        texts = d.execute_script(JS_COMMENTS)
        tail = d.execute_script("""
          const el = document.querySelector('[class*=comments-el]');
          return el ? el.innerText.slice(-120) : '';
        """)
    finally:
        d.quit()
    uniq = list(dict.fromkeys(t.strip() for t in texts if t.strip()))
    if args.limit:
        uniq = uniq[: args.limit]
    save({"count": len(uniq), "comments": uniq, "saw_end": "- THE END -" in (tail or ""),
          "note": "每条是整块文本：昵称/正文/时间地点/点赞回复；未登录时只能看到部分"},
         args.out or TMP / "out" / "comments.json",
         {"count": len(uniq), "saw_end": "- THE END -" in (tail or "")})


def main():
    ap = argparse.ArgumentParser(description="collect-rednote-info 抓取后端")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--cookie", help="完整 Cookie 字符串")
        p.add_argument("--cookie-file", help="含 Cookie 的文件，默认 %%TEMP%%\\xhs\\cookie.txt")
        p.add_argument("--out", help="输出 JSON 路径")

    p = sub.add_parser("profile", help="账号信息 + 首屏笔记")
    p.add_argument("url")
    common(p)

    p = sub.add_parser("catalog", help="滚动加载完整目录")
    p.add_argument("url")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--max-scroll", type=int, default=60)
    p.add_argument("--profile-dir")
    p.add_argument("--headless", action="store_true")
    common(p)

    p = sub.add_parser("search", help="按关键词搜索，滚动取结果列表")
    p.add_argument("keyword", help="搜索词，可含空格，如 \"泉州 旅游攻略\"")
    p.add_argument("--limit", type=int, default=40)
    p.add_argument("--max-scroll", type=int, default=20)
    p.add_argument("--interval", type=float, default=2.2, help="每次滚动后的等待秒数，太小会触发风控")
    p.add_argument("--wait", type=float, default=9.0, help="打开搜索页后的首次等待秒数")
    p.add_argument("--profile-dir")
    p.add_argument("--headless", action="store_true")
    common(p)

    p = sub.add_parser("note", help="笔记正文与图片")
    p.add_argument("url")
    p.add_argument("--download", help="把图片下载到该目录")
    common(p)

    p = sub.add_parser("comments", help="评论区文字")
    p.add_argument("url")
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--scroll", type=int, default=10)
    p.add_argument("--profile-dir")
    p.add_argument("--headless", action="store_true")
    common(p)

    args = ap.parse_args()
    {"profile": cmd_profile, "catalog": cmd_catalog, "search": cmd_search,
     "note": cmd_note, "comments": cmd_comments}[args.cmd](args)


if __name__ == "__main__":
    main()
