# Copyright (c) 2026 PitchAI. All rights reserved.
"""Search provider billing evidence through unread-safe iCloud IMAP.

Use the installed iCloud skill's credential and flag helpers. Credentials, raw
addresses, message identifiers, subjects and bodies remain in process memory.
Search all selectable folders except drafts. Export candidates, not assertions
that money was paid or that an Apple mailbox belongs to a subscription identity.
"""

from __future__ import annotations

import argparse
import datetime as dt
import email
import hashlib
import html
import imaplib
import importlib
import json
import re
import ssl
import sys
from email.policy import default
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, TypedDict, cast

if TYPE_CHECKING:
    from collections.abc import Callable
    from email.message import EmailMessage


class MailTools(Protocol):
    """Installed skill operations used without printing credential-bearing objects."""

    def load_env_file(self, path: Path) -> dict[str, str]:
        """Read the protected environment file."""
        raise NotImplementedError

    def fetch_flags(self, client: imaplib.IMAP4_SSL, uid: bytes) -> set[str]:
        """Fetch flags without changing them."""
        raise NotImplementedError


class Notice(TypedDict):
    """Allowlisted billing candidate, with no raw private message fields."""

    sent_at: str
    provider_domain: str
    source_id_sha256: str
    body_sha256: str
    exact_identity_header_matches: list[str]
    exact_identity_body_matches: list[str]
    subject_terms: list[str]
    body_terms: list[str]
    amount_mentions: list[str]
    plan_mentions: list[str]
    has_attachments: bool
    qualification: str


class Folder(TypedDict):
    """Anonymous folder search coverage."""

    folder_sha256: str
    query_counts: list[int]


class ScanResult(TypedDict):
    """Complete search coverage and candidate projection."""

    folders: list[Folder]
    messages_fetched_with_unchanged_flags: int
    candidates: list[Notice]


_SEARCHES = (
    '(SINCE "01-Nov-2025" BEFORE "07-Sep-2026" OR FROM "openai.com" SUBJECT "ChatGPT")',
    '(SINCE "01-Nov-2025" BEFORE "07-Sep-2026" FROM "apple.com" TEXT "ChatGPT")',
)
_TERMS = ("receipt", "invoice", "payment", "subscription", "cancel", "billing", "renew", "credit")
_CUTOFF = dt.datetime(2026, 9, 6, 20, 20, tzinfo=dt.UTC)


def project(message: EmailMessage, account_emails: list[tuple[str, str]]) -> Notice | None:
    """Keep dated provider candidates with anonymous amount and plan mentions.

    Returns:
        A candidate projection, or None for a nonprovider or out-of-period message.
    """
    domain = parseaddr(str(message.get("From", "")))[1].rsplit("@", 1)[-1].lower()
    if not any(domain == provider or domain.endswith("." + provider) for provider in ("openai.com", "apple.com")):
        return None
    received = parsedate_to_datetime(str(message.get("Date", "")))
    if received >= _CUTOFF or received < dt.datetime(2025, 11, 1, tzinfo=dt.UTC):
        return None
    subject = str(message.get("Subject", ""))
    body_part = message.get_body(preferencelist=("plain", "html"))
    body = cast("str", body_part.get_content()) if body_part else ""
    plain = html.unescape(re.sub(r"<[^>]*>", " ", body))
    text = " ".join((subject + " " + plain).split())
    terms = [term for term in _TERMS if re.search(term, text, re.IGNORECASE)]
    if not terms:
        return None
    header_fields = ("To", "Delivered-To", "X-Original-To")
    headers = [str(message.get(field, "")) for field in header_fields]
    addresses = getaddresses(headers)
    recipients = {address.lower() for _, address in addresses}
    return {
        "sent_at": received.isoformat(), "provider_domain": domain,
        "source_id_sha256": hashlib.sha256(str(message.get("Message-ID", body)).encode()).hexdigest(),
        "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "exact_identity_header_matches": [alias for alias, address in account_emails if address.lower() in recipients],
        "exact_identity_body_matches": [alias for alias, address in account_emails if address.lower() in body.lower()],
        "subject_terms": [term for term in _TERMS if re.search(term, subject, re.IGNORECASE)],
        "body_terms": terms,
        "amount_mentions": sorted(set(re.findall(
            r"(?:USD|EUR|GBP|\$|€|£)\s*\d[\d,.]*|\d[\d,.]*\s*(?:USD|EUR|GBP|euros?)\b", text, re.IGNORECASE,
        ))),
        "plan_mentions": sorted(set(re.findall(r"ChatGPT\s+(?:Pro|Plus|Business|Team)", text, re.IGNORECASE))),
        "has_attachments": any(part.get_content_disposition() == "attachment" for part in message.walk()),
        "qualification": "Mention detection only; payment and subscription attribution require separate review.",
    }


