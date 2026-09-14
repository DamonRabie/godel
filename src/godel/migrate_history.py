"""Verified, repeatable transfer of legacy histories into MLflow."""

import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import time
import zipfile

from .history import import_history, snapshot_native
from .storage import Store, atomic_json
from .trace_delivery import flush


def migrate(home):
    home = Path(home).resolve()
    archive_dir = home / ".godel/backups"
    archive_dir.mkdir(exist_ok=True)
    stamp = str(time.time_ns())
    backup = archive_dir / f"state-before-traces-{stamp}.sqlite3"
    with (
        sqlite3.connect(home / ".godel/state.sqlite3") as source,
        sqlite3.connect(backup) as target,
    ):
        source.backup(target)
    backup.chmod(0o600)
    journals = []
    archive_path = archive_dir / f"legacy-journals-{stamp}.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((home / "projects").glob("*/.godel/history/*.jsonl")):
            content = path.read_bytes()
            archive.writestr(str(path.relative_to(home)), content)
            journals.append((path, hashlib.sha256(content).hexdigest(), content))
    archive_path.chmod(0o600)
    result = import_history(home)
    for path in sorted((home / "projects").glob("*/.godel/sessions/*.jsonl")):
        try:
            with path.open() as stream:
                header = json.loads(stream.readline())
            snapshot_native(path.parents[2], header["id"], path)
        except (ValueError, KeyError) as error:
            result["warnings"].append(
                f"Native cache retained without migration: {path.name}: {type(error).__name__}"
            )
    store = Store(home)
    while True:
        batch = flush(home, force=True, limit=500)
        with store.connection() as db:
            pending = db.execute("SELECT count(*) FROM pending_history").fetchone()[0]
            errors = db.execute(
                "SELECT id,error FROM pending_history WHERE error IS NOT NULL LIMIT 5"
            ).fetchall()
        if not pending:
            break
        if errors:
            return {
                **result,
                "complete": False,
                "pending": pending,
                "errors": errors,
                "backup": str(backup),
            }
        if not batch["delivered"]:
            time.sleep(0.2)
    archived = 0
    with zipfile.ZipFile(archive_path) as archive:
        for path, digest, content in journals:
            ids = []
            try:
                for line in content.splitlines():
                    ids.append(json.loads(line)["id"])
            except (ValueError, KeyError, TypeError):
                continue  # Retain malformed originals; never discard an unparsed tail.
            with store.connection() as db:
                verified = all(
                    db.execute("SELECT delivered FROM history_refs WHERE id=?", (id_,)).fetchone()
                    == (1,)
                    for id_ in ids
                )
            if (
                verified
                and path.exists()
                and hashlib.sha256(path.read_bytes()).hexdigest() == digest
                and archive.read(str(path.relative_to(home))) == content
            ):
                path.unlink()
                archived += 1
    with store.connection() as db:
        remaining_legacy = db.execute("SELECT count(*) FROM events").fetchone()[0]
        total = db.execute("SELECT count(*) FROM history_refs WHERE delivered=1").fetchone()[0]
    result.update(
        complete=remaining_legacy == 0,
        delivered=total,
        journalsArchived=archived,
        pending=0,
        backup=str(backup),
        journalBackup=str(archive_path),
        note="Native Pi files are a rebuildable runtime cache; no Godel history reads use them.",
    )
    atomic_json(home / ".godel/history-migration.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--home", type=Path, required=True)
    result = migrate(parser.parse_args().home)
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result["complete"] else 1)
