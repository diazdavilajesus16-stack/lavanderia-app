# -*- coding: utf-8 -*-
"""
Sistema de Control de Lavandería - Autoservicio
Backend: API REST + WebSocket, login con roles, monitor automático de ciclos,
historial de ciclos, reportes y configuración.
"""
import asyncio
import json
import os
import secrets
from datetime import datetime, timedelta
from typing import List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import (
    init_db, get_db, SessionLocal, Maquina, CicloSesion, TipoMaquina, EstadoMaquina,
    Usuario, RolUsuario, Configuracion,
)
from auth import hash_password, verificar_password

NUM_LAVADORAS = 19
NUM_SECADORAS = 19

ARCHIVO_CLAVE = "session_secret.key"
if os.environ.get("SESSION_SECRET"):
    SECRET_KEY = os.environ["SESSION_SECRET"]
elif os.path.exists(ARCHIVO_CLAVE):
    with open(ARCHIVO_CLAVE, "r") as f:
        SECRET_KEY = f.read().strip()
else:
    SECRET_KEY = secrets.token_hex(32)
    with open(ARCHIVO_CLAVE, "w") as f:
        f.write(SECRET_KEY)

USUARIO_DEFAULT = "admin"
PASSWORD_DEFAULT = "lavanderia123"

app = FastAPI(title="Control de Lavandería")
app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, same_site="lax")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        data = json.dumps(message, ensure_ascii=False)
        vivos = []
        for connection in self.active_connections:
            try:
                await connection.send_text(data)
                vivos.append(connection)
            except Exception:
                pass
        self.active_connections = vivos


manager = ConnectionManager()


def get_sesion_activa(db: Session, maquina_id: int):
    return (
        db.query(CicloSesion)
        .filter(CicloSesion.maquina_id == maquina_id, CicloSesion.recogido == 0)
        .order_by(CicloSesion.id.desc())
        .first()
    )


def get_configuracion(db: Session) -> Configuracion:
    config = db.query(Configuracion).first()
    if not config:
        config = Configuracion(id=1)
        db.add(config)
        db.commit()
        db.refresh(config)
    return config


def estado_completo_maquinas(db: Session):
    maquinas = db.query(Maquina).order_by(Maquina.tipo, Maquina.numero).all()
    resultado = []
    for m in maquinas:
        sesion = get_sesion_activa(db, m.id) if m.estado != EstadoMaquina.disponible else None
        resultado.append(m.to_dict(sesion))
    return resultado


# ---------- Autenticación ----------
def usuario_actual(request: Request, db: Session = Depends(get_db)) -> Usuario:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="No has iniciado sesión")
    usuario = db.query(Usuario).filter(Usuario.id == user_id).first()
    if not usuario:
        raise HTTPException(status_code=401, detail="Sesión inválida")
    return usuario


def solo_dueno(usuario: Usuario = Depends(usuario_actual)) -> Usuario:
    if usuario.rol != RolUsuario.dueno:
        raise HTTPException(status_code=403, detail="Solo el dueño puede hacer esto")
    return usuario


def usuario_actual_ws(websocket: WebSocket, db: Session) -> Usuario | None:
    session = websocket.scope.get("session", {})
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.query(Usuario).filter(Usuario.id == user_id).first()


# ---------- Esquemas ----------
class IniciarCicloRequest(BaseModel):
    cliente_nombre: str
    cliente_telefono: str | None = None
    duracion_minutos: int | None = None


class TelefonoRequest(BaseModel):
    telefono: str


class LoginRequest(BaseModel):
    username: str
    password: str


class NuevoUsuarioRequest(BaseModel):
    username: str
    password: str
    nombre: str
    rol: RolUsuario


class ConfiguracionRequest(BaseModel):
    duracion_default_lavadora: int
    duracion_default_secadora: int
    nombre_negocio: str


