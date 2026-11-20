"""Own job postings without a client: the rule sits in the model, not in the prompt.

Origin: apps/jobs/models.py (Mandate) and apps/clients/services.py (_check_sendable).
Excerpt, shortened; not runnable on its own.
"""


class Mandate(TimeStampedModel):
    class Kind(models.TextChoices):
        CLIENT = "client", "Kundenauftrag"
        OWN = "own", "Eigene Ausschreibung"

    kind = models.CharField(max_length=6, choices=Kind.choices, default=Kind.CLIENT)
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.PROTECT)   # empty only for kind=own

    def client_function_block(self, what: str) -> str:
        """Empty string = allowed. Otherwise the reason why `what` (contract, invoice, profile to a client) is blocked.
        The one place every client-only function asks: MCP tools, services and admin all call it."""
        if self.company_id:
            return ""
        return (f"{what} geht bei einer eigenen Ausschreibung ohne Firma nicht (Auftrag {self.pk}: „{self.title}“). "
                "Erst die Firma zuordnen (update_mandate mit company_id), dann ist es möglich.")

    def _check_company_rule(self) -> None:
        if self.kind == self.Kind.CLIENT and not self.company_id:
            raise ValidationError({"company": "Bei einem Kundenauftrag ist die Firma Pflicht."})
        if self.kind == self.Kind.OWN and self.company_id:
            self.kind = self.Kind.CLIENT        # assigning a company, on any path, turns it into a client mandate

    def save(self, *args, **kwargs):
        self._check_company_rule()              # forms, admin, services and MCP tools all end up here
        ...
        super().save(*args, **kwargs)


# A caller (contract service): the block is a readable message that reaches the user, not an exception swallowed somewhere.
def _check_sendable(contract):
    if block := contract.mandate.client_function_block("Ein Vertrag"):
        raise ContractError(block)
    ...
