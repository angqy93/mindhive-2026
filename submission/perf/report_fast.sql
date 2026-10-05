-- Task 4 fix: the "Tenant Match Health" report, with the same columns, rows and values as
-- starter/report_query.sql, reading each table once instead of once per output group.
--
-- Window: 2026-05-01 to 2026-06-30 (the service binds :date_from / :date_to). Timestamps are
-- compared as text: created_at < '2026-06-31' keeps all of 30 June and leaves out the impossible
-- day 2026-06-31 that exists in the data, exactly like substr(created_at, 1, 10) <= '2026-06-30'.

WITH
-- Order lines and their candidates, per tenant, channel and day.
-- Only order_line has a channel, so the columns that count per channel come from here.
lines_per_channel AS (
    SELECT ol.tenant_id,
           ol.channel,
           substr(ol.created_at, 1, 10)                                   AS day,
           COUNT(DISTINCT ol.line_id)                                     AS lines_total,
           -- lines where the matcher committed to an answer
           COUNT(DISTINCT CASE WHEN me.accepted = 1 THEN me.line_id END)  AS lines_accepted,
           -- how much work the matcher did per line
           COUNT(me.event_id)                                             AS candidates_considered,
           -- distinct buyers touched
           COUNT(DISTINCT ol.customer_id)                                 AS distinct_customers
      FROM order_line ol
      LEFT JOIN match_event me ON me.line_id = ol.line_id
     WHERE ol.created_at >= '2026-05-01' AND ol.created_at < '2026-06-31'
     GROUP BY ol.tenant_id, ol.channel, substr(ol.created_at, 1, 10)
),

-- Every item the matcher considered, per tenant and day: how often, how fast, and whether it
-- became the answer. Covers the window and the day before it (30 April), which the
-- previous-day column needs for 1 May. This is the only read of match_event.
items_per_day AS (
    SELECT tenant_id,
           substr(created_at, 1, 10)                                      AS day,
           item_code,
           COUNT(*)                                                       AS events,
           SUM(latency_ms)                                                AS sum_latency,
           MAX(latency_ms)                                                AS max_latency,
           SUM(accepted)                                                  AS accepted,
           SUM(CASE WHEN accepted = 1 THEN score END)                     AS sum_accept_score
      FROM match_event
     WHERE (created_at >= '2026-04-30' AND created_at < '2026-04-31')
        OR (created_at >= '2026-05-01' AND created_at < '2026-06-31')
     GROUP BY tenant_id, substr(created_at, 1, 10), item_code
),

-- What the matcher did per tenant and day, all channels together: these columns never looked
-- at the channel, so every channel row of a tenant-day shows the same value.
matcher_per_day AS (
    SELECT d.tenant_id,
           d.day,
           -- winning-candidate score, averaged
           SUM(d.sum_accept_score) / SUM(d.accepted)                      AS avg_accept_score,
           -- latency, such as it is measured today
           MAX(d.max_latency)                                             AS max_latency_ms,
           CAST(SUM(d.sum_latency) AS REAL) / SUM(d.events)               AS avg_latency_ms,
           -- accepted answers that pointed at a disabled item
           SUM(CASE WHEN it.disabled = 1 THEN d.accepted ELSE 0 END)      AS accepted_disabled
      FROM items_per_day d
      LEFT JOIN item it ON it.tenant_id = d.tenant_id AND it.item_code = d.item_code
     WHERE d.day >= '2026-05-01'
     GROUP BY d.tenant_id, d.day
),

-- Items the matcher also considered for this tenant on the PREVIOUS day: an item counts when
-- the last day before today that the tenant's matcher considered it is exactly yesterday.
items_also_yesterday AS (
    SELECT tenant_id,
           day,
           COUNT(*)                                                       AS repeat_items_prev_day
      FROM (SELECT tenant_id,
                   day,
                   LAG(day) OVER (PARTITION BY tenant_id, item_code ORDER BY day) AS prev_day
              FROM items_per_day)
     WHERE prev_day = date(day, '-1 day')
       AND day >= '2026-05-01'
     GROUP BY tenant_id, day
),

-- New column: nearest-rank p95 of latency_ms over the same tenant-day set as max_latency_ms
-- (every candidate of the tenant that day, all channels). It is the smallest latency at which at
-- least ceil(0.95 x count) of the tenant-day's candidates are reached, counting from the fastest;
-- (95 * n + 99) / 100 is that ceiling in whole numbers. Latencies are whole milliseconds and
-- repeat a lot, so they are counted per value first and only those counts are sorted.
latency_counts AS (
    SELECT tenant_id,
           substr(created_at, 1, 10)                                      AS day,
           latency_ms,
           COUNT(*)                                                       AS candidates
      FROM match_event
     WHERE created_at >= '2026-05-01' AND created_at < '2026-06-31'
     GROUP BY tenant_id, substr(created_at, 1, 10), latency_ms
),
latency_p95 AS (
    SELECT tenant_id,
           day,
           MIN(latency_ms)                                                AS p95_latency_ms
      FROM (SELECT tenant_id,
                   day,
                   latency_ms,
                   SUM(candidates) OVER (PARTITION BY tenant_id, day ORDER BY latency_ms) AS reached,
                   SUM(candidates) OVER (PARTITION BY tenant_id, day)                     AS n
              FROM latency_counts)
     WHERE reached >= (95 * n + 99) / 100
     GROUP BY tenant_id, day
)

SELECT
    l.tenant_id,
    t.plan,
    l.channel,
    l.day,
    l.lines_total,

    -- lines where the matcher committed to an answer
    l.lines_accepted,

    -- how much work the matcher did per line
    l.candidates_considered,

    -- winning-candidate score, averaged
    m.avg_accept_score,

    -- latency, such as it is measured today
    m.max_latency_ms,
    m.avg_latency_ms,

    -- distinct buyers touched
    l.distinct_customers,

    -- items the matcher also considered for this tenant on the PREVIOUS day
    -- (0 when no item repeats, like the original COUNT)
    COALESCE(y.repeat_items_prev_day, 0)                                  AS repeat_items_prev_day,

    -- share of accepted answers that pointed at a disabled item
    m.accepted_disabled,

    -- new: nearest-rank p95 of latency_ms, over the same tenant-day set as max_latency_ms
    p.p95_latency_ms

FROM lines_per_channel l
JOIN tenant t                    ON t.tenant_id = l.tenant_id
JOIN matcher_per_day m           ON m.tenant_id = l.tenant_id AND m.day = l.day
LEFT JOIN items_also_yesterday y ON y.tenant_id = l.tenant_id AND y.day = l.day
JOIN latency_p95 p               ON p.tenant_id = l.tenant_id AND p.day = l.day
ORDER BY l.tenant_id, l.channel, l.day;
