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
  - `LLEIDA_USER`
  - `LLEIDA_SMS_API_KEY` (API Key del servicio **Send SMS**)
  - `LLEIDA_MESSAGES_API_KEY` (API Key del servicio **Messages**)

Lleida.net suele requerir **API Keys distintas por servicio** (Send SMS vs Messages).

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

- `LLEIDA_USER`
- `LLEIDA_SMS_API_KEY`
- `LLEIDA_MESSAGES_API_KEY`

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

- `LLEIDA_API_BASE_URL` (default `https://api.lleida.net/`)
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
streamlit run app.py --server.address 0.0.0.0 --server.port $PORT
```

3) Configura las **Environment Variables**:
- `LLEIDA_USER`
- `LLEIDA_SMS_API_KEY`
- `LLEIDA_MESSAGES_API_KEY`
- (opcional) `DATABASE_URL`
- (opcional) `SEED_USERS_JSON`

> Persistencia: si usas SQLite en App Platform, podrías perder datos en redeploy. Para producción, usa `DATABASE_URL` con Postgres.

---

## 6) Seguridad / Buenas prácticas

- Cambia contraseñas por defecto (o usa `SEED_USERS_JSON` con contraseñas fuertes).
- No subas credenciales a Git.
- Si vas a restringir por red (VPC / IPs), hazlo en DigitalOcean; la app no aplica filtros por IP.
