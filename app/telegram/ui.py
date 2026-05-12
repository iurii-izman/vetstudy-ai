from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup

from app.telegram.callbacks import callback_data


def build_ai_reply_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text="💾 Сохранить", callback_data=callback_data("save"))],
        [InlineKeyboardButton(text="⚡ Кратко", callback_data=callback_data("short")), InlineKeyboardButton(text="🔎 Глубже", callback_data=callback_data("deeper"))],
        [InlineKeyboardButton(text="🧠 Карточки", callback_data=callback_data("cards")), InlineKeyboardButton(text="🧪 Тест", callback_data=callback_data("test"))],
        [InlineKeyboardButton(text="🧭 Связанные темы", callback_data=callback_data("related"))],
        [InlineKeyboardButton(text="👍", callback_data=callback_data("fb_up")), InlineKeyboardButton(text="👎", callback_data=callback_data("fb_down")), InlineKeyboardButton(text="ошибка", callback_data=callback_data("fb_error"))],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_review_keyboard(card_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="😵 Again", callback_data=callback_data("review_again", card_id)),
                InlineKeyboardButton(text="😬 Hard", callback_data=callback_data("review_hard", card_id)),
            ],
            [InlineKeyboardButton(text="🙂 Good", callback_data=callback_data("review_good", card_id)), InlineKeyboardButton(text="😎 Easy", callback_data=callback_data("review_easy", card_id))],
            [InlineKeyboardButton(text="👁 Показать ответ", callback_data=callback_data("review_reveal", card_id))],
        ]
    )


def build_main_menu_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📅 На сегодня"), KeyboardButton(text="🩺 Кейсы")],
            [KeyboardButton(text="🧠 Карточки"), KeyboardButton(text="➕ Создать")],
            [KeyboardButton(text="📚 Темы"), KeyboardButton(text="⚙️ Профиль")],
        ],
        resize_keyboard=True,
        persistent=True,
    )
