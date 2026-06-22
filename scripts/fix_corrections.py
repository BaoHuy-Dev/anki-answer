"""Detect user-corrected bunpou cards, regenerate the explanation for the
user's correct answer, and rewrite the Back field with a marked "ĐÃ SỬA" block.

Stages:
  detect   -> output/grammar/corrections.json        (read-only, detection)
  backup   -> output/grammar/back_backup.json         (save original Back fields)
  regen    -> fills "new_*" fields in corrections.json (Gemini, resumable)
  apply    -> writes new Back + tag 'da-sua' to Anki   (needs --yes)

Run:
  python scripts/fix_corrections.py detect
  python scripts/fix_corrections.py backup
  python scripts/fix_corrections.py regen
  python scripts/fix_corrections.py apply --yes
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from anki_ocr.anki_connect import AnkiConnectClient  # noqa: E402
from anki_ocr.ocr import strip_html  # noqa: E402
from scripts.grammar_group import gemini_json, OUT_DIR, DECK_ROOTS  # noqa: E402

client = AnkiConnectClient()
WS = re.compile(r"\s+")
CIRCLED = "①②③④⑤⑥⑦⑧⑨"
CORR_PATH = OUT_DIR / "corrections.json"
BACKUP_PATH = OUT_DIR / "back_backup.json"


def _clean(t: str) -> str:
    return WS.sub(" ", strip_html(t or "")).strip()


def _num(ch: str) -> int | None:
    if ch in CIRCLED:
        return CIRCLED.index(ch) + 1
    if ch.isdigit():
        return int(ch)
    return None


def _front_question(front_html: str) -> str:
    m = re.search(r"<b>OCR câu hỏi:</b>\s*(.*?)</p>", front_html or "", re.DOTALL | re.IGNORECASE)
    return _clean(m.group(1)) if m else ""


def _front_options(front_html: str) -> list[str]:
    m = re.search(r"<b>OCR lựa chọn:</b></p>\s*<ul>(.*?)</ul>", front_html or "", re.DOTALL | re.IGNORECASE)
    if not m:
        return []
    return [_clean(li) for li in re.findall(r"<li>(.*?)</li>", m.group(1), re.DOTALL | re.IGNORECASE)]


def _front_options_map(front_options: list[str]) -> dict[int, str]:
    """Map an option number (1-4) to its text, parsing the leading label."""
    out: dict[int, str] = {}
    for opt in front_options:
        mm = re.match(r"\s*([①-⑨]|\d)\s*[.、)]?\s*(.*)", opt)
        if mm:
            n = _num(mm.group(1))
            if n and mm.group(2).strip():
                out[n] = mm.group(2).strip()
    return out


def _front_image(front_html: str) -> str:
    m = re.search(r'<img src="([^"]+)"', front_html or "")
    return m.group(1) if m else ""


# ---------- mondai 1 ----------

M1_CONF = re.compile(r"\(do tin cay:[^)]*\)(.*?)</i>", re.IGNORECASE | re.DOTALL)
M1_LEAD = re.compile(r"Dap an dung:</b>\s*([①-⑨]|\d)\s*[-.、]?\s*(.*?)\s*<i>", re.IGNORECASE | re.DOTALL)


def _m1_options(back_html: str) -> dict[int, str]:
    out: dict[int, str] = {}
    om = re.search(r"<b>Phan tich tung dap an:</b><ol>(.*?)</ol>", back_html or "", re.DOTALL | re.IGNORECASE)
    if not om:
        return out
    for li in re.findall(r"<li>(.*?)</li>", om.group(1), re.DOTALL | re.IGNORECASE):
        bm = re.search(r"<b>\s*(\d)\.?\s*(.*?)</b>", li, re.DOTALL | re.IGNORECASE)
        if bm:
            out[int(bm.group(1))] = _clean(bm.group(2))
    return out


def detect_m1(note: dict) -> dict | None:
    back = note["fields"]["Back"]["value"]
    front = note["fields"]["Front"]["value"]
    conf = M1_CONF.search(back)
    if not conf:
        return None
    rest = re.sub(r"<[^>]+>", " ", conf.group(1))
    dm = re.search(r"[1-4]", rest)
    if not dm:
        return None
    corr_num = int(dm.group(0))
    lead = M1_LEAD.search(back)
    gem_num = _num(lead.group(1)) if lead else None
    gem_text = _clean(lead.group(2)) if lead else ""
    opts = _m1_options(back)
    front_opts = _front_options(front)
    fmap = _front_options_map(front_opts)
    if not opts:
        opts = fmap
    return {
        "note_id": note["noteId"],
        "type": "m1",
        "question": _front_question(front),
        "options": opts,
        "front_options": front_opts,
        "gemini_num": gem_num,
        "gemini_text": gem_text or opts.get(gem_num, ""),
        "corrected_num": corr_num,
        "corrected_text": opts.get(corr_num) or fmap.get(corr_num, ""),
        "hint": rest.strip(),
        "image": _front_image(front),
    }


# ---------- mondai 2 ----------

M2_ORDER = re.compile(r"Thứ tự đúng:</b>\s*(.*?)</p>", re.IGNORECASE | re.DOTALL)


def _seq(s: str) -> list[int]:
    return [CIRCLED.index(ch) + 1 for ch in s if ch in CIRCLED]


def detect_m2(note: dict) -> dict | None:
    back = note["fields"]["Back"]["value"]
    front = note["fields"]["Front"]["value"]
    user = None
    for pm in re.findall(r"<p>([\d\s]+)</p>", back):
        digs = [int(x) for x in re.findall(r"[1-4]", pm)]
        if len(digs) >= 3:
            user = digs
    if user is None:
        plain = re.sub(r"&nbsp;|<[^>]+>", " ", back)
        digs = [int(x) for x in re.findall(r"[1-4]", plain)]
        if "anki-ocr-answer" not in back and "Dap an" not in back and 3 <= len(digs) <= 4 and len(plain.strip()) < 15:
            user = digs
    if user is None:
        return None
    gm = M2_ORDER.search(back)
    gem_order = _seq(gm.group(1)) if gm else None
    fopts = _front_options(front)
    return {
        "note_id": note["noteId"],
        "type": "m2",
        "question": _front_question(front),
        "front_options": fopts,
        "gemini_order": gem_order,
        "corrected_order": user,
        "image": _front_image(front),
        "needs_ocr": not bool(fopts),
    }


def stage_detect() -> None:
    records = []
    for idx, root in DECK_ROOTS.items():
        ids = client.invoke("findNotes", query=f'deck:"{root}::*"')
        for note in client.notes_info(ids):
            rec = detect_m1(note) if idx == 1 else detect_m2(note)
            if rec:
                rec["deck_idx"] = idx
                records.append(rec)
    CORR_PATH.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    m1 = [r for r in records if r["type"] == "m1"]
    m2 = [r for r in records if r["type"] == "m2"]
    print(f"Detected {len(records)} corrected cards: m1={len(m1)}, m2={len(m2)}")
    print(f"  m1 missing option text: {sum(1 for r in m1 if not r['corrected_text'])}")
    print(f"  m2 needs OCR (no front options): {sum(1 for r in m2 if r['needs_ocr'])}")


# ============================ backup ============================

def stage_backup() -> None:
    recs = json.load(open(CORR_PATH, encoding="utf-8"))
    ids = [r["note_id"] for r in recs]
    backup = {}
    for note in client.notes_info(ids):
        backup[str(note["noteId"])] = {
            "Back": note["fields"]["Back"]["value"],
            "Front": note["fields"]["Front"]["value"],
            "tags": note.get("tags", []),
        }
    BACKUP_PATH.write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Backed up {len(backup)} notes -> {BACKUP_PATH.name}")


# ============================ regen (Gemini) ============================

M1_SYSTEM = """Bạn là giáo viên ngữ pháp tiếng Nhật JLPT N3.
Mỗi mục gồm: câu hỏi điền vào chỗ trống, các lựa chọn, và SỐ ĐÁP ÁN ĐÚNG đã được người dùng xác minh.
Đáp án AI trước đó SAI; hãy TIN TUYỆT ĐỐI vào số đáp án đúng được cung cấp.
Trả về DUY NHẤT một JSON array, mỗi phần tử:
{"id": <id>,
 "answer_text": "<chữ Nhật của lựa chọn đúng>",
 "explanation": "<2-4 câu tiếng Việt: vì sao đáp án đúng phù hợp ngữ cảnh, và vì sao các lựa chọn khác sai>",
 "grammar_point": "<nhãn ngữ pháp dạng từ điển, vd 〜って, 〜ばかり, 〜といい, Nからの; nếu chỉ là từ vựng/phó từ dùng dạng 語:<từ>>",
 "grammar_note": "<1 câu tiếng Việt nêu cách dùng cấu trúc/từ đó>"}
