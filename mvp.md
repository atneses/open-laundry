# MVP: Sistema de Gestión de Lavandería

> Definición del MVP y propuesta de implementación · Última actualización: 2026-10-17

---

## 1. Revisión de la propuesta inicial

### Lo que está bien planteado
- El alcance es razonable para un MVP: ventas, clientes, inventario y control de equipos.
- Exponer todo mediante una API (DRF) es lo correcto: el mismo backend sirve a la web y, más adelante, a la app móvil.
- Docker desde el inicio permite no depender de un solo proveedor de nube (AWS / GCloud).

### Observaciones y huecos detectados

| # | Observación | Impacto | Recomendación |
|---|-------------|---------|---------------|
| 1 | ✅ *Corregido:* el modelo de la secadora en la propuesta inicial decía `CDG27RUNCNS`; el correcto (según la etiqueta) es **`CDG27RUCNS`**. | — | — |
| 2 | **Se supone control "por red local".** Los equipos comerciales LG no exponen una API local documentada. LG ofrece una **Commercial Laundry API** *cloud‑to‑cloud* (REST), y **solo para socios B2B de LG**. Además, los equipos se dan de alta con una app instaladora que entrega el representante de LG. | **Alto.** Es el requerimiento más riesgoso y del que depende el punto 4 de los generales. | Validar con LG **antes de desarrollar** (ver §4). Diseñar el sistema con una capa de abstracción y tener un plan B. |
| 3 | ✅ *Confirmado:* los equipos **tienen WiFi** y pueden conectarse a la red del local (internet estable); todavía no están conectados. **Ojo:** tener WiFi no basta para controlarlos desde nuestro sistema. Hace falta acceso a la API de LG (punto 2). | Medio | Fase 0: conectar una máquina y ver qué app/plataforma de LG la reconoce. |
| 4 | ✅ *Definido:* roles **administrador (admin)** y **empleado**, más de 5 usuarios. | Medio | Autenticación y permisos desde el MVP. Ver §3, *Roles y permisos*. |
| 5 | ✅ *Resuelto:* cobro **por carga** (lavadora / secadora), con **precios distintos para autoservicio y encargo**, y catálogo ampliable (p. ej. lavado de tenis). | — | Catálogo `Servicio` + `PrecioServicio` por modalidad (ver §3). El **encargo** necesita además un flujo de estados (recibido → listo → entregado). |
| 6 | ✅ *Resuelto:* pagos en **efectivo y tarjeta (crédito/débito)**; no se requiere CFDI. Corte de caja **por turno**. | Bajo | El cobro con tarjeta se hace en una terminal externa (banco, Clip, Mercado Pago Point) y el sistema solo registra tipo y referencia. Apertura y corte de caja por turno en el MVP. |
| 7 | "Inventario" no especifica qué se controla. | Bajo | Se propone: insumos (detergente, suavizante, bolsas) con entradas/salidas y stock mínimo. |
| 8 | Por ahora hay **una sola sucursal**, sin planes cercanos de abrir más. | Bajo | Mantener un modelo `Sucursal` mínimo (una fila), sin pantallas de multisucursal. Agregarlo desde el inicio cuesta casi nada y evita migraciones si después se abre otra. |
| 10 | El detergente y el suavizante van **incluidos siempre** (promoción permanente). Si el cliente trae los suyos, se usan los del cliente y **el precio no cambia**. | Medio (inventario) | El inventario no se mueve por ventas, sino por **consumo por carga**: se descuenta automáticamente cuando se usan los insumos de la casa. Ver §3. |
| 11 | Se necesita **imprimir tickets** para el cliente con el desglose del consumo. | Medio | Ticket en la impresora térmica del local (**POS-8360, 80 mm, USB**). Ver §3, *Ticket para el cliente*. |
| 9 | No se mencionan **notificaciones** al cliente (ropa lista). | Bajo | Fase 2: WhatsApp/SMS usando el teléfono ya registrado. |

---

## 2. Arquitectura propuesta

