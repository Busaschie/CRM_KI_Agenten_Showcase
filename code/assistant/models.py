# Showcase excerpt from a private project - not runnable on its own. See ../../README.md and LICENSE.
import secrets
from datetime import timedelta

from django.db import models
from django.utils import timezone


def _token() -> str:
    return secrets.token_hex(4)


def _expires() -> "timezone.datetime":
    return timezone.now() + timedelta(minutes=PendingAction.TTL_MINUTES)


class ToolCall(models.Model):
    """Protokoll: Welche Werkzeug-Aufrufe hat Claude im CRM ausgelöst (Nachweis, wer was gesehen/geändert hat)."""
    created_at = models.DateTimeField("Zeitpunkt", auto_now_add=True)
    tool = models.CharField("Werkzeug", max_length=100)
    is_write = models.BooleanField("Ändert Daten", default=False)
    arguments = models.JSONField("Parameter", default=dict, blank=True)
    ok = models.BooleanField("Erfolgreich", default=True)
    summary = models.CharField("Ergebnis (kurz)", max_length=255, blank=True)
    error = models.TextField("Fehler", blank=True)

    class Meta:
        verbose_name = "Werkzeug-Aufruf"
        verbose_name_plural = "Werkzeug-Aufrufe"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.created_at:%d.%m.%Y %H:%M} {self.tool}"


class PendingAction(models.Model):
    """Entwurf einer Aktion, die erst nach ausdrücklicher Bestätigung ausgeführt wird (prepare_* → confirm_*).

    Einmal verwendbar, läuft ab. Was bestätigt wird, steht in `preview` (genau das hat Niko gesehen)."""
    TTL_MINUTES = 30

    class Status(models.TextChoices):
        PENDING = "pending", "Wartet auf Bestätigung"
        CONFIRMED = "confirmed", "Ausgeführt"
        CANCELLED = "cancelled", "Verworfen"
        FAILED = "failed", "Fehlgeschlagen"

    token = models.CharField("Bestätigungs-ID", max_length=16, unique=True, default=_token, editable=False)
    kind = models.CharField("Art", max_length=50)
    payload = models.JSONField("Daten", default=dict)
    preview = models.TextField("Vorschau")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField("Angelegt", auto_now_add=True)
    expires_at = models.DateTimeField("Gültig bis", default=_expires)
    executed_at = models.DateTimeField("Ausgeführt am", null=True, blank=True)

    class Meta:
        verbose_name = "Entwurf zur Bestätigung"
        verbose_name_plural = "Entwürfe zur Bestätigung"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.kind} {self.token} ({self.get_status_display()})"
