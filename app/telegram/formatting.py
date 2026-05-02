from __future__ import annotations

import html
import re


TELEGRAM_HTML_PARSE_MODE = "HTML"


def split_for_telegram(text: str, limit: int = 3900) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks = []
    current = []
    size = 0
    for line in text.splitlines(keepends=True):
        if size + len(line) > limit and current:
            chunks.append("".join(current))
            current = [line]
            size = len(line)
        else:
            current.append(line)
            size += len(line)
    if current:
        chunks.append("".join(current))
    return chunks


SECTION_ICON_RULES: tuple[tuple[str, str], ...] = (
    (r"шаг|алгоритм|план|сейчас|действ", "✅"),
    (r"кратк|вывод|итог|главн|резюме", "🔎"),
    (r"патофизиолог|механизм|причин", "🧬"),
    (r"диагност|анализ|обслед|анамнез|осмотр", "🧪"),
    (r"диф|дифференц", "🔍"),
    (r"лечени|терапи|препарат|доз|фармаколог", "💊"),
    (r"риск|ошиб|опасн|красн|вниман|важно|токсич", "⚠️"),
    (r"симптом|признак|клиник", "📌"),
    (r"контрол|монитор|повтор", "📈"),
    (r"запомн|памят|карточ", "🧠"),
    (r"тег", "🏷"),
)

SAFE_LINK_RE = re.compile(r"^(?:https?://|tg://)[^\s\"<>]+$", re.IGNORECASE)
MARKDOWN_LINK_RE = re.compile(r"\[([^\]\n]+)\]\(([^)\s]+)\)")
INLINE_CODE_RE = re.compile(r"`([^`\n]+)`")


