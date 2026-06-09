from __future__ import annotations

import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .anki_connect import AnkiConnectClient
from .core import ProcessConfig, process_deck
from .enrich import DEFAULT_GEMINI_KEY_NAMES, get_env_var


def _default_model() -> str:
    return get_env_var("GEMINI_MODEL") or get_env_var("OPENAI_MODEL") or "gemini-2.5-flash"


def _default_api_key() -> str:
    for name in [*DEFAULT_GEMINI_KEY_NAMES, "OPENAI_API_KEY"]:
        value = get_env_var(name)
        if value:
            return value
    return ""


def _api_key_env_name(model: str) -> str:
    if model.strip().lower().startswith("gemini"):
        return "GEMINI_API_KEY"
    return "OPENAI_API_KEY"


class DesktopApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Anki OCR Answer")
        self.geometry("980x760")
        self.minsize(900, 700)

        self._queue: queue.Queue[tuple[str, str | dict[str, str] | None]] = queue.Queue()
        self._running = False

        self.deck_var = tk.StringVar(value="Moji goi mondai 3")
        self.front_field_var = tk.StringVar(value="Front")
        self.back_field_var = tk.StringVar(value="Back")
        self.target_field_var = tk.StringVar(value="Back")
        self.ocr_lang_var = tk.StringVar(value="jpn+eng")
        self.model_var = tk.StringVar(value=_default_model())
        self.base_url_var = tk.StringVar(value="")
        self.report_path_var = tk.StringVar(value=str(Path("output") / "report.md"))
        self.limit_var = tk.StringVar(value="")
        self.api_key_var = tk.StringVar(value=_default_api_key())
        self.dry_run_var = tk.BooleanVar(value=True)
        self.skip_existing_var = tk.BooleanVar(value=False)

        self.status_var = tk.StringVar(value="Sẵn sàng")
        self.progress_var = tk.StringVar(value="0 note")

        self._build_ui()
        self.after(100, self._poll_queue)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=16)
        root.pack(fill=tk.BOTH, expand=True)

        header = ttk.Frame(root)
        header.pack(fill=tk.X, pady=(0, 12))
        ttk.Label(header, text="Anki OCR Answer", font=("Segoe UI", 22, "bold")).pack(anchor=tk.W)
        ttk.Label(
            header,
            text="OCR ảnh trong deck Anki, sinh romaji, dịch Việt và ghi chú ngữ pháp ngắn.",
            foreground="#445",
        ).pack(anchor=tk.W, pady=(4, 0))

        form = ttk.LabelFrame(root, text="Cấu hình", padding=12)
        form.pack(fill=tk.X)

        self._row(form, 0, "Deck", self.deck_var)
        self._row(form, 1, "Front field", self.front_field_var)
        self._row(form, 2, "Back field", self.back_field_var)
        self._row(form, 3, "Target field", self.target_field_var)
        self._row(form, 4, "OCR lang", self.ocr_lang_var)
        self._row(form, 5, "Model", self.model_var)
        self._row(form, 6, "Base URL tùy chọn", self.base_url_var)
        self._row(form, 7, "Report path", self.report_path_var, browse=True)
        self._row(form, 8, "Limit", self.limit_var)
        self._row(form, 9, "API key (Gemini/OpenAI)", self.api_key_var, show="*")

        options = ttk.Frame(form)
        options.grid(row=10, column=0, columnspan=3, sticky="w", pady=(8, 0))
        ttk.Checkbutton(options, text="Dry-run", variable=self.dry_run_var).pack(side=tk.LEFT)
        ttk.Label(options, text="  ").pack(side=tk.LEFT)
        ttk.Checkbutton(options, text="Skip existing", variable=self.skip_existing_var).pack(side=tk.LEFT)
        ttk.Label(options, text="  ").pack(side=tk.LEFT)
        ttk.Label(options, textvariable=self.status_var, foreground="#234").pack(side=tk.LEFT)

        actions = ttk.Frame(root)
        actions.pack(fill=tk.X, pady=(12, 8))
        self.run_button = ttk.Button(actions, text="Run OCR", command=self._start_process)
        self.run_button.pack(side=tk.LEFT)
        ttk.Button(actions, text="Clear log", command=self._clear_log).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Label(actions, textvariable=self.progress_var).pack(side=tk.RIGHT)

        output_frame = ttk.LabelFrame(root, text="Log", padding=10)
        output_frame.pack(fill=tk.BOTH, expand=True)
        self.log = tk.Text(output_frame, wrap=tk.WORD, height=24, font=("Consolas", 10))
        self.log.pack(fill=tk.BOTH, expand=True, side=tk.LEFT)
        scrollbar = ttk.Scrollbar(output_frame, orient=tk.VERTICAL, command=self.log.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.log.configure(yscrollcommand=scrollbar.set)

    def _row(self, parent: ttk.Frame, row: int, label: str, variable: tk.StringVar, browse: bool = False, show: str | None = None) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=(0, 10), pady=4)
        entry = ttk.Entry(parent, textvariable=variable, show=show)
        entry.grid(row=row, column=1, sticky="ew", pady=4)
        parent.grid_columnconfigure(1, weight=1)
        if browse:
            ttk.Button(parent, text="Browse", command=self._browse_report).grid(row=row, column=2, sticky="e", padx=(8, 0))

    def _browse_report(self) -> None:
        chosen = filedialog.asksaveasfilename(
            title="Chọn report Markdown",
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("All files", "*.*")],
        )
        if chosen:
            self.report_path_var.set(chosen)

    def _clear_log(self) -> None:
        self.log.delete("1.0", tk.END)

    def _append_log(self, message: str) -> None:
        self.log.insert(tk.END, message + "\n")
        self.log.see(tk.END)

    def _start_process(self) -> None:
        if self._running:
            return

        deck = self.deck_var.get().strip()
        if not deck:
            messagebox.showerror("Thiếu deck", "Vui lòng nhập tên deck.")
            return

        self._running = True
        self.run_button.configure(state=tk.DISABLED)
        self.status_var.set("Đang chạy...")
        self.progress_var.set("0 note")
        self._append_log(f"Bắt đầu xử lý deck: {deck}")

        model = self.model_var.get().strip() or "gemini-2.5-flash"
        api_key = self.api_key_var.get().strip()
        if api_key:
            os.environ[_api_key_env_name(model)] = api_key

        limit_text = self.limit_var.get().strip()
        try:
            limit = int(limit_text) if limit_text else None
        except ValueError:
            messagebox.showerror("Limit không hợp lệ", "Limit phải là số nguyên hoặc để trống.")
            self._finish_run()
            return
        config = ProcessConfig(
            deck=deck,
            front_field=self.front_field_var.get().strip() or "Front",
            back_field=self.back_field_var.get().strip() or "Back",
            target_field=self.target_field_var.get().strip() or "Back",
            ocr_lang=self.ocr_lang_var.get().strip() or "jpn+eng",
            model=model,
            base_url=self.base_url_var.get().strip() or None,
            dry_run=self.dry_run_var.get(),
            report_path=Path(self.report_path_var.get().strip() or "output/report.md"),
            limit=limit,
            skip_existing=self.skip_existing_var.get(),
        )

        worker = threading.Thread(target=self._worker, args=(config,), daemon=True)
        worker.start()

    def _worker(self, config: ProcessConfig) -> None:
        try:
            client = AnkiConnectClient()

            def logger(message: str) -> None:
                self._queue.put(("log", message))

            def note_callback(note) -> None:
                self._queue.put(("note", {
                    "note_id": str(note.note_id),
                    "ocr_files": str(len(note.ocr_files)),
                    "updated": "yes" if note.updated else "dry-run",
                }))

            processed = process_deck(client, config, logger=logger, note_callback=note_callback)
            self._queue.put(("done", {
                "count": str(len(processed)),
                "report": str(config.report_path),
                "dry_run": str(config.dry_run),
            }))
        except Exception as exc:  # noqa: BLE001
            self._queue.put(("error", str(exc)))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == "log" and isinstance(payload, str):
                    self._append_log(payload)
                elif kind == "note" and isinstance(payload, dict):
                    self.progress_var.set(f"Note {payload['note_id']} - {payload['updated']}")
                    self._append_log(f"Note {payload['note_id']} | OCR files: {payload['ocr_files']} | {payload['updated']}")
                elif kind == "done" and isinstance(payload, dict):
                    self.status_var.set("Hoàn tất")
                    self._append_log(f"Hoàn tất. Report: {payload['report']}")
                    self._append_log(f"Processed notes: {payload['count']}")
                    if payload.get("dry_run") == "True":
                        self._append_log("Chế độ dry-run: chưa ghi vào Anki.")
                    self._finish_run()
                elif kind == "error" and isinstance(payload, str):
                    self.status_var.set("Lỗi")
                    self._append_log(f"Lỗi: {payload}")
                    messagebox.showerror("Anki OCR Answer", payload)
                    self._finish_run()
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)

    def _finish_run(self) -> None:
        self._running = False
        self.run_button.configure(state=tk.NORMAL)


def main() -> None:
    app = DesktopApp()
    app.mainloop()


if __name__ == "__main__":
    main()