```
                    ┌──────────────────────┐      ┌──────────────────────┐
                    │  Web (React + Vite)  │      │ Mobile (React Native │
                    │  Panel admin / caja  │      │  / Expo) – Fase 3    │
                    └──────────┬───────────┘      └──────────┬───────────┘
                               │ HTTPS (JWT)                 │
                    ┌──────────▼─────────────────────────────▼───────────┐
                    │          API – Django + Django REST Framework       │
                    │  clientes · ventas · inventario · máquinas · caja   │
                    └───────┬───────────────────┬──────────────┬─────────┘
                            │                   │              │
                    ┌───────▼──────┐   ┌────────▼───────┐  ┌───▼──────────────┐
                    │ PostgreSQL   │   │ Redis          │  │ Celery workers   │
                    │              │   │ (broker/cache) │  │ (comandos a      │
                    └──────────────┘   └────────────────┘  │  máquinas, sync) │
                                                           └───┬──────────────┘
                                                               │ MachineDriver
                          ┌────────────────────────────────────┼─────────────────────┐
                          │                                    │                     │
                ┌─────────▼─────────┐            ┌─────────────▼──────────┐  ┌───────▼────────┐
                │ LG Commercial     │            │ Agente local en la     │  │ Simulador      │
                │ Laundry API       │            │ lavandería (plan B)    │  │ (desarrollo /  │
                │ (cloud-to-cloud)  │            │ ESP32/RPi + relés      │  │  pruebas)      │
                └─────────┬─────────┘            └─────────────┬──────────┘  └────────────────┘
                          │                                    │
                     Lavadoras / secadoras LG en la lavandería
```

### Stack

| Capa | Tecnología | Nota |
|------|------------|------|
| Backend | Django 5 + DRF | Se mantiene lo propuesto. |
| Auth | `djangorestframework-simplejwt` | JWT para la web y el móvil. Roles con Groups/Permissions de Django. |
| Tareas asíncronas | **Celery + Redis** | *Agregado.* Mandar comandos a las máquinas, consultar su estado y reintentar sin bloquear la API. |
| Tiempo real (opcional) | Django Channels o SSE | Mostrar el estado de las máquinas en vivo. Se puede empezar con *polling* cada 10 s. |
| Frontend | React + TypeScript + Vite | UI: MUI o shadcn/ui. Datos: TanStack Query. |
| Mobile | React Native (Expo) | Fase 3; consume la misma API. |
| BD | PostgreSQL 16 | |
| Documentación API | `drf-spectacular` (OpenAPI) | Permite generar el cliente TS automáticamente. |
| Contenedores | Docker + docker compose | Servicios: `api`, `worker`, `beat`, `db`, `redis`, `web`. |
| CI/CD | GitHub Actions | Pruebas, lint (ruff, eslint) y build de imágenes. |

### Despliegue (sin atarse a una nube)
- **Etapa inicial (bajo costo):** una sola VM (AWS EC2/Lightsail o GCP Compute Engine) con docker compose, Caddy/Nginx con HTTPS automático y respaldos diarios de PostgreSQL hacia S3/GCS.
- **Etapa de crecimiento:** BD administrada (RDS / Cloud SQL), contenedores en ECS Fargate / Cloud Run y Redis administrado.
- **Portabilidad:** configuración por variables de entorno (12‑factor) y almacenamiento con API compatible con S3 (`django-storages`). Nada específico de un proveedor dentro del código.

---

## 3. Módulos y modelo de datos

### Apps de Django
```
backend/
├── core/          # Sucursal, Usuario, roles, configuración
├── clientes/      # Cliente
├── inventario/    # Producto/Insumo, MovimientoInventario
├── ventas/        # Venta, DetalleVenta, Pago, CorteCaja, Servicio (catálogo/precios)
└── maquinas/      # Maquina, CicloUso, drivers/ (lg_cloud, local_agent, simulator)
```

### Entidades principales

