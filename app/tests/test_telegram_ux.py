from app.telegram.ux import next_step_keyboard, provider_error_text, quota_error_text, safety_error_text


def test_error_texts_follow_action_alternative_goal_pattern():
    for text in (provider_error_text(), quota_error_text(), safety_error_text()):
        assert "Действие:" in text
        assert "Альтернатива:" in text
        assert "Цель:" in text


def test_first_value_keyboard_has_three_quick_actions():
    keyboard = next_step_keyboard("first_value")
    assert len(keyboard.inline_keyboard) == 3
    labels = [row[0].text for row in keyboard.inline_keyboard]
    assert "Start 10-min route" in labels[0]
