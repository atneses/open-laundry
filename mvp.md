# MVP Sistema de Gestion y control de lavanderia

## Requerimientos

### Generales
1. Gestionar ventas
2. Registro de clientes, nombre y teléfono como minimo para contactar al cliente. Otra información como dirección, etc como opcional
3. Inventario
4. Activación de lavadoras y secadoras a traves de la web, y mantener registro de usos.

### Modos de cobro

Cobro por carga (lavadora, secadora)

1. Auto servicio
2. Por encargo

Distintos precios para autoservicio y encargo

Capacidad de agregar mas servicios a futuro (ejemplo: lavado de tenis)

Por el momento no se necesita facturacion (CFDI)

### Metodos de pago

1. Efectivo
2. Tarjeta (credito, debito)

### Específicos

#### Conexión con lavadoras LG Conectarse con lavadoras LG conectadas a la red local de la lavandería

Las lavadoras y secadoras LG tiene la capacidad de conectarse y ponerse en marcha via WiFi

**Modelo de equipos**

Lavadora: **GCWM1069CD7** 
![lavadora.png](lavadora.png)

Secadora: **CDG27RUNCNS**
![secadora.png](secadora.png)


### Propuesta de arquitectura
Se planea montar en un servidor en la nube principalmente en AWS pero no cerrado a usar otra nube como GCloud.

Asi mismo se plantea una API para poder tener una version web y una version mobile

**Stack:**
- Backend: Django y Django Restframework
- Front: React
- Base de datos: Postgresql
- Docker