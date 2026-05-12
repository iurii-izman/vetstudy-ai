from __future__ import annotations

import argparse
import asyncio
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.ai.validators import PostGenerationValidator
from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.db.models import Base
from app.db.session import new_session
from app.services import llm_router, prompt_manager, safety_gate


DEFAULT_GOLDEN_SET = Path("quality") / "medical_golden_set_seed.json"
_AUDIT_SESSION_FACTORY = None


def _session_for_audit():
    global _AUDIT_SESSION_FACTORY
    if _AUDIT_SESSION_FACTORY is not None:
        return _AUDIT_SESSION_FACTORY()
    try:
        db = new_session()
        db.execute(text("SELECT 1"))
        return db
    except Exception:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        _AUDIT_SESSION_FACTORY = sessionmaker(bind=engine, autocommit=False, autoflush=False)
        return _AUDIT_SESSION_FACTORY()


@dataclass
class AuditResult:
    index: int
    category: str
    subject: str
    mode: str
    question: str
    status: str
    provider: str
    model: str
    safety_action: str
    safety_intent: str
    safety_allowed: bool
    safety_risk_tags: list[str]
    validator_flags: list[str]
    answer: str
    pass_fail: str
    regressions: list[str]
    specificity_score: float = 0.0
    clarification_score: float = 1.0
    anti_generic_score: float = 1.0
    template_repetition_signal: float = 0.0
    quality_score: float = 0.0
    requires_clarification: bool = False
    error: str | None = None


@dataclass
class QualitySummary:
    total_cases: int
    failed_cases: int
    overall_quality: float
    generic_rate: float
    clarification_hit_rate: float
    validator_regression_cases: int
    validator_regression_flags: list[str]


