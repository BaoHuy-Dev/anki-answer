"""YouTube JLPT N3 Mondai 4 (発話表現, has pictures) -> Anki cards.

Front = picture screenshot + audio. Back = situation + 3 options + answer + explanation.
Reuses VTT 番-marker + silence segmentation from the Mondai 5 pipeline.

Stages: segments -> cut (audio clips + picture frames) -> trans -> cards --yes -> reorder --yes
Study order: reverse (last question first).
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
from scripts.yt_listening import parse_markers as _pm_generic, FFMPEG  # noqa: E402
from anki_ocr.anki_connect import AnkiConnectClient  # noqa: E402

SCRATCH = Path(r"C:\Users\Admin\AppData\Local\Temp\claude\g--Project-anki-answer\222990d3-471a-4d04-b6a7-e2681247e9ec\scratchpad\m4")
AUDIO = SCRATCH / "m4audio.m4a"
VIDEO = SCRATCH / "m4video.mp4"
VTT = SCRATCH / "m4.ja.vtt"
SILENCE_LOG = SCRATCH / "m4silence.log"
FFPROBE = FFMPEG.replace("ffmpeg.exe", "ffprobe.exe")

OUT = ROOT / "output" / "listening_m4"
CLIPS = OUT / "clips"
FRAMES = OUT / "frames"
for d in (OUT, CLIPS, FRAMES):
    d.mkdir(parents=True, exist_ok=True)
SEG_PATH = OUT / "segments.json"
ITEMS_PATH = OUT / "items.json"
ADDED_PATH = OUT / "added.json"

DECK = "N3 Nghe hiểu - Mondai 4 (発話表現)"
MEDIA_PREFIX = "yt_n3m4_v2"
TRANS_MODELS = ["gemini-2.5-flash", "gemini-2.5-flash-lite"]
TRANS_BATCH = 3
client = AnkiConnectClient()


def _to_s(t: str) -> float:
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


CUE_RE = re.compile(r"(\d{2}:\d{2}:\d{2}\.\d{3}) --> .*?\n(.*?)(?=\n\d{2}:\d{2}:\d{2}\.\d{3} -->|\Z)", re.DOTALL)
CUE_FULL_RE = re.compile(
    r"(\d{2}:\d{2}:\d{2}\.\d{3}) --> (\d{2}:\d{2}:\d{2}\.\d{3})[^\n]*\n"
    r"(.*?)(?=\n\d{2}:\d{2}:\d{2}\.\d{3} -->|\Z)",
    re.DOTALL,
)


def _clean_cue(body: str) -> str:
    return re.sub(r"<[^>]+>", "", body).replace("\n", " ").strip()


def vtt_cues() -> list[dict]:
    raw = VTT.read_text(encoding="utf-8")
    cues = []
    for m in CUE_FULL_RE.finditer(raw):
        body = _clean_cue(m.group(3))
        if body:
            cues.append({"start": _to_s(m.group(1)), "end": _to_s(m.group(2)), "body": body})
    return cues


def _has_question(body: str) -> bool:
    return "言いますか" in body


def _has_question_label(body: str) -> bool:
    txt = body.strip()
    return bool(re.match(r"^[1-4１-４]\s*番", txt) or re.match(r"^番", txt))


def _situation_start(cues: list[dict], anchor: float, prev_anchor: float | None) -> float:
    lo = max(0.0, anchor - 18.0)
    if prev_anchor is not None:
        lo = max(lo, prev_anchor + 6.0)
    win = [c for c in cues if lo <= c["start"] <= anchor + 0.1]

    labels = [c for c in win if _has_question_label(c["body"])]
    if labels:
        cluster = [labels[-1]]
        for c in reversed(labels[:-1]):
            if cluster[0]["start"] - c["start"] <= 2.5:
                cluster.insert(0, c)
            else:
                break
        return max(0.0, cluster[0]["start"] - 0.1)

    full_questions = [
        c for c in win
        if _has_question(c["body"]) and re.match(r"^[1-4１-４]\b", c["body"].strip())
    ]
    if full_questions:
        return max(0.0, full_questions[-1]["start"] - 1.7)

    questions = [c for c in win if _has_question(c["body"])]
    if questions:
        return max(0.0, questions[-1]["start"] - 0.5)

    return max(0.0, anchor - 6.0)


def question_anchors() -> list[float]:
    """Each Mondai-4 prompt ends with '...何と言いますか?' — a reliable per-question anchor."""
    raw = VTT.read_text(encoding="utf-8")
    hits = []
    for m in CUE_RE.finditer(raw):
        body = re.sub(r"<[^>]+>", "", m.group(2))
        if "言いますか" in body:
            hits.append(_to_s(m.group(1)))
    hits.sort()
    clean = []
    for t in hits:
        if not clean or t - clean[-1] > 10:
            clean.append(t)
    return clean


def _ensure_silence() -> None:
    if SILENCE_LOG.exists():
        return
    subprocess.run([FFMPEG, "-hide_banner", "-i", str(AUDIO),
                    "-af", "silencedetect=noise=-30dB:d=0.7", "-f", "null", "-"],
                   stderr=open(SILENCE_LOG, "w", encoding="utf-8"), check=True)


def parse_silence() -> list[tuple[float, float]]:
    txt = SILENCE_LOG.read_text(encoding="utf-8", errors="ignore")
    starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", txt)]
    ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", txt)]
    return list(zip(starts, ends))


def stage_segments() -> None:
    _ensure_silence()
    L = question_anchors()
    cues = vtt_cues()
    dur = float(subprocess.run([FFPROBE, "-i", str(AUDIO), "-show_entries", "format=duration",
                                "-v", "quiet", "-of", "csv=p=0"], capture_output=True, text=True).stdout.strip() or 2532)
    starts = [_situation_start(cues, anchor, L[i - 1] if i else None) for i, anchor in enumerate(L)]
    segs = []
    for i, anchor in enumerate(L):
        start = starts[i]
        if i + 1 < len(starts):
            end = max(start + 8.0, starts[i + 1] - 0.15)
        else:
            tail = [c for c in cues if anchor <= c["start"] <= min(dur, anchor + 36.0)]
            last_cue_end = max((c["end"] for c in tail), default=anchor + 20.0)
            end = min(dur, max(anchor + 18.0, last_cue_end + 2.0))
        segs.append({"q": i + 1, "start": round(start, 2), "end": round(end, 2),
                     "anchor": round(anchor, 2), "front_time": round(anchor + 0.35, 2),
                     "dur": round(end - start, 2)})
    SEG_PATH.write_text(json.dumps(segs, ensure_ascii=False, indent=2), encoding="utf-8")
    d = [s["dur"] for s in segs]
    print(f"segments: {len(segs)} | dur min={min(d)} max={max(d)} avg={round(sum(d)/len(d),1)}")


def stage_cut(limit: int | None, force: bool = False) -> None:
    segs = json.load(open(SEG_PATH, encoding="utf-8"))
    if limit:
        segs = segs[:limit]
    for s in segs:
        q = s["q"]
        clip = CLIPS / f"q{q:03d}.mp3"
        if force or not clip.exists():
            subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-ss", str(s["start"]),
                            "-to", str(s["end"]), "-i", str(AUDIO), "-ac", "1", "-b:a", "64k", str(clip)], check=True)
        frame = FRAMES / f"q{q:03d}.jpg"
        if force or not frame.exists():
            # grab the picture during the situation narration (a few sec before 言いますか)
            t = s.get("front_time", s.get("anchor", s["start"] + 4) + 0.35)
            subprocess.run([FFMPEG, "-y", "-hide_banner", "-loglevel", "error", "-ss", str(t),
                            "-i", str(VIDEO), "-frames:v", "1", "-q:v", "3", str(frame)], check=True)
    nclip = sum(1 for s in segs if (CLIPS / f"q{s['q']:03d}.mp3").exists())
    nframe = sum(1 for s in segs if (FRAMES / f"q{s['q']:03d}.jpg").exists())
    print(f"cut: {nclip} clip, {nframe} frame")


TRANS_SYSTEM = """Bạn là giáo viên JLPT N3, phần nghe 発話表現 (Mondai 4): có một bức TRANH minh họa tình huống, người dẫn mô tả tình huống và chỉ vào 1 người (mũi tên →), rồi đọc 3 lựa chọn câu nói (1,2,3). Chọn câu mà người đó NÊN nói, phù hợp tình huống nhất.
Bạn nhận NHIỀU đoạn audio theo thứ tự. Trả về DUY NHẤT một JSON array, mỗi phần tử ứng 1 đoạn ĐÚNG THỨ TỰ:
{"situation":"<lời dẫn tình huống tiếng Nhật>",
 "situation_vi":"<dịch tiếng Việt>",
 "options":["<câu 1 tiếng Nhật>","<câu 2>","<câu 3>"],
 "options_vi":["<dịch 1>","<dịch 2>","<dịch 3>"],
 "answer":<1|2|3>,
 "explanation":"<giải thích ngắn tiếng Việt: vì sao đáp án đúng phù hợp, các câu kia sai>"}
