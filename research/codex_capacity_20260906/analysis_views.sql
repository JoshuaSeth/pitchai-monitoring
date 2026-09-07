-- These temporary views read the frozen cohort ledger without altering it.
-- Pool quota is counted once per interval. It is never assigned independently
-- to every model row. Dominance is a workload control, not proof of isolation.
CREATE TEMP VIEW hourly_totals AS
SELECT interval_id,timing_scope,SUM(standard_usd) AS broad_usd,
       SUM(CASE WHEN strict_eligible=1 THEN standard_usd ELSE 0 END) AS strict_usd,
       SUM(CASE WHEN strict_eligible=1 THEN september6_reference_usd ELSE 0 END) AS fixed_usd,
       SUM(CASE WHEN strict_eligible=1 THEN calls ELSE 0 END) AS strict_calls,
       SUM(CASE WHEN strict_eligible=1 THEN uncached ELSE 0 END) AS uncached,
       SUM(CASE WHEN strict_eligible=1 THEN cached ELSE 0 END) AS cached,
       SUM(CASE WHEN strict_eligible=1 THEN output ELSE 0 END) AS output,
       SUM(CASE WHEN strict_eligible=1 THEN reasoning ELSE 0 END) AS reasoning,
       SUM(CASE WHEN strict_eligible=1 THEN long_context_calls ELSE 0 END) AS long_context_calls,
       SUM(unpriced_calls) AS unpriced_calls,SUM(uncertain_price_calls) AS uncertain_price_calls,
       SUM(different_reset_calls) AS different_reset_calls,SUM(missing_reset_calls) AS missing_reset_calls
FROM exposures GROUP BY interval_id,timing_scope;

CREATE TEMP VIEW hourly_dominant AS
SELECT * FROM (
    SELECT *,ROW_NUMBER() OVER (PARTITION BY interval_id ORDER BY standard_usd DESC,model,effort) AS rank
    FROM exposures WHERE timing_scope='nominal' AND strict_eligible=1
) WHERE rank=1;

CREATE TEMP VIEW hourly_analysis AS
SELECT h.*,datetime(h.start_at,'unixepoch') AS start_utc,date(h.start_at,'unixepoch') AS day,
       d.model,d.effort,d.standard_usd AS dominant_usd,d.calls AS dominant_calls,
       d.sessions AS dominant_sessions,d.standard_usd/n.strict_usd AS dominant_value_share,
       n.strict_usd/n.broad_usd AS strict_value_share,n.strict_calls,
       n.strict_usd,n.fixed_usd,n.uncached,n.cached,n.output,n.reasoning,
       n.long_context_calls,n.unpriced_calls,n.uncertain_price_calls,
       n.different_reset_calls,n.missing_reset_calls,
       i.strict_usd AS interior_usd,o.strict_usd AS enclosing_usd,
       e.segment,e.transition_grade,e.credit,
       CASE WHEN d.standard_usd>=.95*n.strict_usd AND n.strict_usd>=.95*n.broad_usd
                 AND n.unpriced_calls=0 AND n.uncertain_price_calls=0
                 AND n.different_reset_calls=0 AND n.missing_reset_calls=0 AND h.delta_pp>=5
            THEN 1 ELSE 0 END AS primary_cohort
FROM hour_windows h JOIN hourly_totals n ON h.interval_id=n.interval_id AND n.timing_scope='nominal'
JOIN hourly_dominant d USING(interval_id)
LEFT JOIN hourly_totals i ON h.interval_id=i.interval_id AND i.timing_scope='interior'
LEFT JOIN hourly_totals o ON h.interval_id=o.interval_id AND o.timing_scope='enclosing'
LEFT JOIN epochs e ON h.account=e.account AND h.start_at>=e.start_at AND h.end_at<=e.last_at
                   AND ABS(h.reset-e.reset)<=30
WHERE h.duration=604800;

