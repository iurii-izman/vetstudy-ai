import json
import logging

from app.observability import JsonFormatter


def test_json_formatter_keeps_route_decision_and_reason_fields():
    logger = logging.getLogger("tests.observability")
    record = logger.makeRecord(
        logger.name,
        logging.INFO,
        __file__,
        10,
        "route_decision",
        args=(),
        exc_info=None,
        extra={
            "event": "route_decision",
            "route_decision": "low_risk",
            "reason": "intent=general_education",
            "provider": "gemini",
            "model": "gemini-2.5-flash-lite",
        },
    )

    payload = json.loads(JsonFormatter().format(record))
    assert payload["event"] == "route_decision"
    assert payload["route_decision"] == "low_risk"
    assert payload["reason"] == "intent=general_education"
