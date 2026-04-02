# Documentación del Proyecto: GEMA

## Visión General
**Objetivo del proyecto:** SaaS multi‑tenant para reservas por WhatsApp.

* **Backend:** FastAPI asíncrono.
* **Base de datos:** PostgreSQL (Supabase) vía SQLAlchemy + Pydantic.
* **Integraciones:** Google Calendar (service account) y WhatsApp Cloud API (Meta Graph API).
* **Bot:** Máquina de estados y reglas de negocio estrictas para fechas, horarios y zonas horarias.

---

## 1. Stack Técnico

| Componente | Tecnología |
| :--- | :--- |
| **Lenguaje** | Python 3.14 (en máquina local; el código asume 3.10+) |
| **Framework web** | FastAPI |
| **Servidor ASGI** | Uvicorn |
| **ORM** | SQLAlchemy 2.x (async engine con asyncpg) |
| **Validación** | Pydantic v2 + pydantic-settings |
| **Base de datos** | PostgreSQL (Supabase) |
| **Migraciones** | Alembic + psycopg (driver sync para migrar) |
| **WhatsApp** | WhatsApp Cloud API v17 (requests) |
| **Google Calendar** | google-api-python-client + google-auth (service account) |
| **Fechas / NLP** | dateparser, pytz, anyio (para hilos en llamadas síncronas) |

---

## 2. Estructura del Proyecto

```text
.
├── app/
│   ├── api/
│   │   └── v1/
│   │       ├── endpoints/
│   │       │   ├── admin.py
│   │       │   └── webhook.py
│   │       └── router.py
│   ├── core/
│   │   ├── config.py
│   │   ├── database.py
│   │   ├── google_calendar.py
│   │   └── whatsapp.py
│   ├── models/
│   │   ├── booking.py
│   │   └── bot_state.py
│   ├── repositories/
│   │   ├── base_repository.py
│   │   ├── negocio_repository.py
│   │   ├── servicio_repository.py
│   │   ├── paciente_repository.py
│   │   └── cita_repository.py
│   ├── schemas/
│   │   └── booking.py
│   ├── services/
│   │   ├── availability_service.py
│   │   ├── slot_finder.py
│   │   └── state_machine.py
│   ├── utils/
│   │   ├── dateparser_utils.py
│   │   └── phone_utils.py
│   └── main.py
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       ├── 0001_initial.py
│       └── 0002_bot_whatsapp.py (revision: "0002_bot_whatsapp")
├── scripts/
│   ├── test_state_machine.py
│   ├── test_webhook.py
│   ├── test_webhook_select.py
│   ├── test_webhook_confirm_and_cancel.py
│   ├── book_and_cancel_next.py
│   └── test_cancel_by_patient_id.py
├── requirements.txt
├── alembic.ini
├── .env
└── credentials.json
```

---

## 3. Configuración de Entorno

### Archivo `.env` (Ejemplo)

```env
# Base de datos (Supabase)
DB_USER=postgres
DB_PASSWORD=1xxxxxxxx6
DB_NAME=postgres
DB_HOST=db.bsqfbsmdqkgjhsgszldq.supabase.co
DB_PORT=5432
DATABASE_URL=postgresql+asyncpg://postgres:1xxxxxxxx6@db.bsqfbsmdqkgjhsgszldq.supabase.co:5432/postgres

# Google Calendar
GOOGLE_CALENDAR_ID=xxxxxxxxxx@gmail.com
GOOGLE_CALENDAR_SERVICE_ACCOUNT_FILE=credentials.json

# WhatsApp Meta
WHATSAPP_VERIFY_TOKEN="token_seguro_gema_123"
WHATSAPP_PHONE_NUMBER_ID="xxxxxxxxxxxxxxx"
WHATSAPP_ACCESS_TOKEN=TU_TOKEN_DE_META
```

> **Notas Importantes de Configuración:**
> * `DATABASE_URL` debe usar `+asyncpg` para habilitar el modo asíncrono.
> * El carácter `@` en la contraseña debe estar codificado como `%40`.
> * `GOOGLE_CALENDAR_SERVICE_ACCOUNT_FILE` debe apuntar al archivo `credentials.json` correspondiente a la cuenta de servicio.
> * `WHATSAPP_ACCESS_TOKEN` requiere un token válido generado desde la aplicación de WhatsApp Cloud API.

### Configuración de la App (`app/core/config.py`)
El módulo Settings se encarga de cargar las siguientes variables:
* `DATABASE_URL`
* `DEFAULT_TIMEZONE` (valor por defecto: "Europe/Madrid")
* `GOOGLE_CALENDAR_SERVICE_ACCOUNT_FILE`
* `GOOGLE_CALENDAR_APPLICATION_NAME`
* `WHATSAPP_ACCESS_TOKEN`
* `WHATSAPP_VERIFY_TOKEN`

