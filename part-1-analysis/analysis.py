"""
Tapi Challenge - Análisis Parte 1
Carga transactions.sql en SQLite in-memory y ejecuta queries diagnósticas.
"""
import sqlite3
import re
from pathlib import Path

# --- Setup ---
# Los archivos originales del challenge viven en /data del repo.
BASE = Path(__file__).parent
DATA = BASE.parent / "data"
SQL_FILE = DATA / "transactions.sql"
LOG_FILE = DATA / "app.log"

# El SQL original usa sintaxis Postgres (VARCHAR, NUMERIC). SQLite es flexible
# con tipos así que corre igual. Solo ajustamos si hiciera falta.
sql_script = SQL_FILE.read_text()

conn = sqlite3.connect(":memory:")
conn.row_factory = sqlite3.Row
conn.executescript(sql_script)

def run(query, title=""):
    """Ejecuta una query e imprime resultados en formato tabla."""
    if title:
        print(f"\n{'='*70}\n{title}\n{'='*70}")
    cur = conn.execute(query)
    rows = cur.fetchall()
    if not rows:
        print("(sin resultados)")
        return
    cols = rows[0].keys()
    # Ancho dinámico por columna
    widths = {c: max(len(c), max(len(str(r[c])) for r in rows)) for c in cols}
    header = " | ".join(c.ljust(widths[c]) for c in cols)
    print(header)
    print("-" * len(header))
    for r in rows:
        print(" | ".join(str(r[c]).ljust(widths[c]) for c in cols))

# =====================================================================
# Q1: Sanity check - ¿qué hay en la tabla?
# =====================================================================
run("""
SELECT COUNT(*) AS total_txns,
       MIN(created_at) AS primera,
       MAX(created_at) AS ultima,
       SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS ok,
       SUM(CASE WHEN status='failed'  THEN 1 ELSE 0 END) AS fail
FROM transactions;
""", "Q1: Volumen general de las últimas 2h")

# =====================================================================
# Q2: Timeline por minuto - ¿cuándo se dispara el problema?
# =====================================================================
run("""
SELECT substr(created_at, 1, 16) AS minuto,
       SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS ok,
       SUM(CASE WHEN status='failed'  THEN 1 ELSE 0 END) AS fail,
       COUNT(*) AS total,
       ROUND(100.0 * SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_fail
FROM transactions
GROUP BY minuto
ORDER BY minuto;
""", "Q2: Timeline por minuto (dónde salta la curva)")

# =====================================================================
# Q3: Descomposición por proveedor + biller - ¿qué combinación falla?
# =====================================================================
run("""
SELECT provider,
       biller_id,
       COUNT(*) AS total,
       SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS fallidas,
       ROUND(100.0 * SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_fallo
FROM transactions
GROUP BY provider, biller_id
ORDER BY pct_fallo DESC, total DESC;
""", "Q3: Fallo por proveedor + biller (ventana completa)")

# =====================================================================
# Q4: LA pregunta clave - ¿es solo FinCore o afecta a más partners?
# =====================================================================
run("""
SELECT partner_id,
       provider,
       COUNT(*) AS total,
       SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS fallidas,
       ROUND(100.0 * SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_fallo
FROM transactions
WHERE created_at >= '2024-11-12 14:09:00'
GROUP BY partner_id, provider
ORDER BY partner_id, provider;
""", "Q4: Fallo cruzado partner x provider desde el inicio del incidente")

# =====================================================================
# Q5: Control - ¿los partners tienen éxito con OTROS proveedores?
# Prueba de que el problema no es del partner sino del proveedor.
# =====================================================================
run("""
SELECT provider,
       COUNT(*) AS total,
       SUM(CASE WHEN status='success' THEN 1 ELSE 0 END) AS ok,
       SUM(CASE WHEN status='failed'  THEN 1 ELSE 0 END) AS fail
FROM transactions
WHERE created_at >= '2024-11-12 14:09:00'
GROUP BY provider;
""", "Q5: Control - performance por proveedor desde T0 (openpay debería seguir sano)")

# =====================================================================
# Q6: Firma del error - ¿hay un patrón consistente?
# =====================================================================
run("""
SELECT error_code,
       error_message,
       COUNT(*) AS ocurrencias
FROM transactions
WHERE status='failed'
GROUP BY error_code, error_message;
""", "Q6: Firma del error (mismo código, mismo mensaje = comportamiento sistemático)")

# =====================================================================
# Q7: Primera transacción fallida (T0 exacto)
# =====================================================================
run("""
SELECT id, created_at, partner_id, biller_id, provider, error_code
FROM transactions
WHERE status='failed'
ORDER BY created_at ASC
LIMIT 3;
""", "Q7: Primeras 3 transacciones fallidas (T0 del incidente)")

# =====================================================================
# Análisis de logs - confirmación cruzada
# =====================================================================
print(f"\n{'='*70}\nANÁLISIS DE LOGS (app.log)\n{'='*70}")

log_lines = LOG_FILE.read_text().strip().split("\n")
errors = [l for l in log_lines if "ERROR" in l]
retries = [l for l in errors if "attempt=" in l]

# Latencias en errores
latencies = []
for l in errors:
    m = re.search(r'latency=(\d+)ms', l)
    if m:
        latencies.append(int(m.group(1)))

print(f"Total de líneas en el log: {len(log_lines)}")
print(f"Líneas de ERROR:           {len(errors)}")
print(f"Con marca 'attempt=X/3':   {len(retries)}")
print(f"Latencia mínima error:     {min(latencies)}ms")
print(f"Latencia máxima error:     {max(latencies)}ms")
print(f"Latencia promedio error:   {sum(latencies)//len(latencies)}ms")
print(f"\n→ Firma: timeout consistente ~30000ms = cutoff del sistema, no error random")

# Reintentos
print("\nEjemplo de la cadena de reintentos (txn-011):")
for l in log_lines:
    if "txn-011" in l:
        print(f"  {l}")

# Provider vs status en logs
from collections import Counter
provider_status = Counter()
for l in log_lines:
    prov_m = re.search(r'provider=(\w+)', l)
    stat_m = re.search(r'status=(\w+)', l)
    if prov_m and stat_m:
        provider_status[(prov_m.group(1), stat_m.group(1))] += 1

print("\nCross-check log: provider x status")
for (prov, stat), n in sorted(provider_status.items()):
    print(f"  {prov:10} {stat:10} {n}")

conn.close()
