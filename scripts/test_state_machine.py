import asyncio
from datetime import datetime
import os
import sys

import psycopg
import pytz

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.core.config import get_settings
from app.core.database import AsyncSessionLocal
from app.services.state_machine import state_machine


def pick_first_negocio():
    s = get_settings()
    url = s.DATABASE_URL
    # Alembic usa asyncpg en .env, pero psycopg (sync) para test.
    url = url.replace("postgresql+asyncpg://", "postgresql://", 1).replace(
        "postgresql+asyncpg:", "postgresql:", 1
    )
    conn = psycopg.connect(url)
    cur = conn.cursor()
    cur.execute("select id, telefono_bot from negocios order by id asc limit 1")
    row = cur.fetchone()
    conn.close()
    if not row:
        raise RuntimeError("No hay negocios en la base de datos.")
    return row[0], row[1]


async def main():
    negocio_id, telefono_bot = pick_first_negocio()
    now_utc = datetime.utcnow().replace(tzinfo=pytz.UTC)

    async with AsyncSessionLocal() as db:
        r1 = await state_machine.process_message(
            db,
            telefono_sender=telefono_bot,
            texto_mensaje="Hola",
            negocio_id=negocio_id,
            paciente_nombre="Paciente",
            now_utc=now_utc,
        )
        print("r1", r1)

        r2 = await state_machine.process_message(
            db,
            telefono_sender=telefono_bot,
            texto_mensaje="Reservar",
            negocio_id=negocio_id,
            paciente_nombre="Paciente",
            now_utc=now_utc,
        )
        print("r2", r2)

        # Intentar seleccionar primer servicio (puede implicar Google Calendar en Fase 2).
        try:
            r3 = await state_machine.process_message(
                db,
                telefono_sender=telefono_bot,
                texto_mensaje="1",
                negocio_id=negocio_id,
                paciente_nombre="Paciente",
                now_utc=now_utc,
            )
            print("r3", r3)
        except Exception as e:
            print("r3_excepcion", type(e).__name__, str(e))


if __name__ == "__main__":
    asyncio.run(main())

