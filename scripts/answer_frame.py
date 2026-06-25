"""Detect the red-circled correct answer in Minchan listening videos.

Each question ends with a slide where the correct option number is circled in red.
We scan that window at 2 fps, find the frame with the most pure-red in the answer
region, and read which third (1/2/3) the red sits in -> the official answer.

Region/axis differ by Mondai:
  m4 (発話表現): numbers '1 2 3' horizontal at bottom  -> region bottom-center, split columns
  m5 (即時応答): numbers '1. 2. 3.' vertical at left     -> region left-center, split rows
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
from PIL import Image

REGION = {
    "m4": (0.26, 0.76, 0.74, 0.94),  # x0,y0,x1,y1 (fractional)
    "m5": (0.285, 0.36, 0.43, 0.74),
}
AXIS = {"m4": "col", "m5": "row"}


def _red_thirds(arr: np.ndarray, region, axis: str) -> list[int]:
    h, w, _ = arr.shape
    x0, y0, x1, y1 = region
    crop = arr[int(h * y0):int(h * y1), int(w * x0):int(w * x1)]
    R, G, B = crop[:, :, 0].astype(int), crop[:, :, 1].astype(int), crop[:, :, 2].astype(int)
    red = (R > 150) & (G < 95) & (B < 95)
    parts = np.array_split(red, 3, axis=(1 if axis == "col" else 0))
    return [int(p.sum()) for p in parts]


def _looks_like_m5_title(arr: np.ndarray) -> bool:
    R, G, B = arr[:, :, 0].astype(int), arr[:, :, 1].astype(int), arr[:, :, 2].astype(int)
    yellow = (R > 180) & (G > 145) & (B < 110)
    h, w = yellow.shape
    left_top = yellow[:int(h * 0.45), :int(w * 0.25)].mean()
    right = yellow[:, int(w * 0.65):].mean()
    return left_top > 0.08 and right > 0.08


def find_circle(ffmpeg: str, video: str, t0: float, t1: float, mondai: str,
                workdir: Path, threshold: int = 25) -> dict:
    workdir.mkdir(parents=True, exist_ok=True)
    for f in workdir.glob("f_*.jpg"):
        f.unlink()
    subprocess.run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-ss", str(t0), "-to", str(t1),
                    "-i", video, "-vf", "fps=2", "-q:v", "4", str(workdir / "f_%03d.jpg")], check=True)
    frames = sorted(workdir.glob("f_*.jpg"))
    region, axis = REGION[mondai], AXIS[mondai]
    best = None
    best_any = None
    for i, fp in enumerate(frames):
        arr = np.asarray(Image.open(fp).convert("RGB"))
        thirds = _red_thirds(arr, region, axis)
        tot = sum(thirds)
        candidate = (tot, thirds, fp, t0 + i * 0.5)
        if best_any is None or tot > best_any[0]:
            best_any = candidate
        if mondai == "m5" and _looks_like_m5_title(arr):
            continue
        if best is None or tot > best[0]:
            best = candidate
    if best is None:
        best = best_any
    if not best:
        return {"answer": 0, "red_total": 0, "thirds": [0, 0, 0], "time": t0, "frame": ""}
    tot, thirds, fp, t = best
    answer = int(np.argmax(thirds)) + 1 if tot >= threshold else 0
    return {"answer": answer, "red_total": tot, "thirds": thirds, "time": round(t, 2), "frame": str(fp)}


if __name__ == "__main__":
    import json
    FFMPEG = r"C:\Users\Admin\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin\ffmpeg.exe"
    SC = Path(r"C:\Users\Admin\AppData\Local\Temp\claude\g--Project-anki-answer\222990d3-471a-4d04-b6a7-e2681247e9ec\scratchpad")
    wd = SC / "framescan"
    # m4 q1: anchors 11.84 -> 41 ; m5 q1: seg 4.86-33.31
    print("m4 q1:", json.dumps(find_circle(FFMPEG, str(SC / "m4" / "m4video.mp4"), 24.8, 40.0, "m4", wd)))
    print("m5 q1:", json.dumps(find_circle(FFMPEG, str(SC / "n3video.mp4"), 20.5, 34.3, "m5", wd)))
