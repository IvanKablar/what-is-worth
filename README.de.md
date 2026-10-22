# What is Worth?

[English](README.md) · **Deutsch** · [Español](README.es.md) · [中文](README.zh.md) · [日本語](README.ja.md) · [Русский](README.ru.md)

What is Worth? zeigt, was KI-Coding-Agenten an API-Gegenwert verbrauchen. Im Mittelpunkt steht nicht der Kalendermonat, sondern das Abo-Fenster von Wochenreset zu Wochenreset. Für jedes Konto wird außerdem gemessen, wie viele Dollar ein Prozentpunkt des Wochenkontingents wert ist.

Unterstützt wird zurzeit Claude Code. Weitere Agenten lassen sich als Adapter ergänzen. Alles läuft lokal: Es gibt kein Konto und keinen Proxy, und es werden keine Daten verschickt. Die einzige Netzwerkverbindung lädt einmal täglich die Preisliste von LiteLLM.

## Was es kann

- **Übersicht seit dem Wochenreset** für das angemeldete Konto: Auslastung, API-Wert, Wert je Prozentpunkt, Tempo und Prognose, wann das Limit erreicht ist.
- **Aufschlüsselung** nach Tag, Modell und Projekt. Projekt ist das Git-Repository. Worktrees und Unterordner zählen zu ihrem Hauptrepository.
- **Alle Konten in einer Tabelle**, jeweils im eigenen Wochenfenster mit eigenem Reset-Zeitpunkt.
- **Abopreis gegen API-Wert:** der Listenpreis jedes Plans pro Woche und ein Faktor aus API-Wert je Prozentpunkt geteilt durch das, was ein Prozentpunkt im Abo kostet.
- **Gesamtkosten aller Konten:** heute, diese Woche, dieser Monat und insgesamt seit Beginn der Historie.
- **Frühere Wochen** im Reset-Raster des Kontos.
- **Statusline in Claude Code** mit Wochenauslastung, Kosten seit Reset, Wert je Prozentpunkt, Countdown sowie Kosten der Sitzung und der letzten Abfrage.
- **Berichte** nach Tag, Woche und Monat über die gesamte Historie.
- **Sechs Sprachen:** Deutsch, Englisch, Spanisch, Chinesisch, Japanisch und Russisch.

Beispiel der Statusline:

```
Woche 51 % · 8,04 $ seit Reset · Reset Mo 01:00 (noch 3 T 7 h) · Sitzung 24,12 $ · Abfrage 2,34 $
```

## Voraussetzungen

- Python 3.11 oder neuer. Weitere Pakete sind nicht nötig.
- Git für die Projektzuordnung und die Freigabe.
- Claude Code, dessen Transkripte unter `~/.claude/projects/` liegen.

## Installation

1. Repository klonen, zum Beispiel nach `~/what-is-worth`.
2. Eine Freigabe erzeugen. Sie exportiert den letzten Commit nach `~/.local/share/what-is-worth/app`:

   ```
   scripts/release.sh
   ```

3. Den Befehl `wiw` in den Pfad legen:

   ```
   ln -s ~/.local/share/what-is-worth/app/bin/wiw ~/.local/bin/wiw
   ```

4. Die Statusline in `~/.claude/settings.json` eintragen:

   ```json
   "statusLine": {
     "type": "command",
     "command": "/home/<benutzer>/.local/share/what-is-worth/app/bin/wiw statusline",
     "padding": 0
   }
   ```

5. Einmal alles einlesen. Bei rund 2.700 Transkripten dauert das 10 bis 20 Sekunden:

   ```
   wiw sync
   ```

Claude Code löscht Transkripte standardmäßig nach 30 Tagen. Wer die Historie behalten will, setzt in `~/.claude/settings.json` einen hohen Wert für `cleanupPeriodDays`. Bereits eingelesene Daten bleiben im Datenbuch auch dann erhalten, wenn das Transkript später gelöscht wird.

## Benutzung

| Befehl | Wirkung |
|---|---|
| `wiw` | Übersicht seit dem letzten Wochenreset, gleich wie `wiw overview` |
| `wiw overview --weeks 10` | Übersicht mit zehn früheren Wochen |
| `wiw report day` | Kosten pro Tag, ebenso `week` und `month`, optional mit `--since 2026-09-01` |
| `wiw sync` | neue Daten einlesen, läuft sonst automatisch |
| `wiw sync --rebuild` | vorhandene Transkripte neu einlesen, etwa nach geänderten Leseregeln |
| `wiw reprice` | alle Kosten mit der aktuellen Preisliste neu berechnen |

