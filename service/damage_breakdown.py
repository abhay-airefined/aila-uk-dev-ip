import json
import logging
import re
import time
from functools import wraps
from typing import Any, Dict, List, Optional

from service.models import DamageBreakdown
from service.rag_utils import get_llm_response

MAX_DAMAGE_CONTEXT_CHARS = 30000

NUMERIC_PATTERN = re.compile(
    r"(?i)(?:\u00a3|\$|\u20ac|aed|gbp|usd|eur|inr|rs\.?)\s?[\d,]+(?:\.\d+)?"
    r"|[\d,]+(?:\.\d+)?\s?(?:\u00a3|\$|\u20ac|aed|gbp|usd|eur|inr|rs\.?)"
    r"|\b\d+(?:,\d{3})*(?:\.\d+)?\s?(?:%|percent|days?|weeks?|months?|years?|hours?|hrs?|kg|sqm|sq\.?\s?ft)\b"
    r"|\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b"
    r"|\b\d{4}\b"
)

DAMAGE_KEYWORDS = {
    "damage",
    "damages",
    "loss",
    "losses",
    "compensation",
    "salary",
    "wage",
    "pay",
    "arrears",
    "unpaid",
    "refund",
    "deposit",
    "repair",
    "replacement",
    "invoice",
    "bill",
    "expense",
    "cost",
    "costs",
    "fee",
    "fees",
    "interest",
    "penalty",
    "loan",
    "debt",
    "rent",
    "medical",
    "injury",
    "harassment",
    "distress",
    "reputation",
    "reputational",
    "overtime",
    "commission",
    "bonus",
    "notice",
    "redundancy",
    "holiday",
    "pension",
    "termination",
    "breach",
}


def retry_operation(max_attempts=3, delay_seconds=2):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            attempts = 0
            while attempts < max_attempts:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    attempts += 1
                    if attempts == max_attempts:
                        logging.error(f"Failed after {max_attempts} attempts. Error: {str(e)}")
                        raise
                    logging.warning(
                        f"Attempt {attempts} failed. Retrying in {delay_seconds} seconds. Error: {str(e)}"
                    )
                    time.sleep(delay_seconds)
            return None

        return wrapper

    return decorator


@retry_operation()
def get_llm_response_with_retry(*args, **kwargs):
    return get_llm_response(*args, **kwargs)


def _split_context_blocks(text: str) -> List[str]:
    normalized = re.sub(r"\r\n?", "\n", text or "")
    blocks = [block.strip() for block in re.split(r"\n\s*\n+", normalized) if block.strip()]
    if len(blocks) > 1:
        return blocks
    return [block.strip() for block in re.split(r"(?<=[.!?])\s+", normalized) if block.strip()]


def _score_damage_block(block: str) -> int:
    lower_block = block.lower()
    has_number = bool(NUMERIC_PATTERN.search(block))
    keyword_hits = sum(1 for keyword in DAMAGE_KEYWORDS if keyword in lower_block)

    if has_number and keyword_hits:
        return 3
    if has_number:
        return 2
    if keyword_hits:
        return 1
    return 0


def build_damage_context(
    defendant_text: str,
    plaintiff_text: Optional[str] = None,
    max_chars: int = MAX_DAMAGE_CONTEXT_CHARS,
) -> str:
    """Keep a compact source slice focused on amounts, dates, and damage language."""
    labelled_sources = [("Defendant documents", defendant_text or "")]
    if plaintiff_text:
        labelled_sources.append(("Plaintiff documents", plaintiff_text))

    scored_blocks = []
    order = 0
    for label, text in labelled_sources:
        for block in _split_context_blocks(text):
            score = _score_damage_block(block)
            if score == 0:
                continue
            compact_block = re.sub(r"\s+", " ", block).strip()
            scored_blocks.append((score, order, f"[{label}] {compact_block}"))
            order += 1

    if not scored_blocks:
        fallback_text = "\n\n".join(
            f"[{label}]\n{text[: max_chars // len(labelled_sources)]}"
            for label, text in labelled_sources
            if text
        )
        return fallback_text[:max_chars]

    scored_blocks.sort(key=lambda item: (-item[0], item[1]))
    selected = []
    current_length = 0
    for _, _, block in scored_blocks:
        additional_length = len(block) + 2
        if current_length + additional_length > max_chars:
            continue
        selected.append(block)
        current_length += additional_length

    return "\n\n".join(selected)


def damage_breakdown_system_prompt() -> str:
    return """You are a senior legal damages analyst for a UK legal dispute.
Your task is to produce a clear, evidence-grounded damage breakdown after a judicial case analysis has already been completed.

Use only the provided prior analysis and damage context. Do not invent amounts, facts, evidence, legal findings, or calculations.

You must:
- Identify every monetary amount, percentage, date, quantity, duration, invoice, salary/wage figure, loan/debt, rent/deposit, repair cost, fee, penalty, interest figure, or other numerical term relevant to damages, remedies, or loss.
- Separate claimed amounts from amounts actually supported by evidence.
- Explain calculations step by step where the documents allow calculation.
- If a total cannot be safely calculated, say so and explain what is missing.
- Include non-numeric damages and case impact factors such as distress, reputational harm, inconvenience, breach seriousness, mitigation, vulnerability, ongoing impact, and evidential weaknesses.
- Distinguish strong, moderate, weak, and unclear recovery items.
- Keep the output practical for a frontend: concise labels, clear amounts, and useful next steps.

You only respond in English. You are only allowed to respond in valid JSON matching this structure:
{
  "executive_summary": "string",
  "currency_and_assumptions": ["string"],
  "numerical_breakdown": [
    {
      "category": "string",
      "description": "string",
      "amount_claimed": "string or null",
      "amount_supported": "string or null",
      "calculation": "string",
      "source_evidence": "string",
      "dispute_or_uncertainty": "string",
      "likely_recoverability": "Strong | Moderate | Weak | Unclear",
      "confidence_score": 50
    }
  ],
  "non_numeric_breakdown": [
    {
      "factor": "string",
      "impact": "string",
      "evidence": "string",
      "valuation_note": "string"
    }
  ],
  "case_breakdown": ["string"],
  "total_claimed": "string",
  "total_supported": "string",
  "disputed_or_unclear_amounts": ["string"],
  "evidence_gaps": ["string"],
  "practical_next_steps": ["string"],
  "settlement_or_remedy_view": "string"
}
"""


def damage_breakdown_human_prompt(
    analysis: Dict[str, Any],
    damage_context: str,
    case_id: Optional[str] = None,
) -> str:
    return f"""Case ID:
<case_id>
{case_id or "Not provided"}
</case_id>

Prior judicial analysis:
<analysis_json>
{json.dumps(analysis, ensure_ascii=False, indent=2)}
</analysis_json>

Damage-focused source context from uploaded documents:
<damage_context>
{damage_context or "No source damage context was stored. Use the prior judicial analysis only and clearly identify missing evidence."}
</damage_context>

Produce the damage breakdown now. Be precise and do not overstate unsupported damages."""


def run_damage_breakdown(
    analysis: Dict[str, Any],
    damage_context: str,
    case_id: Optional[str] = None,
) -> Dict[str, Any]:
    breakdown = get_llm_response_with_retry(
        system_prompt=damage_breakdown_system_prompt(),
        human_prompt=damage_breakdown_human_prompt(analysis, damage_context, case_id),
        response_format=DamageBreakdown,
    )
    return breakdown.model_dump()
