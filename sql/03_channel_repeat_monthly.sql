-- Доля повторных заказов по каналам привлечения помесячно
-- + отклонение от скользящего среднего за 3 предыдущих месяца (оконная функция).
-- Используется для поиска аномалий.
WITH ranked AS (
    SELECT o.order_id, o.order_date, c.channel,
           ROW_NUMBER() OVER (PARTITION BY o.customer_id ORDER BY o.order_date) AS order_num
    FROM orders o JOIN customers c USING (customer_id)
),
monthly AS (
    SELECT channel, strftime('%Y-%m', order_date) AS month,
           SUM(CASE WHEN order_num > 1 THEN 1 ELSE 0 END) AS repeat_orders
    FROM ranked GROUP BY channel, month
)
SELECT channel, month, repeat_orders,
       ROUND(AVG(repeat_orders) OVER (PARTITION BY channel ORDER BY month
             ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING), 1) AS avg_prev_3m,
       ROUND(1.0 * repeat_orders / AVG(repeat_orders) OVER (PARTITION BY channel ORDER BY month
             ROWS BETWEEN 3 PRECEDING AND 1 PRECEDING) - 1, 3) AS deviation
FROM monthly
WHERE month >= '2024-06'
ORDER BY channel, month;
