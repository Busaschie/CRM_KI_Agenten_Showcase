"""Two-step writes: prepare -> preview -> explicit yes -> confirm.

Origin: apps/assistant/tools.py (_new_pending, _take, a confirm function) and apps/assistant/models.py (PendingAction).
Excerpt, shortened, comments translated; not runnable on its own.
"""


def _new_pending(kind: str, key: dict, payload: dict, preview: str) -> PendingAction:
    """Create a draft. An older open draft of the same kind for the same target is replaced (never two live drafts for one thing)."""
    with transaction.atomic():
        for old in PendingAction.objects.select_for_update().filter(kind=kind, status=PendingAction.Status.PENDING):
            if all(old.payload.get(k) == v for k, v in key.items()):
                old.status = PendingAction.Status.CANCELLED
                old.save(update_fields=["status"])
        # `preview` is exactly the text the user sees and says "yes" to; `token` is the one-time confirmation_id (16 hex characters).
        return PendingAction.objects.create(kind=kind, payload={**key, **payload}, preview=preview)


def _take(confirmation_id: str, kind: str) -> PendingAction:
    """Lock the draft row and hand it out once: right kind, still open, not expired."""
    try:
        p = PendingAction.objects.select_for_update().get(token=(confirmation_id or "").strip())
    except PendingAction.DoesNotExist:
        raise ToolError("Diese Bestätigungs-ID kenne ich nicht.") from None
    if p.kind != kind:
        raise ToolError("Diese Bestätigungs-ID gehört zu einer anderen Aktion.")
    if p.status != PendingAction.Status.PENDING:
        raise ToolError(f"Dieser Entwurf ist nicht mehr offen ({p.get_status_display()}).")
    if p.expires_at < timezone.now():                       # drafts live 30 minutes
        raise ToolError("Der Entwurf ist abgelaufen. Bitte neu vorbereiten.")
    return p


@tool(write=True, internal=True)
def confirm_update_mandate(confirmation_id: str) -> dict:
    with transaction.atomic():
        p = _take(confirmation_id, KIND_UPDATE_MANDATE)
        mandate = Mandate.objects.select_for_update(of=("self",)).get(pk=p.payload["mandate_id"])
        # Refuse if the data changed since the preview: the "yes" belongs to what the user saw, not to what is there now.
        if any(_mandate_value(mandate, c["field"]) != c["old"] for c in p.payload["changes"]):
            raise ToolError("Der Auftrag wurde inzwischen geändert. Bitte die Änderung neu vorbereiten.")
        _apply_mandate(mandate, {c["field"]: c["new"] for c in p.payload["changes"]})
        mandate.save()
        _finish(p, True)                                    # status CONFIRMED: a second use of the same ID fails in _take
    return {"id": mandate.pk, "saved": True}
