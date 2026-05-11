from app.ai.safety import SafetyGate


def test_dosage_requires_weight():
    gate = SafetyGate()
    result = gate.check("дай дозировку мелоксикама кошке")
    assert result.action == "ask_clarifying_questions"
    assert result.allowed is True  # non-blocking: questions shown as soft hint
    assert any("масса" in q.lower() for q in (result.clarifying_questions or []))


def test_dosage_with_weight_allowed():
    gate = SafetyGate()
    result = gate.check(
        "доза мелоксикама кошка 4 кг, взрослый, при боли, суспензия 1.5 мг/мл, внутрь, не беременна, без ХБП/ХПН/ХСН, текущие препараты: нет"
    )
    assert result.allowed is True
    assert result.action in {"allow", "answer_with_warning"}


def test_acceptance_paracetamol_cat_warning():
    gate = SafetyGate()
    result = gate.check("парацетамол кошке")
    assert result.action == "answer_with_warning"  # toxicology: non-blocking with warning
    assert result.allowed is True
    assert "paracetamol_in_cats" in result.risk_tags


def test_acceptance_collie_ivermectin_warning():
    gate = SafetyGate()
    result = gate.check("собака колли и ивермектин")
    assert result.action == "answer_with_warning"
    assert "ivermectin_mdr1_risk" in result.risk_tags


def test_acceptance_nsaid_pred_warning():
    gate = SafetyGate()
    result = gate.check("НПВС + преднизолон")
    assert result.action == "answer_with_warning"
    assert "steroid_plus_nsaid" in result.risk_tags


def test_general_education_not_blocked():
    gate = SafetyGate()
    result = gate.check("объясни механизм действия НПВС у собак")
    assert result.allowed is True
    assert result.action in {"allow", "answer_with_warning"}


def test_intent_dosage_request():
    gate = SafetyGate()
    result = gate.check("сколько дать мг/кг собаке")
    assert result.intent == "dosage_request"


def test_intent_clinical_case():
    gate = SafetyGate()
    result = gate.check("клинический случай: собака с рвотой и диагнозом гастрит")
    assert result.intent == "clinical_case"


def test_intent_toxicology():
    gate = SafetyGate()
    result = gate.check("подозрение на отравление у кошки")
    assert result.intent == "toxicology"


def test_intent_drug_interaction():
    gate = SafetyGate()
    result = gate.check("можно ли вместе карпрофен + преднизолон")
    assert result.intent == "drug_interaction"


def test_intent_uncertain_source():
    gate = SafetyGate()
    result = gate.check("на форуме советуют дать это собаке")
    assert result.intent == "uncertain_source"


def test_intent_emergency_red_flag():
    gate = SafetyGate()
    result = gate.check("кошка не дышит, что делать срочно")
    assert result.intent == "emergency_or_red_flag"
    assert result.action == "answer_with_warning"  # non-blocking: full protocol given
    assert result.allowed is True


def test_nsaids_in_cats_risk_tag():
    gate = SafetyGate()
    result = gate.check("мелоксикам кошке")
    assert "nsaids_in_cats" in result.risk_tags


def test_aminoglycoside_kidney_risk_tag():
    gate = SafetyGate()
    result = gate.check("гентамицин у собаки с болезнью почек")
    assert "aminoglycoside_kidney_risk" in result.risk_tags


def test_anticoagulants_risk_tag():
    gate = SafetyGate()
    result = gate.check("варфарин у собаки")
    assert "anticoagulants_risk" in result.risk_tags


def test_anesthesia_sedation_combination_tag():
    gate = SafetyGate()
    result = gate.check("кетамин + медетомидин для седации")
    assert "anesthesia_sedation_combination" in result.risk_tags


def test_dosage_missing_species_asks():
    gate = SafetyGate()
    result = gate.check("доза амоксициллина 10 кг")
    assert result.action == "ask_clarifying_questions"
    assert any("вид" in q.lower() for q in (result.clarifying_questions or []))


