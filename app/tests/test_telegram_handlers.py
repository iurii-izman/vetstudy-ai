from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest

from app.media.types import UnsupportedMediaError
from app.telegram import handlers


class FakeMessage:
    def __init__(self, *, user_id=1, chat_id=100, thread_id=777, text="hello", username=None):
        self.from_user = SimpleNamespace(id=user_id, full_name="User Test", username=username)
        self.chat = SimpleNamespace(id=chat_id)
        self.message_thread_id = thread_id
        self.text = text
        self.message_id = 55
        self.answers = []
        self.bot = SimpleNamespace()
        self.voice = None
        self.audio = None
        self.photo = []
        self.document = None

    async def answer(self, text, **kwargs):
        self.answers.append({"text": text, **kwargs})


class FakeDB:
    def close(self):
        return None

    def commit(self):
        return None


def _patch_minimal_text_flow(monkeypatch, *, topic):
    monkeypatch.setattr(handlers, "_check_allow", lambda message: True)
    monkeypatch.setattr(handlers, "new_session", lambda: FakeDB())
    monkeypatch.setattr(
        handlers,
        "ChatDBService",
        lambda db: SimpleNamespace(
            ensure_user=lambda *a, **k: SimpleNamespace(id="u-1", settings={}),
            get_topic_for_chat_thread=lambda *a, **k: topic,
            get_or_create_active_session=lambda *a, **k: SimpleNamespace(id="s-1", mode="practical"),
            save_user_message=lambda *a, **k: None,
            save_assistant_message=lambda *a, **k: SimpleNamespace(id="m-1"),
        ),
    )
    monkeypatch.setattr(
        handlers,
        "MessageRepo",
        lambda db: SimpleNamespace(
            add=lambda *a, **k: SimpleNamespace(id="m-1"),
            last_assistant=lambda *a, **k: None,
            recent_for_session=lambda *a, **k: [],
            count_for_session=lambda *a, **k: 1,
        ),
    )
    monkeypatch.setattr(handlers, "MemoryRepo", lambda db: SimpleNamespace(add=lambda **k: None))
    monkeypatch.setattr(
        handlers,
        "MemoryService",
        lambda *a, **k: SimpleNamespace(
            retrieve_for_topic=lambda *x, **y: [],
            search=lambda *x, **y: _async_return([]),
            ingest_assistant_answer=lambda *x, **y: _async_return(None),
            summarize_topic=lambda *x, **y: _async_return("Summary"),
            related_topics=lambda *x, **y: _async_return([]),
        ),
    )
    monkeypatch.setattr(handlers, "SubjectRepo", lambda db: SimpleNamespace(get_by_id=lambda *a, **k: None))
    monkeypatch.setattr(handlers.prompt_manager, "build", lambda **k: "prompt")
    monkeypatch.setattr(handlers.safety_gate, "check", lambda text: SimpleNamespace(allowed=True, warning=None))


async def _async_return(value):
    return value


class _DocumentJobDb:
    def __init__(self, user):
        self.user = user
        self.closed = False

    def close(self):
        self.closed = True

    def commit(self):
        return None


def _patch_document_job_repos(monkeypatch, *, user, memory_rows, error_rows):
    monkeypatch.setattr(handlers, "new_session", lambda: _DocumentJobDb(user))
    monkeypatch.setattr(handlers, "UserRepo", lambda db: SimpleNamespace(get_or_create=lambda *a, **k: db.user))
    monkeypatch.setattr(handlers, "MemoryRepo", lambda db: SimpleNamespace(add=lambda **kwargs: memory_rows.append(kwargs)))
    monkeypatch.setattr(handlers, "ErrorEventRepo", lambda db: SimpleNamespace(add=lambda **kwargs: error_rows.append(kwargs)))


@pytest.mark.asyncio
async def test_document_job_marks_indexed(monkeypatch):
    job_id = str(uuid.uuid4())
    user = SimpleNamespace(settings={"documents": [{"job_id": job_id, "filename": "case.txt", "status": "queued"}]})
    memory_rows = []
    error_rows = []
    _patch_document_job_repos(monkeypatch, user=user, memory_rows=memory_rows, error_rows=error_rows)
    monkeypatch.setattr(handlers, "extract_document_text", lambda *a, **k: "one two three")
    monkeypatch.setattr(handlers, "chunk_text", lambda text: ["chunk"])
    monkeypatch.setattr(handlers.llm_router, "embed", lambda *a, **k: _async_return([[0.1, 0.2]]))

    await handlers._index_document_job(
        stored_path=Path("case.txt"),
        original_name="case.txt",
        user_id=uuid.uuid4(),
        topic_id=uuid.uuid4(),
        telegram_user_id=7,
        display_name="U",
        job_id=job_id,
    )

    assert memory_rows
    assert user.settings["documents"][0]["status"] == "indexed"
    assert user.settings["documents"][0]["chunks"] == 1
    assert error_rows == []


