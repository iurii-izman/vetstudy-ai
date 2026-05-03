from app.telegram.formatting import format_ai_answer_for_telegram, split_for_telegram, strip_telegram_html


def test_split_for_telegram():
    text = ("abc\n" * 3000).strip()
    chunks = split_for_telegram(text, limit=500)
    assert len(chunks) > 1
    assert all(len(c) <= 500 for c in chunks)


def test_format_ai_answer_converts_markdown_to_telegram_html():
    text = """**Шаг 1: Краткий осмотр и анамнез**

- **Патофизиология:** стресс повышает кортизол.
- **Диагностика:** ОАК, ОАМ и осмотр.

Теги: #стресс #диагностика"""

    rendered = format_ai_answer_for_telegram(text)

    assert "✅ <b>Шаг 1: Краткий осмотр и анамнез</b>" in rendered
    assert "• 🧬 <b>Патофизиология:</b> стресс повышает кортизол." in rendered
    assert "• 🧪 <b>Диагностика:</b> ОАК, ОАМ и осмотр." in rendered
    assert "🏷 <b>Теги:</b> #стресс #диагностика" in rendered
    assert "**" not in rendered


def test_format_ai_answer_escapes_unsafe_html_but_keeps_supported_markup():
    rendered = format_ai_answer_for_telegram("Важно: <script>x</script> и `CRP`")

    assert "&lt;script&gt;x&lt;/script&gt;" in rendered
    assert "<code>CRP</code>" in rendered


def test_strip_telegram_html_for_fallback():
    text = strip_telegram_html("🧪 <b>Диагностика:</b> <code>ОАК</code>")

    assert text == "🧪 Диагностика: ОАК"


def test_format_ai_answer_converts_markdown_table_to_readable_blocks():
    text = """**Спецшаблон фармакологии - новокаин у лошадей**

| № | Блок | Содержание |
|---|------|------------|
| 1 | Краткий вывод | Нет данных о применении новокаина у лошадей |
| 2 | Механизм | Неизвестен |
| 3 | Дозировки | **Отсутствуют** |

**Красный флаг: необходима консультация специалиста**."""

    rendered = format_ai_answer_for_telegram(text)

    assert "💊 <b>Спецшаблон фармакологии - новокаин у лошадей</b>" in rendered
    assert "1. 🔎 <b>Краткий вывод:</b> Нет данных о применении новокаина у лошадей" in rendered
    assert "2. 🧬 <b>Механизм:</b> Неизвестен" in rendered
    assert "3. 💊 <b>Дозировки:</b> <b>Отсутствуют</b>" in rendered
    assert "⚠️ <b>Красный флаг: необходима консультация специалиста</b>" in rendered
    assert "| № |" not in rendered
    assert "**" not in rendered


def test_format_ai_answer_keeps_evidence_citations_readable():
    text = """**Citations**\n- EMA Meloxicam Product Information [chunk-1]\n- WSAVA Emergency Red Flags [mem-2]\n\n**Статус:** `needs_manual_check`"""
    rendered = format_ai_answer_for_telegram(text)
    assert "EMA Meloxicam Product Information [chunk-1]" in rendered
    assert "WSAVA Emergency Red Flags [mem-2]" in rendered
    assert "<code>needs_manual_check</code>" in rendered
