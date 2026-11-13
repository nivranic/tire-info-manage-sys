"""Explicit PostgreSQL connections for the authenticated governance workstation CLI."""
import ipaddress
import os
from pathlib import Path
import re

from sqlalchemy import create_engine, event
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

from .external_fact_governance import GovernanceError


def _environment():
    # libpq services, hostaddr, options and credentials must not override the
    # reviewed profile. Do not log names/values or mutate the caller's environment.
    if any(key.upper().startswith("PG") and value for key, value in os.environ.items()):
        raise GovernanceError("postgres_environment_unsupported")


def postgres_connect_args(profile):
    """Validate a closed, credential-free profile before prompting or connecting."""
    keys = {"schema", "host", "port", "database", "user", "sslmode", "sslrootcert"}
    def invalid():
        raise GovernanceError("postgres_profile_invalid")

    if type(profile) is not dict or profile.keys() != keys or profile["schema"] != "external-fact-postgres@1":
        invalid()
    for key in ("database", "user"):
        if type(profile[key]) is not str or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,62}", profile[key]) is None:
            invalid()
    port, host = profile["port"], profile["host"]
    if type(port) is not int or not 1 <= port <= 65535 or type(host) is not str or len(host) > 253:
        invalid()
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
        if re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*", host) is None:
            invalid()
    else:
        if host != str(address) or "%" in host:
            invalid()
    mode, root = profile["sslmode"], profile["sslrootcert"]
    if mode == "disable":
        if address is None or not address.is_loopback or root is not None:
            invalid()
    elif mode == "verify-full":
        if type(root) is not str:
            invalid()
        try:
            path = Path(root)
            if not path.is_absolute() or path.is_symlink() or not path.is_file():
                invalid()
        except (OSError, ValueError):
            invalid()
    else:
        invalid()
    _environment()
    import psycopg
    supported = {item.keyword.decode("ascii") for item in psycopg.pq.Conninfo.get_defaults()}
    if not {"sslcertmode", "require_auth", "gssencmode", "channel_binding"}.issubset(supported):
        raise GovernanceError("postgres_client_unsupported")
    return {
        "host": host, "port": port, "dbname": profile["database"], "user": profile["user"],
        "sslmode": mode, **({"sslrootcert": root} if root is not None else {}),
        "sslcertmode": "disable", "gssencmode": "disable", "require_auth": "scram-sha-256",
        "channel_binding": "require" if mode == "verify-full" else "disable",
        "connect_timeout": 5, "client_encoding": "UTF8", "application_name": "tire_governance_cli",
        "options": "-c search_path=pg_catalog,public -c lock_timeout=2000 -c statement_timeout=5000 "
                   "-c idle_in_transaction_session_timeout=15000",
    }


def postgres_engine(parameters, password):
    """No default target, DDL, pooling, implicit credentials or reconnect retry."""
    _environment()
    if type(password) is not str or not password or len(password) > 1024 or "\x00" in password:
        raise GovernanceError("postgres_authentication_required")
    engine = create_engine(URL.create("postgresql+psycopg"),
        connect_args={**parameters, "password": password}, poolclass=NullPool,
        isolation_level="READ COMMITTED", hide_parameters=True)

    @event.listens_for(engine, "do_connect")
    def check_environment(_dialect, _record, _args, _params):
        _environment()
    return engine
