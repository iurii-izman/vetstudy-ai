from app.ai.safety import SafetyGate


def test_dosage_requires_weight():
    gate = SafetyGate()
    result = gate.check("дай дозировку мелоксикама кошке")
    assert result.action == "ask_clarifying_questions"
    assert result.allowed is False
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
    assert result.action == "answer_with_warning"
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
    assert result.action == "refuse_emergency_instruction_and_triage"
    assert result.allowed is False


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
    assert len(result.disclaimers) == 3
