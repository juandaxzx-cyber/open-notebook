"""Guard the production deploy overlay (PR-BT4).

Parses ``docker-compose.yml`` + ``docker-compose.prod.yml`` directly (pure
YAML, no Docker — same DX1 precedent as ``test_compose.py``) and asserts
the merged intent: Caddy is the only service publishing host ports, every
port surrealdb/open_notebook/tutor publish in the base file is cleared by
the overlay, the Caddyfile is referenced and proxies to the tutor service.

Compose-merge mechanism note: ``ports`` is a "unique resource" sequence
(compose-spec merge key ``{ip, target, published, protocol}``) — Compose
APPENDS override entries that don't collide with a base entry, it does not
replace the list. A bare ``ports: []`` override therefore publishes
nothing new and silently leaves every base port in place; it does NOT
clear them. The only mechanism that reliably clears an inherited list is
the custom ``!reset`` YAML tag (compose-spec "Reset value", Compose CLI
v2.24.4+): a value must still be present syntactically but is ignored, and
the attribute resets to its type's default (``null``/``[]``). The overlay
therefore uses ``ports: !reset []``, not a plain ``ports: []``.

PyYAML has no built-in constructor for ``!reset`` (``yaml.safe_load``
raises ``ConstructorError`` on it — asserted below), so this test registers
one purely to make the file loadable for assertions; it mirrors what
Compose itself does (reset the tagged attribute to its default), it does
not change real merge behavior.

PR-BT4b extends this file (same pure-YAML/file-assertion pattern, no
Docker) to also guard the ``backup`` service: present, correct image,
``deploy/backup.sh`` + ``./backups`` mounted, no published ports, and the
two new env var names (``TUTOR_BACKUP_INTERVAL_HOURS``,
``TUTOR_BACKUP_KEEP``) referenced in ``.env.production.example``.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml

_ROOT = Path(__file__).resolve().parent.parent
_BASE_PATH = _ROOT / "docker-compose.yml"
_PROD_PATH = _ROOT / "docker-compose.prod.yml"
_CADDYFILE_PATH = _ROOT / "Caddyfile"
_BACKUP_SCRIPT_PATH = _ROOT / "deploy" / "backup.sh"
_ENV_PROD_EXAMPLE_PATH = _ROOT / ".env.production.example"

_CLEARED_SERVICES = ("surrealdb", "open_notebook", "tutor")


class _ResetTagLoader(yaml.SafeLoader):
    """SafeLoader extended with a constructor for compose-spec's ``!reset``."""


def _construct_reset(loader: yaml.SafeLoader, node: yaml.Node) -> list[Any]:
    # compose-spec: the tagged value is ignored; the attribute resets to
    # its type's default. Every use in this repo tags a `ports` sequence,
    # so `[]` is the faithful stand-in for assertion purposes.
    return []


_ResetTagLoader.add_constructor("!reset", _construct_reset)


def _load(path: Path) -> dict[str, Any]:
    data = yaml.load(path.read_text(encoding="utf-8"), Loader=_ResetTagLoader)
    assert isinstance(data, dict)
    return data


def _base_services() -> dict[str, Any]:
    return dict(_load(_BASE_PATH)["services"])


def _prod_services() -> dict[str, Any]:
    return dict(_load(_PROD_PATH)["services"])


def test_overlay_file_exists_and_parses() -> None:
    assert _PROD_PATH.is_file()
    assert "services" in _load(_PROD_PATH)


def test_plain_safe_load_cannot_parse_reset_tag() -> None:
    # Documents *why* the custom loader above exists, and pins the
    # mechanism: if this ever stops raising, PyYAML gained native !reset
    # support and the loader class could be simplified.
    with pytest.raises(yaml.constructor.ConstructorError):
        yaml.safe_load(_PROD_PATH.read_text(encoding="utf-8"))


def test_caddy_service_present_and_publishes_80_443() -> None:
    caddy = _prod_services()["caddy"]
    assert str(caddy["image"]).startswith("caddy:")
    ports = caddy["ports"]
    assert "80:80" in ports
    assert "443:443" in ports