@pytest.mark.asyncio
async def test_document_job_marks_failed_on_unsupported(monkeypatch):
    user_id = uuid.uuid4()
    job_id = str(uuid.uuid4())
    user = SimpleNamespace(settings={"documents": [{"job_id": job_id, "filename": "bad.pdf", "status": "queued"}]})
    memory_rows = []
    error_rows = []
    _patch_document_job_repos(monkeypatch, user=user, memory_rows=memory_rows, error_rows=error_rows)
    monkeypatch.setattr(handlers, "extract_document_text", lambda *a, **k: (_ for _ in ()).throw(UnsupportedMediaError("bad file")))

    await handlers._index_document_job(
        stored_path=Path("bad.pdf"),
        original_name="bad.pdf",
        user_id=user_id,
        topic_id=uuid.uuid4(),
        telegram_user_id=7,
        display_name="U",
        job_id=job_id,
    )

    assert memory_rows == []
    assert user.settings["documents"][0]["status"] == "failed"
    assert user.settings["documents"][0]["error"] == "bad file"
    assert error_rows[0]["user_id"] == user_id
    assert error_rows[0]["category"] == "document_index_failed"


@pytest.mark.asyncio
async def test_document_job_skips_already_completed_retry(monkeypatch):
    job_id = str(uuid.uuid4())
    user = SimpleNamespace(settings={"documents": [{"job_id": job_id, "filename": "case.txt", "status": "indexed"}]})
    memory_rows = []
    error_rows = []
    _patch_document_job_repos(monkeypatch, user=user, memory_rows=memory_rows, error_rows=error_rows)
    monkeypatch.setattr(handlers, "extract_document_text", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("should not run")))

    await handlers._index_document_job(
        stored_path=Path("case.txt"),
        original_name="case.txt",
        user_id=uuid.uuid4(),
        topic_id=uuid.uuid4(),
        telegram_user_id=7,
        display_name="U",
        job_id=job_id,
    )

    assert memory_rows == []
    assert error_rows == []
    assert user.settings["documents"][0]["status"] == "indexed"


@pytest.mark.asyncio
async def test_message_in_known_topic(monkeypatch):
    _patch_minimal_text_flow(monkeypatch, topic=SimpleNamespace(id="t-1", subject_id="sub-1", title="Терапия"))
    async def _generate(*args, **kwargs):
        return "**Короткий ответ**\n\n- **Диагностика:** ОАК"

    monkeypatch.setattr(handlers.llm_router, "generate", _generate)
    message = FakeMessage()
    await handlers.on_text(message)
    assert message.answers
    assert message.answers[0]["parse_mode"] == "HTML"
    assert "<b>Короткий ответ</b>" in message.answers[0]["text"]
    assert "• 🧪 <b>Диагностика:</b> ОАК" in message.answers[0]["text"]
    assert "message_thread_id" not in message.answers[0]
    assert message.answers[-1]["reply_markup"] is not None


@pytest.mark.asyncio
async def test_message_in_unknown_topic(monkeypatch):
    _patch_minimal_text_flow(monkeypatch, topic=None)
    async def _generate(*args, **kwargs):
        raise RuntimeError("must not call llm")

    monkeypatch.setattr(handlers.llm_router, "generate", _generate)
    message = FakeMessage()
    await handlers.on_text(message)
    assert "не привязан" in message.answers[0]["text"]
    assert "777" in message.answers[0]["text"]


@pytest.mark.asyncio
async def test_embedded_bot_command_reroutes_instead_of_pipeline(monkeypatch):
    _patch_minimal_text_flow(monkeypatch, topic=SimpleNamespace(id="t-1", subject_id="sub-1", title="Терапия"))
    called = {}

    async def _cmd_today(message, command=None):
        called["args"] = getattr(command, "args", None)
        await message.answer("rerouted today")

    async def _pipeline_should_not_run(*args, **kwargs):
        raise AssertionError("on_text should reroute embedded command and skip text pipeline")

    monkeypatch.setattr(handlers, "cmd_today", _cmd_today)
    monkeypatch.setattr(handlers, "_run_text_pipeline", _pipeline_should_not_run)

    message = FakeMessage(text="@vetprofessor_bot /today standard")
    await handlers.on_text(message)

    assert called["args"] == "standard"
    assert any("rerouted today" in item["text"] for item in message.answers)


@pytest.mark.asyncio
async def test_allowlist_for_start(monkeypatch):
    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: SimpleNamespace(allowed_user_ids={999}),
    )
    message = FakeMessage(user_id=1)
    await handlers.cmd_start(message)
    assert message.answers
    assert "Доступ запрещен" in message.answers[0]["text"]
    assert "1" in message.answers[0]["text"]


@pytest.mark.asyncio
async def test_allowlist_for_mode(monkeypatch):
    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: SimpleNamespace(allowed_user_ids={999}),
    )
    message = FakeMessage(user_id=1, text="/mode practical")
    await handlers.cmd_mode(message, SimpleNamespace(args="practical"))
    assert message.answers
    assert "Доступ запрещен" in message.answers[0]["text"]
    assert "1" in message.answers[0]["text"]


