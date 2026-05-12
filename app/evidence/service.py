from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any

from app.config import get_settings


HIGH_RISK_MARKERS = (
    "доз",
    "mg/kg",
    "мг/кг",
    "токс",
    "взаимодейств",
    "седа",
    "анестез",
    "красн",
    "экстр",
)

AUTHORITATIVE_DOSING_CATEGORIES = {"product_label_or_spc", "licensed_formulary"}
DOSAGE_QUERY_PATTERN = re.compile(r"\b(доз|mg/kg|мг/кг|мг|mg|мл|ml|сколько\s+дать|рассчит)\b", re.IGNORECASE)
SHORT_ANSWER_HEADER_PATTERN = re.compile(r"^\**\s*(короткий\s+ответ|short\s+answer)\s*\**\s*:?\s*$", re.IGNORECASE)
SECTION_HEADER_PATTERN = re.compile(r"^\**\s*(evidence|citations|статус|manual\s*check)\s*\**\s*:?\s*$", re.IGNORECASE)
IRRELEVANT_CITATION_TITLE = {"", "-", "n/a", "none", "unknown", "untitled source"}
IRRELEVANT_CITATION_REF = {"", "-", "n/a", "none", "unknown"}


@dataclass
class EvidenceResponse:
    short_answer: str
    evidence_bullets: list[str]
    citations: list[str]
    trust_indicators: list[str]
    verification_status: str
    status: str
    needs_manual_check: bool
    manual_check_reasons: list[str]
    next_questions: list[str]