def format_ai_answer_for_telegram(text: str) -> str:
    """Render an AI answer as Telegram-supported HTML.

    The LLM is treated as an untrusted text source: user-visible text is escaped
    first, then a small markdown-like subset is converted to Telegram HTML tags.
    """
    normalized = (text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return "Нет ответа."

    rendered: list[str] = []
    code_lines: list[str] = []
    code_lang = ""
    in_code = False

    lines = normalized.splitlines()
    index = 0
    while index < len(lines):
        raw_line = lines[index]
        stripped = raw_line.strip()
        fence_match = re.match(r"^```([A-Za-z0-9_+-]*)\s*$", stripped)
        if fence_match:
            if in_code:
                rendered.append(_format_code_block("\n".join(code_lines), code_lang))
                code_lines = []
                code_lang = ""
                in_code = False
            else:
                in_code = True
                code_lang = fence_match.group(1).lower()
            index += 1
            continue
        if in_code:
            code_lines.append(raw_line)
            index += 1
            continue
        if _is_table_row(stripped):
            table_lines = []
            while index < len(lines) and _is_table_row(lines[index].strip()):
                table_lines.append(lines[index].strip())
                index += 1
            rendered.extend(_format_markdown_table(table_lines))
            continue
        rendered.append(_format_visual_line(raw_line))
        index += 1

    if in_code:
        rendered.append(_format_code_block("\n".join(code_lines), code_lang))

    compact = "\n".join(rendered)
    compact = re.sub(r"\n{3,}", "\n\n", compact).strip()
    return compact or "Нет ответа."


def strip_telegram_html(text: str) -> str:
    without_tags = re.sub(r"</(?:blockquote|pre|code|b|strong|i|em|u|ins|s|strike|del|tg-spoiler)>", "", text)
    without_tags = re.sub(r"<br\s*/?>", "\n", without_tags)
    without_tags = re.sub(r"<[^>]+>", "", without_tags)
    return html.unescape(without_tags).strip()


def _format_visual_line(raw_line: str) -> str:
    line = raw_line.strip()
    if not line:
        return ""

    quote = re.match(r"^>\s?(.*)$", line)
    if quote:
        return f"<blockquote>{_format_inline(quote.group(1).strip())}</blockquote>"

    heading_text = _extract_heading(line)
    if heading_text:
        return _format_heading(heading_text)

    bullet = re.match(r"^[-*•]\s+(.*)$", line)
    if bullet:
        content = bullet.group(1).strip()
        return f"• {_leading_icon(content)}{_format_inline(content)}"

    numbered = re.match(r"^(\d+)[.)]\s+(.*)$", line)
    if numbered:
        content = numbered.group(2).strip()
        return f"{numbered.group(1)}. {_leading_icon(content)}{_format_inline(content)}"

    short_label = re.match(r"^(.{2,64}?):\s+(.+)$", line)
    if short_label and _looks_like_label(short_label.group(1)):
        label = short_label.group(1).strip()
        content = short_label.group(2).strip()
        return f"{_icon_for(label)} <b>{html.escape(_strip_markdown(label))}:</b> {_format_inline(content)}"

    return _format_inline(line)


def _is_table_row(line: str) -> bool:
    if not line.startswith("|") or not line.endswith("|"):
        return False
    return line.count("|") >= 3


def _is_table_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", cell.strip()) for cell in cells)


def _parse_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _format_markdown_table(table_lines: list[str]) -> list[str]:
    rows = [_parse_table_row(line) for line in table_lines]
    rows = [row for row in rows if row and not _is_table_separator(row)]
    if not rows:
        return []

    header = rows[0] if len(rows) > 1 and _looks_like_table_header(rows[0]) else []
    data_rows = rows[1:] if header else rows
    formatted = []
    for row in data_rows:
        line = _format_table_data_row(row, header)
        if line:
            formatted.append(line)
    return formatted


def _looks_like_table_header(cells: list[str]) -> bool:
    lowered = {_strip_markdown(cell).lower() for cell in cells}
    header_words = {"#", "№", "n", "no", "номер", "блок", "содержание", "раздел", "ответ", "описание"}
    return bool(lowered & header_words)


def _format_table_data_row(row: list[str], header: list[str]) -> str:
    if len(row) >= 3 and row[0].strip().isdigit():
        number = row[0].strip()
        label = row[1].strip()
        content = " | ".join(cell for cell in row[2:] if cell.strip()).strip()
        if label and content:
            return f"{number}. {_icon_for(label)} <b>{html.escape(_strip_markdown(label))}:</b> {_format_inline(content)}"
        if label:
            return f"{number}. {_format_inline(label)}"

    if len(row) >= 2 and len(row[0]) <= 80:
        label = row[0].strip()
        content = " | ".join(cell for cell in row[1:] if cell.strip()).strip()
        if content:
            return f"• {_icon_for(label)} <b>{html.escape(_strip_markdown(label))}:</b> {_format_inline(content)}"

    if header and len(header) == len(row):
        parts = []
        for key, value in zip(header, row, strict=True):
            if value.strip():
                parts.append(f"<b>{html.escape(_strip_markdown(key))}:</b> {_format_inline(value)}")
        return "• " + " · ".join(parts) if parts else ""

    return "• " + _format_inline(" · ".join(cell for cell in row if cell.strip()))


def _extract_heading(line: str) -> str:
    markdown_heading = re.match(r"^#{1,6}\s+(.+)$", line)
    if markdown_heading:
        return markdown_heading.group(1).strip()

    bold_heading = re.match(r"^\*\*(.+?)\*\*[.!?]?$", line)
    if bold_heading and len(bold_heading.group(1).strip()) <= 140:
        return bold_heading.group(1).strip()

    if line.endswith(":") and len(line) <= 90:
        return line[:-1].strip()

    return ""


def _format_heading(text: str) -> str:
    clean = _strip_markdown(text).strip(":- ")
    icon = _icon_for(clean)
    return f"{icon} <b>{html.escape(clean)}</b>"


def _format_inline(text: str) -> str:
    placeholders: list[str] = []

    def stash(value: str) -> str:
        placeholders.append(value)
        return f"\x00TG{len(placeholders) - 1}\x00"

    def replace_code(match: re.Match[str]) -> str:
        return stash(f"<code>{html.escape(match.group(1))}</code>")

    def replace_link(match: re.Match[str]) -> str:
        label = match.group(1).strip()
        url = match.group(2).strip()
        if not SAFE_LINK_RE.match(url):
            return match.group(0)
        return stash(f'<a href="{html.escape(url, quote=True)}">{html.escape(label)}</a>')

    prepared = MARKDOWN_LINK_RE.sub(replace_link, text)
    prepared = INLINE_CODE_RE.sub(replace_code, prepared)
    prepared = html.escape(prepared)
    prepared = re.sub(r"\*\*([^*\n]{1,500}?)\*\*", r"<b>\1</b>", prepared)
    prepared = re.sub(r"__([^_\n]{1,500}?)__", r"<u>\1</u>", prepared)
    prepared = re.sub(r"~~([^~\n]{1,500}?)~~", r"<s>\1</s>", prepared)
    prepared = re.sub(r"\|\|([^|\n]{1,500}?)\|\|", r"<tg-spoiler>\1</tg-spoiler>", prepared)
    prepared = re.sub(r"(?<!\*)\*(?!\s)([^*\n]{1,240}?)(?<!\s)\*(?!\*)", r"<i>\1</i>", prepared)

    for index, value in enumerate(placeholders):
        prepared = prepared.replace(html.escape(f"\x00TG{index}\x00"), value).replace(f"\x00TG{index}\x00", value)
    return prepared


def _format_code_block(code: str, lang: str = "") -> str:
    safe_code = html.escape(code.strip("\n"))
    safe_lang = re.sub(r"[^A-Za-z0-9_+-]", "", lang or "")
    if safe_lang:
        return f'<pre><code class="language-{safe_lang}">{safe_code}</code></pre>'
    return f"<pre>{safe_code}</pre>"


def _strip_markdown(text: str) -> str:
    clean = text.strip()
    clean = re.sub(r"^\*\*(.+)\*\*$", r"\1", clean)
    clean = re.sub(r"^__(.+)__$", r"\1", clean)
    clean = clean.strip("*_`# ")
    return clean


def _looks_like_label(text: str) -> bool:
    lowered = _strip_markdown(text).lower()
    return any(re.search(pattern, lowered) for pattern, _ in SECTION_ICON_RULES) or len(lowered.split()) <= 4


def _icon_for(text: str) -> str:
    lowered = _strip_markdown(text).lower()
    for pattern, icon in SECTION_ICON_RULES:
        if re.search(pattern, lowered):
            return icon
    return "📍"


def _leading_icon(text: str) -> str:
    label_match = re.match(r"^\*\*(.{2,64}?):\*\*", text)
    if label_match:
        return f"{_icon_for(label_match.group(1))} "
    return ""