@pytest.mark.asyncio
async def test_allowlist_accepts_username(monkeypatch):
    monkeypatch.setattr(
        "app.config.get_settings",
        lambda: SimpleNamespace(allowed_user_ids={999}, allowed_usernames={"student_user"}),
    )
    message = FakeMessage(user_id=1, username="student_user")
    await handlers.cmd_start(message)
    assert message.answers
    assert "VetStudy AI готов" in message.answers[0]["text"]
    assert "First value за 10 минут" in message.answers[0]["text"]
    assert "One-tap сценарий" in message.answers[1]["text"]


@pytest.mark.asyncio
async def test_mode_evidence_allowed(monkeypatch):
    monkeypatch.setattr(handlers, "_check_allow", lambda message: True)
    monkeypatch.setattr(handlers, "new_session", lambda: FakeDB())
    monkeypatch.setattr(
        handlers,
        "ChatDBService",
        lambda db: SimpleNamespace(
            ensure_user=lambda *a, **k: SimpleNamespace(id="u-1", settings={}),
            get_topic_for_chat_thread=lambda *a, **k: SimpleNamespace(id="t-1", subject_id="sub-1"),
        ),
    )
    monkeypatch.setattr(handlers, "SessionRepo", lambda db: SimpleNamespace(get_active=lambda *a, **k: SimpleNamespace(mode="practical"), new_active=lambda *a, **k: SimpleNamespace(mode="practical")))
    monkeypatch.setattr(handlers, "UserRepo", lambda db: SimpleNamespace(set_mode_preference=lambda *a, **k: None))
    message = FakeMessage(user_id=1, text="/mode evidence")
    await handlers.cmd_mode(message, SimpleNamespace(args="evidence"))
    assert any("evidence" in item["text"] for item in message.answers)


@pytest.mark.asyncio
async def test_why_command_shows_trace(monkeypatch):
    monkeypatch.setattr(handlers, "_check_allow", lambda message: True)
    monkeypatch.setattr(handlers, "new_session", lambda: FakeDB())
    monkeypatch.setattr(
        handlers,
        "ChatDBService",
        lambda db: SimpleNamespace(
            ensure_user=lambda *a, **k: SimpleNamespace(id="u-1", settings={}),
            get_topic_for_chat_thread=lambda *a, **k: SimpleNamespace(id="t-1", subject_id="sub-1"),
        ),
    )
    monkeypatch.setattr(handlers, "SessionRepo", lambda db: SimpleNamespace(get_active=lambda *a, **k: SimpleNamespace(id="s-1")))
    monkeypatch.setattr(
        handlers,
        "MessageRepo",
        lambda db: SimpleNamespace(
            last_assistant=lambda *a, **k: SimpleNamespace(
                metadata_={
                    "why_trace": {
                        "risk_intent": "dosage_request",
                        "risk_tags": ["dosage", "nsaids_in_cats"],
                        "needs_manual_check": True,
                        "manual_check_reasons": ["Нет точной концентрации."],
                        "missing_data": ["Уточните вид и вес."],
                    }
                }
            )
        ),
    )
    message = FakeMessage(user_id=1, text="/why")
    await handlers.cmd_why(message)
    text = message.answers[0]["text"]
    assert "risk intent: dosage_request" in text
    assert "needs_manual_check: yes" in text
    assert "Без внутренних системных промптов" in text


@pytest.mark.asyncio
async def test_why_command_uses_evidence_fallback_when_trace_missing(monkeypatch):
    monkeypatch.setattr(handlers, "_check_allow", lambda message: True)
    monkeypatch.setattr(handlers, "new_session", lambda: FakeDB())
    monkeypatch.setattr(
        handlers,
        "ChatDBService",
        lambda db: SimpleNamespace(
            ensure_user=lambda *a, **k: SimpleNamespace(id="u-1", settings={}),
            get_topic_for_chat_thread=lambda *a, **k: SimpleNamespace(id="t-1", subject_id="sub-1"),
        ),
    )
    monkeypatch.setattr(handlers, "SessionRepo", lambda db: SimpleNamespace(get_active=lambda *a, **k: SimpleNamespace(id="s-1")))
    monkeypatch.setattr(
        handlers,
        "MessageRepo",
        lambda db: SimpleNamespace(
            last_assistant=lambda *a, **k: SimpleNamespace(
                metadata_={
                    "safety": {"intent": "drug_interaction", "risk_tags": ["aminoglycoside_kidney_risk"]},
                    "evidence": {"status": "needs_manual_check", "next_questions": ["Уточните ХБП/ХПН и текущие препараты."]},
                }
            )
        ),
    )
    message = FakeMessage(user_id=1, text="/why")
    await handlers.cmd_why(message)
    text = message.answers[0]["text"]
    assert "risk intent: drug_interaction" in text
    assert "aminoglycoside_kidney_risk" in text
    assert "Уточните ХБП/ХПН" in text


