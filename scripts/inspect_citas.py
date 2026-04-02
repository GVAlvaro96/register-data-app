import os
import sys

import psycopg

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.core.config import get_settings


def main():
    s = get_settings()
    url = s.DATABASE_URL
    url = url.replace("postgresql+asyncpg://", "postgresql://", 1).replace(
        "postgresql+asyncpg:", "postgresql:", 1
    )

    conn = psycopg.connect(url)
    cur = conn.cursor()

    # Verifica si existe paciente de prueba.
    cur.execute(
        "select id, telefono, nombre from pacientes where telefono=%s",
        ("600000000",),
    )
    pacientes = cur.fetchall()
    print("pacientes", pacientes)

    cur.execute(
        "select count(*) from citas c join pacientes p on p.id=c.paciente_id where p.telefono=%s",
        ("600000000",),
    )
    print("citas_count", cur.fetchone())

    cur.execute(
        """
        select
            c.id,
            c.estado,
            c.calendar_event_id,
            c.fecha_hora,
            c.negocio_id,
            p.telefono,
            p.nombre
        from citas c
        join pacientes p on p.id = c.paciente_id
        where p.telefono = %s
        order by c.fecha_hora desc
        limit 10
        """,
        ("600000000",),
    )
    rows = cur.fetchall()
    conn.close()

    for r in rows:
        print(r)


if __name__ == "__main__":
    main()

