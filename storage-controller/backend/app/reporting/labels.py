"""Server-side report localization (Phase 5).

Report locale is chosen per report, independent of the UI language. English is the
default/fallback. User-entered free text (incident notes, corrective actions) is
NEVER auto-translated.
"""

from __future__ import annotations

_MONTHS = {
    "en": [
        "", "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December",
    ],
    "de": [
        "", "Januar", "Februar", "März", "April", "Mai", "Juni",
        "Juli", "August", "September", "Oktober", "November", "Dezember",
    ],
}

_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "report_title_default": "HACCP Temperature Report",
        "period": "Reporting period",
        "report_id": "Report ID",
        "generated": "Generated",
        "timezone": "Timezone",
        "organization": "Organization",
        "site": "Site",
        "overall_status": "Overall status",
        "status_ok": "OK",
        "status_attention": "Attention",
        "status_incomplete": "Incomplete data",
        "unit": "Storage unit",
        "type": "Type / profile",
        "range": "Permitted range",
        "min": "Min",
        "max": "Max",
        "avg": "Average",
        "coverage": "Data coverage",
        "unavailable": "Unavailable",
        "incidents": "Incidents",
        "longest_incident": "Longest incident",
        "time_above": "Time above limit",
        "time_below": "Time below limit",
        "defrost": "Defrost",
        "defrost_cycles": "Defrost cycles",
        "typical_duration": "Typical duration",
        "max_duration": "Max duration",
        "recovery": "Recovery",
        "abnormal": "Abnormal",
        "data_quality": "Data quality",
        "incomplete_warning": (
            "Data is incomplete for this period — not a compliance statement."
        ),
        "missing_entity": "No sensor data recorded.",
        "configured_limits": "Configured safety limits",
        "operational_note": (
            "Operational defrost characteristics are learned and are not legal/HACCP limits."
        ),
        "review": "Review & signature",
        "prepared_by": "Prepared by",
        "reviewed_by": "Reviewed by",
        "date": "Date",
        "signature": "Signature",
        "page": "Page",
        "of": "of",
        "none": "None",
        "incident_type": "Type",
        "incident_state": "State",
        "incident_start": "Start",
        "incident_end": "End",
        "incident_duration": "Duration",
        "incident_extreme": "Extreme",
        "corrective_action": "Corrective action",
        "no_incidents": "No incidents in this period.",
        "chart_unit": "°C",
        "summary_units": "Storage units",
        "summary_incidents": "Total incidents",
    },
    "de": {
        "report_title_default": "HACCP-Temperaturbericht",
        "period": "Berichtszeitraum",
        "report_id": "Berichts-ID",
        "generated": "Erstellt",
        "timezone": "Zeitzone",
        "organization": "Organisation",
        "site": "Standort",
        "overall_status": "Gesamtstatus",
        "status_ok": "OK",
        "status_attention": "Beachten",
        "status_incomplete": "Unvollständige Daten",
        "unit": "Lagereinheit",
        "type": "Typ / Profil",
        "range": "Zulässiger Bereich",
        "min": "Min",
        "max": "Max",
        "avg": "Mittel",
        "coverage": "Datenabdeckung",
        "unavailable": "Nicht verfügbar",
        "incidents": "Vorfälle",
        "longest_incident": "Längster Vorfall",
        "time_above": "Zeit über Grenze",
        "time_below": "Zeit unter Grenze",
        "defrost": "Abtauen",
        "defrost_cycles": "Abtauzyklen",
        "typical_duration": "Typische Dauer",
        "max_duration": "Max. Dauer",
        "recovery": "Erholung",
        "abnormal": "Auffällig",
        "data_quality": "Datenqualität",
        "incomplete_warning": (
            "Daten für diesen Zeitraum unvollständig — keine Konformitätsaussage."
        ),
        "missing_entity": "Keine Sensordaten aufgezeichnet.",
        "configured_limits": "Konfigurierte Sicherheitsgrenzen",
        "operational_note": (
            "Betriebliche Abtauwerte sind gelernt und keine rechtlichen/HACCP-Grenzen."
        ),
        "review": "Prüfung & Unterschrift",
        "prepared_by": "Erstellt von",
        "reviewed_by": "Geprüft von",
        "date": "Datum",
        "signature": "Unterschrift",
        "page": "Seite",
        "of": "von",
        "none": "Keine",
        "incident_type": "Typ",
        "incident_state": "Status",
        "incident_start": "Beginn",
        "incident_end": "Ende",
        "incident_duration": "Dauer",
        "incident_extreme": "Extremwert",
        "corrective_action": "Korrekturmaßnahme",
        "no_incidents": "Keine Vorfälle in diesem Zeitraum.",
        "chart_unit": "°C",
        "summary_units": "Lagereinheiten",
        "summary_incidents": "Vorfälle gesamt",
    },
}


def month_name(month: int, locale: str) -> str:
    table = _MONTHS.get(locale, _MONTHS["en"])
    if 1 <= month <= 12:
        return table[month]
    return str(month)


def labels(locale: str) -> dict[str, str]:
    return _LABELS.get(locale, _LABELS["en"])