@pytest.mark.asyncio
async def test_today_command_builds_route_and_tracks_event(monkeypatch):
    tracked = []
    monkeypatch.setattr(handlers, "_check_allow", lambda message: True)
    monkeypatch.setattr(handlers, "new_session", lambda: FakeDB())
    monkeypatch.setattr(
        handlers,
        "ChatDBService",
        lambda db: SimpleNamespace(
            ensure_user=lambda *a, **k: SimpleNamespace(id="u-1", settings={}),
            get_topic_for_chat_thread=lambda *a, **k: SimpleNamespace(id="t-1", subject_id="sub-1"),
        ),
    )
    monkeypatch.setattr(
        handlers,
        "ProductAnalyticsService",
        lambda db: SimpleNamespace(track=lambda **kwargs: tracked.append(kwargs)),
    )
    monkeypatch.setattr(
        handlers.LearningService,
        "build_daily_route",
        lambda self, **kwargs: SimpleNamespace(
            mode="standard",
            plan_minutes=25,
            mini_case="Собака с диареей: дифференциалы?",
            drug_risk="НПВС у кошек: check kidney and hydration.",
            due_count=4,
            review_cards=["Q1", "Q2", "Q3"],
            reflection_question="Что проверишь первым?",
            used_fallback=False,
            weak_topics=["Терапия"],
            zero_result_searches=1,
            negative_feedback_count=1,
            high_risk_block_count=4,
            skill_map={"therapy": {"confidence": 0.5, "errors": 1, "recent_case_level": "basic", "updated_from": "review/case/feedback/search"}},
            difficulty_band="medium",
            progression_mode="controlled_progression",
            recovery_mode=False,
            why_personalization="why",
        ),
    )
    monkeypatch.setattr(handlers.LearningService, "compute_streak", lambda self, **kwargs: (3, 0))
    message = FakeMessage(user_id=1, text="/today")
    await handlers.cmd_today(message)
    assert message.answers
    text = message.answers[0]["text"]
    assert "Маршрут на 25 минут (standard)" in text
    assert "карточки к сроку 4" in text.lower()
    assert "Zero-result поисков" in text
    assert "High-risk блокировок" in text
    assert "Streak: 3 дн." in text
    assert tracked and tracked[0]["event_name"] == "learning_route_opened"


@pytest.mark.asyncio
async def test_weekly_command_outputs_recap(monkeypatch):
    tracked = []
    monkeypatch.setattr(handlers, "_check_allow", lambda message: True)
    monkeypatch.setattr(handlers, "new_session", lambda: FakeDB())
    monkeypatch.setattr(
        handlers,
        "ChatDBService",
        lambda db: SimpleNamespace(ensure_user=lambda *a, **k: SimpleNamespace(id="u-1", settings={})),
    )
    monkeypatch.setattr(
        handlers.LearningService,
        "build_weekly_recap",
        lambda self, **kwargs: SimpleNamespace(
            cards_created=6,
            cards_reviewed=9,
            high_risk_queries=2,
            questions_asked=14,
            weak_topics=["Кардио"],
        ),
    )
    monkeypatch.setattr(handlers, "ProductAnalyticsService", lambda db: SimpleNamespace(track=lambda **kwargs: tracked.append(kwargs)))
    message = FakeMessage(user_id=1, text="/weekly")
    await handlers.cmd_weekly(message)
    assert "Weekly recap" in message.answers[0]["text"]
    assert "Кардио" in message.answers[0]["text"]
    assert tracked and tracked[0]["event_name"] == "weekly_recap_opened"


@pytest.mark.asyncio
async def test_plan_week_command_outputs_plan(monkeypatch):
    tracked = []
    monkeypatch.setattr(handlers, "_check_allow", lambda message: True)
    monkeypatch.setattr(handlers, "new_session", lambda: FakeDB())
    monkeypatch.setattr(
        handlers,
        "ChatDBService",
        lambda db: SimpleNamespace(
            ensure_user=lambda *a, **k: SimpleNamespace(id="u-1", settings={}),
            get_topic_for_chat_thread=lambda *a, **k: SimpleNamespace(id="t-1", subject_id="sub-1"),
        ),
    )
    monkeypatch.setattr(
        handlers.LearningService,
        "build_week_plan",
        lambda self, **kwargs: SimpleNamespace(
            days=[SimpleNamespace(day_index=1, mode="light", focus="Терапия", mini_case="Кейс", review_target=2, quiz_target=1, planned_commands=["/case", "/review", "/quiz"])],
            weak_topics=["Терапия"],
            overdue_count=3,
            streak_days=4,
            relaunch_days=0,
            workload_budget=12,
            total_density=10,
            why_plan="why",
        ),
    )
    monkeypatch.setattr(handlers, "ProductAnalyticsService", lambda db: SimpleNamespace(track=lambda **kwargs: tracked.append(kwargs)))
    message = FakeMessage(user_id=1, text="/plan_week")
    await handlers.cmd_plan_week(message)
    assert "Персональный план на 7 дней" in message.answers[0]["text"]
    assert "/case x1" in message.answers[0]["text"]
    assert tracked and tracked[0]["event_name"] == "weekly_plan_opened"


@pytest.mark.asyncio
async def test_profile_command_updates_settings(monkeypatch):
    user = SimpleNamespace(id="u-1", settings={})
    monkeypatch.setattr(handlers, "_check_allow", lambda message: True)
    monkeypatch.setattr(handlers, "new_session", lambda: FakeDB())
    monkeypatch.setattr(handlers, "UserRepo", lambda db: SimpleNamespace(get_or_create=lambda *a, **k: user))
    monkeypatch.setattr(handlers, "ProductAnalyticsService", lambda db: SimpleNamespace(track=lambda **k: None))
    message = FakeMessage(user_id=1, text="/profile region=eu species=cat density=quick")
    await handlers.cmd_profile(message, SimpleNamespace(args="region=eu species=cat density=quick"))
    assert user.settings["profile"]["region"] == "eu"
    assert user.settings["profile"]["species_focus"] == "cat"
    assert user.settings["profile"]["response_density"] == "quick"


