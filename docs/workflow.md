# Session 11 workflow wire diagram

`A` = atomic protocol, `D` = disposable component, `G` = glue. The model steps use synthetic replies by default; an optional local backend uses the same boundaries.

```mermaid
flowchart TD
    Input["Config JSON, record CSV, and saved HTML"] --> G1["G1 Load fixture bundle"]
    G1 --> D1["D1 Check required metadata and source pairing"]
    D1 -->|Valid record| A1["A1 Parse saved HTML to text"]
    D1 -->|Invalid input| Gate{"G2 Correction available?"}
    A1 -->|Incomplete registry or unusable text| Gate
    Gate -->|One replacement| D1
    Gate -->|Unresolved| Error["G2 Record the error and flag verify"]
    A1 -->|Ready service text| D2["D2 Request service evidence"]
    D2 --> A2E["A2 Validate evidence"]
    A2E --> D3["D3 Verify source quotes and apply research rules"]
    D3 --> D4["D4 Explain the fixed result"]
    D4 --> A2X["A2 Validate explanation"]
    A2X --> D5["D5 Check explanation consistency"]
    D2 -.->|Reply failure| Error
    A2E -.->|Invalid evidence| Error
    D3 -.->|Evidence conflict| Error
    D4 -.->|Reply failure| ErrExplanation["G2 Retain the rule result and log the error"]
    A2X -.->|Invalid explanation| ErrExplanation
    D5 -.->|Inconsistent explanation| ErrExplanation
    ErrExplanation --> Render["D5 Render all rows"]
    D5 --> Render
    Error --> Render
    Render --> G2["G2 Save audit HTML and shortlist CSV"]
    G2 --> Human["Human source review before any action"]
```

Bundle format errors stop before candidate processing. A missing or unreadable saved page can use the same one-replacement path. An invalid model reply never supplies new evidence or changes the rule result.