In Claude Code öffnest du die Übersicht mit `! wiw`. Dabei ist kein Modell beteiligt, der Aufruf kostet also keine Tokens.

Die Statusline liest bei jeder Aktualisierung nur die neuen Zeilen der eigenen Sitzung nach. Höchstens alle fünf Minuten startet sie zusätzlich im Hintergrund einen Lauf über alle Transkripte.

## Konfiguration

| Variable | Bedeutung | Standard |
|---|---|---|
| `WIW_LANG` | Sprache: `de`, `en`, `es`, `zh`, `ja` oder `ru` | Systemsprache, sonst Englisch |
| `WIW_DATA_DIR` | Ablage von Datenbuch und Freigabe | `~/.local/share/what-is-worth` |
| `WIW_CONFIG_DIR` | Ablage der Preis-Overrides | `~/.config/what-is-worth` |
| `WIW_CACHE_DIR` | Zwischenspeicher der Preisliste | `~/.cache/what-is-worth` |
| `WIW_CLAUDE_DIRS` | weitere Claude-Konfigurationsordner, durch `:` getrennt | `~/.claude` und `CLAUDE_CONFIG_DIR` |

Eigene Preise, etwa für ein Modell, das LiteLLM noch nicht kennt, kommen in `~/.config/what-is-worth/prices.json`. Die Schlüssel entsprechen denen von LiteLLM, Preise gelten pro Token:

```json
{
  "claude-neues-modell": {
    "input_cost_per_token": 0.000004,
    "output_cost_per_token": 0.00002,
    "cache_read_input_token_cost": 0.0000002,
    "cache_creation_input_token_cost": 0.000005,
    "cache_creation_input_token_cost_above_1hr": 0.000008
  }
}
```

Danach `wiw reprice` ausführen.

## Wie gerechnet wird

**Datenquelle.** Claude Code schreibt jede API-Antwort mit ihren Token-Zahlen in ein Transkript pro Sitzung, Subagenten und Workflows in eigene Dateien. Jede Antwort steht dort oft mehrfach. What is Worth? behält pro Nachrichten-ID die vollständig gestreamte Kopie und bevorzugt die Hauptkonversation vor Wiederholungen in Subagenten.

**Preise.** Die Sätze kommen aus LiteLLM. Berücksichtigt werden Input, Output, Cache-Lesen und beide Cache-Lebensdauern von fünf Minuten und einer Stunde. Dazu kommen der doppelte Preis im Fast Mode, 10 % Aufschlag für Datenresidenz, Websuchen zu 10 $ pro 1.000 und Langkontext-Tarife. Liegt ein Prompt über der Schwelle, etwa bei Haiku 5.5 über 100.000 Tokens, kostet die ganze Anfrage den höheren Satz und nicht nur der Überschuss.

**Abo-Fenster und Konten.** Nur die Statusline erfährt Auslastung, Reset-Zeitpunkt und angemeldetes Konto. Sie schreibt diese Werte bei jeder Aktualisierung mit. Jede Antwort gehört zu dem Konto, das zu ihrem Zeitpunkt angemeldet war. Ein `/login` gilt für alle laufenden Sitzungen gleichzeitig.

**Wert je Prozentpunkt.** Berechnet werden die Kosten eines Kontos seit der ersten Auslastungsmeldung im Fenster, geteilt durch den Anstieg der Auslastung seitdem. Claude Code meldet nur ganze Prozent. Der Wert erscheint deshalb erst ab 5 Prozentpunkten Anstieg, damit der Rundungsfehler unter etwa 20 % bleibt.

**Kosten einer Abfrage.** Gemeint sind alle Antworten einer Sitzung von einer Eingabe bis zur nächsten, Subagenten eingeschlossen.

## Genauigkeit

