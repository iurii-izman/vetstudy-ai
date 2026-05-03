from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ValidationResult:
    ok: bool
    flags: list[str]
    rewritten_answer: str


class PostGenerationValidator:
    _DOSAGE_CALC_PATTERN = re.compile(r"\b(мг/кг|mg/kg|доз[аы]|сколько\s+дать)\b", re.IGNORECASE)
    _HAS_NUMERIC_DOSING = re.compile(r"\b\d+(?:[.,]\d+)?\s*(мг/кг|mg/kg|мг|mg|мл|ml)\b", re.IGNORECASE)
    _HAS_REQUIRED_DOSING_DATA = re.compile(
        r"\b(кг|kg|концентрац|мг/мл|mg/ml|внутрь|po|iv|im|sc|текущие препараты|принимает)\b",
        re.IGNORECASE,
    )
    _EMERGENCY_PATTERN = re.compile(r"\b(не\s+дыш|без\s+сознания|судорог|коллапс|сильн\w+\s+кровотеч)\b", re.IGNORECASE)
    _TRIAGE_PATTERN = re.compile(r"\b(сроч\w*|неотлож\w*|клиник\w*|ветеринар\w*)\b", re.IGNORECASE)
    _UNSAFE_HOME_PATTERN = re.compile(r"\b(дайте\s+дома|лечите\s+дома|подождите\s+дома)\b", re.IGNORECASE)
    _TOX_PATTERN = re.compile(r"\b(парацетамол|acetaminophen|отрав\w*|токс\w*)\b", re.IGNORECASE)
    _INTERACTION_ASSERTIVE_PATTERN = re.compile(r"\b(нет\s+взаимодействий|взаимодействий\s+нет)\b", re.IGNORECASE)
    _INTERACTION_CHECK_PATTERN = re.compile(r"\b(провер|инструкц|справочник|формуляр)\b", re.IGNORECASE)
    _DOSAGE_SOURCE_PATTERN = re.compile(
        r"\b(источник|цитат|citation|ansa|ema|upd|spc|smpc|инструкц|label|листок|формуляр|formulary|plumb|bsava|merck|msd)\b",
        re.IGNORECASE,
    )
    _SOURCE_UNCERTAIN_PATTERN = re.compile(r"\b(форум|reddit|тикток|знаком\w+\s+сказал)\b", re.IGNORECASE)
    _SOURCE_CHECK_PATTERN = re.compile(r"\b(требует\s+проверки|нужно\s+проверить|проверьте\s+источник)\b", re.IGNORECASE)
    _DIAGNOSIS_CERTAINTY_PATTERN = re.compile(r"\b(точный\s+диагноз|окончательный\s+диагноз|это\s+точно)\b", re.IGNORECASE)
    _EXAM_NEEDED_PATTERN = re.compile(r"\b(очного\s+осмотр|осмотр[ае]\s+ветеринар\w*|нужен\s+осмотр)\b", re.IGNORECASE)

    def validate(self, *, question: str, answer: str) -> ValidationResult:
        flags: list[str] = []
        rewritten = answer
        q = question.lower()
        a = answer.lower()

        if (self._DOSAGE_CALC_PATTERN.search(q) or self._HAS_NUMERIC_DOSING.search(a)) and self._HAS_NUMERIC_DOSING.search(a) and not self._HAS_REQUIRED_DOSING_DATA.search(q):
            flags.append("dosage_missing_required_data")
        if self._HAS_NUMERIC_DOSING.search(a) and not self._DOSAGE_SOURCE_PATTERN.search(a):
            flags.append("dosage_without_source_reference")
        if self._EMERGENCY_PATTERN.search(q):
            if not self._TRIAGE_PATTERN.search(a):
                flags.append("emergency_no_escalation")
            if self._UNSAFE_HOME_PATTERN.search(a):
                flags.append("emergency_unsafe_home_instruction")
        if self._TOX_PATTERN.search(q):
            if "токс" not in a and "отрав" not in a:
                flags.append("toxicology_no_warning")
            if not self._TRIAGE_PATTERN.search(a):
                flags.append("toxicology_no_escalation")
        if "взаимодейств" in q and self._INTERACTION_ASSERTIVE_PATTERN.search(a) and not self._INTERACTION_CHECK_PATTERN.search(a):
            flags.append("drug_interaction_overconfident")
        if self._SOURCE_UNCERTAIN_PATTERN.search(q) and not self._SOURCE_CHECK_PATTERN.search(a):
            flags.append("source_uncertainty_not_marked")
        if self._DIAGNOSIS_CERTAINTY_PATTERN.search(a) and not self._EXAM_NEEDED_PATTERN.search(a):
            flags.append("medical_certainty_without_exam")

        if flags:
            rewritten = (
                f"{answer.rstrip()}\n\n"
                "Проверка безопасности: ответ требует дополнительной верификации и очной клинической оценки."
            )
        return ValidationResult(ok=not flags, flags=flags, rewritten_answer=rewritten)
