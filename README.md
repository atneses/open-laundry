# Lavandería: sistema de gestión

Sistema web para la lavandería: caja y ventas, encargos, clientes, inventario, tickets y control de las lavadoras y secadoras.

> **Estado actual:** se construyen primero el backend y el panel de administración (Django + Unfold).

- **Qué se va a construir y por qué:** [`mvp.md`](mvp.md)
- **Plan de implementación paso a paso:** [`plan.md`](plan.md)
- **Reglas de código y forma de trabajo:** [`CLAUDE.md`](CLAUDE.md)

## Requisitos

- Docker y Docker Compose

## Levantar el entorno de desarrollo

```bash
cp .env.example .env          # y cambiar DJANGO_SECRET_KEY
docker compose up -d          # levanta la base de datos y la API
docker compose exec api python manage.py createsuperuser
```

| Qué | Dirección |
|-----|-----------|
| Admin (Django + Unfold) | http://localhost:8000/admin/ |
| Documentación de la API | http://localhost:8000/api/docs/ |

## Comandos útiles

```bash
docker compose exec api pytest                       # pruebas
docker compose exec api ruff check . && docker compose exec api ruff format .   # lint y formato
docker compose exec api python manage.py makemigrations
docker compose logs -f api                           # ver el log de la API
```

## Estructura

El código (apps, modelos, funciones, comentarios) está en inglés; los textos que ve el usuario, en español.

```
backend/     Django: config/ (settings) y core/
docs/        Imágenes, manuales y datos de configuración
```
