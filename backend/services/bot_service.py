import os
import json
from backend.utils.generate_main import generate_main_py, generate_moderator_main

from backend.core.app_paths import PROJECTS_DIR as BASE_DIR


def create_bot_project(
    bot_id: int,
    name: str,
    token: str,
    platform: str = "telegram",
    kind: str = "scenario",
):
    bot_dir = os.path.join(BASE_DIR, f"bot_{bot_id}")
    os.makedirs(bot_dir, exist_ok=True)
    platform = "telegram"
    kind = "moderator" if str(kind or "").strip().lower() == "moderator" else "scenario"
    display_name = (name or "").strip() or (
        "Channel Moderator" if kind == "moderator" else f"Bot {bot_id}"
    )

    with open(os.path.join(bot_dir, "config.json"), "w", encoding="utf-8") as f:
        json.dump(
            {
                "name": display_name,
                "api_key": token,
                "platform": platform,
                "kind": kind,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )

    with open(os.path.join(bot_dir, "state.json"), "w", encoding="utf-8") as f:
        json.dump({}, f, indent=2, ensure_ascii=False)

    if kind == "moderator":
        # No scenario editor for moderator bots — Channel Hub runtime only.
        generate_moderator_main(bot_id)
        return

    initial_scenario = {
        "blocks": [
            {"id": "start", "type": "start", "x": 50, "y": 100, "data": {}}
        ],
        "connections": [],
        "tags": [],
    }
    with open(os.path.join(bot_dir, "scenario.json"), "w", encoding="utf-8") as f:
        json.dump(initial_scenario, f, ensure_ascii=False, indent=2)

    generate_main_py(bot_id)