def search_folder(client: imaplib.IMAP4_SSL, mailbox: str) -> tuple[set[bytes], list[int]]:
    """Search a folder without changing its read state.

    Returns:
        Unique matching UIDs and per-query counts.

    Raises:
        RuntimeError: If selection or search fails.
    """
    if client.select(mailbox, readonly=True)[0] != "OK":
        message = "Read-only mailbox selection failed"
        raise RuntimeError(message)
    found: set[bytes] = set()
    counts: list[int] = []
    for query in _SEARCHES:
        status, data = client.uid("SEARCH", query)
        if status != "OK":
            message = "IMAP provider search failed"
            raise RuntimeError(message)
        results = cast("bytes", data[0] or b"").split()
        found.update(results)
        counts.append(len(results))
    return found, counts


def read_notice(client: imaplib.IMAP4_SSL, library: MailTools, uid: bytes,
                account_emails: list[tuple[str, str]]) -> Notice | None:
    """Read and project one message, verifying its flags before and after.

    Returns:
        Anonymous candidate or None when no provider notice qualifies.

    Raises:
        RuntimeError: If reading fails or flags change during verification.
    """
    before = library.fetch_flags(client, uid)
    status, data = client.uid("FETCH", uid.decode(), "(UID FLAGS BODY.PEEK[])")
    if status != "OK":
        message = "IMAP provider message read failed"
        raise RuntimeError(message)
    parts = cast("list[bytes | tuple[bytes, bytes] | None]", data)
    literal = next(part[1] for part in parts if isinstance(part, tuple))
    parsed = email.message_from_bytes(literal, policy=default)
    projection = project(parsed, account_emails)
    if library.fetch_flags(client, uid) != before:
        message = "Message flags changed during read-only verification"
        raise RuntimeError(message)
    return projection


def scan(client: imaplib.IMAP4_SSL, library: MailTools, account_emails: list[tuple[str, str]]) -> ScanResult:
    """Search and fetch through EXAMINE and BODY.PEEK, retaining no mailbox names.

    Returns:
        Anonymous folder coverage, unique candidates and flag verification counts.

    Raises:
        RuntimeError: If a listing, search, read or flag verification fails.
        TypeError: If the server returns an unexpected folder record type.
    """
    status, folders = client.list()
    if status != "OK":
        message = "IMAP folder listing failed"
        raise RuntimeError(message)
    coverage: list[Folder] = []
    candidates: dict[str, Notice] = {}
    fetched = 0
    for folder in folders:
        if not isinstance(folder, bytes):
            message = "Unexpected IMAP folder record type"
            raise TypeError(message)
        match = re.fullmatch(rb'\(([^)]*)\) "[^"]*" (.+)', folder)
        if not match:
            message = "Unrecognized IMAP folder listing syntax"
            raise RuntimeError(message)
        if b"\\Noselect" in match[1] or b"\\Drafts" in match[1] or match[2] == b'"Drafts"':
            continue
        found, counts = search_folder(client, match[2].decode())
        coverage.append({"folder_sha256": hashlib.sha256(match[2]).hexdigest(), "query_counts": counts})
        for uid in sorted(found):
            projection = read_notice(client, library, uid, account_emails)
            if projection is not None:
                candidates[projection["source_id_sha256"]] = projection
            fetched += 1
    return {"folders": coverage, "messages_fetched_with_unchanged_flags": fetched,
            "candidates": sorted(candidates.values(), key=lambda row: str(row["sent_at"]))}


def main() -> None:
    """Use existing protected credentials and print only the anonymous projection."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skill-directory", type=Path, required=True)
    args = parser.parse_args()
    skill = cast("Path", args.skill_directory)
    sys.path.insert(0, str(skill / "scripts"))
    library = cast("MailTools", cast("object", importlib.import_module("icloud_mail")))
    settings = library.load_env_file(Path("/root/.config/pitchai/icloud_mail.env"))
    identities = cast("Callable[[Path, Path, str], list[tuple[str, str]]]",
                      importlib.import_module(".extract_billing_notices", __package__).identities)
    account_emails = identities(Path("/srv/codex-usage-dashboard/usage-history.sqlite3"),
                               Path("/srv/auth-token-server/data/accounts"), _CUTOFF.isoformat())
    with imaplib.IMAP4_SSL("imap.mail.me.com", 993, ssl_context=ssl.create_default_context(), timeout=30) as client:
        client.login(settings["ICLOUD_MAIL_USERNAME"], settings["ICLOUD_MAIL_APP_PASSWORD"])
        result = scan(client, library, account_emails)
        client.logout()
    sys.stdout.write(json.dumps({"schema": 1, "cutoff_exclusive": _CUTOFF.isoformat(),
                                 "searches": _SEARCHES, "read_only": True, **result}, indent=2) + "\n")


if __name__ == "__main__":
    main()
