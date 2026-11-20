"""Settings page: a typed register of .env keys; every input is checked by type, range and format before it is written.

Origin: apps/core/env_registry.py (Key, normalize).
Excerpt, shortened; not runnable on its own.
"""
LOCKED = frozenset({"DJANGO_DEBUG", "DJANGO_SECRET_KEY", "ALLOW_CRM_RESET"})      # never editable on the page, whatever the type


@dataclass(frozen=True)
class Key:
    name: str
    group: str
    kind: str                    # str | int | bool | time | email | url | choice | secret | iban | ...
    explain: str
    lo: int | None = None
    hi: int | None = None

    @property
    def editable(self) -> bool:
        return self.kind in EDITABLE_KINDS and self.name not in LOCKED

    @property
    def masked(self) -> bool:
        """Never shown, logged or quoted in texts (secrets, bank data)."""
        return self.kind in MASKED_KINDS


def normalize(key: Key, text: str) -> str:
    """Validate the input and bring it into the .env spelling. Raises ValueError_ with a readable German message."""
    if not key.editable:
        raise ValueError_(f"{key.name} ist gesperrt und kann hier nicht geändert werden.")
    text = (text or "").strip()
    if key.kind == "bool":
        if text.lower() not in ("1", "0", "true", "false", "an", "aus"):
            raise ValueError_(f"{key.name}: bitte „an“ oder „aus“ wählen.")
        return "1" if text.lower() in ("1", "true", "an") else "0"
    if key.kind == "int":
        if not re.fullmatch(r"\d{1,9}", text):
            raise ValueError_(f"{key.name}: bitte eine ganze Zahl eingeben.")
        n = int(text)
        if not (key.lo <= n <= key.hi):
            raise ValueError_(f"{key.name}: Wert muss zwischen {key.lo} und {key.hi} liegen.")
        return str(n)
    ...
    raise ValueError_(f"{key.name}: unbekannter Typ.")
