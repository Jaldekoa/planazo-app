# Planazo

**La excusa perfecta para salir.**

[![React](https://img.shields.io/badge/React-19-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev/)
[![Node.js](https://img.shields.io/badge/Node.js-22-339933?style=flat-square&logo=node.js&logoColor=white)](https://nodejs.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?style=flat-square&logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docs.docker.com/compose/)
[![Express](https://img.shields.io/badge/Express-5-000000?style=flat-square&logo=express&logoColor=white)](https://expressjs.com/)
[![Vite](https://img.shields.io/badge/Vite-8-646CFF?style=flat-square&logo=vite&logoColor=white)](https://vitejs.dev/)

---

## ¿Qué es Planazo?

Planazo es una aplicación web que conecta a personas con actividades de ocio cercanas. Los usuarios pueden **descubrir negocios y actividades**, **crear grupos de amigos**, **proponer planes** y **votar colectivamente**. Haciendo todo en un mismo sitio.

---

## Arquitectura

```
[Navegador]
     │
     │ HTTP :80
     ▼
[ Nginx ]  ◄── SPA React (build estático)
     │
     │ /api/*  proxy_pass
     ▼
[ Backend Node.js :3000 ]
     │
     ▼
[ PostgreSQL 16 ]
```

Tres contenedores Docker orquestados con `docker-compose`:

| Contenedor | Imagen | Descripción |
|------------|--------|-------------|
| `postgres` | `postgres:16` | Base de datos. Datos persistidos en volumen `postgres_data` |
| `backend`  | `node:22-alpine` | API REST Express 5. No expone puertos al host |
| `nginx`    | `nginx:alpine` | Sirve el SPA y hace proxy de `/api/*` al backend |

---

## Stack tecnológico

**Backend** — Node.js 22 · Express 5 · Sequelize · PostgreSQL · JWT · Multer · Zod

**Frontend** — React 19 · Vite 8 · React Router v7 · Leaflet · Lucide React

**Infraestructura** — Docker · Docker Compose · Nginx

---

## Instalación y arranque

### Prerrequisitos

- [Docker](https://docs.docker.com/get-docker/) y [Docker Compose](https://docs.docker.com/compose/) instalados
- Git con soporte para submodules

### 1. Clonar el repositorio

```bash
git clone --recurse-submodules https://github.com/Jaldekoa/planazo-app.git
cd planazo-app
```

> Si ya clonaste sin `--recurse-submodules`:
> ```bash
> git submodule update --init --recursive
> ```

### 2. Configurar variables de entorno

Crea el fichero `.env` dentro de `backend/`:

```bash
cp backend/.env.example backend/.env
```

Edita `backend/.env` con tus valores:

```env
# Base de datos
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=planazo
POSTGRES_USER=tu_usuario
POSTGRES_PASSWORD=tu_contraseña

# Servidor
APP_PORT=3000
JWT_SECRET=una_clave_secreta_larga_y_segura

# Servicios externos
CHATBOT_HOST=localhost
CHATBOT_PORT=5000
MODEL_HOST=localhost

# CORS (desarrollo local)
FRONT_PORT=5173
```

> Nunca subas el `.env` real al repositorio. El fichero `.env.example` es solo una plantilla.

### 3. Arrancar con Docker

```bash
docker compose up --build
```

La primera vez tardará unos minutos en descargar las imágenes y construir los contenedores. Una vez listo, abre el navegador en:

```
http://localhost
```

Para parar:

```bash
docker compose down
```

Para parar y borrar los datos de la base de datos:

```bash
docker compose down -v
```

---

## Estructura del proyecto

```
planazo-app/
├── backend/              # Submodule → Jaldekoa/backend
│   ├── src/
│   │   ├── config/       # Sequelize, CORS, JWT
│   │   ├── controllers/  # Lógica HTTP por recurso
│   │   ├── middlewares/  # Auth (JWT), RBAC, validación
│   │   ├── models/       # Modelos Sequelize + relaciones
│   │   ├── routes/       # Router central + sub-routers
│   │   ├── services/     # Lógica de negocio
│   │   └── utils/        # Logger, Multer
│   └── db/
│       └── 01_schema.sql # Esquema inicial de PostgreSQL
├── frontend/             # Submodule → Jaldekoa/frontend
│   └── src/
│       ├── components/   # Componentes reutilizables
│       ├── context/      # UserContext (estado global)
│       ├── hooks/        # useFetch, useForm, useDebounce…
│       ├── pages/        # Una página por ruta
│       ├── routes/       # React Router v7
│       └── services/     # Capa de fetch a /api/*
├── docker-compose.yml
└── .gitmodules
```

---

## Flujo de trabajo Git

Las ramas de feature siguen la convención `DES-<número>/<descripción>`, vinculadas a tickets de Jira:

```
main          ← entregas
 └── dev      ← integración continua
      └── DES-26/middleware-auth
      └── DES-77/rutas
      └── DES-99/provider-user-context
```

**Flujo:** crear rama desde `dev` → abrir PR → review → merge a `dev` → merge periódico a `main`

---

## Modelo de datos 

```
users ──────────────── groups  (M:M vía members)
  │                      │
  │                    plans
  │                      │
  └── user_preferences  proposals ── activities ── businesses
        │                  │
  activity_categories    votes
                           │
                         reviews ── review_categories
```

---

## Seguridad

- **JWT en httpOnly cookie** — no accesible desde JavaScript, protección contra XSS
- **RBAC** — roles `user`, `business`, `admin` aplicados por middleware
- **Rate limiting** — 100 peticiones / 5 min por IP
- **Helmet** — cabeceras de seguridad HTTP
- **Validación doble** — Zod en schemas + express-validator en middlewares
- **Redes Docker aisladas** — la BD no está expuesta al host

---

## Licencia

Repositorio privado — todos los derechos reservados.
