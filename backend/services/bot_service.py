import os
import json
from backend.utils.generate_main import generate_main_py
from backend.utils.vk_default_scenario import vk_default_scenario

from backend.core.app_paths import PROJECTS_DIR as BASE_DIR

def create_bot_project(bot_id: int, name: str, token: str, platform: str = "telegram"):
    bot_dir = os.path.join(BASE_DIR, f"bot_{bot_id}")
    os.makedirs(bot_dir, exist_ok=True)
    platform = (platform or "telegram").strip().lower()
    if platform not in ("telegram", "vk"):
        platform = "telegram"

    # config.json
    with open(os.path.join(bot_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(
            {"name": name, "api_key": token, "platform": platform},
            f,
            indent=2,
            ensure_ascii=False,
        )

    # state.json
    with open(os.path.join(bot_dir, "state.json"), "w", encoding="utf-8") as f:
        json.dump({}, f, indent=2, ensure_ascii=False)

    # Сценарий: для VK — готовое меню; для Telegram — только блок «старт»
    if platform == "vk":
        initial_scenario = vk_default_scenario()
    else:
        initial_scenario = {
            "blocks": [
                {"id": "start", "type": "start", "x": 50, "y": 100, "data": {}}
            ],
            "connections": [],
            "tags": [],
        }
    with open(os.path.join(bot_dir, "scenario.json"), "w", encoding="utf-8") as f:
        json.dump(initial_scenario, f, ensure_ascii=False, indent=2)

    # main.py по сценарию (при наличии scenario.json)
    generate_main_py(bot_id)
