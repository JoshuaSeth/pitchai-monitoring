# **Instruction Set #2 — Executing UI Tests & Investigating Failures**

## **Purpose**

Run standardized UI tests across multiple production applications, monitor for failures, and investigate using production logs with the help of the infra/ops engineer.

---

## **Workflow Steps**

1. **Trigger or Schedule Test Runs**

   * Run all standardized UI tests across production environments on a set schedule (e.g., hourly, daily) or manually as needed.

2. **Collect Results**

   * Gather pass/fail data, execution timestamps, and any screenshots or DOM captures from failures.

3. **If a Test Fails:**

   * **Re-run the failed test** to confirm it’s reproducible.
   * If still failing, escalate to the infra/ops engineer.

4. **Prepare Incident Context for Ops Engineer**

   * Test name and flow description.
   * Time of failure.
   * Screenshot or DOM snapshot.
   * Any related test output or logs.

5. **Ops Engineer Log Investigation**

   * Match failure timestamps to backend or service errors.
   * Identify whether the failure is UI-related, backend-related, or environmental.

6. **Collaborate on Resolution**

   * If it’s a legitimate bug, create a ticket with all findings.
   * If UI changed intentionally, update the test flow and assertions.
   * If environmental, escalate to infra team for fixes.

7. **Document Incident**

   * Root cause.
   * Actions taken.
   * Any changes to the test or environment.

---

## **Incident Report Template**

```yaml
test_name: Checkout — Card Payment Success
failure_time: 2025-08-16 14:35 UTC
reproducible: true
ops_contact: Alex Smith
root_cause: Payment service timeout
resolution: Restarted payment service, monitoring closely
test_update: None
```

---

**Output:**

* Updated pass/fail test report.
* Documented incident.
* Updated tests if necessary.
