-- Когортное удержание: доля клиентов когорты (месяц регистрации),
-- совершивших покупку через N месяцев после регистрации.
WITH activity AS (
    SELECT DISTINCT c.customer_id,
           strftime('%Y-%m', c.signup_date) AS cohort,
           (CAST(strftime('%Y', o.order_date) AS INT) - CAST(strftime('%Y', c.signup_date) AS INT)) * 12
         + (CAST(strftime('%m', o.order_date) AS INT) - CAST(strftime('%m', c.signup_date) AS INT)) AS month_n
    FROM customers c
    JOIN orders o USING (customer_id)
),
cohort_size AS (
    SELECT cohort, COUNT(DISTINCT customer_id) AS size FROM activity WHERE month_n = 0 GROUP BY cohort
)
SELECT a.cohort, a.month_n,
       COUNT(DISTINCT a.customer_id)                         AS active,
       ROUND(1.0 * COUNT(DISTINCT a.customer_id) / s.size, 4) AS retention
FROM activity a JOIN cohort_size s USING (cohort)
WHERE a.month_n BETWEEN 0 AND 12
GROUP BY a.cohort, a.month_n
ORDER BY a.cohort, a.month_n;