def test_dosage_reordered_skolko_dat_detected():
    gate = SafetyGate()
    result = gate.check("Сколько амоксициллина дать собаке 12 кг при пиодермии?")
    assert result.intent == "dosage_request"
    assert result.action == "ask_clarifying_questions"
    assert any("форма" in q.lower() or "концентра" in q.lower() for q in (result.clarifying_questions or []))


def test_paracetamol_kot_detects_cat_warning():
    gate = SafetyGate()
    result = gate.check("Кот съел таблетку парацетамола")
    assert result.action == "answer_with_warning"  # toxicology: non-blocking, full protocol
    assert result.allowed is True
    assert "paracetamol_in_cats" in result.risk_tags


def test_emergency_russian_seizure_phrase_escalates():
    gate = SafetyGate()
    result = gate.check("Кошка в судорогах 5 минут")
    assert result.intent == "emergency_or_red_flag"
    assert result.action == "answer_with_warning"  # non-blocking: full emergency protocol
    assert result.allowed is True


def test_dosage_russian_inflection_detected():
    gate = SafetyGate()
    result = gate.check("Дай дозу мелоксикама кошке")
    assert result.intent == "dosage_request"
    assert result.action == "ask_clarifying_questions"
    assert result.allowed is True  # non-blocking


def test_toxicology_chocolate_ingestion_detected():
    gate = SafetyGate()
    result = gate.check("Собака съела шоколад")
    assert result.intent == "toxicology"
    assert result.action == "answer_with_warning"  # non-blocking: full tox protocol
    assert result.allowed is True
    assert "toxic_exposure_common" in result.risk_tags


def test_toxicology_xylitol_and_raisin_detected():
    gate = SafetyGate()
    xylitol = gate.check("Собака съела ксилит")
    raisin = gate.check("Собака съела изюм")
    assert xylitol.intent == "toxicology"
    assert raisin.intent == "toxicology"


def test_toxicology_permethrin_for_cat_detected():
    gate = SafetyGate()
    result = gate.check("Кошка слизала перметрин")
    assert result.intent == "toxicology"
    assert result.action == "answer_with_warning"  # non-blocking


def test_interaction_phrase_without_plus_detected():
    gate = SafetyGate()
    result = gate.check("Есть ли взаимодействия у гентамицина при ХБП?")
    assert result.intent == "drug_interaction"
    assert "aminoglycoside_kidney_risk" in result.risk_tags


def test_dosage_missing_route_asks():
    gate = SafetyGate()
    result = gate.check("доза амоксициллина собаке 10 кг, при пиодермии, таблетки 250 мг, взрослый, не беременна, без почечной недостаточности, текущие препараты: нет")
    assert result.action == "ask_clarifying_questions"
    assert any("путь введения" in q.lower() for q in (result.clarifying_questions or []))


def test_dosage_missing_current_drugs_asks():
    gate = SafetyGate()
    result = gate.check("доза амоксициллина собаке 10 кг, при пиодермии, таблетки 250 мг, взрослый, внутрь, не беременна, без почечной недостаточности")
    assert result.action == "ask_clarifying_questions"
    assert any("какие препараты" in q.lower() for q in (result.clarifying_questions or []))


def test_dosage_missing_indication_asks():
    gate = SafetyGate()
    result = gate.check("доза амоксициллина собаке 10 кг, таблетки 250 мг, взрослый, внутрь, не беременна, без почечной недостаточности, текущие препараты: нет")
    assert result.action == "ask_clarifying_questions"
    assert any("показание" in q.lower() for q in (result.clarifying_questions or []))


def test_disclaimers_present():
    gate = SafetyGate()
    result = gate.check("парацетамол кошке")
    assert result.disclaimers is not None
    assert len(result.disclaimers) == 2  # reduced from 3: no more "учебная помощь" entry