class EvidenceService:
    def __init__(self) -> None:
        self.settings = get_settings()
        self._sources_cache: dict[str, dict[str, Any]] = {}

    def is_high_risk(self, text: str, risk_tags: list[str] | None = None) -> bool:
        payload = (text or "").lower()
        if any(token in payload for token in HIGH_RISK_MARKERS):
            return True
        tags = {x.lower() for x in (risk_tags or [])}
        return bool(tags & {"paracetamol_in_cats", "nsaids_in_cats", "aminoglycoside_kidney_risk", "anticoagulants_risk", "anesthesia_sedation_combination"})

    def load_sources(self) -> dict[str, dict[str, Any]]:
        path = Path(self.settings.evidence_sources_path)
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        result: dict[str, dict[str, Any]] = {}
        for item in data.get("sources", []):
            source_id = str(item.get("source_id") or "").strip()
            if source_id:
                result[source_id] = item
        self._sources_cache = result
        return result

    def build_response(self, *, query: str, llm_answer: str, retrieved: list[Any], high_risk: bool) -> EvidenceResponse:
        sources = self._sources_cache or self.load_sources()
        if not retrieved:
            return EvidenceResponse(
                short_answer="не подтверждено источником",
                evidence_bullets=["Подходящий фрагмент в curated library не найден."],
                citations=[],
                trust_indicators=["src:mixed | trust:low | verify:missing"],
                verification_status="missing",
                status="needs_manual_check",
                needs_manual_check=True,
                manual_check_reasons=["Нет релевантного подтвержденного источника в curated library."],
                next_questions=[
                    "Какой точный препарат/действующее вещество?",
                    "Вид, вес, возраст и ключевые симптомы пациента?",
                ],
            )

        evidence_bullets: list[str] = []
        citations: list[str] = []
        trust_indicators: list[str] = []
        trust_levels: list[int] = []
        source_categories: list[str] = []
        source_classes: list[str] = []
        for item in retrieved[:4]:
            ref = str(item.chunk_id or item.memory_id or "").strip()
            title = str(item.source_title or "").strip() or "Untitled source"
            source = self._source_for_title(sources, title)
            trust = int(source.get("trust_level", 2)) if source else 2
            category = str(source.get("category", "")) if source else ""
            source_class = self._source_class_for_category(category)
            snippet = self._normalize_line(str(item.snippet or ""))
            citation = self._format_citation(title=title, ref=ref)
            if snippet:
                evidence_bullets.append(snippet)
            if citation:
                citations.append(citation)
                trust_levels.append(trust)
                source_categories.append(category)
                source_classes.append(source_class)
                trust_indicators.append(
                    self._format_trust_indicator(
                        source_class=source_class,
                        trust_bucket=self._trust_bucket(trust),
                        verification_status="draft",
                    )
                )

        evidence_bullets = self._dedupe_lines(evidence_bullets)
        citations = self._dedupe_lines(citations)
        normalized = self._sanitize_short_answer(llm_answer)
        has_authoritative_dosing_source = any(
            category in AUTHORITATIVE_DOSING_CATEGORIES and trust >= 5
            for category, trust in zip(source_categories, trust_levels, strict=False)
        )
        looks_like_dosing = bool(DOSAGE_QUERY_PATTERN.search(f"{query} {llm_answer}"))
        hard_dosing_manual = looks_like_dosing and not has_authoritative_dosing_source
        single_source_ok = looks_like_dosing and has_authoritative_dosing_source
        needs_manual = hard_dosing_manual or (high_risk and not single_source_ok and (len(citations) < 2 or max(trust_levels or [0]) < 4))
        partially_verified = len(citations) == 1 and not single_source_ok

        status = "verified"
        if hard_dosing_manual or needs_manual:
            status = "needs_manual_check"
        elif partially_verified:
            status = "partially_verified"
        verification_status = status
        manual_check_reasons: list[str] = []
        if hard_dosing_manual:
            manual_check_reasons.append("Для дозировки не найден authoritative source (label/SPC или licensed formulary).")
        if high_risk and len(citations) < 2 and not single_source_ok:
            manual_check_reasons.append("High-risk сценарий подтвержден слишком малым числом источников.")
        if high_risk and max(trust_levels or [0]) < 4 and not single_source_ok:
            manual_check_reasons.append("High-risk сценарий без достаточного уровня доверия к источнику.")
        if not manual_check_reasons and status == "needs_manual_check":
            manual_check_reasons.append("Требуется ручная клиническая проверка по safety-политике.")
        next_questions: list[str] = []
        if status in {"needs_manual_check", "partially_verified"}:
            next_questions = [
                "Уточните вид, вес, возраст и ключевые симптомы.",
                "Уточните точный препарат/концентрацию/маршрут и региональную доступность.",
            ]
        trust_indicators = self._finalize_trust_indicators(
            trust_indicators=trust_indicators,
            source_classes=source_classes,
            trust_levels=trust_levels,
            verification_status=verification_status,
        )

        return EvidenceResponse(
            short_answer=normalized,
            evidence_bullets=evidence_bullets,
            citations=citations,
            trust_indicators=trust_indicators,
            verification_status=verification_status,
            status=status,
            needs_manual_check=needs_manual,
            manual_check_reasons=manual_check_reasons,
            next_questions=next_questions,
        )

    def preferred_sources(self, *, region: str, species_focus: str) -> list[str]:
        sources = self._sources_cache or self.load_sources()
        region = (region or "unspecified").lower()
        species_focus = (species_focus or "dog_cat").lower()
        out: list[str] = []
        for row in sources.values():
            row_region = str(row.get("region", "")).lower()
            row_species = str(row.get("species", "")).lower()
            region_match = region in {"unspecified", "local"} or region in row_region
            species_match = (
                species_focus == "dog_cat"
                or species_focus in row_species
                or row_species in {"multi", "dog_cat"}
            )
            if region_match and species_match:
                title = str(row.get("title", "")).strip()
                if title:
                    out.append(title)
            if len(out) >= 5:
                break
        return out

    @staticmethod
    def render_markdown(resp: EvidenceResponse) -> str:
        lines = [
            "**Короткий ответ**",
            resp.short_answer,
            "",
            "**Trust**",
        ]
        for indicator in resp.trust_indicators:
            lines.append(f"- {indicator}")
        lines.extend([
            "",
            "**Evidence**",
        ])
        for row in resp.evidence_bullets:
            lines.append(f"- {row}")
        lines.append("")
        lines.append("**Citations**")
        if resp.citations:
            for c in resp.citations:
                lines.append(f"- {c}")
        else:
            lines.append("- не подтверждено источником")
        lines.append("")
        lines.append(f"**Статус:** `{resp.status}`")
        if resp.needs_manual_check:
            lines.append("**Manual check:** требуется ручная проверка")
        if resp.manual_check_reasons:
            lines.append("**Почему manual check**")
            for reason in resp.manual_check_reasons:
                lines.append(f"- {reason}")
        return "\n".join(lines).strip()

    @staticmethod
    def _source_for_title(sources: dict[str, dict[str, Any]], title: str) -> dict[str, Any] | None:
        title_norm = (title or "").strip().lower()
        for item in sources.values():
            if (item.get("title") or "").strip().lower() == title_norm:
                return item
        return None

    @staticmethod
    def _normalize_line(text: str) -> str:
        return re.sub(r"\s+", " ", (text or "").strip())

    def _sanitize_short_answer(self, raw_answer: str) -> str:
        lines = (raw_answer or "").splitlines()
        chunks: list[str] = []
        for raw_line in lines:
            line = self._normalize_line(raw_line)
            if not line:
                continue
            if SHORT_ANSWER_HEADER_PATTERN.match(line):
                continue
            if SECTION_HEADER_PATTERN.match(line):
                break
            chunks.append(line)
        if not chunks:
            return "не подтверждено источником"
        return " ".join(self._dedupe_lines(chunks)) or "не подтверждено источником"

    @classmethod
    def _format_citation(cls, *, title: str, ref: str) -> str | None:
        title_norm = cls._normalize_line(title).lower()
        ref_norm = cls._normalize_line(ref).lower()
        if title_norm in IRRELEVANT_CITATION_TITLE and ref_norm in IRRELEVANT_CITATION_REF:
            return None
        if title_norm in IRRELEVANT_CITATION_TITLE and ref_norm in {"", "-"}:
            return None
        if not title_norm and not ref_norm:
            return None
        formatted_title = cls._normalize_line(title) or "Untitled source"
        formatted_ref = cls._normalize_line(ref) or "-"
        if formatted_title.lower() == "untitled source" and formatted_ref == "-":
            return None
        return f"{formatted_title} [{formatted_ref}]"

    @classmethod
    def _dedupe_lines(cls, values: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for item in values:
            normalized = cls._normalize_line(item)
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(normalized)
        return out

    @staticmethod
    def _source_class_for_category(category: str) -> str:
        category_norm = (category or "").strip().lower()
        if category_norm in {"product_label_or_spc", "regulator"}:
            return "official"
        if category_norm == "licensed_formulary":
            return "licensed"
        if category_norm in {"public_guideline", "public_manual"}:
            return "public"
        return "mixed"

    @staticmethod
    def _trust_bucket(trust_level: int) -> str:
        if trust_level >= 5:
            return "high"
        if trust_level >= 3:
            return "medium"
        return "low"

    @classmethod
    def _format_trust_indicator(cls, *, source_class: str, trust_bucket: str, verification_status: str) -> str:
        return f"src:{source_class} | trust:{trust_bucket} | verify:{verification_status}"

    @classmethod
    def _finalize_trust_indicators(
        cls,
        *,
        trust_indicators: list[str],
        source_classes: list[str],
        trust_levels: list[int],
        verification_status: str,
    ) -> list[str]:
        if not trust_indicators:
            return [cls._format_trust_indicator(source_class="mixed", trust_bucket="low", verification_status=verification_status)]
        top_level = max(trust_levels or [0])
        top_class = source_classes[0] if source_classes else "mixed"
        compact = cls._format_trust_indicator(
            source_class=top_class,
            trust_bucket=cls._trust_bucket(top_level),
            verification_status=verification_status,
        )
        return [compact]
