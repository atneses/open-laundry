# Reglas de CLAUDE
Respuestas lo menos verbosas posible: DEBES proporcionar respuestas cortas pero sin omitir nada importante.

Hacer únicamente lo que se pidió. Si detectas algún potencias riesgo, preguntar si se debe tomar en cuenta en la implementación.

# Reglas del proyecto: Sistema de Gestión de Lavandería

Lee esto antes de trabajar en el proyecto. Para el **qué** y el **porqué** del sistema, ver [`mvp.md`](mvp.md); para el **orden de trabajo**, [`plan.md`](plan.md).

## Antes de empezar una tarea

1. Revisa en `plan.md` en qué etapa y paso va el proyecto (casillas `[x]` / `[ ]`).
2. Revisa en `mvp.md` el modelo de datos, los permisos y las reglas de negocio que aplican. Los nombres de modelos, campos, permisos, endpoints y temas MQTT ya están definidos ahí: **úsalos tal cual**.
3. Si algo del plan o del MVP no encaja con lo que se está construyendo, pregunta antes de cambiar el diseño, y actualiza `mvp.md` / `plan.md` si se decide otra cosa.

## Idioma

- **Todo el código en inglés:** apps, modelos, campos, funciones, variables, nombres de pruebas, comentarios, docstrings, nombres de pasos de CI (cuando exista) y comentarios de configuración.
- **Lo que ve el usuario también se escribe en inglés en el código**, marcado para traducción con `gettext_lazy as _` (`verbose_name`, `choices`, títulos del admin y del menú, mensajes de error, nombres de permisos). La interfaz se muestra en **español (México)** mediante las traducciones de `backend/locale/es_MX/`.
  - Los nombres de permisos (`Meta.permissions`) se guardan como texto en la base de datos y el admin no los traduce solo; tenerlo en cuenta al agregar sus traducciones.
- **Documentación para el negocio en español:** `mvp.md`, `plan.md`, `README.md`.
- Las equivalencias concepto → nombre en código están en `mvp.md` §3, *Nombres en el código*.

## Stack (no cambiar sin acordarlo)

| Parte               | Tecnología                                                                                                 |
|---------------------|------------------------------------------------------------------------------------------------------------|
| Backend             | Python 3.14, **Django 5.2 LTS**, Django REST Framework, `djangorestframework-simplejwt`, `drf-spectacular` |
| Admin               | Django Admin + `django-unfold` (back-office: configuración, consultas, reportes)                           |
| Tareas              | Celery + Redis                                                                                             |
| Base de datos       | PostgreSQL 16                                                                                              |
| Frontend (caja)     | React + TypeScript + Vite, **Tailwind + shadcn/ui**, TanStack Query, React Router                          |
| Control de máquinas | MQTT (Mosquitto) + programa propio en la cajita de relés                                                   |
| Entorno             | Docker + docker compose                                                                                    |

Las versiones están fijadas en `backend/requirements/*.txt` (y en `frontend/package.json` cuando exista).

## Estilo de código Python y Django

