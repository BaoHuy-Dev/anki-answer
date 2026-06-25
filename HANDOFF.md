# BÀN GIAO — Dự án anki-answer (cập nhật: 2026-06-24)

File này tóm tắt TOÀN BỘ công việc đã làm để một AI/người khác có thể tiếp tục.
Repo: `g:\Project\anki-answer`. Tất cả script ở `scripts/`, dữ liệu trung gian ở `output/`.

---

## 0. Môi trường & điều kiện chạy

- **Anki phải đang mở** + add-on **AnkiConnect** (http://localhost:8765). Client: `anki_ocr/anki_connect.py`.
- Python 3.12 (Windows). Chạy script với `PYTHONUTF8=1` để in được tiếng Nhật/Việt.
- **ffmpeg/ffprobe** (cài qua winget Gyan.FFmpeg, KHÔNG có trong PATH). Đường dẫn tuyệt đối dùng trong script:
  `C:\Users\Admin\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin\ffmpeg.exe`
- **yt-dlp** (pip). YouTube hiện cần JS runtime → dùng `--js-runtimes node` (Node có sẵn).
- **Gemini API keys**: dự án đọc `GEMINI_API_KEY`, `GEMINI_API_KEY_1..9` (env hoặc registry HKCU\Environment).
  - SANDBOX CHẶN ghi key vào registry → phải `export` key inline trước mỗi lệnh python.
  - Free tier giới hạn theo NGÀY trên mỗi project/model. `gemini-2.0-flash` = limit 0 (không dùng được free).
  - Dùng `gemini-2.5-flash` và `gemini-2.5-flash-lite`. Khi cạn quota, người dùng cấp thêm bộ key mới (project mới = quota mới).
  - Hàm gọi: `scripts/grammar_group.py::gemini_json(system, user, images=[...], model="...")` — có xoay key + retry rate-limit. `images` nhận data URL (audio `data:audio/mpeg;base64,...` hoặc ảnh `data:image/jpeg;base64,...`).
- Quy ước: nhầu hết script có các "stage", chạy `python scripts/X.py <stage> [--yes]`. `--yes` mới ghi thật vào Anki; không có `--yes` là dry-run.

---

## 1. Gom nhóm ngữ pháp Bunpou (XONG)

Decks gốc: `bunpou dokkai mondai 1` (392 thẻ, điền chỗ trống) và `bunpou dokkai mondai 2` (hái sao ★).
Yêu cầu: gom thẻ theo CẤU TRÚC NGỮ PHÁP của đáp án thành deck tổng + deck con, xếp theo tần suất, **COPY chứ không move** (giữ deck gốc).

- Script: `scripts/grammar_group.py` — stages: `extract → classify → canon → report → apply`.
  - classify dùng Gemini gắn nhãn ngữ pháp; canon gộp biến thể; report ra `output/grammar/deckN.report.md`.
- COPY (không move): `scripts/copy_to_grammar.py` (restore/copy) — tạo note nhân bản (addNotes allowDuplicate), tag `grammar-copy`.
- Kết quả: deck tổng `Ngữ pháp N3 - Mondai 1 (theo cấu trúc)` (255 deck con) và `... Mondai 2 ...`. Mỗi cấu trúc 1 deck con, tên `001. 〜うちに (n)` xếp theo tần suất.

## 2. Sửa đáp án Bunpou người dùng tự chỉnh (XONG)

Người dùng đã sửa tay nhiều thẻ Gemini làm sai (mã hoá: mondai1 = chữ số trong `<i>(do tin cay: cao)...</i>`; mondai2 = dãy `<p>N N N N</p>`).
- Script: `scripts/fix_corrections.py` — `detect → backup → regen → apply`. Backup: `output/grammar/back_backup.json`.
- 138 thẻ được giải thích lại theo đáp án đúng, khối đỏ "⚠ ĐÃ SỬA" ở đầu mặt sau, tag `da-sua`.

## 3. Giải thích "kiểu mẹo" cho Mondai 2 (XONG)

Mondai 2 tăng lên **152 thẻ** (thêm câu mới + sửa thêm). Viết lại TOÀN BỘ theo "mẹo khoanh nhanh đi thi".
- Script: `scripts/redo_mondai2.py` — `detect → backup → regen → apply`. Backup: `output/grammar/m2_back_backup.json`.
- Mặt sau: khối xanh "💡 Mẹo khoanh nhanh" ở đầu (đáp án ★, thứ tự, câu hoàn chỉnh, mẹo, ngữ pháp) + giữ chi tiết cũ. Tag `meo-thi` (+`da-sua` nếu đã sửa).
- Làm mới bản copy mondai2 trong deck ngữ pháp: `scripts/refresh_m2_copies.py` (`prep` rồi `rebuild --yes`). 125 deck con. LƯU Ý đã học: `addNotes` KHÔNG tự tạo deck → phải `createDeck` trước; nhãn nhóm dùng nhãn ĐƠN sạch (CLASSIFY_SYSTEM), không dùng grammar_point dài.

---

## 4. NGHE HIỂU từ YouTube → Anki (Mondai 5 + Mondai 4)

Mục tiêu: tách từng câu hỏi + audio (+ tranh cho Mondai 4) vào Anki để luyện nghe.
**Thứ tự học cả 2 deck = NGƯỢC (câu cuối học trước)** → stage `reorder` xoá hết rồi addNotes theo thứ tự câu lớn→nhỏ (thứ tự thẻ mới trong Anki = thứ tự add). reorder cũng tự storeMediaFile.

### File nguồn (trong scratchpad — KHÔNG nằm trong repo):
`C:\Users\Admin\AppData\Local\Temp\claude\g--Project-anki-answer\222990d3-471a-4d04-b6a7-e2681247e9ec\scratchpad\`
- Mondai 5 (video `NAWrpkUPuz8`): `n3audio.m4a`, `n3video.mp4` (480p), `n3.ja.vtt`, `silence.log`
- Mondai 4 (video `NRqpsFnSpeE`): `m4/m4audio.m4a`, `m4/m4video.mp4` (480p), `m4/m4.ja.vtt`, `m4/m4silence.log`

### Pipeline & dữ liệu
- **Mondai 5** — script `scripts/yt_listening.py`; output `output/listening/`.
  - Phân đoạn theo mốc "番" (223 câu) + snap khoảng lặng. Stages: `segments → cut → trans → cards/reorder`.
  - `segments.json`, `items.json` (transcript: prompt, prompt_vi, options[3], options_vi[3], answer, explanation), `clips/qNNN.mp3`, `frames/qNNN_start.jpg`, `frames/qNNN_end.jpg`, `answers.json` (answer_official từ khoanh đỏ), `added.json`.
  - Deck: `N3 Nghe hiểu - Mondai 5 (即時応答)`, tag `n3-choukai-m5`, `yt-import`. Media: `yt_n3m5_v2_qNNN.mp3 / _s.jpg / _e.jpg`.
- **Mondai 4** — script `scripts/yt_listening_m4.py`; output `output/listening_m4/`.
  - Phân đoạn theo mốc "言いますか" (80 câu — video ghi 100 nhưng thật ra 80). Cùng cấu trúc file như trên.
  - items có `situation`/`situation_vi` thay cho prompt. Deck: `N3 Nghe hiểu - Mondai 4 (発話表現)`, tag `n3-choukai-m4`. Media `yt_n3m4_...`.

### Đáp án THẬT từ "khoanh đỏ" trong video (điểm quan trọng)
Video Minchan hiện ĐÁP ÁN ĐÚNG bằng VÒNG TRÒN ĐỎ ở cuối mỗi câu (sau khi nghe). Ta lấy đáp án thật từ đó thay vì để Gemini đoán từ audio.
- `scripts/answer_frame.py`: `find_circle()` quét khung (2 fps) tìm khung có nhiều ĐỎ THUẦN nhất trong vùng đáp án (m4: dải dưới chia 3 CỘT; m5: trái-giữa chia 3 HÀNG). Với m5, detector bỏ qua title slide `JLPT N3 45+` để các câu cuối block không copy nhầm ảnh bìa sang mặt sau.
- `scripts/answer_frames_run.py run m4|m5`: chụp `qNNN_start.jpg` (đầu câu, chưa khoanh) + `qNNN_end.jpg` (khung khoanh đỏ) + ghi `answers.json`.
- `scripts/read_circle.py m4|m5`: gửi các ảnh `_end.jpg` cho **Gemini vision** đọc số khoanh đỏ → `answer_official` (gộp 4 ảnh/lượt). (Dò pixel để TÌM khung, Gemini để ĐỌC số — pixel đọc số bị nhiễu vì chữ "2" màu đỏ.)
- `scripts/fix_explanations.py m4|m5`: với câu mà `answer_official` ≠ đáp án AI → set answer=official + viết lại explanation (cờ `answer_corrected_by_circle`).

### Bố cục thẻ nghe (theo yêu cầu mới nhất)
- **Mặt trước**: ảnh `_start.jpg` (m4 = tranh tình huống; m5 = slide "1 2 3") + `[sound:...mp3]` + "Câu N: ...".
- **Mặt sau**: ảnh `_end.jpg` (khoanh đỏ) + transcript (Nhật+Việt) + đáp án (màu đỏ, "khoanh đỏ trong video") + giải thích.

---

## 5. TRẠNG THÁI HIỆN TẠI & VIỆC CÒN DỞ

Tất cả mục 1–3 và phần lõi mục 4 đã XONG. Đang làm: **dựng lại 2 deck nghe với bố cục ảnh đầu/ảnh khoanh đỏ + đáp án thật**.

- ✅ **Mondai 4**: đã dựng lại xong — 80 thẻ, front=ảnh đầu+audio, back=ảnh khoanh đỏ+đáp án thật (8 câu đã sửa theo khoanh đỏ: 16,35,36,44,58,59,76,80). Cập nhật 2026-06-24: đã sửa lỗi lệch front/back do segment cắt theo khoảng lặng ở các cụm q34-36, q58-60, q79-80; `yt_listening_m4.py` giờ cắt theo mốc caption VTT, `answer_frames_run.py` lấy start frame sau anchor và giữ `answer_official`. Sau đó phát hiện Anki vẫn dùng ảnh mặt trước cũ cho q80,71,69,66,64,52,41,28,25,23,17,12,11 do media filename/cache cũ; đã đổi toàn bộ media M4 sang prefix `yt_n3m4_v2_...` và rebuild lại deck 80/80 thẻ. Validate: tag `n3-choukai-m4` có 80 card, đủ q1-q80, không còn ref media cũ, hash Anki media khớp local.
- ✅ **Mondai 5**: ĐÃ dựng lại xong — 223 thẻ, thứ tự 223→1, front=ảnh `_s.jpg`+audio, back=ảnh `_e.jpg` khoanh đỏ+đáp án thật. Cập nhật 2026-06-24: sửa lỗi front/back lệch và back rơi vào title slide ở video `NAWrpkUPuz8` bằng cách lưu `anchor/front_time` theo caption, bỏ qua chữ `順番` khi parse mốc `番`, đổi media sang prefix `yt_n3m5_v2_...`, và cho `answer_frame.py` bỏ qua title slide M5 khi dò khoanh đỏ. Đã regenerate frames: `answers.json` đủ 223/223 `answer_official`, heuristic title trên toàn bộ `q*_end.jpg` = 0. Đã rebuild Anki 223/223; validate tag `n3-choukai-m5` có 223 note, không còn ref media cũ, đủ 669 ref v2, hash Anki media khớp local.

### Cách HOÀN TẤT / KIỂM TRA Mondai 5 (chạy lại an toàn — idempotent)
```powershell
cd "G:\Project\anki-answer"
# (export đủ GEMINI_API_KEY... nếu cần, nhưng reorder KHÔNG gọi Gemini)
$env:PYTHONIOENCODING='utf-8'
python scripts\yt_listening.py reorder --yes
# kiểm tra:
python -c "import sys;sys.path.insert(0,'.');from anki_ocr.anki_connect import AnkiConnectClient as A;c=A();print('m5',len(c.invoke('findCards',query='deck:\"N3 Nghe hiểu - Mondai 5 (即時応答)\"')),'thẻ')"
```
Kỳ vọng: 223 thẻ, thứ tự học 223→1, front có `<img ..._s.jpg>`+`[sound:]`, back có `<img ..._e.jpg>`.

### Nếu cần làm video nghe MỚI khác
1. Tải: `python -m yt_dlp -f 135 --js-runtimes node -o video.mp4 URL` (480p) + `-f 140` (audio) + `--write-auto-subs --sub-langs ja --sub-format vtt`.
2. Sửa hằng số đường dẫn trong `yt_listening*.py` / `answer_frames_run.py` cho video mới.
3. Chạy: `segments → cut → trans` (export keys) → `answer_frames_run run` → `read_circle` → `fix_explanations` → `reorder --yes`.

---

## 6. Bộ key Gemini hiện dùng (người dùng cấp, project mới, quota khỏe)
Export inline trước lệnh python cần Gemini (audio/vision/text):
```
export GEMINI_API_KEY="AIzaSyAvICWI5kLDRZKTkBx1zcuUaaCv74BiUSI"
export GEMINI_API_KEY_1="AIzaSyBilehe0luGrd75DrMR2CPtfxZakymfT4s"
export GEMINI_API_KEY_2="AIzaSyAVxMGJcovB_Xea6w2CXpMQqD4juUlwOrU"
export GEMINI_API_KEY_3="AIzaSyAlJY8Orn5FNXFcPk-zjaPm79KSt88u89k"
export GEMINI_API_KEY_4="AIzaSyCLth-EZuSP71s91DEUChXTo1cbJjp_N_4"
export GEMINI_API_KEY_5="AIzaSyBXxRxIHnlC92qaxFv6GtPgzU6VhRQhgt8"
export GEMINI_API_KEY_6="AIzaSyDVygda7wBd9vs2DzDQ2Noiw68hNxb_Fuk"
export GEMINI_API_KEY_7="AIzaSyANkBm7RV6ZslsiTLMSGRM7aHG1TyVUfJ0"
export GEMINI_API_KEY_8="AIzaSyAPc60R6nCVb8IbKFFkmickC0P33qlSkrQ"
export GEMINI_API_KEY_9="AIzaSyA-oTUkDMNj0uqRXgPsiD2GdDTkns9F5m0"
```
(Bộ key cũ — phần lớn đã cạn quota ngày — vẫn nằm trong lịch sử chat.)

## 7. Tag tổng hợp để lọc trong Anki
- `grammar-copy` — bản copy theo cấu trúc ngữ pháp.
- `da-sua` — thẻ bunpou đã sửa đáp án.
- `meo-thi` — thẻ mondai 2 giải thích kiểu mẹo.
- `n3-choukai-m5` / `n3-choukai-m4` + `yt-import` — thẻ nghe từ YouTube.

## 8. Hoàn tác
- Backup mặt sau bunpou: `output/grammar/back_backup.json`, `output/grammar/m2_back_backup.json`.
- origin deck gốc khi gom nhóm: `output/grammar/deckN.origin.json`.
- Xoá thẻ nghe: lọc tag `yt-import` rồi xoá (không ảnh hưởng deck khác).