@pytest.mark.asyncio
async def test_split_long_answer(monkeypatch):
    _patch_minimal_text_flow(monkeypatch, topic=SimpleNamespace(id="t-1", subject_id="sub-1", title="Терапия"))
    long_answer = ("строка\n" * 2500).strip()
    async def _generate(*args, **kwargs):
        return long_answer

    monkeypatch.setattr(handlers.llm_router, "generate", _generate)
    message = FakeMessage()
    await handlers.on_text(message)
    assert message.answers
    assert all(len(item["text"]) <= 3900 for item in message.answers)
    assert any("density=deep" in item["text"] for item in message.answers)


@pytest.mark.asyncio
async def test_context_compaction_marks_user_and_tracks(monkeypatch):
    tracked = []
    _patch_minimal_text_flow(monkeypatch, topic=SimpleNamespace(id="t-1", subject_id="sub-1", title="Терапия"))
    monkeypatch.setattr(
        handlers,
        "MessageRepo",
        lambda db: SimpleNamespace(
            add=lambda *a, **k: SimpleNamespace(id="m-1"),
            last_assistant=lambda *a, **k: None,
            recent_for_session=lambda *a, **k: [SimpleNamespace(role="user", content=("очень длинный контекст " * 40)) for _ in range(20)],
            count_for_session=lambda *a, **k: 1,
        ),
    )
    monkeypatch.setattr(handlers, "ProductAnalyticsService", lambda db: SimpleNamespace(track=lambda **kwargs: tracked.append(kwargs)))
    monkeypatch.setattr(handlers.llm_router, "generate", lambda *a, **k: _async_return("Ответ"))
    message = FakeMessage()
    await handlers.on_text(message)
    assert any("Контекст свернут" in item["text"] for item in message.answers)
    assert any(item["event_name"] == "context_compacted" for item in tracked)


def test_callback_parsing():
    parsed = handlers.parse_callback_data(handlers._callback_data("cards", "123"))
    assert parsed is not None
    assert parsed.action == "cards"
    assert parsed.payload == "123"
    assert handlers.parse_callback_data("invalid") is None
    assert handlers.parse_callback_data("vx:cards:123:bad-signature") is None


def test_review_keyboard_uses_signed_callbacks():
    markup = handlers._build_review_keyboard("card-1")
    callback_values = [button.callback_data for row in markup.inline_keyboard for button in row]
    assert callback_values
    assert all(isinstance(value, str) and value.startswith("vx:") for value in callback_values)
    assert all(handlers.parse_callback_data(value) is not None for value in callback_values)


@pytest.mark.asyncio
async def test_search_formats_results(monkeypatch):
    monkeypatch.setattr(handlers, "_check_allow", lambda message: True)
    monkeypatch.setattr(handlers, "new_session", lambda: FakeDB())
    monkeypatch.setattr(
        handlers,
        "ChatDBService",
        lambda db: SimpleNamespace(
            ensure_user=lambda *a, **k: SimpleNamespace(id="u-1"),
            get_topic_for_chat_thread=lambda *a, **k: SimpleNamespace(id="t-1", subject_id="sub-1", title="Терапия"),
        ),
    )
    monkeypatch.setattr(handlers, "TopicRepo", lambda db: SimpleNamespace(get_by_chat_thread=lambda *a, **k: SimpleNamespace(id="t-1", subject_id="sub-1", title="Терапия")))
    monkeypatch.setattr(
        handlers,
        "MemoryService",
        lambda *a, **k: SimpleNamespace(
            search=lambda *x, **y: _async_return(
                [
                    SimpleNamespace(topic_title="Терапия", created_at=__import__("datetime").datetime(2026, 1, 2), snippet="Фрагмент 1"),
                    SimpleNamespace(topic_title="Диагностика", created_at=__import__("datetime").datetime(2026, 1, 3), snippet="Фрагмент 2"),
                    SimpleNamespace(topic_title="Хирургия", created_at=__import__("datetime").datetime(2026, 1, 4), snippet="Фрагмент 3"),
                ]
            )
        ),
    )
    message = FakeMessage(text="/search панкреатит")
    command = SimpleNamespace(args="панкреатит")
    await handlers.cmd_search(message, command)
    text = message.answers[0]["text"]
    assert "1. [Терапия] 2026-01-02" in text
    assert "2. [Диагностика] 2026-01-03" in text
    assert "3. [Хирургия] 2026-01-04" in text


