-- ============================================================
-- Q01: Timeline por minuto para identificar T0 del incidente
-- ============================================================
-- Objetivo: ver la curva de fallos vs éxitos por minuto y
-- ubicar el momento exacto donde algo cambia.
-- ============================================================

SELECT
    substr(created_at, 1, 16)                                    AS minuto,
    SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END)          AS ok,
    SUM(CASE WHEN status = 'failed'  THEN 1 ELSE 0 END)          AS fail,
    COUNT(*)                                                     AS total,
    ROUND(100.0 * SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_fail
FROM transactions
GROUP BY minuto
ORDER BY minuto;
