#!/usr/bin/env python3
"""Prepare the existing public AC-PID-Frequency-Temp fork for parallel HA installation.

Run this script from (or pass the path to) the repository root. It does not
connect to GitHub, does not alter the original Home Assistant installation,
and intentionally does not change the heating algorithms.
"""

from __future__ import annotations

import json
from pathlib import Path
import re
import sys

OLD_DOMAIN = "ac_pid_frequency_temp"
NEW_DOMAIN = "ac_pid_frequency_temp_temp"
OLD_CARD = "ac-pid-frequency-temp-card"
NEW_CARD = "ac-pid-frequency-temp-temp-card"
OLD_NAME = "AC PID Frequency Temp"
NEW_NAME = "AC PID Frequency Temp Temp"

# Replace longer / more specific tokens before their prefixes.
REPLACEMENTS = [
    ("ac-pid-frequency-temp", "ac-pid-frequency-temp-temp"),
    (OLD_DOMAIN, NEW_DOMAIN),
    ("AC-PID-FREQUENCY-TEMP", "AC-PID-FREQUENCY-TEMP-TEMP"),
    ("AC_PID_FREQUENCY_TEMP", "AC_PID_FREQUENCY_TEMP_TEMP"),
    (OLD_NAME, NEW_NAME),
]

TEXT_EXTS = {
    ".py", ".js", ".json", ".yaml", ".yml", ".md", ".toml", ".ini",
    ".txt", ".css", ".html", ".sh", ".svg", ".xml",
}
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache"}


def fail(message: str) -> None:
    raise SystemExit(f"FEHLER: {message}")


def transform(source: str) -> str:
    # Keep the attribution and upstream URL (capitalized GitHub repo name) intact.
    for before, after in REPLACEMENTS:
        source = source.replace(before, after)
    return source


def is_ignored(path: Path, repo: Path) -> bool:
    return any(part in SKIP_DIRS for part in path.relative_to(repo).parts)


def read_utf8(path: Path) -> str:
    # Explicit UTF-8, as used by the original integration.
    return path.read_text(encoding="utf-8-sig")


def make_js_isolated(js: str) -> str:
    begin = "/* AC PID Frequency Temp Temp: isolierter Skript-Scope (Parallelbetrieb) */"
    if begin in js:
        return js
    # Original frontend is a plain script, not an ES module.
    if re.search(r"(?m)^\s*(?:import|export)\s+", js):
        fail("Die Lovelace-Karte enthält jetzt ES-Modul-Syntax. Bitte vor der Umstellung prüfen.")
    return f"{begin}\n(() => {{\n{js.rstrip()}\n}})();\n"