def test_caddy_mounts_the_caddyfile() -> None:
    caddy = _prod_services()["caddy"]
    volumes = caddy["volumes"]
    assert any("Caddyfile" in str(v) for v in volumes)
    assert _CADDYFILE_PATH.is_file()


def test_caddy_has_data_and_config_volumes() -> None:
    caddy = _prod_services()["caddy"]
    volumes_text = " ".join(str(v) for v in caddy["volumes"])
    assert "caddy_data" in volumes_text
    assert "caddy_config" in volumes_text
    assert "caddy_data" in _load(_PROD_PATH).get("volumes", {})
    assert "caddy_config" in _load(_PROD_PATH).get("volumes", {})


def test_caddy_depends_on_tutor() -> None:
    caddy = _prod_services()["caddy"]
    assert "tutor" in caddy.get("depends_on", [])


def test_overlay_clears_ports_for_internal_services() -> None:
    prod = _prod_services()
    for name in _CLEARED_SERVICES:
        assert name in prod, f"{name} must be present in the overlay to reset its ports"
        assert "ports" in prod[name], f"{name} must reset ports in the overlay"
        assert prod[name]["ports"] == [], (
            f"{name} ports must be cleared, got {prod[name]['ports']!r}"
        )


def test_overlay_uses_the_reset_tag_not_a_bare_empty_list() -> None:
    # A bare `ports: []` would be silently absorbed by Compose's sequence-
    # merge/unique-resource rules and leave the base ports intact (see
    # module docstring) — the raw YAML text must carry the `!reset` tag on
    # each cleared service for the clearing to actually take effect at
    # `docker compose` merge time.
    text = _PROD_PATH.read_text(encoding="utf-8")
    assert text.count("!reset") >= len(_CLEARED_SERVICES)


def test_base_file_actually_publishes_the_ports_being_cleared() -> None:
    # Sanity check: the overlay is clearing something real, not a no-op —
    # if the base file ever stopped publishing ports here, this overlay's
    # `!reset` would be dead weight and the invariant untested.
    base = _base_services()
    for name in _CLEARED_SERVICES:
        assert base[name].get("ports"), f"expected base {name} to publish ports"


def test_no_service_other_than_caddy_publishes_ports_in_the_merged_model() -> None:
    # Simulates the merge outcome directly: for every service the overlay
    # doesn't mention (there are none besides the four here), the base
    # ports would still apply — assert explicitly there ARE no such gaps.
    base = _base_services()
    prod = _prod_services()
    for name, service in base.items():
        base_ports = service.get("ports")
        if not base_ports:
            continue
        assert name in prod, (
            f"base service '{name}' publishes ports but the overlay never addresses it"
        )
        assert prod[name].get("ports") == [], (
            f"'{name}' publishes ports in the base file and the overlay doesn't clear them"
        )


def test_caddyfile_references_tutor_domain_and_proxies_to_tutor() -> None:
    content = _CADDYFILE_PATH.read_text(encoding="utf-8")
    assert "TUTOR_DOMAIN" in content
    assert "reverse_proxy tutor:5056" in content


def test_tutor_stays_reachable_internally_after_overlay() -> None:
    # tutor keeps its container port/healthcheck (Dockerfile.tutor EXPOSE
    # 5056, docker-compose.yml's own service definition) and stays on the
    # compose network — only the *host* publish is cleared by the overlay,
    # so Caddy (also on the network, same docker compose project) can still
    # reach it by service name. Assert the base wiring the overlay leaves
    # untouched, plus the Caddyfile's proxy target encoding exactly that.
    base_tutor = _base_services()["tutor"]
    assert base_tutor["build"]["dockerfile"] == "Dockerfile.tutor"
    content = _CADDYFILE_PATH.read_text(encoding="utf-8")
    assert "tutor:5056" in content


