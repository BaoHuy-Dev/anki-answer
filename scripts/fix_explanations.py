"""For questions where the red-circle official answer differs from the audio-AI answer,
set answer=official and regenerate the Vietnamese explanation for the official answer.

Run: python scripts/fix_explanations.py m4   |   python scripts/fix_explanations.py m5
"""
from __future__ import annotations

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
SYS = """Bạn là giáo viên luyện thi nghe JLPT N3. Mỗi mục có câu dẫn + 3 lựa chọn và ĐÁP ÁN ĐÚNG đã xác minh (theo đáp án chính thức khoanh đỏ trong video). Hãy viết lại GIẢI THÍCH tiếng Việt ngắn gọn theo đáp án đúng đó: vì sao đáp án đúng phù hợp, các lựa chọn còn lại sai/không tự nhiên.
Trả về DUY NHẤT một JSON array, mỗi phần tử {"id":<id>,"explanation":"..."} theo đúng thứ tự."""


def run(key: str) -> None:
    out = CFG[key]
    items = {x["q"]: x for x in json.load(open(out / "items.json", encoding="utf-8"))}
    ans = {a["q"]: a.get("answer_official", 0) for a in json.load(open(out / "answers.json", encoding="utf-8"))}
    prompt_key = "situation" if key == "m4" else "prompt"
    todo = []
    for q, x in items.items():
        off = ans.get(q, 0)
        if off in (1, 2, 3) and off != x.get("answer"):
            todo.append(q)
    print(f"{key}: {len(todo)} câu cần viết lại giải thích theo khoanh đỏ: {todo}")
    B = 5
    for i in range(0, len(todo), B):
        batch = todo[i:i + B]
        payload = [{"id": q, "prompt": items[q].get(prompt_key), "options": items[q].get("options"),
                    "correct_answer": ans[q]} for q in batch]
        arr = None
        for m in MODELS:
            try:
                arr = _parse_arr(gemini_json(SYS, json.dumps(payload, ensure_ascii=False), model=m)); break
            except Exception as e:  # noqa: BLE001
                err = str(e)
        if arr is None:
            print(f"  batch {batch} ERROR {err[:90]}"); continue
        got = {str(o.get("id")): o for o in arr if isinstance(o, dict)}
        for q in batch:
            o = got.get(str(q))
            items[q]["answer"] = ans[q]
            if o and o.get("explanation"):
                items[q]["explanation"] = o["explanation"]
            items[q]["answer_corrected_by_circle"] = True
        out_items = list(items.values())
        (out / "items.json").write_text(json.dumps(out_items, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  [{min(i+B,len(todo))}/{len(todo)}] {batch}")
        time.sleep(2)
    print(f"{key}: done")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "m4")
