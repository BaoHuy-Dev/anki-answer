from __future__ import annotations

import html
import re
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from .anki_connect import AnkiConnectClient
from .enrich import AnswerOption, EnrichmentResult, enrich_card
from .ocr import extract_image_sources, ocr_media_sources, strip_html


@dataclass
class ProcessConfig:
    deck: str
    front_field: str = "Front"
    back_field: str = "Back"
    target_field: str = "Back"
    ocr_lang: str = "jpn+eng"
    model: str = "gemini-2.5-flash"
    base_url: str | None = None
    dry_run: bool = False
    report_path: Path = Path("output/report.md")
    limit: int | None = None
    start_index: int = 1
    end_index: int | None = None
    skip_existing: bool = False
    skip_complete: bool = False


@dataclass
class FrontOcrConfig:
    deck: str
    front_field: str = "Front"
    back_field: str = "Back"
    ocr_lang: str = "jpn+eng"
    dry_run: bool = False
    report_path: Path = Path("output/front-ocr-report.md")
    limit: int | None = None
    start_index: int = 1
    end_index: int | None = None
    skip_existing: bool = False


@dataclass
class ProcessedNote:
    note_id: int
    ocr_files: list[str]
    ocr_text: str
    question: str
    answer: str
    back_block: str
    updated: bool
    skipped_reason: str | None = None


@dataclass
class FrontOcrNote:
    note_id: int
    ocr_files: list[str]
    question: str
    options: list[str]
    raw_ocr: str
    front_block: str
    updated: bool
    skipped_reason: str | None = None


GENERATED_BLOCK_PATTERN = re.compile(r'\s*<div class="anki-ocr-answer">.*?</div>\s*', re.DOTALL)
FRONT_OCR_BLOCK_PATTERN = re.compile(r'\s*<div class="anki-ocr-front">.*?</div>\s*', re.DOTALL)
IMAGE_IMPORT_ID_PATTERN = re.compile(r"\bimage_import_id_[a-f0-9]+\b", re.IGNORECASE)
NO_READABLE_CONTENT_MARKER = 'data-status="no-readable-content"'
WHITESPACE_PATTERN = re.compile(r"\s+")
JAPANESE_PATTERN = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
OPTION_LABEL_PATTERN = re.compile(r"^(?:[①-⑳]|\(?\d{1,2}\)?[.)、．]?)$")
INLINE_OPTION_PATTERN = re.compile(r"^(?P<label>[①-⑳]|\(?\d{1,2}\)?[.)、．]?)\s*(?P<text>.+)$")
ORDER_LABEL_PATTERN = re.compile(r"[\u2460-\u2473]|\b\d{1,2}\b")
PLACEHOLDER_TOKEN_PATTERN = re.compile(r"_{2,}|＿+|\(\s*\)|（\s*）|★")
PLACEHOLDER_GROUP_PATTERN = re.compile(r"(?:(?:\s*(?:_{2,}|＿+|\(\s*\)|（\s*）|★)\s*){2,})")


def remove_generated_block(field_html: str) -> str:
    return GENERATED_BLOCK_PATTERN.sub("", field_html or "").strip()


def remove_front_ocr_block(field_html: str) -> str:
    return FRONT_OCR_BLOCK_PATTERN.sub("", field_html or "").strip()


def has_generated_block(field_html: str) -> bool:
    if not GENERATED_BLOCK_PATTERN.search(field_html or ""):
        return False
    
    # Check if the block is a NEW clean block
    # A new clean block MUST have "<b>Câu hỏi:</b>"
    if "<b>Câu hỏi:</b>" not in field_html:
        return False # Messy, don't skip!
        
    try:
        question_part = field_html.split("<b>Câu hỏi:</b>")[1].split("</p>")[0]
        if "|" in question_part:
            return False # Messy, don't skip!
    except IndexError:
        return False # Messy, don't skip!
        
    return True # Clean, DO skip!


def has_front_ocr_block(field_html: str) -> bool:
    return FRONT_OCR_BLOCK_PATTERN.search(field_html or "") is not None


