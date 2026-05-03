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
