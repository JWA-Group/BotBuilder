import os
import json
from backend.utils.generate_main import generate_main_py

from backend.core.app_paths import PROJECTS_DIR as BASE_DIR

def create_bot_project(bot_id: int, name: str, token: str, platform: str = "telegram"):
    bot_dir = os.path.join(BASE_DIR, f"bot_{bot_id}")
    os.makedirs(bot_dir, exist_ok=True)
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