@pytest.mark.asyncio
async def test_voice_transcribes_and_answers(monkeypatch, tmp_path):
    monkeypatch.setattr(handlers, "_check_allow", lambda message: True)
    monkeypatch.setattr(handlers, "get_settings", lambda: SimpleNamespace(max_voice_file_size_bytes=1024 * 1024, multimodal_ocr_enabled=False, multimodal_vision_enabled=False, max_image_file_size_bytes=1, max_document_file_size_bytes=1))
    monkeypatch.setattr(handlers, "new_session", lambda: FakeDB())
    monkeypatch.setattr(
        handlers,
        "ChatDBService",
        lambda db: SimpleNamespace(
            ensure_user=lambda *a, **k: SimpleNamespace(id="u-1", settings={}),
            get_topic_for_chat_thread=lambda *a, **k: SimpleNamespace(id="t-1", subject_id="sub-1"),
            get_or_create_active_session=lambda *a, **k: SimpleNamespace(id="s-1", mode="practical"),
            save_user_message=lambda *a, **k: None,
            save_assistant_message=lambda *a, **k: SimpleNamespace(id="m-1"),
        ),
    )
    monkeypatch.setattr(handlers, "TopicRepo", lambda db: SimpleNamespace())
    monkeypatch.setattr(handlers, "SubjectRepo", lambda db: SimpleNamespace(get_by_id=lambda *a, **k: None))
    monkeypatch.setattr(handlers, "MessageRepo", lambda db: SimpleNamespace(recent_for_session=lambda *a, **k: []))
    monkeypatch.setattr(handlers, "MemoryRepo", lambda db: SimpleNamespace(add=lambda **k: None))
    monkeypatch.setattr(
        handlers,
        "MemoryService",
        lambda *a, **k: SimpleNamespace(search=lambda *x, **y: _async_return([]), ingest_assistant_answer=lambda *x, **y: _async_return(None)),
    )
    monkeypatch.setattr(handlers.prompt_manager, "build", lambda **k: "prompt")
    monkeypatch.setattr(handlers.safety_gate, "check", lambda text: SimpleNamespace(allowed=True, warning=None))
    async def _generate(*args, **kwargs):
        return "answer"
    monkeypatch.setattr(handlers.llm_router, "generate", _generate)
    monkeypatch.setattr(handlers.llm_router, "transcribe", lambda *a, **k: _async_return("привет"))
    monkeypatch.setattr(handlers, "download_telegram_file", lambda **k: _async_return(SimpleNamespace(path=tmp_path / "v.ogg", original_name="v.ogg", size_bytes=10)))
    (tmp_path / "v.ogg").write_bytes(b"abc")
    message = FakeMessage()
    message.voice = SimpleNamespace(file_id="1", file_size=12)
    await handlers.on_voice(message)
    assert any("Транскрипт" in a["text"] for a in message.answers)
    assert any("Structured summary" in a["text"] for a in message.answers)


@pytest.mark.asyncio
async def test_callback_pick_rejects_foreign_memory(monkeypatch):
    monkeypatch.setattr(handlers, "get_settings", lambda: SimpleNamespace(allowed_user_ids={7}))
    monkeypatch.setattr(handlers, "new_session", lambda: FakeDB())
    monkeypatch.setattr(
        handlers,
        "ChatDBService",
        lambda db: SimpleNamespace(
            ensure_user=lambda *a, **k: SimpleNamespace(id="u-owner", settings={}),
        ),
    )
    monkeypatch.setattr(
        handlers,
        "MemoryRepo",
        lambda db: SimpleNamespace(
            get=lambda _id: SimpleNamespace(user_id="u-other"),
        ),
    )
    query = SimpleNamespace(
        data=handlers._callback_data("pick", "62a95438-3d18-4231-8245-fca4f2f8c5b8"),
        from_user=SimpleNamespace(id=7, full_name="U"),
        answer=lambda *a, **k: _async_return(None),
        message=FakeMessage(),
    )
    await handlers.on_ai_action(query)
    assert any("чужой" in item["text"] for item in query.message.answers)


@pytest.mark.asyncio
async def test_callback_save_creates_note(monkeypatch):
    saved = []
    monkeypatch.setattr(handlers, "get_settings", lambda: SimpleNamespace(allowed_user_ids={7}))
    monkeypatch.setattr(handlers, "new_session", lambda: FakeDB())
    monkeypatch.setattr(
        handlers,
        "ChatDBService",
        lambda db: SimpleNamespace(
            ensure_user=lambda *a, **k: SimpleNamespace(id="u-1", settings={}),
            get_topic_for_chat_thread=lambda *a, **k: SimpleNamespace(id="t-1", subject_id="sub-1"),
        ),
    )
    monkeypatch.setattr(handlers, "SessionRepo", lambda db: SimpleNamespace(get_active=lambda *a, **k: SimpleNamespace(id="s-1")))
    monkeypatch.setattr(handlers, "MessageRepo", lambda db: SimpleNamespace(last_assistant=lambda *a, **k: SimpleNamespace(id="m-1", content="answer")))
    monkeypatch.setattr(handlers, "MemoryRepo", lambda db: SimpleNamespace(add=lambda **kwargs: saved.append(kwargs)))
    query = SimpleNamespace(
        data=handlers._callback_data("save"),
        from_user=SimpleNamespace(id=7, full_name="U"),
        answer=lambda *a, **k: _async_return(None),
        message=FakeMessage(),
    )
    await handlers.on_ai_action(query)
    assert saved
    assert saved[0]["kind"] == "note"
    assert any("Сохранено" in item["text"] for item in query.message.answers)


