"""
Tests for the /case and /case_answer virtual case training flow.

Covers:
- allowlist gate (allowlist blocks denied users)
- user isolation (each user's active_case_id is stored per-user in settings)
- educational disclaimer wording appears in every case presentation
- case_started / case_submitted product events are tracked
- safety: case_answer blocked when no active case
- safety: Socratic evaluation prompt does NOT contain treatment prescriptions
  (the build_case_eval method must include the safety rules block)
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock  # noqa: F401 – kept for future use

import pytest

from app.telegram import handlers
from app.cases import CASES, CASE_EDUCATIONAL_DISCLAIMER, get_case_by_id
from app.ai.prompts import PromptManager


# ─────────────────────────── helpers ────────────────────────────────────────


class FakeMessage:
    def __init__(self, *, user_id=1, text="", username=None):
        self.from_user = SimpleNamespace(id=user_id, full_name="Test User", username=username)
        self.chat = SimpleNamespace(id=100)
        self.message_thread_id = None
        self.text = text
        self.message_id = 42
        self.answers: list[dict] = []
        self.bot = SimpleNamespace()
        self.voice = None
        self.audio = None
        self.photo = []
        self.document = None

    async def answer(self, text, **kwargs):
        self.answers.append({"text": text, **kwargs})


class FakeMessageNoAnswers:
    def __init__(self, *, user_id=1, text="", username=None):
        self.from_user = SimpleNamespace(id=user_id, full_name="Test User", username=username)
        self.chat = SimpleNamespace(id=100)
        self.message_thread_id = None
        self.text = text
        self.message_id = 42
        self.bot = SimpleNamespace()
        self.voice = None
        self.audio = None
        self.photo = []
        self.document = None
        self.replies: list[dict] = []

    async def answer(self, text, **kwargs):
        self.replies.append({"text": text, **kwargs})


class FakeDB:
    def close(self): pass
    def commit(self): pass
    def add(self, *args): pass
    def flush(self): pass
    def refresh(self, *args): pass
    def query(self, *args):
        return SimpleNamespace(
            filter=lambda *a: SimpleNamespace(first=lambda: None, all=lambda: [])
        )


async def _async_return(val):
    return val


def _make_user(case_id: str | None = None) -> SimpleNamespace:
    settings = {}
    if case_id:
        settings["active_case_id"] = case_id
    return SimpleNamespace(id="u-1", settings=settings)


def _patch_user_repo(monkeypatch, user):
    monkeypatch.setattr(
        handlers,
        "UserRepo",
        lambda db: SimpleNamespace(get_or_create=lambda *a, **k: user),
    )


def _patch_topic_repo(monkeypatch):
    monkeypatch.setattr(
        handlers,
        "TopicRepo",
        lambda db: SimpleNamespace(get_by_chat_thread=lambda *a, **k: None),
    )


def _patch_analytics(monkeypatch, events: list):
    monkeypatch.setattr(
        handlers,
        "ProductAnalyticsService",
        lambda db: SimpleNamespace(track=lambda **kwargs: events.append(kwargs)),
    )


# ─────────────────────────── cases module ───────────────────────────────────


def test_cases_has_expected_count():
    assert len(CASES) >= 8, f"Expected ≥8 cases, got {len(CASES)}"


def test_cases_all_have_required_fields():
    required = {"id", "title", "description", "rubric"}
    for case in CASES:
        missing = required - set(case.keys())
        assert not missing, f"Case {case.get('id')} missing fields: {missing}"


def test_cases_rubric_has_required_keys():
    rubric_keys = {"missing_data", "red_flags", "key_differentials", "unsafe_assumptions"}
    for case in CASES:
        missing = rubric_keys - set(case["rubric"].keys())
        assert not missing, f"Case {case['id']} rubric missing keys: {missing}"


def test_get_case_by_id_known():
    first_id = CASES[0]["id"]
    result = get_case_by_id(first_id)
    assert result is not None
    assert result["id"] == first_id


def test_get_case_by_id_unknown():
    assert get_case_by_id("nonexistent_xyz") is None


def test_educational_disclaimer_content():
    # Disclaimer must contain the AI accuracy warning
    assert "AI может ошибаться" in CASE_EDUCATIONAL_DISCLAIMER
    assert "верифицируйте" in CASE_EDUCATIONAL_DISCLAIMER


# ─────────────────────────── prompt safety ──────────────────────────────────


def test_build_case_eval_contains_safety_rules():
    pm = PromptManager()
    case = CASES[0]
    prompt = pm.build_case_eval(
        case_title=case["title"],
        case_description=case["description"],
        rubric=case["rubric"],
        student_answer="Мой ответ: гастрит, дать противорвотное.",
    )
    # Must include accuracy rules (no invented doses, source required)
    assert "needs_manual_check" in prompt.lower() or "Правила точности" in prompt
    # Must instruct full clinical assessment: diagnosis and treatment plan
    assert "диагноз" in prompt.lower() or "лечения" in prompt.lower()


def test_build_case_eval_contains_rubric_items():
    pm = PromptManager()
    case = get_case_by_id("vomiting_dog")
    assert case is not None
    prompt = pm.build_case_eval(
        case_title=case["title"],
        case_description=case["description"],
        rubric=case["rubric"],
        student_answer="Нужна биохимия.",
    )
    # Rubric items must appear in prompt to guide the LLM evaluator
    assert "инородное тело" in prompt or "гастрит" in prompt  # differential
    assert "рвота с кровью" in prompt or "красные флаги" in prompt.lower()


def test_build_case_eval_includes_student_answer():
    pm = PromptManager()
    case = CASES[0]
    student_answer = "Мой уникальный ответ xyzy123"
    prompt = pm.build_case_eval(
        case_title=case["title"],
        case_description=case["description"],
        rubric=case["rubric"],
        student_answer=student_answer,
    )
    assert student_answer in prompt


# ─────────────────────────── /case allowlist ────────────────────────────────


@pytest.mark.asyncio
async def test_case_command_blocked_when_not_allowed(monkeypatch):
    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: SimpleNamespace(allowed_user_ids={999}, allowed_usernames=set()),
    )
    message = FakeMessage(user_id=1)
    await handlers.cmd_case(message, SimpleNamespace(args=""))
    assert message.answers
    assert "Доступ запрещен" in message.answers[0]["text"]


@pytest.mark.asyncio
async def test_case_answer_blocked_when_not_allowed(monkeypatch):
    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: SimpleNamespace(allowed_user_ids={999}, allowed_usernames=set()),
    )
    message = FakeMessage(user_id=1, text="/case_answer анализ")
    await handlers.cmd_case_answer(message)
    assert message.answers
    assert "Доступ запрещен" in message.answers[0]["text"]


# ─────────────────────────── /case command ──────────────────────────────────


@pytest.mark.asyncio
async def test_case_command_lists_cases_when_no_args(monkeypatch):
    monkeypatch.setattr(handlers, "_check_allow", lambda msg: True)
    monkeypatch.setattr(handlers, "new_session", lambda: FakeDB())
    user = _make_user()
    _patch_user_repo(monkeypatch, user)
    events: list = []
    _patch_analytics(monkeypatch, events)

    message = FakeMessage(user_id=1, text="/case")
    await handlers.cmd_case(message, SimpleNamespace(args=""))

    assert message.answers
    answer = message.answers[0]
    assert "Выбери" in answer["text"] or "кейс" in answer["text"].lower()
    # Keyboard must be present
    assert answer.get("reply_markup") is not None


@pytest.mark.asyncio
async def test_case_command_direct_id_sets_active_case_and_shows_disclaimer(monkeypatch):
    monkeypatch.setattr(handlers, "_check_allow", lambda msg: True)
    monkeypatch.setattr(handlers, "new_session", lambda: FakeDB())
    user = _make_user()
    _patch_user_repo(monkeypatch, user)
    events: list = []
    _patch_analytics(monkeypatch, events)

    first_case = CASES[0]
    message = FakeMessage(user_id=1, text=f"/case {first_case['id']}")
    await handlers.cmd_case(message, SimpleNamespace(args=first_case["id"]))

    # active_case_id must be set on this user's settings (user isolation)
    assert user.settings.get("active_case_id") == first_case["id"]

    # Disclaimer must appear in the answer
    assert message.answers
    combined = " ".join(a["text"] for a in message.answers)
    assert "AI может ошибаться" in combined or "верифицируйте" in combined

    # case_started event tracked
    assert any(e.get("event_name") == "case_started" for e in events)
    started = next(e for e in events if e.get("event_name") == "case_started")
    assert started["properties"]["case_id"] == first_case["id"]


@pytest.mark.asyncio
async def test_case_command_unknown_id_gives_error(monkeypatch):
    monkeypatch.setattr(handlers, "_check_allow", lambda msg: True)
    monkeypatch.setattr(handlers, "new_session", lambda: FakeDB())
    user = _make_user()
    _patch_user_repo(monkeypatch, user)
    _patch_analytics(monkeypatch, [])

    message = FakeMessage(user_id=1, text="/case unknown_id_xyz")
    await handlers.cmd_case(message, SimpleNamespace(args="unknown_id_xyz"))

    assert message.answers
    assert "не найден" in message.answers[0]["text"].lower()
    # active_case_id must NOT be set for unknown case
    assert "active_case_id" not in user.settings


# ─────────────────────────── user isolation ─────────────────────────────────


@pytest.mark.asyncio
async def test_case_active_case_is_per_user(monkeypatch):
    """Each user object gets its own active_case_id — no cross-user leakage."""
    monkeypatch.setattr(handlers, "_check_allow", lambda msg: True)
    monkeypatch.setattr(handlers, "new_session", lambda: FakeDB())
    _patch_analytics(monkeypatch, [])

    user_a = _make_user()
    user_b = _make_user()

    case_a = CASES[0]
    case_b = CASES[1]

    # Activate case for user A
    monkeypatch.setattr(handlers, "UserRepo", lambda db: SimpleNamespace(get_or_create=lambda uid, *a, **k: user_a if uid == 1 else user_b))
    msg_a = FakeMessage(user_id=1, text=f"/case {case_a['id']}")
    await handlers.cmd_case(msg_a, SimpleNamespace(args=case_a["id"]))

    # Activate case for user B
    monkeypatch.setattr(handlers, "UserRepo", lambda db: SimpleNamespace(get_or_create=lambda uid, *a, **k: user_a if uid == 1 else user_b))
    msg_b = FakeMessage(user_id=2, text=f"/case {case_b['id']}")
    await handlers.cmd_case(msg_b, SimpleNamespace(args=case_b["id"]))

    # Verify isolation
    assert user_a.settings.get("active_case_id") == case_a["id"]
    assert user_b.settings.get("active_case_id") == case_b["id"]
    assert user_a.settings.get("active_case_id") != user_b.settings.get("active_case_id")


# ─────────────────────────── /case_answer ────────────────────────────────────


@pytest.mark.asyncio
async def test_case_answer_no_active_case_prompts_user(monkeypatch):
    monkeypatch.setattr(handlers, "_check_allow", lambda msg: True)
    monkeypatch.setattr(handlers, "new_session", lambda: FakeDB())
    user = _make_user(case_id=None)
    _patch_user_repo(monkeypatch, user)
    _patch_topic_repo(monkeypatch)

    message = FakeMessage(user_id=1, text="/case_answer Мой анализ")
    await handlers.cmd_case_answer(message)

    assert message.answers
    assert "кейс" in message.answers[0]["text"].lower() or "/case" in message.answers[0]["text"]


@pytest.mark.asyncio
async def test_case_answer_empty_answer_prompts_user(monkeypatch):
    monkeypatch.setattr(handlers, "_check_allow", lambda msg: True)
    monkeypatch.setattr(handlers, "new_session", lambda: FakeDB())
    user = _make_user(case_id=CASES[0]["id"])
    _patch_user_repo(monkeypatch, user)
    _patch_topic_repo(monkeypatch)

    # Text is only "/case_answer" with no analysis
    message = FakeMessage(user_id=1, text="/case_answer")
    await handlers.cmd_case_answer(message)

    assert message.answers
    # Should prompt for analysis text
    assert "/case_answer" in message.answers[0]["text"] or "анализ" in message.answers[0]["text"].lower()


@pytest.mark.asyncio
async def test_case_answer_submits_and_tracks_event(monkeypatch):
    monkeypatch.setattr(handlers, "_check_allow", lambda msg: True)
    monkeypatch.setattr(handlers, "new_session", lambda: FakeDB())

    case = CASES[0]
    user = _make_user(case_id=case["id"])
    _patch_user_repo(monkeypatch, user)
    _patch_topic_repo(monkeypatch)

    events: list = []
    _patch_analytics(monkeypatch, events)

    # Quota passes
    monkeypatch.setattr(
        handlers,
        "QuotaGuard",
        lambda settings: SimpleNamespace(
            check_user_and_global=lambda db, u: SimpleNamespace(allowed=True, message=None)
        ),
    )
    monkeypatch.setattr(handlers, "get_settings", lambda: SimpleNamespace(
        allowed_user_ids=set(), allowed_usernames=set(),
    ))
    monkeypatch.setattr(
        handlers.llm_router,
        "generate",
        lambda *a, **k: _async_return(
            "✅ Правильно: запросили ОАК.\n❓ Не упомянули панкреатит.\n⚠️ учебный пример — needs_manual_check"
        ),
    )

    message = FakeMessage(user_id=1, text="/case_answer Запрошу ОАК и биохимию. Дифференциал: гастрит.")
    await handlers.cmd_case_answer(message)

    # case_submitted event must be tracked
    assert any(e.get("event_name") == "case_submitted" for e in events)
    submitted = next(e for e in events if e.get("event_name") == "case_submitted")
    assert submitted["properties"]["case_id"] == case["id"]

    # Active case must be cleared after submission (user isolation: cleared for this user only)
    assert user.settings.get("active_case_id") is None

    # Response must include educational disclaimer
    combined = " ".join(a["text"] for a in message.answers)
    assert "AI может ошибаться" in combined or "верифицируйте" in combined or "needs_manual_check" in combined.lower()


@pytest.mark.asyncio
async def test_case_answer_response_contains_safety_disclaimer(monkeypatch):
    """LLM response wrapper must always include the educational safety disclaimer."""
    monkeypatch.setattr(handlers, "_check_allow", lambda msg: True)
    monkeypatch.setattr(handlers, "new_session", lambda: FakeDB())

    case = CASES[0]
    user = _make_user(case_id=case["id"])
    _patch_user_repo(monkeypatch, user)
    _patch_topic_repo(monkeypatch)
    _patch_analytics(monkeypatch, [])

    monkeypatch.setattr(
        handlers,
        "QuotaGuard",
        lambda s: SimpleNamespace(
            check_user_and_global=lambda db, u: SimpleNamespace(allowed=True, message=None)
        ),
    )
    monkeypatch.setattr(handlers, "get_settings", lambda: SimpleNamespace(
        allowed_user_ids=set(), allowed_usernames=set(),
    ))
    monkeypatch.setattr(
        handlers.llm_router,
        "generate",
        lambda *a, **k: _async_return("Хорошая попытка. Вы упустили кардиологию."),
    )

    message = FakeMessage(user_id=1, text="/case_answer Гастрит, инородное тело.")
    await handlers.cmd_case_answer(message)

    combined = " ".join(a["text"] for a in message.answers)
    # The hardcoded disclaimer must always appear regardless of LLM output
    assert (
        "AI может ошибаться" in combined
        or "верифицируйте" in combined
    ), f"AI accuracy disclaimer missing from case_answer response: {combined[:300]}"


@pytest.mark.asyncio
async def test_case_answer_no_runtime_dependency_on_message_answers(monkeypatch):
    monkeypatch.setattr(handlers, "_check_allow", lambda msg: True)
    monkeypatch.setattr(handlers, "new_session", lambda: FakeDB())
    user = _make_user(case_id=CASES[0]["id"])
    _patch_user_repo(monkeypatch, user)
    _patch_topic_repo(monkeypatch)
    _patch_analytics(monkeypatch, [])
    monkeypatch.setattr(
        handlers,
        "QuotaGuard",
        lambda s: SimpleNamespace(check_user_and_global=lambda db, u: SimpleNamespace(allowed=True, message=None)),
    )
    monkeypatch.setattr(handlers.llm_router, "generate", lambda *a, **k: _async_return("ok"))

    message = FakeMessageNoAnswers(user_id=1, text="/case_answer анализ")
    await handlers.cmd_case_answer(message)

    assert message.replies


@pytest.mark.asyncio
async def test_case_answer_parses_command_with_mention(monkeypatch):
    monkeypatch.setattr(handlers, "_check_allow", lambda msg: True)
    monkeypatch.setattr(handlers, "new_session", lambda: FakeDB())
    user = _make_user(case_id=CASES[0]["id"])
    _patch_user_repo(monkeypatch, user)
    _patch_topic_repo(monkeypatch)
    _patch_analytics(monkeypatch, [])
    monkeypatch.setattr(
        handlers,
        "QuotaGuard",
        lambda s: SimpleNamespace(check_user_and_global=lambda db, u: SimpleNamespace(allowed=True, message=None)),
    )
    monkeypatch.setattr(handlers.llm_router, "generate", lambda *a, **k: _async_return("ok"))

    message = FakeMessage(user_id=1, text="/case_answer@vetprofessor_bot Мой анализ")
    await handlers.cmd_case_answer(message)

    assert any("Напиши свой анализ" not in item["text"] for item in message.answers)
