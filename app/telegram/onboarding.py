from __future__ import annotations

from app.analytics import ProductAnalyticsService

ONBOARDING_STEPS = ("bind_topic", "today_route", "first_case")
REGION_VALUES = {"us", "eu", "local", "unspecified"}
SPECIES_VALUES = {"dog", "cat", "dog_cat"}
RESPONSE_DENSITY_VALUES = {"quick", "balanced", "deep"}


def onboarding_state(user) -> dict:
    settings = dict(user.settings or {})
    onboarding = dict(settings.get("onboarding") or {})
    completed = [x for x in onboarding.get("completed_steps", []) if x in ONBOARDING_STEPS]
    onboarding["completed_steps"] = sorted(set(completed), key=ONBOARDING_STEPS.index)
    onboarding["is_completed"] = bool(onboarding.get("is_completed", False))
    return onboarding


def save_onboarding_state(user, onboarding: dict) -> None:
    settings = dict(user.settings or {})
    settings["onboarding"] = onboarding
    user.settings = settings
    if onboarding.get("is_completed"):
        user.onboarding_completed = True


def complete_onboarding_step(*, user, step: str, analytics: ProductAnalyticsService, topic_id=None) -> bool:
    if step not in ONBOARDING_STEPS:
        return False
    onboarding = onboarding_state(user)
    completed = list(onboarding.get("completed_steps", []))
    if step in completed:
        return False
    completed.append(step)
    onboarding["completed_steps"] = sorted(set(completed), key=ONBOARDING_STEPS.index)
    onboarding["is_completed"] = len(onboarding["completed_steps"]) >= len(ONBOARDING_STEPS)
    save_onboarding_state(user, onboarding)
    analytics.track(
        user_id=user.id,
        topic_id=topic_id,
        event_name="onboarding_step_completed",
        properties={"step": step, "completed_steps": onboarding["completed_steps"]},
    )
    if onboarding["is_completed"]:
        analytics.track(user_id=user.id, topic_id=topic_id, event_name="onboarding_completed", properties={"steps": onboarding["completed_steps"]})
    return True


def user_profile(user) -> dict:
    settings = dict(user.settings or {})
    profile = dict(settings.get("profile") or {})
    region = str(profile.get("region", "unspecified")).lower()
    species_focus = str(profile.get("species_focus", "dog_cat")).lower()
    if region not in REGION_VALUES:
        region = "unspecified"
    if species_focus not in SPECIES_VALUES:
        species_focus = "dog_cat"
    density = str(profile.get("response_density", "balanced")).lower()
    if density not in RESPONSE_DENSITY_VALUES:
        density = "balanced"
    return {"region": region, "species_focus": species_focus, "response_density": density}


def apply_response_density(answer: str, density: str) -> str:
    text = (answer or "").strip()
    if density == "deep":
        return text
    limit = 900 if density == "quick" else 2200
    if len(text) <= limit:
        return text
    tail = "\n\n[Сокращено под ваш режим. Для полного разбора: /profile density=deep]"
    return f"{text[:limit].rstrip()}{tail}"
