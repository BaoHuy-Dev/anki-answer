from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from anki_ocr.anki_connect import AnkiConnectClient  # noqa: E402

client = AnkiConnectClient()

out = []

def log(msg: str) -> None:
    out.append(msg)

deck_names = client.invoke("deckNames")
target_roots = ["bunpou dokkai mondai 1", "bunpou dokkai mondai 2"]
log("# All decks matching targets")
for d in sorted(deck_names):
    if any(d == r or d.startswith(r + "::") for r in target_roots):
        ids = client.deck_notes(d)
        log(f"- {d}  -> {len(ids)} notes")

# Sample notes from each root (recursive) to see answer format
for root in target_roots:
    log(f"\n# Sample notes from '{root}' (recursive)")
    ids = client.invoke("findNotes", query=f'deck:"{root}::*" OR deck:"{root}"')
    log(f"Total notes (recursive): {len(ids)}")
    sample = ids[:3]
    infos = client.notes_info(sample)
    for info in infos:
        log(f"\n## Note {info['noteId']}  modelName={info.get('modelName')}")
        log(f"tags={info.get('tags')}")
        for fname, fdata in info.get("fields", {}).items():
            val = fdata.get("value", "")
            log(f"--- FIELD: {fname} ---")
            log(val)

Path("output").mkdir(exist_ok=True)
Path("output/deck_inspect.md").write_text("\n".join(out), encoding="utf-8")
print("Wrote output/deck_inspect.md, lines:", len(out))
