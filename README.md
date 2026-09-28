# Sistema de Control de Lavandería — Autoservicio (MVP)

MVP funcional: control manual de inicio de ciclo (sin sensores todavía),
con actualización en tiempo real en pantalla y cambio automático de estado
cuando el ciclo termina.

## Qué incluye este MVP

- Grid visual de las 19 lavadoras y 19 secadoras.
- Al hacer clic en una máquina disponible: se asigna el nombre del cliente
  (y teléfono opcional) y se inicia el temporizador del ciclo.
- El estado se actualiza **en tiempo real** en todas las pantallas conectadas
  (computadora y celular) usando WebSockets — no hace falta refrescar.
- Cuando el tiempo del ciclo se cumple, el sistema cambia **automáticamente**
  el estado de la máquina a "Ciclo terminado" (color rojo), sin intervención
  del personal.
- Botón "Ropa recogida" para liberar la máquina y dejarla disponible de nuevo.
- Botón para marcar una máquina en mantenimiento (fuera de servicio).

- **Alerta sonora** en el dashboard cuando una máquina termina su ciclo (útil
  si el personal no está mirando la pantalla en ese momento). Es un sonido
  generado por el propio navegador, sin archivos ni costo.
- **Botón "Avisar por WhatsApp"**: cuando el ciclo termina, abre WhatsApp con
  un mensaje ya escrito al número del cliente (usando el enlace gratuito
  `wa.me`). El personal solo debe darle "Enviar". Si no se registró el
  teléfono al iniciar el ciclo, lo pide en ese momento.
  - El número se formatea automáticamente para Perú (agrega el código 51
    a números de 9 dígitos).

- **Login con roles**: nadie puede ver ni tocar el sistema sin iniciar sesión.
  - Rol **Dueño**: acceso total, incluida la gestión de quién más tiene acceso.
  - Rol **Personal**: puede operar las máquinas (asignar, liberar, avisar),
    pero no puede agregar ni quitar usuarios.
  - Usuario y contraseña por defecto la primera vez que arranca el sistema:
    **usuario:** `admin` — **contraseña:** `lavanderia123`
    (aparece también en la ventana negra al iniciar). **Cámbiala cuanto antes**
    creando tu propio usuario dueño y borrando este, o al menos cambiando la
    contraseña editando la base de datos.
  - El dueño agrega/quita personal desde el botón **"Usuarios"** en la
    esquina superior derecha del sistema.

## Lo que NO incluye todavía (siguientes fases, con costo)

- Detección automática por sensores/hardware de cuándo la máquina realmente
  empieza a girar (por ahora el personal lo marca al momento de recibir al cliente).
- Envío 100% automático de WhatsApp/SMS sin que el personal toque nada
  (requiere contratar WhatsApp Business API o Twilio, con costo por mensaje).
- Reportes históricos, ingresos, estadísticas de uso.
- Login de usuarios / roles.

## Cómo correrlo

1. Instalar dependencias (se recomienda un entorno virtual):
   ```bash
   pip install -r requirements.txt
   ```

2. Iniciar el servidor:
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000 --reload
   ```

3. Abrir en el navegador:
   - Desde la misma computadora: `http://localhost:8000`
   - Desde un celular en la misma red WiFi: `http://<IP-de-la-computadora>:8000`
     (por ejemplo `http://192.168.1.15:8000`)

La base de datos (`lavanderia.db`, SQLite) se crea sola la primera vez que
arranca el servidor, junto con las 19 lavadoras y 19 secadoras.

## Estructura del proyecto

```
lavanderia_app/
├── main.py               # Backend: API REST + WebSocket + monitor de ciclos
├── database.py           # Modelos (Máquina, CicloSesion) y conexión SQLite
├── requirements.txt
├── Iniciar Sistema.bat   # Doble clic para arrancar el sistema (Windows)
├── static/
│   └── index.html        # Frontend: dashboard visual, responsive
└── lavanderia.db         # Se crea automáticamente al arrancar
```

## Personalizar

- **Duración por defecto de los ciclos**: en `main.py`, constantes
  `DURACION_DEFAULT_LAVADORA` y `DURACION_DEFAULT_SECADORA` (en minutos).
- **Cantidad de máquinas**: en `main.py`, constantes `NUM_LAVADORAS` y
  `NUM_SECADORAS`.

## Guía para el dueño de la lavandería (sin conocimientos técnicos)

Esta parte es para entregarle al cliente final, quien va a operar el sistema
día a día sin depender de ti.

### Uso diario
1. Doble clic en **`Iniciar Sistema.bat`** (está en esta misma carpeta).
2. Se abre una ventana negra — es normal, **no la cierres** mientras se use
   el sistema. El navegador se abrirá solo después de unos segundos.
3. Para usarlo desde el celular: conectarse a la **misma WiFi** de la
   computadora y entrar a `http://<IP-de-la-PC>:8000` (ver cómo obtener la
   IP más abajo).
4. Para apagar el sistema: cerrar esa ventana negra (o apagar la PC).

### Para que se inicie solo al prender la computadora (opcional, recomendado)
Así el dueño no tiene que acordarse de hacer doble clic cada día:
1. Presiona `Windows + R`, escribe `shell:startup` y Enter (abre una carpeta).
2. Copia un acceso directo de `Iniciar Sistema.bat` dentro de esa carpeta.
3. Desde ese momento, el sistema arranca solo cada vez que se prende la PC.

### Cómo obtener la IP de la computadora (para el celular)
1. En la PC, abrir el símbolo del sistema (buscar "cmd" en el menú inicio).
2. Escribir `ipconfig` y Enter.
3. Buscar el bloque **"Adaptador de LAN inalámbrica Wi-Fi"** y copiar el
   número de "Dirección IPv4" (ejemplo: `192.168.100.24`).
4. Esta IP puede cambiar si se reinicia el router — si el celular deja de
   conectar, repetir este paso.

### Importante: alcance de esta versión
- El sistema funciona **dentro de la lavandería**, mientras el celular y la
  computadora estén en la **misma red WiFi**. No es accesible desde fuera del
  local (por ejemplo, el dueño no podrá verlo desde su casa) — eso es lo que
  permite que sea 100% gratuito, sin depender de un servicio de hosting pago.
- Si en el futuro se quiere acceso desde cualquier lugar (por ejemplo, para
  supervisar desde otra sucursal o desde casa), existen opciones de
  hosting con planes gratuitos limitados (Render, Railway) — se puede evaluar
  más adelante si hace falta.

## Para desplegarlo con una URL real (no localhost), gratis

Ver la guía paso a paso en **`DEPLOY.md`** (despliegue gratuito en Render).
Incluye las limitaciones del plan gratuito y cómo pasar a uno pagado más
adelante si el negocio lo necesita.
