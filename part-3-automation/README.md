# Parte 3 — Automatización de detección en n8n

**Objetivo:** detectar incidentes de proveedor+biller antes de que el partner reporte.

---

## TL;DR

Flujo de n8n que corre cada 5 minutos, consulta la DB para detectar si algún biller+proveedor superó el 30% de tasa de error en los últimos 15 minutos, y — si es así — envía una alerta enriquecida por Claude al canal interno de monitoreo en Slack. Incluye deduplicación para no spamear el canal con el mismo incidente.

**Impacto esperado:** reducir el gap de 23 minutos que se dio en el caso analizado en la Parte 1 (T0 a las 14:09, reporte del cliente a las 14:32) a un máximo de 5 minutos (el intervalo del cron).

---

## Cómo pensé el flujo

El desafío principal era decidir **qué le pido a Claude y qué le pido a SQL**. Mi primera intuición fue pasarle toda la data a Claude cada 5 minutos para que analice y decida si hay incidente. Cuando lo repensé, vi que eso tenía tres problemas: gasto innecesario de tokens en las corridas sin incidente, latencia más alta que una query directa, y menos determinismo (SQL siempre da el mismo resultado, Claude puede variar sutilmente).

La decisión final fue **separar detección de resumen**: SQL detecta con una regla dura (umbral de 30% en ventana de 15 min), y Claude solo entra al ruedo cuando hay algo que reportar, para traducir los datos crudos en un mensaje ejecutivo accionable.

Ese diseño tiene tres ventajas concretas:

1. **Ahorra tokens**: en un día normal sin incidentes, Claude nunca se llama.
2. **Es más rápido**: la mayoría de las corridas terminan en el primer nodo IF.
3. **Aporta valor donde realmente importa**: Claude no reemplaza al SQL en detección, sino que traduce los datos a lenguaje humano y sugiere severidad.

---

## Diagrama del flujo

![Diagrama del flujo n8n](diagram.png)

*Screenshot del canvas de n8n con los 8 nodos configurados y conectados.*

---

## Los 8 nodos y qué hace cada uno

### 1. Schedule Trigger — `Every 5 min`

Cron que dispara el flujo cada 5 minutos. Es el heartbeat del sistema. No requiere lógica adicional.

### 2. SQL — `SQL: detect threshold`

Consulta la tabla `transactions` de los últimos 15 minutos y devuelve las combinaciones biller+proveedor que superen el 30% de tasa de error, con un piso mínimo de 5 transacciones para evitar falsos positivos por muestras chicas.

```sql
SELECT
  provider,
  biller_id,
  COUNT(*) AS total,
  SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS fallidas,
  ROUND(100.0 * SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) / COUNT(*), 1) AS pct_fallo,
  MIN(created_at) AS ventana_desde,
  MAX(created_at) AS ventana_hasta,
  STRING_AGG(DISTINCT partner_id, ', ') AS partners_afectados
FROM transactions
WHERE created_at >= NOW() - INTERVAL '15 minutes'
GROUP BY provider, biller_id
HAVING
  COUNT(*) >= 5
  AND (100.0 * SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) / COUNT(*)) > 30;
```

Nota: el JSON del flujo asume Postgres como motor de DB. En un contexto productivo real, la query apuntaría a una réplica de solo lectura o al data warehouse, nunca a la DB primaria de producción.

### 3. IF — `IF: has incident?`

Si la query devolvió filas → hay incidente, seguir. Si vino vacía → cortar el flujo. En un día normal sin incidentes, la mayoría del tiempo el flujo termina acá, sin consumir ningún recurso adicional.

### 4. SQL — `SQL: check dedupe`

Consulta la tabla auxiliar `alert_history` para saber si ya alertamos este mismo incidente (misma combinación `provider-biller`) en los últimos 30 minutos.

```sql
SELECT COUNT(*) AS recent_alerts
FROM alert_history
WHERE alert_key = '{{ provider }}-{{ biller_id }}'
  AND sent_at >= NOW() - INTERVAL '30 minutes';
```

La clave compuesta `provider-biller` permite que incidentes distintos que ocurran simultáneamente (ej: Nexopay+CFE y Openpay+TELMEX al mismo tiempo) se traten como incidentes independientes y no se dedupliquen entre sí.

### 5. IF — `IF: already alerted?`

Si ya hubo una alerta reciente para este incidente → cortar. Si es la primera detección → seguir hacia Claude.

### 6. HTTP Request — `Claude: generate summary`

Llamada a la API de Claude con un prompt que le pasa los datos del incidente y le pide un resumen ejecutivo en formato Slack. El prompt está diseñado para que Claude genere una estructura consistente con severidad sugerida y próxima acción, no un texto libre variable.

El prompt sigue este formato:

