"""Group bunpou cards by the grammar structure of their answer.

Stages (decoupled so the LLM steps can resume without re-calling):

  extract   -> output/grammar/deckN.cards.json     (no API)
  classify  -> output/grammar/deckN.labels.json     (Gemini, batched, resumable)
  canon     -> output/grammar/deckN.canon.json      (Gemini, merge variants)
  report    -> output/grammar/deckN.report.md       (no API)
  apply     -> create decks + move cards in Anki     (writes to Anki; needs --yes)

Run:
  python scripts/grammar_group.py extract
  python scripts/grammar_group.py classify
  python scripts/grammar_group.py canon
  python scripts/grammar_group.py report
  python scripts/grammar_group.py apply --yes        # actually moves cards
  python scripts/grammar_group.py apply              # dry-run (prints plan only)
"""
from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from anki_ocr.anki_connect import AnkiConnectClient  # noqa: E402
from anki_ocr.ocr import strip_html  # noqa: E402
from anki_ocr.enrich import (  # noqa: E402
    _api_key_candidates,
    _rotated_api_keys,
    _mark_key_success,
    _client_for_model,
    _is_rate_limit_error,
    _retry_delay_seconds,
)

OUT_DIR = ROOT / "output" / "grammar"
OUT_DIR.mkdir(parents=True, exist_ok=True)

DECK_ROOTS = {
    1: "bunpou dokkai mondai 1",
    2: "bunpou dokkai mondai 2",
}
NEW_PARENT = {
    1: "Ngữ pháp N3 - Mondai 1 (theo cấu trúc)",
    2: "Ngữ pháp N3 - Mondai 2 (theo cấu trúc)",
}
NO_SOLUTION_LABEL = "⚠ Chưa có lời giải"
MODEL = "gemini-2.5-flash"
BATCH = 12

client = AnkiConnectClient()
WS = re.compile(r"\s+")


# ============================ stage 1: extract ============================

@dataclass
class CardRecord:
    note_id: int
    card_id: int
    deck: str
    question: str
    answer: str
    grammar_context: str
    forced_label: str = ""
    corrected: bool = False


def _clean(text: str) -> str:
    return WS.sub(" ", strip_html(text or "")).strip()


def _front_question(front_html: str) -> str:
    m = re.search(r"<b>OCR câu hỏi:</b>\s*(.*?)</p>", front_html or "", re.DOTALL | re.IGNORECASE)
    return _clean(m.group(1)) if m else _clean(front_html)


def _ocr_answer_value(back_html: str, label: str) -> str:
    m = re.search(rf"<p><b>{re.escape(label)}:</b>\s*(.*?)</p>", back_html or "", re.DOTALL | re.IGNORECASE)
    return _clean(m.group(1)) if m else ""


def _parse_mondai2(back_html: str) -> tuple[str, str]:
    answer = _ocr_answer_value(back_html, "Đáp án")
    note = _ocr_answer_value(back_html, "Ghi chú ôn tập")
    completed = _ocr_answer_value(back_html, "Câu hoàn chỉnh")
    ctx = f"Câu hoàn chỉnh: {completed} | Giải thích: {note}" if completed else note
    return answer, ctx


def _parse_mondai1(back_html: str) -> tuple[str, str]:
    m = re.search(r"<b>Dap an dung:</b>\s*(.*?)(?:<i>|<br>)", back_html or "", re.DOTALL | re.IGNORECASE)
    answer = _clean(m.group(1)) if m else ""
    ctx_parts: list[str] = []
    gm = re.search(r"<b>Ngu phap chinh:</b><ul>(.*?)</ul>", back_html or "", re.DOTALL | re.IGNORECASE)
    if gm:
        for li in re.findall(r"<li>(.*?)</li>", gm.group(1), re.DOTALL | re.IGNORECASE):
            bm = re.search(r"<b>(.*?)</b>\s*:?\s*(.*)", li, re.DOTALL | re.IGNORECASE)
            ctx_parts.append(f"{_clean(bm.group(1))}: {_clean(bm.group(2))}" if bm else _clean(li))
    om = re.search(r"<b>Phan tich tung dap an:</b><ol>(.*?)</ol>", back_html or "", re.DOTALL | re.IGNORECASE)
    if om:
        for li in re.findall(r"<li>(.*?)</li>", om.group(1), re.DOTALL | re.IGNORECASE):
            if "(dung)" in li.lower() or "(đúng)" in li.lower():
                ctx_parts.insert(0, "ĐÁP ÁN ĐÚNG: " + _clean(li))
                break
    return answer, " || ".join(p for p in ctx_parts if p)


