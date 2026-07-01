-- ============================================================
-- Q05: Primera transacción fallida (T0 exacto)
-- ============================================================
-- Objetivo: ubicar al segundo el inicio del incidente para
-- cotejarlo con el log y comunicarlo con precisión al cliente.
-- ============================================================

SELECT
    id,
    created_at,
    partner_id,
    biller_id,
    provider,
    error_code
FROM transactions
WHERE status = 'failed'
ORDER BY created_at ASC
LIMIT 3;
