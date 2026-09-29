# -*- coding: utf-8 -*-
"""
Configuración de la base de datos (SQLite) y modelos con SQLAlchemy.
"""
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, DateTime, ForeignKey, Enum
)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship
import enum

DATABASE_URL = "sqlite:///./lavanderia.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class TipoMaquina(str, enum.Enum):
    lavadora = "lavadora"
    secadora = "secadora"


class EstadoMaquina(str, enum.Enum):
    disponible = "disponible"
    en_uso = "en_uso"
    finalizado = "finalizado"   # ciclo terminó, ropa lista, pendiente de recoger
    mantenimiento = "mantenimiento"


class RolUsuario(str, enum.Enum):
    dueno = "dueno"
    personal = "personal"


class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    nombre = Column(String, nullable=False)
    rol = Column(Enum(RolUsuario), default=RolUsuario.personal, nullable=False)

    def to_dict(self):
        return {"id": self.id, "username": self.username, "nombre": self.nombre, "rol": self.rol.value}


class Maquina(Base):
    __tablename__ = "maquinas"

    id = Column(Integer, primary_key=True, index=True)
    tipo = Column(Enum(TipoMaquina), nullable=False)
    numero = Column(Integer, nullable=False)          # 1..19 dentro de su tipo
    estado = Column(Enum(EstadoMaquina), default=EstadoMaquina.disponible, nullable=False)

    ciclos = relationship("CicloSesion", back_populates="maquina")

    def to_dict(self, sesion_activa=None):
        return {
            "id": self.id,
            "tipo": self.tipo.value,
            "numero": self.numero,
            "estado": self.estado.value,
            "sesion": sesion_activa.to_dict() if sesion_activa else None,
        }


class CicloSesion(Base):
    __tablename__ = "ciclos"

    id = Column(Integer, primary_key=True, index=True)
    maquina_id = Column(Integer, ForeignKey("maquinas.id"), nullable=False)
    cliente_nombre = Column(String, nullable=False)
    cliente_telefono = Column(String, nullable=True)
    duracion_minutos = Column(Integer, nullable=False)
    hora_inicio = Column(DateTime, default=datetime.utcnow)
    hora_fin_estimada = Column(DateTime, nullable=False)
    hora_finalizado = Column(DateTime, nullable=True)   # cuándo el ciclo realmente terminó (lo detectó el monitor)
    hora_recogido = Column(DateTime, nullable=True)     # cuándo el cliente recogió la ropa (máquina liberada)
    recogido = Column(Integer, default=0)  # 0 = no recogido, 1 = recogido (libera máquina)

    maquina = relationship("Maquina", back_populates="ciclos")

    def to_dict(self):
        return {
            "id": self.id,
            "cliente_nombre": self.cliente_nombre,
            "cliente_telefono": self.cliente_telefono,
            "duracion_minutos": self.duracion_minutos,
            "hora_inicio": self.hora_inicio.isoformat(),
            "hora_fin_estimada": self.hora_fin_estimada.isoformat(),
        }

    def to_dict_historial(self):
        return {
            "id": self.id,
            "cliente_nombre": self.cliente_nombre,
            "duracion_minutos": self.duracion_minutos,
            "hora_inicio": self.hora_inicio.isoformat(),
            "hora_finalizado": self.hora_finalizado.isoformat() if self.hora_finalizado else None,
            "hora_recogido": self.hora_recogido.isoformat() if self.hora_recogido else None,
            "completado": self.hora_finalizado is not None,
        }


class Configuracion(Base):
    """Fila única con parámetros ajustables del sistema (dueño los edita desde 'Configuración')."""
    __tablename__ = "configuracion"

    id = Column(Integer, primary_key=True, default=1)
    duracion_default_lavadora = Column(Integer, default=35)
    duracion_default_secadora = Column(Integer, default=45)
    nombre_negocio = Column(String, default="Control de Lavandería")

    def to_dict(self):
        return {
            "duracion_default_lavadora": self.duracion_default_lavadora,
            "duracion_default_secadora": self.duracion_default_secadora,
            "nombre_negocio": self.nombre_negocio,
        }


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
