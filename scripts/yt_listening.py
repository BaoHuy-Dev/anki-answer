"""YouTube JLPT listening (即時応答 Mondai 5) -> Anki cards.

Pipeline:
  segments -> output/listening/segments.json   (parse 番 markers + snap to silence)
  cut [N]  -> output/listening/clips/qNNN.mp3   (ffmpeg per-question clips)
  trans    -> output/listening/items.json       (Gemini: transcribe + solve, resumable)
  cards --yes -> add media + notes to Anki

Paths are wired to the already-downloaded files in the scratchpad.
"""
from __future__ import annotations

import base64
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.grammar_group import gemini_json  # noqa: E402
from scripts.fix_corrections import _parse_arr  # noqa: E402
from anki_ocr.anki_connect import AnkiConnectClient  # noqa: E402

SCRATCH = Path(r"C:\Users\Admin\AppData\Local\Temp\claude\g--Project-anki-answer\222990d3-471a-4d04-b6a7-e2681247e9ec\scratchpad")
AUDIO = SCRATCH / "n3audio.m4a"
VTT = SCRATCH / "n3.ja.vtt"
SILENCE_LOG = SCRATCH / "silence.log"
FFMPEG = r"C:\Users\Admin\AppData\Local\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.1-full_build\bin\ffmpeg.exe"

OUT = ROOT / "output" / "listening"
CLIPS = OUT / "clips"
OUT.mkdir(parents=True, exist_ok=True)
CLIPS.mkdir(parents=True, exist_ok=True)
SEG_PATH = OUT / "segments.json"
ITEMS_PATH = OUT / "items.json"

DECK = "N3 Nghe hiểu - Mondai 5 (即時応答)"
MEDIA_PREFIX = "yt_n3m5_v2"
client = AnkiConnectClient()


def _to_s(t: str) -> float:
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def parse_markers() -> list[float]:
    raw = VTT.read_text(encoding="utf-8")
    cue_re = re.compile(r"(\d{2}:\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3})[^\n]*\n(.*?)(?=\n\d{2}:\d{2}:\d{2}\.\d{3} -->|\Z)", re.DOTALL)
    tok_re = re.compile(r"<(\d{2}:\d{2}:\d{2}\.\d{3})><c>(.*?)</c>")
    def has_marker(text: str) -> bool:
        return any(ch == "番" and (i == 0 or text[i - 1] != "順") for i, ch in enumerate(text))
    hits = []
    for m in cue_re.finditer(raw):
        cstart = _to_s(m.group(1)); body = m.group(3); last = 0
        for tm in tok_re.finditer(body):
            if has_marker(body[last:tm.start()]):
                hits.append(cstart)
            if has_marker(tm.group(2)):
                hits.append(_to_s(tm.group(1)))
            last = tm.end()
        if has_marker(body[last:]):
            hits.append(cstart)
    hits.sort()
    clean = []
    for t in hits:
        if not clean or t - clean[-1] > 15:
            clean.append(t)
    return clean


def parse_silence() -> list[tuple[float, float]]:
    """Return list of (silence_start, silence_end)."""
    txt = SILENCE_LOG.read_text(encoding="utf-8", errors="ignore")
    starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", txt)]
    ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", txt)]
    return list(zip(starts, ends))


def stage_segments() -> None:
    marks = parse_markers()
    sil = parse_silence()
    dur = float(subprocess.run([FFMPEG.replace("ffmpeg.exe", "ffprobe.exe"), "-i", str(AUDIO),
                                "-show_entries", "format=duration", "-v", "quiet", "-of", "csv=p=0"],
                               capture_output=True, text=True).stdout.strip() or 7440)
    segs = []
    for i, t in enumerate(marks):
        # start: snap to a silence interval whose END is just before the marker (the bell/gap), within 6s
        cands = [s for s in sil if t - 6 <= s[1] <= t + 0.5]
        start = max(cands, key=lambda s: s[1])[0] if cands else max(0, t - 1.0)
        # end: just before next marker -> snap to nearest silence start before next marker
        nxt = marks[i + 1] if i + 1 < len(marks) else dur
        end_cands = [s for s in sil if nxt - 6 <= s[0] <= nxt]
        end = min(end_cands, key=lambda s: abs(s[0] - nxt))[0] if end_cands else max(start + 5, nxt - 1.0)
        segs.append({"q": i + 1, "start": round(start, 2), "end": round(end, 2),
                     "anchor": round(t, 2), "front_time": round(t + 0.35, 2),
                     "dur": round(end - start, 2)})
    SEG_PATH.write_text(json.dumps(segs, ensure_ascii=False, indent=2), encoding="utf-8")
    durs = [s["dur"] for s in segs]
    print(f"segments: {len(segs)} | dur min={min(durs)} max={max(durs)} avg={round(sum(durs)/len(durs),1)}")