def has_complete_generated_block(field_html: str) -> bool:
    if not has_generated_block(field_html):
        return False
    if "Quota exceeded" in field_html or "RESOURCE_EXHAUSTED" in field_html:
        return False
    if NO_READABLE_CONTENT_MARKER in field_html:
        return True
    return "<li><b>" in field_html and "<b>Câu hỏi:" in field_html


def clean_note_text(field_html: str) -> str:
    text = strip_html(remove_generated_block(field_html))
    text = IMAGE_IMPORT_ID_PATTERN.sub(" ", text)
    return WHITESPACE_PATTERN.sub(" ", text).strip()


def _html_text(value: str) -> str:
    return html.escape(value, quote=False)


def _format_multi_line(value: str) -> str:
    if not value:
        return ""
    text = html.escape(value, quote=False)
    if "|" in text:
        parts = [p.strip() for p in text.split("|") if p.strip()]
        return "<br>" + "<br>".join(f"• {p}" for p in parts)
        
    # Break after 」 if not followed by punctuation or another bracket
    pattern_closing = re.compile(r'([」])\s*([^」\s。、.!,?])')
    text = pattern_closing.sub(r'\1<br>\2', text)
    
    # Break before A, B, C or names before 「
    pattern_speaker = re.compile(r'(\s+|[。])([A-ZＡ-Ｚ]\s*[「:：])')
    text = pattern_speaker.sub(r'\1<br>\2', text)
    
    # Clean up double <br>
    text = re.sub(r'(<br>\s*)+', '<br>', text)
    text = text.replace('<br> ', '<br>')
    if text.startswith('<br>'):
        text = text[4:]
    text = text.replace(' <br>', '<br>')
        
    return text


def _option_matches_answer(option: AnswerOption, answer: str) -> bool:
    normalized_option = WHITESPACE_PATTERN.sub("", option.text).lower()
    normalized_answer = WHITESPACE_PATTERN.sub("", answer).lower()
    return bool(normalized_answer) and normalized_option == normalized_answer


def _label_number(label: str) -> int | None:
    text = label.strip()
    if len(text) == 1 and "\u2460" <= text <= "\u2473":
        return ord(text) - ord("\u2460") + 1
    match = re.search(r"\d{1,2}", text)
    if match:
        return int(match.group(0))
    return None


def _ordered_options(correct_order: str, options: list[AnswerOption]) -> list[AnswerOption]:
    option_by_number = {
        number: option
        for option in options
        if (number := _label_number(option.label)) is not None
    }
    ordered: list[AnswerOption] = []
    seen: set[int] = set()
    for match in ORDER_LABEL_PATTERN.finditer(correct_order or ""):
        number = _label_number(match.group(0))
        if number is None or number in seen or number not in option_by_number:
            continue
        ordered.append(option_by_number[number])
        seen.add(number)
    return ordered


def _compose_star_sentence(question: str, ordered: list[AnswerOption]) -> tuple[str, int | None]:
    if not question or not ordered:
        return "", None
    for match in PLACEHOLDER_GROUP_PATTERN.finditer(question):
        group = match.group(0)
        if "★" not in group:
            continue
        tokens = PLACEHOLDER_TOKEN_PATTERN.findall(group)
        try:
            star_index = tokens.index("★")
        except ValueError:
            star_index = None
        if len(tokens) != len(ordered):
            continue
        sentence = f"{question[:match.start()]}{''.join(option.text for option in ordered)}{question[match.end():]}"
        return WHITESPACE_PATTERN.sub(" ", sentence).strip(), star_index
    return "", None


def _sentence_has_ordered_fragments(sentence: str, ordered: list[AnswerOption]) -> bool:
    compact_sentence = WHITESPACE_PATTERN.sub("", sentence or "")
    if not compact_sentence:
        return False
    cursor = 0
    for option in ordered:
        compact_option = WHITESPACE_PATTERN.sub("", option.text or "")
        if not compact_option:
            continue
        index = compact_sentence.find(compact_option, cursor)
        if index == -1:
            return False
        cursor = index + len(compact_option)
    return True


