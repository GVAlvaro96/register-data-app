from __future__ import annotations

from alembic import op
import sqlalchemy as sa
import sqlalchemy.dialects.postgresql as psql

# Revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "negocios",
        sa.Column("id", psql.UUID(as_uuid=True), primary_key=True),
        sa.Column("nombre_negocio", sa.String(), nullable=False),
        sa.Column("telefono_bot", sa.String(), nullable=False),
        sa.Column("whatsapp_phone_id", sa.String(), nullable=False, server_default=sa.text("''")),
        sa.Column("google_calendar_id", sa.String(), nullable=False),
        sa.Column("config_horario", psql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "zona_horaria",
            sa.String(),
            nullable=False,
            server_default=sa.text("'Europe/Madrid'"),
        ),
    )

    op.create_table(
        "servicios",
        sa.Column("id", psql.UUID(as_uuid=True), primary_key=True),
        sa.Column("negocio_id", psql.UUID(as_uuid=True), sa.ForeignKey("negocios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("nombre", sa.String(), nullable=False),
        sa.Column("duracion_minutos", sa.Integer(), nullable=False),
    )

    op.create_table(
        "pacientes",
        sa.Column("id", psql.UUID(as_uuid=True), primary_key=True),
        sa.Column("telefono", sa.String(), nullable=False),
        sa.Column("nombre", sa.String(), nullable=False),
        sa.UniqueConstraint("telefono", name="uq_pacientes_telefono"),
    )

    op.create_table(
        "citas",
        sa.Column("id", psql.UUID(as_uuid=True), primary_key=True),
        sa.Column("negocio_id", psql.UUID(as_uuid=True), sa.ForeignKey("negocios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("paciente_id", psql.UUID(as_uuid=True), sa.ForeignKey("pacientes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("servicio_id", psql.UUID(as_uuid=True), sa.ForeignKey("servicios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fecha_hora", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "estado",
            sa.String(),
            nullable=False,
            server_default=sa.text("'CONFIRMADA'"),
        ),
        sa.Column("calendar_event_id", sa.String(), nullable=False, server_default=sa.text("''")),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.UniqueConstraint("negocio_id", "fecha_hora", name="uq_citas_negocio_fecha_hora"),
    )

    op.create_table(
        "bot_estados",
        sa.Column("telefono", sa.String(), primary_key=True),
        sa.Column("estado", sa.String(), nullable=False),
        sa.Column("negocio_id", psql.UUID(as_uuid=True), nullable=True),
        sa.Column("servicio_id", psql.UUID(as_uuid=True), nullable=True),
        sa.Column("sugerencia_start_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sugerencia_end_utc", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelacion_citas_ids", psql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("actualizado_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )


def downgrade() -> None:
    op.drop_table("bot_estados")
    op.drop_table("citas")
    op.drop_table("pacientes")
    op.drop_table("servicios")
    op.drop_table("negocios")