@pytest.mark.asyncio
async def test_callback_clarify_quick(monkeypatch):
    monkeypatch.setattr(handlers, "get_settings", lambda: SimpleNamespace(allowed_user_ids={7}))
    tracked = []
    monkeypatch.setattr(handlers, "new_session", lambda: FakeDB())
    monkeypatch.setattr(handlers, "UserRepo", lambda db: SimpleNamespace(get_or_create=lambda *a, **k: SimpleNamespace(id="u-1")))
    monkeypatch.setattr(handlers, "ProductAnalyticsService", lambda db: SimpleNamespace(track=lambda **kwargs: tracked.append(kwargs)))
    query = SimpleNamespace(
        data=handlers._callback_data("clarify_quick", "drug"),
        from_user=SimpleNamespace(id=7, full_name="U"),
        answer=lambda *a, **k: _async_return(None),
        message=FakeMessage(),
    )
    await handlers.on_ai_action(query)
    assert any("препарат=" in item["text"] for item in query.message.answers)
    assert any(item["event_name"] == "safety_clarification_completed" for item in tracked)


@pytest.mark.asyncio
async def test_continue_prefers_active_case(monkeypatch):
    tracked = []
    user = SimpleNamespace(id="u-1", settings={"active_case_id": "vomiting_dog"})
    monkeypatch.setattr(handlers, "_check_allow", lambda message: True)
    monkeypatch.setattr(handlers, "new_session", lambda: FakeDB())
    monkeypatch.setattr(
        handlers,
        "ChatDBService",
        lambda db: SimpleNamespace(
            ensure_user=lambda *a, **k: user,
            get_topic_for_chat_thread=lambda *a, **k: SimpleNamespace(id="t-1", subject_id="sub-1"),
        ),
    )
    monkeypatch.setattr(handlers, "ProductAnalyticsService", lambda db: SimpleNamespace(track=lambda **kwargs: tracked.append(kwargs)))
    called = []
    async def _cmd_case(message, command):
        called.append(command.args)
    monkeypatch.setattr(handlers, "cmd_case", _cmd_case)
    message = FakeMessage(user_id=1, text="/continue")
    await handlers.cmd_continue(message)
    assert called == ["vomiting_dog"]
    events = [item["event_name"] for item in tracked]
    assert "resume_requested" in events
    assert "resume_completed" in events


@pytest.mark.asyncio
async def test_callback_learning_three_cards_tracks_completion(monkeypatch):
    tracked = []
    monkeypatch.setattr(handlers, "get_settings", lambda: SimpleNamespace(allowed_user_ids={7}))
    monkeypatch.setattr(handlers, "new_session", lambda: FakeDB())
    monkeypatch.setattr(
        handlers,
        "ChatDBService",
        lambda db: SimpleNamespace(
            ensure_user=lambda *a, **k: SimpleNamespace(id="u-1", settings={}),
            get_topic_for_chat_thread=lambda *a, **k: SimpleNamespace(id="t-1", subject_id="sub-1"),
        ),
    )
    monkeypatch.setattr(handlers, "ProductAnalyticsService", lambda db: SimpleNamespace(track=lambda **kwargs: tracked.append(kwargs)))
    monkeypatch.setattr(handlers, "SessionRepo", lambda db: SimpleNamespace(get_active=lambda *a, **k: SimpleNamespace(id="s-1")))
    monkeypatch.setattr(handlers, "MessageRepo", lambda db: SimpleNamespace(last_assistant=lambda *a, **k: SimpleNamespace(id="m-1", content="answer")))
    monkeypatch.setattr(
        handlers.LearningService,
        "generate_cards_structured",
        lambda self, **kwargs: _async_return(
            [
                {"front": "Q1 long enough", "back": "A1 long enough", "tags": [], "card_type": "fact", "needs_manual_check": False},
                {"front": "Q2 long enough", "back": "A2 long enough", "tags": [], "card_type": "fact", "needs_manual_check": False},
                {"front": "Q3 long enough", "back": "A3 long enough", "tags": [], "card_type": "fact", "needs_manual_check": False},
            ]
        ),
    )
    monkeypatch.setattr(handlers, "FlashcardRepo", lambda db: SimpleNamespace(add_many=lambda cards: None))
    query = SimpleNamespace(
        data=handlers._callback_data("learning_three_cards", "learning"),
        from_user=SimpleNamespace(id=7, full_name="U"),
        answer=lambda *a, **k: _async_return(None),
        message=FakeMessage(),
    )
    await handlers.on_ai_action(query)
    assert any("3 карточки" in item["text"] for item in query.message.answers)
    assert any(item["event_name"] == "learning_cta_clicked" for item in tracked)
    assert any(item["event_name"] == "learning_step_completed" for item in tracked)