# ---------- Arranque ----------
@app.on_event("startup")
def startup_event():
    init_db()
    db = SessionLocal()
    try:
        if db.query(Maquina).count() == 0:
            for i in range(1, NUM_LAVADORAS + 1):
                db.add(Maquina(tipo=TipoMaquina.lavadora, numero=i, estado=EstadoMaquina.disponible))
            for i in range(1, NUM_SECADORAS + 1):
                db.add(Maquina(tipo=TipoMaquina.secadora, numero=i, estado=EstadoMaquina.disponible))
            db.commit()

        if db.query(Usuario).count() == 0:
            db.add(Usuario(
                username=USUARIO_DEFAULT,
                password_hash=hash_password(PASSWORD_DEFAULT),
                nombre="Dueño",
                rol=RolUsuario.dueno,
            ))
            db.commit()
            print(f"[AVISO] Usuario creado por defecto -> usuario: '{USUARIO_DEFAULT}' "
                  f"contraseña: '{PASSWORD_DEFAULT}'. Cámbiala apenas puedas.")

        get_configuracion(db)
    finally:
        db.close()

    asyncio.create_task(monitor_ciclos())


async def monitor_ciclos():
    while True:
        await asyncio.sleep(3)
        db = SessionLocal()
        try:
            ahora = datetime.utcnow()
            en_uso = db.query(Maquina).filter(Maquina.estado == EstadoMaquina.en_uso).all()
            cambios = False
            for m in en_uso:
                sesion = get_sesion_activa(db, m.id)
                if sesion and sesion.hora_fin_estimada <= ahora:
                    m.estado = EstadoMaquina.finalizado
                    sesion.hora_finalizado = ahora
                    cambios = True
            if cambios:
                db.commit()
                await manager.broadcast({"evento": "actualizacion", "maquinas": estado_completo_maquinas(db)})
        finally:
            db.close()


# ---------- Autenticación: endpoints ----------
@app.post("/api/login")
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    usuario = db.query(Usuario).filter(Usuario.username == req.username.strip()).first()
    if not usuario or not verificar_password(req.password, usuario.password_hash):
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
    request.session["user_id"] = usuario.id
    return {"ok": True, "usuario": usuario.to_dict()}


@app.post("/api/logout")
def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/me")
def me(usuario: Usuario = Depends(usuario_actual)):
    return usuario.to_dict()


# ---------- Usuarios (solo dueño) ----------
@app.get("/api/usuarios")
def listar_usuarios(db: Session = Depends(get_db), _: Usuario = Depends(solo_dueno)):
    return [u.to_dict() for u in db.query(Usuario).order_by(Usuario.id).all()]


@app.post("/api/usuarios")
def crear_usuario(req: NuevoUsuarioRequest, db: Session = Depends(get_db), _: Usuario = Depends(solo_dueno)):
    if db.query(Usuario).filter(Usuario.username == req.username.strip()).first():
        raise HTTPException(status_code=400, detail="Ese nombre de usuario ya existe")
    nuevo = Usuario(
        username=req.username.strip(),
        password_hash=hash_password(req.password),
        nombre=req.nombre.strip(),
        rol=req.rol,
    )
    db.add(nuevo)
    db.commit()
    return {"ok": True, "usuario": nuevo.to_dict()}


@app.delete("/api/usuarios/{usuario_id}")
def eliminar_usuario(usuario_id: int, db: Session = Depends(get_db), actual: Usuario = Depends(solo_dueno)):
    if usuario_id == actual.id:
        raise HTTPException(status_code=400, detail="No puedes eliminar tu propio usuario")
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    db.delete(usuario)
    db.commit()
    return {"ok": True}


# ---------- Configuración (solo dueño edita; todos pueden leer) ----------
@app.get("/api/configuracion")
def obtener_configuracion(db: Session = Depends(get_db), _: Usuario = Depends(usuario_actual)):
    return get_configuracion(db).to_dict()


@app.post("/api/configuracion")
def actualizar_configuracion(req: ConfiguracionRequest, db: Session = Depends(get_db),
                              _: Usuario = Depends(solo_dueno)):
    config = get_configuracion(db)
    config.duracion_default_lavadora = req.duracion_default_lavadora
    config.duracion_default_secadora = req.duracion_default_secadora
    config.nombre_negocio = req.nombre_negocio.strip() or "Control de Lavandería"
    db.commit()
    return {"ok": True, "configuracion": config.to_dict()}


