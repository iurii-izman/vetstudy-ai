from types import SimpleNamespace

from app.evidence import EvidenceService


def test_high_risk_exact_label_single_source_can_be_verified(tmp_path):
    path = tmp_path / "sources.json"
    path.write_text(
        """
        {
          "sources": [
            {
              "source_id": "label",
              "title": "Exact Product SPC",
              "category": "product_label_or_spc",
              "trust_level": 5,
              "region": "Moldova/Transnistria",
              "species": "dog"
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    service = EvidenceService()
    service.settings.evidence_sources_path = str(path)

    resp = service.build_response(
        query="Рассчитай дозу для собаки 10 кг",
        llm_answer="Учебный расчет по SPC: 1 мг/кг.",
        retrieved=[SimpleNamespace(chunk_id="c1", memory_id=None, source_title="Exact Product SPC", snippet="SPC dose and route.")],
        high_risk=True,
    )

    assert resp.status == "verified"
    assert resp.needs_manual_check is False
    assert resp.trust_indicators
    assert resp.verification_status == "verified"


def test_high_risk_public_manual_single_source_needs_manual_check(tmp_path):
    path = tmp_path / "sources.json"
    path.write_text(
        """
        {
          "sources": [
            {
              "source_id": "manual",
              "title": "Public Manual",
              "category": "public_manual",
              "trust_level": 4,
              "region": "Global",
              "species": "multi"
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    service = EvidenceService()
    service.settings.evidence_sources_path = str(path)

    resp = service.build_response(
        query="Рассчитай дозу для кошки",
        llm_answer="Учебный расчет: 1 мг/кг.",
        retrieved=[SimpleNamespace(chunk_id="c1", memory_id=None, source_title="Public Manual", snippet="General background.")],
        high_risk=True,
    )

    assert resp.status == "needs_manual_check"
    assert resp.needs_manual_check is True
    assert resp.manual_check_reasons
    assert resp.next_questions


def test_preferred_sources_by_region_and_species(tmp_path):
    path = tmp_path / "sources.json"
    path.write_text(
        """
        {
          "sources": [
            {"source_id": "a", "title": "US dog source", "region": "US", "species": "dog"},
            {"source_id": "b", "title": "EU cat source", "region": "EU", "species": "cat"},
            {"source_id": "c", "title": "Global multi source", "region": "Global", "species": "multi"}
          ]
        }
        """,
        encoding="utf-8",
    )
    service = EvidenceService()
    service.settings.evidence_sources_path = str(path)
    picked = service.preferred_sources(region="us", species_focus="dog")
    assert "US dog source" in picked


def test_evidence_postprocess_dedupes_answer_and_filters_citations(tmp_path):
    path = tmp_path / "sources.json"
    path.write_text(
        """
        {
          "sources": [
            {
              "source_id": "label",
              "title": "Exact Product SPC",
              "category": "product_label_or_spc",
              "trust_level": 5,
              "region": "Moldova/Transnistria",
              "species": "dog"
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    service = EvidenceService()
    service.settings.evidence_sources_path = str(path)

    resp = service.build_response(
        query="Что делать?",
        llm_answer=(
            "**Короткий ответ**\n"
            "Учебный пример, сначала стабилизация.\n"
            "Учебный пример, сначала стабилизация.\n\n"
            "**Evidence**\n"
            "- лишний блок\n"
        ),
        retrieved=[
            SimpleNamespace(chunk_id="c1", memory_id=None, source_title="Exact Product SPC", snippet="SPC stabilization step."),
            SimpleNamespace(chunk_id="c1", memory_id=None, source_title="Exact Product SPC", snippet="SPC stabilization step."),
            SimpleNamespace(chunk_id="-", memory_id=None, source_title="Untitled source", snippet=""),
        ],
        high_risk=False,
    )

    assert resp.short_answer == "Учебный пример, сначала стабилизация."
    assert resp.evidence_bullets == ["SPC stabilization step."]
    assert resp.citations == ["Exact Product SPC [c1]"]


def test_evidence_postprocess_keeps_manual_check_when_citations_filtered(tmp_path):
    path = tmp_path / "sources.json"
    path.write_text('{"sources":[]}', encoding="utf-8")
    service = EvidenceService()
    service.settings.evidence_sources_path = str(path)

    resp = service.build_response(
        query="Рассчитай дозу для кошки",
        llm_answer="**Короткий ответ**\nУчебный расчет.",
        retrieved=[SimpleNamespace(chunk_id="-", memory_id=None, source_title="Untitled source", snippet="")],
        high_risk=True,
    )

    assert resp.citations == []
    assert resp.status == "needs_manual_check"
    assert resp.needs_manual_check is True


def test_evidence_render_includes_compact_trust_indicators(tmp_path):
    path = tmp_path / "sources.json"
    path.write_text(
        """
        {
          "sources": [
            {
              "source_id": "label",
              "title": "Exact Product SPC",
              "category": "product_label_or_spc",
              "trust_level": 5,
              "region": "Moldova/Transnistria",
              "species": "dog"
            }
          ]
        }
        """,
        encoding="utf-8",
    )
    service = EvidenceService()
    service.settings.evidence_sources_path = str(path)
    resp = service.build_response(
        query="Какой план?",
        llm_answer="Учебный шаг по источнику.",
        retrieved=[SimpleNamespace(chunk_id="c1", memory_id=None, source_title="Exact Product SPC", snippet="Protocol detail.")],
        high_risk=False,
    )
    rendered = service.render_markdown(resp)
    assert "**Trust**" in rendered
    assert "src:official | trust:high | verify:partially_verified" in rendered
