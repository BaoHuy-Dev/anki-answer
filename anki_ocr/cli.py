from __future__ import annotations

import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from .anki_connect import AnkiConnectClient
from .core import FrontOcrConfig, ProcessConfig, process_deck, process_front_ocr_deck
from .enrich import get_env_var

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

app = typer.Typer(add_completion=False, no_args_is_help=True, help="OCR ảnh trong deck Anki và sinh nội dung mặt sau.")
console = Console()


def _default_model() -> str:
    return get_env_var("GEMINI_MODEL") or get_env_var("OPENAI_MODEL") or "gemini-2.5-flash"


@app.callback()
def main() -> None:
    """OCR ảnh trong deck Anki và sinh nội dung mặt sau."""


@app.command()
def process(
    deck: str = typer.Option(..., "--deck", help="Tên deck Anki."),
    front_field: str = typer.Option("Front", "--front-field", help="Field chứa câu hỏi/ảnh."),
    back_field: str = typer.Option("Back", "--back-field", help="Field chứa đáp án gốc."),
    target_field: str = typer.Option("Back", "--target-field", help="Field sẽ được ghi đè / cập nhật."),
    ocr_lang: str = typer.Option("jpn+eng", "--ocr-lang", help="Ngôn ngữ cho Tesseract."),
    model: str = typer.Option(_default_model(), "--model", help="Model để sinh romaji/dịch/ngữ pháp."),
    base_url: str | None = typer.Option(None, "--base-url", help="Base URL OpenAI-compatible nếu cần."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Không ghi vào Anki, chỉ tạo report."),
    report_path: Path = typer.Option(Path("output/report.md"), "--report-path", help="Đường dẫn report Markdown."),
    limit: int | None = typer.Option(None, "--limit", help="Giới hạn số note xử lý."),
    start_index: int = typer.Option(1, "--start-index", help="Index note bắt đầu trong deck (1-based)."),
    end_index: int | None = typer.Option(None, "--end-index", help="Index note kết thúc trong deck (1-based, inclusive)."),
    skip_existing: bool = typer.Option(False, "--skip-existing", help="Bỏ qua note đã có block anki-ocr-answer."),
    skip_complete: bool = typer.Option(False, "--skip-complete", help="Bỏ qua note đã có đủ danh sách lựa chọn."),
) -> None:
    client = AnkiConnectClient()
    def logger(message: str) -> None:
        console.print(message)
        console.file.flush()

    summary = Table(title="Anki OCR Summary")
    summary.add_column("Note ID", style="cyan")
    summary.add_column("OCR files", style="magenta")
    summary.add_column("Updated", style="green")
    processed = process_deck(
        client,
        ProcessConfig(
            deck=deck,
            front_field=front_field,
            back_field=back_field,
            target_field=target_field,
            ocr_lang=ocr_lang,
            model=model,
            base_url=base_url,
            dry_run=dry_run,
            report_path=report_path,
            limit=limit,
            start_index=start_index,
            end_index=end_index,
            skip_existing=skip_existing,
            skip_complete=skip_complete,
        ),
        logger=logger,
    )

    for note in processed:
        summary.add_row(str(note.note_id), str(len(note.ocr_files)), "yes" if note.updated else "dry-run")

    console.print(summary)
    console.print(f"[green]Report đã được ghi vào {report_path}[/green]")
    if dry_run:
        console.print("[yellow]Chế độ dry-run: chưa ghi vào Anki.[/yellow]")


@app.command()
def front_ocr(
    deck: str = typer.Option(..., "--deck", help="Tên deck Anki."),
    front_field: str = typer.Option("Front", "--front-field", help="Field chứa ảnh/câu hỏi."),
    back_field: str = typer.Option("Back", "--back-field", help="Field chứa lời giải đã sinh hoặc OCR cũ."),
    ocr_lang: str = typer.Option("jpn+eng", "--ocr-lang", help="Ngôn ngữ cho Tesseract khi cần OCR từ ảnh."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Không ghi vào Anki, chỉ tạo report."),
    report_path: Path = typer.Option(Path("output/front-ocr-report.md"), "--report-path", help="Đường dẫn report Markdown."),
    limit: int | None = typer.Option(None, "--limit", help="Giới hạn số note xử lý."),
    start_index: int = typer.Option(1, "--start-index", help="Index note bắt đầu trong deck (1-based)."),
    end_index: int | None = typer.Option(None, "--end-index", help="Index note kết thúc trong deck (1-based, inclusive)."),
    skip_existing: bool = typer.Option(False, "--skip-existing", help="Bỏ qua note đã có block anki-ocr-front."),
) -> None:
    client = AnkiConnectClient()

    def logger(message: str) -> None:
        console.print(message)
        console.file.flush()

    summary = Table(title="Anki Front OCR Summary")
    summary.add_column("Note ID", style="cyan")
    summary.add_column("Source", style="magenta")
    summary.add_column("Updated", style="green")
    processed = process_front_ocr_deck(
        client,
        FrontOcrConfig(
            deck=deck,
            front_field=front_field,
            back_field=back_field,
            ocr_lang=ocr_lang,
            dry_run=dry_run,
            report_path=report_path,
            limit=limit,
            start_index=start_index,
            end_index=end_index,
            skip_existing=skip_existing,
        ),
        logger=logger,
    )

    for note in processed:
        source = "ocr-image" if note.ocr_files else "back"
        if note.skipped_reason:
            source = note.skipped_reason
        summary.add_row(str(note.note_id), source, "yes" if note.updated else "dry-run/skip")

    console.print(summary)
    console.print(f"[green]Report đã được ghi vào {report_path}[/green]")
    if dry_run:
        console.print("[yellow]Chế độ dry-run: chưa ghi vào Anki.[/yellow]")
