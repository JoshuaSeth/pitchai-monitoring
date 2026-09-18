-- Read after analysis_views.sql in a read-only connection to the frozen cohort
-- database. The published model rate changes on a UTC date, but its exact
-- intraday effective time is unavailable. Bound that day's Sol reference value
-- by applying the old or new rate to every retained boundary-day call.
-- This is a price-timing sensitivity, with standard service and no missing-work
-- correction. Constant-price comparisons are unchanged.
CREATE TEMP TABLE boundary_calls AS
SELECT account,timestamp,day,model,long_context,standard_usd,
       (uncached*5+cached*0.5+output*30)/1000000.0 AS old_rate_usd,
       (uncached*4+cached*0.4+output*20)/1000000.0 AS new_rate_usd
FROM account_calls WHERE strict_eligible=1 AND price_boundary_day=1;

CREATE TEMP VIEW boundary_hours AS
SELECT h.interval_id,h.account,h.day,h.model,h.effort,h.delta_pp,h.strict_usd,
       COUNT(*) AS boundary_calls,SUM(c.old_rate_usd-c.new_rate_usd) AS extra_old_rate_usd
FROM hourly_analysis h JOIN boundary_calls c ON c.account=h.account
  AND c.timestamp>h.start_at AND c.timestamp<=h.end_at
WHERE h.primary_cohort=1 AND h.timing_eligible=1
GROUP BY h.interval_id;

CREATE TEMP VIEW boundary_epochs AS
SELECT e.account,e.segment,datetime(e.start_at,'unixepoch') AS start_utc,
       COUNT(*) AS boundary_calls,SUM(c.old_rate_usd-c.new_rate_usd) AS extra_old_rate_usd
FROM epochs e JOIN boundary_calls c ON c.account=e.account
  AND c.timestamp>e.start_at AND c.timestamp<=e.end_at
GROUP BY e.account,e.segment;

SELECT json_object(
  'unsupported_boundary_calls',(SELECT COUNT(*) FROM boundary_calls
       WHERE day<>'2026-08-21' OR model<>'gpt-5.6-sol' OR long_context<>0),
  'totals',(SELECT json_object('calls',COUNT(*),'dated_usd',SUM(standard_usd),
       'old_rate_usd',SUM(old_rate_usd),'new_rate_usd',SUM(new_rate_usd),
       'extra_old_rate_usd',SUM(old_rate_usd-new_rate_usd)) FROM boundary_calls),
  'primary_hours',(SELECT json_group_array(json_object(
       'interval_id',interval_id,'account',account,'day',day,'model',model,'effort',effort,
       'points',delta_pp,'dated_usd',strict_usd,'boundary_calls',boundary_calls,
       'extra_old_rate_usd',extra_old_rate_usd)) FROM boundary_hours ORDER BY interval_id),
  'epochs',(SELECT json_group_array(json_object(
       'account',account,'segment',segment,'start_utc',start_utc,
       'boundary_calls',boundary_calls,'extra_old_rate_usd',extra_old_rate_usd))
       FROM boundary_epochs ORDER BY account,segment)
) AS result;