# ---------- Máquinas ----------
@app.get("/api/maquinas")
def listar_maquinas(db: Session = Depends(get_db), _: Usuario = Depends(usuario_actual)):
    return estado_completo_maquinas(db)


@app.post("/api/maquinas/{maquina_id}/iniciar")
async def iniciar_ciclo(maquina_id: int, req: IniciarCicloRequest, db: Session = Depends(get_db),
                         _: Usuario = Depends(usuario_actual)):
    maquina = db.query(Maquina).filter(Maquina.id == maquina_id).first()
    if not maquina:
        raise HTTPException(status_code=404, detail="Máquina no encontrada")
    if maquina.estado not in (EstadoMaquina.disponible,):
        raise HTTPException(status_code=400, detail="La máquina no está disponible")

    config = get_configuracion(db)
    default = config.duracion_default_lavadora if maquina.tipo == TipoMaquina.lavadora else config.duracion_default_secadora
    duracion = req.duracion_minutos or default
    ahora = datetime.utcnow()
    sesion = CicloSesion(
        maquina_id=maquina.id,
        cliente_nombre=req.cliente_nombre.strip(),
        cliente_telefono=(req.cliente_telefono or "").strip() or None,
        duracion_minutos=duracion,
        hora_inicio=ahora,
        hora_fin_estimada=ahora + timedelta(minutes=duracion),
    )
    maquina.estado = EstadoMaquina.en_uso
    db.add(sesion)
    db.commit()

    await manager.broadcast({"evento": "actualizacion", "maquinas": estado_completo_maquinas(db)})
    return {"ok": True}


@app.post("/api/maquinas/{maquina_id}/telefono")
async def guardar_telefono(maquina_id: int, req: TelefonoRequest, db: Session = Depends(get_db),
                            _: Usuario = Depends(usuario_actual)):
    sesion = get_sesion_activa(db, maquina_id)
    if not sesion:
        raise HTTPException(status_code=404, detail="No hay un ciclo activo en esta máquina")
    sesion.cliente_telefono = req.telefono.strip()
    db.commit()
    await manager.broadcast({"evento": "actualizacion", "maquinas": estado_completo_maquinas(db)})
    return {"ok": True}


@app.post("/api/maquinas/{maquina_id}/liberar")
async def liberar_maquina(maquina_id: int, db: Session = Depends(get_db), _: Usuario = Depends(usuario_actual)):
    maquina = db.query(Maquina).filter(Maquina.id == maquina_id).first()
    if not maquina:
        raise HTTPException(status_code=404, detail="Máquina no encontrada")

    sesion = get_sesion_activa(db, maquina.id)
    if sesion:
        sesion.recogido = 1
        sesion.hora_recogido = datetime.utcnow()
    maquina.estado = EstadoMaquina.disponible
    db.commit()

    await manager.broadcast({"evento": "actualizacion", "maquinas": estado_completo_maquinas(db)})
    return {"ok": True}


@app.post("/api/maquinas/{maquina_id}/mantenimiento")
async def alternar_mantenimiento(maquina_id: int, db: Session = Depends(get_db),
                                  _: Usuario = Depends(usuario_actual)):
    maquina = db.query(Maquina).filter(Maquina.id == maquina_id).first()
    if not maquina:
        raise HTTPException(status_code=404, detail="Máquina no encontrada")

    if maquina.estado == EstadoMaquina.mantenimiento:
        maquina.estado = EstadoMaquina.disponible
    elif maquina.estado == EstadoMaquina.disponible:
        maquina.estado = EstadoMaquina.mantenimiento
    else:
        raise HTTPException(status_code=400, detail="Solo se puede marcar mantenimiento si está disponible")
    db.commit()

    await manager.broadcast({"evento": "actualizacion", "maquinas": estado_completo_maquinas(db)})
    return {"ok": True}