```
Sucursal(id, nombre, direccion, telefono)

Usuario(id, nombre, email, rol[admin|empleado], sucursal, activo,
        permisos_extra(M2M Permission))
         — una cuenta por persona; al irse un empleado se desactiva
           (no se borra) para conservar su historial
         — rol = Group de Django (permisos por defecto);
           permisos_extra = user_permissions (agregados por un admin)

BitacoraPermiso(id, usuario, permiso, accion[otorgado|revocado],
                hecho_por(admin), fecha)

Cliente(id, nombre*, telefono*, email?, direccion?, notas?, creado_en)
        * obligatorio  — telefono único por sucursal

Servicio(id, nombre, tipo[lavado|secado|otro], unidad[carga|pieza|par],
         maquina_tipo[lavadora|secadora|ninguna], usa_maquina(bool), activo)
         — p. ej. "Lavado por carga", "Secado por carga", "Lavado de tenis"

PrecioServicio(id, servicio, modalidad[autoservicio|encargo],
               programa?, precio, vigente_desde, sucursal)
         — hoy: un precio fijo por servicio y modalidad (programa vacío)
         — a futuro: si se agregan precios por programa (p. ej. agua
           caliente, ciclo pesado, más tiempo de secado) se dan de alta
           filas con `programa` y el POS lo pide; si no existe precio
           para ese programa se usa el general. No requiere cambiar código.
         — agregar un servicio nuevo (p. ej. lavado de tenis) es solo
           dar de alta registros

Producto(id, nombre, sku, unidad(ml|g|pieza), costo, stock_actual,
         stock_minimo, se_vende(bool), precio_venta?, sucursal)
         — detergente y suavizante: se_vende = false (insumo interno)

ConsumoPorCarga(id, servicio, producto, cantidad)
         — solo aplica a "Lavado por carga" (el secado no consume insumos)
         — valor inicial: entre 150 y 200 ml de detergente y de suavizante
           por carga (pendiente de confirmar). Se carga como dato editable
           desde el admin, no en el código, para ajustarlo cuando se
           confirme la medida
         — tip: comparar el consumo teórico contra las compras reales cada
           mes sirve para afinar la medida y detectar mermas

MovimientoInventario(id, producto, tipo[entrada|consumo|venta|ajuste],
                     cantidad, costo_unitario?, ciclo_uso?, venta?,
                     usuario, fecha)
         — tipo = consumo se genera solo, al iniciar un ciclo que usa
           insumos de la casa

Venta(id, folio, cliente?, sucursal, usuario,
      modalidad[autoservicio|encargo],
      estado[pendiente_pago|pago_parcial|pagada|cancelada],
      subtotal, descuento, total, saldo, turno(CorteCaja),
      cancelada_por?, motivo_cancelacion?, cancelada_en?, creada_en)
      — cliente obligatorio cuando modalidad = encargo
      — autoservicio: se cobra completo antes de activar la máquina
      — encargo: se puede pagar al recibir, al entregar o con anticipo
        + resto (varios Pago por venta); no se entrega un encargo con
        saldo pendiente: solo el administrador puede hacerlo

Encargo(id, venta(1:1), estado[recibido|en_proceso|listo|entregado],
        fecha_promesa, entregado_en?, notas)
      — solo para modalidad = encargo; permite saber qué ropa está
        pendiente o lista y avisar al cliente

DetalleVenta(id, venta, servicio? | producto?, cantidad, precio_unitario, importe)
      — precio_unitario se copia de PrecioServicio según la modalidad
        de la venta (se conserva aunque el precio cambie después)

Pago(id, venta, metodo[efectivo|tarjeta_credito|tarjeta_debito], monto,
     referencia?, mp_payment_intent_id?, fecha)
      — tarjeta: terminal Mercado Pago Point. MVP: se captura la
        referencia del voucher a mano. Fase 2: integración con la API de
        Point (el POS envía el monto a la terminal y recibe la confirmación
        automáticamente, sin teclear montos ni referencias)

Descuento(id, nombre, tipo[porcentaje|monto_fijo], valor,
          alcance[venta|servicio], servicios?(M2M), modalidad?[autoservicio|encargo],
          vigente_desde?, vigente_hasta?, activo, creado_por(administrador))
          — solo el administrador los crea; el empleado elige de la lista los que
            aplican a esa venta (vigentes, de esa modalidad y servicio)
          — p. ej. "10% martes en autoservicio", "$20 menos en encargo"

SolicitudAutorizacion(...)   — FASE FUTURA, no se implementa en el MVP
          (id, tipo[entrega_con_saldo|ajuste_inventario|...],
          solicitante(empleado), objeto_tipo, objeto_id, datos(JSON: monto, motivo…),
          estado[pendiente|aprobada|rechazada|expirada|usada],
          resuelta_por?(administrador), comentario?, creada_en, expira_en, resuelta_en?)
          — la acción se ejecuta solo si hay una solicitud aprobada, vigente,
            sin usar y con los mismos datos

DescuentoAplicado(id, venta, detalle_venta?, descuento, monto, usuario)
          — guarda el monto calculado al momento y quién lo aplicó

CorteCaja(id, sucursal, usuario, apertura, cierre?, fondo_inicial,
          efectivo_esperado, efectivo_contado?, diferencia?,
          total_tarjeta, num_ventas, num_cancelaciones, notas?)
          — uno por turno y empleado; efectivo_esperado = fondo_inicial
            + pagos en efectivo del turno (menos los cancelados)
          — total_tarjeta se cuadra contra el reporte de Mercado Pago Point

Maquina(id, sucursal, tipo[lavadora|secadora], modelo, numero_serie,
        alias("Lavadora 3"), driver[lg_cloud|local_agent|simulator],
        id_externo, estado[disponible|en_uso|fuera_servicio|desconocido],
        ultima_sincronizacion)

CicloUso(id, maquina?, venta?, detalle_venta?, usuario, cliente?,
         programa?, insumos_cliente(bool, default false),
         inicio_solicitado, inicio_confirmado?, fin?,
         estado[pendiente_asignar|solicitado|en_curso|terminado|fallido|cancelado],
         respuesta_driver(JSON))
         — insumos_cliente = true → el cliente trajo su detergente: no se
           descuenta inventario y el precio no cambia
```

