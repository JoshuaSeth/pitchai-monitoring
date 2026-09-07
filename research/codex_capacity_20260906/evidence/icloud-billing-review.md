# Additional billing-source check

The configured iCloud mailbox was searched through the installed iCloud skill's official IMAP path. All 14 selectable nondraft folders were examined read-only. Two provider queries per folder covered November 1, 2025 through the analysis cutoff; the search's day boundary was followed by an exact message-date cutoff. The queries included OpenAI senders, ChatGPT subjects, and Apple messages mentioning ChatGPT.

Ten matching messages were fetched with `BODY.PEEK[]`. Flags were read before and after every fetch and remained unchanged. One candidate contained a $6.17 amount mention dated November 12, 2025. It had no exact subscription identity match in the inspected recipient headers or body and does not establish a subscription payment. No attributable paid-subscription receipt was recovered.

The available iCloud mailbox is not independently established as the mailbox behind account A02's relay identity. No Gmail reader is exposed by the current tools, and the configured PitchAI credential directory on main contains no Gmail-named credential file. This is a limitation of discovered access, not a claim that A07 has no billing records.

Two complete exports agreed byte for byte: SHA256 `8dd75c72c0fdea4819feb87c0bfd50bdbbcf03a2501cb0f5681f3b375aac2810`. The retained export is [icloud-billing-notices.json](icloud-billing-notices.json). Protected credentials and raw message content were never exported. The temporary remote helpers and their generated import caches were removed after the read.

To reproduce, place `extract_icloud_billing.py` and `extract_billing_notices.py` together in an owned temporary directory on the broker host, then run its existing Python 3.12 executable:

```bash
/root/.local/share/uv/python/cpython-3.12-linux-x86_64-gnu/bin/python3.12 \
  OWNED_DIRECTORY/extract_icloud_billing.py \
  --skill-directory /root/.codex/skills/icloud
```

The helper uses the installed skill's protected credential loader, the historical broker alias mapping, and locally stored identity claims. It prints only the anonymous projection. Remove the owned remote helper copies and generated import caches afterward. No login, plan, bank, routing or mailbox-flag change is required.
