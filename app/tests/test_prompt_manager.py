from pathlib import Path

from app.ai.prompts import PromptManager


SNAPSHOTS_DIR = Path(__file__).parent / "snapshots"


def _snapshot(name: str) -> str:
    return (SNAPSHOTS_DIR / name).read_text(encoding="utf-8").removesuffix("\n")


def test_prompt_snapshot_pharmacology_practical():
    pm = PromptManager()
    prompt = pm.build(
        mode="practical",
        subject="pharmacology",
        user_message="Как применять НПВС при острой боли у собаки?",
        memory_chunks=["Ранее обсуждали мелоксикам и контроль ЖКТ рисков."],
        session_history=["user: Нужен быстрый алгоритм", "assistant: Сначала triage и pain score"],
        safety_warning="Проверьте видовую токсичность и противопоказания для кошек перед применением.",
    )
    assert prompt == _snapshot("prompt_pharmacology_practical.txt")


def test_prompt_snapshot_exam_diagnostics():
    pm = PromptManager()
    prompt = pm.build(
        mode="exam",
        subject="diagnostics",
        user_message="Как отличить преренальную и ренальную азотемию?",
        memory_chunks=["Пользователь просил больше кейсов с биохимией крови."],
        session_history=["user: Разбери по шагам", "assistant: Нужны анамнез, удельный вес мочи и динамика"],
    )
    assert prompt == _snapshot("prompt_exam_diagnostics.txt")


def test_pharmacology_dosing_guard_text_present():
    pm = PromptManager()
    prompt = pm.build(
        mode="deep",
        subject="pharmacology",
        user_message="Дай дозу препарата X",
        memory_chunks=[],
        session_history=[],
    )
    assert "Дозировки: только через safety gate" in prompt