**Regla clave:** cada carga vendida de un servicio con `usa_maquina = true` genera un `CicloUso` ligado a la `DetalleVenta` (una venta de 3 cargas de lavado → 3 ciclos). Así se pueden **cuadrar las ventas contra los usos reales de las máquinas** y detectar ciclos no cobrados.

- **Autoservicio:** el cliente paga en el mostrador y el **empleado** activa la máquina desde la web; el ciclo se inicia de inmediato. El cliente no activa máquinas por su cuenta (no está en el alcance del MVP).
- **Insumos:** al iniciar un ciclo, si `insumos_cliente = false`, se genera un `MovimientoInventario(tipo=consumo)` según `ConsumoPorCarga`. Así el administrador ve cuánto cuesta la promoción del detergente gratis y recibe alertas de stock mínimo.
- **Encargo:** los ciclos quedan *pendientes de asignar* y el empleado los activa cuando procesa la ropa. El `Encargo` avanza de estado conforme se completan sus ciclos.

### Roles y permisos

Más de 5 usuarios, **cada empleado con su propia cuenta** (nunca compartida), para que ventas, cancelaciones y cortes queden a nombre de quien los hizo.

**Modelo:** cada acción del sistema es un **permiso**. Un **rol** es solo un paquete de permisos por defecto. Además, el admin puede **agregar permisos individuales** a un empleado concreto, para que haga acciones de admin sin convertirlo en admin. Por ejemplo, darle a Juan, el encargado de la tarde, permiso de *entregar encargos con saldo* y *ver cortes de caja*.

```
permisos efectivos de un usuario = permisos de su rol + permisos agregados a él
```

| Permiso | Código | Admin | Empleado (por defecto) | ¿Se puede agregar a un empleado? |
|---------|--------|:-----:|:----------------------:|:--------------------------------:|
| Cobrar ventas (autoservicio / encargo) e imprimir tickets | `ventas.cobrar` | ✅ | ✅ | — |
| Activar máquinas / registrar ciclos | `maquinas.activar` | ✅ | ✅ | — |
| Registrar clientes y gestionar encargos | `clientes.gestionar` | ✅ | ✅ | — |
| Aplicar descuentos **del catálogo autorizado** | `descuentos.aplicar` | ✅ | ✅ | — |
| Cancelar ventas (motivo obligatorio, queda en bitácora) | `ventas.cancelar` | ✅ | ✅ | — |
| Registrar entradas de inventario | `inventario.entrada` | ✅ | ✅ | — |
| Abrir y cerrar **su** caja (corte por turno) | `caja.operar` | ✅ | ✅ | — |
| Crear, editar o desactivar descuentos | `descuentos.gestionar` | ✅ | ❌ | ✅ |
| Ajustes de inventario (mermas, correcciones) | `inventario.ajustar` | ✅ | ❌ | ✅ |
| Entregar un encargo con saldo pendiente | `encargos.entregar_con_saldo` | ✅ | ❌ | ✅ |
| Ver cortes de otros turnos y diferencias de caja | `caja.ver_todos` | ✅ | ❌ | ✅ |
| Precios, servicios, consumo por carga | `catalogo.gestionar` | ✅ | ❌ | ✅ |
| Alta y configuración de máquinas | `maquinas.gestionar` | ✅ | ❌ | ✅ |
| Reportes (ventas, uso de máquinas, inventario, cancelaciones) | `reportes.ver` | ✅ | ❌ | ✅ |
| Gestionar usuarios, roles y permisos | `usuarios.gestionar` | ✅ | ❌ | ❌ **solo admin** |

- **Quién asigna:** solo un admin agrega o quita permisos. Gestionar usuarios y permisos **no se puede delegar**, para evitar que un empleado se dé permisos a sí mismo o a otros.
- **Efecto inmediato:** al quitar un permiso, el empleado pierde el acceso en su siguiente acción, sin cerrar sesión.
- **Bitácora:** se registra quién otorgó o quitó cada permiso y cuándo. Las acciones hechas con un permiso agregado quedan a nombre del empleado, igual que el resto.
- **Interfaz:** en la ficha de cada usuario, el admin ve los permisos del rol (fijos) y una lista de casillas con los permisos que puede agregar.
- **Implementación:** usa el sistema de permisos que ya trae Django: un `Group` por rol (`Admin`, `Empleado`), `Permission` personalizados con los códigos de la tabla y `user_permissions` para los permisos individuales. En DRF, cada endpoint declara el permiso que exige (p. ej. una clase `TienePermiso("encargos.entregar_con_saldo")`) y el frontend usa la lista de permisos efectivos solo para ocultar botones. **La validación real siempre ocurre en el backend.**
- Un empleado **no puede cobrar sin tener una caja abierta**: cada venta y cada pago quedan ligados a su turno.
- Las cancelaciones las puede hacer el empleado sin autorización, pero se registran (quién, cuándo, motivo, monto). El administrador las ve en un reporte de cancelaciones por empleado.
- **MVP:** si un empleado no tiene el permiso de una acción, esta queda **bloqueada** para él. La hace un admin o un empleado al que se le haya agregado ese permiso.
- **Fase futura:** permisos temporales (con fecha de vencimiento, p. ej. mientras el admin está de vacaciones) y roles personalizados (p. ej. "Encargado de turno") como paquetes de permisos con nombre, si se vuelve tedioso asignarlos uno por uno.
- **Fase futura:** autorización remota (ver abajo).

