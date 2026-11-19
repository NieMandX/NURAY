#!/usr/bin/env python3
"""Verify and restore NURAY source archives downloaded from private storage."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import tarfile
import tempfile


def copy_and_hash(source, destination=None):
    checksum = hashlib.sha256()
    total = 0
    while block := source.read(4 * 1024 * 1024):
        checksum.update(block)
        total += len(block)
        if destination is not None:
            destination.write(block)
    return total, checksum.hexdigest()


def check_file(path, record):
    with path.open("rb") as source:
        if copy_and_hash(source) != (record["bytes"], record["sha256"]):
            raise ValueError(f"Checksum or length mismatch: {path}")


def restore_path(root, name):
    relative = PurePosixPath(name)
    if (
        relative.is_absolute()
        or not relative.parts
        or str(relative) != name
        or {"..", ".git"} & set(relative.parts)
        or "\\" in name
        or relative.parts[0] not in {"moscow-fidelity", ".local"}
    ):
        raise ValueError(f"Unexpected archive path: {name}")
    target = root / relative
    if target.resolve() != target:
        raise ValueError(f"Destination traverses a symbolic link: {target}")
    return target


def verify_or_restore(source, record, target):
    if target is not None and target.exists():
        check_file(target, record)
        return
    expected = (record["bytes"], record["sha256"])
    if target is None:
        if copy_and_hash(source) != expected:
            raise ValueError(f"Checksum mismatch: {record['path']}")
        return

    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".nuray-restore-", dir=target.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            if copy_and_hash(source, output) != expected:
                raise ValueError(f"Checksum mismatch: {record['path']}")
        os.link(temporary, target)
    finally:
        Path(temporary).unlink()


def restore(archive_dir, root, verify_only):
    manifest = json.loads((archive_dir / "manifest.json").read_text(encoding="utf-8"))
    if manifest["version"] != 1 or not manifest["archives"]:
        raise ValueError("Unsupported or empty workbench manifest")
    seen_members = set()
    for record in manifest["archives"]:
        name = record["name"]
        if Path(name).name != name or not name.endswith(".tar.gz"):
            raise ValueError(f"Invalid archive name: {name}")
        archive = archive_dir / name
        check_file(archive, record)
        with tarfile.open(archive, "r|gz") as tar:
            members = iter(tar)
            for row in record["members"]:
                member = next(members, None)
                if (
                    member is None
                    or not member.isfile()
                    or member.name != row["path"]
                    or member.size != row["bytes"]
                    or member.name in seen_members
                ):
                    raise ValueError(f"Archive member differs from manifest: {row['path']}")
                target = restore_path(root, member.name)
                with tar.extractfile(member) as source:
                    verify_or_restore(source, row, None if verify_only else target)
                seen_members.add(member.name)
            if next(members, None) is not None:
                raise ValueError(f"Unexpected extra members in {name}")
        print(f"Verified {name} ({len(record['members'])} files)", flush=True)
    print(f"{'Checked' if verify_only else 'Restored'} {len(seen_members)} files.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive_dir", type=Path, help="Directory with manifest.json and all archives")
    parser.add_argument("--destination", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    restore(args.archive_dir.resolve(), args.destination.resolve(), args.verify_only)


if __name__ == "__main__":
    main()