@pytest.mark.asyncio
async def test_review_shows_leech_hint(monkeypatch):
    monkeypatch.setattr(handlers, "_check_allow", lambda message: True)
    monkeypatch.setattr(handlers, "new_session", lambda: FakeDB())
    monkeypatch.setattr(
        handlers,
        "ChatDBService",
        lambda db: SimpleNamespace(
            ensure_user=lambda *a, **k: SimpleNamespace(id="u-1", settings={}),
            get_topic_for_chat_thread=lambda *a, **k: SimpleNamespace(id="t-1", subject_id="sub-1"),
        ),
    )
    monkeypatch.setattr(
        handlers,
        "FlashcardRepo",
        lambda db: SimpleNamespace(
            list_due=lambda *a, **k: [SimpleNamespace(id="c-1", front="Question", tags=["leech"])]
        ),
    )
    message = FakeMessage(user_id=1, text="/review")
    await handlers.cmd_review(message)
    assert message.answers
    assert "разбить карточку" in message.answers[0]["text"]


@pytest.mark.asyncio
async def test_checkpoint_command_outputs_score(monkeypatch):
    tracked = []
    monkeypatch.setattr(handlers, "_check_allow", lambda message: True)
    monkeypatch.setattr(handlers, "new_session", lambda: FakeDB())
    monkeypatch.setattr(
        handlers,
        "ChatDBService",
        lambda db: SimpleNamespace(
            ensure_user=lambda *a, **k: SimpleNamespace(id="u-1", settings={}),
            get_topic_for_chat_thread=lambda *a, **k: SimpleNamespace(id="t-1", subject_id="sub-1", title="Терапия", summary="S"),
        ),
    )
    monkeypatch.setattr(handlers, "SessionRepo", lambda db: SimpleNamespace(get_active=lambda *a, **k: SimpleNamespace(id="s-1")))
    monkeypatch.setattr(handlers, "MessageRepo", lambda db: SimpleNamespace(last_assistant=lambda *a, **k: SimpleNamespace(content="ctx")))
    monkeypatch.setattr(handlers, "ProductAnalyticsService", lambda db: SimpleNamespace(track=lambda **kwargs: tracked.append(kwargs)))
    monkeypatch.setattr(handlers.LearningService, "generate_checkpoint", lambda self, **kwargs: _async_return([{"type": "mcq", "question": "Q1", "correct_answer": "B", "rationale": "R", "misconception_tag": "tag1", "why_in_practice": "W"}]))
    monkeypatch.setattr(handlers.LearningService, "evaluate_checkpoint", lambda self, **kwargs: SimpleNamespace(checkpoint_score=20, misconception_tags=["tag1"], recommended_next_step="/fix_gaps", breakdown="Breakdown"))
    monkeypatch.setattr(handlers.LearningService, "detect_weak_skills_for_topic", lambda self, **kwargs: ["low_review_retention"])
    monkeypatch.setattr(handlers.LearningService, "update_mastery_for_topic", lambda self, **kwargs: ({"score": 40, "confidence": 0.4}, ["tag1"]))
    message = FakeMessage(user_id=1, text="/checkpoint")
    await handlers.cmd_checkpoint(message)
    assert any("Checkpoint стартовал" in item["text"] for item in message.answers)
    assert any("Checkpoint Q1/" in item["text"] for item in message.answers)
    assert any(item["event_name"] == "checkpoint_started" for item in tracked)


@pytest.mark.asyncio
async def test_fix_gaps_builds_playlist(monkeypatch):
    tracked = []
    monkeypatch.setattr(handlers, "_check_allow", lambda message: True)
    monkeypatch.setattr(handlers, "new_session", lambda: FakeDB())
    monkeypatch.setattr(
        handlers,
        "ChatDBService",
        lambda db: SimpleNamespace(
            ensure_user=lambda *a, **k: SimpleNamespace(id="u-1", settings={"weak_skills": ["topic:therapy"]}),
            get_topic_for_chat_thread=lambda *a, **k: SimpleNamespace(id="t-1", subject_id="sub-1", title="Терапия"),
        ),
    )
    monkeypatch.setattr(handlers, "ProductAnalyticsService", lambda db: SimpleNamespace(track=lambda **kwargs: tracked.append(kwargs)))
    monkeypatch.setattr(handlers.LearningService, "build_daily_route", lambda self, **kwargs: SimpleNamespace(high_risk_block_count=1, weak_topics=["topic:therapy"]))
    monkeypatch.setattr(
        handlers.LearningService,
        "build_remediation_plan",
        lambda self, **kwargs: SimpleNamespace(
            weak_skills=["topic:therapy"],
            steps=[
                {"kind": "mini_case", "title": "Mini", "command": "/case basic"},
                {"kind": "card", "title": "Card1", "command": "/cards"},
                {"kind": "card", "title": "Card2", "command": "/cards"},
                {"kind": "card", "title": "Card3", "command": "/cards"},
                {"kind": "micro_quiz", "title": "Quiz", "command": "/quiz"},
            ],
            safety_framing=True,
            recommended_next_step="/today light",
        ),
    )
    message = FakeMessage(user_id=1, text="/fix_gaps")
    await handlers.cmd_fix_gaps(message)
    assert any("Adaptive remediation playlist" in item["text"] for item in message.answers)
    assert any(item["event_name"] == "remediation_plan_generated" for item in tracked)
