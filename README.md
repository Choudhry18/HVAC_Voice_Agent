# LiveKit HVAC Voice Agent

1. Copy `.env.example` to `.env` and add your LiveKit credentials.
2. Run `uv sync`.
3. Run `uv run python agent.py console` for a local voice test.
4. Run `uv run python agent.py dev` for a LiveKit call test.

## Standard request flow

```mermaid
flowchart TD
    A[Caller reports an HVAC problem] --> B{Immediate danger?}
    B -->|Gas, smoke, fire, or carbon monoxide| C[Tell caller to evacuate and call 911]
    B -->|No| D[Collect details conversationally, in any order]

    D --> E[Name, callback number, service address, property type, and availability]
    E --> E2[Commercial only: business name, site contact, equipment, and access notes]
    D --> I[Validate the address as soon as it is given and confirm the standardized form]
    I --> J{Address verified and in service area?}
    J -->|No| H[Save service request for staff review]
    J -->|Yes| K[Search appointment slots]

    K --> K1[Worker grades emergency from weather, issue, and volunteered context]
    K1 --> K2{Commercial request?}
    K2 -->|Yes| F[Classify the issue to a service code, required skill, and duration]
    F --> G{Supported service with enough confidence?}
    G -->|No| H
    G -->|Yes| L{Qualified technician and open slot?}
    K2 -->|No| L
    L -->|No| H
    L -->|Yes| M{Emergency outside business hours?}
    M -->|No| N[Offer up to three windows by day and time]
    M -->|Yes| O{On-call technician available?}
    O -->|No and no regular slot| H
    O -->|No but regular slot available| N
    O -->|Yes| P[Warn that after-hours service may cost more]
    P --> Q{Caller agrees?}
    Q -->|No| N
    Q -->|Yes| R[Summarize the request details and selected window]
    N --> R

    R --> S{Caller confirms everything?}
    S -->|No| D
    S -->|Yes| T[Book the appointment and reserve the window]
    T --> V[Read back the confirmed window and offer an email confirmation]

    H --> W[Service team follows up]
```