def normalize_word_order_payload(payload: dict[str, Any]) -> dict[str, Any]:
    answer_options = [option for option in (payload.get("answer_options") or []) if isinstance(option, AnswerOption)]
    ordered = _ordered_options(str(payload.get("correct_order") or ""), answer_options)
    if not ordered:
        return payload

    normalized = dict(payload)
    existing_completed = str(payload.get("completed_sentence") or "")
    completed_sentence, star_index = _compose_star_sentence(str(payload.get("japanese_question") or ""), ordered)
    if existing_completed and _sentence_has_ordered_fragments(existing_completed, ordered):
        normalized["completed_sentence"] = existing_completed
    elif completed_sentence:
        normalized["completed_sentence"] = completed_sentence
    if star_index is None or star_index >= len(ordered):
        return normalized

    star_option = ordered[star_index]
    normalized["answer"] = f"{star_option.label} {star_option.text}".strip()
    if star_option.romaji:
        normalized["romaji_answer"] = star_option.romaji
    if star_option.vietnamese:
        normalized["vietnamese_answer"] = star_option.vietnamese
    normalized["answer_options"] = [
        replace(option, is_correct=_label_number(option.label) == _label_number(star_option.label))
        for option in answer_options
    ]
    return normalized


def _extract_generated_value(field_html: str, label: str) -> str:
    pattern = re.compile(rf"<p><b>{re.escape(label)}:</b>\s*(.*?)</p>", re.DOTALL | re.IGNORECASE)
    match = pattern.search(field_html or "")
    if not match:
        return ""
    return strip_html(match.group(1))


def _extract_generated_options(field_html: str) -> list[str]:
    match = re.search(r"<p><b>Các lựa chọn:</b></p>\s*<ul>(.*?)</ul>", field_html or "", re.DOTALL | re.IGNORECASE)
    if not match:
        return []

    options: list[str] = []
    for item in re.findall(r"<li>(.*?)</li>", match.group(1), re.DOTALL | re.IGNORECASE):
        option_match = re.search(r"<b>(.*?)</b>", item, re.DOTALL | re.IGNORECASE)
        text = strip_html(option_match.group(1) if option_match else item)
        if text:
            options.append(text)
    return options


def parse_generated_back_for_front_ocr(back_html: str) -> tuple[str, list[str]]:
    question = _extract_generated_value(back_html, "Câu hỏi")
    options = _extract_generated_options(back_html)
    return question, options


def extract_legacy_ocr_text(back_html: str) -> str:
    match = re.search(r"<b>OCR:</b>\s*<br>\s*<pre[^>]*>(.*?)</pre>", back_html or "", re.DOTALL | re.IGNORECASE)
    if not match:
        return ""
    return html.unescape(match.group(1)).strip()


def _is_front_ocr_header(line: str) -> bool:
    lowered = line.lower()
    if not line:
        return True
    if re.match(r"^20\d{2}\s*年", line):
        return True
    return any(
        marker in lowered
        for marker in (
            "toản sensei",
            "toan sensei",
            "tổng hợp",
            "tong hop",
            "luyện",
            "luyen",
            "jlpt",
            "like",
            "share",
            "subscribe",
        )
    )


def parse_ocr_text_for_front(raw_ocr: str) -> tuple[str, list[str]]:
    lines = [
        WHITESPACE_PATTERN.sub(" ", line).strip()
        for line in (raw_ocr or "").splitlines()
    ]
    lines = [line for line in lines if line and not _is_front_ocr_header(line)]

    question_lines: list[str] = []
    options: list[str] = []
    pending_label = ""

    for line in lines:
        inline_match = INLINE_OPTION_PATTERN.match(line)
        if pending_label:
            options.append(f"{pending_label} {line}".strip())
            pending_label = ""
            continue
        if OPTION_LABEL_PATTERN.match(line):
            pending_label = line
            continue
        if inline_match and JAPANESE_PATTERN.search(inline_match.group("text")):
            label = inline_match.group("label")
            if not question_lines and not label.startswith(("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨")):
                question_lines.append(line)
                continue
            options.append(f"{inline_match.group('label')} {inline_match.group('text')}".strip())
            continue
        if JAPANESE_PATTERN.search(line):
            question_lines.append(line)

    question = WHITESPACE_PATTERN.sub(" ", " ".join(question_lines)).strip()
    return question, options


