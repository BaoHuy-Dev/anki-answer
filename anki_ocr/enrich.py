from __future__ import annotations

import ast
import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from openai import OpenAI


@dataclass
class AnswerOption:
    label: str
    text: str
    romaji: str
    vietnamese: str
    is_correct: bool
    note: str = ""


@dataclass
class EnrichmentResult:
    answer: str
    japanese_question: str
    romaji_question: str
    vietnamese_question: str
    romaji_answer: str
    vietnamese_answer: str
    completed_sentence: str
    correct_order: str
    answer_options: list[AnswerOption]
    grammar_note: str
    error_message: str = ""


SYSTEM_PROMPT = """You are a Japanese learning assistant for Anki cards.
Return only valid JSON. Do not add markdown fences or any explanation outside JSON.

Tasks:
- Read the OCR text and the original Anki fields.
- Infer the correct answer when possible.
- If the question has a blank such as ( ), fill it with the most natural short answer.
- If multiple-choice options are visible, choose the best correct option.
- Extract every visible option, including wrong options.
- Extract the original Japanese question sentence or prompt from the image.
- Preserve blanks such as ( ) in the extracted Japanese question.
- Do not include the multiple-choice option list inside "japanese_question".
- Detect the question type and tailor the explanation:
  - Fill-in-the-blank: explain the key vocabulary or grammar pattern.
  - Synonym questions: explain why the correct option has the same meaning as the target word or phrase, and how the wrong options differ.
  - Word-usage questions: choose the sentence where the target word is used naturally, and explain why each wrong sentence is unnatural.
  - Word-order/star questions: reorder all visible fragments into the most natural full sentence, identify the fragment at the ★ position, and explain the grammar or collocation that fixes the order.
- Convert the question to romaji.
- Translate the question to Vietnamese.
- Convert the correct answer to romaji.
- Translate the correct answer to Vietnamese.
- For every option, provide romaji, Vietnamese translation, whether it is correct, and a short Vietnamese note useful for review.
- Write a short Vietnamese study note focused on the main useful point.

Rules:
- "answer" must be concise: for fill-in or synonym questions, return the correct word/phrase; for word-usage questions, return the correct option label and sentence; for word-order/star questions, return the option label and fragment that belongs at ★.
- For word-order/star questions, use the number of fragments needed by the blank slots. Some questions use all four visible options; some use only three and leave one distractor unused.
- For word-order/star questions, if the prompt shows four blanks like "____ ____ ★ ____", ★ is the third blank. The answer is the option placed in that third blank.
- For word-order/star questions, "completed_sentence" must contain every fragment listed in "correct_order" exactly once and no blank markers.
- For word-order/star questions, "correct_order" must list all option labels/fragments in sentence order, for example "① → ④ → ③ → ②".
- Before returning a word-order/star answer, self-check that every fragment named in "correct_order" appears in "completed_sentence" in the same order. If any fragment is missing, fix the sentence before returning JSON.
- "answer_options" must include both correct and wrong options if options are visible.
- Mark "is_correct" true only for the correct option(s).
- For word-order/star questions, mark "is_correct" true only for the option that belongs at ★, not every fragment used in the completed sentence.
- When translating short particles such as か, の, と, を, translate their function in Vietnamese instead of copying the romaji.
- Keep option notes brief, concrete, and easy to review in Anki.
- Use empty strings only when the information is impossible to infer.

Word-order/star examples:
- Prompt: 昨日、本屋で小説2冊____ ____ ★ ____本を1冊買った。 Options: ① と, ② の, ③ について, ④ レポートの書き方. Correct order: ① → ④ → ③ → ②. Answer at ★: ③ について. Completed sentence: 昨日、本屋で小説2冊とレポートの書き方についての本を1冊買った。
- Prompt: さくら大学の周りには、レストランや喫茶店などの____ ____ ★ ____ある。 Options: ① 中心に, ② 飲食店を, ③ いろいろな店が, ④ 本屋や美容院など. Correct order: ② → ① → ④ → ③. Answer at ★: ④ 本屋や美容院など. Completed sentence: さくら大学の周りには、レストランや喫茶店などの飲食店を中心に、本屋や美容院などいろいろな店がある。
- Prompt: 弾けば( ) ( ) ★ ( ) 自分でもわかり、とても楽しい。 Options: ① 上手に, ② ひくほど, ③ なっていくのが, ④ 弾けるように. Correct order: ② → ① → ④ → ③. Answer at ★: ④ 弾けるように. Completed sentence: 弾けばひくほど上手に弾けるようになっていくのが自分でもわかり、とても楽しい。

Schema:
{
  "answer": "...",
  "japanese_question": "...",
  "romaji_question": "...",
  "vietnamese_question": "...",
  "romaji_answer": "...",
  "vietnamese_answer": "...",
  "completed_sentence": "...",
  "correct_order": "...",
  "answer_options": [
    {
      "label": "①",
      "text": "...",
      "romaji": "...",
      "vietnamese": "...",
      "is_correct": true,
      "note": "..."
    }
  ],
  "grammar_note": "..."
}
"""

