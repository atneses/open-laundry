# MVP: Sistema de Gestión de Lavandería

> Definición del MVP y propuesta de implementación · Última actualización: 2026-10-18

Sistema web para una lavandería de una sola sucursal con autoservicio y servicio por encargo: ventas y caja, clientes, encargos, inventario de insumos, tickets y **activación de las lavadoras y secadoras desde el sistema**, con registro de cada uso.

---

## Índice

- [1. Requerimientos y decisiones](#1-requerimientos-y-decisiones)
- [2. Arquitectura](#2-arquitectura)
  - [Stack](#stack)
  - [Interfaces](#interfaces)
- [3. Modelo de datos](#3-modelo-de-datos)
  - [Apps de Django](#apps-de-django)
  - [Entidades](#entidades)
  - [Reglas del modelo](#reglas-del-modelo)
- [4. Funcionalidades](#4-funcionalidades)
  - [Roles y permisos](#roles-y-permisos)
  - [Ticket para el cliente](#ticket-para-el-cliente)
  - [Endpoints principales (REST)](#endpoints-principales-rest)
- [5. Control de lavadoras y secadoras](#5-control-de-lavadoras-y-secadoras)
  - [Equipos](#equipos)
  - [La cajita de relés (instalación de Aitare)](#la-cajita-de-relés-instalación-de-aitare)
  - [Plan: programa propio en la cajita](#plan-programa-propio-en-la-cajita)
  - [Configuración de las máquinas](#configuración-de-las-máquinas)
  - [Opciones evaluadas](#opciones-evaluadas)
- [6. Seguridad](#6-seguridad)
- [7. Plan de trabajo](#7-plan-de-trabajo)
  - [Fase 0 – Preparación](#fase-0--preparación)
  - [Fase 1 – MVP operativo](#fase-1--mvp-operativo)
  - [Fase 2 – Control de máquinas e integraciones](#fase-2--control-de-máquinas-e-integraciones)
  - [Fase 3 – Crecimiento](#fase-3--crecimiento)
- [8. Estructura del repositorio](#8-estructura-del-repositorio)
- [9. Pendientes](#9-pendientes)
- [Anexo: diseños para fases futuras](#anexo-diseños-para-fases-futuras)
  - [Autorización remota del administrador](#autorización-remota-del-administrador)
- [Referencias](#referencias)

---

## 1. Requerimientos y decisiones

| Área                        | Decisión                                                                                                                                                                                    |
|-----------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Cobro**                   | Por carga (lavadora / secadora). Precio **fijo** hoy, configurable por programa a futuro.                                                                                                   |
| **Modalidades**             | Autoservicio y encargo, con precios distintos. Catálogo ampliable (p. ej. lavado de tenis).                                                                                                 |
| **Encargos**                | Se cobran al recibir, al entregar o con anticipo + resto. Estados: recibido → en proceso → listo → entregado.                                                                               |
| **Activación de máquinas**  | La hace el **empleado** desde la caja, después de cobrar. El cliente no activa máquinas en el MVP.                                                                                          |
| **Detergente y suavizante** | Incluidos siempre (promoción permanente). Si el cliente trae los suyos, se usan y el precio no cambia. Unos **150–200 ml de cada uno** por carga de lavado (por confirmar).                 |
| **Clientes**                | Nombre y teléfono obligatorios; dirección y demás datos opcionales.                                                                                                                         |
| **Inventario**              | Insumos (detergente, suavizante, bolsas): entradas, consumo automático por carga, stock mínimo.                                                                                             |
| **Pagos**                   | Efectivo y tarjeta (crédito / débito) en terminal **Mercado Pago Point**. Sin CFDI por ahora.                                                                                               |
| **Caja**                    | Apertura y corte **por turno** y por empleado.                                                                                                                                              |
| **Tickets**                 | Comprobante no fiscal con desglose del consumo, en impresora térmica **POS-8360 de 80 mm por USB**.                                                                                         |
| **Roles**                   | **Administrador (admin)** y **empleado**. Más de 5 usuarios, cada uno con su propia cuenta.                                                                                                 |
| **Permisos**                | Cada acción es un permiso. El admin puede agregar permisos de admin a un empleado concreto (excepto gestionar usuarios y permisos).                                                         |
| **Descuentos**              | El empleado solo aplica los del catálogo que crea el admin: porcentaje o monto fijo, con vigencia, por servicio o modalidad.                                                                |
| **Cancelaciones**           | El empleado puede cancelar sin autorización, con motivo obligatorio y registro en bitácora.                                                                                                 |
| **Acciones reservadas**     | Solo las hace un admin o un empleado con ese permiso. La autorización remota desde el celular queda para una fase futura.                                                                   |
| **Back-office**             | Admin de Django personalizado con **Unfold**. React solo para la operación diaria.                                                                                                          |
| **Equipos**                 | 4 lavadoras `GCWM1069CD7` y 2 secadoras `CDG27RUCNS` (LG, comerciales).                                                                                                                     |
| **Control de máquinas**     | **Cajita de relés existente** con programa propio, conectada por MQTT: manda pulsos de crédito a la entrada de pago de cada máquina. Respaldo: modo libre (PUSH) + registro manual. Ver §5. |
| **Sucursales**              | Una sola. Se guarda un modelo `Sucursal` mínimo por si se abre otra.                                                                                                                        |
| **Infraestructura**         | Nube (AWS de inicio, sin atarse a ella) con Docker. API para web y, a futuro, móvil.                                                                                                        |

---

## 2. Arquitectura

```mermaid
flowchart TB
    subgraph front["Clientes de la API"]
        web["Web (React + Vite)<br/>Operación diaria: caja, encargos, máquinas"]
        mobile["Mobile (React Native / Expo)<br/>Fase 3"]
    end

    adminui["Navegador del admin<br/>Configuración, catálogo, usuarios y permisos,<br/>consultas y dashboard"]

    subgraph django["Django"]
        api["API: Django REST Framework<br/>clientes · ventas · inventario · máquinas · caja"]
        admin["Django Admin + Unfold (/admin/)"]
    end
    db[("PostgreSQL")]
    redis[("Redis<br/>broker / cache")]
    worker["Celery workers<br/>MachineDriver: comandos a máquinas"]
    broker["Broker MQTT (Mosquitto)"]
    listener["Escucha MQTT<br/>confirmaciones, estado, consumo"]

    web -- "HTTPS (JWT)" --> api
    mobile -. "HTTPS (JWT)" .-> api
    adminui -- "HTTPS (sesión)" --> admin
    api --> db
    admin --> db
    api --> redis
    redis --> worker
    worker --> db
    worker -- "comando" --> broker
    broker --> listener
    listener --> db

    subgraph local["Lavandería"]
        placa["Cajita de relés (ESP8266)<br/>programa propio"]
        shelly["Medidores de consumo<br/>(opcional)"]
        maq["4 lavadoras + 2 secadoras LG<br/>entrada de pago"]
    end

    broker <-- "MQTT cifrado" --> placa
    shelly -.-> broker
    placa -- "pulsos de crédito por cable" --> maq
    shelly -. mide .-> maq

    lg["LG Commercial Laundry API<br/>(opción a futuro)"]
    sim["Simulador<br/>(desarrollo / pruebas)"]
    worker -.-> lg
    worker -.-> sim
```

### Stack

| Capa                   | Tecnología                                                                  | Nota                                                                       |
|------------------------|-----------------------------------------------------------------------------|----------------------------------------------------------------------------|
| Backend                | Django 5 + DRF                                                              |                                                                            |
| Auth                   | `djangorestframework-simplejwt`                                             | JWT para web y móvil; permisos con Groups/Permissions de Django.           |
| Tareas asíncronas      | Celery + Redis                                                              | Comandos a máquinas y reintentos sin bloquear la API.                      |
| Control de máquinas    | MQTT (Mosquitto) + programa propio en la cajita (ESPHome o firmware propio) | La cajita se conecta sola al broker; no hay que abrir puertos en el local. |
| Admin / back-office    | Django Admin + `django-unfold`                                              | Ver *Interfaces*.                                                          |
| Frontend               | React + TypeScript + Vite                                                   | Solo operación diaria. UI: MUI o shadcn/ui. Datos: TanStack Query.         |
| Tiempo real (opcional) | Django Channels o SSE                                                       | Se puede empezar con *polling* cada 10 s.                                  |
| Mobile                 | React Native (Expo)                                                         | Fase 3; misma API.                                                         |
| BD                     | PostgreSQL 16                                                               |                                                                            |
| Documentación API      | `drf-spectacular` (OpenAPI)                                                 | Genera el cliente TS.                                                      |
| Contenedores           | Docker + docker compose                                                     | `api`, `worker`, `beat`, `db`, `redis`, `web`, `mqtt`, `mqtt-listener`.    |
| CI/CD                  | GitHub Actions                                                              | Pruebas, lint (ruff, eslint), build de imágenes.                           |

**Despliegue:** al inicio, una VM (AWS EC2/Lightsail o GCP Compute Engine) con docker compose, Caddy/Nginx con HTTPS y respaldos diarios de PostgreSQL a S3/GCS. Al crecer: BD administrada (RDS / Cloud SQL), ECS Fargate / Cloud Run y Redis administrado. Configuración por variables de entorno y almacenamiento compatible con S3 (`django-storages`): nada específico de un proveedor en el código.

### Interfaces

| Interfaz                                                                              | Quién la usa                             | Para qué                                                                                                                                 |
|---------------------------------------------------------------------------------------|------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------|
| **Web React** (caja)                                                                  | Empleados y admin                        | Punto de venta, encargos, activar máquinas, abrir/cerrar caja, imprimir tickets.                                                         |
| **Django Admin + [Unfold](https://github.com/unfoldadmin/django-unfold)** (`/admin/`) | Admin y empleados con permisos agregados | Usuarios y permisos, catálogo y precios, descuentos, consumo por carga, inventario, máquinas y cajita, consultas, dashboard de reportes. |

**Personalización con Unfold:** marca de la lavandería (logo, colores, modo claro/oscuro, español); menú lateral por áreas (*Operación*, *Catálogo*, *Inventario*, *Máquinas*, *Usuarios y permisos*, *Bitácoras*), visible según permisos; **dashboard** con ventas del día (efectivo / tarjeta), cargas por máquina, encargos pendientes y listos, stock bajo, diferencias de caja, cancelaciones y descuentos por empleado; filtros (fechas, empleado, modalidad, método de pago, máquina) y búsqueda global; fichas con pestañas (una venta con sus detalles, pagos, descuentos y ciclos); acciones (máquina fuera de servicio, desactivar descuento, reimprimir ticket, pulso de prueba).

**Reglas del admin:** ventas, pagos, cortes y bitácoras son **de solo lectura**; se crean y cancelan solo desde la caja. Entran el rol admin y los empleados con algún permiso agregado (`is_staff`), y cada sección respeta la tabla de permisos. Usa sesión de Django (no JWT); estáticos con WhiteNoise o Nginx.

---

## 3. Modelo de datos

### Apps de Django
```
backend/
├── core/          # Sucursal, Usuario, roles, configuración
├── clientes/      # Cliente
├── inventario/    # Producto, ConsumoPorCarga, MovimientoInventario
├── ventas/        # Servicio, PrecioServicio, Venta, DetalleVenta, Pago, Encargo, Descuento, CorteCaja
└── maquinas/      # Controlador, Maquina, CicloUso, drivers/ (relay_board, manual, simulator, lg_cloud)
```

### Entidades

```mermaid
erDiagram
    SUCURSAL ||--o{ USUARIO : tiene
    SUCURSAL ||--o{ CLIENTE : tiene
    SUCURSAL ||--o{ MAQUINA : tiene
    SUCURSAL ||--o{ PRODUCTO : tiene
    SUCURSAL ||--o{ PRECIO_SERVICIO : define
    SUCURSAL ||--o{ CONTROLADOR : tiene
    USUARIO ||--o{ BITACORA_PERMISO : "recibe / otorga"
    USUARIO ||--o{ CORTE_CAJA : abre
    USUARIO ||--o{ VENTA : registra
    CORTE_CAJA ||--o{ VENTA : "turno de"
    CLIENTE |o--o{ VENTA : compra
    VENTA ||--|{ DETALLE_VENTA : contiene
    VENTA ||--o{ PAGO : "se paga con"
    VENTA ||--o| ENCARGO : "si es encargo"
    VENTA ||--o{ DESCUENTO_APLICADO : recibe
    DESCUENTO ||--o{ DESCUENTO_APLICADO : "se aplica como"
    DESCUENTO }o--o{ SERVICIO : "aplica a"
    SERVICIO ||--o{ PRECIO_SERVICIO : "tiene precios"
    SERVICIO |o--o{ DETALLE_VENTA : "se vende en"
    PRODUCTO |o--o{ DETALLE_VENTA : "se vende en"
    SERVICIO ||--o{ CONSUMO_POR_CARGA : consume
    PRODUCTO ||--o{ CONSUMO_POR_CARGA : "se consume en"
    PRODUCTO ||--o{ MOVIMIENTO_INVENTARIO : registra
    DETALLE_VENTA |o--o{ CICLO_USO : "genera (1 por carga)"
    CONTROLADOR |o--o{ MAQUINA : "controla (1 relé c/u)"
    MAQUINA |o--o{ CICLO_USO : ejecuta
    CICLO_USO |o--o{ MOVIMIENTO_INVENTARIO : "descuenta insumos"

    SUCURSAL {
        int id PK
        string nombre
        string direccion
        string telefono
    }
    USUARIO {
        int id PK
        string nombre
        string email
        string rol "admin | empleado (Group de Django)"
        int sucursal_id FK
        bool activo
        m2m permisos_extra "user_permissions agregados por un admin"
    }
    BITACORA_PERMISO {
        int id PK
        int usuario_id FK
        string permiso
        string accion "otorgado | revocado"
        int hecho_por FK "admin"
        datetime fecha
    }
    CLIENTE {
        int id PK
        string nombre "obligatorio"
        string telefono "obligatorio, único por sucursal"
        string email "opcional"
        string direccion "opcional"
        text notas
        datetime creado_en
    }
    SERVICIO {
        int id PK
        string nombre "Lavado por carga, Secado por carga, Lavado de tenis"
        string tipo "lavado | secado | otro"
        string unidad "carga | pieza | par"
        string maquina_tipo "lavadora | secadora | ninguna"
        bool usa_maquina
        bool activo
    }
    PRECIO_SERVICIO {
        int id PK
        int servicio_id FK
        string modalidad "autoservicio | encargo"
        string programa "opcional, para precios por programa a futuro"
        decimal precio
        date vigente_desde
        int sucursal_id FK
    }
    PRODUCTO {
        int id PK
        string nombre
        string sku
        string unidad "ml | g | pieza"
        decimal costo
        decimal stock_actual
        decimal stock_minimo
        bool se_vende "false para detergente y suavizante"
        decimal precio_venta "opcional"
        int sucursal_id FK
    }
    CONSUMO_POR_CARGA {
        int id PK
        int servicio_id FK
        int producto_id FK
        decimal cantidad "150 a 200 ml, editable"
    }
    MOVIMIENTO_INVENTARIO {
        int id PK
        int producto_id FK
        string tipo "entrada | consumo | venta | ajuste"
        decimal cantidad
        decimal costo_unitario "opcional"
        int ciclo_uso_id FK "opcional"
        int venta_id FK "opcional"
        int usuario_id FK
        datetime fecha
    }
    VENTA {
        int id PK
        string folio
        int cliente_id FK "obligatorio en encargo"
        int sucursal_id FK
        int usuario_id FK
        string modalidad "autoservicio | encargo"
        string estado "pendiente_pago | pago_parcial | pagada | cancelada"
        decimal subtotal
        decimal descuento
        decimal total
        decimal saldo
        int turno_id FK "CorteCaja"
        int cancelada_por FK "opcional"
        string motivo_cancelacion "opcional"
        datetime cancelada_en "opcional"
        datetime creada_en
    }
    ENCARGO {
        int id PK
        int venta_id FK "1:1"
        string estado "recibido | en_proceso | listo | entregado"
        datetime fecha_promesa
        datetime entregado_en "opcional"
        text notas
    }
    DETALLE_VENTA {
        int id PK
        int venta_id FK
        int servicio_id FK "o producto"
        int producto_id FK "o servicio"
        decimal cantidad
        decimal precio_unitario "copiado de PrecioServicio"
        decimal importe
    }
    PAGO {
        int id PK
        int venta_id FK
        string metodo "efectivo | tarjeta_credito | tarjeta_debito"
        decimal monto
        string referencia "voucher de Mercado Pago Point"
        string mp_payment_intent_id "Fase 2"
        datetime fecha
    }
    DESCUENTO {
        int id PK
        string nombre
        string tipo "porcentaje | monto_fijo"
        decimal valor
        string alcance "venta | servicio"
        string modalidad "opcional: autoservicio | encargo"
        date vigente_desde "opcional"
        date vigente_hasta "opcional"
        bool activo
        int creado_por FK "admin"
    }
    DESCUENTO_APLICADO {
        int id PK
        int venta_id FK
        int detalle_venta_id FK "opcional"
        int descuento_id FK
        decimal monto
        int usuario_id FK
    }
    CORTE_CAJA {
        int id PK
        int sucursal_id FK
        int usuario_id FK
        datetime apertura
        datetime cierre "opcional"
        decimal fondo_inicial
        decimal efectivo_esperado
        decimal efectivo_contado "opcional"
        decimal diferencia "opcional"
        decimal total_tarjeta
        int num_ventas
        int num_cancelaciones
        text notas
    }
    CONTROLADOR {
        int id PK
        int sucursal_id FK
        string nombre "Cajita principal"
        string mqtt_client_id
        string credencial_hash
        bool en_linea
        datetime ultima_conexion
        string version_firmware
    }
    MAQUINA {
        int id PK
        int sucursal_id FK
        string tipo "lavadora | secadora"
        string modelo
        string numero_serie
        string alias "Lavadora 3"
        string driver "relay_board | manual | simulator | lg_cloud"
        int controlador_id FK "opcional"
        int canal_rele "1 a 8"
        int pulsos_por_ciclo
        int ancho_pulso_ms "50 o 100"
        int pausa_entre_pulsos_ms
        string medidor_id "opcional"
        string id_externo
        string estado "disponible | en_uso | fuera_servicio | desconocido"
        datetime ultima_sincronizacion
    }
    CICLO_USO {
        int id PK
        int maquina_id FK "opcional hasta asignarse"
        int venta_id FK
        int detalle_venta_id FK
        int usuario_id FK
        int cliente_id FK "opcional"
        string programa "opcional"
        bool insumos_cliente "default false"
        datetime inicio_solicitado
        datetime inicio_confirmado "opcional"
        datetime fin "opcional"
        string estado "pendiente_asignar | solicitado | credito_enviado | en_curso | terminado | fallido | cancelado"
        bool manual "true si se arrancó en modo PUSH"
        json respuesta_driver
    }
```

### Reglas del modelo

**Ventas y ciclos**
- **Cada carga vendida** de un servicio con `usa_maquina = true` genera un `CicloUso` (3 cargas → 3 ciclos). Así se **cuadran las ventas contra los usos reales** y se detectan ciclos no cobrados.
- **Autoservicio:** se cobra completo, el empleado activa la máquina y el ciclo se inicia de inmediato.
- **Encargo:** los ciclos quedan *pendientes de asignar* y el empleado los activa al procesar la ropa; él `Encargo` avanza de estado con ellos. Se puede pagar en varios `Pago`. Un encargo con saldo solo lo entrega quien tenga `encargos.entregar_con_saldo`.
- **Estados del ciclo:** `solicitado` → `credito_enviado` (la cajita confirmó el crédito; falta presionar Start) → `en_curso` (por el medidor de consumo, el empleado o por tiempo) → `terminado`. Si la cajita no confirma pasa a `fallido`. `manual = true` cuando se arrancó en modo PUSH.
- **DetalleVenta:** un servicio **o** un producto. `precio_unitario` se copia de `PrecioServicio` según la modalidad y se conserva aunque el precio cambie.

**Precios y descuentos**
- **PrecioServicio:** hoy un precio fijo por servicio y modalidad (`programa` vacío). Para cobrar distinto ciertos programas se agregan filas con `programa`; si no hay, se usa el general. Un servicio nuevo es solo dar de alta registros.
- **Descuento:** los crea quien tenga `descuentos.gestionar`. El empleado elige de la lista los vigentes para esa modalidad y servicio (p. ej. "10% martes en autoservicio"). `DescuentoAplicado` guarda el monto y quién lo aplicó.

**Inventario**
- **ConsumoPorCarga:** solo para lavado (el secado no consume). Valor inicial 150–200 ml de detergente y 150–200 ml de suavizante, editable desde el admin.
- Al iniciar un ciclo con `insumos_cliente = false` se genera un `MovimientoInventario(tipo=consumo)`. Así se ve el costo de la promoción y salen alertas de stock mínimo. Comparar cada mes el consumo teórico contra las compras ayuda a afinar la medida y detectar mermas.

**Caja y pagos**
- **CorteCaja:** uno por turno y empleado; no se puede cobrar sin caja abierta. `efectivo_esperado = fondo_inicial + pagos en efectivo del turno` (menos cancelados). `total_tarjeta` se cuadra contra el reporte de Mercado Pago Point.
- **Pago con tarjeta:** en el MVP se captura a mano la referencia del voucher; en la Fase 2 la integración con la API de Point la llena sola (`mp_payment_intent_id`).

**Usuarios y máquinas**
- **Usuario:** una cuenta por persona; al irse se desactiva (no se borra). `rol` = `Group` de Django; `permisos_extra` = `user_permissions`.
- **Controlador / Máquina:** una cajita controla las 6 máquinas, un relé por máquina (`canal_rele`). Los pulsos de cada máquina deben coincidir con su configuración de pago (ver §5).

---

## 4. Funcionalidades

### Roles y permisos

Cada acción es un **permiso**. Un **rol** es un paquete de permisos por defecto, y el admin puede **agregar permisos individuales** a un empleado (p. ej. al encargado de la tarde: *entregar encargos con saldo* y *ver cortes de caja*) sin convertirlo en admin.

```
permisos efectivos = permisos del rol + permisos agregados al usuario
```

| Permiso                                      | Código                        | Admin | Empleado | ¿Se puede agregar a un empleado? |
|----------------------------------------------|-------------------------------|:-----:|:--------:|:--------------------------------:|
| Cobrar ventas e imprimir tickets             | `ventas.cobrar`               |  ✅   |    ✅    |                —                 |
| Activar máquinas / registrar ciclos          | `maquinas.activar`            |  ✅   |    ✅    |                —                 |
| Registrar clientes y gestionar encargos      | `clientes.gestionar`          |  ✅   |    ✅    |                —                 |
| Aplicar descuentos del catálogo              | `descuentos.aplicar`          |  ✅   |    ✅    |                —                 |
| Cancelar ventas (con motivo)                 | `ventas.cancelar`             |  ✅   |    ✅    |                —                 |
| Registrar entradas de inventario             | `inventario.entrada`          |  ✅   |    ✅    |                —                 |
| Abrir y cerrar **su** caja                   | `caja.operar`                 |  ✅   |    ✅    |                —                 |
| Crear, editar o desactivar descuentos        | `descuentos.gestionar`        |  ✅   |    ❌    |                ✅                |
| Ajustes de inventario (mermas, correcciones) | `inventario.ajustar`          |  ✅   |    ❌    |                ✅                |
| Entregar un encargo con saldo pendiente      | `encargos.entregar_con_saldo` |  ✅   |    ❌    |                ✅                |
| Ver cortes de otros turnos                   | `caja.ver_todos`              |  ✅   |    ❌    |                ✅                |
| Precios, servicios, consumo por carga        | `catalogo.gestionar`          |  ✅   |    ❌    |                ✅                |
| Alta y configuración de máquinas y cajita    | `maquinas.gestionar`          |  ✅   |    ❌    |                ✅                |
| Reportes                                     | `reportes.ver`                |  ✅   |    ❌    |                ✅                |
| Gestionar usuarios, roles y permisos         | `usuarios.gestionar`          |  ✅   |    ❌    |        ❌ **solo admin**         |

- Solo un admin agrega o quita permisos; **gestionar usuarios y permisos no se delega**, para que nadie se dé permisos a sí mismo.
- Al quitar un permiso, deja de valer en la siguiente acción, sin cerrar sesión. Se registra quién lo otorgó o quitó y cuándo.
- Si un empleado no tiene el permiso, la acción queda **bloqueada**: la hace un admin o un empleado con ese permiso.
- **Implementación:** `Group` por rol, `Permission` personalizados con los códigos de la tabla y `user_permissions` para los individuales. Cada endpoint de DRF declara el permiso que exige; el frontend solo oculta botones. **La validación siempre ocurre en el backend.** En el admin, la ficha del usuario muestra los permisos del rol y casillas para los extra.

### Ticket para el cliente

Comprobante **no fiscal**, que se imprime al cobrar y se puede reimprimir.

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

- **Autoservicio:** puede indicar la máquina asignada a cada carga ("Lavadora 3").
- **Encargo:** el ticket de recepción sirve para recoger la ropa; al entregar se imprime otro con saldo en $0.
- La línea "Detergente y suavizante (promoción) $0.00" sale **siempre** que haya cargas de lavado. Si el cliente trajo sus productos, el ticket no cambia (`insumos_cliente` es solo interno).
- Con tarjeta: tipo y referencia del voucher. En efectivo: monto recibido y cambio.
- **Impresión (MVP):** vista React con `@media print` a **80 mm** (~48 caracteres por línea) en la POS-8360 USB, desde el diálogo del navegador (sin márgenes ni encabezados). **Mejora opcional:** impresión directa y apertura de cajón con ESC/POS vía QZ Tray. El backend entrega los datos ya calculados (`/api/ventas/{id}/ticket/`), reutilizables para WhatsApp o PDF.

### Endpoints principales (REST)
```
/api/auth/token/  /api/auth/refresh/
/api/auth/me/                     usuario actual + permisos efectivos
/api/usuarios/                    CRUD (solo admin)
/api/usuarios/{id}/permisos/      agregar / quitar permisos individuales (solo admin)
/api/clientes/                    CRUD + búsqueda por teléfono/nombre
/api/servicios/                   catálogo + precios por modalidad
/api/productos/                   CRUD + /alertas-stock/
/api/inventario/movimientos/
/api/ventas/                      crear (con modalidad), pagar, cancelar
/api/ventas/{id}/ticket/          datos del ticket
/api/encargos/                    listado por estado, cambiar estado, entregar
/api/descuentos/                  catálogo (gestionar / vigentes)
/api/caja/cortes/                 abrir / cerrar turno, corte actual, historial
/api/maquinas/                    listado con estado
/api/maquinas/{id}/iniciar/       crea CicloUso y encola el comando
/api/maquinas/{id}/pulso-prueba/  solo con maquinas.gestionar
/api/controladores/               estado de la cajita (en línea, última conexión)
/api/ciclos/                      historial de usos
/api/reportes/ventas-diarias/  /uso-maquinas/  /inventario/
```

---

## 5. Control de lavadoras y secadoras

### Equipos

|  Lavadora `GCWM1069CD7` (×4)  |  Secadora `CDG27RUCNS` (×2)   |
|:-----------------------------:|:-----------------------------:|
| ![lavadora.png](lavadora.png) | ![secadora.png](secadora.png) |

Del manual de la lavadora (`Wahser_GCWM1069CD7_manual.pdf`):
- Modelo tipo **tarjeta / OPL**. Desde el menú de servicio se elige **PAY** (monedas o tarjeta) o **FREE / OPL** (*On-Premise Laundry*: sin pago, muestra *PUSH* y arranca con Start). Hoy las máquinas están en **OPL**.
- En modo PAY acepta **monedero por pulsos de crédito** (50 o 100 ms) con valor configurable por pulso, o lector de tarjeta Greenwald / ESD.
- 120 V, 60 Hz, enchufe de 3 patas en contacto propio.
- Tiene WiFi para la plataforma comercial **LG Laundry Lounge** (no LG ThinQ). Una lavadora ya está en la red, sin registrar. **El control no depende de ese WiFi.**
- Contraseña de fábrica del menú de servicio: `3000` (ver §6).
- Falta revisar el manual de la secadora.

### La cajita de relés (instalación de Aitare)

|                             |                                                                                                                                                                                                                                                                                                                                                   |
|-----------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **Hardware**                | Placa genérica de **8 relés** (Songle SRD-05VDC) con **ESP-12F (ESP8266)**, alimentación de 7 a 28 V. Usa **6 relés**, uno por máquina, cableados a la **entrada de pago**. Tiene expuesto el puerto de programación (5V, TXD, RXD, IO0, GND).                                                                                                    |
| **Cómo funcionaba**         | El programa "ControlEquipos" (Visual Basic 6, en la PC del negocio) le mandaba órdenes por **HTTP en una red local aislada**: router propio de Aitare, sin internet, red `192.168.10.x` (`/?E=1&T=…`, `/?E=3&PM=…&PR=…`). La cajita cerraba el relé varias veces, como monedas; la máquina **pitaba y mostraba el tiempo** y se presionaba Start. |
| **Por qué se dejó de usar** | Fallaba seguido. Causa probable: la PC tenía que estar en la red sin internet y Windows se cambiaba sola a la red con internet. Otras posibles: antena del ESP8266 dentro de la caja de plástico o la fuente. La distancia no es problema (local de 4 × 7 m). El router de Aitare está apagado.                                                   |

Fotos y copia del programa: carpeta `Aitaire/`.

### Plan: programa propio en la cajita

Se conservan la placa, los relés y los 6 cables; solo se cambia el programa (ESPHome o firmware propio):

1. Se **respalda el programa de Aitare** (adaptador USB-serie) para poder volver atrás.
2. Se retira el router de Aitare; la placa se conecta al **WiFi principal del local (2.4 GHz)**.
3. La placa abre una conexión **saliente y cifrada** al broker MQTT en la nube: sin puertos abiertos ni PC encendida en el local.
4. Si la señal del ESP8266 no alcanza, se cambia solo la placa por una **ESP32 de 8 relés con antena externa**.

**Cómo se comunica:**
- `RelayBoardDriver` (implementa `MachineDriver`) publica en `lavanderia/<controlador>/cmd`: `{"id": 812, "canal": 3, "pulsos": 4, "ancho_ms": 50, "pausa_ms": 150}`.
- La cajita envía los pulsos por el relé y responde en `lavanderia/<controlador>/ack`: `{"id": 812, "ok": true}`. Publica *en línea / fuera de línea* con el mensaje de "última voluntad" de MQTT.
- **Sin pulsos duplicados:** él `id` es el del `CicloUso`; la cajita recuerda los últimos y no repite si llega un reintento.
- La **escucha MQTT** (proceso aparte) recibe confirmaciones, estado y consumo, y actualiza `CicloUso`, `Maquina` y `Controlador`. Se guarda la respuesta cruda en `respuesta_driver`.
- Cada cajita tiene su propio usuario MQTT y solo accede a sus temas.

**Flujo de una venta:**

```mermaid
sequenceDiagram
    actor E as Empleado
    participant S as Sistema
    participant P as Cajita
    participant L as Lavadora 3

    E->>S: Cobra 1 carga de lavado (autoservicio)
    S->>S: Crea CicloUso (solicitado)
    S->>P: cmd {id: ciclo 812, relé 3, 4 pulsos, 50 ms}
    P->>L: 4 pulsos (como 4 monedas)
    P-->>S: ack {id: ciclo 812, ok}
    S-->>E: "Crédito enviado: presiona Start en Lavadora 3"
    S->>S: CicloUso → crédito enviado
    E->>L: Elige programa y Start
    Note over S,L: Con medidor: el consumo sube → en curso<br/>El consumo baja → terminado
    alt La cajita no confirma en 10 s
        S-->>E: "Sin respuesta de la cajita: usa modo manual"
        S->>S: CicloUso → fallido (la venta se conserva)
    end
```

- **Caja:** "Activar Lavadora 3" → "Crédito enviado: presiona Start", con indicador de cajita en línea.
- **Admin:** alta de la cajita, relé y pulsos por máquina, **pulso de prueba** y bitácora de órdenes.
- **Sin ciclos colgados:** una tarea de Celery Beat cierra por tiempo los ciclos sin medidor.
- **Sin internet o con la cajita fallando:** la máquina se pasa a **OPL (PUSH)** y la venta se registra a mano (`CicloUso.manual`), sin perderla.

### Configuración de las máquinas

| Ajuste                                               | Valor                                                                                                                       | Página del manual (PDF) |
|------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------|:-----------------------:|
| Entrar al menú de servicio                           | Tarjeta de servicio o interruptor + contraseña                                                                              |        23–24, 26        |
| Pago o libre (`Product Type`)                        | **`PAY`** (respaldo: `FrEE` / OPL)                                                                                          |           68            |
| Monedas o tarjeta (`Vend Type`)                      | **Coin**                                                                                                                    |           70            |
| Duración del pulso (`Coin Drop Type`)                | 50 ms o 100 ms, igual que `Maquina.ancho_pulso_ms`                                                                          |           72            |
| Precio por programa (`Regular Price Setup`)          | Según los pulsos (0.00–9.95)                                                                                                |          26–29          |
| Valor de cada pulso (`Coin 1 Value`)                 | **Pulsos por ciclo = precio ÷ valor por pulso** (fábrica: 1.00 ÷ 0.25 = 4). Se puede simplificar a 1 pulso igualando ambos. |           63            |
| Tiempo que guarda el crédito (`Standby Return Time`) | 0 = siempre; 1–180 = ese tiempo                                                                                             |           66            |
| Indicador de crédito completo                        | El LED de Start parpadea (*"full vend price has been satisfied"*)                                                           |           12            |
| Operación normal                                     | Programa → precio → crédito → Start                                                                                         |           22            |

Aitare ya tenía esta configuración: hay que copiar sus valores de ControlEquipos. El manual de usuario no muestra el conector físico de la entrada de pago (está en el manual de servicio o se ve en la instalación).

### Opciones evaluadas

| Opción                                                                | Rol           | Resumen                                                                                                                                                       |
|-----------------------------------------------------------------------|---------------|---------------------------------------------------------------------------------------------------------------------------------------------------------------|
| **A. Cajita de relés con programa propio**                            | **Principal** | Hardware y cableado ya instalados, independiente de LG, la máquina no arranca sin pago. Requiere cambiar el programa (reversible) y alguien presiona Start.   |
| **B. LG Smart Laundry Lounge / Commercial Laundry API**               | A futuro      | Oficial y con más datos. Solo para socios B2B de LG; documentación no pública; no se sabe si permite iniciar ciclos. Información pedida con `contacto_lg.md`. |
| **C. Medición de consumo** (p. ej. Shelly Plus Plug US, 120 V / 15 A) | Complemento   | Confirma arranque y fin y cuenta ciclos reales, por MQTT. No arranca máquinas; hay que calibrar el umbral.                                                    |
| **D. Registro manual** (OPL / PUSH)                                   | Respaldo      | Sin riesgo técnico; solo bitácora.                                                                                                                            |
| LG ThinQ / `pythinqconnect` / Home Assistant                          | Descartada    | Son para aparatos de casa; estos equipos usan Laundry Lounge.                                                                                                 |

**Recomendación:** construir el MVP con **D + simulador**, conectar **A** en cuanto se pruebe con una lavadora y sumar **C** para confirmar arranque y fin. **B** queda según lo que responda LG.

Sobre LG: la [página de LG México](https://www.lg.com/mx/business/lavanderia-comercial/smart-laundry-lounge/) ofrece Smart Laundry Lounge con la app **LG Laundry Crew** y una API (más de 40 endpoints: Dispositivo, Estadísticas, Tienda, Registro, Callback). El acceso pasa por acuerdos (confidencialidad, licencia), una clave de pruebas con app instaladora y una clave de producción, desde `smartsolution.developer.lge.com`. Ese portal público solo documenta la ThinQ Business API, para aparatos de casa.

---

## 6. Seguridad

- HTTPS obligatorio; JWT con expiración corta + refresh token.
- Permisos validados en el backend (§4); solo un admin gestiona usuarios y permisos.
- Datos de clientes: el mínimo necesario, aviso de privacidad y respaldos cifrados.
- Credenciales (MQTT, LG, Mercado Pago) en variables de entorno o *secrets manager*, nunca en el repositorio.
- MQTT cifrado; cada cajita con su propio usuario revocable y acceso solo a sus temas; solo el backend publica órdenes.
- **Cambiar la contraseña de fábrica `3000`** del menú de servicio de las máquinas, si el menú lo permite: con ella se puede pasar una máquina a modo libre.
- Bitácora de acciones sensibles: cancelaciones, descuentos, ajustes de inventario, entregas con saldo, arranques manuales, diferencias de caja, cambios de permisos.

---

## 7. Plan de trabajo

### Fase 0 – Preparación
- **Cajita:** capturas de la configuración de pulsos de cada equipo en ControlEquipos; foto de la conexión de un relé; adaptador USB-serie (CH340 o CP2102); respaldo del programa de Aitare; prueba con **una lavadora** en modo PAY; confirmar WiFi de 2.4 GHz.
- **Máquinas:** manual de la secadora; cambiar la contraseña `3000`; probar un medidor de consumo en una lavadora (opcional).
- **LG:** enviar la consulta de información (`contacto_lg.md`) y revisar el portal de desarrolladores con sesión iniciada.
- **Caja:** driver de la POS-8360 y ticket de prueba de 80 mm; cuenta de desarrollador de Mercado Pago (API de Point).
- **Proyecto:** repositorio, estructura `backend/` + `frontend/`, docker compose, CI básico.

### Fase 1 – MVP operativo
- Autenticación, usuarios, roles y permisos individuales.
- Admin con Unfold: marca, menú, configuración (catálogo, precios, descuentos, consumo por carga, máquinas, usuarios y permisos) y consultas de solo lectura.
- Clientes (alta rápida por teléfono).
- Catálogo de servicios con precio de autoservicio y de encargo.
- Punto de venta: modalidad, cobro en efectivo o tarjeta (referencia del voucher), ticket y reimpresión.
- Encargos: recepción con fecha promesa, pagos parciales, tablero pendiente / listo / entregado.
- Inventario: entradas, consumo automático por carga, alertas de stock.
- Descuentos autorizados.
- Apertura y corte de caja por turno.
- Máquinas y ciclos con **driver manual y simulador** (el simulador imita a la cajita: confirma o falla).
- Reportes en el dashboard de Unfold.
- Despliegue en una VM con respaldos.

### Fase 2 – Control de máquinas e integraciones
- Broker MQTT, escucha MQTT, `RelayBoardDriver` y programa de la cajita; alta de relés y pulsos de las 6 máquinas; pulso de prueba.
- Medición de consumo en las 6 máquinas (opcional).
- Estado de las máquinas en tiempo real; conciliación ventas ↔ ciclos y alertas de ciclos sin cobro.
- Integración con la API de Mercado Pago Point.
- `LGCloudDriver`, solo si LG da acceso a su API.

### Fase 3 – Crecimiento
- App móvil (Expo) y, si el negocio lo decide, activación por el propio cliente con pago en línea.
- Notificaciones por WhatsApp/SMS ("tu ropa está lista").
- Precios por programa o por tiempo de secado (el modelo ya lo soporta).
- Autorización remota de acciones reservadas y verificación en dos pasos para admins (ver Anexo).
- Permisos temporales y roles personalizados (p. ej. "Encargado de turno").
- Facturación CFDI, multisucursal y programa de lealtad, si se necesitan.

---

## 8. Estructura del repositorio

```
Laundry/
├── backend/
│   ├── config/            # settings (base, dev, prod, UNFOLD), urls, celery.py
│   ├── templates/admin/   # plantillas del dashboard de Unfold
│   ├── core/  clientes/  inventario/  ventas/  maquinas/
│   ├── requirements/      # o pyproject.toml
│   └── Dockerfile
├── frontend/
│   ├── src/ (api/, features/, components/, routes/)
│   └── Dockerfile
├── firmware/              # programa de la cajita (ESPHome YAML o código) y respaldo del de Aitare
├── mosquitto/             # configuración del broker MQTT (usuarios, permisos por tema)
├── docker-compose.yml
├── docker-compose.prod.yml
├── .env.example
└── docs/                  # mvp.md, contacto_lg.md, imágenes, manuales
```

---

## 9. Pendientes

1. **Cajita:** capturas de la configuración de pulsos en ControlEquipos, foto de la conexión de un relé y adaptador USB-serie.
2. **Secadora:** manual de la `CDG27RUCNS`, para confirmar que su entrada de pago y pulsos funcionan igual.
3. **LG:** respuesta a la consulta (`contacto_lg.md`): compatibilidad, registro, API, inicio remoto y costos.
4. **Insumos:** medida exacta de detergente y suavizante por carga (editable; no bloquea).
5. **Impresora POS-8360:** confirmar con una impresión de prueba si acepta ESC/POS, y si se usa cajón de dinero.

---

## Anexo: diseños para fases futuras

### Autorización remota del administrador

Cuando un empleado intenta una acción reservada, el sistema le ofrece **"Solicitar autorización"** y el admin la aprueba desde su celular, desde cualquier lugar:

```mermaid
sequenceDiagram
    autonumber
    actor E as Empleado (caja)
    participant S as Sistema (nube)
    actor A as Admin (celular, desde cualquier lugar)

    E->>S: Entregar encargo A-123 con saldo $80
    S->>S: Crea SolicitudAutorizacion<br/>(pendiente, expira en 15 min)
    S-->>E: "Esperando autorización…"
    S->>A: Notificación push:<br/>"Juan quiere entregar A-123 con saldo $80"

    alt El admin aprueba
        A->>S: Aprobar (+ comentario opcional)
        S->>S: Ejecuta la acción y registra en bitácora<br/>quién la pidió y quién la autorizó
        S-->>E: Aprobada: encargo entregado
    else El admin rechaza
        A->>S: Rechazar (+ comentario)
        S-->>E: Rechazada (con el comentario del admin)
    else Nadie responde en 15 min
        S->>S: Solicitud expirada
        S-->>E: Expirada: puede volver a solicitarla
    end
```

- **Notificación:** Web Push (respaldo: correo; después: WhatsApp) y bandeja de "Solicitudes pendientes" en el panel del admin.
- **Seguridad:** autoriza exactamente lo pedido (acción + objeto + monto); un solo uso; expira en 15 min (configurable); solo un admin aprueba. Conviene implementarla junto con verificación en dos pasos para admins.
- **Acciones solicitables:** entregar encargo con saldo y ajustes de inventario, ampliable a otras.
- **Modelo:** `SolicitudAutorizacion(tipo, solicitante, objeto_tipo, objeto_id, datos JSON, estado [pendiente | aprobada | rechazada | expirada | usada], resuelta_por, comentario, creada_en, expira_en, resuelta_en)`. La acción solo se ejecuta con una solicitud aprobada, vigente, sin usar y con los mismos datos.

---

## Referencias

- Manual de la lavadora `GCWM1069CD7`: `Wahser_GCWM1069CD7_manual.pdf`
- Instalación de Aitare (fotos y programa): `Aitaire/`
- Consulta a LG: `contacto_lg.md`
- LG México – Smart Laundry Lounge: https://www.lg.com/mx/business/lavanderia-comercial/smart-laundry-lounge/
- LG – Commercial Laundry API: https://thinq.developer.lge.com/en/cloud/about/service/commercial-laundry/
- LG Smart Solution API Developer: https://smartsolution.developer.lge.com/en/apiManage/landing
- django-unfold: https://github.com/unfoldadmin/django-unfold
