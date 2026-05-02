from app.ai.validators import PostGenerationValidator


def test_dosage_validator_flags_missing_data():
    v = PostGenerationValidator()
    r = v.validate(question="Сколько амоксициллина дать собаке?", answer="Дайте 20 мг/кг дважды в день.")
    assert "dosage_missing_required_data" in r.flags


def test_toxicology_validator_flags_missing_escalation():
    v = PostGenerationValidator()
    r = v.validate(question="Кот съел парацетамол", answer="Наблюдайте дома.")
    assert "toxicology_no_escalation" in r.flags