def test_overlay_does_not_republish_any_on_or_db_port() -> None:
    # Belt-and-suspenders against the exact regression this PR exists to
    # prevent: no literal ON/DB host port shows up anywhere in the overlay
    # outside of a `!reset` clearing statement.
    text = _PROD_PATH.read_text(encoding="utf-8")
    for leaked_port in ("8502:8502", "5055:5055", "8000:8000"):
        assert leaked_port not in text


def test_backup_service_present_and_uses_surrealdb_image() -> None:
    # Contract: "uses the same SurrealDB image (has the surreal CLI)" — the
    # backup service reuses the exact image tag the base `surrealdb`
    # service pins, so it always ships the same `/surreal` CLI version.
    prod = _prod_services()
    base = _base_services()
    assert "backup" in prod
    assert prod["backup"]["image"] == base["surrealdb"]["image"]


def test_backup_service_publishes_no_ports() -> None:
    backup = _prod_services()["backup"]
    # The service never appears in the base compose file, so unlike
    # surrealdb/open_notebook/tutor it has no inherited ports to `!reset` —
    # it simply must never declare a `ports:` key of its own.
    assert "ports" not in backup


def test_backup_mounts_the_script_and_the_backups_directory() -> None:
    backup = _prod_services()["backup"]
    volumes_text = " ".join(str(v) for v in backup["volumes"])
    assert "deploy/backup.sh" in volumes_text
    assert "/backup.sh" in volumes_text
    assert "./backups" in volumes_text or "backups:/backups" in volumes_text
    assert _BACKUP_SCRIPT_PATH.is_file()


def test_backup_script_is_executable_posix_sh_with_lf_endings() -> None:
    import os
    import stat

    content = _BACKUP_SCRIPT_PATH.read_bytes()
    assert content.startswith(b"#!/bin/sh")
    assert b"\r\n" not in content, "backup.sh must use LF line endings"
    mode = os.stat(_BACKUP_SCRIPT_PATH).st_mode
    assert mode & stat.S_IXUSR, (
        "backup.sh should be executable (docker exec backup /backup.sh)"
    )


def test_backup_script_supports_on_demand_single_pass_and_loop_mode() -> None:
    text = _BACKUP_SCRIPT_PATH.read_text(encoding="utf-8")
    # On-demand path (contract + deploy guide): `docker compose ... exec
    # backup /backup.sh` with no arguments must NOT loop forever — it has
    # to be a single pass that returns control to the caller.
    assert "--loop" in text
    assert "run_once" in text


def test_backup_service_entrypoint_runs_the_script_in_loop_mode() -> None:
    backup = _prod_services()["backup"]
    entrypoint = backup.get("entrypoint")
    assert entrypoint is not None
    entrypoint_text = " ".join(str(part) for part in entrypoint)
    assert "/backup.sh" in entrypoint_text
    assert "--loop" in entrypoint_text


def test_backup_script_exports_both_databases_and_rotates() -> None:
    text = _BACKUP_SCRIPT_PATH.read_text(encoding="utf-8")
    # Both databases the stack uses (PR-C1: OpenNotebook's own +
    # tutor's `atenea`, same namespace, different database).
    assert "SURREAL_DATABASE" in text
    assert "TUTOR_SURREAL_DATABASE" in text
    assert "surreal export" in text
    assert "TUTOR_BACKUP_KEEP" in text
    assert "TUTOR_BACKUP_INTERVAL_HOURS" in text


def test_backup_service_depends_on_surrealdb() -> None:
    backup = _prod_services()["backup"]
    assert "surrealdb" in backup.get("depends_on", [])


def test_env_production_example_documents_backup_env_defaults() -> None:
    content = _ENV_PROD_EXAMPLE_PATH.read_text(encoding="utf-8")
    assert "TUTOR_BACKUP_INTERVAL_HOURS=" in content
    assert "TUTOR_BACKUP_KEEP=" in content
    # Names-only: contract forbids real values in this file (never secrets,
    # and these aren't secrets either, but the convention is names/defaults
    # in comments, blank `=`).
    assert "TUTOR_BACKUP_INTERVAL_HOURS=24" not in content
    assert "TUTOR_BACKUP_KEEP=14" not in content