---

## 4. Modelo de Datos (SQLAlchemy / PostgreSQL)

### 4.1 Negocio (`app/models/booking.py`)
* **id:** UUID (Primary Key).
* **nombre_negocio:** str.
* **telefono_bot:** str (coincide con `metadata.display_phone_number` del webhook).
* **whatsapp_phone_id:** str (`phone_number_id` de WhatsApp Cloud API).
* **google_calendar_id:** str (ID del calendario para consultar y crear eventos).
* **config_horario:** JSONB (Mapa de días "0" a "6" con sus intervalos de inicio y fin).
* **zona_horaria:** str (por defecto y server_default: "Europe/Madrid").
* **Relaciones:** `servicios` (lista de Servicio) y `citas` (lista de Cita).

### 4.2 Servicio
* **id:** UUID (Primary Key).
* **negocio_id:** UUID (Foreign Key hacia `negocios.id`, con regla de cascada).
* **nombre:** str.
* **duracion_minutos:** int (duración del servicio en minutos).

### 4.3 Paciente
* **id:** UUID (Primary Key).
* **telefono:** str (Restricción UNIQUE).
* **nombre:** str (Se obtiene de `contacts[0].profile.name` o usa "Paciente" como fallback).

### 4.4 Cita
* **id:** UUID (Primary Key).
* **negocio_id:** UUID (Foreign Key hacia `negocios.id`).
* **paciente_id:** UUID (Foreign Key hacia `pacientes.id`).
* **servicio_id:** UUID (Foreign Key hacia `servicios.id`).
* **fecha_hora:** DateTime con timezone (siempre almacenado en UTC como timestamptz).
* **estado:** str ("CONFIRMADA" o "CANCELADA", por defecto "CONFIRMADA").
* **calendar_event_id:** str (ID del evento en Google Calendar, por defecto "").
* **notas:** Text o None.
* **Restricción clave:** `UniqueConstraint("negocio_id", "fecha_hora", name="uq_citas_negocio_fecha_hora")`.

### 4.5 BotEstado (`app/models/bot_state.py`)
* **telefono:** str (Primary Key).
* **estado:** str (Valores: "None", "ESPERANDO_SERVICIO", "ESPERANDO_FECHA", "ESPERANDO_CANCELACION").
* **negocio_id:** UUID o None.
* **servicio_id:** UUID o None.
* **sugerencia_start_utc:** DateTime con timezone o None.
* **sugerencia_end_utc:** DateTime con timezone o None.
* **cancelacion_citas_ids:** JSONB o None (lista de IDs de citas durante la fase de cancelación).
* **actualizado_at:** timestamptz (por defecto usa `now()`).

---

## 5. Capa de Acceso a Datos (Repositories)

### Base Genérica (`base_repository.py`)
Pensada para ser utilizada por servicios y lógica de dominio.
* **get(db, id):** Recupera un registro.
* **create(db, obj_in):** Crea un registro utilizando Pydantic CreateSchema.
* **update(db, db_obj, obj_in):** Realiza un merge de campos ignorando los no seteados (`exclude_unset`).
* **delete(db, id):** Elimina un registro.

### Repositorios Específicos
* **negocio_repository.py:** `get_by_google_calendar_id`, `get_by_telefono_bot` (normaliza a dígitos y usa `func.regexp_replace`), `get_by_display_phone_number` (alias semántico).
* **servicio_repository.py:** `list_by_negocio` (ordena servicios por nombre).
* **paciente_repository.py:** `get_by_telefono`.
* **cita_repository.py:** `list_by_negocio`, `list_actives_by_negocio` (estado distinto a "CANCELADA"), `list_actives_by_paciente`, `cancelar_cita` (realiza un UPDATE del estado a "CANCELADA" sin borrar la fila).
* **bot_state_repository.py:** `get_by_telefono`, `upsert`.

---

## 6. Lógica de Negocio (Core)

### 6.1 Búsqueda de Huecos (`app/services/slot_finder.py`)
* **Granularidad:** La búsqueda se realiza en bloques de 30 minutos (09:00, 09:30, 10:00, etc.).
* **Duración:** Se basa en `servicio.duracion_minutos`.
* **Estabilidad horaria:** Los horarios de `config_horario` no cruzan la medianoche; si lo hacen, deben modelarse como dos bloques en días distintos.
* **Colisiones (Google Calendar):** Compara en UTC ajustando los márgenes (`timeMin = start_utc + 1 minuto`, `timeMax = end_utc - 1 minuto`). Si la lista está vacía, el hueco está libre.
* **Métodos clave:** `find_next_available_slot` y `validate_slot_exact`.

