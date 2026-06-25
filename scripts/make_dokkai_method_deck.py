# -*- coding: utf-8 -*-
"""Tạo deck "Phương pháp đục lỗ JLPT N3" từ nội dung 5 ảnh phương pháp.

Cấu trúc:
  Phương pháp đục lỗ JLPT N3
    ::Dạng 1 - Nối câu (liên từ)
    ::Dạng 2 - Sai khiến, bị động, cho nhận
    ::Dạng 3 - Từ chỉ thị (こそあど)

Thẻ dùng note type "Cơ bản" (Mặt trước / Mặt sau). Mỗi thẻ gắn tag
`phuong-phap-duc-lo-n3`. Chạy nhiều lần an toàn: addNotes bỏ qua thẻ trùng
mặt trước trong cùng deck.

Run:
  python scripts/make_dokkai_method_deck.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from anki_ocr.anki_connect import AnkiConnectClient  # noqa: E402

client = AnkiConnectClient()
MODEL = "Cơ bản"          # fields: Mặt trước / Mặt sau
F_FRONT, F_BACK = "Mặt trước", "Mặt sau"
TAG = "phuong-phap-duc-lo-n3"

PARENT = "Phương pháp đục lỗ JLPT N3"
D1 = f"{PARENT}::Dạng 1 - Nối câu (liên từ)"
D2 = f"{PARENT}::Dạng 2 - Sai khiến, bị động, cho nhận"
D3 = f"{PARENT}::Dạng 3 - Từ chỉ thị (こそあど)"

# (deck, front_html, back_html)
notes: list[tuple[str, str, str]] = []


def add(deck: str, front: str, back: str) -> None:
    notes.append((deck, front, back))


# ───────────────────────── DẠNG 1 – LIÊN TỪ NỐI CÂU ─────────────────────────
# Thẻ tổng quát theo nhóm chức năng
add(D1,
    "<b>Dạng 1 – TH1:</b> Hai vế <span style='color:#c0392b'><b>TRÁI NGƯỢC</b></span> "
    "nhau → dùng những liên từ nào?",
    "でも、ところが、しかし、それでも、けど、が"
    "<br><i>(≈ nhưng, tuy nhiên, dù vậy — vế sau ngược ý vế trước)</i>")
add(D1,
    "<b>Dạng 1 – TH2:</b> Vế sau <span style='color:#27ae60'><b>BỔ SUNG THÔNG TIN</b></span> "
    "cho vế trước → liên từ nào?",
    "そして、それに、また、そのうえ、その上、しかも"
    "<br><i>(≈ và, hơn nữa, thêm vào đó, mà còn)</i>")
add(D1,
    "<b>Dạng 1 – TH3:</b> Vế sau <span style='color:#2980b9'><b>GIẢI THÍCH / LÀ KẾT QUẢ</b></span> "
    "của vế trước → liên từ nào?",
    "それで、だから、そのため、そこで、ですから、したがって"
    "<br><i>(≈ vì vậy, do đó, cho nên, vì thế)</i>")

# Thẻ nhận diện từng liên từ (từ → nhóm + nghĩa) — sát đề thi
TRAINGUOC = "🔴 <b>TRÁI NGƯỢC</b> (vế sau ngược ý)"
BOSUNG = "🟢 <b>BỔ SUNG</b> (thêm thông tin)"
GIAITHICH = "🔵 <b>GIẢI THÍCH / KẾT QUẢ</b>"
conj = [
    ("でも", TRAINGUOC, "nhưng, thế nhưng (đầu câu, thân mật)"),
    ("ところが", TRAINGUOC, "thế mà, ngờ đâu (kết quả trái với dự đoán)"),
    ("しかし", TRAINGUOC, "tuy nhiên, nhưng (trang trọng)"),
    ("それでも", TRAINGUOC, "dù vậy, mặc dù thế"),
    ("けど", TRAINGUOC, "nhưng (khẩu ngữ, thân mật)"),
    ("が", TRAINGUOC, "nhưng (giữa câu, văn viết/lịch sự)"),
    ("そして", BOSUNG, "và, rồi thì (nối tiếp)"),
    ("それに", BOSUNG, "hơn nữa, thêm vào đó"),
    ("また", BOSUNG, "ngoài ra, đồng thời"),
    ("そのうえ", BOSUNG, "hơn thế nữa"),
    ("その上", BOSUNG, "hơn thế nữa (= そのうえ, viết kanji)"),
    ("しかも", BOSUNG, "hơn nữa, mà còn"),
    ("それで", GIAITHICH, "vì thế, thế là (dẫn tới kết quả)"),
    ("だから", GIAITHICH, "vì vậy, cho nên (thân mật)"),
    ("そのため", GIAITHICH, "vì lý do đó, do đó"),
    ("そこで", GIAITHICH, "vì vậy, nhân đó (nên đã làm gì)"),
    ("ですから", GIAITHICH, "vì vậy (lịch sự)"),
    ("したがって", GIAITHICH, "do đó, vì thế (trang trọng, văn viết)"),
]
for w, grp, mean in conj:
    add(D1,
        f"Liên từ <span style='font-size:1.4em'><b>{w}</b></span> thuộc nhóm nào? Nghĩa?",
        f"{grp}<br>{w} = {mean}")

# ──────────── DẠNG 2 – SAI KHIẾN / BỊ ĐỘNG / SK BỊ ĐỘNG / CHO NHẬN ────────────
add(D2,
    "<b>Mẫu Sai khiến</b> (使役形): cấu trúc + ý nghĩa?",
    "<b>N1 は N2 に／を V使役形</b><br>"
    "→ N1 <b>bắt</b> hoặc <b>cho phép</b> N2 làm gì đó.<br>"
    "<i>に: dùng với tha động từ (có を tân ngữ) · を: dùng với tự động từ.</i>")
add(D2,
    "<b>Mẫu Bị động</b> (受身形): cấu trúc + ý nghĩa?",
    "<b>N1 は N2 に V受身形</b><br>"
    "→ N1 <b>bị</b> hoặc <b>được</b> N2 tác động.")
add(D2,
    "<b>Mẫu Sai khiến bị động</b> (使役受身形): cấu trúc + ý nghĩa?",
    "<b>N1 は N2 に V使役受身形</b><br>"
    "→ N1 <b>bị N2 bắt</b> làm gì đó (thường mang nghĩa miễn cưỡng, không muốn).")
add(D2,
    "Mẫu cho nhận: N1 は N2 に V<b>てあげる</b> → nghĩa?",
    "N1 <b>làm gì đó CHO</b> N2.<br><i>(phía mình/người làm ơn → cho người khác)</i>")
add(D2,
    "Mẫu cho nhận: N1 は N2 に V<b>てもらう／てもらいます</b> → nghĩa?",
    "N1 <b>ĐƯỢC</b> N2 làm gì cho.<br><i>(chủ ngữ là người NHẬN ơn — nhờ/được N2 giúp)</i>")
add(D2,
    "Mẫu cho nhận: N1 は N2 に V<b>てくれる／てくれます</b> → nghĩa?",
    "N1 (người khác) <b>làm gì đó CHO mình</b> / phía mình.")
# Thẻ phân biệt – phần hay nhầm
add(D2,
    "Phân biệt <b>使役形</b> (sai khiến) và <b>受身形</b> (bị động) khi gặp trong bài?",
    "• 使役 ~<b>せる/させる</b>: N1 <b>bắt/cho phép</b> N2 làm (N1 chủ động).<br>"
    "• 受身 ~<b>れる/られる</b>: N1 <b>bị</b> N2 tác động (N1 chịu tác động).")
add(D2,
    "Hướng lợi ích của <b>あげる / もらう / くれる</b>?",
    "• <b>あげる</b>: mình → người khác (CHO đi).<br>"
    "• <b>もらう</b>: mình ← người khác (ĐƯỢC nhận; chủ ngữ = người nhận).<br>"
    "• <b>くれる</b>: người khác → mình/phía mình (cho MÌNH).")
add(D2,
    "Cách chia (nhóm 1 / nhóm 2): Sai khiến – Bị động – Sai khiến bị động?",
    "<b>使役 (sai khiến):</b> G1 hàng あ+せる (書く→書か<b>せる</b>) · G2 +させる (食べ<b>させる</b>) · する→させる · 来る→来させる<br>"
    "<b>受身 (bị động):</b> G1 hàng あ+れる (書か<b>れる</b>) · G2 +られる (食べ<b>られる</b>) · する→される · 来る→来られる<br>"
    "<b>使役受身:</b> G1 +せられる/される (書か<b>せられる</b>/書か<b>される</b>) · G2 +させられる (食べ<b>させられる</b>)")

# ───────────────────── DẠNG 3 – TỪ CHỈ THỊ (こそあど) ─────────────────────
# Bảng theo loại (こ / そ / あ / ど)
rows = [
    ("Đồ vật (cái này / đó / kia / nào)", "これ", "それ", "あれ", "どれ"),
    ("Đi với danh từ (… này / đó / kia / nào)", "この", "その", "あの", "どの"),
    ("Nơi chốn (chỗ này / đó / kia / nào)", "ここ", "そこ", "あそこ", "どこ"),
    ("Phương hướng / lịch sự (phía này / đó / kia / nào)", "こちら", "そちら", "あちら", "どちら"),
    ("Cách thức (như thế này / thế / kia / nào)", "こう", "そう", "ああ", "どう"),
    ("Kiểu loại (loại … thế này / thế / kia / nào)", "こんな", "そんな", "あんな", "どんな"),
    ("Trang trọng (… như thế này / thế / kia / nào)", "このような", "そのような", "あのような", "どのような"),
]
for name, ko, so, a, do in rows:
    add(D3,
        f"Từ chỉ thị – <b>{name}</b>: bộ こ / そ / あ / ど?",
        f"こ → <b>{ko}</b> ・ そ → <b>{so}</b> ・ あ → <b>{a}</b> ・ ど → <b>{do}</b>")

# Cách dùng こ / そ / あ (bảng sâu – ảnh 5)
add(D3,
    "<b>Bộ こ (KO – cận đài)</b> dùng khi nào? (bản chất · không gian · tư duy/hội thoại · ví dụ)",
    "<b>Bản chất:</b> Hiện tại & Chủ quan – thuộc phía <b>NGƯỜI NÓI</b> (hoặc tương lai gần sắp tới).<br>"
    "<b>Không gian:</b> vật/nơi chốn nằm <b>sát người nói</b> (xa người nghe).<br>"
    "<b>Tư duy/hội thoại:</b> chỉ hiện tại/tương lai gần; <b>dẫn dắt thông tin SẮP nói ra</b>; tái hiện quá khứ như đang xảy ra trước mắt.<br>"
    "<b>Ví dụ:</b> この本 (cuốn sách này – đang cầm) · これから発表します (sau đây tôi xin phát biểu) · この間 (hôm nọ/vừa rồi)")
add(D3,
    "<b>Bộ そ (SO – trung đài)</b> dùng khi nào? (bản chất · không gian · tư duy/hội thoại · ví dụ)",
    "<b>Bản chất:</b> Khách quan & Logic – thuộc phía <b>NGƯỜI NGHE</b>, hoặc văn bản/lời nói.<br>"
    "<b>Không gian:</b> vật/nơi chốn nằm <b>sát người nghe</b> (xa người nói).<br>"
    "<b>Tư duy/hội thoại:</b> nói về sự việc <b>chỉ MỘT bên biết</b>; <b>thay thế từ ở câu trước</b> (tránh lặp từ), mang tính khách quan/lý trí.<br>"
    "<b>Ví dụ:</b> その時計 (cái đồng hồ đó – bạn đang đeo) · その時 (lúc đó – thời điểm vừa kể) · それは良い意見だ (đó là ý kiến hay – ý bạn vừa nói)")
add(D3,
    "<b>Bộ あ (A – viễn đài)</b> dùng khi nào? (bản chất · không gian · tư duy/hội thoại · ví dụ)",
    "<b>Bản chất:</b> Hoài niệm & Ký ức – nằm xa <b>CẢ HAI</b>, hoặc sâu trong tâm trí.<br>"
    "<b>Không gian:</b> vật/nơi chốn nằm <b>xa cả người nói lẫn người nghe</b>.<br>"
    "<b>Tư duy/hội thoại:</b> nói về sự việc <b>CẢ HAI bên đều biết rõ</b>; tự độc thoại, hoài niệm, bồi hồi về ký ức cũ.<br>"
    "<b>Ví dụ:</b> あの山 (ngọn núi kia – phía xa) · あの時は楽しかった (lúc đó vui biết mấy) · あのスキー旅行 (chuyến trượt tuyết năm ngoái đó)")
# Quy tắc quyết định – mấu chốt khi làm bài
add(D3,
    "<b>Mấu chốt phân biệt そ vs あ</b> khi nhắc lại điều đã nói?",
    "• <b>そ</b> (それ・その…): khi <b>chỉ 1 bên</b> (người nói HOẶC người nghe) biết, "
    "hoặc thay thế từ ở câu trước để tránh lặp.<br>"
    "• <b>あ</b> (あれ・あの…): khi <b>cả 2 bên cùng biết rõ</b>, cùng có ký ức về điều đó.<br>"
    "• <b>こ</b> (これ・この…): thông tin của <b>chính người nói</b>, sắp nêu ra / thuộc hiện tại.")
add(D3,
    "Trong văn bản, chỉ thị từ <b>thay thế cụm vừa nêu ở câu trước</b> (tránh lặp) thường là bộ nào?",
    "→ Bộ <b>そ</b> (それ・その・そこ…). Đây là cách dùng phổ biến nhất trong bài đọc/đục lỗ.")
add(D3,
    "Chỉ thị từ <b>dẫn dắt / giới thiệu thông tin SẮP nói</b> (sau đây…) là bộ nào?",
    "→ Bộ <b>こ</b> (これから, この…). Ví dụ: これから (sau đây).")


def main() -> None:
    out = io.StringIO()
    for d in (PARENT, D1, D2, D3):
        client.invoke("createDeck", deck=d)
    payload = [{
        "deckName": d,
        "modelName": MODEL,
        "fields": {F_FRONT: front, F_BACK: back},
        "tags": [TAG],
        "options": {"allowDuplicate": False,
                    "duplicateScope": "deck"},
    } for (d, front, back) in notes]
    res = client.invoke("addNotes", notes=payload)
    ok = sum(1 for r in res if r)
    skipped = [notes[i] for i, r in enumerate(res) if not r]
    by_deck: dict[str, int] = {}
    for (d, _, _), r in zip(notes, res):
        if r:
            by_deck[d] = by_deck.get(d, 0) + 1
    out.write(f"# Tạo deck '{PARENT}'\n\n")
    out.write(f"Tổng số thẻ định tạo: {len(notes)} | thành công: {ok} | "
              f"bỏ qua (trùng): {len(skipped)}\n\n")
    for d in (D1, D2, D3):
        out.write(f"- {d}: +{by_deck.get(d, 0)} thẻ\n")
    if skipped:
        out.write("\n## Bỏ qua (đã tồn tại / trùng mặt trước):\n")
        for d, f, _ in skipped:
            out.write(f"- [{d}] {f[:70]}\n")
    Path(ROOT / "output").mkdir(exist_ok=True)
    rep = ROOT / "output" / "duc_lo_method_deck.report.md"
    rep.write_text(out.getvalue(), encoding="utf-8")
    print(out.getvalue())


if __name__ == "__main__":
    main()