def render_front_ocr_block(question: str, options: list[str], raw_ocr: str = "") -> str:
    lines = [
        '<div class="anki-ocr-front">',
        "<hr>",
    ]
    if question:
        lines.append(f"<p><b>OCR câu hỏi:</b> {_format_multi_line(question)}</p>")
    if options:
        lines.append("<p><b>OCR lựa chọn:</b></p>")
        lines.append("<ul>")
        for option in options:
            lines.append(f"<li>{_html_text(option)}</li>")
        lines.append("</ul>")
    if not question and not options and raw_ocr.strip():
        lines.append("<p><b>OCR từ ảnh:</b></p>")
        lines.append(f'<pre style="white-space:pre-wrap">{_html_text(raw_ocr.strip())}</pre>')
    lines.append("</div>")
    return "\n".join(lines)


def render_back_block(payload: dict[str, Any]) -> str:
    payload = normalize_word_order_payload(payload)
    lines = [
        '<div class="anki-ocr-answer">',
        "<hr>",
    ]
    if payload.get("answer"):
        lines.append(f"<p><b>Đáp án:</b> {_html_text(payload['answer'])}</p>")
    if payload.get("japanese_question"):
        lines.append(f"<p><b>Câu hỏi:</b> {_format_multi_line(payload['japanese_question'])}</p>")
    if payload.get("romaji_question"):
        lines.append(f"<p><b>Romaji câu hỏi:</b> {_format_multi_line(payload['romaji_question'])}</p>")
    if payload.get("vietnamese_question"):
        lines.append(f"<p><b>Dịch câu hỏi:</b> {_format_multi_line(payload['vietnamese_question'])}</p>")
    if payload.get("romaji_answer"):
        lines.append(f"<p><b>Romaji đáp án:</b> {_html_text(payload['romaji_answer'])}</p>")
    if payload.get("vietnamese_answer"):
        lines.append(f"<p><b>Dịch đáp án:</b> {_html_text(payload['vietnamese_answer'])}</p>")
    if payload.get("completed_sentence"):
        lines.append(f"<p><b>Câu hoàn chỉnh:</b> {_html_text(payload['completed_sentence'])}</p>")
    if payload.get("correct_order"):
        lines.append(f"<p><b>Thứ tự đúng:</b> {_html_text(payload['correct_order'])}</p>")
    answer_options = payload.get("answer_options") or []
    if answer_options:
        lines.append("<p><b>Các lựa chọn:</b></p>")
        lines.append("<ul>")
        for option in answer_options:
            if not isinstance(option, AnswerOption):
                continue
            is_correct = option.is_correct or _option_matches_answer(option, str(payload.get("answer", "")))
            status = "Đúng" if is_correct else "Sai"
            label = f"{option.label} " if option.label else ""
            detail_parts = []
            if option.romaji:
                detail_parts.append(f"Romaji: {_html_text(option.romaji)}")
            if option.vietnamese:
                detail_parts.append(f"Dịch: {_html_text(option.vietnamese)}")
            if option.note:
                detail_parts.append(f"Ghi chú: {_html_text(option.note)}")
            detail = " | ".join(detail_parts)
            if detail:
                detail = f" - {detail}"
            lines.append(
                f"<li><b>{_html_text(label + option.text)}</b> "
                f"(<i>{status}</i>){detail}</li>"
            )
        lines.append("</ul>")
    if payload.get("grammar_note"):
        lines.append(f"<p><b>Ghi chú ôn tập:</b> {_html_text(payload['grammar_note'])}</p>")
    lines.append("</div>")
    return "\n".join(lines)


def merge_back_block(existing_html: str, back_block: str) -> str:
    cleaned = remove_generated_block(existing_html)
    if cleaned:
        return f"{cleaned}\n{back_block}"
    return back_block


