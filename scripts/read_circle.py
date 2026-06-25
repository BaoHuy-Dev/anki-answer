"""Read the red-circled official answer from each saved end-frame via Gemini vision.
Fills answer_official into output/<deck>/answers.json (resumable).

Run: python scripts/read_circle.py m4   |   python scripts/read_circle.py m5
"""
from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.grammar_group import gemini_json  # noqa: E402
from scripts.fix_corrections import _parse_arr  # noqa: E402

CFG = {"m5": ROOT / "output" / "listening", "m4": ROOT / "output" / "listening_m4"}
MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
BATCH = 4
SYS = """Mỗi ảnh là slide đáp án phần nghe JLPT N3 (Minchan). Trong mỗi ảnh, số của ĐÁP ÁN ĐÚNG được KHOANH TRÒN MÀU ĐỎ (vòng đỏ quanh số 1, 2 hoặc 3).
Với mỗi ảnh, xác định số nào (1/2/3) bị khoanh đỏ. Trả về DUY NHẤT một JSON array các số nguyên theo ĐÚNG THỨ TỰ các ảnh, vd [3,1,2,2]. Nếu một ảnh không thấy vòng đỏ, trả 0 cho ảnh đó."""


def _url(p: Path) -> str:
    return f"data:image/jpeg;base64,{base64.b64encode(p.read_bytes()).decode()}"


def _to_int(v) -> int:
    if isinstance(v, int):
        return v
    if isinstance(v, dict):
        for k in ("answer", "value", "number"):
            if k in v:
                v = v[k]; break
    s = str(v)
    return int(s) if s.strip().lstrip("-").isdigit() else 0


def run(key: str) -> None:
    out = CFG[key]
    frames = out / "frames"
    answers = {a["q"]: a for a in json.load(open(out / "answers.json", encoding="utf-8"))}
    qs = [q for q in sorted(answers) if (frames / f"q{q:03d}_end.jpg").exists()
          and "answer_official" not in answers[q]]
    print(f"{key}: đọc {len(qs)} ảnh khoanh đỏ")
    for i in range(0, len(qs), BATCH):
        batch = qs[i:i + BATCH]
        imgs = [_url(frames / f"q{q:03d}_end.jpg") for q in batch]
        arr = None
        for m in MODELS:
            try:
                arr = _parse_arr(gemini_json(SYS, f"{len(batch)} ảnh. Trả JSON array {len(batch)} số.",
                                             images=imgs, model=m)); break
            except Exception as e:  # noqa: BLE001
                err = str(e)
        if arr is None:
            print(f"  batch {batch} ERROR {err[:90]}"); continue
        for j, q in enumerate(batch):
            answers[q]["answer_official"] = _to_int(arr[j]) if j < len(arr) else 0
        (out / "answers.json").write_text(json.dumps(list(answers.values()), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  [{min(i+BATCH,len(qs))}/{len(qs)}] {[(q, answers[q]['answer_official']) for q in batch]}")
        time.sleep(2)
    got = sum(1 for a in answers.values() if a.get("answer_official"))
    print(f"{key} done: đọc được {got}/{len(answers)}")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "m4")
