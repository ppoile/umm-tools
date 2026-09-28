#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZLV Mannschaftswertung für das Uster Mehrkampf Meeting (UMM).

Die Mannschaftswertung wird für die U12, U14 und U16 Wettkämpfe ermittelt.

Liest den TAF-Resultate-Export (CSV, z. B. "2026-09-27_Resultate-Export.csv")
und berechnet pro Kategorie (Klasse + Mehrkampf-Event) eine Mannschaftswertung:
  - Es zählen pro Verein die besten 4 Athleten (Punktesumme).
  - Ein Verein kommt nur in die Wertung, wenn mindestens 4 Athleten
    rangiert sind (Mindestzahl, konfigurierbar mit --min).
  - Nur Vereine aus dem Kanton Zürich (ZH) kommen in die Wertung.
  - Athleten mit 0 Punkten (DNS / aufgegeben / nicht rangiert) werden
    ignoriert; DNF-Athleten mit ClassRank sind rangiert und zählen.
  - "vereinslos" Athleten werden ignoriert.

Aufruf:
    python manschaftswertung.py 2026-09-27_Resultate-Export.csv
    python manschaftswertung.py export.csv --top 5        # Top-5 je Verein
    python manschaftswertung.py export.csv --podium 3     # erste 3 Ränge ausgeben
    python manschaftswertung.py export.csv --kanton ZH SG  # andere Kantone

