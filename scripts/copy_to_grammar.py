"""Undo the earlier MOVE and instead COPY cards into the grammar sub-decks.

  restore  -> move the original cards back to their source decks (deckN.origin.json)
  copy     -> create duplicate notes (tag 'grammar-copy') inside the grammar sub-decks
  verify   -> print counts

Run:
  python scripts/copy_to_grammar.py restore
  python scripts/copy_to_grammar.py copy
  python scripts/copy_to_grammar.py verify
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.grammar_group import (  # noqa: E402
    client, _grouped, NEW_PARENT, _safe, DECK_ROOTS, OUT_DIR,
)


def target_map(deck_idx: int) -> dict[int, str]:
    ordered, _ = _grouped(deck_idx)
    parent = NEW_PARENT[deck_idx]
    m: dict[int, str] = {}
    for order, (label, recs) in enumerate(ordered, start=1):
        name = f"{parent}::{order:03d}. {_safe(label)} ({len(recs)})"
        for r in recs:
            m[r["note_id"]] = name
    return m


def stage_restore() -> None:
    for idx in DECK_ROOTS:
        origin = json.load(open(OUT_DIR / f"deck{idx}.origin.json", encoding="utf-8"))
        parent = NEW_PARENT[idx]
        cards = client.invoke("findCards", query=f'deck:"{parent}::*"')
        if not cards:
            print(f"deck{idx}: không còn thẻ trong '{parent}::*' (đã trả về?)")
            continue
        info = client.invoke("cardsInfo", cards=cards)
        by_deck: dict[str, list[int]] = {}
        missing = 0
        for c in info:
            orig = origin.get(str(c["note"]))
            if not orig:
                missing += 1
                continue
            by_deck.setdefault(orig, []).append(c["cardId"])
        for orig, cids in by_deck.items():
            client.invoke("changeDeck", cards=cids, deck=orig)
        moved = sum(len(v) for v in by_deck.values())
        print(f"deck{idx}: trả {moved} thẻ về deck gốc ({len(by_deck)} deck), thiếu origin: {missing}")


def stage_copy() -> None:
    for idx in DECK_ROOTS:
        tmap = target_map(idx)
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
        fail = [add[i]["deckName"] for i, x in enumerate(res) if not x]
        print(f"deck{idx}: tạo {ok}/{len(add)} bản sao. Lỗi: {len(fail)}")
        if fail:
            for f in fail[:10]:
                print("   FAIL ->", f)


def stage_verify() -> None:
    for idx, root in DECK_ROOTS.items():
        parent = NEW_PARENT[idx]
        old = len(client.invoke("findCards", query=f'deck:"{root}::*"'))
        new = len(client.invoke("findCards", query=f'deck:"{parent}::*"'))
        copies = len(client.invoke("findCards", query=f'deck:"{parent}::*" tag:grammar-copy'))
        print(f"{root}: deck cũ={old} thẻ | deck ngữ pháp mới={new} thẻ (copy={copies})")


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "verify"
    {"restore": stage_restore, "copy": stage_copy, "verify": stage_verify}.get(
        stage, lambda: print(f"Unknown stage: {stage}")
    )()
