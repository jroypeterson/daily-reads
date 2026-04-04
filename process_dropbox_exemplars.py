"""Harvest local Dropbox taste exemplars into the unified exemplar store."""

import hashlib
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from gmail_reader import clean_url, is_probable_article_url
from project_data import evidence_id_for, load_json, save_json, taste_evidence_path

EXEMPLAR_PATH = taste_evidence_path()
DEFAULT_DROPBOX_TASTE_DIR = Path(r"C:\Users\jroyp\Dropbox\Claude Folder\daily-reads-taste-samples")
ARCHIVE_SUBDIR = "Incorporated into taste preferences"
SUPPORTED_TEXT_EXTENSIONS = {".txt", ".md", ".url", ".html", ".htm"}
SUPPORTED_FILE_EXTENSIONS = {".pdf", ".doc", ".docx"}
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


def configured_dropbox_dir() -> Path | None:
    value = os.environ.get("DROPBOX_TASTE_DIR")
    if value:
        return Path(value).expanduser()
    return DEFAULT_DROPBOX_TASTE_DIR


def archive_dir(root: Path) -> Path:
    return root / ARCHIVE_SUBDIR


def file_sha1(path: Path) -> str:
    digest = hashlib.sha1()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_text_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def extract_url(text: str) -> str:
    for match in URL_RE.findall(text or ""):
        cleaned = clean_url(match.rstrip(").,>"))
        if is_probable_article_url(cleaned):
            return cleaned
    if text.strip().startswith("[InternetShortcut]"):
        for line in text.splitlines():
            if line.startswith("URL="):
                cleaned = clean_url(line.split("=", 1)[1].strip())
                if is_probable_article_url(cleaned):
                    return cleaned
    return ""


def read_sidecar_note(path: Path) -> str:
    note_path = Path(str(path) + ".note.txt")
    if not note_path.exists():
        return ""
    return read_text_file(note_path).strip()[:500]


def build_exemplar(path: Path, root: Path) -> dict | None:
    relpath = str(path.relative_to(root))
    note = read_sidecar_note(path)
    extension = path.suffix.lower()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    if extension in SUPPORTED_TEXT_EXTENSIONS:
        text = read_text_file(path)
        url = extract_url(text)
        if url:
            return {
                "id": evidence_id_for(f"dropbox-url|{url}"),
                "kind": "positive_exemplar",
                "source_channel": "dropbox",
                "title": path.stem,
                "url": url,
                "local_path": str(path),
                "note": note,
                "score": None,
                "content_status": "unfetched",
                "metadata": {
                    "dropbox_relpath": relpath,
                    "file_hash": file_sha1(path),
                    "mime_type": "text/plain",
                },
                "created_at": timestamp,
            }
        if not note:
            note = re.sub(r"\s+", " ", text).strip()[:500]

    if extension in SUPPORTED_FILE_EXTENSIONS or extension in SUPPORTED_TEXT_EXTENSIONS:
        return {
            "id": evidence_id_for(f"dropbox-file|{file_sha1(path)}"),
            "kind": "positive_exemplar",
            "source_channel": "dropbox",
            "title": path.stem,
            "url": "",
            "local_path": str(path),
            "note": note,
            "score": None,
            "content_status": "local_file_pending",
            "metadata": {
                "dropbox_relpath": relpath,
                "file_hash": file_sha1(path),
                "mime_type": "",
            },
            "created_at": timestamp,
        }

    return None


def archive_processed_file(path: Path, root: Path) -> Path:
    destination_dir = archive_dir(root)
    destination_dir.mkdir(parents=True, exist_ok=True)
    destination = destination_dir / path.name
    counter = 2
    while destination.exists():
        destination = destination_dir / f"{path.stem}-{counter}{path.suffix}"
        counter += 1
    moved_path = Path(shutil.move(str(path), str(destination)))

    note_path = Path(str(path) + ".note.txt")
    if note_path.exists():
        moved_note = destination_dir / (moved_path.name + ".note.txt")
        note_counter = 2
        while moved_note.exists():
            moved_note = destination_dir / (f"{moved_path.stem}-{note_counter}{moved_path.suffix}.note.txt")
            note_counter += 1
        shutil.move(str(note_path), str(moved_note))

    return moved_path


def main():
    print("=" * 60)
    print("  DROPBOX EXEMPLAR CHECK")
    print("=" * 60)

    root = configured_dropbox_dir()
    if not root:
        print("No DROPBOX_TASTE_DIR set — skipping Dropbox exemplar ingestion.")
        return
    if not root.exists():
        print(f"Configured Dropbox exemplar directory does not exist: {root}")
        return

    exemplars = load_json(EXEMPLAR_PATH, [])
    existing_ids = {entry.get("id") for entry in exemplars if isinstance(entry, dict)}
    processed = 0

    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        if archive_dir(root) in path.parents:
            continue
        if path.name.endswith(".note.txt"):
            continue
        exemplar = build_exemplar(path, root)
        if not exemplar:
            continue
        archived_path = archive_processed_file(path, root)
        exemplar["local_path"] = str(archived_path)
        exemplar["metadata"]["dropbox_relpath"] = str(archived_path.relative_to(root))
        if exemplar["id"] in existing_ids:
            continue
        exemplars.append(exemplar)
        existing_ids.add(exemplar["id"])
        processed += 1
        print(f"  Recorded Dropbox exemplar: {archived_path.name}")

    save_json(EXEMPLAR_PATH, exemplars)
    print(f"Processed {processed} Dropbox exemplar(s).")


if __name__ == "__main__":
    main()
