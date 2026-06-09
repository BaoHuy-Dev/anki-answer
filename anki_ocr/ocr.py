from __future__ import annotations

import base64
import html
import io
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from PIL import Image
import pytesseract

IMAGE_SRC_PATTERN = re.compile(r'<img[^>]+src=["\']([^"\']+)["\']', re.IGNORECASE)
STYLE_SCRIPT_PATTERN = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
TAG_PATTERN = re.compile(r"<[^>]+>")
WHITESPACE_PATTERN = re.compile(r"\s+")


def _user_env_value(name: str) -> str:
    if os.name != "nt":
        return ""
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            value, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return ""
    return str(value)


def configure_tesseract_command() -> None:
    tessdata_prefix = os.environ.get("TESSDATA_PREFIX", "").strip() or _user_env_value("TESSDATA_PREFIX").strip()
    if tessdata_prefix:
        os.environ["TESSDATA_PREFIX"] = os.path.expandvars(tessdata_prefix)

    if shutil.which("tesseract"):
        return

    path_values = [os.environ.get("PATH", ""), _user_env_value("Path")]
    candidates: list[Path] = []
    for path_value in path_values:
        for directory in path_value.split(os.pathsep):
            if directory.strip():
                candidates.append(Path(os.path.expandvars(directory.strip())) / "tesseract.exe")

    candidates.extend(
        [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Tesseract-OCR" / "tesseract.exe",
            Path("C:/Program Files/Tesseract-OCR/tesseract.exe"),
            Path("C:/Program Files (x86)/Tesseract-OCR/tesseract.exe"),
        ]
    )

    for candidate in candidates:
        if candidate.is_file():
            pytesseract.pytesseract.tesseract_cmd = str(candidate)
            return


@dataclass
class OCRAsset:
    filename: str
    text: str
    image_base64: str
    mime_type: str


configure_tesseract_command()


def media_mime_type(filename: str) -> str:
    lower_name = filename.lower()
    if lower_name.endswith(".jpg") or lower_name.endswith(".jpeg"):
        return "image/jpeg"
    if lower_name.endswith(".webp"):
        return "image/webp"
    if lower_name.endswith(".gif"):
        return "image/gif"
    return "image/png"


def extract_image_sources(field_html: str) -> list[str]:
    return list(dict.fromkeys(IMAGE_SRC_PATTERN.findall(field_html or "")))


def strip_html(field_html: str) -> str:
    text = STYLE_SCRIPT_PATTERN.sub(" ", field_html or "")
    text = TAG_PATTERN.sub(" ", text)
    text = html.unescape(text)
    return WHITESPACE_PATTERN.sub(" ", text).strip()


def decode_media_blob(encoded: str) -> bytes:
    return base64.b64decode(encoded)


def ocr_image_bytes(image_bytes: bytes, language: str) -> str:
    with Image.open(io.BytesIO(image_bytes)) as image:
        image.load()
        return pytesseract.image_to_string(image, lang=language).strip()


def ocr_media_sources(
    media_sources: Iterable[str],
    retrieve_media: Callable[[str], str],
    language: str,
) -> list[OCRAsset]:
    results: list[OCRAsset] = []
    for source in media_sources:
        encoded_blob = retrieve_media(source)
        image_bytes = decode_media_blob(encoded_blob)
        text = ocr_image_bytes(image_bytes, language=language)
        results.append(
            OCRAsset(
                filename=source,
                text=text,
                image_base64=encoded_blob,
                mime_type=media_mime_type(source),
            )
        )
    return results
