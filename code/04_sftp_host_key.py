"""Upload of the job pages over SFTP: the server host key is checked BEFORE any login, also with a password.

Origin: apps/jobs/sftp_sync.py (fingerprint, verify_host_key, connect).
Excerpt, shortened; not runnable on its own.
"""


def fingerprint(key) -> str:
    return "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")


def verify_host_key(key, expected: str) -> None:
    if not (expected or "").strip():
        raise FinalError("JOBS_SFTP_HOST_KEY fehlt (Fingerabdruck des Servers).")      # no pinned key = no connection
    found = fingerprint(key)
    if found != _norm_fp(expected):
        raise FinalError(f"Host-Key des Servers stimmt nicht überein (gefunden: {found}). Abbruch; nichts übertragen. "
                         "Nur nach Prüfung beim Anbieter den neuen Fingerabdruck eintragen.")


def connect() -> SftpRemote:
    """Pinned host key first, then ONE login attempt. Every failure becomes an error with a fixed text (never credentials)."""
    pkey = _load_key()
    sock = socket.create_connection((settings.JOBS_SFTP_HOST, settings.JOBS_SFTP_PORT), timeout=timeout)
    transport = paramiko.Transport(sock)
    try:
        transport.start_client(timeout=timeout)
        verify_host_key(transport.get_remote_server_key(), settings.JOBS_SFTP_HOST_KEY)    # before any credentials are sent
        _authenticate(transport, pkey)
        ...
    except SyncError:
        transport.close()
        raise
    except Exception as e:                                  # noqa: BLE001
        transport.close()
        raise SyncError(f"Verbindung fehlgeschlagen ({type(e).__name__}).") from None   # type name only, never the message text
