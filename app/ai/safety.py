import re
from dataclasses import dataclass
from typing import Literal


@dataclass
class SafetyResult:
    action: Literal[
        "allow",
        "ask_clarifying_questions",
        "answer_with_warning",
        "refuse_emergency_instruction_and_triage",
    ]
    intent: Literal[
        "general_education",
        "dosage_request",
        "clinical_case",
        "emergency_or_red_flag",
        "toxicology",
        "drug_interaction",
        "uncertain_source",
    ]
    risk_tags: list[str]
    allowed: bool
    warning: str | None = None
    clarifying_questions: list[str] | None = None
    disclaimers: list[str] | None = None


class SafetyGate:
    DOSAGE_PATTERN = re.compile(
        r"\b(доза|дозиров\w*|мг/кг|mg/kg|сколько\b.{0,50}\bдать|рассчита\w*\b.{0,50}\bдоз\w*)\b",
        re.IGNORECASE,
    )
    CLINICAL_CASE_PATTERN = re.compile(r"\b(симптом|анамнез|кейс|случай|диагноз|лечение)\b", re.IGNORECASE)
    EMERGENCY_PATTERN = re.compile(
        r"\b(не\s+дыш|судорог|коллапс|без\s+сознания|остановк[аи]\s+дыхания|сильн\w+\s+кровотеч|анафилакс|срочно|реанимац)\b",
        re.IGNORECASE,
    )
    TOX_PATTERN = re.compile(r"\b(отрав\w*|токс\w*|яд\w*|парацетамол\w*|acetaminophen)\b", re.IGNORECASE)
    INTERACTION_PATTERN = re.compile(r"\b(\+|вместе|комбинац|взаимодейств)\b", re.IGNORECASE)
    UNCERTAIN_SOURCE_PATTERN = re.compile(r"\b(форум\w*|чатgpt|тикток|reddit|знаком\w+\s+сказал)\b", re.IGNORECASE)

    CAT_PATTERN = re.compile(r"\b(кошк\w*|кот|кота|коту|котом|котен\w*|cat)\b", re.IGNORECASE)
    DOG_PATTERN = re.compile(r"\b(собак\w*|пес|пёс|пса|псу|dog)\b", re.IGNORECASE)
    WEIGHT_PATTERN = re.compile(r"\b\d+(?:[.,]\d+)?\s?(кг|kg)\b", re.IGNORECASE)
    AGE_PATTERN = re.compile(r"\b(\d+\s?(мес|месяц|лет|год)|щенок|котенок|пожил\w*|senior)\b", re.IGNORECASE)
    INDICATION_PATTERN = re.compile(r"\b(при|для|из-за|диагноз|артрит|боль|лихорад)\b", re.IGNORECASE)
    FORM_PATTERN = re.compile(r"\b(таблетк\w*|суспенз\w*|раствор\w*|инъекц\w*|капсул\w*|капли|mg/ml|мг/мл|%|мл)\b", re.IGNORECASE)
    ROUTE_PATTERN = re.compile(r"\b(per os|po|внутрь|iv|im|sc|s/c|подкожно|в/в|в/м)\b", re.IGNORECASE)
    PREGNANCY_PATTERN = re.compile(r"\b(беремен\w*|лактац\w*|кормящ\w*)\b", re.IGNORECASE)
    ORGAN_STATUS_PATTERN = re.compile(r"\b(поч\w+|renal|kidney|печ\w+|liver|серд\w+|heart|хпн|хбп)\b", re.IGNORECASE)
    CURRENT_DRUGS_PATTERN = re.compile(
        r"\b(принимает|уже\s+дает|текущ\w+\s+препарат\w*|текущие\s+препараты|на\s+препарат\w*)\b",
        re.IGNORECASE,
    )

    NSAID_PATTERN = re.compile(r"\b(нпвс|nsaid|мелоксикам|карпрофен|кетопрофен)\b", re.IGNORECASE)
    PARACETAMOL_PATTERN = re.compile(r"\b(парацетамол\w*|acetaminophen)\b", re.IGNORECASE)
    IVERMECTIN_PATTERN = re.compile(r"\b(ивермектин|ivermectin)\b", re.IGNORECASE)
    MDR1_PATTERN = re.compile(r"\b(mdr1|колли|шелти|австралийск\w+\s+овчарк\w*)\b", re.IGNORECASE)
    STEROID_PATTERN = re.compile(r"\b(преднизолон|дексаметазон|стероид)\b", re.IGNORECASE)
    AMINOGLYCOSIDE_PATTERN = re.compile(r"\b(гентамицин|амикацин|неомицин|аминогликозид)\b", re.IGNORECASE)
    ANTICOAG_PATTERN = re.compile(r"\b(антикоагулянт|варфарин|гепарин|клопидогрел)\b", re.IGNORECASE)
    ANESTH_PATTERN = re.compile(r"\b(анестези\w*|седац\w*|пропофол|кетамин|медетомидин|дексмедетомидин)\b", re.IGNORECASE)

    DISCLAIMERS = [
        "Проверьте по актуальной инструкции/формуляру.",
        "Это учебная помощь, не замена очному решению врача.",
        "При красных флагах нужна срочная очная помощь.",
    ]

    def check(self, text: str) -> SafetyResult:
        intent = self._classify_intent(text)
        risk_tags = self._detect_risk_tags(text)

        if intent == "emergency_or_red_flag":
            return SafetyResult(
                action="refuse_emergency_instruction_and_triage",
                intent=intent,
                risk_tags=risk_tags,
                allowed=False,
                warning="Красные флаги: нужна срочная очная/неотложная помощь. Удаленно нельзя давать пошаговые экстренные инструкции.",
                disclaimers=self.DISCLAIMERS,
            )

        if intent == "dosage_request":
            questions = self._build_dosage_clarifying_questions(text)
            if questions:
                return SafetyResult(
                    action="ask_clarifying_questions",
                    intent=intent,
                    risk_tags=risk_tags,
                    allowed=False,
                    warning="Недостаточно данных для безопасного расчета дозы.",
                    clarifying_questions=questions,
                    disclaimers=self.DISCLAIMERS,
                )

        if risk_tags:
            return SafetyResult(
                action="answer_with_warning",
                intent=intent,
                risk_tags=risk_tags,
                allowed=True,
                warning=self._risk_warning_text(risk_tags),
                disclaimers=self.DISCLAIMERS,
            )

        return SafetyResult(
            action="allow",
            intent=intent,
            risk_tags=risk_tags,
            allowed=True,
            disclaimers=self.DISCLAIMERS,
        )

    def _classify_intent(
        self, text: str
    ) -> Literal[
        "general_education",
        "dosage_request",
        "clinical_case",
        "emergency_or_red_flag",
        "toxicology",
        "drug_interaction",
        "uncertain_source",
    ]:
        if self.EMERGENCY_PATTERN.search(text):
            return "emergency_or_red_flag"
        if self.DOSAGE_PATTERN.search(text):
            return "dosage_request"
        if self.TOX_PATTERN.search(text):
            return "toxicology"
        if self._looks_like_interaction(text):
            return "drug_interaction"
        if self.UNCERTAIN_SOURCE_PATTERN.search(text):
            return "uncertain_source"
        if self.CLINICAL_CASE_PATTERN.search(text):
            return "clinical_case"
        return "general_education"

    def _detect_risk_tags(self, text: str) -> list[str]:
        risks: list[str] = []
        has_cat = bool(self.CAT_PATTERN.search(text))
        has_dog = bool(self.DOG_PATTERN.search(text))

        if has_cat and self.NSAID_PATTERN.search(text):
            risks.append("nsaids_in_cats")
        if has_cat and self.PARACETAMOL_PATTERN.search(text):
            risks.append("paracetamol_in_cats")
        if has_dog and self.IVERMECTIN_PATTERN.search(text) and self.MDR1_PATTERN.search(text):
            risks.append("ivermectin_mdr1_risk")
        if self.NSAID_PATTERN.search(text) and self.STEROID_PATTERN.search(text):
            risks.append("steroid_plus_nsaid")
        if self.AMINOGLYCOSIDE_PATTERN.search(text) and self.ORGAN_STATUS_PATTERN.search(text):
            risks.append("aminoglycoside_kidney_risk")
        if self.ANTICOAG_PATTERN.search(text):
            risks.append("anticoagulants_risk")
        if self.ANESTH_PATTERN.search(text) and self._looks_like_interaction(text):
            risks.append("anesthesia_sedation_combination")
        return risks

    def _build_dosage_clarifying_questions(self, text: str) -> list[str]:
        questions: list[str] = []

        if not (self.CAT_PATTERN.search(text) or self.DOG_PATTERN.search(text)):
            questions.append("Уточните вид: кошка или собака?")
        if not self.WEIGHT_PATTERN.search(text):
            questions.append("Какая масса тела (кг)?")
        if self._age_relevant(text) and not self.AGE_PATTERN.search(text):
            questions.append("Уточните возраст/стадию жизни (котенок/щенок, взрослый, пожилой).")
        if not self.INDICATION_PATTERN.search(text):
            questions.append("Какое показание/диагноз для назначения?")
        if self._form_relevant(text) and not self.FORM_PATTERN.search(text):
            questions.append("Уточните форму и концентрацию препарата.")
        if not self.ROUTE_PATTERN.search(text):
            questions.append("Какой путь введения (PO/SC/IM/IV)?")
        if self._pregnancy_relevant(text) and not self.PREGNANCY_PATTERN.search(text):
            questions.append("Есть ли беременность/лактация?")
        if self._organ_status_relevant(text) and not self.ORGAN_STATUS_PATTERN.search(text):
            questions.append("Есть ли болезни почек/печени/сердца?")
        if not self.CURRENT_DRUGS_PATTERN.search(text):
            questions.append("Какие препараты животное уже получает сейчас?")
        return questions

    @staticmethod
    def _age_relevant(text: str) -> bool:
        return bool(re.search(r"\b(котен|щен|юниор|senior|пожил)\b", text, re.IGNORECASE))

    @staticmethod
    def _form_relevant(text: str) -> bool:
        return True

    @staticmethod
    def _pregnancy_relevant(text: str) -> bool:
        return bool(re.search(r"\b(самк\w*|сук\w*|кошк\w*|собак\w*)\b", text, re.IGNORECASE))

    @staticmethod
    def _organ_status_relevant(text: str) -> bool:
        return True

    def _looks_like_interaction(self, text: str) -> bool:
        return "+" in text or bool(self.INTERACTION_PATTERN.search(text))

    @staticmethod
    def _risk_warning_text(risk_tags: list[str]) -> str:
        mapping = {
            "nsaids_in_cats": "НПВС у кошек: повышенный риск, проверяйте видовую безопасность и режим.",
            "paracetamol_in_cats": "Парацетамол у кошек: высокий токсикологический риск.",
            "ivermectin_mdr1_risk": "Ивермектин у MDR1-предрасположенных пород: риск нейротоксичности.",
            "steroid_plus_nsaid": "Комбинация НПВС + стероид: высокий риск ЖКТ-осложнений.",
            "aminoglycoside_kidney_risk": "Аминогликозиды при почечном риске: нефротоксичность.",
            "anticoagulants_risk": "Антикоагулянты: высокий риск кровотечений и лекарственных взаимодействий.",
            "anesthesia_sedation_combination": "Комбинации седации/анестезии требуют очной оценки и мониторинга.",
        }
        return " ".join(mapping[tag] for tag in risk_tags if tag in mapping)
