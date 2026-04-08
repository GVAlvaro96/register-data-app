import uuid
from sqlalchemy import String, ForeignKey, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base

class Empleado(Base):
    __tablename__ = "empleados"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    negocio_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("negocios.id", ondelete="CASCADE"), nullable=False)
    nombre: Mapped[str] = mapped_column(String, nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    color_id: Mapped[str | None] = mapped_column(String, nullable=True)