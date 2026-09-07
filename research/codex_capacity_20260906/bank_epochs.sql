-- A missing credit before expiry plus a new weekly window is evidence of a
-- probable bank redemption, not an observed redemption response. Preserve that
-- distinction from the guardian's six directly recorded actions.
CREATE TABLE guardian_snapshots AS
SELECT json_extract(data,'$.snapshot_id') AS snapshot_id,
       json_extract(data,'$.account') AS account,
       json_extract(data,'$.captured_at') AS captured_at,
       (julianday(json_extract(data,'$.captured_at'))-2440587.5)*86400 AS observed,
       json_extract(data,'$.primary.used_percent') AS used,
       json_extract(data,'$.primary.reset_at') AS reset,
       json_extract(data,'$.primary.limit_window_seconds') AS duration,
       json_extract(data,'$.available_count') AS available_count,
       json_extract(data,'$.credits') AS credits
FROM broker_records WHERE kind='guardian_snapshot';
CREATE UNIQUE INDEX guardian_snapshot_identity ON guardian_snapshots(snapshot_id);
CREATE INDEX guardian_account_time ON guardian_snapshots(account,observed);

CREATE TABLE credit_presence AS
SELECT s.snapshot_id,s.account,s.observed,
       json_extract(c.value,'$.credit') AS credit,
       json_extract(c.value,'$.expires_at') AS expires_at,
       json_extract(c.value,'$.granted_at') AS granted_at,
       json_extract(c.value,'$.status') AS status,
       json_extract(c.value,'$.redeemable') AS redeemable,
       json_extract(c.value,'$.supported_by_plan') AS supported_by_plan
FROM guardian_snapshots s,json_each(s.credits) c;
CREATE INDEX credit_identity_time ON credit_presence(account,credit,observed);

CREATE TABLE bank_losses AS
WITH last_presence AS (
    SELECT account,credit,MAX(observed) AS last_present,MIN(expires_at) AS expires_at,
           MAX(expires_at) AS latest_expiry,MIN(granted_at) AS granted_at
    FROM credit_presence GROUP BY account,credit
), missing AS (
    SELECT p.*,MIN(s.observed) AS first_absent
    FROM last_presence p JOIN guardian_snapshots s
         ON s.account=p.account AND s.observed>p.last_present
    GROUP BY p.account,p.credit
), adjacent AS (
    SELECT m.*,a.used AS before_used,a.reset AS before_reset,
           z.used AS after_used,z.reset AS after_reset,
           a.available_count AS before_count,z.available_count AS after_count,
           m.first_absent<unixepoch(m.expires_at) AS disappeared_before_expiry,
           EXISTS(SELECT 1 FROM broker_records r WHERE r.kind='redemption'
                  AND json_extract(r.data,'$.credit')=m.credit
                  AND json_extract(r.data,'$.account')=m.account
                  AND json_extract(r.data,'$.status')='succeeded') AS direct_guardian_action
    FROM missing m JOIN guardian_snapshots a
      ON a.account=m.account AND a.observed=m.last_present
    JOIN guardian_snapshots z ON z.account=m.account AND z.observed=m.first_absent
), anchors AS (
    SELECT a.*,(
        SELECT MIN(s.observed) FROM guardian_snapshots s
        WHERE s.account=a.account AND s.observed>=a.first_absent
          AND s.observed<a.first_absent+604800 AND s.used>0 AND s.duration=604800
          AND ABS(s.reset-a.before_reset)>30
    ) AS first_positive_new_window
    FROM adjacent a
)
SELECT a.*,s.reset AS positive_reset,s.used AS first_positive_used,
       CASE WHEN direct_guardian_action=1 THEN 'direct_guardian_redemption'
            WHEN disappeared_before_expiry=1 AND after_count=before_count-1
                 AND s.reset IS NOT NULL THEN 'credit_loss_and_new_window'
            ELSE 'unresolved_credit_disappearance' END AS evidence_grade
