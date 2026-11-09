"""Local Dropbox taste ingestion, run daily by DailyReadsDropboxTasteSync.

Pull, run the three ingestion steps, then commit and push the taste files. The
commit is refused if it would lose evidence records (#685): on 2026-10-19 this
job committed taste_evidence.json as `[]`, 627 lines deleted.
"""

import json
import subprocess
import sys

EVIDENCE_PATH = "taste_evidence.json"
TRACKED_PATHS = [EVIDENCE_PATH, "learned_preferences.json", "learned_preferences.md"]
INGEST_STEPS = [
    "process_dropbox_exemplars.py",
    "process_exemplar_content.py",
    "preference_learning.py",
]
EXIT_EVIDENCE_LOSS = 3


def _records(text: str):
    """The parsed list of records, or None if the text is not a JSON list."""
    try:
        data = json.loads(text)
    except ValueError:
        return None
    return data if isinstance(data, list) else None


def _ids(records: list) -> set:
    return {r.get("id") for r in records if isinstance(r, dict) and r.get("id")}


def evidence_loss(head_text: str | None, working_text: str) -> str | None:
    """Why committing working_text over head_text would lose evidence, or None.

    Compares ids as well as length: a rewrite that keeps the count but replaces
    the records loses just as much. With no usable HEAD copy there is nothing to
    lose, so the working file only has to parse.
    """
    working = _records(working_text)
    if working is None:
        return f"{EVIDENCE_PATH} is not a readable JSON list"
    head = _records(head_text) if head_text is not None else None
    if head is None:
        return None
    if len(working) < len(head):
        return f"{EVIDENCE_PATH} shrank from {len(head)} to {len(working)} records"
    missing = sorted(_ids(head) - _ids(working))
    if missing:
        return f"{EVIDENCE_PATH} lost {len(missing)} record id(s), e.g. {missing[:3]}"
    return None


def head_evidence() -> str | None:
    r = subprocess.run(["git", "show", f"HEAD:{EVIDENCE_PATH}"], capture_output=True)
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", "replace")


def working_evidence() -> str:
    with open(EVIDENCE_PATH, "rb") as f:
        return f.read().decode("utf-8", "replace")


def main() -> int:
    # Sync with remote first so local taste ingestion stacks on top of the latest
    # GitHub Actions workflow output instead of forking history. Without this the
    # local 'taste ingestion' commits and the remote 'Daily reads' commits diverge
    # every day because they touch the same learned_preferences files.
    subprocess.run(["git", "fetch", "origin"], check=False)
    r = subprocess.run(["git", "pull", "--rebase", "--autostash", "-X", "ours", "origin", "main"])
    if r.returncode != 0:
        print("git pull --rebase failed; aborting taste ingestion to avoid divergence")
        subprocess.run(["git", "rebase", "--abort"], check=False)
        return r.returncode

    for step in INGEST_STEPS:
        r = subprocess.run([sys.executable, step])
        if r.returncode != 0:
            return r.returncode

    r = subprocess.run(["git", "diff", "--quiet", *TRACKED_PATHS])
    if r.returncode == 0:
        return 0

    reason = evidence_loss(head_evidence(), working_evidence())
    if reason:
        print(f"REFUSING TO COMMIT: {reason}. Nothing was staged or pushed.")
        return EXIT_EVIDENCE_LOSS

    subprocess.run(["git", "add", *TRACKED_PATHS])
    subprocess.run(["git", "commit", "-m", "Local Dropbox taste ingestion"])
    subprocess.run(["git", "push"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
