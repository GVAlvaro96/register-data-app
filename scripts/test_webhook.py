import json
import os
import sys

import psycopg
import pytz
import requests


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.core.config import get_settings


def db_first_negocio():
    s = get_settings()
    url = s.DATABASE_URL
    url = url.replace("postgresql+asyncpg://", "postgresql://", 1).replace(
        "postgresql+asyncpg:", "postgresql:", 1
    )
    conn = psycopg.connect(url)
    cur = conn.cursor()
    cur.execute("select id, telefono_bot from negocios order by id asc limit 1")
    negocio_id, telefono_bot = cur.fetchone()
    conn.close()
    return negocio_id, telefono_bot


def read_bot_estado(telefono: str):
    s = get_settings()
    url = s.DATABASE_URL
    url = url.replace("postgresql+asyncpg://", "postgresql://", 1).replace(
        "postgresql+asyncpg:", "postgresql:", 1
    )
    conn = psycopg.connect(url)
    cur = conn.cursor()
    cur.execute(
        "select telefono, estado from bot_estados where telefono=%s",
        (telefono,),
    )
    row = cur.fetchone()
    conn.close()
    return row


def main():
    negocio_id, telefono_bot = db_first_negocio()
    telefono_sender = "600000000"  # prueba

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"display_phone_number": telefono_bot},
                            "contacts": [{"profile": {"name": "Paciente"}}],
                            "messages": [
                                {"from": telefono_sender, "text": {"body": "Reservar"}}
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
        timeout=30,
    )
    print("webhook_status", resp.status_code)

    row = read_bot_estado(telefono_sender)
    print("bot_estado_row", row)


if __name__ == "__main__":
    main()

