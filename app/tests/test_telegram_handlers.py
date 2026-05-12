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
            mini_case="Собака с диареей: дифференциалы?",
            drug_risk="НПВС у кошек: check kidney and hydration.",
            due_count=4,
            review_cards=["Q1", "Q2", "Q3"],
            reflection_question="Что проверишь первым?",
            used_fallback=False,
            weak_topics=["Терапия"],
            zero_result_searches=1,
            negative_feedback_count=1,
        ),
    )
    message = FakeMessage(user_id=1, text="/today")
    await handlers.cmd_today(message)
    assert message.answers
    text = message.answers[0]["text"]
    assert "Маршрут на 15-30 минут" in text
    assert "карточки к сроку 4" in text.lower()
    assert "Zero-result поисков" in text
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
async def test_profile_command_updates_settings(monkeypatch):
    user = SimpleNamespace(id="u-1", settings={})
    monkeypatch.setattr(handlers, "_check_allow", lambda message: True)
    monkeypatch.setattr(handlers, "new_session", lambda: FakeDB())
    monkeypatch.setattr(handlers, "UserRepo", lambda db: SimpleNamespace(get_or_create=lambda *a, **k: user))
    monkeypatch.setattr(handlers, "ProductAnalyticsService", lambda db: SimpleNamespace(track=lambda **k: None))
    message = FakeMessage(user_id=1, text="/profile region=eu species=cat")
    await handlers.cmd_profile(message, SimpleNamespace(args="region=eu species=cat"))
    assert user.settings["profile"]["region"] == "eu"
    assert user.settings["profile"]["species_focus"] == "cat"


@pytest.mark.asyncio
async def test_split_long_answer(monkeypatch):
    _patch_minimal_text_flow(monkeypatch, topic=SimpleNamespace(id="t-1", subject_id="sub-1", title="Терапия"))
    long_answer = ("строка\n" * 2500).strip()
    async def _generate(*args, **kwargs):
        return long_answer

    monkeypatch.setattr(handlers.llm_router, "generate", _generate)
    message = FakeMessage()
    await handlers.on_text(message)
    assert len(message.answers) > 1
    assert all(len(item["text"]) <= 3900 for item in message.answers)


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
