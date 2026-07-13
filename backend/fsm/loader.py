# backend/fsm/loader.py

import json
import os
from aiogram.fsm.state import State, StatesGroup

class DynamicFSM:
    def __init__(self, path: str):
        self.path = path
        self.states: dict[str, dict] = {}
        self.transitions: dict[str, list[dict]] = {}
        self._load()

    def _load(self):
        if not os.path.exists(self.path):
            raise FileNotFoundError(f"FSM файл не найден: {self.path}")

        with open(self.path, encoding="utf-8") as f:
            data = json.load(f)

        for state in data.get("states", []):
            name = state["name"]
            self.states[name] = {
                "message": state.get("message", ""),
                "transitions": state.get("transitions", [])
            }
            self.transitions[name] = state.get("transitions", [])

    def get_message(self, state: str) -> str:
        return self.states.get(state, {}).get("message", "")

    def get_transitions(self, state: str) -> list[dict]:
        return self.transitions.get(state, [])


# Пример использования в боте:
# from backend.fsm.loader import DynamicFSM
# fsm = DynamicFSM("projects/bot_{bot_id}/fsm.json")
# message = fsm.get_message("start")
# transitions = fsm.get_transitions("start")
