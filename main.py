# -*- coding: utf-8 -*-
"""
Sistema de Control de Lavandería - Autoservicio
MVP: control manual de inicio de ciclo (sin sensores), con actualización
en tiempo real vía WebSocket, cambio automático de estado al terminar el ciclo,
y login con roles (dueño / personal).
"""
import asyncio
import json
import os
import secrets
from datetime import datetime, timedelta
from typing import List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import (
    init_db, get_db, SessionLocal, Maquina, CicloSesion, TipoMaquina, EstadoMaquina,
    Usuario, RolUsuario,
)
from auth import hash_password, verificar_password

NUM_LAVADORAS = 19
NUM_SECADORAS = 19
DURACION_DEFAULT_LAVADORA = 35   # minutos
DURACION_DEFAULT_SECADORA = 45   # minutos

# Clave para firmar las cookies de sesión.
# En Render (o cualquier hosting con disco no permanente) conviene fijarla como
# variable de entorno SESSION_SECRET, para que no cambie en cada reinicio y la
# gente no tenga que volver a iniciar sesión todo el tiempo.
# Si no existe esa variable (uso local en Windows), se genera una vez y se
# guarda en un archivo local.
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

# Usuario dueño por defecto, creado solo si todavía no existe ningún usuario.
USUARIO_DEFAULT = "admin"
PASSWORD_DEFAULT = "lavanderia123"

app = FastAPI(title="Control de Lavandería")

app.add_middleware(SessionMiddleware, secret_key=SECRET_KEY, same_site="lax")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- Gestión de conexiones WebSocket ----------
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


def estado_completo_maquinas(db: Session):
    maquinas = db.query(Maquina).order_by(Maquina.tipo, Maquina.numero).all()
    resultado = []
    for m in maquinas:
        sesion = get_sesion_activa(db, m.id) if m.estado != EstadoMaquina.disponible else None
        resultado.append(m.to_dict(sesion))
    return resultado


# ---------- Autenticación ----------
def usuario_actual(request: Request, db: Session = Depends(get_db)) -> Usuario:
    """Dependencia para endpoints REST: exige sesión activa, si no hay -> 401."""
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
    """Misma verificación que usuario_actual, pero para la conexión WebSocket."""
    session = websocket.scope.get("session", {})
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.query(Usuario).filter(Usuario.id == user_id).first()


# ---------- Esquemas de entrada ----------
class IniciarCicloRequest(BaseModel):
    cliente_nombre: str
    cliente_telefono: str | None = None
    duracion_minutos: int | None = None  # si no se envía, se usa el default según tipo


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


# ---------- Eventos de arranque ----------
@app.on_event("startup")
def startup_event():
    init_db()
    db = SessionLocal()
    try:
        existentes = db.query(Maquina).count()
        if existentes == 0:
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
    finally:
        db.close()

    asyncio.create_task(monitor_ciclos())


async def monitor_ciclos():
    """Revisa cada pocos segundos si algún ciclo en curso ya terminó,
    y si es así cambia el estado de la máquina a 'finalizado' y avisa por WebSocket."""
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
                    cambios = True
            if cambios:
                db.commit()
                await manager.broadcast({
                    "evento": "actualizacion",
                    "maquinas": estado_completo_maquinas(db),
                })
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


# ---------- Gestión de usuarios (solo dueño) ----------
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


# ---------- Endpoints REST de máquinas (protegidos: requieren sesión) ----------
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

    duracion = req.duracion_minutos or (
        DURACION_DEFAULT_LAVADORA if maquina.tipo == TipoMaquina.lavadora else DURACION_DEFAULT_SECADORA
    )
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


# ---------- WebSocket (exige sesión activa) ----------
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    db = SessionLocal()
    usuario = usuario_actual_ws(websocket, db)
    if not usuario:
        await websocket.close(code=4401)  # código propio para "no autenticado"
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


# ---------- Frontend estático ----------
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/login")
def pagina_login():
    return FileResponse("static/login.html")


@app.get("/")
def index(request: Request):
    if not request.session.get("user_id"):
        return RedirectResponse(url="/login")
    return FileResponse("static/index.html")
