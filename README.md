# LiveKit HVAC Voice Agent

1. Copy `.env.example` to `.env` and add your LiveKit credentials.
2. Run `uv sync`.
3. Run `uv run python agent.py console` for a local voice test.
4. Run `uv run python agent.py dev` for a LiveKit call test.

## Commercial fix request flow

```mermaid
flowchart TD
    A[Commercial customer reports an HVAC problem] --> B{Immediate danger?}
    B -->|Gas, smoke, fire, or carbon monoxide| C[Tell caller to hang up and call 911]
    B -->|No| D[Assess safety and operational impact]

    D --> E[Collect business, contact, address, equipment, access, and availability details]
    E --> F[Classify the issue and equipment type]
    F --> G{Supported classification with enough confidence?}

    G -->|No| H[Save request for commercial staff review]
    G -->|Yes| I[Standardize address and ask caller to confirm it]
    I --> J{Address verified and in service area?}
    J -->|No| K[Commercial team follows up]
    J -->|Yes| L{Qualified technician and time available?}

    L -->|No| H
    L -->|Yes| M{Emergency outside business hours?}
    M -->|No| N[Offer up to three appointment windows]
    M -->|Yes| O{On-call technician available?}
    O -->|No| N
    O -->|Yes| P[Explain the higher after-hours cost]
    P --> Q{Caller agrees?}
    Q -->|No| N
    Q -->|Yes| R[Review request details and selected window]
    N --> R

    R --> S{Caller confirms everything?}
    S -->|No| E
    S -->|Yes| T[Create tentative commercial booking]
    T --> U[Mark as pending staff confirmation]
    U --> V[Read back the window and offer an email summary]

    H --> K
```