@app.get("/api/maquinas/{maquina_id}/historial")
def historial_maquina(maquina_id: int, db: Session = Depends(get_db), _: Usuario = Depends(usuario_actual)):
    maquina = db.query(Maquina).filter(Maquina.id == maquina_id).first()
    if not maquina:
        raise HTTPException(status_code=404, detail="Máquina no encontrada")
    ciclos = (
        db.query(CicloSesion)
        .filter(CicloSesion.maquina_id == maquina_id)
        .order_by(CicloSesion.id.desc())
        .limit(20)
        .all()
    )
    return [c.to_dict_historial() for c in ciclos]


# ---------- Actividad reciente y reportes (datos reales, no simulados) ----------
@app.get("/api/actividad")
def actividad_reciente(db: Session = Depends(get_db), _: Usuario = Depends(usuario_actual)):
    recientes = (
        db.query(CicloSesion)
        .order_by(CicloSesion.id.desc())
        .limit(30)
        .all()
    )
    eventos = []
    maquinas_por_id = {m.id: m for m in db.query(Maquina).all()}
    for c in recientes:
        m = maquinas_por_id.get(c.maquina_id)
        if not m:
            continue
        nombre_maquina = f"{'Lavadora' if m.tipo == TipoMaquina.lavadora else 'Secadora'} {m.numero:02d}"
        eventos.append({"hora": c.hora_inicio.isoformat(), "texto": f"{nombre_maquina} inició ciclo ({c.cliente_nombre})"})
        if c.hora_finalizado:
            eventos.append({"hora": c.hora_finalizado.isoformat(), "texto": f"{nombre_maquina} terminó su ciclo"})
        if c.hora_recogido:
            eventos.append({"hora": c.hora_recogido.isoformat(), "texto": f"{nombre_maquina} quedó disponible"})
    eventos.sort(key=lambda e: e["hora"], reverse=True)
    return eventos[:15]


@app.get("/api/reportes")
def reportes(db: Session = Depends(get_db), _: Usuario = Depends(usuario_actual)):
    hoy = datetime.utcnow().date()
    ciclos_hoy = db.query(CicloSesion).filter(CicloSesion.hora_inicio >= datetime(hoy.year, hoy.month, hoy.day)).all()

    def promedio_duracion(tipo: TipoMaquina):
        maquinas_ids = [m.id for m in db.query(Maquina).filter(Maquina.tipo == tipo).all()]
        ciclos = db.query(CicloSesion).filter(
            CicloSesion.maquina_id.in_(maquinas_ids), CicloSesion.hora_finalizado.isnot(None)
        ).all()
        if not ciclos:
            return None
        return round(sum(c.duracion_minutos for c in ciclos) / len(ciclos), 1)

    # Uso por hora del día de hoy (cuántos ciclos se iniciaron en cada hora) - dato real, no relleno
    usos_por_hora = [0] * 24
    for c in ciclos_hoy:
        usos_por_hora[c.hora_inicio.hour] += 1

    return {
        "maquinas": estado_completo_maquinas(db),
        "ciclos_iniciados_hoy": len(ciclos_hoy),
        "promedio_duracion_lavadora": promedio_duracion(TipoMaquina.lavadora),
        "promedio_duracion_secadora": promedio_duracion(TipoMaquina.secadora),
        "uso_por_hora_hoy": usos_por_hora,
    }


# ---------- WebSocket ----------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    db = SessionLocal()
    usuario = usuario_actual_ws(websocket, db)
    if not usuario:
        await websocket.close(code=4401)
        db.close()
        return

    await manager.connect(websocket)
    try:
        await websocket.send_text(json.dumps({
            "evento": "actualizacion",
            "maquinas": estado_completo_maquinas(db),
        }, ensure_ascii=False))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    finally:
        db.close()


# ---------- Frontend ----------
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/login")
def pagina_login():
    return FileResponse("static/login.html")


@app.get("/")
def index(request: Request):
    if not request.session.get("user_id"):
        return RedirectResponse(url="/login")
    return FileResponse("static/index.html")
