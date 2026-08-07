"""
Structured-output schemas shared by every agent (PRD Section 4.4: every
agent enforces JSON schema output rather than free text, for reliable
inter-stage parsing and deterministic email assembly).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentCallResult:
    """Wraps any agent's parsed output together with the token/cost
    accounting needed for agent_run_log and the digest's cost footer."""
    data: dict
    input_tokens: int
    output_tokens: int
    cost_usd: float


SCREENING_SCHEMA = {
    "type": "object",
    "properties": {
        "has_new_activity": {"type": "boolean"},
        "reasoning": {"type": "string"},
    },
    "required": ["has_new_activity", "reasoning"],
}

FILINGS_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "hard_facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "form_type": {"type": "string"},
                    "description": {"type": "string"},
                    "filed_at": {"type": "string"},
                    "url": {"type": "string"},
                },
                "required": ["form_type", "description", "filed_at", "url"],
            },
        },
        "low_confidence_flags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["hard_facts", "low_confidence_flags"],
}

NEWS_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "subjective_info": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "source_name": {"type": "string"},
                    "source_url": {"type": "string"},
                    "published_at": {"type": "string"},
                },
                "required": ["claim", "source_name", "source_url", "published_at"],
            },
        },
        "low_confidence_flags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["subjective_info", "low_confidence_flags"],
}

MACRO_EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "global_context": {"type": "string"},
        "us_context": {"type": "string"},
        "sector_context": {"type": "string"},
    },
    "required": ["global_context", "us_context", "sector_context"],
}

VALIDATION_SCHEMA = {
    "type": "object",
    "properties": {
        "discrepancy_analysis": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    # Descriptive comparison language only — no confidence
                    "type": {"type": "string", "enum": ["agreement", "disagreement", "unsupported_narrative"]},
                    "description": {"type": "string"},
                },
                "required": ["type", "description"],
            },
        },
        "needs_more_context": {"type": "boolean"},
        "additional_context_request": {"type": "string"},
    },
    "required": ["discrepancy_analysis", "needs_more_context"],
}

COMPOSER_SCHEMA = {
    "type": "object",
    "properties": {
        "subject_line": {"type": "string"},
        "html_body": {"type": "string"},
        "daily_summary_by_holding": {
            "type": "object",
            "description": "holding_id (as string) -> compact ~200-token summary for the 7-day recall store",
            "additionalProperties": {"type": "string"},
        },
    },
    "required": ["subject_line", "html_body", "daily_summary_by_holding"],
}