-- Nominal epoch values span the first positive observation to the first
-- maximum. +/-120s alternatives test timestamp alignment, not hidden credits.
CREATE TEMP VIEW epoch_costs AS
WITH scopes(timing_scope,inset) AS (VALUES ('interior',120),('nominal',0),('enclosing',-120))
SELECT e.account,e.segment,s.timing_scope,
       SUM(c.standard_usd) AS broad_usd,
       SUM(CASE WHEN c.strict_eligible=1 THEN c.standard_usd ELSE 0 END) AS strict_usd,
       SUM(CASE WHEN c.strict_eligible=1 THEN c.september6_reference_usd ELSE 0 END) AS fixed_usd,
       SUM(CASE WHEN c.strict_eligible=1 THEN 1 ELSE 0 END) AS strict_calls,
       COUNT(DISTINCT CASE WHEN c.strict_eligible=1 THEN c.session END) AS strict_sessions,
       SUM(CASE WHEN c.strict_eligible=1 THEN c.uncached ELSE 0 END) AS uncached,
       SUM(CASE WHEN c.strict_eligible=1 THEN c.cached ELSE 0 END) AS cached,
       SUM(CASE WHEN c.strict_eligible=1 THEN c.output ELSE 0 END) AS output,
       SUM(CASE WHEN c.strict_eligible=1 THEN c.reasoning ELSE 0 END) AS reasoning,
       SUM(CASE WHEN c.strict_eligible=1 THEN c.long_context ELSE 0 END) AS long_context_calls,
       SUM(c.standard_usd IS NULL) AS unpriced_calls,
       SUM(c.price_status<>'dated_standard_reference') AS uncertain_price_calls,
       SUM(ABS(c.weekly_reset-e.reset)>30) AS different_reset_calls,
       SUM(c.weekly_reset IS NULL) AS missing_reset_calls
FROM epochs e CROSS JOIN scopes s JOIN account_calls c ON c.account=e.account
  AND c.timestamp>e.start_at+s.inset AND c.timestamp<=e.end_at-s.inset
WHERE e.delta_pp>0 GROUP BY e.account,e.segment,s.timing_scope;

CREATE TEMP VIEW epoch_dominant AS
SELECT * FROM (
    SELECT *,ROW_NUMBER() OVER (PARTITION BY account,segment ORDER BY standard_usd DESC,model,effort) AS rank
    FROM epoch_exposures WHERE strict_eligible=1
) WHERE rank=1;

CREATE TEMP VIEW epoch_analysis AS
SELECT e.*,datetime(e.start_at,'unixepoch') AS start_utc,datetime(e.end_at,'unixepoch') AS end_utc,
       d.model,d.effort,d.standard_usd AS dominant_usd,
       d.standard_usd/n.strict_usd AS dominant_value_share,n.strict_usd/n.broad_usd AS strict_value_share,
       n.strict_usd,n.fixed_usd,n.strict_calls,n.strict_sessions,n.uncached,n.cached,n.output,n.reasoning,
       n.long_context_calls,n.unpriced_calls,n.uncertain_price_calls,
       n.different_reset_calls,n.missing_reset_calls,
       i.strict_usd AS interior_usd,o.strict_usd AS enclosing_usd,
       (SELECT MAX(observed-prior_at) FROM (
           SELECT observed,LAG(observed) OVER (ORDER BY observed,used) AS prior_at
           FROM epoch_observations q WHERE q.account=e.account AND q.segment=e.segment
             AND q.observed<=e.end_at
       )) AS consumption_max_gap_seconds
FROM epochs e LEFT JOIN epoch_dominant d USING(account,segment)
LEFT JOIN epoch_costs n ON e.account=n.account AND e.segment=n.segment AND n.timing_scope='nominal'
LEFT JOIN epoch_costs i ON e.account=i.account AND e.segment=i.segment AND i.timing_scope='interior'
LEFT JOIN epoch_costs o ON e.account=o.account AND e.segment=o.segment AND o.timing_scope='enclosing';

CREATE TEMP VIEW cohort_validation AS
SELECT 'duplicate_account_calls' AS check_name,COUNT(*)-COUNT(DISTINCT call_key) AS failures FROM account_calls
UNION ALL SELECT 'duplicate_epochs',COUNT(*)-COUNT(DISTINCT account||':'||segment) FROM epochs
UNION ALL SELECT 'inventory_count_mismatch',COUNT(*) FROM guardian_snapshots
  WHERE available_count<>json_array_length(credits)
UNION ALL SELECT 'decreasing_positive_epoch_steps',COUNT(*) FROM (
  SELECT used-LAG(used) OVER (PARTITION BY account,segment ORDER BY observed,used) AS step
  FROM epoch_observations) WHERE step < -1
UNION ALL SELECT 'duplicate_hour_mapping',COUNT(*)-COUNT(DISTINCT interval_id) FROM hourly_analysis
UNION ALL SELECT 'missing_account_calls',COUNT(*)=0 FROM account_calls
UNION ALL SELECT 'missing_guardian_inventory',COUNT(*)=0 FROM guardian_snapshots;
