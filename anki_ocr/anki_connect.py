from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import requests


class AnkiConnectError(RuntimeError):
    pass


@dataclass
class AnkiConnectClient:
    url: str = "http://localhost:8765"
    timeout: float = 30.0

    def invoke(self, action: str, **params: Any) -> Any:
        payload = {"action": action, "version": 6, "params": params}
        response = requests.post(self.url, json=payload, timeout=self.timeout)
        response.raise_for_status()

        data = response.json()
        if data.get("error") is not None:
            raise AnkiConnectError(str(data["error"]))
        return data.get("result")

    def deck_notes(self, deck_name: str) -> list[int]:
        query = f'deck:"{deck_name}"'
        return self.invoke("findNotes", query=query)

    def notes_info(self, note_ids: list[int]) -> list[dict[str, Any]]:
        if not note_ids:
            return []
        return self.invoke("notesInfo", notes=note_ids)

    def retrieve_media_file(self, filename: str) -> str:
        return self.invoke("retrieveMediaFile", filename=filename)

    def update_note_fields(self, note_id: int, fields: dict[str, str]) -> Any:
        return self.invoke("updateNoteFields", note={"id": note_id, "fields": fields})
