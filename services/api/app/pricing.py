from __future__ import annotations

import json
import math
import os

from .models import CourseDraft, TranscriptSegment


MODEL = "qwen3.7-flash"

# Qwen3.7-Flash international (Singapore), CNY per 1M tokens.
# Cache discounts are deliberately excluded: a newly recorded transcript is not
# expected to hit the prompt cache, so this is the safer amount to show users.
PRICE_TIERS = (
    (32_000, 0.225, 0.974, "INPUT <= 32K"),
    (256_000, 0.749, 2.998, "32K < INPUT <= 256K"),
    (1_000_000, 1.495, 5.995, "256K < INPUT <= 1M"),
)

SYSTEM_PROMPT = """你是课程纪要 Agent。根据带时间戳的英文原文和中文译文重新理解并总结课程，不要逐句复制。
输出简洁中文摘要、经过归纳的知识点、任务/上课/DDL、更正关系、待确认信息和分层脑图。
任何日期不完整时必须标记 pending_confirmation；不得猜测年月日。每个日程项必须引用输入中真实存在的 segment_id。
仅返回符合 JSON Schema 的 JSON。"""


def _text_tokens(text: str) -> int:
    """Conservative tokenizer-free estimate for mixed English/Chinese text."""
    ascii_count = sum(ord(char) < 128 for char in text)
    non_ascii_count = len(text) - ascii_count
    return math.ceil(ascii_count / 3.6 + non_ascii_count / 1.25)


def estimate_organize(transcript: list[TranscriptSegment]) -> dict:
    transcript_json = json.dumps([segment.model_dump() for segment in transcript], ensure_ascii=False)
    schema_json = json.dumps(CourseDraft.model_json_schema(), ensure_ascii=False)
    input_tokens = _text_tokens(SYSTEM_PROMPT) + _text_tokens(transcript_json) + _text_tokens(schema_json) + 180
    # Structured notes are normally 7–12% of the transcript. Keep a useful
    # minimum for short recordings and cap the estimate for a one-pass draft.
    output_tokens = min(4_000, max(800, math.ceil(input_tokens * 0.09)))
    # Used only for the UI countdown. Structured output has a fixed setup cost
    # plus generation time that grows with the requested JSON response.
    estimated_duration_seconds = min(180, max(20, math.ceil(12 + output_tokens / 45)))

    limit, input_rate, output_rate, tier = PRICE_TIERS[-1]
    for candidate in PRICE_TIERS:
        if input_tokens <= candidate[0]:
            limit, input_rate, output_rate, tier = candidate
            break
    input_cost = input_tokens / 1_000_000 * input_rate
    output_cost = output_tokens / 1_000_000 * output_rate
    return {
        "model": os.environ.get("QWEN_TEXT_MODEL", MODEL),
        "currency": "CNY",
        "estimated_input_tokens": input_tokens,
        "estimated_output_tokens": output_tokens,
        "estimated_total_tokens": input_tokens + output_tokens,
        "estimated_input_cost": round(input_cost, 6),
        "estimated_output_cost": round(output_cost, 6),
        "estimated_total_cost": round(input_cost + output_cost, 6),
        "estimated_duration_seconds": estimated_duration_seconds,
        "input_rate_per_million": input_rate,
        "output_rate_per_million": output_rate,
        "pricing_tier": tier,
        "pricing_region": "Singapore (international)",
        "is_estimate": True,
        "cache_assumed": False,
    }
