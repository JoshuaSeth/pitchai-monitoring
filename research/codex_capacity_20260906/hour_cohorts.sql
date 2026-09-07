-- Endpoints are external account-tagged provider reads, not workload-selected
-- rollout percentages. Idle zero readings have floating deadlines: exclude them.
CREATE TEMP VIEW fresh AS
SELECT *,CAST(observed/3600 AS INTEGER) AS hour_bin
FROM quota.observations
WHERE stale=0 AND freshness IN ('current','guardian_direct_capture','provider_observation')
      AND used>0 AND observed>=reset-duration-120 AND observed<=reset+120;

CREATE TABLE hour_windows AS
WITH ordered AS (
    SELECT *,LAG(observed) OVER w AS prior_at,LAG(used) OVER w AS prior_used,
        FIRST_VALUE(used) OVER w AS first_used,
        LAST_VALUE(used) OVER full_window AS last_used
    FROM fresh
    WINDOW w AS (PARTITION BY account,duration,hour_bin ORDER BY observed,used),
      full_window AS (PARTITION BY account,duration,hour_bin ORDER BY observed,used
                      ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING)
), grouped AS (
    SELECT account,duration,hour_bin,MIN(reset) AS reset,MAX(reset)-MIN(reset) AS reset_spread,
           MIN(observed) AS start_at,MAX(observed) AS end_at,
           MIN(first_used) AS start_used,MAX(last_used) AS end_used,
           MAX(last_used)-MIN(first_used) AS delta_pp,
           COUNT(*) AS observations,COUNT(DISTINCT observed) AS distinct_times,
           MAX(observed-prior_at) AS max_gap_seconds,
           MIN(used-prior_used) AS smallest_step_pp,
           MAX(capture_time_only) AS has_capture_time_proxy,
           SUM(source_kind='recovery_quota') AS recovery_observations
    FROM ordered GROUP BY account,duration,hour_bin
)
SELECT ROW_NUMBER() OVER (ORDER BY account,duration,hour_bin) AS interval_id,*,
       reset_spread<=1 AND end_at-start_at>=1800 AND max_gap_seconds<=1800
         AND smallest_step_pp>=-1 AND delta_pp>0 AS timing_eligible
FROM grouped;

-- Five-hour and weekly observations remain separate. At most one nonoverlapping
-- nominal interval exists per account/window/hour. The +/-120s variants are
-- timing sensitivities and must not be summed across hours as new consumption.
-- Unknown or unrecovered workloads remain a coverage limitation of every slope.
CREATE TABLE exposures AS
WITH scopes(timing_scope,inset) AS (VALUES ('interior',120),('nominal',0),('enclosing',-120))
SELECT h.interval_id,s.timing_scope,c.strict_eligible,c.model,c.effort,
       COUNT(*) AS calls,COUNT(DISTINCT c.session) AS sessions,
       SUM(c.uncached) AS uncached,SUM(c.cached) AS cached,
       SUM(c.output) AS output,SUM(c.reasoning) AS reasoning,
       SUM(c.standard_usd) AS standard_usd,SUM(c.standard_eur) AS standard_eur,
       SUM(c.write_upper_eur) AS write_upper_eur,
       SUM(c.september6_reference_usd) AS september6_reference_usd,
       SUM(c.standard_usd IS NULL) AS unpriced_calls,
       SUM(c.price_status<>'dated_standard_reference') AS uncertain_price_calls,
       SUM(c.long_context) AS long_context_calls,
       SUM(c.service_tier IS NULL) AS unknown_tier_calls,
       SUM(CASE WHEN h.duration=604800 THEN ABS(c.weekly_reset-h.reset)>1
                ELSE ABS(c.five_reset-h.reset)>1 END) AS different_reset_calls,
       SUM(CASE WHEN h.duration=604800 THEN c.weekly_reset IS NULL
                ELSE c.five_reset IS NULL END) AS missing_reset_calls
FROM hour_windows h CROSS JOIN scopes s
JOIN account_calls c ON c.account=h.account
    AND c.timestamp>h.start_at+s.inset AND c.timestamp<=h.end_at-s.inset
WHERE h.timing_eligible=1
GROUP BY h.interval_id,s.timing_scope,c.strict_eligible,c.model,c.effort;
CREATE INDEX exposure_interval ON exposures(interval_id,timing_scope);
