"""Стартовый сценарий для VK: приветствие + меню (без /start — реагирует на любое сообщение)."""


def vk_default_scenario() -> dict:
    return {
        "tags": ["vk", "welcome", "menu"],
        "blocks": [
            {
                "id": "start",
                "type": "start",
                "x": 80,
                "y": 120,
                "data": {},
            },
            {
                "id": "msg_welcome",
                "type": "message",
                "x": 320,
                "y": 120,
                "data": {
                    "text": (
                        "Здравствуйте! 👋\n\n"
                        "Вы написали сообществу. Я помогу с основными вопросами.\n"
                        "Выберите пункт в меню ниже или напишите «меню»."
                    ),
                    "media": {"type": None, "files": []},
                    "inlineButtons": [],
                },
            },
            {
                "id": "menu_main",
                "type": "menu",
                "x": 560,
                "y": 120,
                "data": {
                    "name": "Главное меню",
                    "text": "Чем могу помочь?",
                    "buttons": [
                        {"text": "ℹ️ О нас"},
                        {"text": "📞 Контакты"},
                        {"text": "❓ Помощь"},
                    ],
                },
            },
            {
                "id": "msg_about",
                "type": "message",
                "x": 800,
                "y": 40,
                "data": {
                    "text": (
                        "О нас\n\n"
                        "Здесь вы можете рассказать о сообществе, услугах или проекте.\n"
                        "Отредактируйте этот текст в конструкторе сценариев."
                    ),
                    "media": {"type": None, "files": []},
                    "inlineButtons": [],
                },
            },
            {
                "id": "msg_contacts",
                "type": "message",
                "x": 800,
                "y": 120,
                "data": {
                    "text": (
                        "Контакты\n\n"
                        "Телефон: +7 (000) 000-00-00\n"
                        "Почта: info@example.com\n"
                        "Сайт: https://example.com"
                    ),
                    "media": {"type": None, "files": []},
                    "inlineButtons": [],
                },
            },
            {
                "id": "msg_help",
                "type": "message",
                "x": 800,
                "y": 200,
                "data": {
                    "text": (
                        "Помощь\n\n"
                        "Напишите «меню» — вернётесь в главное меню.\n"
                        "Напишите любой вопрос — мы ответим в рабочее время."
                    ),
                    "media": {"type": None, "files": []},
                    "inlineButtons": [],
                },
            },
            {
                "id": "menu_return",
                "type": "menu",
                "x": 1040,
                "y": 120,
                "data": {
                    "name": "Снова меню",
                    "text": "Главное меню:",
                    "buttons": [
                        {"text": "ℹ️ О нас"},
                        {"text": "📞 Контакты"},
                        {"text": "❓ Помощь"},
                    ],
                },
            },
        ],
        "connections": [
            {"from": "start", "to": "msg_welcome", "outputIndex": 0},
            {"from": "msg_welcome", "to": "menu_main", "outputIndex": 0},
            {"from": "menu_main", "to": "msg_about", "outputIndex": 0},
            {"from": "menu_main", "to": "msg_contacts", "outputIndex": 1},
            {"from": "menu_main", "to": "msg_help", "outputIndex": 2},
            {"from": "msg_about", "to": "menu_return", "outputIndex": 0},
            {"from": "msg_contacts", "to": "menu_return", "outputIndex": 0},
            {"from": "msg_help", "to": "menu_return", "outputIndex": 0},
        ],
    }