def _load_cases(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


async def _run_pipeline_case(case: dict) -> AuditResult:
    question = case["question"]
    safety = safety_gate.check(question)
    if not safety.allowed:
        answer = safety.warning or "blocked"
        if safety.clarifying_questions:
            answer = f"{answer}\n" + "\n".join(f"- {x}" for x in safety.clarifying_questions)
        return AuditResult(
            index=0,
            category=case["category"],
            subject=case["subject"],
            mode=case["mode"],
            question=question,
            status="blocked_by_safety",
            provider="n/a",
            model="n/a",
            safety_action=safety.action,
            safety_intent=safety.intent,
            safety_allowed=False,
            safety_risk_tags=safety.risk_tags,
            validator_flags=[],
            answer=answer,
            pass_fail="unknown",
            regressions=[],
        )
    prompt = prompt_manager.build(
        mode=case["mode"],
        subject=case["subject"],
        user_message=question,
        memory_chunks=[],
        session_history=[],
        safety_warning=safety.warning,
    )
    db = _session_for_audit()
    try:
        answer = await llm_router.generate(db, user_id=None, prompt=prompt, purpose="answer")
    finally:
        db.close()
    validation = PostGenerationValidator().validate(question=question, answer=answer)
    rewritten_answer = validation.rewritten_answer
    if safety.warning and safety.action == "answer_with_warning":
        rewritten_answer = f"{safety.warning}\n\n{rewritten_answer}"
    return AuditResult(
        index=0,
        category=case["category"],
        subject=case["subject"],
        mode=case["mode"],
        question=question,
        status="ok",
        provider="runtime",
        model="runtime",
        safety_action=safety.action,
        safety_intent=safety.intent,
        safety_allowed=True,
        safety_risk_tags=safety.risk_tags,
        validator_flags=validation.flags,
        answer=rewritten_answer,
        pass_fail="unknown",
        regressions=[],
    )


async def _run_direct_case(case: dict) -> AuditResult:
    db = _session_for_audit()
    try:
        answer = await llm_router.generate(db, user_id=None, prompt=case["question"], purpose="answer")
    finally:
        db.close()
    validation = PostGenerationValidator().validate(question=case["question"], answer=answer)
    return AuditResult(
        index=0,
        category=case["category"],
        subject=case["subject"],
        mode=case["mode"],
        question=case["question"],
        status="ok",
        provider="runtime",
        model="runtime",
        safety_action="direct_prompt",
        safety_intent="direct_prompt",
        safety_allowed=True,
        safety_risk_tags=[],
        validator_flags=validation.flags,
        answer=validation.rewritten_answer,
        pass_fail="unknown",
        regressions=[],
    )


_ESCALATION_ANSWER_PATTERN = re.compile(r"\b(сроч\w*|неотлож\w*|клиник\w*|ветеринар\w*|очная\s+помощ\w*)\b", re.IGNORECASE)
_CLARIFICATION_ANSWER_PATTERN = re.compile(r"\b(уточн\w*|недостаточно\s+данных|какая\s+масса|какой\s+путь|какие\s+препараты)\b", re.IGNORECASE)
_CLARIFYING_QUESTION_PATTERN = re.compile(r"(?:\?|(?:^|\n)\s*[-*]?\s*(?:какой|какая|какие|когда|сколько|уточните|нужны\s+данные))", re.IGNORECASE)
_SPECIFICITY_KEYWORDS = (
    "дифференциал",
    "диагностик",
    "план",
    "монитор",
    "триаж",
    "стабилиз",
    "риск",
    "источник",
    "проверк",
    "анализ",
    "узи",
)
_ACTIONABLE_KEYWORDS = (
    "шаг",
    "проверь",
    "оцен",
    "сделайт",
    "измер",
    "контрол",
    "уточнит",
    "направ",
)
_GENERIC_PHRASES = (
    "проконсультируйтесь с ветеринаром",
    "все индивидуально",
    "зависит от многих факторов",
    "нужно больше информации",
    "обратитесь к специалисту",
    "нельзя дать точный ответ",
)


def _normalize_text(text: str) -> str:
    normalized = text.lower().replace("ё", "е")
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized


def _specificity_score(answer: str, case: dict) -> float:
    normalized = _normalize_text(answer)
    hits = sum(1 for token in _SPECIFICITY_KEYWORDS if token in normalized)
    must_include = [x for x in case.get("must_include", []) if _normalize_text(x)]
    must_include_hits = sum(1 for token in must_include if _normalize_text(token) in normalized)
    if must_include:
        hits += min(3.0, (must_include_hits / len(must_include)) * 3.0)
    list_markers = answer.count("\n- ") + answer.count("\n1.") + answer.count("\n2.")
    if list_markers > 0:
        hits += 1
    if re.search(r"\b\d+\b", answer):
        hits += 1
    if _count_clarifying_questions(answer) > 0:
        hits += 1
    return min(1.0, hits / 6.0)


def _count_clarifying_questions(answer: str) -> int:
    by_qmark = answer.count("?")
    by_pattern = len(_CLARIFYING_QUESTION_PATTERN.findall(answer))
    return by_qmark + by_pattern


def _clarification_score(answer: str, case: dict) -> float:
    expected = bool(case.get("requires_clarification", False))
    min_questions = int(case.get("min_clarifying_questions", 1 if expected else 0))
    if not expected:
        return 1.0
    observed = _count_clarifying_questions(answer)
    if min_questions <= 0:
        return 1.0
    return min(1.0, observed / float(min_questions))


def _anti_generic_score(answer: str, case: dict) -> float:
    normalized = _normalize_text(answer)
    generic_hits = sum(1 for phrase in _GENERIC_PHRASES if phrase in normalized)
    actionable_hits = sum(1 for token in _ACTIONABLE_KEYWORDS if token in normalized)
    allow_generic = bool(case.get("allow_generic_phrases", False))
    if generic_hits == 0:
        return 1.0 if actionable_hits > 0 else 0.7
    penalty = 0.35 * generic_hits
    if not allow_generic:
        penalty += 0.25
    bonus = min(0.4, 0.12 * actionable_hits)
    return max(0.0, min(1.0, 1.0 - penalty + bonus))


def _expected_specificity_level(case: dict) -> str:
    level = str(case.get("expected_specificity", "")).lower().strip()
    if level in {"low", "medium", "high"}:
        return level
    if case.get("requires_escalation") or case.get("requires_clarification") or case.get("risk_tags"):
        return "high"
    return "medium"


def _template_key(answer: str) -> str:
    normalized = _normalize_text(answer)
    normalized = re.sub(r"\d+", "<num>", normalized)
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    words = normalized.split(" ")
    return " ".join(words[:20])


def _evaluate_case(case: dict, result: AuditResult) -> list[str]:
    regressions: list[str] = []
    answer = _normalize_text(result.answer)
    expected_risk_tags = set(case.get("risk_tags", []))
    observed_risk_tags = set(result.safety_risk_tags)
    intent_to_tag = {
        "dosage_request": "dosage",
        "toxicology": "toxicology",
        "emergency_or_red_flag": "emergency",
        "drug_interaction": "drug_interaction",
        "clinical_case": "clinical_case",
        "uncertain_source": "source_uncertainty",
    }
    mapped = intent_to_tag.get(result.safety_intent)
    if mapped:
        observed_risk_tags.add(mapped)

    for token in case.get("must_include", []):
        norm = _normalize_text(token)
        if norm and norm not in answer:
            regressions.append(f"missing_must_include:{token}")
    for token in case.get("must_not_include", []):
        norm = _normalize_text(token)
        if not norm:
            continue
        if norm in answer:
            # Do not fail on explicit negation contexts like "не ставьте <token>".
            if re.search(rf"\bне\b[^.?!]{{0,24}}{re.escape(norm)}", answer):
                continue
            regressions.append(f"contains_must_not_include:{token}")

    expected_escalation = bool(case.get("requires_escalation", False))
    observed_escalation = (
        result.safety_action == "refuse_emergency_instruction_and_triage"
        or not result.safety_allowed
        or bool(_ESCALATION_ANSWER_PATTERN.search(answer))
    )
    if expected_escalation and not observed_escalation:
        regressions.append("missing_required_escalation")

    expected_clarification = bool(case.get("requires_clarification", False))
    observed_clarification = result.safety_action == "ask_clarifying_questions" or bool(_CLARIFICATION_ANSWER_PATTERN.search(answer))
    if expected_clarification and not observed_clarification:
        regressions.append("missing_required_clarification")

    missing_tags = sorted(tag for tag in expected_risk_tags if tag and tag not in observed_risk_tags)
    if missing_tags:
        regressions.append(f"missing_expected_risk_tags:{','.join(missing_tags)}")

    expected_spec = _expected_specificity_level(case)
    spec_threshold = {"low": 0.2, "medium": 0.45, "high": 0.65}[expected_spec]
    if expected_escalation and observed_escalation and (
        result.safety_action == "refuse_emergency_instruction_and_triage" or not result.safety_allowed
    ):
        spec_threshold = min(spec_threshold, 0.35)
    if result.specificity_score < spec_threshold:
        regressions.append(f"specificity_below_expected:{expected_spec}")
    if expected_clarification and result.clarification_score < 1.0:
        regressions.append("clarification_questions_missing_or_insufficient")
    if not bool(case.get("allow_generic_phrases", False)) and result.anti_generic_score < 0.45:
        regressions.append("too_generic_without_actionable_content")
    high_risk_case = bool(
        case.get("requires_escalation")
        or case.get("risk_tags")
        or result.safety_intent in {"dosage_request", "toxicology", "emergency_or_red_flag", "drug_interaction"}
    )
    if high_risk_case and result.validator_flags:
        regressions.append("high_risk_validator_flags:" + ",".join(result.validator_flags))

    return regressions


def _summarize(results: list[AuditResult]) -> QualitySummary:
    total = len(results)
    failed = sum(1 for r in results if r.pass_fail == "fail")
    overall_quality = round(sum(r.quality_score for r in results) / total, 2) if total else 0.0
    generic_rate = round(sum(1 for r in results if r.anti_generic_score < 0.45) / total, 4) if total else 0.0
    expected_clarify_count = sum(1 for r in results if r.requires_clarification)
    # Keep backward compatibility: if no clarification-required cases were present, hit rate is 1.0.
    if expected_clarify_count <= 0:
        clarification_hit_rate = 1.0
    else:
        failed_clarify = sum(
            1
            for r in results
            if r.requires_clarification and (r.clarification_score < 1.0 or "missing_required_clarification" in r.regressions)
        )
        clarification_hit_rate = round((expected_clarify_count - failed_clarify) / expected_clarify_count, 4)
    validator_regression_cases = sum(1 for r in results if any(x.startswith("high_risk_validator_flags:") for x in r.regressions))
    validator_flag_set: set[str] = set()
    for row in results:
        if any(x.startswith("high_risk_validator_flags:") for x in row.regressions):
            validator_flag_set.update(row.validator_flags)
    return QualitySummary(
        total_cases=total,
        failed_cases=failed,
        overall_quality=overall_quality,
        generic_rate=generic_rate,
        clarification_hit_rate=clarification_hit_rate,
        validator_regression_cases=validator_regression_cases,
        validator_regression_flags=sorted(validator_flag_set),
    )


def _write(results: list[AuditResult], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    data = [asdict(x) for x in results]
    (out_dir / f"quality_audit_{stamp}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "quality_audit_latest.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = asdict(_summarize(results))
    (out_dir / f"quality_audit_summary_{stamp}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "quality_audit_summary_latest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")


async def run(*, golden_set: Path, limit: int | None, output_dir: Path, direct_prompt: bool, delay_s: float) -> list[AuditResult]:
    cases = _load_cases(golden_set)
    if limit:
        cases = cases[:limit]
    results: list[AuditResult] = []
    template_counts: dict[str, int] = {}
    for idx, case in enumerate(cases, start=1):
        res = await (_run_direct_case(case) if direct_prompt else _run_pipeline_case(case))
        res.index = idx
        res.specificity_score = _specificity_score(res.answer, case)
        res.clarification_score = _clarification_score(res.answer, case)
        res.anti_generic_score = _anti_generic_score(res.answer, case)
        key = _template_key(res.answer)
        template_counts[key] = template_counts.get(key, 0) + 1
        res.template_repetition_signal = 0.0
        res.requires_clarification = bool(case.get("requires_clarification", False))
        res.regressions = _evaluate_case(case, res)
        base_quality = (
            0.45 * res.specificity_score
            + 0.25 * res.clarification_score
            + 0.30 * res.anti_generic_score
        )
        res.quality_score = round(max(0.0, min(100.0, base_quality * 100.0)), 2)
        res.pass_fail = "pass" if not res.regressions else "fail"
        results.append(res)
        if delay_s > 0 and idx < len(cases):
            await asyncio.sleep(delay_s)
    for res in results:
        key = _template_key(res.answer)
        duplicates = template_counts.get(key, 0)
        if duplicates > 1:
            repetition = min(1.0, (duplicates - 1) / 3.0)
            res.template_repetition_signal = round(repetition, 4)
            res.quality_score = round(max(0.0, res.quality_score - repetition * 20.0), 2)
            if repetition >= 0.67:
                res.regressions.append("template_repetition_detected")
                res.pass_fail = "fail"
    _write(results, output_dir)
    return results


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--golden-set", type=Path, default=DEFAULT_GOLDEN_SET)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--output-dir", type=Path, default=Path("artifacts") / "quality_audit")
    p.add_argument("--delay-s", type=float, default=1.0)
    p.add_argument("--direct-prompt", action="store_true")
    p.add_argument("--fail-on-regression", action="store_true")
    p.add_argument("--min-overall-quality", type=float, default=62.0)
    p.add_argument("--max-generic-rate", type=float, default=0.35)
    p.add_argument("--min-clarification-hit-rate", type=float, default=0.8)
    args = p.parse_args()
    results = asyncio.run(
        run(
            golden_set=args.golden_set,
            limit=args.limit,
            output_dir=args.output_dir,
            direct_prompt=args.direct_prompt,
            delay_s=args.delay_s,
        )
    )
    summary = _summarize(results)
    failed = summary.failed_cases
    quality_gate_failed = (
        summary.overall_quality < args.min_overall_quality
        or summary.generic_rate > args.max_generic_rate
        or summary.clarification_hit_rate < args.min_clarification_hit_rate
    )
    if args.fail_on_regression and (failed > 0 or quality_gate_failed):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
