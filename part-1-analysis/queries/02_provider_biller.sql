-- ============================================================
-- Q02: Descomposición por proveedor + biller
-- ============================================================
-- Objetivo: cruzar la dimensión "proveedor" con "biller" para
-- ver dónde se concentran los fallos. Ayuda a distinguir si el
-- problema es del biller o del proveedor upstream.
-- ============================================================

SELECT
    provider,
    biller_id,
    COUNT(*)                                                     AS total,
    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END)           AS fallidas,
    ROUND(100.0 * SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_fallo
FROM transactions
GROUP BY provider, biller_id
ORDER BY pct_fallo DESC, total DESC;