GEMINI_OPENAI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
DEFAULT_GEMINI_KEY_NAMES = ["GEMINI_API_KEY", *[f"GEMINI_API_KEY_{index}" for index in range(1, 10)]]
REQUEST_TIMEOUT_SECONDS = 60
MAX_RATE_LIMIT_ROUNDS = 4
MAX_RATE_LIMIT_SLEEP_SECONDS = 75
_NEXT_KEY_INDEX = 0


def get_env_var(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if value or os.name != "nt":
        return value

    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            registry_value, _ = winreg.QueryValueEx(key, name)
    except OSError:
        return ""
    return str(registry_value).strip()


def _parse_json_payload(content: str) -> dict[str, Any]:
    text = content.strip()
    if not text:
        return {}

    try:
        payload = json.loads(text)
        if isinstance(payload, dict):
            return payload
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = text[start : end + 1]
        try:
            payload = json.loads(candidate)
            if isinstance(payload, dict):
                return payload
        except json.JSONDecodeError:
            try:
                payload = ast.literal_eval(candidate)
                if isinstance(payload, dict):
                    return payload
            except (ValueError, SyntaxError):
                return {}

    return {}


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "correct", "đúng", "dung"}
    return bool(value)


def _parse_answer_options(payload: dict[str, Any]) -> list[AnswerOption]:
    raw_options = payload.get("answer_options") or payload.get("choices") or payload.get("options") or []
    if not isinstance(raw_options, list):
        return []

    options: list[AnswerOption] = []
    for index, item in enumerate(raw_options, start=1):
        if isinstance(item, str):
            text = item.strip()
            if text:
                options.append(AnswerOption(label=str(index), text=text, romaji="", vietnamese="", is_correct=False))
            continue
        if not isinstance(item, dict):
            continue

        text = str(item.get("text") or item.get("answer") or item.get("value") or "").strip()
        if not text:
            continue
        options.append(
            AnswerOption(
                label=str(item.get("label") or item.get("number") or item.get("key") or index).strip(),
                text=text,
                romaji=str(item.get("romaji") or "").strip(),
                vietnamese=str(item.get("vietnamese") or item.get("translation") or "").strip(),
                is_correct=_as_bool(item.get("is_correct") or item.get("correct") or False),
                note=str(item.get("note") or item.get("explanation") or item.get("reason") or "").strip(),
            )
        )
    return options


def _is_gemini_model(model: str) -> bool:
    return model.strip().lower().startswith("gemini")


def _api_key_candidates(model: str) -> tuple[list[tuple[str, str]], str]:
    if _is_gemini_model(model):
        names = DEFAULT_GEMINI_KEY_NAMES
        missing_name = "GEMINI_API_KEY"
    else:
        names = ["OPENAI_API_KEY"]
        missing_name = "OPENAI_API_KEY"

    seen_values: set[str] = set()
    candidates: list[tuple[str, str]] = []
    for name in names:
        value = get_env_var(name)
        if value and value not in seen_values:
            candidates.append((name, value))
            seen_values.add(value)
    return candidates, missing_name


def _rotated_api_keys(api_keys: list[tuple[str, str]]) -> list[tuple[str, str]]:
    global _NEXT_KEY_INDEX
    if not api_keys:
        return []
    start = _NEXT_KEY_INDEX % len(api_keys)
    return [*api_keys[start:], *api_keys[:start]]


def _mark_key_success(api_keys: list[tuple[str, str]], key_name: str) -> None:
    global _NEXT_KEY_INDEX
    for index, (candidate_name, _) in enumerate(api_keys):
        if candidate_name == key_name:
            _NEXT_KEY_INDEX = index + 1
            return


def _client_for_model(model: str, api_key: str, base_url: str | None) -> OpenAI:
    if base_url:
        return OpenAI(api_key=api_key, base_url=base_url, timeout=REQUEST_TIMEOUT_SECONDS)
    if _is_gemini_model(model):
        return OpenAI(api_key=api_key, base_url=GEMINI_OPENAI_BASE_URL, timeout=REQUEST_TIMEOUT_SECONDS)
    return OpenAI(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS)