def _load_corrections() -> dict[str, dict]:
    """note_id(str) -> {answer, label} for user-corrected cards."""
    path = OUT_DIR / "corrections.json"
    if not path.exists():
        return {}
    out: dict[str, dict] = {}
    for r in json.load(open(path, encoding="utf-8")):
        new = r.get("new", {})
        if r["type"] == "m1":
            ans = f"{r['corrected_num']} {new.get('answer_text') or r.get('corrected_text','')}".strip()
        else:
            ans = new.get("star_answer", "") or " → ".join(str(d) for d in r.get("corrected_order", []))
        out[str(r["note_id"])] = {"answer": ans, "label": (new.get("grammar_point") or "").strip()}
    return out


def extract(deck_idx: int) -> list[CardRecord]:
    root = DECK_ROOTS[deck_idx]
    infos = client.notes_info(client.invoke("findNotes", query=f'deck:"{root}" OR deck:"{root}::*"'))
    cards_info = client.invoke("cardsInfo", cards=client.invoke("findCards", query=f'deck:"{root}" OR deck:"{root}::*"'))
    note_to_card: dict[int, int] = {}
    note_to_deck: dict[int, str] = {}
    for c in cards_info:
        note_to_card.setdefault(c["note"], c["cardId"])
        note_to_deck.setdefault(c["note"], c["deckName"])
    corrections = _load_corrections()
    records: list[CardRecord] = []
    for info in infos:
        nid = info["noteId"]
        fields = info.get("fields", {})
        back = fields.get("Back", {}).get("value", "")
        if 'class="anki-ocr-answer"' in back:
            answer, ctx = _parse_mondai2(back)
        else:
            answer, ctx = _parse_mondai1(back)
        corr = corrections.get(str(nid))
        forced, is_corr = "", False
        if corr:
            is_corr = True
            forced = corr["label"]
            if corr["answer"]:
                answer = corr["answer"]
        records.append(CardRecord(
            note_id=nid,
            card_id=note_to_card.get(nid, 0),
            deck=note_to_deck.get(nid, root),
            question=_front_question(fields.get("Front", {}).get("value", ""))[:300],
            answer=answer[:200],
            grammar_context=ctx[:600],
            forced_label=forced,
            corrected=is_corr,
        ))
    return records


def stage_extract() -> None:
    for idx, root in DECK_ROOTS.items():
        recs = extract(idx)
        (OUT_DIR / f"deck{idx}.cards.json").write_text(
            json.dumps([asdict(r) for r in recs], ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"deck{idx} '{root}': {len(recs)} cards (missing answer: {sum(1 for r in recs if not r.answer)})")


# ============================ Gemini helper ============================

def gemini_json(system: str, user: str, logger=print, images: list[str] | None = None,
                model: str | None = None) -> str:
    model = model or MODEL
    keys, missing = _api_key_candidates(model)
    if not keys:
        raise RuntimeError(f"Chưa cấu hình {missing}. Hãy đặt biến môi trường GEMINI_API_KEY rồi chạy lại.")
    if images:
        user_content: object = [{"type": "text", "text": user}] + [
            {"type": "image_url", "image_url": {"url": u}} for u in images
        ]
    else:
        user_content = user
    last_error = ""
    for round_index in range(1, 5):
        wait = 0.0
        for key_name, api_key in _rotated_api_keys(keys):
            cli = _client_for_model(model, api_key, None)
            try:
                resp = cli.chat.completions.create(
                    model=model, temperature=0,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user_content}],
                )
                _mark_key_success(keys, key_name)
                return resp.choices[0].message.content or ""
            except Exception as exc:  # noqa: BLE001
                msg = str(exc).replace(api_key, "[redacted]")
                last_error = f"{key_name}: {msg}"
                if _is_rate_limit_error(msg):
                    wait = max(wait, _retry_delay_seconds(msg) or 35.0)
        if wait <= 0 or round_index >= 4:
            break
        logger(f"  rate-limited, chờ {min(wait + 2, 75):.0f}s...")
        time.sleep(min(wait + 2, 75))
    raise RuntimeError(f"Gemini lỗi: {last_error}")


def parse_json_array(text: str) -> list:
    t = text.strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", t).strip()
    try:
        v = json.loads(t, strict=False)
        return v if isinstance(v, list) else v.get("items", [])
    except json.JSONDecodeError:
        s, e = t.find("["), t.rfind("]")
        if s != -1 and e > s:
            return json.loads(t[s:e + 1], strict=False)
    return []


# ============================ stage 2: classify ============================