def stage_cut(limit: int | None) -> None:
    segs = json.load(open(SEG_PATH, encoding="utf-8"))
    if limit:
        segs = segs[:limit]
    for s in segs:
        out = CLIPS / f"q{s['q']:03d}.mp3"
        if out.exists():
            continue
        subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-ss", str(s["start"]),
                        "-to", str(s["end"]), "-i", str(AUDIO), "-ac", "1", "-b:a", "64k", str(out)],
                       check=True)
    n_ok = sum(1 for s in segs if (CLIPS / f"q{s['q']:03d}.mp3").exists())
    print(f"cut: {n_ok} clips in {CLIPS}")


TRANS_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
TRANS_BATCH = 3

TRANS_SYSTEM = """Bạn là giáo viên JLPT N3, phần nghe 即時応答 (Mondai 5): nghe 1 câu nói mở đầu rồi 3 lựa chọn đáp lại (1,2,3), chọn câu đáp tự nhiên nhất.
Bạn nhận NHIỀU đoạn audio theo thứ tự. Trả về DUY NHẤT một JSON array, mỗi phần tử ứng với 1 đoạn audio ĐÚNG THEO THỨ TỰ, dạng:
{"prompt":"<câu mở đầu tiếng Nhật>",
 "prompt_vi":"<dịch tiếng Việt>",
 "options":["<lựa chọn 1 tiếng Nhật>","<lựa chọn 2>","<lựa chọn 3>"],
 "options_vi":["<dịch 1>","<dịch 2>","<dịch 3>"],
 "answer":<1|2|3>,
 "explanation":"<giải thích ngắn tiếng Việt: vì sao đáp án đúng, các lựa chọn kia sai/không tự nhiên>"}
Số phần tử trong array PHẢI bằng số đoạn audio. Chỉ xuất JSON."""

MIME = "audio/mpeg"


def _clip_data_url(q: int) -> str | None:
    p = CLIPS / f"q{q:03d}.mp3"
    if not p.exists():
        return None
    return f"data:{MIME};base64,{base64.b64encode(p.read_bytes()).decode()}"


def stage_trans(limit: int | None) -> None:
    segs = json.load(open(SEG_PATH, encoding="utf-8"))
    if limit:
        segs = segs[:limit]
    done = {}
    if ITEMS_PATH.exists():
        done = {x["q"]: x for x in json.load(open(ITEMS_PATH, encoding="utf-8"))}
    pending = [s["q"] for s in segs
               if not (s["q"] in done and "prompt" in done[s["q"]]) and (CLIPS / f"q{s['q']:03d}.mp3").exists()]
    print(f"trans: {len(pending)} câu cần xử lý (models={TRANS_MODELS}, batch={TRANS_BATCH})")
    for i in range(0, len(pending), TRANS_BATCH):
        batch = pending[i:i + TRANS_BATCH]
        urls = [_clip_data_url(q) for q in batch]
        text = (f"Có {len(batch)} đoạn audio 即時応答, theo thứ tự câu {batch}. "
                f"Trả về JSON array {len(batch)} phần tử theo đúng thứ tự các đoạn.")
        arr, err = None, ""
        for m in TRANS_MODELS:
            try:
                arr = _parse_arr(gemini_json(TRANS_SYSTEM, text, images=urls, model=m))
                break
            except Exception as e:  # noqa: BLE001
                err = str(e)
        if arr is None:
            print(f"  batch {batch} ERROR {err[:120]}"); continue
        for idx, q in enumerate(batch):
            obj = arr[idx] if idx < len(arr) and isinstance(arr[idx], dict) else {}
            obj["q"] = q
            done[q] = obj
        ITEMS_PATH.write_text(json.dumps(list(done.values()), ensure_ascii=False, indent=2), encoding="utf-8")
        ok = sum(1 for q in batch if done[q].get("prompt"))
        print(f"  [{min(i + TRANS_BATCH, len(pending))}/{len(pending)}] batch {batch} ok={ok}")
        import time as _t
        _t.sleep(3)
    print(f"trans done: {sum(1 for x in done.values() if 'prompt' in x)}/{len(segs)}")


