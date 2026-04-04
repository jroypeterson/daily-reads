"""Harvest external taste exemplars from Gmail alias and label intake paths."""

import base64
import os
import re
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr

from gmail_reader import clean_url, get_gmail_service, is_probable_article_url
from project_data import evidence_id_for, load_json, save_json, taste_evidence_path

EXEMPLAR_PATH = taste_evidence_path()
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
ATTACHMENT_TYPES = {".pdf", ".txt", ".md", ".html", ".htm", ".docx", ".doc"}


def configured_taste_alias() -> str:
    return os.environ.get("TASTE_EMAIL_ALIAS") or "jroypeterson+taste@gmail.com"


def configured_taste_label() -> str:
    return os.environ.get("TASTE_GMAIL_LABEL") or "taste"


def header_map(payload: dict) -> dict:
    return {
        header["name"].lower(): header["value"]
        for header in payload.get("headers", [])
        if isinstance(header, dict) and header.get("name")
    }


def decode_body_data(data: str) -> str:
    if not data:
        return ""
    return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")


def extract_text_bodies(payload: dict) -> list[str]:
    bodies = []
    mime_type = payload.get("mimeType")
    if mime_type == "text/plain":
        bodies.append(decode_body_data(payload.get("body", {}).get("data", "")))
    for part in payload.get("parts", []):
        bodies.extend(extract_text_bodies(part))
    return bodies


def extract_attachment_parts(payload: dict) -> list[dict]:
    attachments = []
    filename = (payload.get("filename") or "").strip()
    body = payload.get("body", {})
    attachment_id = body.get("attachmentId")
    if filename and attachment_id:
        attachments.append(
            {
                "filename": filename,
                "mime_type": payload.get("mimeType", ""),
                "attachment_id": attachment_id,
            }
        )
    for part in payload.get("parts", []):
        attachments.extend(extract_attachment_parts(part))
    return attachments


def extract_candidate_urls(text: str) -> list[str]:
    urls = []
    for match in URL_RE.findall(text or ""):
        cleaned = clean_url(match.rstrip(").,>"))
        if is_probable_article_url(cleaned) and cleaned not in urls:
            urls.append(cleaned)
    return urls


def extract_note(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    explicit = re.search(r"why i liked it:\s*(.+)", text, re.IGNORECASE | re.DOTALL)
    if explicit:
        return explicit.group(1).strip()[:500]
    redacted = URL_RE.sub("", text)
    redacted = re.sub(r"\s+", " ", redacted).strip(" -:\n\t")
    return redacted[:500]


def message_query(hours_back: int) -> str:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
    date_query = cutoff.strftime("%Y/%m/%d")
    return f"after:{date_query} (to:{configured_taste_alias()} OR label:{configured_taste_label()})"


def build_url_exemplar(message: dict, headers: dict, url: str, note: str) -> dict:
    subject = headers.get("subject", "(no subject)")
    sender_raw = headers.get("from", "")
    _, sender_email = parseaddr(sender_raw)
    message_id = message.get("id", "")
    return {
        "id": evidence_id_for(f"email-url|{message_id}|{url}"),
        "kind": "positive_exemplar",
        "source_channel": "email",
        "title": subject,
        "url": url,
        "local_path": "",
        "note": note,
        "score": None,
        "content_status": "unfetched",
        "metadata": {
            "message_id": message_id,
            "subject": subject,
            "sender": sender_raw,
            "sender_email": sender_email.lower(),
            "label_ids": message.get("labelIds", []),
        },
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def build_attachment_exemplar(message: dict, headers: dict, attachment: dict, note: str) -> dict:
    subject = headers.get("subject", "(no subject)")
    sender_raw = headers.get("from", "")
    _, sender_email = parseaddr(sender_raw)
    message_id = message.get("id", "")
    filename = attachment.get("filename", "")
    return {
        "id": evidence_id_for(f"email-attachment|{message_id}|{filename}"),
        "kind": "positive_exemplar",
        "source_channel": "email",
        "title": subject or filename or "(attachment)",
        "url": "",
        "local_path": "",
        "note": note,
        "score": None,
        "content_status": "email_attachment_pending",
        "metadata": {
            "message_id": message_id,
            "subject": subject,
            "sender": sender_raw,
            "sender_email": sender_email.lower(),
            "label_ids": message.get("labelIds", []),
            "filename": filename,
            "mime_type": attachment.get("mime_type", ""),
            "attachment_id": attachment.get("attachment_id", ""),
        },
        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def harvest_messages(service, hours_back: int = 24 * 14) -> list[dict]:
    query = message_query(hours_back)
    response = service.users().messages().list(userId="me", q=query, maxResults=100).execute()
    return response.get("messages", [])


def main():
    print("=" * 60)
    print("  EMAIL EXEMPLAR CHECK")
    print("=" * 60)

    try:
        service = get_gmail_service()
    except Exception as exc:
        print(f"Gmail auth failed: {exc}")
        return

    messages = harvest_messages(service)
    if not messages:
        print("No exemplar emails found.")
        return

    exemplars = load_json(EXEMPLAR_PATH, [])
    existing_ids = {entry.get("id") for entry in exemplars if isinstance(entry, dict)}
    processed = 0

    for message_stub in messages:
        message = service.users().messages().get(
            userId="me", id=message_stub["id"], format="full"
        ).execute()
        headers = header_map(message.get("payload", {}))
        text = "\n\n".join(part for part in extract_text_bodies(message.get("payload", {})) if part)
        text = text or message.get("snippet", "")
        urls = extract_candidate_urls(text)
        note = extract_note(text)

        for url in urls:
            exemplar = build_url_exemplar(message, headers, url, note)
            if exemplar["id"] in existing_ids:
                continue
            exemplars.append(exemplar)
            existing_ids.add(exemplar["id"])
            processed += 1
            print(f"  Recorded URL exemplar: {url}")

        for attachment in extract_attachment_parts(message.get("payload", {})):
            extension = os.path.splitext(attachment.get("filename", ""))[1].lower()
            if extension and extension not in ATTACHMENT_TYPES:
                continue
            exemplar = build_attachment_exemplar(message, headers, attachment, note)
            if exemplar["id"] in existing_ids:
                continue
            exemplars.append(exemplar)
            existing_ids.add(exemplar["id"])
            processed += 1
            print(f"  Recorded attachment exemplar: {attachment.get('filename', '(unnamed)')}")

    save_json(EXEMPLAR_PATH, exemplars)
    print(f"Processed {processed} exemplar entries from {len(messages)} email(s).")


if __name__ == "__main__":
    main()