CLASSIFY_SYSTEM = """You classify JLPT N3 Japanese quiz cards by the SINGLE core grammar point the correct answer tests.
Return ONLY a JSON array. For each input item return:
{"id": <id>, "label": "<canonical Japanese grammar label>", "romaji": "<romaji>", "vi": "<short Vietnamese meaning>"}

Rules for "label":
- Use dictionary/citation form with 〜 marking slots, e.g. 〜うちに, 〜ば〜ほど, 〜について, 〜により, 〜ようにする, 〜たことがある, 〜ないと, 〜わけではない.
- Use V / N / Aい / Aな placeholders when the conjugation class matters, e.g. Vたことがある, Nによって, Vるところ.
- Group conjugation/politeness variants under the SAME label (〜た / 〜ます / 〜ない forms of the same pattern share one label).
- If the card tests vocabulary or an adverb/expression rather than a grammar pattern, use the form 語:<word> (e.g. 語:どちらかというと, 語:確かに).
- Be consistent: identical grammar points across different cards MUST get the exact same label string.
- Prefer the grammar point explained as the key reason for the answer, not incidental grammar in the sentence.
"""


def stage_classify(deck_idx: int) -> None:
    recs = json.load(open(OUT_DIR / f"deck{deck_idx}.cards.json", encoding="utf-8"))
    out_path = OUT_DIR / f"deck{deck_idx}.labels.json"
    done: dict[str, dict] = {}
    if out_path.exists():
        done = {str(x["id"]): x for x in json.load(open(out_path, encoding="utf-8"))}

    pending = []
    for r in recs:
        # user-corrected cards: use the authoritative grammar_point, always override cache
        if r.get("forced_label"):
            done[str(r["note_id"])] = {"id": r["note_id"], "label": r["forced_label"], "romaji": "", "vi": ""}
            continue
        cached = done.get(str(r["note_id"]))
        if cached and cached.get("label") not in ("", "??", None):
            continue
        if not r["answer"] and not r["grammar_context"]:
            done[str(r["note_id"])] = {"id": r["note_id"], "label": NO_SOLUTION_LABEL, "romaji": "", "vi": ""}
            continue
        pending.append(r)

    print(f"deck{deck_idx}: {len(done)} cached/forced, {len(pending)} to classify")
    out_path.write_text(json.dumps(list(done.values()), ensure_ascii=False, indent=2), encoding="utf-8")
    for i in range(0, len(pending), BATCH):
        batch = pending[i:i + BATCH]
        items = [{
            "id": r["note_id"],
            "question": r["question"],
            "answer": r["answer"],
            "explanation": r["grammar_context"],
        } for r in batch]
        user = "Classify these items. Return the JSON array only.\n" + json.dumps(items, ensure_ascii=False)
        arr = parse_json_array(gemini_json(CLASSIFY_SYSTEM, user))
        by_id = {str(x.get("id")): x for x in arr if isinstance(x, dict)}
        for r in batch:
            x = by_id.get(str(r["note_id"]))
            done[str(r["note_id"])] = x if x else {"id": r["note_id"], "label": "??", "romaji": "", "vi": ""}
        out_path.write_text(json.dumps(list(done.values()), ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  [{min(i + BATCH, len(pending))}/{len(pending)}] done")


# ============================ stage 3: canonicalize ============================

CANON_SYSTEM = """You merge near-duplicate JLPT grammar labels into canonical groups.
Input: a JSON array of distinct label strings.
Output: ONLY a JSON object mapping each input label -> its canonical label.
Merge labels that denote the SAME grammar point or word (ignore okurigana, 〜 placement, V/N placeholders, politeness/tense).
Keep distinct grammar points separate. Pick the clearest dictionary-form label as the canonical value.
Every input label MUST appear as a key. Do not invent labels not derivable from the inputs."""


def stage_canon(deck_idx: int) -> None:
    labels = json.load(open(OUT_DIR / f"deck{deck_idx}.labels.json", encoding="utf-8"))
    distinct = sorted({x["label"] for x in labels if x.get("label") and x["label"] != NO_SOLUTION_LABEL})
    mapping: dict[str, str] = {}
    for i in range(0, len(distinct), 60):
        chunk = distinct[i:i + 60]
        obj = gemini_json(CANON_SYSTEM, json.dumps(chunk, ensure_ascii=False))
        t = obj.strip()
        if t.startswith("```"):
            t = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", t).strip()
        s, e = t.find("{"), t.rfind("}")
        part = json.loads(t[s:e + 1]) if s != -1 else {}
        for k in chunk:
            mapping[k] = part.get(k, k)
    mapping[NO_SOLUTION_LABEL] = NO_SOLUTION_LABEL
    (OUT_DIR / f"deck{deck_idx}.canon.json").write_text(
        json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"deck{deck_idx}: {len(distinct)} raw labels -> {len(set(mapping.values()))} canonical")


# ============================ stage 4: report ============================

def _grouped(deck_idx: int):
    recs = {str(r["note_id"]): r for r in json.load(open(OUT_DIR / f"deck{deck_idx}.cards.json", encoding="utf-8"))}
    labels = {str(x["id"]): x for x in json.load(open(OUT_DIR / f"deck{deck_idx}.labels.json", encoding="utf-8"))}
    canon = json.load(open(OUT_DIR / f"deck{deck_idx}.canon.json", encoding="utf-8"))
    groups: dict[str, list] = {}
    meta: dict[str, dict] = {}
    for nid, rec in recs.items():
        lab = labels.get(nid, {})
        raw = lab.get("label", "??")
        clabel = canon.get(raw, raw)
        groups.setdefault(clabel, []).append(rec)
        meta.setdefault(clabel, lab)
    ordered = sorted(groups.items(), key=lambda kv: (kv[0] == NO_SOLUTION_LABEL, -len(kv[1]), kv[0]))
    return ordered, meta


def stage_report(deck_idx: int) -> None:
    ordered, meta = _grouped(deck_idx)
    total = sum(len(v) for _, v in ordered)
    lines = [f"# Gom nhóm cấu trúc ngữ pháp — {DECK_ROOTS[deck_idx]}", ""]
    lines.append(f"- Tổng số thẻ: **{total}**")
    lines.append(f"- Số cấu trúc (sau khi gộp biến thể): **{len([k for k,_ in ordered if k != NO_SOLUTION_LABEL])}**")
    lines.append(f"- Deck tổng sẽ tạo: `{NEW_PARENT[deck_idx]}`")
    lines.append("")
    lines.append("Thứ tự deck con = theo tần suất giảm dần (cấu trúc gặp nhiều học trước).")
    lines.append("")
    for order, (label, recs) in enumerate(ordered, start=1):
        vi = meta.get(label, {}).get("vi", "")
        head = f"## {order:02d}. {label} — {len(recs)} thẻ"
        if vi:
            head += f"  _( {vi} )_"
        lines.append(head)
        for r in recs:
            q = r["question"] or "(không có câu hỏi)"
            mark = " ✏️(đã sửa)" if r.get("corrected") else ""
            lines.append(f"- [{r['answer'] or '—'}]{mark} {q[:90]}")
        lines.append("")
    (OUT_DIR / f"deck{deck_idx}.report.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"deck{deck_idx}: report -> output/grammar/deck{deck_idx}.report.md ({total} thẻ, "
          f"{len([k for k,_ in ordered if k != NO_SOLUTION_LABEL])} cấu trúc)")


# ============================ stage 5: apply ============================

def _safe(name: str) -> str:
    return name.replace("::", "꞉꞉").replace(":", "꞉").replace('"', "'").strip()


def stage_apply(deck_idx: int, do_it: bool) -> None:
    ordered, meta = _grouped(deck_idx)
    parent = NEW_PARENT[deck_idx]
    origin = {}
    plan = []
    for order, (label, recs) in enumerate(ordered, start=1):
        deck_name = f"{parent}::{order:03d}. {_safe(label)} ({len(recs)})"
        plan.append((deck_name, [r["card_id"] for r in recs]))
        for r in recs:
            origin[str(r["note_id"])] = r["deck"]
    print(f"\ndeck{deck_idx} -> '{parent}': {len(plan)} deck con, {sum(len(c) for _,c in plan)} thẻ")
    for deck_name, cards in plan[:8]:
        print(f"  {deck_name}  [{len(cards)} thẻ]")
    if len(plan) > 8:
        print(f"  ... (+{len(plan)-8} deck con nữa)")
    if not do_it:
        print("  (dry-run — thêm --yes để thực sự tạo deck và di chuyển thẻ)")
        return
    (OUT_DIR / f"deck{deck_idx}.origin.json").write_text(
        json.dumps(origin, ensure_ascii=False, indent=2), encoding="utf-8")
    for deck_name, cards in plan:
        client.invoke("createDeck", deck=deck_name)
        if cards:
            client.invoke("changeDeck", cards=cards, deck=deck_name)
    print("  ĐÃ ÁP DỤNG. (origin lưu ở deckN.origin.json để hoàn tác nếu cần)")


# ============================ main ============================

if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "extract"
    only = None
    if "--deck" in sys.argv:
        only = int(sys.argv[sys.argv.index("--deck") + 1])
    do_it = "--yes" in sys.argv
    decks = [only] if only else [1, 2]

    if stage == "extract":
        stage_extract()
    elif stage == "classify":
        for d in decks:
            stage_classify(d)
    elif stage == "canon":
        for d in decks:
            stage_canon(d)
    elif stage == "report":
        for d in decks:
            stage_report(d)
    elif stage == "apply":
        for d in decks:
            stage_apply(d, do_it)
    else:
        print(f"Unknown stage: {stage}")
