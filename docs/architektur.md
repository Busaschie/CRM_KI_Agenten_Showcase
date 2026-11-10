# Architecture / Architektur

**English** · [Deutsch](#deutsch)

## Overview
```
Claude (desktop / phone / voice)
   │  MCP: stdio (local) or Streamable HTTP (remote, bearer token)
   ▼
MCP server  – apps/assistant
   ├─ tools (~60): search, create, change, prepare_* / confirm_*, stop_send
   ├─ drafts (PendingAction) and audit log (ToolCall)
   └─ server instructions + rules inside the tool descriptions
   ▼
Django 5.2 domain apps
   contacts · candidates · jobs · clients · pipeline · communications · privacy
   ▼
PostgreSQL + pgvector      django-q2 queue (in PostgreSQL)      Documenso (e-signature)
```

## Design decisions
- **Claude is the interface, the CRM is the authority.** Rules live in code and the database, never only in a prompt: contract lock, protected-characteristics checks, duplicate checks, expiry of drafts.
- **Two-step writes.** `prepare_*` creates a draft with preview and a one-time confirmation ID (30 minutes). `confirm_*` runs only after an explicit yes and refuses if the data changed in between.
- **Stop window.** Outgoing contracts, profiles, rejections and e-mails are delayed; `stop_send` cancels immediately.
- **Hard contract lock.** A candidate profile can only be sent to a client once the contract is signed. The check is in the model and applies on every path.
- **No generic dumps.** Tools return explicit fields. Fields that must never reach the model (for example work authorization) are simply not part of any tool output; a test asserts this.
- **Audit log without personal data.** Each tool call stores tool name, IDs and field names, not values.
- **Tool budget.** The tool list and server instructions are context for every chat. Limits for descriptions, schemas and instructions are enforced by tests; rules were moved from the global instructions into the tool descriptions where they are read at the moment of use.
- **Swappable providers.** `LLM_PROVIDER` (local Ollama or fake for tests) and `SIGNATURE_PROVIDER` (Documenso or fake). Tests run without network.
- **Remote access hardening.** Cloudflare tunnel, bearer token, host and origin checks, rate limiting, failed-attempt limits, diagnostic command.

## CV processing
Claude reads CV text through tools (`list_new_cvs`, `read_cv`, `create_candidate_from_cv`). Before saving, the server checks that tasks and details sit between the heading of their entry and the next one (two text extraction variants). Unclear cases are reported instead of guessed. Manually edited profile sections are protected when a CV is re-read.

## Testing
About 1,900 pytest tests (PostgreSQL, with an SQLite fallback), including budget tests for tool size, rule-placement tests, locking tests for concurrent confirmation and visibility tests for protected fields.

---

## Deutsch

### Überblick
Claude (Desktop, Handy, Sprache) spricht per MCP (stdio lokal, Streamable HTTP aus der Ferne mit Bearer-Token) mit dem MCP-Server `apps/assistant`. Der enthält rund 60 Werkzeuge, Entwürfe (`PendingAction`) und das Protokoll (`ToolCall`). Darunter liegen die Django-Apps (Kontakte, Kandidaten, Aufträge, Verträge, Pipeline, Kommunikation, Datenschutz) auf PostgreSQL mit pgvector, django-q2 als Warteschlange und Documenso für die E-Signatur.

### Entwurfsentscheidungen
- **Claude bedient, das CRM entscheidet.** Regeln stehen in Code und Datenbank, nicht nur im Prompt: Vertragssperre, Prüfung auf geschützte Merkmale, Dublettenprüfung, Ablauf der Entwürfe.
- **Zweistufiges Schreiben.** `prepare_*` erzeugt Entwurf, Vorschau und einmalige Bestätigungs-ID (30 Minuten); `confirm_*` läuft erst nach ausdrücklichem Ja und verweigert bei zwischenzeitlicher Änderung.
- **Stopp-Fenster.** Ausgehende Verträge, Profile, Absagen und Mails werden verzögert; `stop_send` bricht sofort ab.
- **Harte Vertragssperre.** Ein Profil geht erst nach unterschriebenem Vertrag an den Kunden; die Prüfung sitzt im Modell und gilt auf jedem Weg.
- **Keine pauschalen Dumps.** Werkzeuge liefern ausdrücklich benannte Felder. Was das Modell nie sehen soll (z. B. Arbeitsberechtigung), ist in keiner Ausgabe enthalten; ein Test belegt das.
- **Protokoll ohne Personendaten.** Gespeichert werden Werkzeugname, IDs und Feldnamen, keine Werte.
- **Werkzeugbudget.** Werkzeugliste und Server-Anweisung kosten in jedem Chat Kontext. Grenzen für Beschreibungen, Schemas und Anweisung erzwingen Tests; Regeln stehen in den Werkzeugbeschreibungen, wo sie im Moment der Nutzung gelesen werden.
- **Austauschbare Anbieter.** `LLM_PROVIDER` (Ollama lokal oder Fake) und `SIGNATURE_PROVIDER` (Documenso oder Fake); Tests laufen ohne Netz.
- **Absicherung des Fernzugriffs.** Cloudflare-Tunnel, Bearer-Token, Host- und Origin-Prüfung, Begrenzung, Fehlversuch-Limit, Diagnosebefehl.

### CV-Verarbeitung
Claude liest CV-Texte über Werkzeuge. Vor dem Speichern prüft der Server mit zwei Textfassungen, ob Aufgaben und Details zwischen der Überschrift ihres Eintrags und der des nächsten stehen; Unklares wird gemeldet statt geraten. Von Hand geänderte Profilabschnitte bleiben beim erneuten Einlesen erhalten.

### Tests
Rund 1.900 pytest-Tests (PostgreSQL, SQLite als Rückfall) mit Budget-Tests, Tests zur Regelplatzierung, Sperrtests bei gleichzeitiger Bestätigung und Sichtbarkeitstests für geschützte Felder.
