# Telegram Rich Messages: справка

Rich Messages появились в Bot API 10.1 (11.06.2026) и расширялись в 10.2 (14.07.2026) и 10.3 (24.08.2026). Это может быть новее знаний модели, поэтому методы, теги и поля не додумываем по памяти: опираемся на эту справку, исходники установленной aiogram (`.venv/lib/python*/site-packages/aiogram/methods/send_rich_message.py`, `aiogram/types/input_rich_message.py`) и официальную документацию (ссылки в конце). Если что-то не подтверждается, останавливаемся и уточняем, а не придумываем обходной путь молча.

## Методы

- `sendRichMessage(chat_id, rich_message, reply_markup, ...)`, в aiogram `bot.send_rich_message(...)` и `message.answer_rich(...)`. Есть начиная с aiogram 3.29.
- Редактирование: `editMessageText(..., rich_message=InputRichMessage(...))`. Метода `editRichMessageText` не существует.
- В ответе приходит `Message.rich_message` (объект `RichMessage` со списком `blocks`). Это «эхо» того, как сервер распарсил разметку: по нему удобно проверять, применились ли атрибуты.
- У `sendRichMessage` есть `disable_notification`, поэтому `SilentByDefaultMiddleware` делает его беззвучным, если звук не задан явно.

## InputRichMessage

- Ровно одно из полей: `html`, `markdown`, `blocks` (`blocks` появились в 10.2).
- `skip_entity_detection=True` отключает автоопределение ссылок, упоминаний, номеров и т. п. Ставим всегда.
- Лимиты: до 32768 символов текста, до 500 блоков (каждая строка таблицы считается блоком), до 20 колонок в таблице.
- `parse_mode` к rich-сообщениям не относится.

## Теги Rich HTML

- Блоки: `<h1>`…`<h6>`, `<p>`, `<hr/>`, `<footer>`, `<table>`, `<details>`, а также списки, цитаты, `<pre>`, медиа и `<tg-button-row>` (полный список в документации).
- Инлайн: `<b>`, `<i>`, `<u>`, `<s>`, `<code>`, `<mark>`, `<sub>`, `<sup>`, `<tg-spoiler>`, `<br>`, `<a href="...">`, `<tg-time>`.
- Таблица: `<table compact striped bordered>` (булевы атрибуты; `compact` добавлен в 10.3). Строки `<tr>`, ячейки `<td>` и `<th>`, атрибуты ячеек `colspan`, `rowspan`, `align` (left, center, right), `valign` (top, middle, bottom). Подпись `<caption>`.
- Сворачиваемый блок: `<details open><summary>Заголовок</summary>...блоки...</details>`. `open` значит «раскрыт по умолчанию». Внутри `<details>` можно любое rich-содержимое.
- Время: `<tg-time unix="1790317200" format="r">в 09:20</tg-time>`. Формат задаётся по регулярке `r|w?[dD]?[tT]?`. `r` выводит время относительно текущего момента («через 8 часов») и не сочетается с другими символами. Текст внутри тега служит фолбэком. Форматы `t`, `T`, `d`, `D` показывают время в часовом поясе телефона, поэтому для времени пар их не используем: у студента в другом регионе расписание съедет.
- Экранирование: все `<`, `>`, `&` вне тегов заменяются на `&lt;`, `&gt;`, `&amp;`. Поддерживаются все числовые сущности и только именованные `&lt; &gt; &amp; &quot; &apos; &nbsp; &hellip; &mdash; &ndash; &lsquo; &rsquo; &ldquo; &rdquo;`. `html.escape(s, quote=False)` для текста и `quote=True` для атрибутов дают подходящий результат (`'` превращается в числовую `&#x27;`).
- Кнопки в теле сообщения: блок `<tg-button-row>` (от 1 до 8 кнопок в ряд, стили primary, success, danger, link) и инлайн `<tg-button type="...">`. Точный синтаксис смотри в документации перед использованием.

## Если вместо html собирать JSON-блоки

- `InputRichBlockTable`: `cells` (двумерный массив ячеек, не `rows`), `is_bordered`, `is_striped`, `is_compact`, `caption`.
- `InputRichBlockDetails`: `summary`, `blocks`, `is_open`.

## Кнопки клавиатур

- `style` (цвет) и `icon_custom_emoji_id` у `KeyboardButton` и `InlineKeyboardButton` появились в 9.4. Иконки доступны, только если бот вообще может слать кастомные эмодзи (Premium у владельца бота или купленный на Fragment username).
- `disabled` у `InlineKeyboardButton` появился в 10.3.

## Версии aiogram

3.29 = Bot API 10.1, 3.30 = 10.2, 3.31 = 10.3. Атрибуты HTML парсит сервер, поэтому `compact` работает и на 3.29, если есть `send_rich_message`. Для типизированных `is_compact` и `disabled` нужна 3.31 (в проекте `aiogram>=3.31`).

## Известные грабли

- В таблице, где меньше двух непустых строк, ссылки в ячейках превращаются в обычный текст (серверный баг, tdesktop issue #31248). В ячейки ссылки не ставим.
- По данным сторонних проектов, часть клиентов (некоторые версии Desktop, Web, Android) показывает rich-сообщения как неподдерживаемые. Поэтому нужен запасной классический вид.
- Неясно, как парсер трактует переводы строк между тегами. Собираем HTML без них (`"".join(...)`) и проверяем по эху, что пустых параграфов нет.
- В Rich Markdown `$...$` становится формулой, `==...==` выделением, `|` ломает таблицы, а экранирование части ASCII-символов (например, `\:`) показывается буквально. Для расписания используем HTML.
- Ловушка aiogram: у `edit_message_text` второй позиционный аргумент — `business_connection_id`, а не `chat_id`. Передаём `chat_id` и `message_id` только именованными.

## Что показало эхо сервера (проверено на тестовом боте)

- `<table compact striped>` приходит как `is_compact: true`, `is_striped: true`.
- У ячеек в эхе всегда есть `align` и `valign`; по умолчанию `left` и `middle`. Явные `align="right"` и `valign="top"` применяются.
- `<br>` внутри ячейки превращается в `"\n"` в тексте ячейки: многострочная ячейка работает.
- `<details>` без `open` приходит без `is_open`, с `open` — `is_open: true`.
- `<tg-time format="r">` приходит как `date_time` с `date_time_format: "r"`; текст тега сохраняется как фолбэк.
- `<mark>`, `<s>`, `<b>`, `<i>` приходят как `marked`, `strikethrough`, `bold`, `italic`; вложенность сохраняется.
- `<a href>` в абзаце внутри `<details>` приходит как `url`.

Проверка своими руками: `scripts/rich_preview.py` (нужны `TEST_BOT_TOKEN` и `TEST_CHAT_ID`, с боевым ботом не работает).

## Ссылки

- https://core.telegram.org/bots/api#sendrichmessage
- https://core.telegram.org/bots/api#inputrichmessage
- https://core.telegram.org/bots/api#rich-html-style
- https://core.telegram.org/bots/api#date-time-entity-formatting
- https://core.telegram.org/bots/api-changelog
- https://core.telegram.org/bots/features#rich-messages
- https://docs.aiogram.dev/en/latest/api/methods/send_rich_message.html
