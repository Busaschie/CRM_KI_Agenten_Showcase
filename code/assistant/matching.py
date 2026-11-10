# Showcase excerpt from a private project - not runnable on its own. See ../../README.md and LICENSE.
"""Matching Phase 1 (B-066): passende Kandidaten zu einem Auftrag – einfache, erklärbare Textsuche, nur lesend.

Prinzip: Jedes Kriterium aus `Mandate.must_have` / `nice_to_have` wird einzeln gegen den Text des Profils geprüft (Kurzprofil,
Zusammenfassung, Kompetenzen, Positionen und Berufsstationen, Branchen, Sprachen, Ausbildung, Zertifikate) und gegen den Wohnort
der Person (Ort, Region, Land; Fundstelle „Wohnort“, z. B. für „Wohnort in Bayern“). Ein Kriterium ist
erfüllt, wenn es selbst oder eines seiner Synonyme vorkommt; die Fundstelle nennt Feld, Textstück und den tatsächlich gefundenen
Begriff. Kein Gesamtprozent, keine Gewichtung, kein Modell: Das Ergebnis lässt sich Kriterium für Kriterium nachvollziehen.
Suche: Groß/Klein und Umlaute egal („Müller“ = „Mueller“), der Begriff muss am Wortanfang stehen („Vertriebsleiter“ trifft
„Vertriebsleiterin“, „Java“ trifft nicht „Ojava“). Mehrere Wörter: erst die Wortfolge, sonst alle Wörter im selben Feld.

Nie ausgewertet und nie ausgegeben: Alter, Geschlecht, Herkunft, Staatsangehörigkeit, Familienstand, Religion, Behinderung, Foto.
Die Berufserfahrung in Jahren (years_experience) wird nur geprüft, wenn ein Kriterium sie ausdrücklich nennt („5 Jahre
Berufserfahrung“). Der Name steht im Ergebnis nur zur Identifikation, er wird nicht ausgewertet.
"""
import re
import unicodedata

from django.utils import timezone

from apps.candidates.models import CandidateProfile
from apps.pipeline.models import Submission

