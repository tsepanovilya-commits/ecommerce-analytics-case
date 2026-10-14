-- RFM-сегментация на 2025-12-31: давность, частота, деньги -> баллы 1..5 (NTILE).
WITH base AS (
    SELECT customer_id,
           julianday('2025-12-31') - julianday(MAX(order_date)) AS recency_days,
           COUNT(*)                                             AS frequency,
           SUM(revenue)                                         AS monetary
    FROM orders WHERE status = 'delivered' GROUP BY customer_id
),
scored AS (
    SELECT *,
           6 - NTILE(5) OVER (ORDER BY recency_days) AS r,  -- меньше дней -> выше балл
           NTILE(5) OVER (ORDER BY frequency)        AS f,
           NTILE(5) OVER (ORDER BY monetary)         AS m
    FROM base
)
SELECT CASE
         WHEN r >= 4 AND f >= 4 THEN 'Чемпионы'
         WHEN r >= 3 AND f >= 3 THEN 'Лояльные'
         WHEN r >= 4 AND f <= 2 THEN 'Новые'
         WHEN r <= 2 AND f >= 3 THEN 'Под угрозой ухода'
         ELSE 'Спящие'
       END AS segment,
       COUNT(*) AS customers,
       ROUND(AVG(recency_days)) AS avg_recency,
       ROUND(AVG(frequency), 2) AS avg_freq,
       ROUND(SUM(monetary)) AS revenue,
       ROUND(100.0 * SUM(monetary) / (SELECT SUM(monetary) FROM base), 1) AS revenue_pct
FROM scored GROUP BY segment ORDER BY revenue DESC;
