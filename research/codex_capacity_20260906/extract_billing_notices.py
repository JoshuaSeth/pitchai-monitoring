# Copyright (c) 2026 PitchAI. All rights reserved.
"""Search exact subscription mailboxes through read-only Microsoft Graph calls.

Run on the broker host, piping the approved M365 token minter JSON to stdin. Stored identity
claims identify mailbox addresses locally, but no token, address, subject,
message body or invoice identifier is exported. Amount/date mentions are not
classified as paid invoices automatically. No mailbox read flags are changed.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.client
import json
import operator
import re
import sqlite3
import sys
import urllib.parse
from contextlib import closing
from pathlib import Path
from typing import TYPE_CHECKING, NotRequired, TypedDict, cast

from .input_boundary import InputFailure

if TYPE_CHECKING:
    from collections.abc import Mapping


class Address(TypedDict):
    """Address used only for an exact in-memory recipient comparison."""

    address: str


class Recipient(TypedDict):
    """Graph recipient boundary."""

    emailAddress: Address


class Body(TypedDict):
    """Text representation requested from Graph."""

    content: str


class Message(TypedDict):
    """Only fields needed to classify provider notices."""

    id: str
    receivedDateTime: str
    subject: str
    body: Body
    toRecipients: list[Recipient]
    hasAttachments: bool


class Notice(TypedDict, total=False):
    """Anonymous provider evidence, including explicit missing metadata."""

    received_at: str
    provider_domain: str
    source_id_sha256: str
    body_sha256: str
    direct_recipient_match: bool
    subject_terms: list[str]
    has_attachments: bool
    amount_mentions: list[str]
    plan_mentions: list[str]
    date_mentions: list[str]
    status: str


class AccountSearch(TypedDict):
    """Bounded mailbox search result or a specific access limitation."""

    account: str
    exact_identity_email_match: bool
    status: str
    query: NotRequired[str]
    error: NotRequired[str]
    query_counts_before_date_filter: NotRequired[dict[str, int]]
    unique_messages_in_date_range: NotRequired[int]
    notices: NotRequired[list[Notice]]


_ROOT = "https://graph.microsoft.com/v1.0"
_SEARCHES = ('"from:openai.com"', '"subject:OpenAI"', '"subject:ChatGPT"',
             '"OpenAI AND (receipt OR invoice)"')
_SELECT = "id,receivedDateTime,subject,from,body,toRecipients,hasAttachments"
_TERMS = ("receipt", "invoice", "payment", "subscription", "cancel", "upgrade", "billing", "renew", "credit")
_RESULT_CAP = 1000
_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"


def identities(database: Path, accounts: Path, cutoff: str) -> list[tuple[str, str]]:
    """Resolve anonymous account labels and exact mailbox identity claims.

    Returns:
        Alias/email pairs retained only in the process memory.
    """
    with closing(sqlite3.connect(f"file:{database}?mode=ro", uri=True)) as connection:
        rows = cast("list[tuple[str, str]]", connection.execute(
            "SELECT DISTINCT account_ref,account_label FROM account_usage_samples "
            "WHERE sampled_at<? ORDER BY account_ref", (cutoff,),
        ).fetchall())
    references = sorted({row[0] for row in rows})
    labels = {label: f"A{references.index(ref) + 1:02d}" for ref, label in rows}
    result: list[tuple[str, str]] = []
    for path in sorted(accounts.glob("*/metadata.json")):
        metadata = cast("dict[str, str]", json.loads(path.read_text()))
        auth = cast("dict[str, dict[str, str]]", json.loads((path.parent / "auth.json").read_text()))
        payload = auth["tokens"]["id_token"].split(".")[1]
        decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        claims = cast("dict[str, str]", json.loads(decoded))
        result.append((labels[metadata["label"]], claims["email"]))
    return sorted(result)


def search(mailbox: str, term: str, token: str) -> list[Message]:
    """Perform a scoped read-only search, rejecting truncated or unexpected results.

    Returns:
        Complete search matches, never printed in raw form.

    Raises:
        ConnectionError: If Graph does not return a successful response.
        ValueError: If a search hits the service cap or pagination leaves Graph.
    """
    query = urllib.parse.urlencode({"$search": term, "$select": _SELECT, "$top": _RESULT_CAP})
    url = _ROOT + "/users/" + urllib.parse.quote(mailbox, safe="") + "/messages?" + query
    result: list[Message] = []
    while url:
        if not url.startswith(_ROOT + "/"):
            message = "Unexpected Graph pagination origin"
            raise ValueError(message)
        parts = urllib.parse.urlsplit(url)
        with closing(http.client.HTTPSConnection("graph.microsoft.com", timeout=60)) as connection:
            connection.request("GET", parts.path + "?" + parts.query, headers={
                "Authorization": "Bearer " + token, "Prefer": 'outlook.body-content-type="text"',
            })
            response = connection.getresponse()
            if response.status != http.client.OK:
                message = "Graph HTTP status " + str(response.status)
                raise ConnectionError(message)
            payload = cast("dict[str, object]", json.loads(response.read()))
        result.extend(cast("list[Message]", payload["value"]))
        url = cast("str", payload.get("@odata.nextLink", ""))
    if len(result) >= _RESULT_CAP:
        message = "Search reached the Graph cap; split dates before using this evidence"
        raise ValueError(message)
    return result


def classify(item: Message, mailbox: str) -> Notice | None:
    """Extract numeric mentions without inferring that a notice is an invoice.

    Returns:
        An anonymous provider-notice record, or no record for unrelated senders.
    """
    raw: Mapping[str, object] = item
    sender_record = raw.get("from")
    if sender_record is None:
        return {"source_id_sha256": hashlib.sha256(item["id"].encode()).hexdigest(),
                "received_at": item["receivedDateTime"], "status": "missing_sender_metadata"}
    sender = cast("Recipient", sender_record)["emailAddress"]["address"].lower()
    domain = sender.rsplit("@", 1)[-1]
    if not any(domain == suffix or domain.endswith("." + suffix) for suffix in ("openai.com", "stripe.com")):
        return None
    terms = [term for term in _TERMS if term in item["subject"].lower()]
    if not terms:
        return None
    body = item["body"]["content"]
    return {
        "received_at": item["receivedDateTime"], "provider_domain": domain,
        "source_id_sha256": hashlib.sha256(item["id"].encode()).hexdigest(),
        "body_sha256": hashlib.sha256(body.encode()).hexdigest(),
        "direct_recipient_match": any(r["emailAddress"]["address"].lower() == mailbox.lower()
                                      for r in item["toRecipients"]),
        "subject_terms": terms, "has_attachments": item["hasAttachments"],
        "amount_mentions": re.findall(r"(?:USD|EUR|€|\$)\s*\d[\d,.]*|\d[\d,.]*\s*(?:EUR|USD|€)", body),
        "plan_mentions": sorted(set(re.findall(r"(?i)ChatGPT\s+(?:Pro|Plus|Business|Team|Go)", body))),
        "date_mentions": re.findall(r"(?:" + _MONTHS + r")\s+\d{1,2},?\s+202[56]|202[56]-\d{2}-\d{2}", body),
    }


def inspect_account(alias: str, mailbox: str, token: str, since: str, cutoff: str) -> AccountSearch:
    """Search only an exact tenant mailbox and retain anonymous coverage evidence.

    Returns:
        One account's complete search receipt or explicit access limitation.
    """
    result: AccountSearch = {"account": alias, "exact_identity_email_match": True, "status": "not_started"}
    if not mailbox.lower().endswith("@pitchai.net"):
        return {**result, "status": "non_M365_identity_not_queried"}
    messages: dict[str, Message] = {}
    counts: dict[str, int] = {}
    for term in _SEARCHES:
        matches: list[Message] = []
        with InputFailure(ConnectionError) as failure:
            matches = search(mailbox, term, token)
        if failure.error is not None:
            return {**result, "status": "search_failed", "query": term, "error": str(failure.error)}
        counts[term] = len(matches)
        messages.update((item["id"], item) for item in matches)
    all_messages = messages.values()
    selected = [m for m in all_messages if since <= m["receivedDateTime"] < cutoff]
    ordered = sorted(selected, key=operator.itemgetter("receivedDateTime"))
    notices = [classify(item, mailbox) for item in ordered]
    return {**result, "status": "complete", "query_counts_before_date_filter": counts,
            "unique_messages_in_date_range": len(selected), "notices": [n for n in notices if n is not None]}


def main() -> None:
    """Accept the approved token minter through a pipe without exposing its output."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--broker-database", type=Path, required=True)
    parser.add_argument("--accounts", type=Path, required=True)
    parser.add_argument("--since", required=True)
    parser.add_argument("--cutoff", required=True)
    args = parser.parse_args()
    since, cutoff = cast("str", args.since), cast("str", args.cutoff)
    token = cast("dict[str, str]", json.load(sys.stdin))["access_token"]
    results: list[AccountSearch] = []
    for alias, mailbox in identities(cast("Path", args.broker_database), cast("Path", args.accounts),
                                     cutoff):
        results.append(inspect_account(alias, mailbox, token, since, cutoff))
        sys.stderr.write(alias + ": " + str(results[-1]["status"]) + "\n")
    sys.stdout.write(json.dumps({"schema": 1, "since": since, "cutoff": cutoff,
                                "accounts": results, "qualification": "Provider notice mentions are not "
                                "proof of paid charges or complete billing history. No invoice attachments "
                                "were opened by this extraction; read flags were not changed."}, indent=2) + "\n")


if __name__ == "__main__":
    main()