def _safe_error_message(exc: Exception, api_key: str) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return message.replace(api_key, "[redacted]")


def _is_rate_limit_error(message: str) -> bool:
    lowered = message.lower()
    return "429" in lowered or "resource_exhausted" in lowered or "quota exceeded" in lowered or "rate limit" in lowered


def _retry_delay_seconds(message: str) -> float:
    matches = [
        re.search(r"retry in ([0-9.]+)s", message, re.IGNORECASE),
        re.search(r"retry_delay[^0-9]+([0-9.]+)", message, re.IGNORECASE),
    ]
    for match in matches:
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return 0.0
    return 0.0


def _build_user_content(user_prompt: str, image_data_urls: list[str] | None) -> str | list[dict[str, Any]]:
    if not image_data_urls:
        return user_prompt

    content: list[dict[str, Any]] = [
        {
            "type": "text",
            "text": user_prompt + "\n\nUse the attached image(s) to recover any option text that OCR missed.",
        }
    ]
    for image_url in image_data_urls:
        content.append({"type": "image_url", "image_url": {"url": image_url}})
    return content


def enrich_card(
    ocr_text: str,
    original_question: str,
    original_answer: str,
    model: str,
    base_url: str | None = None,
    image_data_urls: list[str] | None = None,
    logger: Callable[[str], None] | None = None,
) -> EnrichmentResult:
    api_keys, provider_name = _api_key_candidates(model)
    if not api_keys:
        return EnrichmentResult(
            answer=original_answer or ocr_text,
            japanese_question="",
            romaji_question="",
            vietnamese_question="",
            romaji_answer="",
            vietnamese_answer="",
            completed_sentence="",
            correct_order="",
            answer_options=[],
            grammar_note="",
            error_message=f"Chưa có {provider_name} nên chưa sinh romaji/dịch/ngữ pháp.",
        )

    user_prompt = (
        "OCR text:\n"
        f"{ocr_text}\n\n"
        "Original question field:\n"
        f"{original_question}\n\n"
        "Original answer field:\n"
        f"{original_answer}\n"
    )
    user_content = _build_user_content(user_prompt, image_data_urls)
    content = "{}"
    last_error = ""
    for round_index in range(1, MAX_RATE_LIMIT_ROUNDS + 1):
        rate_limit_wait = 0.0
        for key_name, api_key in _rotated_api_keys(api_keys):
            client = _client_for_model(model, api_key, base_url)
            try:
                response = client.chat.completions.create(
                    model=model,
                    temperature=0,
                    messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
            )
                content = response.choices[0].message.content or "{}"
                _mark_key_success(api_keys, key_name)
                last_error = ""
                break
            except Exception as exc:  # noqa: BLE001
                safe_error = _safe_error_message(exc, api_key)
                last_error = f"{key_name}: {safe_error}"
                if _is_rate_limit_error(safe_error):
                    rate_limit_wait = max(rate_limit_wait, _retry_delay_seconds(safe_error) or 35.0)
                    continue
        if not last_error:
            break
        if rate_limit_wait <= 0 or round_index >= MAX_RATE_LIMIT_ROUNDS:
            break

        sleep_seconds = min(rate_limit_wait + 2, MAX_RATE_LIMIT_SLEEP_SECONDS)
        if logger is not None:
            logger(f"Tất cả API key đang bị giới hạn quota, chờ {sleep_seconds:.0f}s rồi thử lại.")
        time.sleep(sleep_seconds)

    if last_error:
        return EnrichmentResult(
            answer=original_answer or ocr_text,
            japanese_question="",
            romaji_question="",
            vietnamese_question="",
            romaji_answer="",
            vietnamese_answer="",
            completed_sentence="",
            correct_order="",
            answer_options=[],
            grammar_note="",
            error_message=f"Lỗi khi gọi LLM ({last_error}).",
        )

    payload = _parse_json_payload(content)
    answer_options = _parse_answer_options(payload)
    return EnrichmentResult(
        answer=str(payload.get("answer", "")).strip(),
        japanese_question=str(payload.get("japanese_question") or payload.get("question") or "").strip(),
        romaji_question=str(payload.get("romaji_question", "")).strip(),
        vietnamese_question=str(payload.get("vietnamese_question", "")).strip(),
        romaji_answer=str(payload.get("romaji_answer", "")).strip(),
        vietnamese_answer=str(payload.get("vietnamese_answer", "")).strip(),
        completed_sentence=str(payload.get("completed_sentence", "")).strip(),
        correct_order=str(payload.get("correct_order", "")).strip(),
        answer_options=answer_options,
        grammar_note=str(payload.get("grammar_note", "")).strip(),
    )
