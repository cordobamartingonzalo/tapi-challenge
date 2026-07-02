# Parte 3 — Automatización de detección en n8n

**Objetivo:** detectar incidentes de proveedor+biller antes de que el partner reporte.

---

## TL;DR

Flujo de n8n que corre cada 5 minutos, consulta la DB para detectar si algún biller+proveedor superó el 30% de tasa de error en los últimos 15 minutos, y — si es así — envía una alerta enriquecida por Claude al canal interno de monitoreo en Slack. Incluye deduplicación para no spamear el canal con el mismo incidente.

**Impacto esperado:** reducir el gap de 23 minutos que se dio en el caso analizado en la Parte 1 (T0 a las 14:09, reporte del cliente a las 14:32) a un máximo de 5 minutos (el intervalo del cron).

---

## Cómo pensé el flujo

El desafío principal era decidir **qué le pido a Claude y qué le pido a SQL**. Mi primera intuición fue pasarle toda la data a Claude cada 5 minutos para que analice y decida si hay incidente. Cuando lo repensé, vi que eso tenía tres problemas: 
1. Gasto innecesario de tokens en las corridas sin incidente.
2. Latencia más alta que una query directa.
3. Menos determinismo (SQL siempre da el mismo resultado, Claude puede variar sutilmente).

La decisión final fue **separar detección de resumen**: SQL detecta con una regla dura (tasa de error de 30% en ventana de 15 min), y Claude solo entra al ruedo cuando hay algo que reportar, para traducir los datos crudos en un mensaje de Slack.

Ese diseño tiene tres ventajas concretas:

1. **Ahorra tokens**: en un día normal sin incidentes, Claude nunca se llama.
2. **Es más rápido**: Si no hay incidente, el flujo se corta.
3. **Aporta valor donde realmente importa**: Claude no reemplaza al SQL en detección, sino que traduce los datos a lenguaje humano y sugiere severidad.

---

## Diagrama del flujo

[Diagrama del flujo]

<img width="2303" height="1429" alt="Untitled-2026-07-02-1336" src="https://github.com/user-attachments/assets/357a5151-b696-46ad-b293-d768cf072c23" />



---

## Los 8 nodos y qué hace cada uno

### 1. Schedule Trigger — `Every 5 min`

Nodo que dispara el flujo cada 5 minutos. 

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

Nota: el JSON del flujo asume Postgres como motor de DB.

### 3. IF — `IF: has incident?`

Si la query devolvió filas → hay incidente, seguir. 
Si vino vacía → cortar el flujo. En un día normal sin incidentes, la mayoría del tiempo el flujo termina acá, sin consumir ningún recurso adicional.

### 4. SQL — `SQL: check dedupe`

Antes de disparar una alerta a Slack, pensé en que habría que saber si este mismo 
incidente ya fue reportado hace poco. Sin esta verificación, el flujo 
mandaría una alerta cada 5 minutos mientras el incidente siga activo, 
saturando el canal.

Para resolverlo generé una tabla auxiliar `alert_history` que cumple dos 
funciones: 
1. Registrar cada incidente alertado (lo hace el último nodo del 
flujo)
2. Ser consultada en cada nueva ejecución para verificar si ese 
mismo incidente ya fue notificado.

​```sql
SELECT COUNT(*) AS recent_alerts
FROM alert_history
WHERE alert_key = '{{ provider }}-{{ biller_id }}'
  AND sent_at >= NOW() - INTERVAL '30 minutes';
​```

La `alert_key` es la combinación `provider-biller` porque el incidente no 
está definido por una transacción individual sino por el rail que se cae. 
Cuando falla Nexopay hacia CFE, todas las transacciones que pasan por ahí 
fallan juntas — para el sistema es un solo incidente, no 20 separados.
### 5. IF — `IF: already alerted?`

Si ya hubo una alerta reciente para este incidente → cortar. Si es la primera detección → seguir hacia Claude.

### 6. HTTP Request — `Claude: generate summary`

Llamada a la API de Claude con un prompt que le pasa los datos del incidente y le pide un resumen ejecutivo en formato de mensaje para Slack. El prompt está diseñado para que Claude genere un mensaje estructurado

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