Giữ thuật ngữ tiếng Nhật bằng chữ Nhật. Chỉ xuất JSON."""

M2_SYSTEM = """Bạn là giáo viên ngữ pháp tiếng Nhật JLPT N3, dạng câu sắp xếp từ (hái sao ★).
Mỗi mục gồm: câu hỏi có các chỗ trống và dấu ★, 4 mảnh ghép (①②③④), và THỨ TỰ ĐÚNG đã được người dùng xác minh (danh sách số theo thứ tự điền vào các chỗ trống).
Đáp án AI trước đó SAI; hãy TIN TUYỆT ĐỐI vào thứ tự đúng được cung cấp.
Nếu thiếu nội dung câu/mảnh ghép, hãy đọc từ ảnh đính kèm.
Dấu ★ là chỗ trống cần tìm đáp án; mảnh ở vị trí ★ chính là đáp án.
Trả về DUY NHẤT một JSON array, mỗi phần tử:
{"id": <id>,
 "completed_sentence": "<câu hoàn chỉnh ghép các mảnh theo đúng thứ tự, không còn chỗ trống/★>",
 "star_answer": "<mảnh ghép nằm ở vị trí ★>",
 "explanation": "<tiếng Việt: cấu trúc câu và vì sao thứ tự này đúng>",
 "grammar_point": "<nhãn ngữ pháp dạng từ điển, vd 〜たことがある, 〜ば〜ほど, 〜か何か>",
 "grammar_note": "<1 câu tiếng Việt nêu cách dùng>"}
