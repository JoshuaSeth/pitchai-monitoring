-- Candidate prices are API reference values; actual service tiers are missing.
-- Retain both a broad recovered set and a stricter provenance/quality subset.
CREATE TABLE account_calls AS
SELECT c.*,p.price_status,p.long_context,p.price_boundary_day,
       p.standard_usd,p.standard_eur,p.write_upper_eur,p.september6_reference_usd,
       CASE WHEN h.source IS NULL THEN 'missing_header_capture'
            WHEN h.outer_session IS NULL THEN 'missing_session_header'
            WHEN c.session<>h.outer_session THEN 'embedded_session_differs_from_outer'
            WHEN c.timestamp<unixepoch(h.outer_at) THEN 'predates_outer_session'
            WHEN h.category NOT IN ('cli_home','managed_runtime') THEN 'matching_header_other_path'
            ELSE 'matching_runtime_path_header' END AS origin_grade,
       CASE WHEN c.session=h.outer_session
                 AND c.timestamp>=unixepoch(h.outer_at)
                 AND h.category IN ('cli_home','managed_runtime')
                 AND c.counter_status='last_call_reconciles'
                 AND c.total_mismatch=0
                 AND c.model_conflict=0 AND c.effort_conflict=0
                 AND d.model_conflict=0 AND d.effort_conflict=0
            THEN 1 ELSE 0 END AS strict_eligible
FROM usage.calls c JOIN replay.decisions d USING(call_key)
JOIN prices.prices p USING(call_key)
LEFT JOIN headers h ON c.cell=h.cell AND c.source=h.source
WHERE d.keep_primary=1 AND c.account IS NOT NULL;
CREATE UNIQUE INDEX account_call_identity ON account_calls(call_key);
CREATE INDEX account_call_time ON account_calls(account,timestamp);

-- Calendar months are observed periods, not verified paid billing periods.
-- September is partial; zero telemetry never proves zero use.
CREATE TABLE account_months AS
SELECT account,substr(day,1,7) AS month,strict_eligible,
       COUNT(*) AS calls,COUNT(DISTINCT day) AS observed_days,
       MIN(day) AS first_day,MAX(day) AS last_day,
       SUM(uncached) AS uncached,SUM(cached) AS cached,
       SUM(output) AS output,SUM(reasoning) AS reasoning,
       SUM(standard_usd) AS standard_usd,SUM(standard_eur) AS standard_eur,
       SUM(write_upper_eur) AS write_upper_eur,
       SUM(standard_usd IS NULL) AS unpriced_calls,
       SUM(price_status<>'dated_standard_reference') AS historically_uncertain_price_calls,
       SUM(service_tier IS NULL) AS unknown_tier_calls
FROM account_calls GROUP BY account,substr(day,1,7),strict_eligible;