#### Autorización remota del administrador *(fase futura, fuera del MVP)*

> Diseño de referencia para cuando se implemente; en el MVP no se construye. El modelo de permisos del MVP ya deja preparado el punto donde se agregará.

Cuando el empleado intenta una acción reservada, en lugar de solo bloquearla el sistema le ofrece **"Solicitar autorización"**:

```
Empleado (caja)                    Sistema (nube)                     Admin (celular, desde cualquier lugar)
───────────────                    ──────────────                     ──────────────────────────────────────
Entregar encargo A-123  ──────►  crea SolicitudAutorizacion  ──────►  notificación push:
con saldo $80                    (pendiente, expira en 15 min)        "Juan quiere entregar A-123 con saldo $80"
                                                                              │
"Esperando autorización…"  ◄───  estado = aprobada / rechazada  ◄─────  [Aprobar]  [Rechazar] (+ comentario)
   │
   └─► si se aprueba, la acción se ejecuta y queda en bitácora con quién la pidió y quién la autorizó
```

- **Desde cualquier lugar:** el sistema está en la nube, así que el administrador entra desde su celular con el mismo sistema web (responsivo, instalable como app/PWA), sin estar en el local.
- **Notificación:** Web Push al celular del administrador (gratis, sin depender de terceros). Respaldo: correo. Más adelante: WhatsApp. Además, en el panel del administrador hay una bandeja de "Solicitudes pendientes".
- **Seguridad de la solicitud:**
  - Autoriza **exactamente** lo que se pidió (acción + venta + monto). Si algo cambia, se necesita otra solicitud.
  - Es de un solo uso y **expira** (15 min, configurable). Si expira, el empleado puede volver a pedirla.
  - Solo un administrador puede aprobarla.
- **Acciones que se pueden solicitar** (configurable por el administrador): entregar un encargo con saldo pendiente y ajustes de inventario. El mecanismo es genérico: si en el futuro se agrega otra acción reservada (p. ej. un descuento fuera del catálogo), se suma a la lista sin rediseñar nada.
- **Tiempo real:** la pantalla del empleado se actualiza sola al aprobarse (WebSocket/SSE o *polling* cada pocos segundos).

### Ticket para el cliente

Comprobante **no fiscal** (no se requiere CFDI), que se imprime al cobrar y se puede reimprimir desde el historial de ventas.

**Contenido (desglose del consumo):**
```
        LAVANDERÍA <nombre>
     <dirección> · <teléfono>
--------------------------------
Folio: A-000123   17/10/2026 14:32
Atendió: <cajero>
Cliente: <nombre> · <teléfono>      (si aplica)
Modalidad: ENCARGO
--------------------------------
Cant  Concepto            Importe
 3    Lavado por carga     $XXX.XX
        @ $XX.XX
 2    Secado por carga     $XXX.XX
        @ $XX.XX
      Detergente y suavizante
        (promoción)          $0.00
--------------------------------
Subtotal                   $XXX.XX
Descuento                   -$X.XX
TOTAL                      $XXX.XX
--------------------------------
Pagos:
  Anticipo  Efectivo       $XXX.XX
  Saldo pendiente          $XXX.XX
Entrega estimada: 18/10/2026 18:00
--------------------------------
  Comprobante no fiscal · Gracias
```
- En **autoservicio** se puede agregar la máquina asignada a cada carga ("Lavadora 3"), para que el cliente sepa cuál usar.
- En **encargo**, el ticket de recepción sirve de comprobante para recoger la ropa. Al entregar se imprime otro con los pagos y el saldo en $0.
- Si el cliente trajo su detergente, la línea de insumos dice "Insumos del cliente".
- Si se paga con tarjeta, se imprimen el tipo (crédito/débito) y la referencia del voucher; si se paga en efectivo, el monto recibido y el cambio.

