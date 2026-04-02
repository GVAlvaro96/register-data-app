import json
import os
import sys

import psycopg
import requests

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.core.config import get_settings


def _sync_db_url():
    s = get_settings()
    url = s.DATABASE_URL
    return url.replace("postgresql+asyncpg://", "postgresql://", 1).replace(
        "postgresql+asyncpg:", "postgresql:", 1
    )


def pick_first_negocio():
    url = _sync_db_url()
    conn = psycopg.connect(url)
    cur = conn.cursor()
    cur.execute("select id, telefono_bot from negocios order by id asc limit 1")
    negocio_id, telefono_bot = cur.fetchone()
    conn.close()
    return str(negocio_id), telefono_bot


def read_paciente_id(telefono_sender: str):
    url = _sync_db_url()
    conn = psycopg.connect(url)
    cur = conn.cursor()
    cur.execute("select id, nombre from pacientes where telefono=%s", (telefono_sender,))
    row = cur.fetchone()
    conn.close()
    return row


def read_latest_cita_id(paciente_id):
    url = _sync_db_url()
    conn = psycopg.connect(url)
    cur = conn.cursor()
    cur.execute(
        """
        select id, estado, calendar_event_id, fecha_hora
        from citas
        where paciente_id=%s
        order by fecha_hora desc
        limit 1
        """,
        (paciente_id,),
    )
    row = cur.fetchone()
    conn.close()
    return row


def main():
    negocio_id, telefono_bot = pick_first_negocio()
    telefono_sender = "600000000"

    # 1) Confirmación: enviar "Sí"
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"display_phone_number": telefono_bot},
                            "contacts": [{"profile": {"name": "Paciente"}}],
                            "messages": [
                                {"from": telefono_sender, "text": {"body": "Sí"}}
                            ],
                        }
                    }
                ]
            }
        ]
    }

    resp = requests.post(
        "http://127.0.0.1:8000/webhook",
        data=json.dumps(payload),
        headers={"Content-Type": "application/json"},
        timeout=120,
    )
    print("webhook_confirm_status", resp.status_code)
    print("webhook_confirm_body_head", (resp.text or "")[:200])

    paciente_row = read_paciente_id(telefono_sender)
    print("paciente_row", paciente_row)
    if not paciente_row:
        print("No se creó paciente; probablemente falló la reserva/Google.")
        return

    paciente_id = paciente_row[0]
    cita_row = read_latest_cita_id(paciente_id)
    print("cita_row_before_cancel", cita_row)
    if not cita_row:
        print("No se creó ninguna cita.")
        return

    cita_id = str(cita_row[0])

    # 2) Cancelación proactiva
    cancel_resp = requests.post(
        f"http://127.0.0.1:8000/admin/cancelar-cita/{cita_id}",
        json={},
        timeout=120,
    )
    print("cancel_status", cancel_resp.status_code)
    try:
        print("cancel_body", cancel_resp.json())
    except Exception:
        print("cancel_text_head", cancel_resp.text[:200])

    # 3) Validar estado DB
    url = _sync_db_url()
    conn = psycopg.connect(url)
    cur = conn.cursor()
    cur.execute("select id, estado from citas where id=%s", (cita_id,))
    after = cur.fetchone()
    conn.close()
    print("cita_row_after_cancel", after)


if __name__ == "__main__":
    main()