def _esc(s: str) -> str:
    return (str(s or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")


def _pick_model() -> str:
    models = client.invoke("modelNames")
    for m in ("Basic", "Cơ bản", "基本"):
        if m in models:
            return m
    # fallback: any model with exactly Front/Back-like 2 fields
    for m in models:
        flds = client.invoke("modelFieldNames", modelName=m)
        if len(flds) >= 2:
            return m
    raise RuntimeError("Không tìm thấy note type phù hợp")


_ANS = None
_MEDIA_DIR = None


def _official(q: int, ai_ans) -> int:
    global _ANS
    if _ANS is None:
        p = OUT / "answers.json"
        _ANS = {a["q"]: a.get("answer_official", 0) for a in json.load(open(p, encoding="utf-8"))} if p.exists() else {}
    off = _ANS.get(q, 0)
    return off if off in (1, 2, 3) else (ai_ans if ai_ans in (1, 2, 3) else 0)


def _media_dir() -> Path:
    global _MEDIA_DIR
    if _MEDIA_DIR is None:
        _MEDIA_DIR = Path(client.invoke("getMediaDirPath"))
    return _MEDIA_DIR


def _copy_media(src: Path, filename: str) -> None:
    if src.exists():
        shutil.copyfile(src, _media_dir() / filename)


def render_back(x: dict, ans: int | None = None, end_img: str = "") -> str:
    if ans is None:
        ans = x.get("answer")
    opts = x.get("options", []) or []
    opts_vi = x.get("options_vi", []) or []
    lis = []
    for i, o in enumerate(opts, 1):
        vi = opts_vi[i - 1] if i - 1 < len(opts_vi) else ""
        correct = (i == ans)
        style = "color:#1e8449;font-weight:bold" if correct else ""
        mark = " ✅" if correct else ""
        lis.append(f'<li style="{style}">{_esc(o)}{mark}<br><span style="color:#777;font-size:0.9em">{_esc(vi)}</span></li>')
    img = f'<img src="{end_img}" style="max-width:95%;max-height:300px"><br>' if end_img else ""
    return (
        '<div style="text-align:left;max-width:640px;margin:auto">'
        f'{img}'
        f'<p><b>Câu mở đầu:</b> {_esc(x.get("prompt"))}<br>'
        f'<span style="color:#666">{_esc(x.get("prompt_vi"))}</span></p>'
        f'<ol>{"".join(lis)}</ol>'
        f'<p><b>Đáp án:</b> <span style="color:#c0392b;font-weight:bold">{ans}</span> (khoanh đỏ trong video)</p>'
        f'<p><b>💡 Giải thích:</b> {_esc(x.get("explanation"))}</p>'
        '</div>'
    )


ADDED_PATH = OUT / "added.json"


def stage_cards(do_it: bool) -> None:
    items = {x["q"]: x for x in json.load(open(ITEMS_PATH, encoding="utf-8"))}
    added = set(json.load(open(ADDED_PATH, encoding="utf-8"))) if ADDED_PATH.exists() else set()
    model = _pick_model()
    fld = client.invoke("modelFieldNames", modelName=model)
    front_field, back_field = fld[0], fld[1]
    if do_it:
        client.invoke("createDeck", deck=DECK)
    notes, qs = [], []
    skipped = 0
    for q in sorted(items):
        x = items[q]
        if q in added or "prompt" not in x:
            skipped += 1
            continue
        clip = CLIPS / f"q{q:03d}.mp3"
        if not clip.exists():
            skipped += 1
            continue
        fname = f"{MEDIA_PREFIX}_q{q:03d}.mp3"
        if do_it:
            client.invoke("storeMediaFile", filename=fname, path=str(clip))
        front = (f'🎧 [sound:{fname}]<br><br><b>Câu {q}</b><br>'
                 'Nghe và chọn câu đáp lại tự nhiên nhất: 1 / 2 / 3')
        notes.append({
            "deckName": DECK, "modelName": model,
            "fields": {front_field: front, back_field: render_back(x)},
            "tags": ["n3-choukai-m5", "yt-import"],
            "options": {"allowDuplicate": True},
        })
        qs.append(q)
    print(f"cards: {len(notes)} mới (đã có {len(added)}), bỏ qua {skipped}, model={model}")
    if not do_it:
        print("  (dry-run — thêm --yes để nạp media + tạo thẻ)")
        return
    if not notes:
        print("  không có thẻ mới để thêm.")
        return
    res = client.invoke("addNotes", notes=notes)
    for q, r in zip(qs, res):
        if r:
            added.add(q)
    ADDED_PATH.write_text(json.dumps(sorted(added), ensure_ascii=False), encoding="utf-8")
    ok = sum(1 for r in res if r)
    print(f"  ĐÃ TẠO {ok}/{len(notes)} thẻ mới | tổng đã import: {len(added)}/223 vào '{DECK}'")


def _store_media(q: int) -> tuple[str, str, str]:
    af = f"{MEDIA_PREFIX}_q{q:03d}.mp3"
    _copy_media(CLIPS / f"q{q:03d}.mp3", af)
    frames = OUT / "frames"
    sf = ef = ""
    if (frames / f"q{q:03d}_start.jpg").exists():
        sf = f"{MEDIA_PREFIX}_q{q:03d}_s.jpg"
        _copy_media(frames / f"q{q:03d}_start.jpg", sf)
    if (frames / f"q{q:03d}_end.jpg").exists():
        ef = f"{MEDIA_PREFIX}_q{q:03d}_e.jpg"
        _copy_media(frames / f"q{q:03d}_end.jpg", ef)
    return af, sf, ef


def _build_note(q: int, x: dict, front_field: str, back_field: str) -> dict:
    af, sf, ef = _store_media(q)
    ans = _official(q, x.get("answer"))
    img = f'<img src="{sf}" style="max-width:95%;max-height:300px"><br>' if sf else ""
    front = (f'{img}🎧 [sound:{af}]<br><b>Câu {q}</b><br>'
             'Nghe và chọn câu đáp lại tự nhiên nhất: 1 / 2 / 3')
    return {
        "deckName": DECK, "modelName": _MODEL,
        "fields": {front_field: front, back_field: render_back(x, ans, ef)},
        "tags": ["n3-choukai-m5", "yt-import"],
        "options": {"allowDuplicate": True},
    }


def stage_reorder(do_it: bool) -> None:
    """Rebuild the deck so cards are added LAST->FIRST (reverse study order)."""
    global _MODEL
    items = {x["q"]: x for x in json.load(open(ITEMS_PATH, encoding="utf-8")) if "prompt" in x}
    ready = sorted(items, reverse=True)  # last question first
    ready = [q for q in ready if (CLIPS / f"q{q:03d}.mp3").exists()]
    _MODEL = _pick_model()
    fld = client.invoke("modelFieldNames", modelName=_MODEL)
    print(f"reorder: sẽ thêm {len(ready)} thẻ theo thứ tự ngược (câu {ready[0]} -> {ready[-1]})")
    if not do_it:
        print("  (dry-run — thêm --yes để xóa & thêm lại theo thứ tự ngược)")
        return
    old = client.invoke("findNotes", query=f'deck:"{DECK}" tag:yt-import')
    if old:
        client.invoke("deleteNotes", notes=old)
        print(f"  xóa {len(old)} thẻ cũ")
    client.invoke("createDeck", deck=DECK)
    notes = [_build_note(q, items[q], fld[0], fld[1]) for q in ready]
    res = client.invoke("addNotes", notes=notes)
    ok = sum(1 for r in res if r)
    ADDED_PATH.write_text(json.dumps(sorted(items), ensure_ascii=False), encoding="utf-8")
    print(f"  ĐÃ THÊM LẠI {ok}/{len(notes)} thẻ theo thứ tự ngược trong '{DECK}'")


_MODEL = "Basic"

if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "segments"
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    do_it = "--yes" in sys.argv
    if stage == "segments":
        stage_segments()
    elif stage == "cut":
        stage_cut(limit)
    elif stage == "trans":
        stage_trans(limit)
    elif stage == "cards":
        stage_cards(do_it)
    elif stage == "reorder":
        stage_reorder(do_it)
    else:
        print(f"Unknown stage: {stage}")