Chỉ xuất JSON."""

MIME = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png", "gif": "image/gif", "webp": "image/webp"}


def _image_data_url(filename: str) -> str | None:
    try:
        b64 = client.retrieve_media_file(filename)
    except Exception:
        return None
    if not b64:
        return None
    ext = filename.rsplit(".", 1)[-1].lower()
    return f"data:{MIME.get(ext, 'image/png')};base64,{b64}"


def _parse_arr(text: str) -> list:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", t).strip()
    try:
        v = json.loads(t, strict=False)
        return v if isinstance(v, list) else [v]
    except json.JSONDecodeError:
        s, e = t.find("["), t.rfind("]")
        if s != -1 and e > s:
            return json.loads(t[s:e + 1], strict=False)
    return []


def stage_regen() -> None:
    recs = json.load(open(CORR_PATH, encoding="utf-8"))
    by_id = {r["note_id"]: r for r in recs}

    # --- mondai 1: batch ---
    m1 = [r for r in recs if r["type"] == "m1" and "new" not in r]
    print(f"m1 to regen: {len(m1)}")
    B = 6
    for i in range(0, len(m1), B):
        batch = m1[i:i + B]
        items = [{
            "id": r["note_id"],
            "question": r["question"],
            "options": [f"{n}. {t}" for n, t in sorted(r["options"].items(), key=lambda kv: int(kv[0]))],
            "correct_number": r["corrected_num"],
            "user_hint": r["hint"],
        } for r in batch]
        arr = _parse_arr(gemini_json(M1_SYSTEM, json.dumps(items, ensure_ascii=False)))
        got = {str(x.get("id")): x for x in arr if isinstance(x, dict)}
        for r in batch:
            x = got.get(str(r["note_id"]))
            if x:
                by_id[r["note_id"]]["new"] = x
        CORR_PATH.write_text(json.dumps(list(by_id.values()), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  m1 [{min(i + B, len(m1))}/{len(m1)}]")

    # --- mondai 2: per card (image when needed) ---
    m2 = [r for r in recs if r["type"] == "m2" and "new" not in r]
    print(f"m2 to regen: {len(m2)}")
    for j, r in enumerate(m2, 1):
        item = {
            "id": r["note_id"],
            "question": r["question"],
            "fragments": r["front_options"],
            "correct_order": r["corrected_order"],
        }
        images = None
        if r.get("needs_ocr") and r.get("image"):
            url = _image_data_url(r["image"])
            images = [url] if url else None
        arr = _parse_arr(gemini_json(M2_SYSTEM, json.dumps(item, ensure_ascii=False), images=images))
        if arr and isinstance(arr[0], dict):
            by_id[r["note_id"]]["new"] = arr[0]
        CORR_PATH.write_text(json.dumps(list(by_id.values()), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  m2 [{j}/{len(m2)}] note {r['note_id']}")


# ============================ apply ============================

CORR_BLOCK = re.compile(r'\s*<div class="anki-correction".*?</div>\s*', re.DOTALL)


def _esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _esc_ml(s: str) -> str:
    return _esc(s).replace("\r\n", "\n").replace("\n", "<br>")


def render_block_m1(r: dict) -> str:
    n = r["new"]
    gem = f"{r['gemini_num'] or ''} {r['gemini_text']}".strip()
    cor = f"{r['corrected_num']} {n.get('answer_text') or r['corrected_text']}".strip()
    return (
        '<div class="anki-correction" style="border:2px solid #c0392b;background:#fff5f5;'
        'padding:10px;border-radius:8px;margin-bottom:10px">'
        '<b style="color:#c0392b">⚠ ĐÃ SỬA ĐÁP ÁN (theo chỉnh sửa của bạn)</b><br>'
        f'<b>Đáp án Gemini (sai):</b> <s>{_esc(gem)}</s><br>'
        f'<b>Đáp án đúng:</b> <b style="color:#1e8449">{_esc(cor)}</b><br>'
        f'<b>Giải thích:</b> {_esc_ml(n.get("explanation",""))}<br>'
        f'<b>Ngữ pháp:</b> {_esc(n.get("grammar_point",""))} — {_esc_ml(n.get("grammar_note",""))}'
        '</div>'
    )


def render_block_m2(r: dict) -> str:
    n = r["new"]
    gem = " → ".join(CIRCLED[d - 1] for d in (r["gemini_order"] or []))
    cor = " → ".join(CIRCLED[d - 1] for d in (r["corrected_order"] or []))
    parts = [
        '<div class="anki-correction" style="border:2px solid #c0392b;background:#fff5f5;'
        'padding:10px;border-radius:8px;margin-bottom:10px">',
        '<b style="color:#c0392b">⚠ ĐÃ SỬA THỨ TỰ (theo chỉnh sửa của bạn)</b><br>',
    ]
    if gem:
        parts.append(f'<b>Thứ tự Gemini (sai):</b> <s>{_esc(gem)}</s><br>')
    parts.append(f'<b>Thứ tự đúng:</b> <b style="color:#1e8449">{_esc(cor)}</b><br>')
    if n.get("star_answer"):
        parts.append(f'<b>Đáp án ★:</b> <b style="color:#1e8449">{_esc(n["star_answer"])}</b><br>')
    if n.get("completed_sentence"):
        parts.append(f'<b>Câu hoàn chỉnh:</b> {_esc(n["completed_sentence"])}<br>')
    parts.append(f'<b>Giải thích:</b> {_esc_ml(n.get("explanation",""))}<br>')
    parts.append(f'<b>Ngữ pháp:</b> {_esc(n.get("grammar_point",""))} — {_esc_ml(n.get("grammar_note",""))}')
    parts.append('</div>')
    return "".join(parts)


def stage_apply(do_it: bool) -> None:
    recs = json.load(open(CORR_PATH, encoding="utf-8"))
    backup = json.load(open(BACKUP_PATH, encoding="utf-8")) if BACKUP_PATH.exists() else {}
    done = 0
    skipped = 0
    for r in recs:
        if "new" not in r:
            skipped += 1
            continue
        nid = r["note_id"]
        orig_back = backup.get(str(nid), {}).get("Back")
        if orig_back is None:
            orig_back = client.notes_info([nid])[0]["fields"]["Back"]["value"]
        base = CORR_BLOCK.sub("", orig_back)
        block = render_block_m1(r) if r["type"] == "m1" else render_block_m2(r)
        new_back = block + "\n" + base
        if not do_it:
            done += 1
            continue
        client.update_note_fields(nid, {"Back": new_back})
        client.invoke("addTags", notes=[nid], tags="da-sua")
        done += 1
    if do_it:
        print(f"ĐÃ ÁP DỤNG: {done} thẻ cập nhật, {skipped} chưa có lời giải mới (bỏ qua).")
    else:
        print(f"DRY-RUN: sẽ cập nhật {done} thẻ, bỏ qua {skipped}. Thêm --yes để ghi vào Anki.")


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "detect"
    do_it = "--yes" in sys.argv
    if stage == "detect":
        stage_detect()
    elif stage == "backup":
        stage_backup()
    elif stage == "regen":
        stage_regen()
    elif stage == "apply":
        stage_apply(do_it)
    else:
        print(f"Unknown stage: {stage}")
