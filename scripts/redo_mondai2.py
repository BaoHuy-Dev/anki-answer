"""Re-explain ALL of `bunpou dokkai mondai 2` in exam trick (mẹo) style,
using the user's corrected order where provided, OCR-ing image-only cards.

  detect  -> output/grammar/m2_redo.json     (read-only)
  backup  -> output/grammar/m2_back_backup.json
  regen   -> fills "new" in m2_redo.json      (Gemini trick style, resumable)
  apply   -> rewrite Back: trick block on top + cleaned old detail below (+tags)

Run: python scripts/redo_mondai2.py <stage> [--yes]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from anki_ocr.anki_connect import AnkiConnectClient  # noqa: E402
from anki_ocr.ocr import strip_html  # noqa: E402
from scripts.grammar_group import gemini_json, OUT_DIR  # noqa: E402
from scripts.fix_corrections import (  # noqa: E402
    _front_question, _front_options, _image_data_url, _parse_arr, _esc, _esc_ml,
)

client = AnkiConnectClient()
ROOT_DECK = "bunpou dokkai mondai 2"
CIRCLED = "①②③④⑤⑥⑦⑧⑨"
REDO_PATH = OUT_DIR / "m2_redo.json"
BACKUP_PATH = OUT_DIR / "m2_back_backup.json"
WS = re.compile(r"\s+")


def _seq(s: str) -> list[int]:
    return [CIRCLED.index(ch) + 1 for ch in s if ch in CIRCLED]


def _trailing_order(back: str) -> list[int] | None:
    for pm in re.findall(r"<p>([\d\s]+)</p>", back):
        d = [int(x) for x in re.findall(r"[1-4]", pm)]
        if len(d) >= 3:
            return d
    plain = re.sub(r"&nbsp;|<[^>]+>", " ", back)
    d = [int(x) for x in re.findall(r"[1-4]", plain)]
    if "anki-ocr-answer" not in back and "Dap an" not in back and 3 <= len(d) <= 4 and len(plain.strip()) < 15:
        return d
    return None


def _ocr_value(back: str, label: str) -> str:
    m = re.search(rf"<p><b>{re.escape(label)}:</b>\s*(.*?)</p>", back or "", re.DOTALL | re.IGNORECASE)
    return WS.sub(" ", strip_html(m.group(1))).strip() if m else ""


def _gemini_order(back: str) -> list[int] | None:
    m = re.search(r"Thứ tự đúng:</b>\s*(.*?)</p>", back or "", re.DOTALL | re.IGNORECASE)
    if not m:
        return None
    raw = m.group(1)
    if "wait" in raw.lower() or "correction" in raw.lower():  # messy self-correction -> untrusted
        return None
    s = _seq(raw)
    return s if len(s) >= 3 else None


def _front_image(front: str) -> str:
    m = re.search(r'<img src="([^"]+)"', front or "")
    return m.group(1) if m else ""


def stage_detect() -> None:
    ids = client.invoke("findNotes", query=f'deck:"{ROOT_DECK}::*"')
    recs = []
    for info in client.notes_info(ids):
        back = info["fields"]["Back"]["value"]
        front = info["fields"]["Front"]["value"]
        q = _front_question(front)
        opts = _front_options(front)
        user = _trailing_order(back)
        gem = _gemini_order(back)
        old_answer = _ocr_value(back, "Đáp án")
        order = user or gem
        recs.append({
            "note_id": info["noteId"],
            "question": q,
            "fragments": opts,
            "image": _front_image(front),
            "needs_ocr": not bool(opts and q),
            "user_order": user,
            "gemini_order": gem,
            "order": order,
            "old_answer": old_answer,
            "corrected": bool(user and (gem != user)),
        })
    REDO_PATH.write_text(json.dumps(recs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"detect: {len(recs)} thẻ | có order: {sum(1 for r in recs if r['order'])} | "
          f"cần OCR: {sum(1 for r in recs if r['needs_ocr'])} | đã sửa: {sum(1 for r in recs if r['corrected'])}")


def stage_backup() -> None:
    recs = json.load(open(REDO_PATH, encoding="utf-8"))
    backup = {}
    if BACKUP_PATH.exists():
        backup = json.load(open(BACKUP_PATH, encoding="utf-8"))
    for info in client.notes_info([r["note_id"] for r in recs]):
        backup[str(info["noteId"])] = info["fields"]["Back"]["value"]
    BACKUP_PATH.write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"backup: {len(backup)} thẻ -> {BACKUP_PATH.name}")


TRICK_SYSTEM = """Bạn là giáo viên luyện thi JLPT N3, chuyên câu sắp xếp từ (hái sao ★).
Giải thích theo KIỂU MẸO ĐI THI: nhìn là khoanh được ngay, đơn giản dễ hiểu, tập trung quy tắc nối mảnh ghép.
Mẹo gồm: tìm chữ cố định ngay trước/sau chỗ trống làm "mỏ neo" (vd: trước 「を」「が」「は」 là danh từ; sau 「の」 là danh từ; 「について」「によって」「に対して」 đứng sau danh từ; 「ば〜ほど」「たり〜たり」 đi theo cặp; 「て」+「いる/くる/おく」...), chỉ ra cặp mảnh BẮT BUỘC đi liền nhau và vì sao, rồi suy ra thứ tự rồi xác định mảnh ở vị trí ★.
Nếu có "verified_order" thì TIN TUYỆT ĐỐI vào nó (đó là đáp án đúng người dùng đã xác minh). Nếu không có verified_order, dùng "existing_order" làm đáp án. Nếu thiếu câu hỏi/mảnh ghép, hãy đọc từ ảnh đính kèm.
Vị trí ★ là chỗ trống thứ tương ứng trong câu; mảnh ở ★ là đáp án cần khoanh.
Trả về DUY NHẤT một JSON array, mỗi phần tử:
{"id":<id>,
 "question":"<câu đề có chỗ trống ___ và ★, đọc từ ảnh nếu cần>",
 "fragments":["① ...","② ...","③ ...","④ ..."],
 "completed_sentence":"<câu hoàn chỉnh, KHÔNG còn ___ hay ★>",
 "correct_order":"④→①→③→②",
 "star_answer":"<số + chữ Nhật của mảnh ở ★, vd ③ 今でも>",
 "tip":"<mẹo khoanh nhanh, 2-4 dòng, MỖI dòng bắt đầu bằng '• ', xuống dòng thật giữa các dòng>",
 "grammar_point":"<nhãn ngữ pháp dạng từ điển, vd 〜について, Vば〜ほど>"}
