-- ============================================================
-- Q03: Cross-partner impact desde T0
-- ============================================================
-- LA query clave del caso. Cruza partner x provider desde el
-- momento en que empezó el incidente para determinar si el
-- problema es de un solo partner o de todos los que usan
-- el mismo proveedor upstream.
--
-- Esta query es la que confirma que NO es un problema de
-- FinCore, sino de Nexopay como proveedor.
-- ============================================================

SELECT
    partner_id,
    provider,
    COUNT(*)                                                     AS total,
    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END)           AS fallidas,
    ROUND(100.0 * SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_fallo
FROM transactions
WHERE created_at >= '2024-11-12 14:09:00'  -- desde T0
GROUP BY partner_id, provider
ORDER BY partner_id, provider;