def merge_front_ocr_block(existing_html: str, front_block: str) -> str:
    cleaned = remove_front_ocr_block(existing_html)
    if cleaned:
        return f"{cleaned}\n{front_block}"
    return front_block


def process_front_ocr_deck(
    client: AnkiConnectClient,
    config: FrontOcrConfig,
    logger: Callable[[str], None] | None = None,
    note_callback: Callable[[FrontOcrNote], None] | None = None,
) -> list[FrontOcrNote]:
    def log(message: str) -> None:
        if logger is not None:
            logger(message)

    note_ids = client.deck_notes(config.deck)
    start_index = max(config.start_index, 1)
    if config.end_index is not None and config.end_index < start_index:
        note_ids = []
    else:
        note_ids = note_ids[start_index - 1 : config.end_index]
    if config.limit is not None:
        note_ids = note_ids[: config.limit]

    report_rows: list[str] = [f"# Front OCR report: {config.deck}", ""]
    notes = client.notes_info(note_ids)
    processed: list[FrontOcrNote] = []
    total_notes = len(notes)
    log(f"Tìm thấy {total_notes} note trong deck '{config.deck}' để cập nhật OCR mặt trước.")

    def write_report() -> None:
        config.report_path.parent.mkdir(parents=True, exist_ok=True)
        config.report_path.write_text("\n".join(report_rows), encoding="utf-8")

    for index, note in enumerate(notes, start=1):
        fields = note.get("fields", {})
        note_id = int(note["noteId"])
        front_html = fields.get(config.front_field, {}).get("value", "")
        back_html = fields.get(config.back_field, {}).get("value", "")
        log(f"[{index}/{total_notes}] Note {note_id}: chuẩn bị OCR mặt trước.")

        if config.skip_existing and has_front_ocr_block(front_html):
            result = FrontOcrNote(
                note_id=note_id,
                ocr_files=[],
                question="",
                options=[],
                raw_ocr="",
                front_block="",
                updated=False,
                skipped_reason="existing-front-ocr-block",
            )
            processed.append(result)
            if note_callback is not None:
                note_callback(result)
            write_report()
            continue

        question, options = parse_generated_back_for_front_ocr(back_html)
        raw_ocr = ""
        ocr_files: list[str] = []

        if not question or not options:
            raw_ocr = extract_legacy_ocr_text(back_html)
            if raw_ocr:
                parsed_question, parsed_options = parse_ocr_text_for_front(raw_ocr)
                if not question:
                    question = parsed_question
                if not options:
                    options = parsed_options

        if (not question or not options) and not raw_ocr:
            media_sources = extract_image_sources(front_html)
            log(f"[{index}/{total_notes}] Note {note_id}: OCR {len(media_sources)} ảnh ở mặt trước.")
            ocr_assets = ocr_media_sources(media_sources, client.retrieve_media_file, config.ocr_lang)
            ocr_files = [asset.filename for asset in ocr_assets]
            raw_ocr = "\n".join(asset.text for asset in ocr_assets if asset.text)
            parsed_question, parsed_options = parse_ocr_text_for_front(raw_ocr)
            if not question:
                question = parsed_question
            if not options:
                options = parsed_options

        front_block = render_front_ocr_block(question, options, raw_ocr)
        if front_block == render_front_ocr_block("", [], ""):
            result = FrontOcrNote(
                note_id=note_id,
                ocr_files=ocr_files,
                question=question,
                options=options,
                raw_ocr=raw_ocr,
                front_block="",
                updated=False,
                skipped_reason="no-front-ocr-content",
            )
            processed.append(result)
            if note_callback is not None:
                note_callback(result)
            write_report()
            continue

        new_front = merge_front_ocr_block(front_html, front_block)
        updated = False
        if not config.dry_run:
            if config.front_field not in fields:
                raise ValueError(f"Field '{config.front_field}' không tồn tại ở note {note_id}")
            client.update_note_fields(note_id, {config.front_field: new_front})
            updated = True
            log(f"[{index}/{total_notes}] Note {note_id}: đã ghi OCR mặt trước.")
        else:
            log(f"[{index}/{total_notes}] Note {note_id}: dry-run, chưa ghi vào Anki.")

        result = FrontOcrNote(
            note_id=note_id,
            ocr_files=ocr_files,
            question=question,
            options=options,
            raw_ocr=raw_ocr,
            front_block=front_block,
            updated=updated,
        )
        processed.append(result)
        if note_callback is not None:
            note_callback(result)

        report_rows.append(f"## Note {note_id}")
        report_rows.append("")
        report_rows.append(f"- OCR files: {', '.join(ocr_files) if ocr_files else 'from-back'}")
        report_rows.append(f"- Question: {question or 'none'}")
        report_rows.append(f"- Options: {', '.join(options) if options else 'none'}")
        report_rows.append("")
        report_rows.append(front_block)
        report_rows.append("")
        write_report()

    write_report()
    return processed