Số phần tử array PHẢI bằng số đoạn audio. Chỉ xuất JSON."""


def _clip_url(q: int) -> str | None:
    p = CLIPS / f"q{q:03d}.mp3"
    return f"data:audio/mpeg;base64,{base64.b64encode(p.read_bytes()).decode()}" if p.exists() else None


def stage_trans(limit: int | None) -> None:
    segs = json.load(open(SEG_PATH, encoding="utf-8"))
    if limit:
        segs = segs[:limit]
    done = {x["q"]: x for x in json.load(open(ITEMS_PATH, encoding="utf-8"))} if ITEMS_PATH.exists() else {}
    pending = [s["q"] for s in segs if not (s["q"] in done and "situation" in done[s["q"]]) and (CLIPS / f"q{s['q']:03d}.mp3").exists()]
    print(f"trans: {len(pending)} câu (models={TRANS_MODELS})")
    import time as _t
    for i in range(0, len(pending), TRANS_BATCH):
        batch = pending[i:i + TRANS_BATCH]
        urls = [_clip_url(q) for q in batch]
        text = f"Có {len(batch)} đoạn audio 発話表現 theo thứ tự câu {batch}. Trả JSON array {len(batch)} phần tử."
        arr, err = None, ""
        for m in TRANS_MODELS:
            try:
                arr = _parse_arr(gemini_json(TRANS_SYSTEM, text, images=urls, model=m)); break
            except Exception as e:  # noqa: BLE001
                err = str(e)
        if arr is None:
            print(f"  batch {batch} ERROR {err[:100]}"); continue
        for idx, q in enumerate(batch):
            obj = arr[idx] if idx < len(arr) and isinstance(arr[idx], dict) else {}
            obj["q"] = q; done[q] = obj
        ITEMS_PATH.write_text(json.dumps(list(done.values()), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  [{min(i+TRANS_BATCH,len(pending))}/{len(pending)}] {batch} ok={sum(1 for q in batch if done[q].get('situation'))}")
        _t.sleep(3)
    print(f"trans done: {sum(1 for x in done.values() if 'situation' in x)}/{len(segs)}")


def _esc(s: str) -> str:
    return (str(s or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")


def _pick_model() -> str:
    return "Basic" if "Basic" in client.invoke("modelNames") else client.invoke("modelNames")[0]


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


ITEM_OVERRIDES = {
    33: {
        "situation": "机の上に友達の傘があります。友達は今帰るところです。何と言いますか？",
        "situation_vi": "Trên bàn có ô của bạn. Bạn của bạn đang chuẩn bị về. Bạn sẽ nói gì?",
        "options": ["傘、忘れてるよ。", "傘、持ってこなかったの？", "傘、ここに置いたら？"],
        "options_vi": ["Bạn quên ô kìa.", "Bạn không mang ô à?", "Hay để ô ở đây đi?"],
        "answer": 1,
        "explanation": "Cần nhắc bạn rằng họ đang để quên ô, nên 「傘、忘れてるよ」 là tự nhiên nhất.",
    },
    34: {
        "situation": "写真を撮ってほしいです。近くにいる人に何と言いますか？",
        "situation_vi": "Bạn muốn nhờ người ở gần chụp ảnh giúp. Bạn sẽ nói gì?",
        "options": ["すみません、写真を撮っていただけませんか？", "あの、写真を撮ってもよろしいですか？", "よければ、写真をお撮りしましょうか？"],
        "options_vi": ["Xin lỗi, anh/chị có thể chụp ảnh giúp tôi được không?", "Tôi có thể chụp ảnh được không?", "Nếu được thì để tôi chụp ảnh cho nhé?"],
        "answer": 1,
        "explanation": "Muốn nhờ người khác chụp giúp thì dùng mẫu lịch sự 「撮っていただけませんか」.",
    },
    35: {
        "situation": "おしゃれな店を見つけました。友達を誘って、一緒に入りたいです。何と言いますか？",
        "situation_vi": "Bạn thấy một cửa hàng đẹp và muốn rủ bạn vào cùng. Bạn sẽ nói gì?",
        "options": ["ここ、行かなきゃいけない？", "ここ、この前入ったよね。", "ここ、ちょっと見ていかない？"],
        "options_vi": ["Mình phải vào đây à?", "Chỗ này lần trước mình vào rồi nhỉ.", "Hay mình ghé xem chỗ này một chút nhé?"],
        "answer": 3,
        "explanation": "Để rủ bạn vào xem cửa hàng, 「ここ、ちょっと見ていかない？」 là lời mời tự nhiên nhất.",
    },
    36: {
        "situation": "辞書を忘れたので、友達の辞書を借りたいです。何と言いますか？",
        "situation_vi": "Bạn quên từ điển nên muốn mượn từ điển của bạn. Bạn sẽ nói gì?",
        "options": ["ぜひその辞書使って。", "その辞書、ちょっと使わせてもらってもいい？", "その辞書使ってみるといいよ。"],
        "options_vi": ["Nhất định hãy dùng quyển từ điển đó đi.", "Cho mình dùng nhờ quyển từ điển đó một chút được không?", "Bạn thử dùng quyển từ điển đó xem."],
        "answer": 2,
        "explanation": "Muốn xin phép mượn/dùng đồ của bạn thì 「使わせてもらってもいい？」 là cách nói phù hợp.",
    },
    57: {
        "situation": "電車で友達にカバンを網棚に置くようにアドバイスします。何と言いますか？",
        "situation_vi": "Trên tàu, bạn muốn khuyên bạn để túi lên giá hành lý. Bạn sẽ nói gì?",
        "options": ["上のカバンの方がいい？", "カバン、網棚に載せたら？", "カバン、網棚に置くつもり？"],
        "options_vi": ["Cái túi phía trên tốt hơn à?", "Hay để túi lên giá hành lý đi?", "Bạn định để túi lên giá à?"],
        "answer": 2,
        "explanation": "Đưa lời khuyên nhẹ nhàng thì 「〜たら？」 phù hợp; câu 2 khuyên đặt túi lên giá hành lý.",
    },
    58: {
        "situation": "柔道の教室を見つけました。練習の様子が見たいです。何と言いますか？",
        "situation_vi": "Bạn tìm thấy một lớp judo và muốn xem buổi luyện tập. Bạn sẽ nói gì?",
        "options": ["練習を見てくださるんですか？", "練習をご覧になってください。", "練習を見学させていただけませんか？"],
        "options_vi": ["Thầy/cô sẽ xem buổi luyện tập giúp tôi ạ?", "Xin hãy xem buổi luyện tập.", "Tôi có thể được tham quan/xem buổi luyện tập không ạ?"],
        "answer": 3,
        "explanation": "Muốn xin phép xem luyện tập thì dùng 「見学させていただけませんか」.",
    },
    59: {
        "situation": "オフィスで、おしゃべりをしてうるさい人がいます。注意します。何と言いますか？",
        "situation_vi": "Trong văn phòng có người nói chuyện ồn. Bạn muốn nhắc họ. Bạn sẽ nói gì?",
        "options": ["あの、小さい声で話してもらいたいんですけど。", "あの、うるさくしてしまってすみません。", "あの、静かにした方がいいでしょうか？"],
        "options_vi": ["Xin lỗi, anh/chị nói nhỏ hơn giúp tôi được không?", "Xin lỗi vì tôi đã làm ồn.", "Tôi nên giữ yên lặng hơn phải không?"],
        "answer": 1,
        "explanation": "Để nhắc người đang nói ồn, câu 1 vừa đúng ý vừa mềm: muốn họ nói nhỏ lại.",
    },
    60: {
        "situation": "駐車場で止められるところを探しています。今出そうな車を見つけました。何と言いますか？",
        "situation_vi": "Bạn đang tìm chỗ đỗ xe và thấy một chiếc xe có vẻ sắp rời đi. Bạn sẽ nói gì?",
        "options": ["そこ、空くんじゃない？", "そこに車はなさそうだよ。", "そこには止まってる。"],
        "options_vi": ["Chỗ đó sắp trống đấy nhỉ?", "Có vẻ chỗ đó không có xe đâu.", "Ở đó đang có xe đỗ."],
        "answer": 1,
        "explanation": "Thấy xe có vẻ sắp đi ra thì 「そこ、空くんじゃない？」 là nhận xét phù hợp.",
    },
    69: {
        "situation": "レストランでスプーンが使いたいですが、ありません。店員に何と言いますか？",
        "situation_vi": "Ở nhà hàng, bạn muốn dùng thìa nhưng không có. Bạn sẽ nói gì với nhân viên?",
        "options": ["あの、スプーンいただけますか？", "あの、スプーンお使いください。", "あの、スプーンありません。"],
        "options_vi": ["Xin lỗi, tôi có thể xin một cái thìa không?", "Xin mời dùng thìa.", "Không có thìa."],
        "answer": 1,
        "explanation": "Muốn xin nhân viên mang thìa thì 「いただけますか」 là cách hỏi lịch sự.",
    },
    78: {
        "situation": "友達が教室を出るところです。椅子に友達の上着があります。何と言いますか？",
        "situation_vi": "Bạn của bạn đang ra khỏi lớp. Trên ghế có áo khoác của bạn ấy. Bạn sẽ nói gì?",
        "options": ["上着、置いていったら？", "上着、取ってくれる？", "上着、忘れてるよ。"],
        "options_vi": ["Hay để áo khoác lại đi?", "Lấy áo khoác giúp mình được không?", "Bạn quên áo khoác kìa."],
        "answer": 3,
        "explanation": "Bạn cần nhắc bạn mình đang quên áo khoác, nên câu 3 đúng nhất.",
    },
    79: {
        "situation": "靴の踵が取れてしまいました。店の人に修理してもらいたいです。何と言いますか？",
        "situation_vi": "Gót giày của bạn bị bung ra. Bạn muốn nhờ người của cửa hàng sửa giúp. Bạn sẽ nói gì?",
        "options": ["あの、この靴、直してほしいんですが。", "あの、この靴、修理しましょうか。", "あの、この靴、いただけますか。"],
        "options_vi": ["Xin lỗi, tôi muốn nhờ sửa đôi giày này.", "Để tôi sửa đôi giày này nhé?", "Tôi có thể nhận đôi giày này không?"],
        "answer": 1,
        "explanation": "Muốn nhờ cửa hàng sửa giày thì câu 1 dùng 「直してほしいんですが」 là phù hợp.",
    },
    80: {
        "situation": "友達から折り紙を習っています。ここまでの折り方が正しいかどうか聞きたいです。何と言いますか？",
        "situation_vi": "Bạn đang học gấp giấy từ bạn mình và muốn hỏi cách gấp đến đây có đúng không. Bạn sẽ nói gì?",
        "options": ["ちょっと折ってみて。", "折り紙ある？", "これでいい？"],
        "options_vi": ["Bạn thử gấp một chút đi.", "Bạn có giấy origami không?", "Như thế này được chưa?"],
        "answer": 3,
        "explanation": "Muốn hỏi cách gấp hiện tại đã đúng chưa thì 「これでいい？」 là tự nhiên nhất.",
    },
}


def _load_items() -> dict[int, dict]:
    items = {x["q"]: x for x in json.load(open(ITEMS_PATH, encoding="utf-8")) if "situation" in x}
    for q, override in ITEM_OVERRIDES.items():
        if q in items:
            fixed = dict(items[q])
            fixed.update(override)
            items[q] = fixed
    return items


def render_back(x: dict, ans: int, end_img: str) -> str:
    opts = x.get("options", []) or []; ovi = x.get("options_vi", []) or []
    lis = []
    for i, o in enumerate(opts, 1):
        v = ovi[i-1] if i-1 < len(ovi) else ""
        st = "color:#1e8449;font-weight:bold" if i == ans else ""
        lis.append(f'<li style="{st}">{_esc(o)}{" ✅" if i==ans else ""}<br><span style="color:#777;font-size:0.9em">{_esc(v)}</span></li>')
    img = f'<img src="{end_img}" style="max-width:95%;max-height:300px"><br>' if end_img else ""
    return ('<div style="text-align:left;max-width:640px;margin:auto">'
            f'{img}'
            f'<p><b>Tình huống:</b> {_esc(x.get("situation"))}<br><span style="color:#666">{_esc(x.get("situation_vi"))}</span></p>'
            f'<ol>{"".join(lis)}</ol>'
            f'<p><b>Đáp án:</b> <span style="color:#c0392b;font-weight:bold">{ans}</span> (khoanh đỏ trong video)</p>'
            f'<p><b>💡 Giải thích:</b> {_esc(x.get("explanation"))}</p></div>')


def _store_media(q: int) -> tuple[str, str, str]:
    af = f"{MEDIA_PREFIX}_q{q:03d}.mp3"; sf = f"{MEDIA_PREFIX}_q{q:03d}_s.jpg"; ef = f"{MEDIA_PREFIX}_q{q:03d}_e.jpg"
    _copy_media(CLIPS / f"q{q:03d}.mp3", af)
    if (FRAMES / f"q{q:03d}_start.jpg").exists():
        _copy_media(FRAMES / f"q{q:03d}_start.jpg", sf)
    else:
        sf = f"{MEDIA_PREFIX}_q{q:03d}.jpg"  # fallback to old situation frame
        _copy_media(FRAMES / f"q{q:03d}.jpg", sf)
    has_end = (FRAMES / f"q{q:03d}_end.jpg").exists()
    if has_end:
        _copy_media(FRAMES / f"q{q:03d}_end.jpg", ef)
    return af, sf, (ef if has_end else "")


def _build_note(q: int, x: dict, model: str, ff: str, bf: str) -> dict:
    af, sf, ef = _store_media(q)
    ans = _official(q, x.get("answer"))
    front = (f'<img src="{sf}" style="max-width:95%;max-height:320px"><br>'
             f'🎧 [sound:{af}]<br><b>Câu {q}</b><br>Nhìn tranh, nghe tình huống, chọn câu nói phù hợp: 1 / 2 / 3')
    return {"deckName": DECK, "modelName": model, "fields": {ff: front, bf: render_back(x, ans, ef)},
            "tags": ["n3-choukai-m4", "yt-import"], "options": {"allowDuplicate": True}}


def stage_cards(do_it: bool, reverse: bool) -> None:
    items = _load_items()
    added = set(json.load(open(ADDED_PATH, encoding="utf-8"))) if ADDED_PATH.exists() else set()
    model = _pick_model(); fld = client.invoke("modelFieldNames", modelName=model)
    order = sorted(items, reverse=reverse)
    todo = [q for q in order if q not in added and (CLIPS / f"q{q:03d}.mp3").exists()]
    print(f"cards: {len(todo)} mới (đã có {len(added)}), reverse={reverse}")
    if not do_it:
        print("  (dry-run)"); return
    client.invoke("createDeck", deck=DECK)
    notes = [_build_note(q, items[q], model, fld[0], fld[1]) for q in todo]
    res = client.invoke("addNotes", notes=notes)
    for q, r in zip(todo, res):
        if r:
            added.add(q)
    ADDED_PATH.write_text(json.dumps(sorted(added), ensure_ascii=False), encoding="utf-8")
    print(f"  ĐÃ TẠO {sum(1 for r in res if r)}/{len(notes)} thẻ | tổng {len(added)}")


def stage_reorder(do_it: bool) -> None:
    items = _load_items()
    ready = [q for q in sorted(items, reverse=True) if (CLIPS / f"q{q:03d}.mp3").exists()]
    model = _pick_model(); fld = client.invoke("modelFieldNames", modelName=model)
    print(f"reorder: {len(ready)} thẻ ngược (câu {ready[0]} -> {ready[-1]})")
    if not do_it:
        print("  (dry-run)"); return
    old = client.invoke("findNotes", query=f'deck:"{DECK}" tag:yt-import')
    if old:
        client.invoke("deleteNotes", notes=old)
    client.invoke("createDeck", deck=DECK)
    notes = [_build_note(q, items[q], model, fld[0], fld[1]) for q in ready]
    res = client.invoke("addNotes", notes=notes)
    ADDED_PATH.write_text(json.dumps(sorted(items), ensure_ascii=False), encoding="utf-8")
    print(f"  ĐÃ THÊM LẠI {sum(1 for r in res if r)}/{len(notes)} thẻ theo thứ tự ngược")


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "segments"
    do_it = "--yes" in sys.argv
    limit = int(sys.argv[sys.argv.index("--limit") + 1]) if "--limit" in sys.argv else None
    if stage == "segments":
        stage_segments()
    elif stage == "cut":
        stage_cut(limit, force="--force" in sys.argv)
    elif stage == "trans":
        stage_trans(limit)
    elif stage == "cards":
        stage_cards(do_it, reverse="--reverse" in sys.argv)
    elif stage == "reorder":
        stage_reorder(do_it)
    else:
        print(f"Unknown stage: {stage}")
