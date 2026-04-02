from __future__ import annotations

from alembic import op
import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as psql

# Revision identifiers, used by Alembic.
revision = "0002_bot_whatsapp"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # 1) whatsapp_phone_id en negocios (si no existe)
    exists_col = conn.execute(
        sa.text(
            """
            select 1
            from information_schema.columns
            where table_schema = 'public'
              and table_name = 'negocios'
              and column_name = 'whatsapp_phone_id'
            """
        )
    ).fetchone()

    if not exists_col:
        op.execute(
            "ALTER TABLE negocios ADD COLUMN whatsapp_phone_id VARCHAR NOT NULL DEFAULT ''"
        )

    # 2) bot_estados (si no existe)
    exists_table = conn.execute(
        sa.text(
            """
            select 1
            from information_schema.tables
            where table_schema = 'public'
              and table_name = 'bot_estados'
            """
        )
    ).fetchone()

    if not exists_table:
        op.create_table(
            "bot_estados",
            sa.Column("telefono", sa.String(), primary_key=True),
            sa.Column("estado", sa.String(), nullable=False),
            sa.Column("negocio_id", psql.UUID(as_uuid=True), nullable=True),
            sa.Column("servicio_id", psql.UUID(as_uuid=True), nullable=True),
            sa.Column("sugerencia_start_utc", sa.DateTime(timezone=True), nullable=True),
            sa.Column("sugerencia_end_utc", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "cancelacion_citas_ids",
                psql.JSONB(astext_type=sa.Text()),
                nullable=True,
            ),
            sa.Column(
                "actualizado_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )


def downgrade() -> None:
    # Importante: dejar downgrade conservador.
    # En caso de volver atrás, borramos tabla y columna si existen.
    conn = op.get_bind()

    exists_table = conn.execute(
        sa.text(
            """
            select 1
            from information_schema.tables
            where table_schema = 'public'
              and table_name = 'bot_estados'
            """
        )
    ).fetchone()

    if exists_table:
        op.drop_table("bot_estados")

    exists_col = conn.execute(
        sa.text(
            """
            select 1
            from information_schema.columns
            where table_schema = 'public'
              and table_name = 'negocios'
              and column_name = 'whatsapp_phone_id'
            """
        )
    ).fetchone()

    if exists_col:
        op.execute("ALTER TABLE negocios DROP COLUMN whatsapp_phone_id")