FROM anchors a LEFT JOIN guardian_snapshots s
  ON s.account=a.account AND s.observed=a.first_positive_new_window;

-- The 30-second tolerance is only within an already identified account. It is
-- not used to map workloads across accounts. In this corpus 30s and 120s give
-- identical transition counts; 1s fragments stable windows on probe jitter.
CREATE TABLE epoch_observations AS
WITH ordered AS (
    SELECT *,LAG(reset) OVER (PARTITION BY account ORDER BY observed,used) AS prior_reset
    FROM fresh WHERE duration=604800
), segmented AS (
    SELECT *,SUM(CASE WHEN prior_reset IS NULL OR ABS(reset-prior_reset)>30 THEN 1 ELSE 0 END)
        OVER (PARTITION BY account ORDER BY observed,used) AS segment
    FROM ordered
)
SELECT * FROM segmented;
CREATE INDEX epoch_observation_group ON epoch_observations(account,segment,observed);

CREATE TABLE epochs AS
WITH grouped AS (
    SELECT account,segment,MIN(observed) AS start_at,MAX(observed) AS last_at,
           MIN(reset) AS reset,MAX(reset)-MIN(reset) AS reset_spread,
           MIN(used) AS min_used,MAX(used) AS max_used,COUNT(*) AS observations,
           MAX(observed-LAGGED.prior_at) AS max_gap_seconds
    FROM (SELECT *,LAG(observed) OVER (PARTITION BY account,segment ORDER BY observed,used) AS prior_at
          FROM epoch_observations) LAGGED
    GROUP BY account,segment
), endpoints AS (
    SELECT g.*,(
        SELECT MIN(o.observed) FROM epoch_observations o
        WHERE o.account=g.account AND o.segment=g.segment AND o.used=g.max_used
    ) AS end_at,(
        SELECT MIN(o.used) FROM epoch_observations o
        WHERE o.account=g.account AND o.segment=g.segment AND o.observed=g.start_at
    ) AS start_used,LAG(reset) OVER (PARTITION BY account ORDER BY segment) AS previous_reset
    FROM grouped g
)
SELECT e.*,e.max_used-e.start_used AS delta_pp,b.credit,b.evidence_grade AS bank_evidence,
       CASE WHEN b.credit IS NOT NULL THEN b.evidence_grade
            WHEN previous_reset IS NULL THEN 'left_censored'
            WHEN start_at>=previous_reset THEN 'ordinary_expiry_compatible'
            ELSE 'unexplained_early_replacement' END AS transition_grade
FROM endpoints e LEFT JOIN bank_losses b
  ON b.account=e.account AND ABS(b.positive_reset-e.reset)<=30
  AND e.start_at>=b.last_present AND e.start_at<b.first_absent+604800;

CREATE TABLE epoch_exposures AS
SELECT e.account,e.segment,c.strict_eligible,c.model,c.effort,
       COUNT(*) AS calls,COUNT(DISTINCT c.session) AS sessions,
       SUM(c.uncached) AS uncached,SUM(c.cached) AS cached,
       SUM(c.output) AS output,SUM(c.reasoning) AS reasoning,
       SUM(c.standard_usd) AS standard_usd,SUM(c.standard_eur) AS standard_eur,
       SUM(c.write_upper_eur) AS write_upper_eur,
       SUM(c.september6_reference_usd) AS september6_reference_usd,
       SUM(c.standard_usd IS NULL) AS unpriced_calls,
       SUM(ABS(c.weekly_reset-e.reset)>30) AS different_reset_calls,
       SUM(c.weekly_reset IS NULL) AS missing_reset_calls
FROM epochs e JOIN account_calls c ON c.account=e.account
  AND c.timestamp>e.start_at AND c.timestamp<=e.end_at
WHERE e.delta_pp>0
GROUP BY e.account,e.segment,c.strict_eligible,c.model,c.effort;