### 6.2 Disponibilidad (`app/services/availability_service.py`)
* **sugerir_siguiente_hueco:** Carga el negocio y servicio, aplica la zona horaria (por defecto "Europe/Madrid") y reutiliza el `SlotFinder` para devolver un `SlotSuggestion` con fechas locales y UTC.

---

## 7. Máquina de Estados del Bot (`app/services/state_machine.py`)

### Flujo de "Reserva"
| Estado Inicial | Acción de Usuario | Resultado |
| :--- | :--- | :--- |
| **None** | Escribe "Reservar" | Lista servicios, cambia estado a `ESPERANDO_SERVICIO`. |
| **ESPERANDO_SERVICIO** | Envía un índice (ej. "1") | Sugiere hueco, guarda datos temporales, cambia a `ESPERANDO_FECHA`. |
| **ESPERANDO_FECHA** | Responde "Sí" | Crea evento en Google Calendar y DB (Cita confirmada). |
| **ESPERANDO_FECHA** | Propone fecha (ej. "lunes 16:00") | Usa `dateparser` ajustado a 30 min. Si es válido, lo toma; si no, sugiere otro hueco. |

### Flujo de "Cancelación"
| Estado Inicial | Acción de Usuario | Resultado |
| :--- | :--- | :--- |
| **None** | Escribe "Cancelar" | Obtiene citas activas, guarda IDs, muestra lista numerada, cambia a `ESPERANDO_CANCELACION`. |
| **ESPERANDO_CANCELACION** | Envía índice | Borra evento en Google Calendar, marca cita como CANCELADA, confirma al usuario. |

---

## 8. Integraciones Externas

### WhatsApp Cloud API (`app/core/whatsapp.py`)
* Utiliza `send_text_message` apuntando al endpoint v17.0 de Meta Graph API.
* Normaliza los números de teléfono a dígitos.
* Si falla con código ≥ 400, lanza un RuntimeError.
* **Nota de depuración:** Errores de tipo *API access blocked* son problemas de permisos/tokens de Meta, no del código.

### Google Calendar (`app/core/google_calendar.py`)
* Se autentica mediante el archivo de service account (`credentials.json`).
* Permite listar, crear y eliminar eventos en bloque UTC.
* **Rendimiento:** Las llamadas síncronas están envueltas en `anyio.to_thread.run_sync` para evitar bloqueos en el event loop asíncrono de FastAPI.

---

## 9. Endpoints FastAPI

### 9.1 Webhook WhatsApp (`app/api/v1/endpoints/webhook.py`)
* **GET /webhook:** Verifica el token de Meta (`hub.challenge`).
* **POST /webhook:** Extrae la información del usuario, interactúa con la máquina de estados, realiza el commit en DB y responde por WhatsApp. Si el envío falla, devuelve un código 200 para no bloquear la cola de Meta.

### 9.2 Admin - Cancelar Cita (`app/api/v1/endpoints/admin.py`)
* **POST /admin/cancelar-cita/{cita_id}:** Elimina el evento de Google, marca la cita como CANCELADA en DB y notifica al paciente vía WhatsApp. Si falla el envío de WhatsApp, devuelve un aviso controlado. En producción, requiere autenticación.

---

## 10. Migraciones y QA

### Migraciones Alembic
* **0001_initial.py:** Crea las tablas iniciales.
* **0002_bot_whatsapp.py:** Añade la columna `whatsapp_phone_id` a negocios y crea la tabla `bot_estados`.

### Scripts de Pruebas (Carpeta `scripts/`)
* **test_state_machine.py:** Prueba directa del flujo sin webhook.
* **test_webhook.py / test_webhook_select.py / test_webhook_confirm_and_cancel.py:** Simulan peticiones POST para validar estados.
* **book_and_cancel_next.py:** Flujo completo E2E con el número 600000000.
* **test_cancel_by_patient_id.py:** Prueba el borrado de citas activas por paciente.

---

## 11. Puesta en Marcha (Guía Rápida)

1.  **Clonar** el proyecto.
2.  **Crear y activar entorno virtual:** `python -m venv .venv` y luego `.\.venv\Scripts\activate`.
3.  **Instalar dependencias:** `pip install --upgrade pip` seguido de `pip install -r requirements.txt`.
4.  **Configurar variables:** Crear archivo `.env` configurando tokens, base de datos y Google.
5.  **Ejecutar migraciones:** `.\.venv\Scripts\alembic.exe -c alembic.ini upgrade head`.
6.  **Levantar servidor:** `.\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000`.
7.  **Configurar webhook:** Registrar la URL en Meta con el Verify Token correspondiente y asociar el `phone_number_id` en la tabla negocios.