**Implementación:**
- **MVP:** vista de ticket en React con CSS `@media print` a ancho de **80 mm** (~72 mm imprimibles, ~48 caracteres por línea), que se imprime con el diálogo del navegador en la impresora térmica **POS-8360 (USB)** instalada en la PC de caja (con su driver). No requiere software extra. Configurar en el navegador: sin márgenes, sin encabezados/pies y tamaño de papel de 80 mm.
- **Mejora (opcional):** impresión directa sin diálogo y apertura del cajón de dinero con comandos ESC/POS, por medio de un agente local (p. ej. QZ Tray) que habla con la impresora por USB. Conviene si el diálogo del navegador estorba en la operación diaria.
- El backend entrega los datos del ticket ya calculados (`/api/ventas/{id}/ticket/`), así el mismo formato sirve después para enviarlo por WhatsApp o como PDF.

### Endpoints principales (REST)
```
/api/auth/token/  /api/auth/refresh/
/api/auth/me/                  usuario actual + permisos efectivos (para el frontend)
/api/usuarios/                 CRUD de usuarios (solo admin)
/api/usuarios/{id}/permisos/   ver / agregar / quitar permisos individuales (solo admin)
/api/clientes/                 CRUD + búsqueda por teléfono/nombre
/api/servicios/                catálogo + precios por modalidad
/api/productos/                CRUD + /alertas-stock/
/api/inventario/movimientos/
/api/ventas/                   crear (con modalidad), pagar, cancelar
/api/ventas/{id}/ticket/       datos del ticket para imprimir / reimprimir
/api/encargos/                 listado por estado, cambiar estado, entregar
/api/descuentos/               catálogo (crear/editar: solo administrador; vigentes: empleado)
/api/caja/cortes/              abrir / cerrar turno, corte actual, historial (administrador)
/api/maquinas/                 listado con estado
/api/maquinas/{id}/iniciar/    POST → crea CicloUso y encola el comando
/api/maquinas/{id}/detener/
/api/ciclos/                   historial de usos (filtros por máquina y fecha)
/api/reportes/ventas-diarias/  /uso-maquinas/  /inventario/
```

---

## 4. Integración con lavadoras y secadoras LG (riesgo principal)

### Situación
- **Lavadoras:** 4 × `GCWM1069CD7`
- **Secadoras:** 2 × `CDG27RUCNS`

| Lavadora `GCWM1069CD7` | Secadora `CDG27RUCNS` |
|:---:|:---:|
| ![lavadora.png](lavadora.png) | ![secadora.png](secadora.png) |

- Los equipos **tienen WiFi** y el local tiene internet estable; **todavía no están conectados a la red**.

LG ofrece una **Commercial Laundry API** (REST, *cloud‑to‑cloud*) para operadores de autoservicio. Permite consultar información de los equipos, configurarlos y ver estadísticas de uso, pero **solo se entrega a socios B2B de LG**. Los equipos se registran con una app instaladora que da el representante tras firmar el acuerdo. No hay una API local pública. En 2026 LG también lanzó la línea *LG Professional Laundry* con la app LaundryCrew y una "Open API" que requiere un desarrollo de integración aparte.

> No se encontró documentación pública que confirme si estos dos modelos son compatibles con esa API, ni si la API permite **iniciar un ciclo de forma remota** (y no solo monitorear). **Hay que validarlo directamente con LG antes de comprometer fechas.**

### Estrategia: capa de abstracción `MachineDriver`

```python
class MachineDriver(Protocol):
    def get_status(self, maquina) -> MachineStatus: ...
    def start_cycle(self, maquina, programa: str | None, credito: Decimal) -> CommandResult: ...
    def stop_cycle(self, maquina) -> CommandResult: ...
```

Toda la lógica de negocio (ventas, ciclos, reportes) habla con esta interfaz y **no sabe qué tecnología hay detrás**. Así el sistema se construye y se prueba completo con el `SimulatorDriver` mientras se resuelve la integración real.

| Opción | Cómo funciona | Pros | Contras |
|--------|---------------|------|---------|
| **A. LG Commercial Laundry API** (preferida) | El backend llama a la API en la nube de LG. | Oficial, no toca el hardware, conserva la garantía. | Requiere un convenio B2B con LG; tiempos y costos inciertos; hay que confirmar que soporte el arranque remoto. |
| **B. Agente local + interfaz de pago del equipo** (plan B) | Un dispositivo en la lavandería (ESP32 o Raspberry Pi) se conecta a la interfaz de monedero/tarjeta de la máquina (la mayoría de los equipos comerciales aceptan pulsos de crédito) y simula el pago. El agente abre una conexión **saliente** al backend (MQTT o WebSocket), así no hay que abrir puertos en el router. | Independiente de LG; funciona con equipos sin WiFi. | Requiere hardware e instalación eléctrica; hay que revisar el manual de servicio y el tema de la garantía; da menos datos (solo crédito y, si acaso, una señal de "en uso"). |
| **C. Solo registro manual** (respaldo) | El cajero marca en el sistema que se inició el ciclo y lo arranca físicamente. | Cero riesgo técnico. | No hay control real; solo sirve como bitácora. |

