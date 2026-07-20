# FrontEnd SMS v2 (Streamlit) — Legal / Negocios

Aplicación web (Streamlit) para **enviar SMS individuales y masivos**, cargando un Excel con números y (opcionalmente) textos personalizados.

Integra:
- **Lleida.net Send SMS API v2** (envío)
- **Lleida.net Messages API v3** (consulta de estados / MT)

> Nota: esta versión es **más simple**: no incluye política de acceso por IP (AUTH_POLICY/ALLOWED_IPS).
> Si vas a limitar el acceso con una **VPC / red privada** en DigitalOcean, esto suele ser suficiente.
>
> Aun así, la app mantiene **login por usuario** para poder **segmentar**: cada área ve solo sus envíos.

---

## 1) Requisitos

- Python 3.10+ (recomendado 3.11)
- Credenciales Lleida.net:
  - `SMS_API_USER`
  - `SMS_API_PASSWORD`

---

## 2) Ejecutar localmente

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# (opcional) cargar variables de entorno
cp .env.example .env
# edita .env y después:
export $(cat .env | xargs)

streamlit run app.py
```

Por defecto, si no existe base de datos, se usa SQLite en `./data/app.db`.

---

## 3) Variables de entorno

### Obligatorias (para enviar y consultar estado)

- `SMS_API_USER`
- `SMS_API_PASSWORD`

### Recomendadas

- `DATABASE_URL` — por ejemplo Postgres (Managed DB). Si no existe, usa SQLite.
- `SEED_USERS_JSON` — crea usuarios en el primer arranque (si no hay usuarios en DB).

Ejemplo `SEED_USERS_JSON`:

```json
[
  {"username":"admin","password":"ChangeMeNow!","department":"Admin","role":"admin"},
  {"username":"vladimir","password":"ChangeMeNow!","department":"Negocios","role":"user"},
  {"username":"lisaura","password":"ChangeMeNow!","department":"Legal","role":"user"}
]
```

### Opcionales

- `SMS_API_URL` (default `https://api.lleida.net/sms/v2/`)
- `MAX_BULK_ROWS` (default `5000`)
- `DEFAULT_SENDER` (default vacío)
- `AUTO_SEED_USERS` (default `true`) — si lo pones `false`, no crea usuarios por defecto.

---

## 4) Excel de carga

La app permite:
- **Masivo**: columna de teléfono + un texto común.
- **Personalizado**: columna de teléfono + columna de mensaje.

Columnas típicas:
- `phone` (o `telefono`, `msisdn`, etc.)
- `message` (o `mensaje`, `txt`, etc.)

La app te deja elegir qué columna corresponde a cada campo.

---

## 5) DigitalOcean App Platform (sin Docker)

Esta versión está pensada para ejecutarse como un **Streamlit app normal** (sin Dockerfile).

En DigitalOcean App Platform:

1) Crea la app desde tu repo (GitHub).

2) En el componente, configura el **Run Command** como:

```bash
python -m src.service
```

3) Configura las **Environment Variables**:
- `SMS_API_USER`
- `SMS_API_PASSWORD`
- (opcional) `DATABASE_URL`
- (opcional) `SEED_USERS_JSON`

> Persistencia: si usas SQLite en App Platform, podrías perder datos en redeploy. Para producción, usa `DATABASE_URL` con Postgres.

---

## 6) Seguridad / Buenas prácticas

- Cambia contraseñas por defecto (o usa `SEED_USERS_JSON` con contraseñas fuertes).
- No subas credenciales a Git.
- Si vas a restringir por red (VPC / IPs), hazlo en DigitalOcean; la app no aplica filtros por IP.

---

## 7) Elegibilidad de clientes y campañas automáticas

La sección **Clientes SMS** permite consultar tres listas desde la API interna:

- Clientes autorizados para recibir SMS.
- Clientes con préstamos que finalizan dentro de la ventana configurada.
- Clientes morosos.

La integración falla de forma segura: un cliente solo se considera elegible cuando
la API devuelve de forma explícita un campo de autorización SMS verdadero. También
se respeta cualquier campo de opt-out.

### API de clientes

Configura una URL base o URLs independientes:

- `CUSTOMER_API_BASE_URL`
- `CUSTOMER_API_ELIGIBLE_URL`
- `CUSTOMER_API_LOAN_ENDING_URL`
- `CUSTOMER_API_DELINQUENT_URL`

Autenticación opcional:

- `CUSTOMER_API_TOKEN` — se envía como Bearer token.
- `CUSTOMER_API_KEY`
- `CUSTOMER_API_KEY_HEADER` — default `X-API-Key`.
- `CUSTOMER_API_HEADERS_JSON` — objeto JSON con headers adicionales.
- `CUSTOMER_API_TIMEOUT_S` — default `30`.
- `CUSTOMER_API_VERIFY_SSL` — default `true`.

Si solo se configura `CUSTOMER_API_BASE_URL`, la app consulta:

- `/sms/eligible`
- `/sms/loan-ending?days=30`
- `/sms/delinquent?min_days=1`

La respuesta puede ser una lista o un objeto que contenga `data`, `results`,
`items`, `customers`, `clientes` o `records`. Se reconocen nombres de campos
comunes en inglés y español, por ejemplo `customer_id`/`cliente_id`,
`phone`/`telefono`, `sms_allowed`/`sms_autorizado`,
`loan_end_date`/`fecha_fin_prestamo` y `days_past_due`/`dias_mora`.

### Envío automático

El mismo contenedor ejecuta un worker liviano, por lo que no añade otro componente
de App Platform. Variables:

- `AUTO_SMS_ENABLED` — default `false`.
- `AUTOMATION_TIMEZONE` — default `America/Santo_Domingo`.
- `AUTOMATION_HOUR` — hora local diaria, default `9`.
- `AUTOMATION_USERNAME` — usuario propietario de las campañas, default `admin`.
- `LOAN_ENDING_DAYS` — default `30`.
- `DELINQUENT_MIN_DAYS` — default `1`.
- `LOAN_ENDING_SMS_TEMPLATE`
- `DELINQUENT_SMS_TEMPLATE`

Las plantillas aceptan `{name}`, `{customer_id}`, `{loan_id}`,
`{loan_end_date}` y `{days_past_due}`.

La automatización registra una clave única por cliente y episodio de préstamo para
evitar duplicados. Por esa razón, antes de activar `AUTO_SMS_ENABLED=true` se
requiere un `DATABASE_URL` persistente. SQLite en App Platform es efímero; el
worker se negará a enviar automáticamente con SQLite salvo que se establezca de
forma explícita `ALLOW_EPHEMERAL_AUTOMATION=true`.
