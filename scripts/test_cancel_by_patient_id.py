import os
import sys
import json

import psycopg
import requests

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.core.config import get_settings


PATIENT_ID = "a7038086-9f01-4c9b-8553-038afdc11a78"


def _sync_db_url():
    s = get_settings()
    url = s.DATABASE_URL
    return url.replace("postgresql+asyncpg://", "postgresql://", 1).replace(
        "postgresql+asyncpg:", "postgresql:", 1
    )


def db_latest_cita_for_patient(paciente_id: str):
    url = _sync_db_url()
    conn = psycopg.connect(url)
    cur = conn.cursor()
    cur.execute(
        """
        select id, estado, calendar_event_id, fecha_hora, negocio_id
        from citas
        where paciente_id = %s
        order by fecha_hora desc
        limit 5
        """,
        (paciente_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def db_get_cita_by_id(cita_id: str):
    url = _sync_db_url()
    conn = psycopg.connect(url)
    cur = conn.cursor()
    cur.execute(
        """
        select id, estado, calendar_event_id, fecha_hora, negocio_id, paciente_id, servicio_id
        from citas
        where id = %s
        """,
        (cita_id,),
    )
    row = cur.fetchone()
    conn.close()
    return row


def main():
    citas = db_latest_cita_for_patient(PATIENT_ID)
    print("latest_citas_count", len(citas))
    for r in citas:
        print("cita:", r)

    if not citas:
        print("No hay citas para ese paciente.")
        return

    # Elegimos primero una cita que NO esté cancelada.
    chosen = None
    for r in citas:
        if r[1] != "CANCELADA":
            chosen = r
            break

    # Si todas están canceladas, usamos la más reciente.
    if not chosen:
        chosen = citas[0]

    cita_id = str(chosen[0])
    print("chosen_cita_id", cita_id)
    print("cita_before", db_get_cita_by_id(cita_id))

    cancel_resp = requests.post(
        f"http://127.0.0.1:8000/admin/cancelar-cita/{cita_id}",
        json={},
        timeout=120,
    )
    print("cancel_status", cancel_resp.status_code)
    try:
        print("cancel_body", cancel_resp.json())
    except Exception:
        print("cancel_text_head", (cancel_resp.text or "")[:300])

    print("cita_after", db_get_cita_by_id(cita_id))


if __name__ == "__main__":
    main()

