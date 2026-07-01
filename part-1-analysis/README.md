# Parte 1 — Análisis del incidente

**Autor:** Gonzalo
**Fecha del incidente:** 12/11/2024
**Reporte inicial:** FinCore, 14:32 UTC vía canal de soporte
**Tiempo de análisis:** ~40 min

---

## TL;DR

A las **14:09:33 UTC** el proveedor **Nexopay** empezó a devolver timeouts consistentes de 30s para el biller **CFE**. Desde ese momento, **el 100% de las transacciones ruteadas por Nexopay hacia CFE están fallando**, y esto afecta al menos a dos partners (FinCore y `other_partner`), no solo a FinCore.

El síntoma que reportó FinCore ("fallan pagos de CFE") es correcto pero incompleto: el problema no es de CFE ni de FinCore, es del proveedor upstream. Cualquier partner que use Nexopay para CFE está siendo impactado.

**Clasificación propuesta:** **P1**.
**Escalar a:** equipo que gestiona la relación técnica con Nexopay (Vendor Ops / Provider Integrations).

---

## 1. ¿Cuándo empezó?

Timeline por minuto (query `Q2`):

```
minuto              ok   fail   pct_fail
14:07               1     0      0.0%
14:09               0     1      100%   ← T0
14:10               1     1      50%
14:11               1     1      50%
14:12               0     2      100%
14:13               1     1      50%
14:14               0     2      100%
...
14:24               0     1      100%
```

**T0 del incidente:** `2024-11-12 14:09:33 UTC` — transacción `txn-011` (`fincore` / `CFE` / `nexopay`).

Antes de las 14:09 no hay un solo fallo en toda la ventana de 2h. El cambio es abrupto, no una degradación progresiva.

Las filas donde ves 50% de fail en un minuto no son "el problema mejorando": son minutos donde hubo una transacción CFE/Nexopay (fallada) y otra por Openpay (exitosa) mezcladas. Filtrando por proveedor, Nexopay cae al 100% de fallo y no se recupera.

---

## 2. ¿Qué biller, proveedor y error están involucrados?

Descomposición por proveedor + biller desde T0 (query `Q3`):

```
provider   biller_id    total   fallidas   pct_fallo
nexopay    CFE          29      23         79.3%   ← todo el incidente
openpay    TELMEX       4       0          0.0%
openpay    IZZI         4       0          0.0%
openpay    TOTALPLAY    3       0          0.0%
```

El 79.3% agregado incluye las transacciones exitosas previas a T0. Si acoto la ventana desde 14:09 en adelante:

```
provider   total   ok   fail
nexopay    23      0    23    ← 100% fallo
openpay    7       7    0
```

- **Biller afectado:** CFE (categoría `electricity`).
- **Proveedor afectado:** Nexopay.
- **Error:** `PROVIDER_TIMEOUT` — "Connection timed out after 30000ms".

Todos los fallos, sin excepción, tienen exactamente el mismo `error_code` y el mismo `error_message` (query `Q6`). No hay dispersión. Eso es firma clara de un problema sistemático del lado del proveedor, no de errores random del sistema.

---

## 3. ¿Afecta a todos los partners o solo a FinCore? ¿Por qué importa?

**Afecta a más de un partner.** Esta es la pieza más importante del análisis (query `Q4`):

```
partner_id       provider   total   fallidas   pct_fallo
fincore          nexopay    20      20         100%
fincore          openpay    7       0          0%
other_partner    nexopay    3       3          100%
```

Dos lecturas clave de esta tabla:

1. **`other_partner` también está fallando el 100% cuando usa Nexopay.** FinCore no es un caso aislado — cualquier partner ruteando por Nexopay hacia CFE está viendo lo mismo. Nadie más nos avisó porque probablemente tienen menos volumen o su alerting es más lento.
2. **FinCore sigue procesando pagos exitosos por Openpay** (TELMEX, IZZI, TOTALPLAY). Eso descarta problema del lado de FinCore: su integración con Tapi está OK.