SNIPPET_CONTEXT = 35
MAX_TERM_LENGTH = 80
MAX_SYNONYMS = 10
MAX_CRITERIA = 30
_UMLAUTS = (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"))
_LOCATION_CUES = {"wohnort", "wohnhaft", "wohnsitz", "region", "raum", "umgebung", "standort"}
_LOCATION_FILLER = _LOCATION_CUES | {"in", "im", "aus", "bei", "von", "um", "nahe", "naehe", "der", "die", "das", "und", "oder"}
_COUNTRIES = {"DE": "Deutschland Germany", "AT": "Österreich Austria", "CH": "Schweiz Switzerland", "RO": "Rumänien Romania"}
_YEARS = re.compile(
    r"(\d{1,2})\s*\+?\s*(?:jahre|jahr|years?)\b.*?(?:erfahrung|experience)|(?:erfahrung|experience).*?(\d{1,2})\s*\+?\s*(?:jahre|jahr|years?)\b")


class MatchingError(ValueError):
    """Eingabe unbrauchbar – Text ist für Claude/Niko lesbar."""


def fold(text: str) -> str:
    """Kleinschreibung, Umlaute als ae/oe/ue/ss, übrige Akzente weg."""
    return _fold_map(text)[0]


def _fold_map(text: str) -> tuple[str, list[int]]:
    """Gefalteter Text und je gefaltetem Zeichen die Position im Original (für das Textstück der Fundstelle)."""
    out, index = [], []
    for i, ch in enumerate(text or ""):
        f = ch.casefold()
        for src, dst in _UMLAUTS:
            f = f.replace(src, dst)
        f = "".join(c for c in unicodedata.normalize("NFKD", f) if not unicodedata.combining(c))
        out.append(f)
        index.extend([i] * len(f))
    return "".join(out), index


def _clean_term(value) -> str:
    return " ".join(str(value or "").split())


# ---------- Kriterien und Synonyme ----------

def criteria_of(mandate) -> tuple[list[str], list[str]]:
    def clean(items):
        out = []
        for item in items or []:
            text = _clean_term(item)
            if text and text not in out:
                out.append(text)
        return out[:MAX_CRITERIA]

    return clean(mandate.must_have), clean(mandate.nice_to_have)


def prepare_synonyms(synonyms, criteria: list[str]) -> tuple[dict[str, list[str]], list[str]]:
    """Synonyme den Kriterien zuordnen (gleiche Schreibweise egal). Gibt (Zuordnung, ignorierte Schlüssel) zurück: Synonyme zu
    Kriterien, die nicht im Auftrag stehen, werden ignoriert und gemeldet."""
    if synonyms in (None, {}, ""):
        return {}, []
    if not isinstance(synonyms, dict):
        raise MatchingError("synonyms muss ein Objekt sein: {Kriterium: [Synonyme]}.")
    by_key = {fold(c): c for c in criteria}
    used: dict[str, list[str]] = {}
    ignored = []
    for key, values in synonyms.items():
        criterion = by_key.get(fold(_clean_term(key)))
        if criterion is None:
            ignored.append(_clean_term(key)[:MAX_TERM_LENGTH])
            continue
        if isinstance(values, str):
            values = [values]
        if not isinstance(values, (list, tuple)):
            raise MatchingError(f"Die Synonyme zu „{key}“ müssen eine Liste sein.")
        terms = used.setdefault(criterion, [])
        for value in values:
            term = _clean_term(value)[:MAX_TERM_LENGTH]
            if term and fold(term) != fold(criterion) and term not in terms and len(terms) < MAX_SYNONYMS:
                terms.append(term)
    return used, ignored


# ---------- Textsuche ----------

def pieces_of(profile: CandidateProfile) -> list[tuple[str, str]]:
    """Durchsuchbare Textstücke (Feld, Text). Nur fachliche Felder, keine Kontakt- oder persönlichen Daten."""
    out: list[tuple[str, str]] = []

    def add(label, value):
        text = _clean_term(value)
        if text:
            out.append((label, text))

    add("Kurzprofil", profile.headline)
    add("Zusammenfassung", profile.summary)
    for item in profile.skills or []:
        add("Kompetenzen", item)
    for pos in profile.positions or []:
        if isinstance(pos, dict):
            add("Positionen", " ".join(str(pos.get(k) or "") for k in ("title", "company")))
            for task in pos.get("tasks") or []:
                add("Positionen (Aufgaben)", task)
        else:
            add("Positionen", pos)
    person = profile.person
    country = f"{person.country} ({_COUNTRIES[person.country.upper()]})" if person.country.upper() in _COUNTRIES else person.country
    add("Wohnort", ", ".join(x for x in (_clean_term(person.city), _clean_term(person.region), country) if x))
    for emp in profile.person.employments.all():
        add("Berufsstationen", f"{emp.title} {emp.company.name}")
    for item in profile.industries or []:
        add("Branchen", item)
    for lang in profile.languages or []:
        add("Sprachen", " ".join(str(lang.get(k) or "") for k in ("name", "level")) if isinstance(lang, dict) else lang)
    for edu in profile.education or []:
        if isinstance(edu, dict):
            add("Ausbildung", " ".join(str(edu.get(k) or "") for k in ("title", "institution")))
            for detail in edu.get("details") or []:
                add("Ausbildung", detail)
        else:
            add("Ausbildung", edu)
    for cert in profile.certifications or []:
        add("Zertifikate", " ".join(str(cert.get(k) or "") for k in ("name", "issuer")) if isinstance(cert, dict) else cert)
    return out


def _pattern(term_folded: str) -> re.Pattern:
    return re.compile(r"(?<![a-z0-9])" + re.escape(term_folded))


def _snippet(original: str, index: list[int], start: int, end: int) -> str:
    first = index[start]
    last = index[end - 1] + 1
    a, b = max(0, first - SNIPPET_CONTEXT), min(len(original), last + SNIPPET_CONTEXT)
    return ("…" if a > 0 else "") + original[a:b].strip() + ("…" if b < len(original) else "")


def find_term(term: str, pieces: list[tuple[str, str]], folded: list[tuple[str, str, str, list[int]]]) -> dict | None:
    """Fundstelle zu einem Begriff oder None. Erst die Wortfolge in einem Textstück, sonst alle Wörter im selben Feld."""
    wanted = fold(term).strip()
    if not wanted:
        return None
    pattern = _pattern(wanted)
    for label, original, hay, index in folded:
        if match := pattern.search(hay):
            return {"feld": label, "text": _snippet(original, index, match.start(), match.end())}
    place = [w for w in wanted.split() if w not in _LOCATION_FILLER]   # „Wohnort in Bayern“ -> „bayern“
    if place and len(place) < len(wanted.split()) and any(w in _LOCATION_CUES for w in wanted.split()):
        for label, original, hay, index in folded:
            if label == "Wohnort" and all(_pattern(w).search(hay) for w in place):
                match = _pattern(place[0]).search(hay)
                return {"feld": label, "text": _snippet(original, index, match.start(), match.end()), "stichwoerter": place}
    words = [w for w in wanted.split() if len(w) >= 3]
    if len(words) >= 2:
        for label in dict.fromkeys(label for label, *_ in folded):
            haystacks = [(o, h, i) for lab, o, h, i in folded if lab == label]
            if all(any(_pattern(w).search(h) for _o, h, _i in haystacks) for w in words):
                original, hay, index = next((o, h, i) for o, h, i in haystacks if _pattern(words[0]).search(h))
                match = _pattern(words[0]).search(hay)
                return {"feld": label, "text": _snippet(original, index, match.start(), match.end()),
                        "stichwoerter": words}
    return None


def required_years(criterion: str) -> int | None:
    """Nennt das Kriterium ausdrücklich Jahre Berufserfahrung („5 Jahre Berufserfahrung“)? Dann die Zahl, sonst None."""
    m = _YEARS.search(fold(criterion))
    return int(m.group(1) or m.group(2)) if m else None


def check_criterion(criterion: str, kind: str, synonyms: list[str], profile: CandidateProfile, pieces, folded) -> dict:
    """Ergebnis zu einem Kriterium: {"erfuellt": True, ...Fundstelle} oder {"erfuellt": False, "gesucht": [...]}."""
    years = required_years(criterion)
    if years is not None:   # years_experience wird nur hier und nur auf ausdrückliche Nennung geprüft
        have = profile.years_experience
        if have is not None and have >= years:
            return {"erfuellt": True, "kriterium": criterion, "art": kind, "gefunden": criterion,
                    "ueber_synonym": False, "fundstelle": {"feld": "Berufserfahrung", "text": f"{have} Jahre"}}
        return {"erfuellt": False, "kriterium": criterion, "art": kind, "gesucht": [criterion],
                "grund": "Berufserfahrung nicht erfasst" if have is None else f"nur {have} Jahre erfasst"}
    for term in [criterion, *synonyms]:
        if hit := find_term(term, pieces, folded):
            return {"erfuellt": True, "kriterium": criterion, "art": kind, "gefunden": term,
                    "ueber_synonym": term != criterion, "fundstelle": hit}
    return {"erfuellt": False, "kriterium": criterion, "art": kind, "gesucht": [criterion, *synonyms]}


# ---------- Hinweise (kein Filter) ----------

def hints_for(profile: CandidateProfile, mandate, today) -> list[str]:
    hints = []
    if mandate.salary_budget and profile.salary_expectation and profile.salary_expectation > mandate.salary_budget:
        hints.append(f"Gehaltswunsch {profile.salary_expectation:,} über dem Budget von {mandate.salary_budget:,}".replace(",", "."))
    location, city = _clean_term(mandate.location), _clean_term(profile.person.city)
    if location:
        if not city:
            hints.append(f"Wohnort nicht erfasst (Auftrag: {location})")
        elif fold(city) not in fold(location) and fold(location) not in fold(city):
            relocate = {True: "umzugsbereit", False: "nicht umzugsbereit", None: "Umzugsbereitschaft nicht erfasst"}[profile.willing_to_relocate]
            hints.append(f"Wohnort {city}, Auftrag in {location}: {relocate}")
    if profile.available_from and profile.available_from > today:
        hints.append(f"Verfügbar erst ab {profile.available_from:%d.%m.%Y} (der Auftrag hat im CRM kein Startdatum)")
    return hints


# ---------- Hauptfunktion ----------

def match_candidates(mandate, limit: int, synonyms=None) -> dict:
    must, nice = criteria_of(mandate)
    base = {"mandate_id": mandate.pk, "mandate": mandate.title, "kriterien": {"muss": must, "wunsch": nice}}
    if not must and not nice:
        return {**base, "treffer": [], "total_treffer": 0, "shown": 0, "geprueft": 0,
                "ausgeschlossen": {"anzahl": 0, "gruende": {}, "zeile": "Nichts geprüft."}, "ignorierte_synonyme": [],
                "hinweis": "Der Auftrag hat keine Muss- und keine Wunschkriterien. Es wurde nichts bewertet und nichts geraten: "
                           "Kriterien zuerst im Auftrag ergänzen."}
    used_synonyms, ignored = prepare_synonyms(synonyms, must + nice)
    today = timezone.localdate()
    in_mandate = set(Submission.objects.filter(mandate=mandate).values_list("candidate_id", flat=True))
    profiles = CandidateProfile.objects.select_related("person").prefetch_related("person__employments__company")
    reasons = {"bereits im Auftrag": 0, "vorgemerkt (on_hold_until in der Zukunft)": 0}
    rows, checked = [], 0
    for profile in profiles:
        checked += 1
        if profile.pk in in_mandate:
            reasons["bereits im Auftrag"] += 1
            continue
        if profile.on_hold_until and profile.on_hold_until > today:
            reasons["vorgemerkt (on_hold_until in der Zukunft)"] += 1
            continue
        pieces = pieces_of(profile)
        folded = [(label, text, *_fold_map(text)) for label, text in pieces]
        results = [check_criterion(c, "muss", used_synonyms.get(c, []), profile, pieces, folded) for c in must]
        results += [check_criterion(c, "wunsch", used_synonyms.get(c, []), profile, pieces, folded) for c in nice]
        met = [r for r in results if r["erfuellt"]]
        missing = [r for r in results if not r["erfuellt"]]
        must_met = sum(1 for r in met if r["art"] == "muss")
        nice_met = sum(1 for r in met if r["art"] == "wunsch")
        rows.append(({"person_id": profile.person_id, "name": str(profile.person), "kurzprofil": profile.headline,
                      "muss_fehlt": must_met < len(must), "muss_erfuellt": f"{must_met} von {len(must)}",
                      "wunsch_erfuellt": f"{nice_met} von {len(nice)}",
                      "erfuellt": [{k: v for k, v in r.items() if k != "erfuellt"} for r in met],
                      "fehlt": [{k: v for k, v in r.items() if k != "erfuellt"} for r in missing],
                      "hinweise": hints_for(profile, mandate, today)},
                     (must_met < len(must), -must_met, -nice_met, profile.person.last_name.casefold(), profile.person.first_name.casefold())))
    rows.sort(key=lambda r: r[1])
    shown = [r[0] for r in rows[:limit]]
    excluded = sum(reasons.values())
    parts = ", ".join(f"{n} {why}" for why, n in reasons.items() if n)
    return {
        **base, "geprueft": checked, "total_treffer": len(rows), "shown": len(shown), "treffer": shown,
        "ausgeschlossen": {"anzahl": excluded, "gruende": {why: n for why, n in reasons.items() if n},
                           "zeile": f"{checked} Kandidaten geprüft, {excluded} ausgeschlossen" + (f" ({parts})" if parts else "")
                                    + f", {len(rows)} bewertet."},
        "ignorierte_synonyme": ignored,
        "hinweis": ("Nur ein Vorschlag auf Basis einer einfachen Textsuche, kein Urteil. Muss-Kriterien nicht erfüllt = unten und mit "
                    "muss_fehlt markiert. Nichts wurde zugeordnet."),
    }
