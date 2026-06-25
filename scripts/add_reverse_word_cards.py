# -*- coding: utf-8 -*-
"""Bổ sung thẻ ĐẢO CHIỀU theo từng từ cho deck 'Phương pháp đục lỗ JLPT N3'.

Mặt trước = 1 từ · Mặt sau = nghĩa + dạng (phân loại).
  - Dạng 3: từng từ chỉ thị (これ, この, ここ, こちら, こう, こんな, このような…)
  - Dạng 2: từng đuôi/mẫu (使役形, 受身形, 使役受身形, てあげる, てもらう, てくれる)
Dạng 1 đã có sẵn thẻ "từ → nhóm + nghĩa" nên không lặp lại.

Run:
  python scripts/add_reverse_word_cards.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from anki_ocr.anki_connect import AnkiConnectClient  # noqa: E402

client = AnkiConnectClient()
MODEL = "Cơ bản"
F_FRONT, F_BACK = "Mặt trước", "Mặt sau"
TAGS = ["phuong-phap-duc-lo-n3", "dao-chieu"]

PARENT = "Phương pháp đục lỗ JLPT N3"
D2 = f"{PARENT}::Dạng 2 - Sai khiến, bị động, cho nhận"
D3 = f"{PARENT}::Dạng 3 - Từ chỉ thị (こそあど)"

notes: list[tuple[str, str, str]] = []


def front(word: str) -> str:
    return (f"<div style='font-size:2em'><b>{word}</b></div>"
            "<div style='color:#888'>→ Nghĩa & dạng?</div>")


def add(deck: str, word: str, back: str) -> None:
    notes.append((deck, front(word), back))


# ───────── DẠNG 3 – TỪNG TỪ CHỈ THỊ (こ / そ / あ / ど) ─────────
BO = {
    "こ": "こ (gần người nói)",
    "そ": "そ (gần người nghe / đã nhắc tới)",
    "あ": "あ (xa cả hai / ký ức chung)",
    "ど": "ど (nghi vấn)",
}
# (word, bộ, loại, nghĩa)
demo = [
    ("これ", "こ", "Đồ vật", "cái này"),
    ("それ", "そ", "Đồ vật", "cái đó"),
    ("あれ", "あ", "Đồ vật", "cái kia"),
    ("どれ", "ど", "Đồ vật", "cái nào"),
    ("この", "こ", "Đi với danh từ", "… này"),
    ("その", "そ", "Đi với danh từ", "… đó"),
    ("あの", "あ", "Đi với danh từ", "… kia"),
    ("どの", "ど", "Đi với danh từ", "… nào"),
    ("ここ", "こ", "Nơi chốn", "chỗ này, ở đây"),
    ("そこ", "そ", "Nơi chốn", "chỗ đó, ở đó"),
    ("あそこ", "あ", "Nơi chốn", "chỗ kia, đằng kia"),
    ("どこ", "ど", "Nơi chốn", "chỗ nào, ở đâu"),
    ("こちら", "こ", "Phương hướng / lịch sự", "phía này; vị này (lịch sự)"),
    ("そちら", "そ", "Phương hướng / lịch sự", "phía đó; vị đó"),
    ("あちら", "あ", "Phương hướng / lịch sự", "phía kia; vị kia"),
    ("どちら", "ど", "Phương hướng / lịch sự", "phía nào; vị nào; cái nào (lịch sự)"),
    ("こう", "こ", "Cách thức", "như thế này"),
    ("そう", "そ", "Cách thức", "như thế (đó)"),
    ("ああ", "あ", "Cách thức", "như thế kia"),
    ("どう", "ど", "Cách thức", "như thế nào"),
    ("こんな", "こ", "Kiểu loại", "… thế này (loại như này)"),
    ("そんな", "そ", "Kiểu loại", "… thế đó (loại như đó)"),
    ("あんな", "あ", "Kiểu loại", "… thế kia (loại như kia)"),
    ("どんな", "ど", "Kiểu loại", "… thế nào (loại như nào)"),
    ("このような", "こ", "Trang trọng (= こんな)", "… như thế này"),
    ("そのような", "そ", "Trang trọng (= そんな)", "… như thế đó"),
    ("あのような", "あ", "Trang trọng (= あんな)", "… như thế kia"),
    ("どのような", "ど", "Trang trọng (= どんな)", "… như thế nào"),
]
for word, bo, loai, mean in demo:
    add(D3, word,
        f"<b>{mean}</b><br><i>Loại: {loai} · Bộ {BO[bo]}</i>")

# ───────── DẠNG 2 – TỪNG ĐUÔI / MẪU ─────────
pat = [
    ("V使役形<br><span style='color:#888'>(~せる／させる)</span>",
     "N1 <b>bắt / cho phép</b> N2 làm gì đó.", "Mẫu Sai khiến (N1 は N2 に／を …)"),
    ("V受身形<br><span style='color:#888'>(~れる／られる)</span>",
     "N1 <b>bị / được</b> N2 tác động.", "Mẫu Bị động (N1 は N2 に …)"),
    ("V使役受身形<br><span style='color:#888'>(~せられる／させられる)</span>",
     "N1 <b>bị N2 bắt</b> làm gì đó (miễn cưỡng).", "Mẫu Sai khiến bị động (N1 は N2 に …)"),
    ("V<b>てあげる</b>",
     "N1 <b>làm gì đó CHO</b> N2 (cho đi).", "Mẫu Cho nhận"),
    ("V<b>てもらう</b>",
     "N1 <b>ĐƯỢC</b> N2 làm gì cho (nhận ơn; chủ ngữ = người nhận).", "Mẫu Cho nhận"),
    ("V<b>てくれる</b>",
     "Người khác <b>làm gì đó CHO mình</b> / phía mình.", "Mẫu Cho nhận"),
]
for form, mean, dang in pat:
    add(D2, form, f"{mean}<br><i>Dạng: {dang}</i>")


def main() -> None:
    out = io.StringIO()
    payload = [{
        "deckName": d,
        "modelName": MODEL,
        "fields": {F_FRONT: f, F_BACK: b},
        "tags": TAGS,
        "options": {"allowDuplicate": False, "duplicateScope": "deck"},
    } for (d, f, b) in notes]
    res = client.invoke("addNotes", notes=payload)
    ok = sum(1 for r in res if r)
    by_deck: dict[str, int] = {}
    for (d, _, _), r in zip(notes, res):
        if r:
            by_deck[d] = by_deck.get(d, 0) + 1
    out.write(f"# Thêm thẻ đảo chiều (từng từ → nghĩa & dạng)\n\n")
    out.write(f"Định tạo: {len(notes)} | thành công: {ok} | "
              f"bỏ qua (trùng): {len(notes) - ok}\n\n")
    for d in (D2, D3):
        out.write(f"- {d}: +{by_deck.get(d, 0)} thẻ\n")
    rep = ROOT / "output" / "duc_lo_reverse_cards.report.md"
    rep.write_text(out.getvalue(), encoding="utf-8")
    print(out.getvalue())


if __name__ == "__main__":
    main()