Por qué importa esta distinción:
- **Cambia a quién escalás.** Si fuera solo FinCore, escalaría a Integraciones o al account manager. Como es cross-partner por un proveedor, escala directo a Vendor Ops / Provider Integrations, que son quienes tienen contacto técnico con Nexopay.
- **Cambia el mensaje al cliente.** No podemos decirle a FinCore "es un problema de tu integración" ni "es un problema de CFE". Tampoco podemos mencionar a los otros partners afectados (info confidencial). El mensaje tiene que ser honesto sobre lo que estamos viendo del lado nuestro sin comprometer a nadie.
- **Cambia la prioridad.** Un incidente que afecta a un partner es P2. Un incidente que afecta a múltiples partners en un servicio core (procesamiento de pagos) es P1.
- **Cambia la comunicación posterior.** Probablemente haya que proactivamente avisar a los demás partners afectados por Nexopay/CFE en vez de esperar a que reporten uno por uno.

---

## 4. Patrón que confirma la hipótesis

Tres piezas de evidencia que apuntan al mismo lugar:

### 4.1 Latencia idéntica en todos los fallos

Del `app.log`:

```
Total ERROR lines:        26
Latencia mínima:          30001ms
Latencia máxima:          30003ms
Latencia promedio:        30001ms
```

Un timeout de 30s clavado en todas las transacciones no es "el proveedor está lento". Es el sistema de Tapi haciendo cutoff al llegar al límite configurado. Nexopay no está respondiendo — o está respondiendo tarde de forma consistente.

### 4.2 Sistema de retry ejecutándose correctamente

Ejemplo de `txn-011` en los logs:

```
14:09:33Z ERROR ... attempt=1/3
14:09:34Z ERROR ... attempt=2/3
14:09:35Z ERROR ... attempt=3/3
```

El servicio de pagos está reintentando 3 veces por transacción, como corresponde. Los 3 intentos fallan con el mismo error. Confirma que:
- El sistema interno de Tapi funciona bien (hace lo que debe).
- El problema no es un blip transitorio: reintentar no cambia el resultado.

### 4.3 Cross-check openpay: sigue verde

Durante toda la ventana del incidente, Openpay procesa transacciones con éxito y latencias normales (700-900ms). Eso descarta:
- Problema de red en el datacenter de Tapi.
- Problema del servicio de pagos en general.
- Problema con el manejo de timeouts.

El problema está localizado en el link Tapi → Nexopay.

---

## Clasificación y escalamiento

**Severidad: P1**

Criterios que uso:
- Servicio core (procesamiento de pagos) caído para un flujo específico.
- Múltiples partners impactados (mínimo 2 confirmados, posiblemente más).
- Impacto directo en el usuario final: no pueden pagar la luz.
- Impacto financiero: cada transacción fallida es revenue perdido para Tapi y para los partners.
- Reputacional: uno de los partners más grandes ya se quejó, otros probablemente lo hagan.

**A qué equipo escalar primero: Vendor Ops / Provider Integrations (el equipo que maneja Nexopay).**

Por qué no otros equipos:
- **Producto/Ingeniería:** no es un bug del código de Tapi. El servicio de pagos está funcionando, reintenta, loguea, hace cutoff correctamente. Meter a Ingeniería sin evidencia de bug es desperdiciar su tiempo.
- **Data:** los datos están limpios y consistentes.
- **Cuenta/Comercial (FinCore):** son consumidores del update, no responsables técnicos. Los mantengo informados vía Parte 2, pero no los pongo en la línea de resolución.

Acciones inmediatas paralelas al escalamiento:
1. Verificar si Nexopay tiene status page pública o algún aviso de incidente.
2. Confirmar si Tapi ya tiene contacto técnico abierto con ellos.
3. Identificar todos los partners que usen Nexopay+CFE para poder comunicar proactivamente.
4. Evaluar si técnicamente es viable rutear temporalmente CFE por Openpay (si Openpay soporta CFE) como mitigación.

---

## Queries SQL utilizadas

Todas las queries están en `queries/`. Las más relevantes:

- `queries/01_timeline.sql` — Timeline por minuto (T0).
- `queries/02_provider_biller.sql` — Descomposición por proveedor+biller.
- `queries/03_cross_partner.sql` — La query clave: partner × provider desde T0.
- `queries/04_error_signature.sql` — Firma del error.
- `queries/05_t0_exact.sql` — Primera transacción fallida al segundo exacto.

El script `analysis.py` corre todo el pipeline (carga SQL en SQLite in-memory + parsea logs) y reproduce los outputs de este documento. Requiere solo Python 3.8+.

```bash
python3 analysis.py
```
