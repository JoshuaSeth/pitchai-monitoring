// Copyright (c) 2026 PitchAI. All rights reserved.
// Exercise the actual dashboard formatter without network or production traffic.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");

const source = fs.readFileSync(path.join(__dirname, "static/dashboard.js"), "utf8");
const boot = 'document.addEventListener("DOMContentLoaded", initialize);';
assert.equal(source.split(boot).length, 2);
const context = { Intl, Date };
vm.createContext(context);
vm.runInContext(source.replace(boot, "globalThis.detail = subscriptionDetail;"), context);

test("exact expiry displays seconds and the declared zone, independent of UTC controls", () => {
  const account = {
    access_state: "active_until_end", access_end_precision: "exact",
    access_ends_on: "2026-10-03", access_ends_at: "2026-10-03T18:50:54Z",
    provider_cancels_at: "2026-10-03T12:50:54Z",
  };
  const text = context.detail(account, "Europe/Berlin");
  assert.match(text, /50:54/);
  assert.match(text, /GMT\+2/);
  assert.doesNotMatch(text, /date only/);
  assert.match(context.detail({ ...account, access_state: "access_ended" }, "Europe/Berlin"), /access ended/);
  assert.match(context.detail({ ...account, access_ends_at: "2026-10-25T18:50:54Z" }, "Europe/Berlin"), /GMT\+1/);
});

test("date-only records retain their calendar label and precision", () => {
  const account = { access_state: "active_until_end", access_ends_on: "2026-10-03", access_ends_at: null };
  const berlin = context.detail(account, "Europe/Berlin");
  assert.match(berlin, /date only/);
  assert.equal(context.detail(account, "America/New_York"), berlin);
  assert.doesNotMatch(berlin, /GMT|00:00/);
});

test("malformed evidence does not display an apparently valid date-only fallback", () => {
  assert.match(context.detail({ access_end_precision: "invalid", access_ends_on: "2026-10-03" }, "Europe/Berlin"),
    /evidence is invalid/);
  assert.equal(context.detail({ access_state: "unknown" }, "Europe/Berlin"), "Subscription state unknown");
});
