from app.ai.validators import PostGenerationValidator


def test_dosage_validator_flags_missing_data():
    v = PostGenerationValidator()
    r = v.validate(question="Сколько амоксициллина дать собаке?", answer="Дайте 20 мг/кг дважды в день.")
    assert "dosage_missing_required_data" in r.flags


def test_toxicology_validator_flags_missing_escalation():
    v = PostGenerationValidator()
    r = v.validate(question="Кот съел парацетамол", answer="Наблюдайте дома.")
    assert "toxicology_no_escalation" in r.flags


def test_dosage_validator_flags_numeric_dose_without_source():
    v = PostGenerationValidator()
    r = v.validate(
        question="Собака 12 кг, амоксициллин суспензия 50 мг/мл, какая учебная доза?",
        answer="Доза 20 мг/кг внутрь.",
    )
    assert "dosage_without_source_reference" in r.flags


def test_dosage_validator_accepts_numeric_dose_with_source_marker():
    v = PostGenerationValidator()
    r = v.validate(
        question="Собака 12 кг, амоксициллин суспензия 50 мг/мл, внутрь, какая учебная доза?",
        answer="Учебный расчет по formulary/source: 20 мг/кг внутрь.",
    )
    assert "dosage_without_source_reference" not in r.flags
