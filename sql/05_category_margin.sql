-- Выручка и валовая маржа по категориям (доставленные заказы).
SELECT p.category,
       ROUND(SUM(oi.price * oi.qty))                          AS revenue,
       ROUND(SUM((oi.price - p.cost) * oi.qty))               AS gross_profit,
       ROUND(1.0 * SUM((oi.price - p.cost) * oi.qty) / SUM(oi.price * oi.qty), 3) AS margin
FROM order_items oi
JOIN orders o   USING (order_id)
JOIN products p USING (product_id)
WHERE o.status = 'delivered'
GROUP BY p.category ORDER BY gross_profit DESC;
