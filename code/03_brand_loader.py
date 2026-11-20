"""One instance, one brand: title, logo, colors and fonts come from a validated brand.json; a broken brand never breaks the app.

Origin: apps/core/branding.py (_text, brand_folders, load_brand).
Excerpt, shortened; not runnable on its own.
"""
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


def _text(data: dict, key: str, maxlen: int = 60, required: bool = True) -> str:
    """Short texts only, no control characters and no markup characters (the values end up in templates and CSS)."""
    if not required and key not in data:
        return ""
    value = _need(data, key).strip()
    if not value or len(value) > maxlen or any(ord(c) < 32 or c in "<>{}" for c in value):
        raise BrandError(f"Feld „{key}“: 1 bis {maxlen} Zeichen, keine Steuerzeichen und kein < > {{ }}")
    return value


def brand_folders(brand_dir: str = "", repo_dir: Path = REPO_BRANDS_DIR) -> dict[str, Path]:
    """All folders with a brand.json. An external BRAND_DIR (outside the repository) wins over brands/ in the repository."""
    found: dict[str, Path] = {}
    for root in (Path(brand_dir) if brand_dir else None, repo_dir):
        if root is None or not root.is_dir():
            continue
        for sub in sorted(root.iterdir()):
            if sub.is_dir() and NAME_RE.match(sub.name) and (sub / "brand.json").is_file():
                found.setdefault(sub.name, sub)
    return found


@lru_cache(maxsize=16)
def load_brand(name: str, brand_dir: str = "", repo_dir: Path = REPO_BRANDS_DIR) -> Brand:
    """Never raises: on any problem the default brand is used and the reason is carried along as a warning
    (shown by health_check and mcp_diagnose)."""
    name = (name or "").strip().lower() or DEFAULT_BRAND
    problem = ""
    if not NAME_RE.match(name):
        problem = "ungültiger Markenname (nur a–z, 0–9, - und _)"
    else:
        folder = brand_folders(brand_dir, repo_dir).get(name)
        if folder is None:
            problem = f"Marke „{name}“ nicht gefunden"
        else:
            try:
                return parse_brand(name, folder)
            except BrandError as exc:
                problem = f"Marke „{name}“ ungültig: {exc}"
    fallback = parse_brand(DEFAULT_BRAND, repo_dir / DEFAULT_BRAND)
    return Brand(**{**fallback.__dict__, "warnings": (f"{problem}; Rückfall auf {DEFAULT_BRAND}",)})