def run(repo: Path) -> None:
    repo = repo.resolve()
    old = repo / "custom_components" / OLD_DOMAIN
    new = repo / "custom_components" / NEW_DOMAIN
    if not (repo / ".git").is_dir():
        fail(f"Kein Git-Repository: {repo}")
    if new.exists():
        fail(f"Zielordner existiert schon: {new}. Skript nicht erneut ausführen.")
    if not old.is_dir():
        fail(f"Quellordner fehlt: {old}")

    manifest = old / "manifest.json"
    const = old / "const.py"
    card = old / "frontend" / (OLD_CARD + ".js")
    config_flow = old / "config_flow.py"
    for required in (manifest, const, card, config_flow, repo / "hacs.json"):
        if not required.is_file():
            fail(f"Erwartete Projektdatei fehlt: {required}")

    original_manifest = json.loads(read_utf8(manifest))
    if original_manifest.get("domain") != OLD_DOMAIN:
        fail("Die aktuelle manifest.json hat eine andere Domain als erwartet.")
    if f'DOMAIN = "{OLD_DOMAIN}"' not in read_utf8(const):
        fail("const.py verwendet nicht die erwartete DOMAIN-Deklaration.")
    original_js = read_utf8(card)
    if f'customElements.define("{OLD_CARD}"' not in original_js:
        fail("Das Frontend-Registrierungsmuster hat sich geändert; bitte manuell prüfen.")

    # Preflight: parse all resulting text files before touching the repository.
    rewritten: dict[Path, str] = {}
    for path in repo.rglob("*"):
        if not path.is_file() or is_ignored(path, repo) or path.suffix.lower() not in TEXT_EXTS:
            continue
        content = read_utf8(path)
        changed = transform(content)
        if path == card:
            changed = make_js_isolated(changed)
        if path == manifest:
            obj = json.loads(changed)
            obj["domain"] = NEW_DOMAIN
            obj["name"] = NEW_NAME
            obj["documentation"] = "https://github.com/Piet1702/AC-PID-Frequency-Temp"
            obj["issue_tracker"] = "https://github.com/Piet1702/AC-PID-Frequency-Temp/issues"
            obj["codeowners"] = ["@Piet1702"]
            # Distinct from the upstream version. Four numeric components are valid.
            obj["version"] = str(original_manifest.get("version", "2.4.1")) + ".1"
            changed = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
        if path == repo / "hacs.json":
            obj = json.loads(changed)
            obj["name"] = NEW_NAME
            changed = json.dumps(obj, ensure_ascii=False, indent=2) + "\n"
        if path.suffix.lower() == ".py":
            try:
                compile(changed, str(path), "exec")
            except SyntaxError as exc:
                fail(f"Python-Syntaxprüfung fehlgeschlagen: {path}: {exc}")
        if path.suffix.lower() == ".json":
            try:
                json.loads(changed)
            except json.JSONDecodeError as exc:
                fail(f"JSON-Syntaxprüfung fehlgeschlagen: {path}: {exc}")
        if changed != content:
            rewritten[path] = changed

    if manifest not in rewritten or const not in rewritten or card not in rewritten:
        fail("Zentrale Dateien konnten nicht wie erwartet vorbereitet werden.")

    print("Vorprüfung erfolgreich: Quellstruktur und Python/JSON geprüft.")
    print(f"Umbennen: {old.relative_to(repo)} -> {new.relative_to(repo)}")
    old.rename(new)

    affected = 0
    for original, content in rewritten.items():
        actual = (new / original.relative_to(old)) if old in original.parents else original
        actual.write_text(content, encoding="utf-8", newline="\n")
        affected += 1

    new_card = new / "frontend" / (NEW_CARD + ".js")
    old_card = new / "frontend" / (OLD_CARD + ".js")
    old_card.rename(new_card)

    # Safety checks on the final directory layout.
    new_manifest = json.loads(read_utf8(new / "manifest.json"))
    new_const = read_utf8(new / "const.py")
    new_js = read_utf8(new_card)
    assert new_manifest["domain"] == NEW_DOMAIN
    assert f'DOMAIN = "{NEW_DOMAIN}"' in new_const
    assert f'customElements.define("{NEW_CARD}"' in new_js
    assert new_js.startswith("/* AC PID Frequency Temp Temp: isolierter Skript-Scope")
    assert (new / "config_flow.py").exists()
    assert not old.exists()
    assert not old_card.exists()

    notes = repo / "PARALLELINSTALLATION.md"
    notes.write_text(
        "# AC PID Frequency Temp Temp – erste Version\n\n"
        "Dieser Fork ist als eigenständige Home-Assistant-Integration eingerichtet.\n\n"
        f"- Integrations-Domain: `{NEW_DOMAIN}`\n"
        f"- Integrationsordner: `custom_components/{NEW_DOMAIN}`\n"
        f"- Lovelace-Karte: `custom:{NEW_CARD}`\n"
        "- Regelungsalgorithmus: gegenüber Upstream unverändert\n"
        "- Keine MQTT-Steuerung, keine automatische Temperaturregelung (noch nicht implementiert)\n\n"
        "## Wichtige Sicherheitsregel\n\n"
        "Niemals beide Hz-Regler gleichzeitig dieselbe Klimaanlage steuern lassen. "
        "Für den ersten Test nur die Integration laden und die neue Regelung ausgeschaltet lassen. "
        "Keines der beiden erzeugten Sensor-Signale aktiv an die Klimaanlage koppeln, "
        "solange die Umschaltung nicht bewusst eingerichtet ist.\n\n"
        "## Installation\n\n"
        "Zunächst HACS-Repository installieren, danach Home Assistant neu starten und "
        "unter Einstellungen > Geräte & Dienste die Integration `AC PID Frequency Temp Temp` hinzufügen. "
        f"Karte: `type: custom:{NEW_CARD}`.\n\n"
        "## Weiterentwicklung\n\n"
        "Der Originalcode bleibt über Git-Remote `upstream` verfügbar. "
        "Beim späteren Übernehmen von Upstream-Änderungen müssen Pfad- und "
        "Namensänderungen erneut berücksichtigt werden.\n",
        encoding="utf-8",
        newline="\n",
    )
    print(f"Geänderte Textdateien: {affected}")
    print(f"Manifest: {new_manifest['name']} ({new_manifest['version']})")
    print(f"HA-Domain: {new_manifest['domain']}")
    print(f"Lovelace: custom:{NEW_CARD}")
    print("FERTIG. Bitte jetzt 'git status' und 'git diff --stat' prüfen.")


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    try:
        run(path)
    except (OSError, ValueError) as exc:
        fail(str(exc))