Todo el código Python sigue **[PEP 8](https://peps.python.org/pep-0008/)** y las **prácticas recomendadas de Django** ([coding style](https://docs.djangoproject.com/en/5.2/internals/contributing/writing-code/coding-style/) y documentación oficial).

**PEP 8 (lo aplica `ruff`, configurado en `backend/pyproject.toml`):**
- Líneas de máximo **99 caracteres** (el límite extendido que permite PEP 8); docstrings y comentarios largos, mejor cerca de 72.
- Nombres: `snake_case` para funciones, variables y módulos; `PascalCase` para clases; `UPPER_CASE` para constantes.
- Imports en tres grupos (biblioteca estándar, terceros, proyecto), ordenados, uno por línea, sin `import *` (excepto en los settings que heredan de `base`).
- Indentación de 4 espacios, dos líneas en blanco entre definiciones de nivel superior.
- Docstrings en las clases y funciones públicas, en inglés.
- El formato lo pone `ruff format`; no discutir estilo a mano.
- **Líneas en blanco** (`ruff format` las conserva pero no las agrega; se escriben a mano):
  - después del docstring de funciones y métodos;
  - antes y después de cada bloque (`if`, `for`, `while`, `with`, `try`, `match`), salvo al inicio o al final del bloque que lo contiene;
  - antes del `return` final de una función, si hay código antes.
  - Las tres reglas anteriores no aplican a los cuerpos de clase (campos, `Meta`), que siguen el espaciado del formateador.
  - Antes de un comentario de línea completa que va después de código (el comentario explica lo que sigue), en funciones, clases y módulos; salvo si abre un bloque o va después de otro comentario. No aplica a comentarios dentro de listas, diccionarios o llamadas.

**Prácticas de Django:**
- **Modelos:** orden de miembros como indica Django (campos → managers → `class Meta` → `__str__` → `save` → `get_absolute_url` → métodos propios). Todo modelo tiene `__str__`. Usar `TextChoices` / `IntegerChoices` para valores fijos (estados, tipos). `related_name` explícito en las relaciones. Restricciones e índices en `Meta.constraints` / `Meta.indexes` cuando una regla deba cumplirse siempre (p. ej. teléfono único por sucursal).
- **Usuario:** referirse a él con `settings.AUTH_USER_MODEL` en relaciones y `get_user_model()` en código; nunca importar `core.User` directamente desde otras apps.
- **Consultas:** evitar consultas en bucle (usar `select_related` / `prefetch_related`); operaciones que cambian varios registros juntos (cobrar, cerrar caja, generar ciclos) dentro de `transaction.atomic()`. Usar `F()` para actualizar contadores o stock sin condiciones de carrera.
- **Vistas y API:** vistas delgadas; validación en serializers / formularios; lógica de negocio en servicios o métodos del modelo. Preferir las vistas genéricas y `ViewSet` de DRF.
- **Fechas y horas:** siempre con zona horaria (`django.utils.timezone.now()`, nunca `datetime.now()`).
- **Seguridad:** nunca construir SQL concatenando texto; no desactivar CSRF; secretos solo desde variables de entorno.
- **Textos de la interfaz:** en inglés y siempre marcados para traducción (`gettext_lazy as _`), incluidos los `verbose_name`.
- **Settings:** acceder con `from django.conf import settings`, nunca importando el módulo de settings.
- Pasar `python manage.py check` (y `check --deploy` con los settings de producción antes de desplegar).

## Backend (Django)

- **Apps:** `core` (sucursal, usuarios, permisos), `customers`, `inventory`, `sales` (catálogo, ventas, pagos, encargos, descuentos, caja), `machines` (cajita, máquinas, ciclos). **Cada app se crea en la etapa que la necesita**; no crear otras apps sin acordarlo.
- **Modelos:**
  - Nombres en inglés y `verbose_name` / `verbose_name_plural` en inglés con `_()` en cada modelo y campo.
  - Todo modelo hereda de `core.models.BaseModel` (`created_at`, `updated_at`, `created_by`, `updated_by`). El usuario lo pone `core.middleware.CurrentUserMiddleware`; `bulk_create` y `QuerySet.update` no pasan por `save`, así que deben llenar esos campos a mano. No agregar campos propios de "quién lo registró" o "fecha de alta": usar `created_by` / `created_at`.
  - Todo lo que pertenece a un local lleva `branch` (FK a `core.Branch`).
  - Montos con `DecimalField` (nunca `float`).
  - Los registros con historial (ventas, pagos, cortes, bitácoras) **no se borran**: se cancelan o desactivan.
- **Migraciones:** siempre en el repositorio, generadas con `makemigrations`. Nunca editar la base de datos a mano. Verificar que no falten con `makemigrations --check`.
- **Permisos:**
  - Cada acción se protege con los códigos de permiso de `mvp.md` §4 (p. ej. `sales.charge`, `sales.deliver_with_balance`).
  - **La validación siempre en el backend:** los servicios reciben al usuario y validan el permiso de la acción (así se prueban sin HTTP y protegen también admin y consola), y cada endpoint de DRF lo repite con su clase de permiso (403). El frontend solo oculta botones.
  - Quien tiene `core.manage_users` decide todos los permisos: puede darlo a un rol o como permiso extra.
  - Los permisos se definen en el `Meta.permissions` del modelo de su app. Los roles (*Admin*, *Empleado*) se crean con una migración de datos y después el admin los edita; `migrate` nunca deshace esos cambios. Cada etapa que define permisos agrega una migración de datos que llama a `core.roles.grant_permissions` (Admin: todos los de la app; Empleado: los marcados en la tabla de `mvp.md` §4), que solo agrega permisos.
- **API:**
  - Por defecto todo endpoint exige autenticación (JWT). Hacer público un endpoint solo si se justifica (como `/api/health/`).
  - Rutas en inglés y en plural con guiones (`/api/cash-sessions/`).
  - Documentar con `drf-spectacular` (tipos de respuesta correctos) para que el frontend pueda generar sus tipos.
- **Lógica de negocio** (cálculo de totales, corte de caja, generación de ciclos, consumo de insumos) en funciones o servicios del modelo/app, no en las vistas, para poder probarla sin HTTP.
- **Admin (Unfold):** ventas, pagos, cortes y bitácoras de **solo lectura**. Usar las clases de `unfold.admin` (`ModelAdmin`, etc.).
  - Para los registros con historial, heredar de `core.admin_base.ReadOnlyModelAdmin`, que no permite agregar, editar ni borrar.
- **Menú del admin:** cada modelo nuevo se agrega al menú lateral en `UNFOLD["SIDEBAR"]` (`config/settings/base.py`), dentro de su área de `mvp.md` §2 (creando el área si no existe), con un ícono de Material Symbols y `"permission"` que revise el permiso de vista del modelo (p. ej. `request.user.has_perm("core.view_user")`).
- **Configuración:** valores sensibles o por entorno solo desde variables de entorno (`.env`, que no se sube a git; documentar las nuevas en `.env.example`). Settings en `config/settings/{base,dev,test,prod}.py`.
- **Idioma de la interfaz:** no volver a agregar `LocaleMiddleware`; el sistema se muestra solo en español. Las traducciones de los textos propios van en `backend/locale/es_MX/LC_MESSAGES/django.po` y se actualizan con `makemessages -l es_MX --ignore=.venv --ignore="*/tests/*"`; las de Unfold (que no trae español) se escriben a mano en `backend/locale_unfold/`, aparte para que `makemessages` no las marque como obsoletas. Ambas se compilan con `compilemessages --ignore=.venv`.

## Frontend (caja)

> Estas reglas aplican cuando exista `frontend/` (ver `plan.md`).


- Componentes de UI con **shadcn/ui** (`npx shadcn@latest add <componente>`); los archivos generados viven en `src/components/ui/`.
- Estilos con clases de Tailwind; no crear archivos CSS por componente.
- Datos del servidor con **TanStack Query**; llamadas a la API por `src/lib/api.ts` y rutas relativas `/api/...` (Vite las reenvía al backend).
- Tipos de la API generados con `npm run api:gen` (con la API levantada) en `src/api/schema.d.ts`. **No escribir a mano tipos que ya da la API**; regenerarlos cuando cambie un endpoint.
- Importar con el alias `@/` (p. ej. `@/components/ui/button`).
- Textos visibles en español (mediante traducciones); nombres de componentes, variables y archivos en inglés.

## Pruebas y calidad

- **Cada regla de negocio lleva su prueba** (cobro, saldo, corte de caja, permisos, ciclos, inventario). Incluir también el caso de error (p. ej. empleado sin permiso → 403).
- Backend: `pytest` + `pytest-django` (pruebas en `<app>/tests/test_*.py`). Frontend: `vitest` + Testing Library (`*.test.tsx` junto al componente).
- **Patrón AAA (Arrange, Act, Assert):** cada prueba prepara los datos, hace **una sola acción** y comprueba el resultado, con una línea en blanco entre cada parte (sin comentarios `# Arrange`). Si una prueba necesita varias acciones (p. ej. sin permiso → 403 y con permiso → 200), se separa en varias pruebas o se usa `parametrize`. La acción dentro de `pytest.raises` cuenta como el Act. Las pruebas de una o dos líneas pueden omitir las líneas en blanco.
- Antes de dar algo por terminado, todo esto debe pasar:
  ```bash
  docker compose exec api ruff format . && docker compose exec api ruff check .
  docker compose exec api pytest
  docker compose exec api python manage.py makemigrations --check --dry-run
  # Cuando exista frontend/:
  cd frontend && npm run lint && npm run typecheck && npm test && npm run build
  ```
- Si algo no se pudo verificar, decirlo explícitamente.

## Entorno de desarrollo

- Todo corre en Docker: `docker compose up -d`. Comandos de Django con `docker compose exec api ...`.
- Admin: http://localhost:8000/admin/ · Docs API: http://localhost:8000/api/docs/
- La base de datos **no publica su puerto** en la PC (el 5432 está ocupado): `docker compose exec db psql -U laundry`.

## Git

- Una rama por etapa o funcionalidad (`feature/etapa-1`, `feature/sales`…), con *pull request* hacia `main`.
- **No hacer commit, push ni merge sin que el usuario lo pida.**
- Mensajes de commit con prefijo convencional, en inglés: `feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`.
- Nunca subir: `.env`, la carpeta `Aitaire/` (datos privados del negocio), respaldos de firmware (`firmware/*.bin`).
- No crear apps, carpetas, servicios ni dependencias antes de que una etapa del plan los necesite.

## Desarrollo incremental: primero lo mínimo indispensable

Cada funcionalidad se construye **primero en su versión mínima que funcione** y cumpla el "Listo cuando" de su paso en `plan.md`. Lo demás se agrega después, cuando se necesite.

- **Sí entra en la primera versión:** el flujo principal, las validaciones que protegen dinero o datos (permisos, montos, saldos, stock) y sus pruebas.
- **No entra (se anota como pendiente):** opciones "por si acaso", configuraciones que nadie pidió, optimizaciones sin un problema medido, pantallas o campos de fases futuras, abstracciones para casos que aún no existen.
- Si una mejora parece valiosa, **se propone al usuario** en lugar de construirla.

**Documentar riesgos y pendientes de cada funcionalidad.** Al terminarla, agregar en su etapa de `plan.md` una sección **"Riesgos y pendientes"** con:

- **Riesgos:** lo que podría fallar o no está probado en condiciones reales (p. ej. "no probado con la impresora real", "si se cae internet durante el cobro, …", "regla supuesta, falta confirmar con el negocio").
- **Pendientes:** lo que se dejó fuera de la versión mínima, lo que falta para que esté completa y lo que depende de otra etapa o de información del negocio.

Si no hay riesgos ni pendientes, escribir "Ninguno identificado" en lugar de omitir la sección. Lo importante debe repetirse también en el resumen al usuario.

## Al terminar un paso del plan

1. Marcar sus casillas en `plan.md` y anotar en la etapa cualquier diferencia con lo planeado.
2. Completar la sección **"Riesgos y pendientes"** de la etapa (ver arriba).
3. Si cambió una decisión, actualizar `mvp.md` (y regenerar su índice si cambiaron los títulos).
4. Resumir al usuario qué se hizo, cómo se verificó, y qué riesgos y pendientes quedan.

## Seguridad y hardware

- Las pruebas de la cajita de relés se hacen con los cables de las máquinas **desconectados** (o las máquinas en modo PUSH), para no regalar créditos.
- Antes de reprogramar la placa, respaldar el programa de Aitare (`esptool.py read_flash`).
- Credenciales (MQTT, Mercado Pago, LG) solo en variables de entorno.

## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- When graphify-out/graph.json exists, run `graphify query "<question>"` before your first grep, search or source-file read for a codebase question, and put this rule in every subagent prompt that explores code. Read raw files only for lines the graph or an earlier read already located. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
- A committed graphify-out/graph.json is rewritten whole on every build, so a large diff to it in a pull request is expected. Do not flag it as churn or suggest skipping the graph rebuild or its hooks.
