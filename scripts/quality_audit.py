from __future__ import annotations

import argparse
import asyncio
import json
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
    validator_flags: list[str]
    answer: str
    error: str | None = None


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
            validator_flags=[],
            answer=answer,
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
        validator_flags=validation.flags,
        answer=validation.rewritten_answer,
    )


async def _run_direct_case(case: dict) -> AuditResult:
    db = _session_for_audit()
    try:
        answer = await llm_router.generate(db, user_id=None, prompt=case["question"], purpose="answer")
    finally:
        db.close()
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
        validator_flags=[],
        answer=answer,
    )


def _write(results: list[AuditResult], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    data = [asdict(x) for x in results]
    (out_dir / f"quality_audit_{stamp}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "quality_audit_latest.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


async def run(*, golden_set: Path, limit: int | None, output_dir: Path, direct_prompt: bool, delay_s: float) -> list[AuditResult]:
    cases = _load_cases(golden_set)
    if limit:
        cases = cases[:limit]
    results: list[AuditResult] = []
    for idx, case in enumerate(cases, start=1):
        res = await (_run_direct_case(case) if direct_prompt else _run_pipeline_case(case))
        res.index = idx
        results.append(res)
        _write(results, output_dir)
        if delay_s > 0 and idx < len(cases):
            await asyncio.sleep(delay_s)
    return results


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--golden-set", type=Path, default=DEFAULT_GOLDEN_SET)
    p.add_argument("--limit", type=int, default=None)
    p.add_argument("--output-dir", type=Path, default=Path("artifacts") / "quality_audit")
    p.add_argument("--delay-s", type=float, default=1.0)
    p.add_argument("--direct-prompt", action="store_true")
    args = p.parse_args()
    asyncio.run(run(golden_set=args.golden_set, limit=args.limit, output_dir=args.output_dir, direct_prompt=args.direct_prompt, delay_s=args.delay_s))


if __name__ == "__main__":
    main()