def process_deck(
    client: AnkiConnectClient,
    config: ProcessConfig,
    logger: Callable[[str], None] | None = None,
    note_callback: Callable[[ProcessedNote], None] | None = None,
) -> list[ProcessedNote]:
    def log(message: str) -> None:
        if logger is not None:
            logger(message)

    note_ids = client.deck_notes(config.deck)
    start_index = max(config.start_index, 1)
    if config.end_index is not None and config.end_index < start_index:
        note_ids = []
    else:
        note_ids = note_ids[start_index - 1 : config.end_index]
    if config.limit is not None:
        note_ids = note_ids[: config.limit]

    report_rows: list[str] = [f"# OCR report: {config.deck}", ""]
    notes = client.notes_info(note_ids)
    processed: list[ProcessedNote] = []
    total_notes = len(notes)
    log(f"Tìm thấy {total_notes} note trong deck '{config.deck}'. Model: {config.model}.")

    if not notes:
        log(f"Không tìm thấy note nào trong deck: {config.deck}")
        config.report_path.parent.mkdir(parents=True, exist_ok=True)
        config.report_path.write_text("\n".join(report_rows), encoding="utf-8")
        return processed

    def write_report() -> None:
        config.report_path.parent.mkdir(parents=True, exist_ok=True)
        config.report_path.write_text("\n".join(report_rows), encoding="utf-8")

    for index, note in enumerate(notes, start=1):
        fields = note.get("fields", {})
        note_id = int(note["noteId"])
        log(f"[{index}/{total_notes}] Note {note_id}: bắt đầu.")
        question_html = fields.get(config.front_field, {}).get("value", "")
        answer_html = remove_generated_block(fields.get(config.back_field, {}).get("value", ""))
        question_text = clean_note_text(question_html)
        answer_text = clean_note_text(answer_html)
        target_value = fields.get(config.target_field, {}).get("value", "")

        if config.skip_existing and has_generated_block(target_value):
            result = ProcessedNote(
                note_id=note_id,
                ocr_files=[],
                ocr_text="",
                question=question_text,
                answer=answer_text,
                back_block="",
                updated=False,
                skipped_reason="existing-generated-block",
            )
            processed.append(result)
            if note_callback is not None:
                note_callback(result)
            log(f"[{index}/{total_notes}] Note {note_id}: bỏ qua vì đã có block anki-ocr-answer.")
            write_report()
            continue

        if config.skip_complete and has_complete_generated_block(target_value):
            result = ProcessedNote(
                note_id=note_id,
                ocr_files=[],
                ocr_text="",
                question=question_text,
                answer=answer_text,
                back_block="",
                updated=False,
                skipped_reason="complete-generated-block",
            )
            processed.append(result)
            if note_callback is not None:
                note_callback(result)
            log(f"[{index}/{total_notes}] Note {note_id}: bỏ qua vì đã có đủ các lựa chọn.")
            write_report()
            continue

        media_sources: list[str] = []
        for field_data in fields.values():
            media_sources.extend(extract_image_sources(field_data.get("value", "")))
        media_sources = list(dict.fromkeys(media_sources))
        log(f"[{index}/{total_notes}] Note {note_id}: OCR {len(media_sources)} ảnh.")

        ocr_assets = ocr_media_sources(media_sources, client.retrieve_media_file, config.ocr_lang)
        ocr_text = "\n".join(asset.text for asset in ocr_assets if asset.text)
        log(f"[{index}/{total_notes}] Note {note_id}: OCR xong, gọi LLM.")

        has_image_payload = any(asset.image_base64 for asset in ocr_assets)
        if not ocr_text.strip() and not question_text and not has_image_payload:
            result = ProcessedNote(
                note_id=note_id,
                ocr_files=[asset.filename for asset in ocr_assets],
                ocr_text=ocr_text,
                question=question_text,
                answer=answer_text,
                back_block="",
                updated=False,
                skipped_reason="no-readable-content",
            )
            processed.append(result)
            if note_callback is not None:
                note_callback(result)
            log(f"Bỏ qua note {note_id}: không có ảnh hoặc text đủ rõ.")
            write_report()
            continue

        enriched: EnrichmentResult = enrich_card(
            ocr_text=ocr_text,
            original_question=question_text,
            original_answer=answer_text,
            model=config.model,
            base_url=config.base_url,
            image_data_urls=[
                f"data:{asset.mime_type};base64,{asset.image_base64}"
                for asset in ocr_assets
                if asset.image_base64
            ],
            logger=log,
        )

        if enriched.error_message:
            result = ProcessedNote(
                note_id=note_id,
                ocr_files=[asset.filename for asset in ocr_assets],
                ocr_text=ocr_text,
                question=question_text,
                answer=answer_text,
                back_block="",
                updated=False,
                skipped_reason="llm-error",
            )
            processed.append(result)
            if note_callback is not None:
                note_callback(result)
            log(f"[{index}/{total_notes}] Note {note_id}: LLM lỗi, chưa ghi vào Anki. {enriched.error_message}")
            report_rows.append(f"## Note {note_id}")
            report_rows.append("")
            report_rows.append(f"- OCR files: {', '.join(result.ocr_files) if result.ocr_files else 'none'}")
            report_rows.append(f"- OCR text: {result.ocr_text or 'none'}")
            report_rows.append(f"- Error: {enriched.error_message}")
            report_rows.append("")
            write_report()
            continue

        payload = {
            "answer": enriched.answer,
            "japanese_question": enriched.japanese_question,
            "romaji_question": enriched.romaji_question,
            "vietnamese_question": enriched.vietnamese_question,
            "romaji_answer": enriched.romaji_answer,
            "vietnamese_answer": enriched.vietnamese_answer,
            "completed_sentence": enriched.completed_sentence,
            "correct_order": enriched.correct_order,
            "answer_options": enriched.answer_options,
            "grammar_note": enriched.grammar_note,
        }
        back_block = render_back_block(payload)
        new_target_value = merge_back_block(target_value, back_block)

        updated = False
        if not config.dry_run:
            if config.target_field not in fields:
                raise ValueError(f"Field '{config.target_field}' không tồn tại ở note {note_id}")
            client.update_note_fields(note_id, {config.target_field: new_target_value})
            updated = True
            log(f"[{index}/{total_notes}] Note {note_id}: đã ghi vào Anki.")
        else:
            log(f"[{index}/{total_notes}] Note {note_id}: dry-run, chưa ghi vào Anki.")

        result = ProcessedNote(
            note_id=note_id,
            ocr_files=[asset.filename for asset in ocr_assets],
            ocr_text=ocr_text,
            question=question_text,
            answer=answer_text,
            back_block=back_block,
            updated=updated,
        )
        processed.append(result)
        if note_callback is not None:
            note_callback(result)

        report_rows.append(f"## Note {note_id}")
        report_rows.append("")
        report_rows.append(f"- OCR files: {', '.join(result.ocr_files) if result.ocr_files else 'none'}")
        report_rows.append(f"- OCR text: {result.ocr_text or 'none'}")
        report_rows.append(f"- Question: {result.question}")
        report_rows.append(f"- Answer: {result.answer}")
        report_rows.append("")
        report_rows.append(back_block)
        report_rows.append("")
        write_report()

    write_report()
    return processed
