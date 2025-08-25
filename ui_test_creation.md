# **Instruction Set #1 — Creating Standardized UI Tests from Browser Interactions**

## **Purpose**

Capture real, repeatable UI flows in production apps and convert them into standardized UI tests that can be run automatically.

---

## **Workflow Steps**

1. **Identify Target Flow**

   * Choose a critical user journey with clear success criteria (e.g., checkout, login, data upload).
   * Ensure the flow is high-value and user-visible.

2. **Launch Browser/QA/Visual Agent**

   * Use the browser agent to perform the flow exactly as a real user would.
   * Keep the session focused on the chosen flow.

3. **Record All Steps**

   * Log every click, text input, wait, and navigation.
   * Use screenshots or video capture if available.
   * Name steps in a clear, consistent format.

4. **Mark Key Assertions**

   * Identify points where correctness must be confirmed (element visible, success message shown, updated data displayed).
   * Avoid ambiguous validations — be explicit.

5. **Export & Save Session**

   * Export the recorded flow from the browser agent.
   * Save files in the shared repository under the correct application/project folder.

6. **Standardize Format**

   * Use the assistant’s **Generate Test** function to convert the recorded flow into our official standardized UI test format.

7. **Tag & Version**

   * Include version/date in metadata.
   * Tag with feature name, sub-feature, and expected outcome.

---

## **Metadata Template**

```yaml
flow_name: Checkout — Card Payment Success
description: User can successfully complete a purchase using credit card
last_verified: 2025-08-16
owner: Danny
target_env: production
source_recording: checkout_flow_recording.json
notes: None
```

---

**Output:**

* New standardized UI test file.
* Metadata file stored in repo.
* Flow ready for deployment into automated runs.
