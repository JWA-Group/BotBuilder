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
      "info.nav.bots": "Chat bots",
      "info.nav.scenario": "Scenario editor",
      "info.nav.plugins": "Plugins & blocks",
      "info.nav.templates": "Templates",
      "info.nav.analytics": "Analytics & data",
      "info.nav.mailing": "Broadcasts",
      "info.nav.monitor": "Monitoring",
      "info.nav.deploy": "Deploy",
      "info.nav.tips": "Tips",

      "info.hero.desc":
        "A desktop app for building Telegram and VK bots without manual project setup: visual scenarios, custom blocks (plugins), templates, analytics, broadcasts, and server deployment.",

      "info.modules.title": "Main menu sections",
      "info.modules.intro": "Each section is a separate module. Briefly, what it does:",
      "info.modules.bots.title_html": '<a href="/bots/">Chat bots</a>',
      "info.modules.bots.desc": "Bot list, tokens, start/stop, open the scenario builder.",
      "info.modules.scenario.title_html": '<a href="/editor/scenario/">Scenario editor</a>',
      "info.modules.scenario.desc": "Canvas with blocks and connections — dialog logic, menus, conditions, messages.",
      "info.modules.plugins.title_html": '<a href="/plugins/">Plugins</a>',
      "info.modules.plugins.desc": "Block catalog: built-in (view only) and custom (editable).",
      "info.modules.builder.title_html": '<a href="/plugin-builder/">Component wizard</a>',
      "info.modules.builder.desc": "Create and edit custom blocks: property fields, color, Python template.",
      "info.modules.templates.title_html": '<a href="/templates/">Template library</a>',
      "info.modules.templates.desc": "Ready scenarios, import/export <code>.bbpack.json</code>, install on a bot.",
      "info.modules.analytics.title_html": '<a href="/analytics/">Analytics</a>',
      "info.modules.analytics.desc": "Activity charts, event calendar, overview for the selected bot.",
      "info.modules.database.title_html": '<a href="/database/">Database</a>',
      "info.modules.database.desc": "View and edit <code>user_data.db</code>, import .db / .json.",
      "info.modules.mailing.title_html": '<a href="/mailing/">Broadcasts</a>',
      "info.modules.mailing.desc": "HTML messages with media, filter subscribers by roles and tags.",
      "info.modules.monitor.title_html": '<a href="/monitor/">Monitoring</a>',
      "info.modules.monitor.desc": "CPU/RAM, bot processes, streaming API and LLM logs.",
      "info.modules.deploy.title_html": '<a href="/deployment/">Deploy</a>',
      "info.modules.deploy.desc": "Docker archive for local runs or upload to VPS via SSH.",

      "info.quickstart.title": "Quick start",
      "info.quickstart.step1_html":
        '<strong>Create a bot in the messenger.</strong> Telegram: <a href="https://t.me/BotFather" target="_blank" rel="noopener">@BotFather</a> → command <code>/newbot</code> → copy the API token. VK: create a community and get the group access key with messaging permissions.',
      "info.quickstart.step2_html":
        'Open <a href="/bots/">Chat bots</a> → add a bot: name, platform (Telegram or VK), paste the token.',
      "info.quickstart.step3_html":
        'Click <strong>Scenario builder</strong> on the bot card. On the canvas, build a chain: start → messages / menu → conditions.',
      "info.quickstart.step4_html":
        "Save the scenario (save button in the editor). If needed, return to the bot list and <strong>start</strong> the bot.",
      "info.quickstart.step5_html":
        'Test the dialog in Telegram or VK. Check logs in <a href="/monitor/">Monitoring</a> if something does not respond.',
      "info.quickstart.tip_html":
        "<strong>Tip.</strong> For VK you can apply a default scenario (greeting and menu) directly from the bot card — a handy starting point.",

      "info.bots.title": "Chat bots",
      "info.bots.intro_html":
        'The <a href="/bots/">Chat bots</a> section is the hub for your projects. Each bot stores its scenario, files, and user database in the project folder.',
      "info.bots.actions_title": "What you can do",
      "info.bots.action1": "Add and remove bots (Telegram / VK).",
      "info.bots.action2": "Start and stop the bot process.",
      "info.bots.action3": "Open the visual scenario builder.",
      "info.bots.action4": "For VK — verify the token and apply a template scenario.",
      "info.bots.note_html":
        "<strong>Important.</strong> After changing the scenario you usually need to <em>restart</em> the bot to load the new code.",

      "info.scenario.title": "Scenario editor",
      "info.scenario.intro_html":
        'Opens from the bot card or via menu «View → New window». A scenario is a graph: <strong>nodes (blocks)</strong> and <strong>connections</strong> between them.',
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

      "info.analytics.title": "Analytics & database",
      "info.analytics.section_title": "Analytics",
      "info.analytics.desc_html":
        '<a href="/analytics/">Analytics</a> shows activity for the selected bot: «today / 7 / 30 days», charts and calendar. Visualization only — data comes from bot activity and user storage.',
      "info.database.section_title": "Database",
      "info.database.desc_html":
        '<a href="/database/">Database</a> opens the project <code>user_data.db</code>: tables, fields, import from another <code>.db</code> or JSON. Handy for editing roles, tags and test records manually.',

      "info.mailing.title": "Broadcasts",
      "info.mailing.desc_html":
        'In <a href="/mailing/">Broadcasts</a> you can send an HTML message with media to bot subscribers. Filter the audience by roles and tags from the user database, preview and run the broadcast.',
      "info.mailing.note":
        "The bot must be available (valid token). For large lists, watch messenger limits and logs in monitoring.",

      "info.monitor.title": "Monitoring",
      "info.monitor.desc_html":
        '<a href="/monitor/">Monitoring</a> shows load (CPU/RAM), bot processes and streaming logs. Stop a stuck process and quickly find API or LLM errors.',

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
        "Multiple windows: <strong>View → New window</strong> — handy to keep the editor and monitoring side by side.",
      "info.tips.item4":
        "If a page is blank or the API does not respond — restart the app and check «Settings» (API port in the menu).",
      "info.tips.item5":
        "After updating BotBuilder, rebuild/restart bots to pick up the new runtime and plugins.",
      "info.tips.footer_html":
        'Open this help anytime: menu <strong>Help → Info</strong> or hotkey <span class="info-kbd">F1</span>.',
    },
    ru: {
      "info.nav_aria": "Содержание",
      "info.nav_title": "Содержание",
      "info.nav.about": "О программе",
      "info.nav.modules": "Разделы меню",
      "info.nav.quickstart": "Быстрый старт",
      "info.nav.bots": "Чат-боты",
      "info.nav.scenario": "Редактор сценариев",
      "info.nav.plugins": "Плагины и блоки",
      "info.nav.templates": "Шаблоны",
      "info.nav.analytics": "Аналитика и данные",
      "info.nav.mailing": "Рассылки",
      "info.nav.monitor": "Мониторинг",
      "info.nav.deploy": "Деплой",
      "info.nav.tips": "Полезные советы",

      "info.hero.desc":
        "Настольное приложение для создания Telegram- и VK-ботов без ручной сборки проекта: визуальный сценарий, свои блоки (плагины), шаблоны, аналитика, рассылки и выгрузка на сервер.",

      "info.modules.title": "Разделы главного меню",
      "info.modules.intro": "Каждый раздел — отдельный модуль. Кратко, за что он отвечает:",
      "info.modules.bots.title_html": '<a href="/bots/">Чат-боты</a>',
      "info.modules.bots.desc": "Список ботов, токены, запуск/остановка, переход в конструктор сценариев.",
      "info.modules.scenario.title_html": '<a href="/editor/scenario/">Редактор сценариев</a>',
      "info.modules.scenario.desc": "Холст с блоками и связями — логика диалога, меню, условия, сообщения.",
      "info.modules.plugins.title_html": '<a href="/plugins/">Плагины</a>',
      "info.modules.plugins.desc": "Каталог блоков: встроенные (только просмотр) и ваши (редактирование).",
      "info.modules.builder.title_html": '<a href="/plugin-builder/">Мастер компонентов</a>',
      "info.modules.builder.desc": "Создание и правка своих блоков: поля свойств, цвет, Python-шаблон.",
      "info.modules.templates.title_html": '<a href="/templates/">Библиотека шаблонов</a>',
      "info.modules.templates.desc": "Готовые сценарии, импорт/экспорт <code>.bbpack.json</code>, установка на бота.",
      "info.modules.analytics.title_html": '<a href="/analytics/">Аналитика</a>',
      "info.modules.analytics.desc": "Графики активности, календарь событий, обзор по выбранному боту.",
      "info.modules.database.title_html": '<a href="/database/">База данных</a>',
      "info.modules.database.desc": "Просмотр и правка <code>user_data.db</code>, импорт .db / .json.",
      "info.modules.mailing.title_html": '<a href="/mailing/">Рассылки</a>',
      "info.modules.mailing.desc": "HTML-сообщения с медиа, фильтр подписчиков по ролям и тегам.",
      "info.modules.monitor.title_html": '<a href="/monitor/">Мониторинг</a>',
      "info.modules.monitor.desc": "CPU/RAM, процессы ботов, потоковые логи API и LLM.",
      "info.modules.deploy.title_html": '<a href="/deployment/">Деплой</a>',
      "info.modules.deploy.desc": "Docker-архив для локального запуска или выгрузка на VPS по SSH.",

      "info.quickstart.title": "Быстрый старт",
      "info.quickstart.step1_html":
        '<strong>Создайте бота в мессенджере.</strong> Telegram: <a href="https://t.me/BotFather" target="_blank" rel="noopener">@BotFather</a> → команда <code>/newbot</code> → скопируйте API-токен. VK: создайте сообщество и получите ключ доступа группы с правами сообщений.',
      "info.quickstart.step2_html":
        'Откройте <a href="/bots/">Чат-боты</a> → добавьте бота: название, платформа (Telegram или VK), вставьте токен.',
      "info.quickstart.step3_html":
        'Нажмите <strong>Конструктор сценариев</strong> у карточки бота. На холсте соберите цепочку: старт → сообщения / меню → условия.',
      "info.quickstart.step4_html":
        "Сохраните сценарий (кнопка сохранения в редакторе). При необходимости вернитесь к списку ботов и <strong>запустите</strong> бота.",
      "info.quickstart.step5_html":
        'Проверьте диалог в Telegram или VK. Смотрите логи в <a href="/monitor/">Мониторинге</a>, если что-то не отвечает.',
      "info.quickstart.tip_html":
        "<strong>Совет.</strong> Для VK можно подставить стандартный сценарий (приветствие и меню) прямо из карточки бота — удобно как точка старта.",

      "info.bots.title": "Чат-боты",
      "info.bots.intro_html":
        'Раздел <a href="/bots/">Чат-боты</a> — центр управления вашими проектами. Каждый бот хранит свой сценарий, файлы и базу пользователей в папке проекта.',
      "info.bots.actions_title": "Что можно делать",
      "info.bots.action1": "Добавлять и удалять ботов (Telegram / VK).",
      "info.bots.action2": "Запускать и останавливать процесс бота.",
      "info.bots.action3": "Открывать визуальный конструктор сценария.",
      "info.bots.action4": "Для VK — проверить токен и применить шаблонный сценарий.",
      "info.bots.note_html":
        "<strong>Важно.</strong> После смены сценария обычно нужно <em>перезапустить</em> бота, чтобы подтянуть новый код.",

      "info.scenario.title": "Редактор сценариев",
      "info.scenario.intro_html":
        "Открывается из карточки бота или через меню «Вид → Новое окно». Сценарий — граф: <strong>узлы (блоки)</strong> и <strong>связи</strong> между ними.",
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

      "info.analytics.title": "Аналитика и база данных",
      "info.analytics.section_title": "Аналитика",
      "info.analytics.desc_html":
        '<a href="/analytics/">Аналитика</a> показывает активность выбранного бота: периоды «сегодня / 7 / 30 дней», графики и календарь. Это визуализация — данные берутся из работы бота и хранилища пользователей.',
      "info.database.section_title": "База данных",
      "info.database.desc_html":
        '<a href="/database/">База данных</a> открывает <code>user_data.db</code> проекта: таблицы, поля, импорт из другого <code>.db</code> или JSON. Удобно править роли, теги и тестовые записи вручную.',

      "info.mailing.title": "Рассылки",
      "info.mailing.desc_html":
        'В <a href="/mailing/">Рассылках</a> можно отправить HTML-сообщение с медиа подписчикам бота. Фильтруйте аудиторию по ролям и тегам из базы пользователей, проверьте превью и запустите рассылку.',
      "info.mailing.note":
        "Бот должен быть доступен (токен валиден). Для больших списков следите за лимитами мессенджера и логами в мониторинге.",

      "info.monitor.title": "Мониторинг",
      "info.monitor.desc_html":
        '<a href="/monitor/">Мониторинг</a> показывает нагрузку (CPU/RAM), список процессов ботов и потоковые логи. Отсюда можно остановить зависший процесс и быстро найти ошибку API или LLM.',

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
        "Несколько окон: <strong>Вид → Новое окно</strong> — удобно держать редактор и мониторинг рядом.",
      "info.tips.item4":
        "Если страница «пустая» или API не отвечает — перезапустите приложение и проверьте пункт «Настройки» (порт API в меню).",
      "info.tips.item5":
        "После обновления BotBuilder пересоберите/перезапустите ботов, чтобы подтянуть новый runtime и плагины.",
      "info.tips.footer_html":
        'Открыть эту справку можно в любой момент: меню <strong>Справка → Инфо</strong> или горячая клавиша <span class="info-kbd">F1</span>.',
    },
    es: {
      "info.nav_aria": "Contenido",
      "info.nav_title": "Contenido",
      "info.nav.about": "Acerca de",
      "info.nav.modules": "Secciones del menú",
      "info.nav.quickstart": "Inicio rápido",
      "info.nav.bots": "Chat bots",
      "info.nav.scenario": "Editor de escenarios",
      "info.nav.plugins": "Plugins y bloques",
      "info.nav.templates": "Plantillas",
      "info.nav.analytics": "Analítica y datos",
      "info.nav.mailing": "Difusiones",
      "info.nav.monitor": "Monitorización",
      "info.nav.deploy": "Despliegue",
      "info.nav.tips": "Consejos útiles",

      "info.hero.desc":
        "Aplicación de escritorio para crear bots de Telegram y VK sin montar el proyecto a mano: escenario visual, bloques propios (plugins), plantillas, analítica, difusiones y despliegue en servidor.",

      "info.modules.title": "Secciones del menú principal",
      "info.modules.intro": "Cada sección es un módulo aparte. Brevemente, para qué sirve:",
      "info.modules.bots.title_html": '<a href="/bots/">Chat bots</a>',
      "info.modules.bots.desc": "Lista de bots, tokens, iniciar/detener, abrir el constructor de escenarios.",
      "info.modules.scenario.title_html": '<a href="/editor/scenario/">Editor de escenarios</a>',
      "info.modules.scenario.desc": "Lienzo con bloques y conexiones — lógica del diálogo, menús, condiciones, mensajes.",
      "info.modules.plugins.title_html": '<a href="/plugins/">Plugins</a>',
      "info.modules.plugins.desc": "Catálogo de bloques: integrados (solo lectura) y personalizados (editables).",
      "info.modules.builder.title_html": '<a href="/plugin-builder/">Asistente de componentes</a>',
      "info.modules.builder.desc": "Crear y editar bloques propios: campos, color, plantilla Python.",
      "info.modules.templates.title_html": '<a href="/templates/">Biblioteca de plantillas</a>',
      "info.modules.templates.desc": "Escenarios listos, importar/exportar <code>.bbpack.json</code>, instalar en un bot.",
      "info.modules.analytics.title_html": '<a href="/analytics/">Analítica</a>',
      "info.modules.analytics.desc": "Gráficos de actividad, calendario de eventos, resumen del bot seleccionado.",
      "info.modules.database.title_html": '<a href="/database/">Base de datos</a>',
      "info.modules.database.desc": "Ver y editar <code>user_data.db</code>, importar .db / .json.",
      "info.modules.mailing.title_html": '<a href="/mailing/">Difusiones</a>',
      "info.modules.mailing.desc": "Mensajes HTML con medios, filtrar suscriptores por roles y etiquetas.",
      "info.modules.monitor.title_html": '<a href="/monitor/">Monitorización</a>',
      "info.modules.monitor.desc": "CPU/RAM, procesos de bots, logs en streaming de API e IA.",
      "info.modules.deploy.title_html": '<a href="/deployment/">Despliegue</a>',
      "info.modules.deploy.desc": "Archivo Docker para ejecución local o subida a VPS por SSH.",

      "info.quickstart.title": "Inicio rápido",
      "info.quickstart.step1_html":
        '<strong>Cree un bot en el mensajero.</strong> Telegram: <a href="https://t.me/BotFather" target="_blank" rel="noopener">@BotFather</a> → comando <code>/newbot</code> → copie el token API. VK: cree una comunidad y obtenga la clave de acceso del grupo con permisos de mensajes.',
      "info.quickstart.step2_html":
        'Abra <a href="/bots/">Chat bots</a> → añada un bot: nombre, plataforma (Telegram o VK), pegue el token.',
      "info.quickstart.step3_html":
        'Pulse <strong>Constructor de escenarios</strong> en la tarjeta del bot. En el lienzo, arme la cadena: inicio → mensajes / menú → condiciones.',
      "info.quickstart.step4_html":
        "Guarde el escenario (botón guardar en el editor). Si hace falta, vuelva a la lista de bots e <strong>inicie</strong> el bot.",
      "info.quickstart.step5_html":
        'Pruebe el diálogo en Telegram o VK. Revise los logs en <a href="/monitor/">Monitorización</a> si no responde.',
      "info.quickstart.tip_html":
        "<strong>Consejo.</strong> Para VK puede aplicar un escenario predeterminado (saludo y menú) desde la tarjeta del bot — un buen punto de partida.",

      "info.bots.title": "Chat bots",
      "info.bots.intro_html":
        'La sección <a href="/bots/">Chat bots</a> es el centro de sus proyectos. Cada bot guarda su escenario, archivos y base de usuarios en la carpeta del proyecto.',
      "info.bots.actions_title": "Qué puede hacer",
      "info.bots.action1": "Añadir y eliminar bots (Telegram / VK).",
      "info.bots.action2": "Iniciar y detener el proceso del bot.",
      "info.bots.action3": "Abrir el constructor visual de escenarios.",
      "info.bots.action4": "Para VK — verificar el token y aplicar un escenario plantilla.",
      "info.bots.note_html":
        "<strong>Importante.</strong> Tras cambiar el escenario suele hacer falta <em>reiniciar</em> el bot para cargar el código nuevo.",

      "info.scenario.title": "Editor de escenarios",
      "info.scenario.intro_html":
        "Se abre desde la tarjeta del bot o menú «Ver → Nueva ventana». Un escenario es un grafo: <strong>nodos (bloques)</strong> y <strong>conexiones</strong> entre ellos.",
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

      "info.analytics.title": "Analítica y base de datos",
      "info.analytics.section_title": "Analítica",
      "info.analytics.desc_html":
        '<a href="/analytics/">Analítica</a> muestra la actividad del bot seleccionado: «hoy / 7 / 30 días», gráficos y calendario. Solo visualización — los datos vienen de la actividad del bot y del almacén de usuarios.',
      "info.database.section_title": "Base de datos",
      "info.database.desc_html":
        '<a href="/database/">Base de datos</a> abre el <code>user_data.db</code> del proyecto: tablas, campos, importar desde otro <code>.db</code> o JSON. Útil para editar roles, etiquetas y registros de prueba.',

      "info.mailing.title": "Difusiones",
      "info.mailing.desc_html":
        'En <a href="/mailing/">Difusiones</a> puede enviar un mensaje HTML con medios a los suscriptores del bot. Filtre la audiencia por roles y etiquetas, previsualice y lance la difusión.',
      "info.mailing.note":
        "El bot debe estar disponible (token válido). Para listas grandes, vigile los límites del mensajero y los logs en monitorización.",

      "info.monitor.title": "Monitorización",
      "info.monitor.desc_html":
        '<a href="/monitor/">Monitorización</a> muestra carga (CPU/RAM), procesos de bots y logs en streaming. Detenga procesos colgados y encuentre errores de API o IA.',

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
        "Varias ventanas: <strong>Ver → Nueva ventana</strong> — útil para tener el editor y la monitorización a la vez.",
      "info.tips.item4":
        "Si la página está en blanco o la API no responde — reinicie la aplicación y revise «Ajustes» (puerto API en el menú).",
      "info.tips.item5":
        "Tras actualizar BotBuilder, recompile/reinicie los bots para cargar el nuevo runtime y plugins.",
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
