"""Record a scripted walkthrough of a demo page as MP4, GIF or WebM.

steps: a list of actions run in order, e.g.
  [{"wait": 1500}, {"eval": "QZ_ASK('Who can approve a carrier SLA exception?')"}, {"scroll": "#answer"}, {"wait": 4000},
   {"click": "#play"}, {"type": ["#q", "lithium batteries"]}, {"press": "Enter"}]
Without steps the page is filmed for `seconds`."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from .check import _chrome, _url


def record(target: str, out: str | Path, steps: list | None = None, seconds: float = 10, size: tuple[int, int] = (1440, 900)) -> Path:
    from playwright.sync_api import sync_playwright
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as td:
        with sync_playwright() as p:
            kw = {"args": ["--no-sandbox", "--allow-file-access-from-files"]}
            if _chrome():
                kw["executable_path"] = _chrome()
            b = p.chromium.launch(**kw)
            ctx = b.new_context(viewport={"width": size[0], "height": size[1]}, record_video_dir=td, record_video_size={"width": size[0], "height": size[1]})
            pg = ctx.new_page()
            pg.goto(_url(target), wait_until="load")
            pg.wait_for_timeout(1200)
            for s in steps or [{"wait": int(seconds * 1000)}]:
                if "wait" in s:
                    pg.wait_for_timeout(int(s["wait"]))
                elif "eval" in s:
                    pg.evaluate(s["eval"])
                elif "click" in s:
                    pg.click(s["click"])
                elif "scroll" in s:
                    pg.evaluate(f"document.querySelector({s['scroll']!r}).scrollIntoView({{behavior:'smooth', block:'start'}})")
                    pg.wait_for_timeout(900)
                elif "type" in s:
                    pg.fill(s["type"][0], ""); pg.type(s["type"][0], s["type"][1], delay=45)
                elif "press" in s:
                    pg.keyboard.press(s["press"])
            video = pg.video.path()
            ctx.close()
            b.close()
        src = Path(video)
        from ..util import ffmpeg_path
        ff = ffmpeg_path()
        if out.suffix == ".webm" or not ff:
            shutil.copyfile(src, out.with_suffix(".webm"))
            return out.with_suffix(".webm")
        if out.suffix == ".gif":
            pal = Path(td) / "pal.png"
            vf = "fps=10,scale=1080:-1:flags=lanczos"
            subprocess.run([ff, "-y", "-i", str(src), "-vf", vf + ",palettegen=max_colors=96:stats_mode=diff", str(pal)], capture_output=True, check=True)
            subprocess.run([ff, "-y", "-i", str(src), "-i", str(pal), "-lavfi", vf + " [x]; [x][1:v] paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle", str(out)], capture_output=True, check=True)
        else:
            subprocess.run([ff, "-y", "-i", str(src), "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out)], capture_output=True, check=True)
    return out