La detección del incidente la resuelvo con SQL, en el nodo `SQL: detect 
threshold` (el umbral del 30% con piso de 5 transacciones). Claude entra 
al ruedo solo cuando ya hay algo que reportar, para traducir los datos 
crudos en un mensaje ejecutivo accionable con sugerencia de severidad y 
próximos pasos.

### Por qué el piso de 5 transacciones

Sin ese piso, 1 fallo de 1 transacción daría 100% de tasa de error y sería un falso positivo constante. Con 5 mínimo, se filtra el ruido de baja actividad sin comprometer la sensibilidad para incidentes reales.

### Por qué el cool-down de 30 minutos

Si el incidente dura más de 30 minutos, se dispara una nueva alerta como recordatorio activo. Menos que eso hubiera generado spam en el canal; más hubiera dejado incidentes de larga duración sin visibilidad recurrente.

### Por qué alertar solo al canal interno

Un humano confirma el incidente antes de notificar al partner. Las razones:

- Evitar falsos positivos hacia clientes enterprise.
- La comunicación al partner requiere criterio.

### Por qué la clave de dedupe es `provider-biller`

Dos incidentes simultáneos en combinaciones distintas (ej: Nexopay+CFE y Openpay+TELMEX cayéndose al mismo tiempo) son problemas independientes y merecen alertas separadas. La clave compuesta permite esa granularidad.

---

## Impacto medible

En el caso analizado en la Parte 1, el gap entre el inicio del incidente (14:09:33) y el reporte del cliente (14:32) fue de **23 minutos**. Con este flujo activo, el gap máximo entre el inicio del incidente y la detección interna es de **5 minutos** (el intervalo del cron).

En términos técnicos, este flujo baja el MTTD (Mean Time To Detect) de ~23 min a <5 min para este tipo específico de incidente.

---

## Cómo importar el flujo en n8n

1. Abrir n8n (local o n8n.cloud).
2. Menú superior → **Workflows** → **Import from File**.
3. Seleccionar `workflow-challenge.json`.
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

- **n8n Cloud** para armar y probar el flujo visualmente.
- **Claude** integrado vía HTTP Request al endpoint `api.anthropic.com/v1/messages`, para generar los mensajes de alerta. El prompt está diseñado para producir output consistente en formato para un mensaje de Slack.
- **Postgres** como motor de DB asumido (podría adaptarse fácilmente a MySQL o SQLite ajustando la sintaxis de las queries).

## Limitaciones conocidas

- **Credenciales placeholder**: el JSON exportado tiene IDs de credencial que hay que reemplazar por credenciales reales al importar (Postgres, Anthropic, Slack). Los IDs actuales son solo de referencia.
- **Umbral fijo**: el 30% está harcodeado en la query. En producción sería útil parametrizarlo por biller (ej: CFE 30%, telcos 40%) para modular la sensibilidad según volumen y criticidad de cada rail.
- **Sin escalamiento automático**: el flujo alerta pero no escala automáticamente. La decisión de escalar al equipo responsable (Equipo de relación técnica con Nexopay) queda como paso humano posterior. Es intencional, por las razones descritas en "Por qué alertar solo al canal interno".

---

## Futuras features

### 1. Umbral parametrizable por biller

Hoy el 30% está hardcodeado en la query. En producción lo movería a una 
tabla de configuración (`biller_thresholds`) donde cada biller tenga su 
propio umbral según volumen y criticidad.

### 2. Claim de alerta desde Slack

Sumar un botón "Tomar incidente" al mensaje de Slack que envía Claude. 
Al hacer click, el bot actualiza el mensaje mostrando quién tomó el 
incidente y a qué hora. Evita que dos personas del equipo empiecen a 
trabajar en paralelo sin saber que el otro ya se hizo cargo, y deja 
trazabilidad de quién estuvo a cargo de cada incidente.

### 3. Dashboard de MTTD/MTTR

Un dashboard (Con Looker Studio / Metabase / Otra herramienta de visualización) con métricas del flujo: cuántas alertas 
por semana, tiempo promedio entre detección y resolución, false positive 
rate. Sirve para iterar el umbral y detectar patrones.