**Recomendación:** salir con **C + simulador** en el MVP (el negocio opera desde el día 1), gestionar **A** en paralelo y prototipar **B** con una sola máquina si LG no responde en 4–6 semanas. Con solo 6 equipos, el plan B es acotado: un controlador por máquina (6 en total), y se valida primero con una lavadora antes de comprar el resto.

### Consideraciones de diseño para el control de máquinas
- **Idempotencia:** cada `iniciar` lleva un `CicloUso.id` para que un reintento no arranque dos ciclos.
- **Confirmación:** el ciclo queda `solicitado` hasta que el driver confirma el arranque; si no confirma en N segundos pasa a `fallido` y se avisa al cajero.
- **Sincronización:** una tarea periódica de Celery Beat consulta el estado de las máquinas y cierra ciclos terminados.
- **Auditoría:** se guarda la respuesta cruda del driver (`respuesta_driver`) para diagnosticar fallas.
- **Modo sin conexión:** si cae internet o la nube de LG, el sistema permite pasar a registro manual (opción C) sin perder la venta.

---

## 5. Seguridad
- HTTPS obligatorio; JWT con expiración corta + refresh token.
- Permisos por rol + permisos individuales agregados por un admin (tabla de §3), validados en el backend (no solo ocultando botones en el frontend). Solo un admin puede gestionar usuarios y permisos.
- Datos personales de clientes (nombre, teléfono): mínimo necesario, aviso de privacidad y respaldos cifrados.
- Credenciales de LG y del agente local en variables de entorno o *secrets manager*, nunca en el repositorio.
- Cada agente local se autentica con su propio token, que se puede revocar.
- Bitácora de acciones sensibles (cancelaciones con motivo, descuentos aplicados, ajustes de inventario, entregas con saldo, arranques manuales, diferencias de caja).

---

## 6. Plan de trabajo por fases

### Fase 0 – Preparación (1 semana)
- **Contactar a LG / distribuidor** sobre la Commercial Laundry API y la compatibilidad de los modelos.
- Conectar **una** lavadora a la red WiFi del local y ver con qué app de LG se registra (ThinQ, la app instaladora comercial, LaundryCrew) y qué permite hacer desde ahí (¿solo monitoreo o también arranque remoto?).
- Revisar en el manual de servicio si tienen interfaz de monedero/pulsos (solo para el plan B).
- Instalar el driver de la impresora POS-8360 en la PC de caja e imprimir un ticket de prueba de 80 mm desde el navegador (y, si se quiere imprimir sin diálogo, probar comandos ESC/POS con QZ Tray).
- Abrir una cuenta de desarrollador de Mercado Pago y revisar la API de Point para la terminal que ya tienen.
- Repositorio, estructura `backend/` + `frontend/`, docker compose, CI básico.

### Fase 1 – MVP operativo (4–6 semanas)
- Autenticación, usuarios, roles (admin / empleado) y permisos individuales que el admin puede agregar a un empleado.
- Clientes (alta rápida desde la caja por teléfono).
- Catálogo de servicios (lavado y secado por carga) con precio fijo de autoservicio y de encargo, ya preparado para precios por programa.
- Punto de venta: elegir la modalidad, crear la venta, cobrar en efectivo o tarjeta (registrando la referencia del voucher de Mercado Pago Point).
- Impresión de ticket con desglose del consumo en la impresora térmica de 80 mm (USB), y reimpresión.
- Encargos: recepción con fecha promesa, pago al recibir, al entregar o con anticipo, tablero "pendiente / listo / entregado".
- Inventario: entradas de insumos, consumo automático por carga (excepto si el cliente trae sus productos), alertas de stock mínimo.
- Máquinas: alta, tablero de estado, `CicloUso` con **driver manual y simulador**.
- Catálogo de descuentos autorizados (porcentaje o monto fijo, con vigencia, por servicio o modalidad).
- Apertura y corte de caja por turno; reportes básicos (ventas del día, uso por máquina, cancelaciones y descuentos por empleado).
- Despliegue en una VM con respaldos automáticos.

### Fase 2 – Integraciones (depende de LG, 3–6 semanas)
- Implementar `LGCloudDriver` **o** el prototipo del agente local (`LocalAgentDriver`) para las 4 lavadoras y 2 secadoras.
- Integración con la API de Mercado Pago Point: enviar el cobro a la terminal desde el POS y conciliarlo automáticamente.
- Estado de las máquinas en tiempo real.
- Conciliación ventas ↔ ciclos y alertas de ciclos sin cobro.

