/**
 * Help / Info page locale keys (merged into BB_LOCALES on load).
 */
(function (global) {
  "use strict";

  var INFO_LOCALES = {
    en: {
      "info.nav_aria": "Contents",
      "info.nav_title": "Contents",
      "info.nav.about": "About",
      "info.nav.modules": "Menu sections",
      "info.nav.quickstart": "Quick start",
      "info.nav.monitor": "Monitoring",
      "info.nav.channel_manager": "Channel Manager",
      "info.nav.post_editor": "Channel Post Editor",
      "info.nav.bots": "Chat Bots",
      "info.nav.scenario": "Scenario editor",
      "info.nav.plugins": "Plugins & blocks",
      "info.nav.templates": "Templates",
      "info.nav.mailing": "Bots Post Editor",
      "info.nav.analytics": "Bot Analytics & data",
      "info.nav.deploy": "Deploy",
      "info.nav.tips": "Tips",

      "info.hero.desc":
        "A desktop app for building Telegram and VK bots without manual project setup: visual scenarios, custom blocks (plugins), Channel Manager, Post Editor, templates, Bot Analytics, broadcasts, and server deployment.",

      "info.modules.title": "Main menu sections",
      "info.modules.intro": "Each section is a separate module. Order matches the home screen. Briefly, what it does:",
      "info.modules.monitor.title_html": '<a href="/monitor/">Monitoring</a>',
      "info.modules.monitor.desc": "CPU/RAM, bot processes, streaming API and LLM logs.",
      "info.modules.channel_manager.title_html": '<a href="/channel-hub/">Channel Manager</a>',
      "info.modules.channel_manager.desc": "Connect channels and moderator bots, stats, feed, comment moderation.",
      "info.modules.post_editor.title_html": '<a href="/post-studio/">Channel Post Editor</a>',
      "info.modules.post_editor.desc": "Compose, schedule and publish posts to Telegram channels.",
      "info.modules.bots.title_html": '<a href="/bots/">Chat Bots</a>',
      "info.modules.bots.desc": "Bot list, tokens, start/stop, open the scenario builder.",
      "info.modules.scenario.title_html": '<a href="/editor/scenario/">Scenario editor</a>',
      "info.modules.scenario.desc": "Canvas with blocks and connections — dialog logic, menus, conditions, messages.",
      "info.modules.templates.title_html": '<a href="/templates/">Template library</a>',
      "info.modules.templates.desc": "Ready scenarios, import/export <code>.bbpack.json</code>, install on a bot.",
      "info.modules.mailing.title_html": '<a href="/mailing/">Bots Post Editor</a>',
      "info.modules.mailing.desc": "HTML messages with media, filter subscribers by roles and tags.",
      "info.modules.analytics.title_html": '<a href="/analytics/">Bot Analytics</a>',
      "info.modules.analytics.desc": "Activity charts, event calendar, overview for the selected chat bot.",
      "info.modules.builder.title_html": '<a href="/plugin-builder/">Component wizard</a>',
      "info.modules.builder.desc": "Create and edit custom blocks: property fields, color, Python template.",
      "info.modules.plugins.title_html": '<a href="/plugins/">Plugins</a>',
      "info.modules.plugins.desc": "Block catalog: built-in (view only) and custom (editable).",
      "info.modules.database.title_html": '<a href="/database/">Database</a>',
      "info.modules.database.desc": "View and edit <code>user_data.db</code>, import .db / .json.",
      "info.modules.deploy.title_html": '<a href="/deployment/">Deploy</a>',
      "info.modules.deploy.desc": "Docker archive for local runs or upload to VPS via SSH.",

      "info.quickstart.title": "Quick start",
      "info.quickstart.step1_html":
        '<strong>Create a bot in the messenger.</strong> Telegram: <a href="https://t.me/BotFather" target="_blank" rel="noopener">@BotFather</a> → command <code>/newbot</code> → copy the API token. VK: create a community and get the group access key with messaging permissions.',
      "info.quickstart.step2_html":
        'Open <a href="/bots/">Chat Bots</a> → add a bot: name, platform (Telegram or VK), paste the token. For channels: create a <strong>moderator bot</strong> in <a href="/channel-hub/">Channel Manager</a> and add it as a channel admin.',
      "info.quickstart.step3_html":
        'Chat flow: open <strong>Scenario builder</strong> on the bot card and build a chain (start → messages / menu → conditions). Channel posts: open <a href="/post-studio/">Channel Post Editor</a>, pick a connected channel and compose the post.',
      "info.quickstart.step4_html":
        "Save the scenario (save button in the editor) or publish/schedule the post. If needed, return to the bot list and <strong>start</strong> the chat bot; keep the moderator bot running for channels.",
      "info.quickstart.step5_html":
        'Test the dialog in Telegram or VK, or check the channel. Use logs in <a href="/monitor/">Monitoring</a> if something does not respond.',
      "info.quickstart.tip_html":
        "<strong>Tip.</strong> For VK you can apply a default scenario (greeting and menu) directly from the bot card — a handy starting point. Channel stats and comments live in Channel Manager, not in Bot Analytics.",

      "info.bots.title": "Chat Bots",
      "info.bots.intro_html":
        'The <a href="/bots/">Chat Bots</a> section is the hub for dialog projects. Each chat bot stores its scenario, files, and user database in the project folder. <strong>Moderator bots</strong> (for channels only, no scenario) are created and managed in <a href="/channel-hub/">Channel Manager</a>.',
      "info.bots.actions_title": "What you can do",
      "info.bots.action1": "Add and remove chat bots (Telegram / VK).",
      "info.bots.action2": "Start and stop the bot process.",
      "info.bots.action3": "Open the visual scenario builder (chat bots only).",
      "info.bots.action4": "For VK — verify the token and apply a template scenario.",
      "info.bots.note_html":
        "<strong>Important.</strong> After changing the scenario you usually need to <em>restart</em> the bot to load the new code. A moderator bot must be a channel administrator to publish posts and moderate comments.",

      "info.channel_manager.title": "Channel Manager",
      "info.channel_manager.intro_html":
        '<a href="/channel-hub/">Channel Manager</a> connects Telegram channels to BotBuilder: moderator bots, KPIs, post feed, charts and comment moderation.',
      "info.channel_manager.how_title": "How to connect a channel",
      "info.channel_manager.how1": "Create or select a moderator bot (token from @BotFather). This type has no scenario — it only serves channels.",
      "info.channel_manager.how2": "Add the bot as an administrator of your Telegram channel (at least posting rights).",
      "info.channel_manager.how3_html":
        "In Channel Manager, add the channel (public <code>@username</code> or invite link) and bind it to the moderator bot.",
      "info.channel_manager.how4": "Open the channel card: overview, charts, recent posts and actions (edit / delete / comments).",
      "info.channel_manager.features_title": "What you get",
      "info.channel_manager.feat1": "List of connected channels and quick switch between them.",
      "info.channel_manager.feat2": "Views, reactions and engagement charts; PDF export when needed.",
      "info.channel_manager.feat3": "Post feed with refresh; open Channel Post Editor to create or update a post.",
      "info.channel_manager.feat4": "Comment moderation where discussion is enabled.",
      "info.channel_manager.note":
        "Channel Manager talks to Telegram through the moderator bot. Keep that bot running while you publish or moderate.",

      "info.post_editor.title": "Channel Post Editor",
      "info.post_editor.intro_html":
        '<a href="/post-studio/">Post Editor</a> builds channel posts: visual layout or HTML, media, inline buttons, schedule and publish.',
      "info.post_editor.how_title": "How to publish a post",
      "info.post_editor.how1": "Select the target channel (it must already be connected in Channel Manager).",
      "info.post_editor.how2": "Compose the post: add rows (text, media, buttons), or switch to HTML mode.",
      "info.post_editor.how3": "Save a draft, publish now, or pick a date/time to schedule.",
      "info.post_editor.how4": "Use Update when editing an already published post; New Post clears the form after a successful publish.",
      "info.post_editor.features_title": "Editor features",
      "info.post_editor.feat1": "Formatting toolbar (bold, italic, links, lists) in the visual editor.",
      "info.post_editor.feat2": "Media files and inline keyboard buttons under the post.",
      "info.post_editor.feat3": "History of drafts and published posts for the selected channel.",
      "info.post_editor.feat4": "After publish or schedule, start a new post in one click.",
      "info.post_editor.note":
        "Publishing needs a live moderator bot with rights in the channel. If publish fails, check Channel Manager and Monitoring logs.",

      "info.scenario.title": "Scenario editor",
      "info.scenario.intro_html":
        'Opens from the chat bot card or via menu «View → New window». A scenario is a graph: <strong>nodes (blocks)</strong> and <strong>connections</strong> between them. Moderator bots do not use this editor.',
      "info.scenario.how_title": "How to build logic",
      "info.scenario.how1": "Drag a block from the palette onto the canvas (start, message, menu, condition, etc.).",
      "info.scenario.how2": "Click a block to open properties on the right: text, buttons, variables.",
      "info.scenario.how3": "Connect one block's output to another's input to set the step order.",
      "info.scenario.how4": "Save the scenario. Version history lets you roll back changes (Time Machine).",
      "info.scenario.blocks_title": "Common blocks",
      "info.scenario.block_start_html": "<strong>Start</strong> — entry point (often the <code>/start</code> command).",
      "info.scenario.block_message_html": "<strong>Message</strong> — text to the user, optional media.",
      "info.scenario.block_menu_html": "<strong>Menu</strong> — buttons and transitions by choice.",
      "info.scenario.block_condition_html": "<strong>Condition</strong> — branch by user data or reply.",
      "info.scenario.block_data_html": "<strong>Command / data</strong> — command handlers and field operations.",
      "info.scenario.block_custom": "<strong>Custom plugins</strong> — any blocks you published in the wizard.",

      "info.plugins.title": "Plugins & blocks",
      "info.plugins.intro":
        "A plugin is a reusable scenario block: UI fields + Python handler template. Built-in plugins cannot be edited; your own can be changed and deleted.",
      "info.plugins.manage_title": "View and manage",
      "info.plugins.manage_html":
        'Open <a href="/plugins/">Plugins</a>: list of all blocks. For custom — «Edit», for built-in — view only.',
      "info.plugins.create_title": "Creating a custom block",
      "info.plugins.create1_html":
        '<a href="/plugin-builder/">Component wizard</a> → set <strong>ID</strong> (Latin letters, digits, <code>_</code> or <code>-</code>), name, canvas color.',
      "info.plugins.create2": "Add property fields (text, number, toggle, etc.) — they appear in the editor panel.",
      "info.plugins.create3_html":
        "Write or edit the Python handler template (Jinja2). It is compiled into the bot code when you save the scenario.",
      "info.plugins.create4": "Publish the component — the block appears in the scenario editor palette immediately.",
      "info.plugins.import_title": "Import and sharing",
      "info.plugins.import1_html":
        'Ready scenarios with plugins often ship in a <code>.bbpack.json</code> package via the <a href="/templates/">Template library</a>.',
      "info.plugins.import2":
        "If a template install is missing plugins, the app will warn you — install the missing ones or import the full package.",
      "info.plugins.import3":
        "Custom plugins live in the app user data plugins folder (see «Help → Data folder»).",
      "info.plugins.error405_html":
        "<strong>If plugin save fails (405).</strong> Fully close BotBuilder and start again — an old backend process may still be on the port.",

      "info.templates.title": "Template library",
      "info.templates.intro_html":
        'In <a href="/templates/">Templates</a> — local and marketplace scenario packages. Exchange format: <code>.bbpack.json</code>.',
      "info.templates.item1_html": "<strong>Preview</strong> — view the graph before installing.",
      "info.templates.item2_html": "<strong>Install on bot</strong> — apply the scenario to a selected project.",
      "info.templates.item3_html": "<strong>Import / export</strong> — share files between machines or team members.",
      "info.templates.item4_html": "<strong>Edit template</strong> — opens the same scenario editor in template mode.",

      "info.analytics.title": "Bot Analytics & database",
      "info.analytics.section_title": "Bot Analytics",
      "info.analytics.desc_html":
        '<a href="/analytics/">Bot Analytics</a> shows activity for the selected chat bot: «today / 7 / 30 days», charts and calendar. Visualization only — data comes from bot activity and user storage. Channel post stats live in <a href="/channel-hub/">Channel Manager</a>.',
      "info.database.section_title": "Database",
      "info.database.desc_html":
        '<a href="/database/">Database</a> opens the project <code>user_data.db</code>: tables, fields, import from another <code>.db</code> or JSON. Handy for editing roles, tags and test records manually.',

      "info.mailing.title": "Bots Post Editor",
      "info.mailing.desc_html":
        'In <a href="/mailing/">Bots Post Editor</a> you can send an HTML message with media to bot subscribers. Filter the audience by roles and tags from the user database, preview and run the broadcast.',
      "info.mailing.note":
        "The bot must be available (valid token). For large lists, watch messenger limits and logs in monitoring.",

      "info.monitor.title": "Monitoring",
      "info.monitor.desc_html":
        '<a href="/monitor/">Monitoring</a> shows load (CPU/RAM), bot processes (including moderator bots) and streaming logs. Stop a stuck process and quickly find API or LLM errors.',

      "info.deploy.title": "Deploy",
      "info.deploy.intro_html": '<a href="/deployment/">Deploy</a> prepares the bot to run outside your PC:',
      "info.deploy.item1_html": "<strong>Docker archive</strong> — download a package for local or server Docker.",
      "info.deploy.item2_html": "<strong>VPS via SSH</strong> — set host, user and path, upload and start the service.",
      "info.deploy.outro":
        "Before deploy, ensure the scenario is saved, the token is current, and the server has Docker (for docker option) or required dependencies.",

      "info.tips.title": "Useful tips",
      "info.tips.item1_html":
        "Menu <strong>Help → Application data folder</strong> opens the directory with bot projects, custom plugins and settings.",
      "info.tips.item2_html":
        'Theme: <strong>View → Light / Dark</strong> or <span class="info-kbd">Ctrl</span>+<span class="info-kbd">Shift</span>+<span class="info-kbd">L</span>.',
      "info.tips.item3_html":
        "Multiple windows: <strong>View → New window</strong> — handy to keep the editor, Channel Manager and monitoring side by side.",
      "info.tips.item4":
        "If a page is blank or the API does not respond — restart the app and check «Settings» (API port in the menu).",
      "info.tips.item5":
        "After updating BotBuilder, rebuild/restart bots (including moderator bots in Channel Manager) to pick up the new runtime and plugins.",
      "info.tips.footer_html":
        'Open this help anytime: menu <strong>Help → Info</strong> or hotkey <span class="info-kbd">F1</span>.',
    },
    ru: {
      "info.nav_aria": "Содержание",
      "info.nav_title": "Содержание",
      "info.nav.about": "О программе",
      "info.nav.modules": "Разделы меню",
      "info.nav.quickstart": "Быстрый старт",
      "info.nav.monitor": "Мониторинг",
      "info.nav.channel_manager": "Менеджер Каналов",
      "info.nav.post_editor": "Редактор Постов Канала",
      "info.nav.bots": "Чат-Боты",
      "info.nav.scenario": "Редактор сценариев",
      "info.nav.plugins": "Плагины и блоки",
      "info.nav.templates": "Шаблоны",
      "info.nav.mailing": "Редактор Постов Ботов",
      "info.nav.analytics": "Аналитика ботов и данные",
      "info.nav.deploy": "Деплой",
      "info.nav.tips": "Полезные советы",

      "info.hero.desc":
        "Настольное приложение для создания Telegram- и VK-ботов без ручной сборки проекта: визуальный сценарий, свои блоки (плагины), Менеджер Каналов, Редактор Постов Канала, шаблоны, аналитика ботов, рассылки и выгрузка на сервер.",

      "info.modules.title": "Разделы главного меню",
      "info.modules.intro": "Каждый раздел — отдельный модуль. Порядок как на главном экране. Кратко, за что он отвечает:",
      "info.modules.monitor.title_html": '<a href="/monitor/">Мониторинг</a>',
      "info.modules.monitor.desc": "CPU/RAM, процессы ботов, потоковые логи API и LLM.",
      "info.modules.channel_manager.title_html": '<a href="/channel-hub/">Менеджер Каналов</a>',
      "info.modules.channel_manager.desc": "Подключение каналов и ботов-модераторов, статистика, лента, модерация комментариев.",
      "info.modules.post_editor.title_html": '<a href="/post-studio/">Редактор Постов Канала</a>',
      "info.modules.post_editor.desc": "Создание, планирование и публикация постов в Telegram-каналы.",
      "info.modules.bots.title_html": '<a href="/bots/">Чат-Боты</a>',
      "info.modules.bots.desc": "Список ботов, токены, запуск/остановка, переход в конструктор сценариев.",
      "info.modules.scenario.title_html": '<a href="/editor/scenario/">Редактор сценариев</a>',
      "info.modules.scenario.desc": "Холст с блоками и связями — логика диалога, меню, условия, сообщения.",
      "info.modules.templates.title_html": '<a href="/templates/">Библиотека шаблонов</a>',
      "info.modules.templates.desc": "Готовые сценарии, импорт/экспорт <code>.bbpack.json</code>, установка на бота.",
      "info.modules.mailing.title_html": '<a href="/mailing/">Редактор Постов Ботов</a>',
      "info.modules.mailing.desc": "HTML-сообщения с медиа, фильтр подписчиков по ролям и тегам.",
      "info.modules.analytics.title_html": '<a href="/analytics/">Аналитика ботов</a>',
      "info.modules.analytics.desc": "Графики активности, календарь событий, обзор по выбранному чат-боту.",
      "info.modules.builder.title_html": '<a href="/plugin-builder/">Мастер компонентов</a>',
      "info.modules.builder.desc": "Создание и правка своих блоков: поля свойств, цвет, Python-шаблон.",
      "info.modules.plugins.title_html": '<a href="/plugins/">Плагины</a>',
      "info.modules.plugins.desc": "Каталог блоков: встроенные (только просмотр) и ваши (редактирование).",
      "info.modules.database.title_html": '<a href="/database/">База данных</a>',
      "info.modules.database.desc": "Просмотр и правка <code>user_data.db</code>, импорт .db / .json.",
      "info.modules.deploy.title_html": '<a href="/deployment/">Деплой</a>',
      "info.modules.deploy.desc": "Docker-архив для локального запуска или выгрузка на VPS по SSH.",

      "info.quickstart.title": "Быстрый старт",
      "info.quickstart.step1_html":
        '<strong>Создайте бота в мессенджере.</strong> Telegram: <a href="https://t.me/BotFather" target="_blank" rel="noopener">@BotFather</a> → команда <code>/newbot</code> → скопируйте API-токен. VK: создайте сообщество и получите ключ доступа группы с правами сообщений.',
      "info.quickstart.step2_html":
        'Откройте <a href="/bots/">Чат-Боты</a> → добавьте бота: название, платформа (Telegram или VK), вставьте токен. Для каналов: создайте <strong>бота-модератора</strong> в <a href="/channel-hub/">Менеджере Каналов</a> и сделайте его администратором канала.',
      "info.quickstart.step3_html":
        'Диалог: нажмите <strong>Конструктор сценариев</strong> у карточки бота и соберите цепочку (старт → сообщения / меню → условия). Посты в канал: откройте <a href="/post-studio/">Редактор Постов Канала</a>, выберите подключённый канал и составьте пост.',
      "info.quickstart.step4_html":
        "Сохраните сценарий (кнопка сохранения в редакторе) или опубликуйте/запланируйте пост. При необходимости вернитесь к списку ботов и <strong>запустите</strong> чат-бота; для каналов держите бота-модератора запущенным.",
      "info.quickstart.step5_html":
        'Проверьте диалог в Telegram или VK либо сам канал. Смотрите логи в <a href="/monitor/">Мониторинге</a>, если что-то не отвечает.',
      "info.quickstart.tip_html":
        "<strong>Совет.</strong> Для VK можно подставить стандартный сценарий (приветствие и меню) прямо из карточки бота — удобно как точка старта. Статистика постов и комментарии — в Менеджере Каналов, а не в Аналитике ботов.",

      "info.bots.title": "Чат-Боты",
      "info.bots.intro_html":
        'Раздел <a href="/bots/">Чат-Боты</a> — центр управления диалоговыми проектами. Каждый чат-бот хранит сценарий, файлы и базу пользователей в папке проекта. <strong>Боты-модераторы</strong> (только для каналов, без сценария) создаются и ведутся в <a href="/channel-hub/">Менеджере Каналов</a>.',
      "info.bots.actions_title": "Что можно делать",
      "info.bots.action1": "Добавлять и удалять чат-ботов (Telegram / VK).",
      "info.bots.action2": "Запускать и останавливать процесс бота.",
      "info.bots.action3": "Открывать визуальный конструктор сценария (только чат-боты).",
      "info.bots.action4": "Для VK — проверить токен и применить шаблонный сценарий.",
      "info.bots.note_html":
        "<strong>Важно.</strong> После смены сценария обычно нужно <em>перезапустить</em> бота, чтобы подтянуть новый код. Бот-модератор должен быть администратором канала, чтобы публиковать посты и модерировать комментарии.",

      "info.channel_manager.title": "Менеджер Каналов",
      "info.channel_manager.intro_html":
        '<a href="/channel-hub/">Менеджер Каналов</a> связывает Telegram-каналы с BotBuilder: боты-модераторы, KPI, лента постов, графики и модерация комментариев.',
      "info.channel_manager.how_title": "Как подключить канал",
      "info.channel_manager.how1": "Создайте или выберите бота-модератора (токен от @BotFather). У этого типа нет сценария — он обслуживает только каналы.",
      "info.channel_manager.how2": "Добавьте бота администратором Telegram-канала (как минимум с правом публикации).",
      "info.channel_manager.how3_html":
        "В Менеджере Каналов добавьте канал (публичный <code>@username</code> или invite-ссылка) и привяжите к боту-модератору.",
      "info.channel_manager.how4": "Откройте карточку канала: обзор, графики, недавние посты и действия (правка / удаление / комментарии).",
      "info.channel_manager.features_title": "Что даёт раздел",
      "info.channel_manager.feat1": "Список подключённых каналов и быстрое переключение между ними.",
      "info.channel_manager.feat2": "Просмотры, реакции и вовлечённость; при необходимости — экспорт PDF.",
      "info.channel_manager.feat3": "Лента постов с обновлением; переход в Редактор Постов Канала для создания или правки.",
      "info.channel_manager.feat4": "Модерация комментариев, если у поста включено обсуждение.",
      "info.channel_manager.note":
        "Менеджер Каналов работает через бота-модератора. Держите его запущенным, пока публикуете или модерируете.",

      "info.post_editor.title": "Редактор Постов Канала",
      "info.post_editor.intro_html":
        '<a href="/post-studio/">Редактор Постов Канала</a> собирает посты для канала: визуальная вёрстка или HTML, медиа, inline-кнопки, расписание и публикация.',
      "info.post_editor.how_title": "Как опубликовать пост",
      "info.post_editor.how1": "Выберите целевой канал (он уже должен быть подключён в Менеджере Каналов).",
      "info.post_editor.how2": "Составьте пост: добавьте ряды (текст, медиа, кнопки) или переключитесь в режим HTML.",
      "info.post_editor.how3": "Сохраните черновик, опубликуйте сразу или выберите дату/время для отложенной публикации.",
      "info.post_editor.how4": "Кнопка «Обновить» — для уже опубликованного поста; «Новый пост» очищает форму после успешной публикации.",
      "info.post_editor.features_title": "Возможности редактора",
      "info.post_editor.feat1": "Панель форматирования (жирный, курсив, ссылки, списки) в визуальном режиме.",
      "info.post_editor.feat2": "Медиафайлы и кнопки inline-клавиатуры под постом.",
      "info.post_editor.feat3": "История черновиков и опубликованных постов выбранного канала.",
      "info.post_editor.feat4": "После публикации или планирования — новый пост одним кликом.",
      "info.post_editor.note":
        "Для публикации нужен запущенный бот-модератор с правами в канале. Если публикация не удалась — проверьте Менеджер Каналов и логи Мониторинга.",

      "info.scenario.title": "Редактор сценариев",
      "info.scenario.intro_html":
        "Открывается из карточки чат-бота или через меню «Вид → Новое окно». Сценарий — граф: <strong>узлы (блоки)</strong> и <strong>связи</strong> между ними. Боты-модераторы этот редактор не используют.",
      "info.scenario.how_title": "Как собирать логику",
      "info.scenario.how1": "Перетащите блок из палитры на холст (старт, сообщение, меню, условие и др.).",
      "info.scenario.how2": "Клик по блоку открывает свойства справа: текст, кнопки, переменные.",
      "info.scenario.how3": "Соедините выход одного блока со входом другого — так задаётся порядок шагов.",
      "info.scenario.how4": "Сохраните сценарий. История версий позволяет откатить изменения (Time Machine).",
      "info.scenario.blocks_title": "Типичные блоки",
      "info.scenario.block_start_html": "<strong>Старт</strong> — точка входа (часто команда <code>/start</code>).",
      "info.scenario.block_message_html": "<strong>Сообщение</strong> — текст пользователю, опционально медиа.",
      "info.scenario.block_menu_html": "<strong>Меню</strong> — кнопки и переходы по выбору.",
      "info.scenario.block_condition_html": "<strong>Условие</strong> — ветвление по данным пользователя или ответу.",
      "info.scenario.block_data_html": "<strong>Команда / данные</strong> — реакции на команды и работа с полями.",
      "info.scenario.block_custom": "<strong>Свои плагины</strong> — любые блоки, которые вы опубликовали в мастере.",

      "info.plugins.title": "Плагины и блоки",
      "info.plugins.intro":
        "Плагин — переиспользуемый блок сценария: UI-поля + Python-шаблон обработчика. Встроенные плагины нельзя менять; свои — можно править и удалять.",
      "info.plugins.manage_title": "Просмотр и управление",
      "info.plugins.manage_html":
        'Откройте <a href="/plugins/">Плагины</a>: список всех блоков. Для своего — «Редактировать», для встроенного — только просмотр.',
      "info.plugins.create_title": "Создание своего блока",
      "info.plugins.create1_html":
        '<a href="/plugin-builder/">Мастер компонентов</a> → укажите <strong>ID</strong> (латиница, цифры, <code>_</code> или <code>-</code>), название, цвет на холсте.',
      "info.plugins.create2": "Добавьте поля свойств (текст, число, переключатель и т.д.) — они появятся в панели редактора.",
      "info.plugins.create3_html":
        "Напишите или поправьте Python-шаблон обработчика (Jinja2). Он компилируется в код бота при сохранении сценария.",
      "info.plugins.create4": "Опубликуйте компонент — блок сразу появится в палитре редактора сценариев.",
      "info.plugins.import_title": "Импорт и обмен",
      "info.plugins.import1_html":
        'Готовые сценарии с плагинами часто идут в пакете <code>.bbpack.json</code> через <a href="/templates/">Библиотеку шаблонов</a>.',
      "info.plugins.import2":
        "Если при установке шаблона не хватает плагинов, приложение предупредит — установите недостающие или импортируйте пакет целиком.",
      "info.plugins.import3":
        "Свои плагины лежат в папке пользовательских плагинов данных приложения (см. «Справка → Папка данных»).",
      "info.plugins.error405_html":
        "<strong>Если сохранение плагина не работает (405).</strong> Полностью закройте BotBuilder и запустите снова — на порту мог остаться старый процесс backend.",

      "info.templates.title": "Библиотека шаблонов",
      "info.templates.intro_html":
        'В <a href="/templates/">Шаблонах</a> — локальные и marketplace-пакеты сценариев. Формат обмена: <code>.bbpack.json</code>.',
      "info.templates.item1_html": "<strong>Превью</strong> — посмотреть граф до установки.",
      "info.templates.item2_html": "<strong>Установить на бота</strong> — подставить сценарий выбранному проекту.",
      "info.templates.item3_html": "<strong>Импорт / экспорт</strong> — обмен файлами между машинами или командой.",
      "info.templates.item4_html": "<strong>Редактирование шаблона</strong> — открывается тот же редактор сценария в режиме шаблона.",

      "info.analytics.title": "Аналитика ботов и база данных",
      "info.analytics.section_title": "Аналитика ботов",
      "info.analytics.desc_html":
        '<a href="/analytics/">Аналитика ботов</a> показывает активность выбранного чат-бота: периоды «сегодня / 7 / 30 дней», графики и календарь. Это визуализация — данные берутся из работы бота и хранилища пользователей. Статистика постов канала — в <a href="/channel-hub/">Менеджере Каналов</a>.',
      "info.database.section_title": "База данных",
      "info.database.desc_html":
        '<a href="/database/">База данных</a> открывает <code>user_data.db</code> проекта: таблицы, поля, импорт из другого <code>.db</code> или JSON. Удобно править роли, теги и тестовые записи вручную.',

      "info.mailing.title": "Редактор Постов Ботов",
      "info.mailing.desc_html":
        'В <a href="/mailing/">Рассылках</a> можно отправить HTML-сообщение с медиа подписчикам бота. Фильтруйте аудиторию по ролям и тегам из базы пользователей, проверьте превью и запустите рассылку.',
      "info.mailing.note":
        "Бот должен быть доступен (токен валиден). Для больших списков следите за лимитами мессенджера и логами в мониторинге.",

      "info.monitor.title": "Мониторинг",
      "info.monitor.desc_html":
        '<a href="/monitor/">Мониторинг</a> показывает нагрузку (CPU/RAM), процессы ботов (включая ботов-модераторов) и потоковые логи. Отсюда можно остановить зависший процесс и быстро найти ошибку API или LLM.',

      "info.deploy.title": "Деплой",
      "info.deploy.intro_html": '<a href="/deployment/">Деплой</a> готовит бота к запуску вне вашего ПК:',
      "info.deploy.item1_html": "<strong>Docker-архив</strong> — скачать пакет для локального или серверного Docker.",
      "info.deploy.item2_html": "<strong>VPS по SSH</strong> — указать хост, пользователя и путь, выгрузить и поднять сервис.",
      "info.deploy.outro":
        "Перед деплоем убедитесь, что сценарий сохранён, токен актуальный, а на сервере есть Docker (для docker-варианта) или нужные зависимости.",

      "info.tips.title": "Полезные советы",
      "info.tips.item1_html":
        "Меню <strong>Справка → Папка данных приложения</strong> открывает каталог, где лежат проекты ботов, пользовательские плагины и настройки.",
      "info.tips.item2_html":
        'Тема: <strong>Вид → Светлая / Тёмная</strong> или <span class="info-kbd">Ctrl</span>+<span class="info-kbd">Shift</span>+<span class="info-kbd">L</span>.',
      "info.tips.item3_html":
        "Несколько окон: <strong>Вид → Новое окно</strong> — удобно держать редактор, Менеджер Каналов и мониторинг рядом.",
      "info.tips.item4":
        "Если страница «пустая» или API не отвечает — перезапустите приложение и проверьте пункт «Настройки» (порт API в меню).",
      "info.tips.item5":
        "После обновления BotBuilder пересоберите/перезапустите ботов (включая ботов-модераторов в Менеджере Каналов), чтобы подтянуть новый runtime и плагины.",
      "info.tips.footer_html":
        'Открыть эту справку можно в любой момент: меню <strong>Справка → Инфо</strong> или горячая клавиша <span class="info-kbd">F1</span>.',
    },
    es: {
      "info.nav_aria": "Contenido",
      "info.nav_title": "Contenido",
      "info.nav.about": "Acerca de",
      "info.nav.modules": "Secciones del menú",
      "info.nav.quickstart": "Inicio rápido",
      "info.nav.monitor": "Monitorización",
      "info.nav.channel_manager": "Gestor De Canales",
      "info.nav.post_editor": "Editor De Posts Del Canal",
      "info.nav.bots": "Chat Bots",
      "info.nav.scenario": "Editor de escenarios",
      "info.nav.plugins": "Plugins y bloques",
      "info.nav.templates": "Plantillas",
      "info.nav.mailing": "Editor De Posts De Bots",
      "info.nav.analytics": "Analítica de bots y datos",
      "info.nav.deploy": "Despliegue",
      "info.nav.tips": "Consejos útiles",

      "info.hero.desc":
        "Aplicación de escritorio para crear bots de Telegram y VK sin montar el proyecto a mano: escenario visual, bloques propios (plugins), Gestor De Canales, Editor De Posts Del Canal, plantillas, Analítica de bots, difusiones y despliegue en servidor.",

      "info.modules.title": "Secciones del menú principal",
      "info.modules.intro": "Cada sección es un módulo aparte. El orden coincide con la pantalla de inicio. Brevemente, para qué sirve:",
      "info.modules.monitor.title_html": '<a href="/monitor/">Monitorización</a>',
      "info.modules.monitor.desc": "CPU/RAM, procesos de bots, logs en streaming de API e IA.",
      "info.modules.channel_manager.title_html": '<a href="/channel-hub/">Gestor De Canales</a>',
      "info.modules.channel_manager.desc": "Conectar canales y bots moderadores, estadísticas, feed y moderación de comentarios.",
      "info.modules.post_editor.title_html": '<a href="/post-studio/">Editor De Posts Del Canal</a>',
      "info.modules.post_editor.desc": "Crear, programar y publicar posts en canales de Telegram.",
      "info.modules.bots.title_html": '<a href="/bots/">Chat Bots</a>',
      "info.modules.bots.desc": "Lista de bots, tokens, iniciar/detener, abrir el constructor de escenarios.",
      "info.modules.scenario.title_html": '<a href="/editor/scenario/">Editor de escenarios</a>',
      "info.modules.scenario.desc": "Lienzo con bloques y conexiones — lógica del diálogo, menús, condiciones, mensajes.",
      "info.modules.templates.title_html": '<a href="/templates/">Biblioteca de plantillas</a>',
      "info.modules.templates.desc": "Escenarios listos, importar/exportar <code>.bbpack.json</code>, instalar en un bot.",
      "info.modules.mailing.title_html": '<a href="/mailing/">Editor De Posts De Bots</a>',
      "info.modules.mailing.desc": "Mensajes HTML con medios, filtrar suscriptores por roles y etiquetas.",
      "info.modules.analytics.title_html": '<a href="/analytics/">Analítica de bots</a>',
      "info.modules.analytics.desc": "Gráficos de actividad, calendario de eventos, resumen del chat bot seleccionado.",
      "info.modules.builder.title_html": '<a href="/plugin-builder/">Asistente de componentes</a>',
      "info.modules.builder.desc": "Crear y editar bloques propios: campos, color, plantilla Python.",
      "info.modules.plugins.title_html": '<a href="/plugins/">Plugins</a>',
      "info.modules.plugins.desc": "Catálogo de bloques: integrados (solo lectura) y personalizados (editables).",
      "info.modules.database.title_html": '<a href="/database/">Base de datos</a>',
      "info.modules.database.desc": "Ver y editar <code>user_data.db</code>, importar .db / .json.",
      "info.modules.deploy.title_html": '<a href="/deployment/">Despliegue</a>',
      "info.modules.deploy.desc": "Archivo Docker para ejecución local o subida a VPS por SSH.",

      "info.quickstart.title": "Inicio rápido",
      "info.quickstart.step1_html":
        '<strong>Cree un bot en el mensajero.</strong> Telegram: <a href="https://t.me/BotFather" target="_blank" rel="noopener">@BotFather</a> → comando <code>/newbot</code> → copie el token API. VK: cree una comunidad y obtenga la clave de acceso del grupo con permisos de mensajes.',
      "info.quickstart.step2_html":
        'Abra <a href="/bots/">Chat Bots</a> → añada un bot: nombre, plataforma (Telegram o VK), pegue el token. Para canales: cree un <strong>bot moderador</strong> en el <a href="/channel-hub/">Gestor De Canales</a> y añádalo como admin del canal.',
      "info.quickstart.step3_html":
        'Diálogo: pulse <strong>Constructor de escenarios</strong> en la tarjeta del bot y arme la cadena (inicio → mensajes / menú → condiciones). Posts al canal: abra el <a href="/post-studio/">Editor De Posts Del Canal</a>, elija un canal conectado y redacte el post.',
      "info.quickstart.step4_html":
        "Guarde el escenario (botón guardar en el editor) o publique/programe el post. Si hace falta, vuelva a la lista e <strong>inicie</strong> el chat bot; para canales mantenga el bot moderador en marcha.",
      "info.quickstart.step5_html":
        'Pruebe el diálogo en Telegram o VK, o revise el canal. Use los logs en <a href="/monitor/">Monitorización</a> si no responde.',
      "info.quickstart.tip_html":
        "<strong>Consejo.</strong> Para VK puede aplicar un escenario predeterminado (saludo y menú) desde la tarjeta del bot — un buen punto de partida. Las estadísticas de posts y comentarios están en el Gestor De Canales, no en Analítica de bots.",

      "info.bots.title": "Chat Bots",
      "info.bots.intro_html":
        'La sección <a href="/bots/">Chat Bots</a> es el centro de proyectos de diálogo. Cada chat bot guarda su escenario, archivos y base de usuarios en la carpeta del proyecto. Los <strong>bots moderadores</strong> (solo canales, sin escenario) se crean y gestionan en el <a href="/channel-hub/">Gestor De Canales</a>.',
      "info.bots.actions_title": "Qué puede hacer",
      "info.bots.action1": "Añadir y eliminar chat bots (Telegram / VK).",
      "info.bots.action2": "Iniciar y detener el proceso del bot.",
      "info.bots.action3": "Abrir el constructor visual de escenarios (solo chat bots).",
      "info.bots.action4": "Para VK — verificar el token y aplicar un escenario plantilla.",
      "info.bots.note_html":
        "<strong>Importante.</strong> Tras cambiar el escenario suele hacer falta <em>reiniciar</em> el bot para cargar el código nuevo. El bot moderador debe ser administrador del canal para publicar posts y moderar comentarios.",

      "info.channel_manager.title": "Gestor De Canales",
      "info.channel_manager.intro_html":
        'El <a href="/channel-hub/">Gestor De Canales</a> conecta canales de Telegram con BotBuilder: bots moderadores, KPI, feed de posts, gráficos y moderación de comentarios.',
      "info.channel_manager.how_title": "Cómo conectar un canal",
      "info.channel_manager.how1": "Cree o elija un bot moderador (token de @BotFather). Este tipo no tiene escenario: solo sirve a canales.",
      "info.channel_manager.how2": "Añada el bot como administrador de su canal de Telegram (al menos con permiso de publicación).",
      "info.channel_manager.how3_html":
        "En el Gestor De Canales, añada el canal (<code>@username</code> público o enlace de invitación) y vincúlelo al bot moderador.",
      "info.channel_manager.how4": "Abra la ficha del canal: resumen, gráficos, posts recientes y acciones (editar / eliminar / comentarios).",
      "info.channel_manager.features_title": "Qué incluye",
      "info.channel_manager.feat1": "Lista de canales conectados y cambio rápido entre ellos.",
      "info.channel_manager.feat2": "Vistas, reacciones y engagement; exportación PDF si hace falta.",
      "info.channel_manager.feat3": "Feed de posts con actualización; abrir el Editor De Posts Del Canal para crear o editar.",
      "info.channel_manager.feat4": "Moderación de comentarios cuando la discusión está activada.",
      "info.channel_manager.note":
        "El Gestor De Canales habla con Telegram a través del bot moderador. Manténgalo en marcha mientras publica o modera.",

      "info.post_editor.title": "Editor De Posts Del Canal",
      "info.post_editor.intro_html":
        'El <a href="/post-studio/">Editor De Posts Del Canal</a> crea posts de canal: diseño visual o HTML, medios, botones inline, programación y publicación.',
      "info.post_editor.how_title": "Cómo publicar un post",
      "info.post_editor.how1": "Seleccione el canal de destino (debe estar ya conectado en el Gestor De Canales).",
      "info.post_editor.how2": "Redacte el post: añada filas (texto, medios, botones) o cambie al modo HTML.",
      "info.post_editor.how3": "Guarde un borrador, publique ahora o elija fecha/hora para programar.",
      "info.post_editor.how4": "Use Actualizar al editar un post ya publicado; Nuevo post limpia el formulario tras una publicación correcta.",
      "info.post_editor.features_title": "Funciones del editor",
      "info.post_editor.feat1": "Barra de formato (negrita, cursiva, enlaces, listas) en el editor visual.",
      "info.post_editor.feat2": "Archivos multimedia y botones de teclado inline bajo el post.",
      "info.post_editor.feat3": "Historial de borradores y posts publicados del canal seleccionado.",
      "info.post_editor.feat4": "Tras publicar o programar, inicie un post nuevo con un clic.",
      "info.post_editor.note":
        "Para publicar hace falta un bot moderador en marcha con permisos en el canal. Si falla, revise el Gestor De Canales y los logs de Monitorización.",

      "info.scenario.title": "Editor de escenarios",
      "info.scenario.intro_html":
        "Se abre desde la tarjeta del chat bot o menú «Ver → Nueva ventana». Un escenario es un grafo: <strong>nodos (bloques)</strong> y <strong>conexiones</strong> entre ellos. Los bots moderadores no usan este editor.",
      "info.scenario.how_title": "Cómo armar la lógica",
      "info.scenario.how1": "Arrastre un bloque de la paleta al lienzo (inicio, mensaje, menú, condición, etc.).",
      "info.scenario.how2": "Al hacer clic en un bloque se abren las propiedades a la derecha: texto, botones, variables.",
      "info.scenario.how3": "Conecte la salida de un bloque con la entrada de otro para definir el orden de pasos.",
      "info.scenario.how4": "Guarde el escenario. El historial de versiones permite deshacer cambios (Time Machine).",
      "info.scenario.blocks_title": "Bloques habituales",
      "info.scenario.block_start_html": "<strong>Inicio</strong> — punto de entrada (a menudo el comando <code>/start</code>).",
      "info.scenario.block_message_html": "<strong>Mensaje</strong> — texto al usuario, medios opcionales.",
      "info.scenario.block_menu_html": "<strong>Menú</strong> — botones y transiciones según la elección.",
      "info.scenario.block_condition_html": "<strong>Condición</strong> — ramificación por datos del usuario o respuesta.",
      "info.scenario.block_data_html": "<strong>Comando / datos</strong> — reacciones a comandos y trabajo con campos.",
      "info.scenario.block_custom": "<strong>Plugins propios</strong> — cualquier bloque publicado en el asistente.",

      "info.plugins.title": "Plugins y bloques",
      "info.plugins.intro":
        "Un plugin es un bloque reutilizable: campos UI + plantilla Python del manejador. Los integrados no se editan; los propios sí se pueden cambiar y eliminar.",
      "info.plugins.manage_title": "Ver y gestionar",
      "info.plugins.manage_html":
        'Abra <a href="/plugins/">Plugins</a>: lista de todos los bloques. Para personalizados — «Editar», para integrados — solo lectura.',
      "info.plugins.create_title": "Crear un bloque propio",
      "info.plugins.create1_html":
        '<a href="/plugin-builder/">Asistente de componentes</a> → indique <strong>ID</strong> (letras latinas, dígitos, <code>_</code> o <code>-</code>), nombre, color en el lienzo.',
      "info.plugins.create2": "Añada campos de propiedades (texto, número, interruptor, etc.) — aparecerán en el panel del editor.",
      "info.plugins.create3_html":
        "Escriba o edite la plantilla Python del manejador (Jinja2). Se compila en el código del bot al guardar el escenario.",
      "info.plugins.create4": "Publique el componente — el bloque aparece de inmediato en la paleta del editor.",
      "info.plugins.import_title": "Importación e intercambio",
      "info.plugins.import1_html":
        'Escenarios listos con plugins suelen venir en paquete <code>.bbpack.json</code> vía la <a href="/templates/">Biblioteca de plantillas</a>.',
      "info.plugins.import2":
        "Si al instalar una plantilla faltan plugins, la app avisará — instale los que falten o importe el paquete completo.",
      "info.plugins.import3":
        "Los plugins propios están en la carpeta de plugins de datos de la aplicación (véase «Ayuda → Carpeta de datos»).",
      "info.plugins.error405_html":
        "<strong>Si falla guardar el plugin (405).</strong> Cierre BotBuilder por completo y ábralo de nuevo — puede quedar un proceso backend antiguo en el puerto.",

      "info.templates.title": "Biblioteca de plantillas",
      "info.templates.intro_html":
        'En <a href="/templates/">Plantillas</a> — paquetes locales y del marketplace. Formato de intercambio: <code>.bbpack.json</code>.',
      "info.templates.item1_html": "<strong>Vista previa</strong> — ver el grafo antes de instalar.",
      "info.templates.item2_html": "<strong>Instalar en bot</strong> — aplicar el escenario al proyecto elegido.",
      "info.templates.item3_html": "<strong>Importar / exportar</strong> — compartir archivos entre equipos o máquinas.",
      "info.templates.item4_html": "<strong>Editar plantilla</strong> — abre el mismo editor en modo plantilla.",

      "info.analytics.title": "Analítica de bots y base de datos",
      "info.analytics.section_title": "Analítica de bots",
      "info.analytics.desc_html":
        '<a href="/analytics/">Analítica de bots</a> muestra la actividad del chat bot seleccionado: «hoy / 7 / 30 días», gráficos y calendario. Solo visualización — los datos vienen de la actividad del bot y del almacén de usuarios. Las estadísticas de posts del canal están en el <a href="/channel-hub/">Gestor De Canales</a>.',
      "info.database.section_title": "Base de datos",
      "info.database.desc_html":
        '<a href="/database/">Base de datos</a> abre el <code>user_data.db</code> del proyecto: tablas, campos, importar desde otro <code>.db</code> o JSON. Útil para editar roles, etiquetas y registros de prueba.',

      "info.mailing.title": "Editor De Posts De Bots",
      "info.mailing.desc_html":
        'En <a href="/mailing/">Editor De Posts De Bots</a> puede enviar un mensaje HTML con medios a los suscriptores del bot. Filtre la audiencia por roles y etiquetas, previsualice y lance la difusión.',
      "info.mailing.note":
        "El bot debe estar disponible (token válido). Para listas grandes, vigile los límites del mensajero y los logs en monitorización.",

      "info.monitor.title": "Monitorización",
      "info.monitor.desc_html":
        '<a href="/monitor/">Monitorización</a> muestra carga (CPU/RAM), procesos de bots (incluidos los moderadores) y logs en streaming. Detenga procesos colgados y encuentre errores de API o IA.',

      "info.deploy.title": "Despliegue",
      "info.deploy.intro_html": '<a href="/deployment/">Despliegue</a> prepara el bot para ejecutarse fuera de su PC:',
      "info.deploy.item1_html": "<strong>Archivo Docker</strong> — descargar paquete para Docker local o en servidor.",
      "info.deploy.item2_html": "<strong>VPS por SSH</strong> — indicar host, usuario y ruta, subir y levantar el servicio.",
      "info.deploy.outro":
        "Antes del despliegue, asegúrese de que el escenario está guardado, el token es actual y el servidor tiene Docker (opción docker) o las dependencias necesarias.",

      "info.tips.title": "Consejos útiles",
      "info.tips.item1_html":
        "Menú <strong>Ayuda → Carpeta de datos de la aplicación</strong> abre el directorio con proyectos de bots, plugins personalizados y ajustes.",
      "info.tips.item2_html":
        'Tema: <strong>Ver → Claro / Oscuro</strong> o <span class="info-kbd">Ctrl</span>+<span class="info-kbd">Shift</span>+<span class="info-kbd">L</span>.',
      "info.tips.item3_html":
        "Varias ventanas: <strong>Ver → Nueva ventana</strong> — útil para tener el editor, el Gestor De Canales y la monitorización a la vez.",
      "info.tips.item4":
        "Si la página está en blanco o la API no responde — reinicie la aplicación y revise «Ajustes» (puerto API en el menú).",
      "info.tips.item5":
        "Tras actualizar BotBuilder, recompile/reinicie los bots (incluidos los moderadores en el Gestor De Canales) para cargar el nuevo runtime y plugins.",
      "info.tips.footer_html":
        'Abra esta ayuda en cualquier momento: menú <strong>Ayuda → Info</strong> o tecla <span class="info-kbd">F1</span>.',
    },
  };

  function mergeInfoLocales() {
    var base = global.BB_LOCALES || {};
    Object.keys(INFO_LOCALES).forEach(function (lang) {
      if (!base[lang]) base[lang] = {};
      Object.assign(base[lang], INFO_LOCALES[lang]);
    });
    global.BB_LOCALES = base;
  }

  mergeInfoLocales();
})(typeof window !== "undefined" ? window : globalThis);