- **Abgleich mit ccusage:** Für August bis Oktober 2026 stimmten Tokens und Kosten pro Monat und Modell überein. Seitdem behebt What is Worth? zwei Zählfehler, die ccusage noch hat. Das betrifft etwa 0,01 % der Kosten.
- **Preissätze:** Alle genutzten Modelle sind mit der offiziellen Preisseite von Anthropic abgeglichen. Die Tabelle liegt in `scripts/official_prices.json`.
- **Unabhängiges Prüfskript:** `scripts/verify_projects.py` rechnet alle Transkripte ohne den Programmcode neu und vergleicht pro Projekt mit dem Datenbuch. Optional nimmt es einen ccusage-Export hinzu:

  ```
  npx ccusage@latest claude session --json --offline > /tmp/cc.json
  python3 scripts/verify_projects.py /tmp/cc.json
  ```

- **Gegen den Zähler von Claude Code:** Die Summe pro Sitzung liegt etwa 1 % darunter. Claude Code schreibt einige Hintergrundaufrufe nicht ins Transkript.

Abopreise sind Listenpreise ohne Steuer von claude.com/pricing: Pro 20 $, Max 5x 100 $, Max 20x 200 $ pro Monat. Die Preisseite nennt für Max nur „ab 100 $“, der Preis für Max 20x ist der bisher bekannte. Tatsächliche Preise können durch Währung, Steuer, Jahreszahlung und Rabatte abweichen.

Alle Beträge sind API-Gegenwerte zu Listenpreisen. Auf einem Pro- oder Max-Abo sind sie Vergleichswerte und keine Rechnung.

## Bekannte Grenzen

- **Konten erst ab Installation.** Die Transkripte enthalten das Konto nicht. Kosten vor der ersten Statusline-Aktualisierung erscheinen als „nicht zuordenbar“.
- **Kontowechsel ohne Statusline.** Wer nach einem Login nur `claude -p` oder die IDE nutzt, dessen Wechsel wird erst bei der nächsten Aktualisierung einer Terminal-Statusline erkannt.
- **Abgelehnte Erstversuche.** Lehnt ein Modell vor jeder Ausgabe ab und antwortet ein anderes, wird der Fallback korrekt bepreist. Ob der abgelehnte Versuch kostet, hängt von seiner Kategorie ab. Die steht nicht im Transkript, und der Versuch wird nicht mitgerechnet.
- **Gelöschte Worktrees.** Worktrees, die schon vor dem ersten Einlesen gelöscht waren, lassen sich keinem Repository zuordnen und erscheinen unter ihrem Ordnernamen.
- **Ein Rechner.** Jeder Rechner führt sein eigenes Datenbuch.

## Aufbau

```
src/whatisworth/
  model.py            Datensätze aller Quellen: Antwort, Abfrage, Limit, Konto
  sources/base.py     Schnittstelle für Quellen
  sources/claude_code.py   Adapter für Claude Code
  ledger.py           SQLite-Datenbuch
  ingest.py           schrittweises Einlesen mit Sperre
  pricing.py          Preise aus LiteLLM mit Overrides
  projects.py         Arbeitsverzeichnis → Git-Repository
  insights.py         Fenster, Konten, Summen, Wert je Prozentpunkt
  statusline.py       Statusline
  cli.py              Befehle
  i18n.py, format.py, locales/   Sprachen und Formate
```

Das Datenbuch speichert Tokens und Rohfakten. Kosten werden beim Einlesen berechnet und lassen sich mit `wiw reprice` neu berechnen. Projekt und Konto werden erst beim Auswerten zugeordnet. Eine neue Quelle, etwa Gemini, ist ein weiterer Adapter, der dieselben Datensätze liefert.

## Entwicklung

```
python3 -m pytest -q tests
bin/wiw            # Arbeitsstand ausführen
scripts/release.sh # letzten Commit freigeben
```

Statusline und `wiw` laufen nur aus der Freigabe. Halbfertige Änderungen im Arbeitsstand werden deshalb nie live ausgeführt. Nach jedem Commit, der live gehen soll, `scripts/release.sh` ausführen.

Neue Texte kommen in alle Dateien unter `src/whatisworth/locales/`. Ein Test prüft, dass alle Sprachen dieselben Schlüssel und Platzhalter haben.

## Geplant

- Gemini CLI als zweite Quelle, gelesen aus dem OTel-Telemetrie-Log statt aus den Chat-Dateien. Nur das Log erfasst auch Router- und Summarizer-Aufrufe.
- Browser-Dashboard auf Basis derselben Auswertung.
- Projektregeln für Ordner, die sich nicht automatisch zuordnen lassen.
