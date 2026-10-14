-- Помесячные ключевые метрики: выручка, заказы, покупатели, средний чек,
-- доля новых покупателей. Учитываются только доставленные заказы.
WITH delivered AS (
    SELECT o.*, strftime('%Y-%m', o.order_date) AS month
    FROM orders o
    WHERE o.status = 'delivered'
),
first_order AS (            -- месяц первой покупки каждого клиента
    SELECT customer_id, MIN(strftime('%Y-%m', order_date)) AS first_month
    FROM orders GROUP BY customer_id
)
SELECT d.month,
       ROUND(SUM(d.revenue))                               AS revenue,
       COUNT(*)                                            AS orders,
       COUNT(DISTINCT d.customer_id)                       AS buyers,
       ROUND(AVG(d.revenue))                               AS aov,
       ROUND(1.0 * COUNT(DISTINCT CASE WHEN f.first_month = d.month THEN d.customer_id END)
             / COUNT(DISTINCT d.customer_id), 3)           AS new_buyers_share
FROM delivered d
JOIN first_order f USING (customer_id)
GROUP BY d.month
ORDER BY d.month;