Hinweis zum Punkteformat: Der Export nutzt ein Komma als
Tausender-Trennzeichen ("1,860" = 1860 Punkte).
"""

import argparse
import csv
import sys
from collections import defaultdict

# Mehrkampf-Events (Zeilen mit Gesamtpunktzahl). Die übrigen Zeilen
# (Einzelzeiten etc.) haben dieselben Event-Codes, aber keine
# Mehrkampf-Punktzahl im Feld "Result" mit Tausenderkomma.
COMBINED_EVENTS = {"MK", "5-K", "6-K", "7-K", "10-K"}

# Standard-Kanton für die Wertung
DEFAULT_CANTONS = {"ZH"}

# Vereine ohne ClubCode im Export (leeres Feld) können hier manuell
# einem Kanton zugeordnet werden. Nicht gelistete Vereine ohne Code
# werden übersprungen (mit Hinweis).
CLUB_CANTON_OVERRIDES = {
    "SSC Athletics": "ZH",
    "TV Oerlikon": "ZH",
    "LC Furttal ZH-Nord": "ZH",
    "TV Hinwil": "ZH",
    "STV Höri": "ZH",
    "LV Zürcher Oberland": "ZH",
    "LC Dübendorf": "ZH",
    "TV Dürnten": "ZH",
    "TV Uster": "ZH",
    "TV Egg": "ZH",
    "TV Maur": "ZH",
    "TV Hombrechtikon": "ZH",
}


def parse_points(raw):
    """'1,860' -> 1860, '656' -> 656, '0' -> 0, ungültig -> None."""
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        return None
    try:
        return int(raw.replace(",", "").replace("'", ""))
    except ValueError:
        return None


def club_canton(club_name, club_code, overrides):
    """Kanton eines Vereins bestimmen."""
    if club_code:
        parts = club_code.split(".")
        if len(parts) >= 2:
            return parts[1]
    return overrides.get(club_name)


def is_ranked(class_rank, details):
    """True, wenn der Athlet offiziell rangiert ist.

    Kriterium ist das Feld 'ClassRank' der Mehrkampf-Zeile: Ist es gesetzt,
    ist der Athlet rangiert – auch wenn er eine Disziplin als DNF beendet
    oder mit ogV (Ausschluss) gewertet hat (z. B. 'Prisca Mose Chivatsi',
    600m DNF, offiziell Rang 9 mit 2733 Punkten). Ist ClassRank leer,
    wurde der Wettkampf nicht beendet und der Athlet ist nicht rangiert
    (z. B. 'Syah Adras', 600m DNS, trotz 1458 Teilpunkten im Export).
    """
    return bool(class_rank and class_rank.strip())


def read_results(path):
    """CSV einlesen und die Mehrkampf-Zeilen mit Punkten extrahieren."""
    # Der Export ist Windows-1252-kodiert (nicht UTF-8), daher explizit
    # cp1252 verwenden.
    with open(path, newline="", encoding="cp1252") as fh:
        reader = csv.DictReader(fh, delimiter=";", quotechar='"')
        rows = []
        for row in reader:
            if row.get("Type") != "Athlete":
                continue
            if row.get("Event") not in COMBINED_EVENTS:
                continue
            points = parse_points(row.get("Result"))
            if points is None or points <= 0:
                continue  # DNS / aufgegeben / nicht rangiert
            if not is_ranked(row.get("ClassRank"), row.get("Details")):
                continue  # nicht rangiert (ClassRank leer, z. B. DNS)
            club = row.get("ClubName") or ""
            if not club or club.startswith("(vereinslos"):
                continue
            rows.append({
                "first": (row.get("FirstName") or "").strip(),
                "last": (row.get("LastName") or "").strip(),
                "club": club,
                "canton": club_canton(club, row.get("ClubCode") or "",
                                      CLUB_CANTON_OVERRIDES),
                "class_": (row.get("Class") or "").strip(),
                "event": (row.get("Event") or "").strip(),
                "points": points,
            })
        return rows


def compute_team_scores(rows, cantons, top_n, min_n):
    """Pro Kategorie (Klasse+Event) und Verein die Top-N-Summe berechnen.

    Vereine mit weniger als min_n rangierten Athleten kommen nicht in
    die Wertung.
    """
    by_category_club = defaultdict(list)
    skipped_clubs = set()

    for r in rows:
        if r["canton"] in cantons:
            key = (r["class_"], r["event"])
            by_category_club[(key, r["club"])].append(r)
        else:
            if r["canton"] is None:
                skipped_clubs.add(r["club"])

    scores = defaultdict(dict)  # category -> club -> (total, athletes)
    for (category, club), athletes in by_category_club.items():
        if len(athletes) < min_n:
            continue  # zu wenige rangierte Athleten -> keine Wertung
        best = sorted(athletes, key=lambda a: a["points"], reverse=True)[:top_n]
        total = sum(a["points"] for a in best)
        scores[category][club] = (total, best)

    return scores, sorted(skipped_clubs)


def main():
    ap = argparse.ArgumentParser(description="ZLV Mannschaftswertung für den UMM")
    ap.add_argument("csv_file", help="Resultate-Export (CSV, Semikolon)")
    ap.add_argument("--top", type=int, default=4,
                    help="Anzahl gewertete Athleten pro Verein (Default 4)")
    ap.add_argument("--min", type=int, default=4,
                    help="Mindestanzahl rangierter Athleten, damit ein "
                         "Verein in die Wertung kommt (Default 4)")
    ap.add_argument("--podium", type=int, default=3,
                    help="Anzahl angezeigter Ränge pro Kategorie (Default 3)")
    ap.add_argument("--kanton", nargs="+", default=sorted(DEFAULT_CANTONS),
                    help="Kantone, die in die Wertung kommen (Default: ZH)")
    args = ap.parse_args()

    rows = read_results(args.csv_file)
    if not rows:
        sys.exit("Keine gewerteten Mehrkampf-Resultate gefunden.")

    scores, skipped = compute_team_scores(rows, set(args.kanton),
                                          args.top, args.min)

    if skipped:
        print("Hinweis: folgende Vereine haben keinen ClubCode im Export "
              "und wurden übersprungen (ggf. in CLUB_CANTON_OVERRIDES "
              "ergänzen):")
        print("  " + ", ".join(skipped))
        print()

    for (class_, event) in sorted(scores):
        clubs = scores[(class_, event)]
        ranking = sorted(clubs.items(),
                         key=lambda kv: kv[1][0], reverse=True)[:args.podium]
        label = ", ".join(filter(None, (f"Klasse {class_}" if class_ else "",
                                        event)))
        print("=" * 72)
        print(f"Kategorie: {label}  –  beste {args.top} Athleten je Verein")
        print("=" * 72)
        for rank, (club, (total, athletes)) in enumerate(ranking, 1):
            print(f"{rank}. {club}  –  {total} Punkte")
            for a in sorted(athletes, key=lambda x: x["points"], reverse=True):
                print(f"     {a['first']} {a['last']} ({a['points']})")
        print()


if __name__ == "__main__":
    main()
