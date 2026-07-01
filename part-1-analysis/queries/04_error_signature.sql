-- ============================================================
-- Q04: Firma del error
-- ============================================================
-- Objetivo: verificar si todos los fallos comparten el mismo
-- código y mensaje de error. Si son idénticos, es firma de un
-- comportamiento sistemático (no fallos random).
-- ============================================================

SELECT
    error_code,
    error_message,
    COUNT(*) AS ocurrencias
FROM transactions
WHERE status = 'failed'
GROUP BY error_code, error_message
ORDER BY ocurrencias DESC;
