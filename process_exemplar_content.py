"""Extract content previews from local exemplar files and update exemplar metadata."""

from datetime import datetime, timezone
from pathlib import Path

from project_data import load_json, save_json, taste_evidence_path

EXEMPLAR_PATH = taste_evidence_path()
MAX_PREVIEW_CHARS = 1200


def text_preview(text: str, limit: int = MAX_PREVIEW_CHARS) -> str:
    return " ".join((text or "").split())[:limit]


def extract_text_from_pdf(path: Path) -> tuple[str, dict]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    page_count = len(reader.pages)
    chunks = []
    for page in reader.pages[:5]:
        page_text = page.extract_text() or ""
        if page_text:
            chunks.append(page_text)
        if sum(len(chunk) for chunk in chunks) >= MAX_PREVIEW_CHARS * 2:
            break
    preview = text_preview("\n".join(chunks))
    return preview, {"page_count": page_count}


def extract_text_from_local_file(path: Path) -> tuple[str, dict]:
    extension = path.suffix.lower()
    if extension == ".pdf":
        return extract_text_from_pdf(path)
    if extension in {".txt", ".md", ".html", ".htm", ".url"}:
        text = path.read_text(encoding="utf-8", errors="replace")
        return text_preview(text), {}
    return "", {}


def process_exemplar(entry: dict) -> bool:
    local_path = entry.get("local_path")
    if not local_path:
        return False
    content_status = entry.get("content_status", "")
    if content_status not in {"local_file_pending", "email_attachment_pending", "extraction_failed"}:
        return False

    path = Path(local_path)
    metadata = entry.setdefault("metadata", {})
    if not path.exists():
        entry["content_status"] = "local_file_missing"
        metadata["extraction_error"] = "local file not found"
        return True

    try:
        preview, extra = extract_text_from_local_file(path)
        if preview:
            metadata["extracted_text_preview"] = preview
            metadata["extracted_text_chars"] = len(preview)
            metadata.update(extra)
            metadata["extracted_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            metadata.pop("extraction_error", None)
            entry["content_status"] = "extracted"
        else:
            entry["content_status"] = "unsupported_local_file"
            metadata["extraction_error"] = f"unsupported extension: {path.suffix.lower()}"
        return True
    except Exception as exc:
        entry["content_status"] = "extraction_failed"
        metadata["extraction_error"] = str(exc)
        return True


def main():
    exemplars = load_json(EXEMPLAR_PATH, [])
    updated = 0
    for entry in exemplars:
        if isinstance(entry, dict) and process_exemplar(entry):
            updated += 1

    save_json(EXEMPLAR_PATH, exemplars)
    print(f"Processed content for {updated} exemplar(s).")


if __name__ == "__main__":
    main()