### Fase 3 – Crecimiento
- App móvil (Expo): el cliente consulta disponibilidad y paga o activa una máquina.
- Notificaciones por WhatsApp/SMS ("tu ropa está lista").
- Activación por el propio cliente desde su celular, con pago en línea (Mercado Pago), solo si el negocio lo decide.
- Precios por programa o por tiempo de secado (el modelo ya lo soporta; solo falta la UI).
- Facturación CFDI, solo si el negocio la llega a necesitar (hoy no se requiere).
- Multisucursal y tablero comparativo, si se abre otra sucursal.
- Autorización remota: el empleado solicita una acción reservada y el administrador la aprueba o rechaza desde su celular, con notificación Web Push (ver §3).
- Verificación en dos pasos (2FA) para la cuenta de administrador. Se recomienda sobre todo junto con la autorización remota; se dejó fuera del MVP para mantenerlo mínimo.
- Programa de lealtad / monedero electrónico.

---

## 7. Estructura de repositorio sugerida

```
Laundry/
├── backend/
│   ├── config/            # settings (base, dev, prod), urls, celery.py
│   ├── core/  clientes/  inventario/  ventas/  maquinas/
│   ├── requirements/      # o pyproject.toml
│   └── Dockerfile
├── frontend/
│   ├── src/ (api/, features/, components/, routes/)
│   └── Dockerfile
├── agent/                 # (Fase 2, plan B) firmware/servicio del agente local
├── docker-compose.yml
├── docker-compose.prod.yml
├── .env.example
└── docs/  (mvp.md, imágenes)
```

---

## 8. Decisiones del negocio

| Tema | Decisión |
|------|----------|
| Cobro | Por carga (lavadora / secadora). Precio **fijo** hoy, pero configurable por programa a futuro. |
| Modalidades | Autoservicio y encargo, con precios distintos. Catálogo ampliable (p. ej. lavado de tenis). |
| Pago de encargos | Al recibir, al entregar o con anticipo + resto: el sistema permite las tres. |
| Activación en autoservicio | El **empleado** la hace desde el mostrador. |
| Detergente / suavizante | Incluido siempre (promoción permanente). Si el cliente trae los suyos, se usan los suyos y el precio no cambia. Medida aproximada: 150–200 ml de cada uno por carga de lavado (por confirmar). |
| Métodos de pago | Efectivo y tarjeta (crédito / débito) con **Mercado Pago Point**. |
| Facturación | No se requiere CFDI por ahora. |
| Tickets | Ticket impreso para el cliente con desglose del consumo (comprobante no fiscal), en impresora térmica POS-8360 de 80 mm por USB. |
| Equipos | 4 lavadoras `GCWM1069CD7` y 2 secadoras `CDG27RUCNS`. |
| Conectividad | Internet estable; los equipos tienen WiFi y pueden conectarse a la red, pero aún no están conectados. |
| Sucursales | Una sola. |
| Roles | **Administrador (admin)** y **empleado**; más de 5 usuarios, cada uno con su propia cuenta. |
| Permisos | Cada acción es un permiso. El admin puede agregar permisos de admin a un empleado concreto (excepto gestionar usuarios y permisos). |
| Descuentos | El empleado solo aplica los autorizados por el administrador: porcentaje o monto fijo, con vigencia, por servicio o modalidad. |
| Cancelaciones | El empleado puede cancelar sin autorización, con motivo obligatorio y registro en bitácora. |
| Caja | Apertura y corte **por turno** y por empleado. |
| Autorizaciones | MVP: las acciones reservadas solo las hace un administrador. La autorización remota desde el celular queda para una fase futura. |

### Pendientes
1. Respuesta de LG / distribuidor sobre la Commercial Laundry API y el arranque remoto.
2. Qué permite la app de LG una vez conectada una máquina (monitoreo o arranque remoto), y si tienen interfaz de monedero/pulsos para el plan B.
3. Confirmar la medida exacta de detergente y de suavizante por carga (hoy se estima entre 150 y 200 ml). No bloquea el desarrollo: es un valor editable desde el admin.
4. Impresora **POS-8360** (80 mm, USB): no se encontró su ficha técnica pública. Las impresoras de esta gama suelen aceptar ESC/POS, tener corte automático y puerto para cajón, pero hay que comprobarlo con una impresión de prueba (Fase 0). Falta saber si se usa cajón de dinero.

---

### Referencias
- LG ThinQ Developer – Commercial Laundry API: https://thinq.developer.lge.com/en/cloud/about/service/commercial-laundry/
- Documentación Commercial Laundry: https://thinq.developer.lge.com/en/cloud/docs/commercial-laundry
- LG Professional Laundry (comunicado, jul. 2026): https://www.lg.com/my/about-lg/press-and-media/lg-electronics-launches-lg-professional-laundry-lineup-for-commercial-operations/
