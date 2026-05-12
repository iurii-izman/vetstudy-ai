from __future__ import annotations


def compact_trust_trace(
    *,
    source: str | None,
    trust_level: str | None,
    verification_status: str | None,
    needs_manual_check: bool,
    manual_check_reasons: list[str] | None = None,
    missing_data: list[str] | None = None,
) -> str:
    reason = (manual_check_reasons or ["-"])[0] if needs_manual_check else "-"
    missing = ", ".join((missing_data or [])[:2]) if missing_data else "-"
    return (
        f"src={source or 'mixed'} | trust={trust_level or 'low'} | verify={verification_status or 'unknown'} "
        f"| manual={'yes' if needs_manual_check else 'no'} ({reason}) | missing={missing}"
    )

