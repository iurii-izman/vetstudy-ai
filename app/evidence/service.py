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


@dataclass
class EvidenceResponse:
    short_answer: str
    evidence_bullets: list[str]
    citations: list[str]
    status: str
    needs_manual_check: bool


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
                status="needs_manual_check",
                needs_manual_check=True,
            )

        evidence_bullets: list[str] = []
        citations: list[str] = []
        trust_levels: list[int] = []
        source_categories: list[str] = []
        for item in retrieved[:4]:
            ref = item.chunk_id or item.memory_id or "-"
            title = item.source_title or "Untitled source"
            source = self._source_for_title(sources, title)
            trust = int(source.get("trust_level", 2)) if source else 2
            category = str(source.get("category", "")) if source else ""
            trust_levels.append(trust)
            source_categories.append(category)
            evidence_bullets.append(f"{item.snippet}")
            citations.append(f"{title} [{ref}]")

        normalized = re.sub(r"\s+", " ", (llm_answer or "")).strip() or "не подтверждено источником"
        has_authoritative_dosing_source = any(
            category in AUTHORITATIVE_DOSING_CATEGORIES and trust >= 5
            for category, trust in zip(source_categories, trust_levels, strict=False)
        )
        looks_like_dosing = bool(DOSAGE_QUERY_PATTERN.search(f"{query} {llm_answer}"))
        single_source_ok = looks_like_dosing and has_authoritative_dosing_source
        needs_manual = high_risk and not single_source_ok and (len(citations) < 2 or max(trust_levels or [0]) < 4)

        status = "verified"
        if needs_manual:
            status = "needs_manual_check"
        elif len(citations) == 1 and not single_source_ok:
            status = "partially_verified"

        return EvidenceResponse(
            short_answer=normalized,
            evidence_bullets=evidence_bullets,
            citations=citations,
            status=status,
            needs_manual_check=needs_manual,
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
            "**Evidence**",
        ]
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
        return "\n".join(lines).strip()

    @staticmethod
    def _source_for_title(sources: dict[str, dict[str, Any]], title: str) -> dict[str, Any] | None:
        title_norm = (title or "").strip().lower()
        for item in sources.values():
            if (item.get("title") or "").strip().lower() == title_norm:
                return item
        return None
