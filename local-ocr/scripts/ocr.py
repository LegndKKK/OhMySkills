#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""本地 PaddleOCR 批量转写（可选后端）。

默认的图片转文字走「模型读图」（视觉理解，能看懂版式、手写、路线图）；
本脚本是**可选**的快速通道：纯 OCR，逐字识别，适合文字规整的长图
（清单、价格表、正文型攻略图）。

一次进程内加载一次模型、处理多张图，避免每张图重复加载。

用法：
    python scripts/ocr.py a.jpg b.jpg --json out.json
    python scripts/ocr.py --dir images/03 --json out.json
    python scripts/ocr.py --dir images/03 --model server --device gpu
    python scripts/ocr.py a.jpg --md          # 直接输出 markdown 片段

输出 JSON 结构：
    {"engine":"paddleocr","device":"gpu","model":"mobile","images":[
        {"path":"a.jpg","text":"...","lines":["..."],"elapsed":0.31,
         "boxes":12,"score":0.97}]}
"""
import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

# Windows 控制台默认 GBK，中文/emoji 会直接崩
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}

# 运行时（venv + 权重）统一放在 E:\models\paddleocr，skill 仓库里不存二进制。
# 换机器/换盘符时用 PADDLE_OCR_HOME 覆盖即可。
_OCR_HOME = Path(os.environ.get("PADDLE_OCR_HOME") or r"E:\models\paddleocr")
_VENV_PY = _OCR_HOME / "venv" / "Scripts" / "python.exe"


def _ensure_runtime():
    """用系统 python 直接跑时，自动切到 E:\\models\\paddleocr\\venv。"""
    if os.environ.get("PADDLE_OCR_REEXEC") == "1":
        return
    if sys.prefix.lower() != sys.base_prefix.lower():  # 已经在 venv 里
        return
    if not _VENV_PY.exists():
        return
    env = dict(os.environ, PADDLE_OCR_REEXEC="1")
    cmd = [str(_VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]]
    raise SystemExit(subprocess.call(cmd, env=env))


if __name__ == "__main__":
    _ensure_runtime()

# 本机全局 PYTHONPATH=E:\install 会把系统 numpy 顶到 site-packages 前面，
# 和 venv 里 paddle 要求的 numpy 版本打架；venv 模式下直接不认 PYTHONPATH。
if sys.prefix != sys.base_prefix and os.environ.get("PYTHONPATH"):
    _extra = {str(Path(x).resolve()).lower()
              for x in os.environ["PYTHONPATH"].split(os.pathsep) if x.strip()}
    sys.path[:] = [p for p in sys.path
                   if str(Path(p or ".").resolve()).lower() not in _extra]

# 权重落在 E:\models\paddleocr\paddlex
os.environ.setdefault("PADDLE_PDX_CACHE_HOME", str(_OCR_HOME / "paddlex"))
os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")
# 默认走 ModelScope：国内访问 HF 经常卡在 TLS 握手（可在外部覆盖）
os.environ.setdefault("PADDLE_PDX_MODEL_SOURCE", "ModelScope")


def collect_images(paths, directory, recursive):
    out = []
    for p in paths:
        p = Path(p)
        if p.is_dir():
            it = p.rglob("*") if recursive else p.glob("*")
            out += [x for x in sorted(it) if x.suffix.lower() in IMG_EXT]
        elif p.suffix.lower() in IMG_EXT:
            out.append(p)
        else:
            print(f"[skip] 不是图片: {p}", file=sys.stderr)
    if directory:
        d = Path(directory)
        it = d.rglob("*") if recursive else d.glob("*")
        out += [x for x in sorted(it) if x.suffix.lower() in IMG_EXT]
    # 去重且保序
    seen, uniq = set(), []
    for p in out:
        k = str(p.resolve()).lower()
        if k not in seen:
            seen.add(k)
            uniq.append(p)
    return uniq


def pick_device(arg):
    if arg != "auto":
        return arg
    try:
        import paddle

        if paddle.device.is_compiled_with_cuda() and paddle.device.cuda.device_count() > 0:
            return "gpu:0"
    except Exception:
        pass
    return "cpu"


def build_ocr(lang, model, device):
    try:
        from paddleocr import PaddleOCR
    except ImportError:
        sys.exit(
            f"缺少 paddleocr：请装到 {_VENV_PY.parent.parent}（或设 PADDLE_OCR_HOME 指向已装好的运行时）\n"
            f"参考 README 的「可选：本地 PaddleOCR」一节；装不好就直接用模型读图，不影响主流程。"
        )

    kwargs = dict(
        lang=lang,
        use_doc_orientation_classify=False,  # 攻略图都是正向的，省 0.1~0.3s/张
        use_doc_unwarping=False,
        use_textline_orientation=False,
        device=device,
    )
    if model in ("mobile", "server"):
        kwargs["text_detection_model_name"] = f"PP-OCRv5_{model}_det"
        kwargs["text_recognition_model_name"] = f"PP-OCRv5_{model}_rec"
    if device == "cpu":
        # paddle 3.3.1 的 oneDNN 在部分 CPU 上直接抛 NotImplementedError
        kwargs["enable_mkldnn"] = False
    try:
        return PaddleOCR(**kwargs)
    except (TypeError, ValueError) as e:  # 老版本 / 无 device 参数
        print(f"[warn] 完整参数失败({e})，退回最小参数", file=sys.stderr)
        base = dict(lang=lang, use_doc_orientation_classify=False,
                    use_doc_unwarping=False, use_textline_orientation=False)
        try:
            return PaddleOCR(**base)
        except (TypeError, ValueError):
            return PaddleOCR(lang=lang)


def _to_points(box):
    return [(float(p[0]), float(p[1])) for p in box]


def _norm_items(result):
    """把 3.x / 2.x 两种返回都归一到 [(text, score, points)]。"""
    items = []
    if result is None:
        return items
    # 3.x: list[OCRResult]，可用 res["rec_texts"] 取值
    for res in result if isinstance(result, (list, tuple)) else [result]:
        try:
            texts = res["rec_texts"]
            scores = res["rec_scores"]
            polys = res["rec_polys"]
        except Exception:
            texts = scores = polys = None
        if texts is not None:
            for t, s, p in zip(texts, scores, polys):
                if t and str(t).strip():
                    items.append((str(t).strip(), float(s), _to_points(p)))
            continue
        # 2.x: [[box, (text, score)], ...]
        seq = res if isinstance(res, (list, tuple)) else []
        if seq and isinstance(seq[0], (list, tuple)) and len(seq[0]) == 2:
            for box, pair in seq:
                if isinstance(pair, (list, tuple)) and len(pair) >= 1:
                    t = str(pair[0]).strip()
                    if t:
                        items.append((t, float(pair[1]) if len(pair) > 1 else 0.0,
                                      _to_points(box)))
    return items


def group_lines(items, tol_ratio=0.6):
    """按 y 中心聚成行，行内按 x 排序；返回 [str]。"""
    if not items:
        return []
    heights = [max(p[1] for p in pts) - min(p[1] for p in pts) for _, _, pts in items]
    h = statistics.median(heights) or 10.0
    tol = h * tol_ratio
    rows = []  # [yc, [items]]
    for it in items:
        pts = it[2]
        yc = sum(p[1] for p in pts) / len(pts)
        x0 = min(p[0] for p in pts)
        for row in rows:
            if abs(row[0] - yc) <= tol:
                row[1].append((x0, it[0]))
                row[0] = (row[0] * (len(row[1]) - 1) + yc) / len(row[1])
                break
        else:
            rows.append([yc, [(x0, it[0])]])
    rows.sort(key=lambda r: r[0])
    lines = []
    for _, cells in rows:
        cells.sort(key=lambda c: c[0])
        lines.append(_join([c[1] for c in cells]))
    return lines


def _join(parts):
    out = ""
    for s in parts:
        if not out:
            out = s
            continue
        a, b = out[-1], s[0]
        cjk = lambda ch: "\u4e00" <= ch <= "\u9fff"
        out += ("" if (cjk(a) or cjk(b)) else " ") + s
    return out.strip()


def run(ocr, path):
    t0 = time.perf_counter()
    try:
        out = ocr.predict(str(path))
    except AttributeError:
        out = ocr.ocr(str(path), cls=True)
    elapsed = time.perf_counter() - t0
    items = _norm_items(out)
    lines = group_lines(items)
    scores = [s for _, s, _ in items]
    return {
        "path": str(path),
        "text": "\n".join(lines),
        "lines": lines,
        "elapsed": round(elapsed, 3),
        "boxes": len(items),
        "score": round(sum(scores) / len(scores), 4) if scores else None,
    }


def to_markdown(results, images, prefix="images"):
    out = []
    cwd = Path.cwd()
    for i, (r, p) in enumerate(zip(results, images), 1):
        try:
            rel = Path(os.path.relpath(p, cwd)).as_posix()
        except ValueError:  # 跨盘符
            rel = p.as_posix()
        out.append(f"### {i:02d}\n")
        out.append(f"![]({rel})\n")
        out.append((r["text"] or "（未识别到文字）") + "\n")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description="本地 PaddleOCR 批量转写")
    ap.add_argument("images", nargs="*", help="图片路径或目录")
    ap.add_argument("--dir", help="图片目录（等价于传目录）")
    ap.add_argument("--recursive", action="store_true", help="递归子目录")
    ap.add_argument("--lang", default="ch", help="语言，默认 ch（中英混排）")
    ap.add_argument("--model", default="mobile", choices=["mobile", "server"],
                    help="mobile 快（默认）；server 准但慢 3~5 倍")
    ap.add_argument("--device", default="auto", help="auto | cpu | gpu:0")
    ap.add_argument("--json", dest="json_out", help="结果写入 JSON 文件")
    ap.add_argument("--md", action="store_true", help="输出 markdown 片段")
    args = ap.parse_args()

    images = collect_images(args.images, args.dir, args.recursive)
    if not images:
        print("没有找到图片", file=sys.stderr)
        return 2

    device = pick_device(args.device)
    t0 = time.perf_counter()
    print(f"[ocr] {len(images)} 张 | device={device} | model={args.model}", file=sys.stderr)
    ocr = build_ocr(args.lang, args.model, device)
    print(f"[ocr] 模型加载 {time.perf_counter() - t0:.1f}s", file=sys.stderr)

    results = []
    for n, p in enumerate(images, 1):
        try:
            r = run(ocr, p)
        except Exception as e:
            r = {"path": str(p), "text": "", "lines": [], "elapsed": 0,
                 "boxes": 0, "score": None, "error": f"{type(e).__name__}: {e}"}
        results.append(r)
        if "error" in r:
            print(f"[ocr] {n:>3}/{len(images)} ERR  {p.name}: {r['error']}", file=sys.stderr)
            continue
        print(f"[ocr] {n:>3}/{len(images)} {r['boxes']:>3}框 {r['elapsed']:.2f}s  {p.name}",
              file=sys.stderr)

    total = sum(r["elapsed"] for r in results)
    payload = {
        "engine": "paddleocr",
        "device": device,
        "model": args.model,
        "lang": args.lang,
        "count": len(results),
        "elapsed_total": round(total, 3),
        "elapsed_avg": round(total / len(results), 3) if results else 0,
        "images": results,
    }
    if args.json_out:
        p = Path(args.json_out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[ocr] -> {p}", file=sys.stderr)
    if args.md:
        print(to_markdown(results, images))
    elif not args.json_out:
        for r in results:
            print(f"===== {Path(r['path']).name} =====")
            print(r["text"])

    errs = [r for r in results if "error" in r]
    print(f"[ocr] 完成 {len(results)} 张，失败 {len(errs)}，总耗时 {total:.2f}s",
          file=sys.stderr)
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main())