Chỉ xuất JSON."""


def stage_regen() -> None:
    recs = json.load(open(REDO_PATH, encoding="utf-8"))
    by_id = {r["note_id"]: r for r in recs}
    text_items = [r for r in recs if "new" not in r and not r["needs_ocr"]]
    img_items = [r for r in recs if "new" not in r and r["needs_ocr"]]

    def payload(r):
        p = {"id": r["note_id"], "question": r["question"], "fragments": r["fragments"]}
        if r["user_order"]:
            p["verified_order"] = r["user_order"]
        elif r["order"]:
            p["existing_order"] = r["order"]
        return p

    print(f"regen: text={len(text_items)}, image={len(img_items)}")
    B = 6
    for i in range(0, len(text_items), B):
        batch = text_items[i:i + B]
        arr = _parse_arr(gemini_json(TRICK_SYSTEM, json.dumps([payload(r) for r in batch], ensure_ascii=False)))
        got = {str(x.get("id")): x for x in arr if isinstance(x, dict)}
        for r in batch:
            if str(r["note_id"]) in got:
                by_id[r["note_id"]]["new"] = got[str(r["note_id"])]
        REDO_PATH.write_text(json.dumps(list(by_id.values()), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  text [{min(i + B, len(text_items))}/{len(text_items)}]")

    for j, r in enumerate(img_items, 1):
        url = _image_data_url(r["image"]) if r["image"] else None
        arr = _parse_arr(gemini_json(TRICK_SYSTEM, json.dumps([payload(r)], ensure_ascii=False),
                                      images=[url] if url else None))
        if arr and isinstance(arr[0], dict):
            by_id[r["note_id"]]["new"] = arr[0]
        REDO_PATH.write_text(json.dumps(list(by_id.values()), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  image [{j}/{len(img_items)}] note {r['note_id']}")


# strip redundant/old lines from the base so the trick block is authoritative
STRIP_PATTERNS = [
    re.compile(r'\s*<div class="anki-correction".*?</div>\s*', re.DOTALL),
    re.compile(r'\s*<div class="anki-trick".*?</div>\s*', re.DOTALL),
    re.compile(r"\s*<p><b>Đáp án:</b>.*?</p>", re.DOTALL | re.IGNORECASE),
    re.compile(r"\s*<p><b>Thứ tự đúng:</b>.*?</p>", re.DOTALL | re.IGNORECASE),
    re.compile(r"\s*<p><b>Câu hoàn chỉnh:</b>.*?</p>", re.DOTALL | re.IGNORECASE),
    re.compile(r"\s*<p>\s*[1-4][\d\s]*</p>", re.DOTALL),
]


def _clean_base(back: str) -> str:
    out = back
    for pat in STRIP_PATTERNS:
        out = pat.sub("", out)
    return out.strip()


def render_trick(r: dict) -> str:
    n = r["new"]
    parts = ['<div class="anki-trick" style="border:2px solid #2471a3;background:#eef6fb;'
             'padding:10px;border-radius:8px;margin-bottom:10px">']
    if r.get("corrected") and r.get("old_answer"):
        parts.append(f'<b style="color:#c0392b">⚠ ĐÃ SỬA:</b> đáp án cũ <s>{_esc(r["old_answer"])}</s> '
                     f'→ đúng: <b style="color:#1e8449">{_esc(n.get("star_answer",""))}</b><br>')
    parts.append(f'<b>💡 Đáp án ★:</b> <b style="color:#1e8449">{_esc(n.get("star_answer",""))}</b><br>')
    if n.get("correct_order"):
        parts.append(f'<b>Thứ tự đúng:</b> {_esc(n["correct_order"])}<br>')
    if n.get("completed_sentence"):
        parts.append(f'<b>Câu hoàn chỉnh:</b> {_esc(n["completed_sentence"])}<br>')
    parts.append(f'<b>Mẹo khoanh nhanh:</b><br>{_esc_ml(n.get("tip",""))}<br>')
    parts.append(f'<b>Ngữ pháp:</b> {_esc(n.get("grammar_point",""))}')
    parts.append("</div>")
    return "".join(parts)


def stage_apply(do_it: bool) -> None:
    recs = json.load(open(REDO_PATH, encoding="utf-8"))
    backup = json.load(open(BACKUP_PATH, encoding="utf-8")) if BACKUP_PATH.exists() else {}
    done = skipped = 0
    for r in recs:
        if "new" not in r:
            skipped += 1
            continue
        nid = r["note_id"]
        orig = backup.get(str(nid)) or client.notes_info([nid])[0]["fields"]["Back"]["value"]
        new_back = render_trick(r) + "\n" + _clean_base(orig)
        if not do_it:
            done += 1
            continue
        client.update_note_fields(nid, {"Back": new_back})
        tags = "meo-thi da-sua" if r.get("corrected") else "meo-thi"
        client.invoke("addTags", notes=[nid], tags=tags)
        done += 1
    msg = "ĐÃ ÁP DỤNG" if do_it else "DRY-RUN (thêm --yes để ghi)"
    print(f"{msg}: {done} thẻ, bỏ qua {skipped} (chưa regen).")


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "detect"
    do_it = "--yes" in sys.argv
    fn = {"detect": stage_detect, "backup": stage_backup, "regen": stage_regen,
          "apply": lambda: stage_apply(do_it)}.get(stage)
    if fn:
        fn()
    else:
        print(f"Unknown stage: {stage}")
