# Cómo publicar el sistema en internet (gratis, con Render)

Esto le da al sistema una dirección web real, por ejemplo:
```
https://control-lavanderia.onrender.com
```
en vez de `localhost` — accesible desde cualquier lugar, no solo desde la WiFi de la lavandería.

## Antes de empezar: limitaciones del plan gratuito

- **Se "duerme" tras 15 minutos sin visitas.** La primera vez que alguien
  entra después de eso, tarda 30-60 segundos en cargar. Después va normal.
- **El almacenamiento no es permanente.** Si el servicio se reinicia (Render
  lo hace de vez en cuando en el plan gratuito), se puede perder el estado
  de qué máquina está usando qué cliente en ese momento. Las 38 máquinas
  se vuelven a crear solas, vacías.
- Si más adelante esto se vuelve crítico para el negocio, existe la opción
  de pasar a un plan pagado (~$7/mes) que no tiene estas limitaciones.

## Paso 1 — Crear una cuenta en GitHub (si no tienes)

Render necesita el código en un repositorio de GitHub para publicarlo.
1. Ve a [github.com](https://github.com) y crea una cuenta gratuita.

## Paso 2 — Subir el proyecto a GitHub

1. En GitHub, crea un repositorio nuevo (botón verde "New").
   - Nómbralo por ejemplo `lavanderia-app`.
   - Puede ser público o privado, ambos son gratis.
2. Sube los archivos de la carpeta `lavanderia_app` a ese repositorio.
   La forma más simple sin usar comandos:
   - Entra al repositorio recién creado.
   - Click en "uploading an existing file".
   - Arrastra todos los archivos de la carpeta `lavanderia_app`
     (`main.py`, `database.py`, `auth.py`, `requirements.txt`, la carpeta
     `static/` completa). **No subas `lavanderia.db` ni `session_secret.key`
     si ya se generaron** — no hacen falta y es mejor que Render los cree solos.
   - Click en "Commit changes".

## Paso 3 — Crear una cuenta en Render

1. Ve a [render.com](https://render.com) y crea una cuenta gratuita
   (puedes registrarte directo con tu cuenta de GitHub, es más rápido).

## Paso 4 — Crear el servicio web

1. En el panel de Render, click en **"New +"** → **"Web Service"**.
2. Conecta tu cuenta de GitHub y selecciona el repositorio `lavanderia-app`.
3. Completa así:
   - **Name**: `control-lavanderia` (o el nombre que prefieras — será parte de la URL)
   - **Region**: la más cercana a Perú disponible (Oregon suele ser la opción más rápida de las gratuitas)
   - **Branch**: `main`
   - **Runtime**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Instance Type**: **Free**
4. Antes de crear, click en **"Advanced"** → **"Add Environment Variable"**:
   - **Key**: `SESSION_SECRET`
   - **Value**: cualquier texto largo y aleatorio (ejemplo: `mi-clave-super-secreta-2026-xyz789`)
   - Esto evita que todos tengan que volver a iniciar sesión cada vez que Render reinicie el servicio.
5. Click en **"Create Web Service"**.

## Paso 5 — Esperar el primer despliegue

Render va a instalar todo y arrancar el sistema — tarda unos 2-5 minutos la
primera vez. Cuando termine, te da la URL pública (algo como
`https://control-lavanderia.onrender.com`).

## Paso 6 — Probarlo

1. Entra a la URL que te dio Render.
2. Deberías ver la pantalla de login.
3. Usuario: `admin` — Contraseña: `lavanderia123` (cámbiala apenas entres).
4. Pruébalo también desde el celular, usando esa misma URL — ya no depende
   de estar en la misma WiFi.

## Actualizaciones futuras

Cada vez que quieras subir un cambio (por ejemplo, si mejoramos algo del
diseño), solo tienes que volver a subir los archivos actualizados a GitHub
(mismo Paso 2) — Render detecta el cambio y vuelve a desplegar solo.

## Si más adelante quieres eliminar las limitaciones del plan gratuito

En el panel de Render, el mismo servicio se puede pasar a un plan pagado
(actualmente desde $7/mes) con un clic, sin tener que rehacer nada — eso
elimina el "dormido" y agrega almacenamiento permanente. Podemos evaluarlo
cuando el negocio lo necesite.
