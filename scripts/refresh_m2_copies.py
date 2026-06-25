"""Rebuild the mondai-2 grammar-structure COPY decks after the trick-style redo.

Steps:
  1. re-extract deck2 cards.json from Anki (now 152 cards, new Back)
  2. write deck2.labels.json from m2_redo grammar_point (authoritative per note)
  3. canon (merge variants) via grammar_group
  4. delete old sub-decks (and their copy cards) under the mondai-2 grammar parent
  5. create fresh sub-decks (ordered by frequency) and addNotes copies (tag grammar-copy)

Run:
  python scripts/refresh_m2_copies.py prep      # steps 1-3 (extract + labels + canon)
  python scripts/refresh_m2_copies.py rebuild --yes   # steps 4-5 (writes to Anki)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.grammar_group import (  # noqa: E402
    client, OUT_DIR, NEW_PARENT, _safe, extract, stage_canon, _grouped,
    gemini_json, parse_json_array, CLASSIFY_SYSTEM,
)

DECK_IDX = 2
M2_REDO = OUT_DIR / "m2_redo.json"
BATCH = 12


def stage_prep() -> None:
    # 1. re-extract current deck2 cards (152, with new trick Back)
    recs = extract(DECK_IDX)
    cards_path = OUT_DIR / f"deck{DECK_IDX}.cards.json"
    from dataclasses import asdict
    cards_path.write_text(json.dumps([asdict(r) for r in recs], ensure_ascii=False, indent=2), encoding="utf-8")

    # 2. clean single grouping label per card via the strict classifier,
    #    using the trick redo (star answer + completed sentence + grammar point) as context.
    redo = {r["note_id"]: r for r in json.load(open(M2_REDO, encoding="utf-8"))}
    pending = []
    for r in recs:
        n = redo.get(r.note_id, {}).get("new", {}) or {}
        pending.append({
            "id": r.note_id,
            "question": r.question,
            "answer": n.get("star_answer", ""),
            "explanation": f"{n.get('grammar_point','')} | {n.get('completed_sentence','')}",
        })
    labels = []
    for i in range(0, len(pending), BATCH):
        batch = pending[i:i + BATCH]
        user = "Classify these items. Return the JSON array only.\n" + json.dumps(batch, ensure_ascii=False)
        arr = parse_json_array(gemini_json(CLASSIFY_SYSTEM, user))
        by_id = {str(x.get("id")): x for x in arr if isinstance(x, dict)}
        for it in batch:
            x = by_id.get(str(it["id"]))
            labels.append(x if x else {"id": it["id"], "label": "??", "romaji": "", "vi": ""})
        print(f"  classify [{min(i + BATCH, len(pending))}/{len(pending)}]")
    (OUT_DIR / f"deck{DECK_IDX}.labels.json").write_text(
        json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"prep: {len(recs)} cards classified into clean labels")

    # 3. canon
    stage_canon(DECK_IDX)


def target_map() -> dict[int, str]:
    ordered, _ = _grouped(DECK_IDX)
    parent = NEW_PARENT[DECK_IDX]
    m: dict[int, str] = {}
    for order, (label, recs) in enumerate(ordered, start=1):
        name = f"{parent}::{order:03d}. {_safe(label)} ({len(recs)})"
        for r in recs:
            m[r["note_id"]] = name
    return m


def stage_rebuild(do_it: bool) -> None:
    parent = NEW_PARENT[DECK_IDX]
    tmap = target_map()
    n_sub = len(set(tmap.values()))
    print(f"rebuild: {len(tmap)} thẻ -> {n_sub} deck con dưới '{parent}'")
    if not do_it:
        for name in sorted(set(tmap.values()))[:8]:
            print("  ", name)
        print("  (dry-run — thêm --yes để xóa copy cũ và tạo lại)")
        return

    # 4. delete old sub-decks + their copy cards
    old_subs = [d for d in client.invoke("deckNames") if d.startswith(parent + "::")]
    if old_subs:
        client.invoke("deleteDecks", decks=old_subs, cardsToo=True)
        print(f"  đã xóa {len(old_subs)} deck con cũ (+ copy cũ)")

    # 5. create the target sub-decks first (addNotes does NOT auto-create decks)
    for name in sorted(set(tmap.values())):
        client.invoke("createDeck", deck=name)

    # 6. create fresh copies from current originals
    infos = client.notes_info(list(tmap.keys()))
    add = []
    for info in infos:
        fields = {k: v["value"] for k, v in info["fields"].items()}
        tags = list(dict.fromkeys(info.get("tags", []) + ["grammar-copy"]))
        add.append({
            "deckName": tmap[info["noteId"]],
            "modelName": info["modelName"],
            "fields": fields,
            "tags": tags,
            "options": {"allowDuplicate": True},
        })
    res = client.invoke("addNotes", notes=add)
    ok = sum(1 for x in res if x)
    print(f"  tạo {ok}/{len(add)} bản copy mới (tag grammar-copy)")


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "prep"
    do_it = "--yes" in sys.argv
    if stage == "prep":
        stage_prep()
    elif stage == "rebuild":
        stage_rebuild(do_it)
    else:
        print(f"Unknown stage: {stage}")