```
Sos un asistente de soporte técnico en una fintech de pagos B2B.
Se detectó un posible incidente en la infraestructura de pagos.

Datos del incidente:
- Proveedor: {{ provider }}
- Biller: {{ biller_id }}
- Total transacciones en la ventana: {{ total }}
- Fallidas: {{ fallidas }}
- Tasa de fallo: {{ pct_fallo }}%
- Ventana temporal: desde {{ ventana_desde }} hasta {{ ventana_hasta }}
- Partners afectados: {{ partners_afectados }}

Generá un mensaje corto y accionable para el canal interno de monitoreo en Slack.
Formato esperado:
:rotating_light: *Incidente detectado*
*Qué:* [una línea sobre qué está fallando]
*Desde:* [ventana temporal]
*Impacto:* [cantidad + partners]
*Severidad sugerida:* [P1/P2/P3] — [criterio breve]

```

### 7. Slack — `Slack: send alert`

Envía el mensaje generado por Claude al canal interno `#alerts-support`. Solo canal interno, nunca directo al cliente. La comunicación con el partner queda como decisión humana después de revisar la alerta.

### 8. SQL — `SQL: log alert`

Inserta una entrada en `alert_history` con el `alert_key` y el timestamp. Esto habilita la deduplicación de las próximas 30 minutos.

```sql
INSERT INTO alert_history (alert_key, sent_at)
VALUES ('{{ provider }}-{{ biller_id }}', NOW());
```

---

## Decisiones de diseño

### Por qué SQL detecta y Claude resume

Alternativa considerada: mandar toda la data a Claude en cada corrida y que él decida si hay incidente. Descartada por costo (llamadas innecesarias), latencia y determinismo. La decisión del umbral es una regla matemática — no necesita LLM.

### Por qué el piso de 5 transacciones

Sin ese piso, 1 fallo de 1 transacción daría 100% de tasa de error y sería un falso positivo constante. Con 5 mínimo, se filtra el ruido de baja actividad sin comprometer la sensibilidad para incidentes reales.

### Por qué el cool-down de 30 minutos

Si el incidente dura más de 30 minutos, se dispara una nueva alerta como recordatorio activo. Menos que eso hubiera generado spam en el canal; más hubiera dejado incidentes de larga duración sin visibilidad recurrente.

### Por qué alertar solo al canal interno

Un humano confirma el incidente antes de notificar al partner. Las razones:

- Evitar falsos positivos hacia clientes enterprise (el costo reputacional es alto).
- La comunicación al partner requiere criterio: modular tono, agregar contexto, confirmar magnitud.
- El diseño del challenge lo sugiere: la Parte 2 del challenge (mensaje al partner) es un paso separado, humano.

### Por qué la clave de dedupe es `provider-biller`

Dos incidentes simultáneos en combinaciones distintas (ej: Nexopay+CFE y Openpay+TELMEX cayéndose al mismo tiempo) son problemas independientes y merecen alertas separadas. La clave compuesta permite esa granularidad.

---

## Impacto medible

En el caso analizado en la Parte 1, el gap entre el inicio del incidente (14:09:33) y el reporte del cliente (14:32) fue de **23 minutos**. Con este flujo activo, el gap máximo entre el inicio del incidente y la detección interna es de **5 minutos** (el intervalo del cron).

En términos técnicos, este flujo baja el MTTD (Mean Time To Detect) de ~23 min a <5 min para este tipo específico de incidente (degradación de rail proveedor+biller).

---

## Cómo importar el flujo en n8n

1. Abrir n8n (local o n8n.cloud).
2. Menú superior → **Workflows** → **Import from File**.
3. Seleccionar `workflow.json`.
4. El flujo aparece en el canvas con los 8 nodos conectados.
5. Configurar las credenciales en cada nodo:
   - **Postgres** (nodos SQL): host, port, user, password, database.
   - **Anthropic API** (nodo Claude): API key.
   - **Slack OAuth2** (nodo Slack): conexión al workspace + canal `#alerts-support`.
6. Crear la tabla `alert_history` en la DB:

```sql
CREATE TABLE alert_history (
  id SERIAL PRIMARY KEY,
  alert_key VARCHAR(100) NOT NULL,
  sent_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_alert_history_key_time
  ON alert_history (alert_key, sent_at);
```

7. Activar el workflow desde el toggle superior.

---

## Herramientas usadas

- **n8n Cloud** (trial gratuito) para armar y probar el flujo visualmente.
- **Claude** integrado vía HTTP Request al endpoint `api.anthropic.com/v1/messages`, para generar los mensajes de alerta en lenguaje natural. El prompt está diseñado para producir output consistente en formato Slack.
- **Postgres** como motor de DB asumido (podría adaptarse fácilmente a MySQL o SQLite ajustando la sintaxis de las queries).

## Limitaciones conocidas

- **Credenciales placeholder**: el JSON exportado tiene IDs de credencial que hay que reemplazar por credenciales reales al importar (Postgres, Anthropic, Slack). Los IDs actuales sirven como referencia de qué integraciones necesita configurar el evaluador.
- **Umbral fijo**: el 30% está harcodeado en la query. En producción sería útil parametrizarlo por biller (ej: CFE 30%, telcos 40%) para modular la sensibilidad según volumen y criticidad de cada rail.
- **Sin escalamiento automático**: el flujo alerta pero no escala automáticamente. La decisión de escalar a Vendor Ops queda como paso humano posterior. Es intencional, por las razones descritas en "Por qué alertar solo al canal interno".
