# Phase 8.5.2 — Universal Number Intelligence

CALLSHIELD remains a Termux/Linux-first local security CLI/TUI. This phase
adds deeper *local* analysis of a phone number and an optional, explicitly
imported contact dataset. It is not a mobile app, identity lookup service,
or cloud reputation client.

## Commands

```text
callshield number <number>
callshield number <number> --json
callshield contacts import <file>
callshield contacts status
callshield contacts list
callshield contacts remove <number>
callshield contacts clear
callshield contacts scan
callshield contacts scan --json
callshield scan <number>   # unchanged
```

## Identity rules

- Local contact name is shown only when the user imported it.
- Source is labelled `Local Contacts`.
- Otherwise Name / Age are `NOT AVAILABLE` and Identity is `NOT VERIFIED`.
- Age is never inferred. Ownership is never claimed.

## Storage

Additive `local_contacts` table (schema version remains 7):

- `number_hash` (SHA-256)
- `number_masked`
- `display_name`
- `imported_at`

No plaintext numbers. Existing tables are unchanged.

## Tests

608 passed (582 existing + 26 new). No existing tests were modified.
