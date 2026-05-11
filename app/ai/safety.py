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
        r"\b(доз\w*|дозиров\w*|мг/кг|mg/kg|сколько\b.{0,50}\bдать|рассчита\w*\b.{0,50}\bдоз\w*)\b",
        re.IGNORECASE,
    )
    CLINICAL_CASE_PATTERN = re.compile(
        r"\b(симптом\w*|анамнез\w*|кейс\w*|случа\w*|диагноз\w*|лечени\w*|рвот\w*|вялост\w*|болезнен\w*|одышк\w*|диаре\w*|желтуш\w*|протокол\w*|пиометр\w*|гнойн\w*\s+ран\w*)\b",
        re.IGNORECASE,
    )
    EMERGENCY_PATTERN = re.compile(
        r"\b(не\s+дыш\w*|судорог\w*|коллапс\w*|без\s+сознания|остановк[аи]\s+дыхания|сильн\w+\s+кровотеч\w*|анафилакс\w*|сроч\w*|реанимац\w*)\b",
        re.IGNORECASE,
    )
    TOX_PATTERN = re.compile(r"\b(отрав\w*|токс\w*|яд\w*|парацетамол\w*|acetaminophen)\b", re.IGNORECASE)
    TOX_INGESTION_PATTERN = re.compile(
        r"\b(шоколад\w*|изюм\w*|ксилит\w*|лук\w*|чеснок\w*|перметрин\w*|съел\w*|съела|слизал\w*|проглот\w*)\b",
        re.IGNORECASE,
    )
    INTERACTION_PATTERN = re.compile(
        r"\b(\+|вместе|комбинац\w*|взаимодейств\w*|совместим\w*|сочета\w*|одновременно)\b",
        re.IGNORECASE,
    )
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

    NSAID_PATTERN = re.compile(r"\b(нпвс|nsaid|мелоксикам\w*|карпрофен\w*|кетопрофен\w*)\b", re.IGNORECASE)
    PARACETAMOL_PATTERN = re.compile(r"\b(парацетамол\w*|acetaminophen)\b", re.IGNORECASE)
    IVERMECTIN_PATTERN = re.compile(r"\b(ивермектин|ivermectin)\b", re.IGNORECASE)
    MDR1_PATTERN = re.compile(r"\b(mdr1|колли|шелти|австралийск\w+\s+овчарк\w*)\b", re.IGNORECASE)
    STEROID_PATTERN = re.compile(r"\b(преднизолон|дексаметазон|стероид)\b", re.IGNORECASE)
    AMINOGLYCOSIDE_PATTERN = re.compile(r"\b(гентамицин\w*|амикацин\w*|неомицин\w*|аминогликозид\w*)\b", re.IGNORECASE)
    ANTICOAG_PATTERN = re.compile(r"\b(антикоагулянт|варфарин|гепарин|клопидогрел)\b", re.IGNORECASE)
    ANESTH_PATTERN = re.compile(r"\b(анестези\w*|седац\w*|пропофол|кетамин|медетомидин|дексмедетомидин)\b", re.IGNORECASE)

    DISCLAIMERS = [
        "Проверьте по актуальной инструкции/формуляру.",
        "AI может ошибаться — верифицируйте клинические решения.",
    ]

    def check(self, text: str) -> SafetyResult:
        normalized = self._normalize_text(text)
        intent = self._classify_intent(normalized)
        risk_tags = self._detect_risk_tags(normalized)
        if intent == "clinical_case" and "clinical_case" not in risk_tags:
            risk_tags.append("clinical_case")
        if intent == "drug_interaction" and "drug_interaction" not in risk_tags:
            risk_tags.append("drug_interaction")

        if intent == "emergency_or_red_flag":
            return SafetyResult(
                action="answer_with_warning",
                intent=intent,
                risk_tags=risk_tags,
                allowed=True,
                warning="⚠️ Красные флаги — экстренная ситуация. Дай полный алгоритм неотложных действий.",
                disclaimers=self.DISCLAIMERS,
            )
        if intent == "toxicology":
            return SafetyResult(
                action="answer_with_warning",
                intent=intent,
                risk_tags=risk_tags,
                allowed=True,
                warning="⚠️ Токсикологический случай. Дай полный протокол: оценка дозы токсина, симптомы, антидот/деконтаминация, мониторинг.",
                clarifying_questions=self._build_toxicology_clarifying_questions(normalized),
                disclaimers=self.DISCLAIMERS,
            )

        if intent == "dosage_request":
            questions = self._build_dosage_clarifying_questions(text)
            if questions:
                return SafetyResult(
                    action="ask_clarifying_questions",
                    intent=intent,
                    risk_tags=risk_tags,
                    allowed=True,
                    warning="Уточняющие данные для точного расчёта дозы (ответ будет дан на основе имеющегося):",
                    clarifying_questions=questions,
                    disclaimers=self.DISCLAIMERS,
                )
        if intent == "clinical_case":
            return SafetyResult(
                action="answer_with_warning",
                intent=intent,
                risk_tags=risk_tags,
                allowed=True,
                warning="Клинический случай. Дай наиболее вероятный диагноз, дифференциалы и конкретный план лечения.",
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

    @staticmethod
    def _normalize_text(text: str) -> str:
        normalized = text.lower().replace("ё", "е")
        normalized = re.sub(r"[/\\|]+", " ", normalized)
        normalized = re.sub(r"[^\w\s+]", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

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
        if self.TOX_PATTERN.search(text) or self.TOX_INGESTION_PATTERN.search(text):
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
        if self.TOX_INGESTION_PATTERN.search(text):
            risks.append("toxic_exposure_common")
            risks.append("emergency")
        if self.UNCERTAIN_SOURCE_PATTERN.search(text):
            risks.append("source_uncertainty")
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
            questions.append("Нужно уточнение формы и концентрации.")
            questions.append("Уточните концентрацию препарата.")
        if not self.ROUTE_PATTERN.search(text):
            questions.append("Какой путь введения (PO/SC/IM/IV)?")
        if self._pregnancy_relevant(text) and not self.PREGNANCY_PATTERN.search(text):
            questions.append("Есть ли беременность/лактация?")
        if self._organ_status_relevant(text) and not self.ORGAN_STATUS_PATTERN.search(text):
            questions.append("Есть ли болезни почек/печени/сердца?")
        if not self.CURRENT_DRUGS_PATTERN.search(text):
            questions.append("Какие препараты животное уже получает сейчас?")
            questions.append("Уточните текущие препараты.")
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

    def _build_toxicology_clarifying_questions(self, text: str) -> list[str]:
        questions = [
            "Что именно было съедено/контакт (вещество, продукт, концентрация)?",
            "Когда это произошло и какой примерно объем/количество?",
            "Нужна оценка дозы токсина: сколько вещества могло попасть животному?",
            "Какие симптомы уже есть сейчас (рвота, судороги, вялость, одышка)?",
            "Вид и масса животного?",
        ]
        if not self.CURRENT_DRUGS_PATTERN.search(text):
            questions.append("Какие препараты животное получает сейчас?")
        return questions

    @staticmethod
    def _risk_warning_text(risk_tags: list[str]) -> str:
        mapping = {
            "nsaids_in_cats": "НПВС у кошек: риск ЖКТ осложнений и видовой токсичности, нужна проверка по инструкции.",
            "paracetamol_in_cats": "Парацетамол у кошек: высокий токсикологический риск.",
            "ivermectin_mdr1_risk": "Ивермектин у MDR1-предрасположенных пород: риск нейротоксичности.",
            "steroid_plus_nsaid": "Комбинация НПВС + стероид: риск ЖКТ осложнений, требуется проверка по инструкции.",
            "aminoglycoside_kidney_risk": "Аминогликозиды при почечном риске: нефротоксичность.",
            "anticoagulants_risk": "Антикоагулянты: высокий риск кровотечений и лекарственных взаимодействий.",
            "anesthesia_sedation_combination": "Комбинации седации/анестезии требуют очной оценки и мониторинга.",
            "toxic_exposure_common": "Потенциальная токсическая экспозиция: нужна срочная очная оценка риска.",
            "source_uncertainty": "Источник ненадежен: требует проверки по инструкции/формуляру.",
            "emergency": "Есть признаки неотложности: срочно в клинику.",
        }
        return " ".join(mapping[tag] for tag in risk_tags if tag in mapping)
