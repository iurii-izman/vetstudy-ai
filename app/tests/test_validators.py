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


def test_dosage_validator_flags_without_numeric_when_source_missing():
    v = PostGenerationValidator()
    r = v.validate(
        question="Сколько дать амоксициллина собаке 12 кг?",
        answer="Для учебного кейса учитывайте вид, массу и путь введения.",
    )
    assert "dosage_without_source_reference" in r.flags


def test_emergency_validator_requires_triage_marker():
    v = PostGenerationValidator()
    r = v.validate(
        question="Кошка в судорогах, что делать?",
        answer="Срочно в клинику.",
    )
    assert "emergency_missing_triage_marker" not in r.flags


def test_toxicology_validator_requires_triage_marker():
    v = PostGenerationValidator()
    r = v.validate(
        question="Собака съела ксилит",
        answer="Это токсикологический риск, срочно в клинику.",
    )
    assert "toxicology_missing_triage_marker" not in r.flags


def test_high_risk_overconfident_flag():
    v = PostGenerationValidator()
    r = v.validate(
        question="Сколько дать карпрофена собаке?",
        answer="Точно дайте 4 мг/кг, это абсолютно безопасно.",
    )
    assert "high_risk_overconfident_tone" in r.flags
