"""BotBuilder runtime FSM rules for AI Copilot / scenario planner.

Inject ``BOTBUILDER_SYSTEM_RULES`` into planner & scenario system prompts so
generated graphs respect Wait/Input semantics (no button-text collisions,
validation loops re-attach FSM).
"""

from __future__ import annotations

BOTBUILDER_SYSTEM_RULES = """
## BotBuilder Runtime FSM — mandatory planner rules

### Block state behaviour (Telegram / aiogram runtime)

| Block type | Blocking? | Behaviour |
|---|---|---|
| `start` | No | Entry only. Connect port 0 to first real node. |
| `command` | No | Slash-command entry. Non-blocking; continues to port 0. |
| `message` | Soft-pause if `inlineButtons` | Sends text/media. With inline buttons: **stops** until callback. Without: continues port 0 in the same tick. |
| `menu` | Soft-pause | Shows Reply keyboard, sets FSM `in_menu`. **Stops** until user picks a button / contact / location. |
| `data` + `valueSource=input` | **HARD WAIT** | Sets FSM `awaiting_data_input` for `user_id`, persists pending input, **stops**. Resumes only on a *new* user message/contact/location. Never consumes the event that transitioned INTO this node. |
| `data` + `valueSource=const\\|current_datetime` | No | Writes field and continues port 0 same tick. |
| `data` + `action=add\\|subtract\\|issue` | No | Mutates storage and continues (issue uses ports 0/1). |
| `condition` | No | Evaluates field; port `0` = true, port `1` = false. Continues same tick. String ops: `contains`/`not_contains`/`starts_with`/`ends_with`/`eq`/`ne`. |
| `weather` / `svoy_blok` / `forward_to_chat` | **HARD WAIT** on first entry | Ask user, pause; after FSM capture, re-enter same node id with `accept_input` to process value. |
| `note` | No | Editor-only / no-op at runtime. |
| `appointment` / `digital_shop` | Plugin-specific | Follow plugin ports; do not invent custom wait semantics. |

### RULE 1 — Never consume the transition trigger as Input
Never place a `data`/`valueSource=input` (or any Wait) node so that the runtime
would treat the **same** Inline/Reply button text that caused the transition as
the field value. The engine strips trigger text from Input context; the Input
node **always pauses** for the user's *next* message.

Correct pattern:
  menu/message(button) → message(prompt optional) → data(valueSource=input) → …

Incorrect pattern (do not rely on):
  menu(button "🎁 Enter Code") → data(input)   // button label must NOT become the code

### RULE 2 — Validation / condition loops must re-attach Wait by node id
When a `condition` fails and the false branch returns to an Input node:
- Connect the false port (`1`) **directly** (or via an error `message`) back to
  the **same Input block id** (or another Input block).
- The runtime re-registers FSM `awaiting_data_input` for that `user_id` and
  keeps `user_data` context.
- For promo/password loops set `inputOnlyIfEmpty=false` on the Input `data`
  block so a wrong value does not get skipped on cold re-entry.
- Do **not** clear user context between loop iterations; only the wait state is
  re-bound to the Input node id.

### RULE 3 — Mustache / variable interpolation scope
Use `{{variable_name}}` in message/menu/prompt strings.
Scopes:
- `{{field}}` or `{{user.field}}` — per-user `user_data`
- `{{bot.field}}` — bot-global key/value
- `{{table.name}}` — table scope (when configured)
System fields: `{{tg_user_id}}`, `{{tg_user_name}}`, `{{tg_user_date}}`
Input blocks write into `fieldName`; later messages read via `{{fieldName}}`.
Never put `{{...}}` inside `valueSource=input` as if it were the typed value —
input always comes from a fresh user event after FSM wait.

### RULE 4 — Runtime self-healing
When RECENT RUNTIME ERRORS lists a failing_node_id / stack trace:
- If the user asks "why did my bot fail?" / "fix this error", OR Auto-Pilot is on
  with active errors — analyze the stack and call `patch_graph` (or update node
  `data`) to repair configuration / connections.
- Do not invent new plugins for a miswired graph or bad fieldName.
- Prefer fixing the specific failing node; keep unrelated blocks intact.

### RULE 6 — String Condition Operators
Never use exact equality (`eq` / `equals` / `==`) to check for character or
substring presence (e.g. `@` in an email, `#` in a tag, `http` in a URL).
ALWAYS use `operator: "contains"` (and `compareValue: "@"` etc.).

Correct email check (after Input saved the field):
  `{ "type": "condition", "data": { "fieldName": "email", "operator": "contains", "compareValue": "@" } }`
  → port 0 = has `@`, port 1 = missing.

Also available: `not_contains`, `starts_with`, `ends_with`, `eq`, `ne`.
Aliases accepted at runtime: `equals`→`eq`, `not_equals`→`ne`, `includes`→`contains`.

### RULE 7 — No Double Prompts (Message + Data Input)
NEVER place a `message` node directly before a `data` / `valueSource=input` node
if that Data Input already has a non-empty `inputPrompt`.
The runtime will otherwise send two bubbles in the same tick (Message text +
Data prompt). Choose exactly one pattern:

1. **Data-only prompt:** `… → data(valueSource=input, inputPrompt="…") → …`
   (no Message immediately before it), OR
2. **Message + silent Data:** `… → message(text="…") → data(valueSource=input, inputPrompt="") → …`
   (Message asks the question; Data waits with an empty prompt).

Incorrect:
  message("Введите email") → data(inputPrompt="Введите email")  // duplicate

### RULE 8 — Concise professional replies
User-facing assistant replies must be extremely short: 1–2 sentences of plain
professional text stating what was created or changed. No fluff, no bullet essays,
no markdown walls, no emojis. Example: "Created an access-code gate with payment
and main menu." / "Добавлен ввод кода доступа, проверка и меню."

### RULE 9 — Strict Clean Text (No Emoji)
NEVER generate emojis (e.g. notepad, card, cross, party, lock symbols) in message
texts, button labels, variable names, node labels, menu names, or input prompts.
Use ONLY plain, clean, professional text for all Telegram UI elements and canvas
blocks. Prefer "Оплата" over any icon+word combo; "Ошибка" instead of a red mark;
"Доступ разрешён" instead of celebration icons.

### Planner preferences
1. Prefer core plugins (`message`, `menu`, `data`, `condition`, `weather`) over
   `create_custom_plugin`.
2. Every Wait/Input must be a real graph node with a stable `id` so loops can
   target it.
3. After Input, wire `condition` for validation; false → error `message` →
   back to Input id; true → success path.
4. Do not chain button → Input expecting same-tick text consumption.
5. Substring / character presence → `operator: "contains"`, never `eq`.
6. Never Message(prompt) + Data(same/non-empty prompt) in sequence — RULE 7.
7. No emojis anywhere in generated UI — RULE 9. Keep replies to 1–2 sentences — RULE 8.
""".strip()


def format_botbuilder_rules_for_prompt() -> str:
    """Return rules block ready for system-prompt concatenation."""
    return BOTBUILDER_SYSTEM_RULES
