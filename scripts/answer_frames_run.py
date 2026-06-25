"""Capture START + END(red-circle) frames and read the official answer for both decks.

  run m5   -> output/listening/frames/qNNN_start.jpg, _end.jpg + answers.json
  run m4   -> output/listening_m4/frames/qNNN_start.jpg, _end.jpg + answers.json
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from scripts.answer_frame import find_circle, _red_thirds, REGION, AXIS  # noqa: E402

FFMPEG = r"C:\Users\Admin\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin\ffmpeg.exe"
FFPROBE = FFMPEG.replace("ffmpeg.exe", "ffprobe.exe")
SC = Path(r"C:\Users\Admin\AppData\Local\Temp\claude\g--Project-anki-answer\222990d3-471a-4d04-b6a7-e2681247e9ec\scratchpad")
SCAN = SC / "framescan"

CFG = {
    "m5": {"video": SC / "n3video.mp4", "out": ROOT / "output" / "listening", "mondai": "m5"},
    "m4": {"video": SC / "m4" / "m4video.mp4", "out": ROOT / "output" / "listening_m4", "mondai": "m4"},
}


def _dur(video: Path) -> float:
    return float(subprocess.run([FFPROBE, "-i", str(video), "-show_entries", "format=duration",
                                 "-v", "quiet", "-of", "csv=p=0"], capture_output=True, text=True).stdout.strip() or 0)


def _grab(video: Path, t: float, dest: Path) -> None:
    subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-ss", str(max(0, t)),
                    "-i", str(video), "-frames:v", "1", "-q:v", "3", str(dest)], check=True)


def run(key: str) -> None:
    cfg = CFG[key]
    video = cfg["video"]
    out = cfg["out"]
    frames = out / "frames"
    frames.mkdir(parents=True, exist_ok=True)
    segs = json.load(open(out / "segments.json", encoding="utf-8"))
    dur = _dur(video)
    answers_path = out / "answers.json"
    old_answers = {}
    if answers_path.exists():
        old_answers = {a["q"]: a for a in json.load(open(answers_path, encoding="utf-8"))}
    answers = []
    for i, s in enumerate(segs):
        q = s["q"]
        if key == "m4":
            nxt = segs[i + 1]["anchor"] if i + 1 < len(segs) else min(dur, s["anchor"] + 30)
            t0, t1 = s["anchor"] + 13, nxt - 1
            start_t = min(nxt - 0.5, max(s["start"] + 0.2, s["anchor"] + 0.35))
        else:  # m5
            t0, t1 = s["start"] + 0.55 * s["dur"], min(dur, s["end"] + 1.5)
            start_t = s.get("front_time", s.get("anchor", s["start"] + 6) + 0.35)
        t1 = min(max(t1, t0 + 4), dur)
        # start frame (front: question + uncircled choices)
        _grab(video, start_t, frames / f"q{q:03d}_start.jpg")
        official = old_answers.get(q, {}).get("answer_official")
        # end frame = the reveal frame (max red in answer region) -> the red circle is drawn here.
        # M5 title slides are filtered inside find_circle so end-of-block questions
        # do not accidentally copy the next video's title card.
        res = find_circle(FFMPEG, str(video), t0, t1, cfg["mondai"], SCAN)
        if res.get("frame"):
            shutil.copyfile(res["frame"], frames / f"q{q:03d}_end.jpg")
        entry = {"q": q, "red_total": res["red_total"], "end_time": res["time"]}
        if official in (1, 2, 3):
            entry["answer_official"] = official
        elif key == "m5" and res.get("answer") in (1, 2, 3):
            entry["answer_official"] = res["answer"]
        answers.append(entry)
        if q % 20 == 0 or q <= 3:
            print(f"  q{q}: end_time={res['time']} red={res['red_total']}")
        answers_path.write_text(json.dumps(answers, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{key}: saved {len(answers)} start+end frames")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "m4")
