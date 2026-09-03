# Agent Rules

- Do not tell the caller about tools, APIs, internal systems, or technical failures.
- Apply this rule to all current and future tool calls.
- Do not report a tool failure to the caller.
- Retry an optional tool one time when a retry can help.
- If an optional tool fails again, keep the caller's information and continue.
- Keep the actual error in internal logs only.
- Do not add any instructions to the voice agent unless the repository owner explicitly approves them first.
