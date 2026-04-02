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
    cur.execute("select id from pacientes where telefono=%s", (telefono_sender,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def read_latest_cita_id(paciente_id):
    url = _sync_db_url()
    conn = psycopg.connect(url)
    cur = conn.cursor()
    cur.execute(
        "select id, estado from citas where paciente_id=%s order by fecha_hora desc limit 1",
        (paciente_id,),
    )
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None


def read_bot_estado(telefono_sender: str):
    url = _sync_db_url()
    conn = psycopg.connect(url)
    cur = conn.cursor()
    cur.execute(
        "select estado, sugerencia_start_utc, sugerencia_end_utc from bot_estados where telefono=%s",
        (telefono_sender,),
    )
    row = cur.fetchone()
    conn.close()
    return row


def read_citas_count(paciente_id):
    if not paciente_id:
        return 0
    url = _sync_db_url()
    conn = psycopg.connect(url)
    cur = conn.cursor()
    cur.execute("select count(*) from citas where paciente_id=%s", (paciente_id,))
    row = cur.fetchone()
    conn.close()
    return row[0] if row else 0


def send_webhook(telefono_bot: str, telefono_sender: str, body: str):
    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"display_phone_number": telefono_bot},
                            "contacts": [{"profile": {"name": "Paciente"}}],
                            "messages": [
                                {"from": telefono_sender, "text": {"body": body}}
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
    return resp


def main():
    negocio_id, telefono_bot = pick_first_negocio()
    telefono_sender = "600000000"

    paciente_id = read_paciente_id(telefono_sender)
    print("paciente_id", paciente_id)
    print("bot_state_before", read_bot_estado(telefono_sender))
    print("citas_count_before", read_citas_count(paciente_id))

    # Flujo: Reservar -> 1 -> Sí
    r1 = send_webhook(telefono_bot, telefono_sender, "Reservar")
    print("send Reservar", r1.status_code, (r1.text or "")[:80])
    print("bot_state_after_reservar", read_bot_estado(telefono_sender))

    r2 = send_webhook(telefono_bot, telefono_sender, "1")
    print("send 1", r2.status_code, (r2.text or "")[:80])
    print("bot_state_after_1", read_bot_estado(telefono_sender))

    r3 = send_webhook(telefono_bot, telefono_sender, "Sí")
    print("send Sí", r3.status_code, (r3.text or "")[:80])
    print("bot_state_after_si", read_bot_estado(telefono_sender))

    # Leer nueva cita
    paciente_id = read_paciente_id(telefono_sender)
    cita_id = read_latest_cita_id(paciente_id) if paciente_id else None
    print("new_cita_id", cita_id)
    print("citas_count_after", read_citas_count(paciente_id))

    if not cita_id:
        print("No se creó cita. Fin de prueba.")
        return

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


if __name__ == "__main__":
    main()

