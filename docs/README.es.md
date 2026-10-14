# Docker qBittorrent — SrPolvoron

Servicio de descargas qBittorrent **independiente y privado** para servidores Debian/Linux mediante Docker Compose. Permite descargar libros, juegos, software, vídeo y otros archivos **sin depender de Jellyfin** y, opcionalmente, integrarse con Radarr/Sonarr de otro proyecto Compose. No exige migración, base de datos, proxy inverso ni apertura pública de la interfaz web.

[Read in English](../README.md)

## Arquitectura y configuración segura por defecto

| Elemento | Predeterminado | Opcional |
| --- | --- | --- |
| Despliegue | Una instancia de qBittorrent gestionada mediante Compose | Conectarla con otros proyectos Compose |
| Interfaz web | `127.0.0.1:8081` del **host**, accesible por SSH | Publicación adicional en la IP WireGuard del host (`--vpn`) |
| BitTorrent | Conexiones salientes a través de la conexión normal del servidor; **sin puerto P2P entrante publicado** | Modificación futura y explícita, no incluida |
| Configuración persistente | `/srv/qbittorrent/config` | `CONFIG_ROOT` configurable |
| Descargas | `/srv/qbittorrent/data` | `DATA_ROOT` configurable |
| DNS de integración multimedia | Sin red compartida | `qbittorrent-standalone:8081` dentro de `media-downloads` |
| Versión | Imagen fijada por digest al instalar | Actualización manual con `./stack lock --refresh` |

Se trata de **una instalación nueva**: no migra ni sustituye el qBittorrent que ya utiliza Jellyfin. El puerto web `8081` evita un posible conflicto con su `8080`. Nunca debes compartir el mismo directorio de configuración entre ambas instancias en funcionamiento. No se modifica ningún otro repositorio.

**Alcance de la VPN:** SSH y WireGuard del host protegen el acceso a la interfaz web, pero **no redirigen el tráfico de los torrents**. Los pares verán la IP pública de salida utilizada por el servidor Docker. Que exista un túnel WireGuard entre tu servidor doméstico y un proxy OVH no convierte automáticamente las descargas en tráfico saliente por una VPN externa.

## Requisitos

- Debian u otro host Linux con Docker (imagen original para `amd64` o `arm64`).
- Docker Engine (recomendado 28+), plugin Docker Compose 2.24+ y Python 3.10+.
- Acceso SSH operativo, preferiblemente con claves; una cuenta con permisos sobre Docker. El acceso al daemon Docker equivale prácticamente a permisos de administrador del host.
- Espacio en disco y acceso de escritura a las rutas elegidas; `sudo` para preparar directorios bajo `/srv`.
- Para `--vpn`, `iproute2`, `wireguard-tools` y una interfaz WireGuard **ya configurada en el host**. Para `--media`, una red bridge Docker externa existente.

No necesita paquetes de Python adicionales. El comando `stack` interpreta valores literales de `.env` sin ejecutar código de shell.

## Inicio rápido — solo SSH, sin otros servicios

```bash
# Dentro de este repositorio
./stack init
id -u
id -g
nano .env                    # Ajusta PUID/PGID y las rutas de almacenamiento
./stack check
sudo ./stack prepare         # Solo crea directorios inexistentes; sin chown sobre datos anteriores
./stack lock                 # Obtiene el digest inmutable de la imagen
./stack config               # Revisa la definición Compose completa
./stack up
./stack status
./stack logs --tail 100     # Primera ejecución: contraseña TEMPORAL del usuario 'admin'
```

`./stack init` no sobrescribe un `.env` existente. `./stack lock` resuelve la imagen estable seleccionada y escribe su digest en `images.lock.env`; no volverá a cambiarlo salvo con `--refresh`. Tanto `.env` como el archivo de bloqueo son específicos de cada instalación, privados y están excluidos de Git.

Desde tu ordenador, con el alias SSH del servidor (sustituye `casa` por el tuyo):

```bash
ssh -N -o ExitOnForwardFailure=yes -L 8081:127.0.0.1:8081 casa
```

Abre **http://127.0.0.1:8081** en tu ordenador. Accede como `admin` con la contraseña temporal indicada en los logs del contenedor. **Cambia inmediatamente el usuario y la contraseña desde Tools → Options → Web UI.** Mientras no establezcas una contraseña permanente, la imagen original generará una nueva al reiniciar. No compartas logs que contengan credenciales.

### Crear las categorías y las rutas de descarga

Después de cambiar la contraseña, ejecuta desde el **servidor Docker**:

```bash
./stack categories              # Solicita la contraseña sin almacenarla
# Si cambiaste también el nombre de usuario:
./stack categories --username myuser
```

El comando utiliza la API web local, configura la ruta por defecto, la ruta de temporales y la gestión automática de torrents, y crea/verifica estas categorías:

| Categoría | Carpeta dentro del contenedor | Uso |
| --- | --- | --- |
| `movies` | `/data/torrents/standalone/movies` | Radarr |
| `tv` | `/data/torrents/standalone/tv` | Sonarr |
| `books` | `/data/torrents/standalone/books` | Manual |
| `games` | `/data/torrents/standalone/games` | Manual |
| `software` | `/data/torrents/standalone/software` | Manual |
| `other` | `/data/torrents/standalone/other` | Predeterminada/manual |
| *incomplete* | `/data/torrents/standalone/incomplete` | Temporales (no es una categoría) |

El script comprueba que las rutas hayan quedado aplicadas y se niega a sobrescribir categorías existentes con rutas distintas. No importa contenido a Jellyfin ni gestiona trackers. Puedes añadir enlaces magnet o archivos `.torrent` en la interfaz web. Para consultar archivos desde otros equipos utiliza tu cuenta SSH/SFTP existente y los permisos adecuados sobre las carpetas. Por ejemplo:

```bash
sftp casa
# Dentro de sftp, escribe: cd /srv/qbittorrent/data/torrents/standalone/books
# Después: ls / get archivo.ext
```

La ruta del host será diferente si personalizaste `DATA_ROOT`. Considera que los archivos comprimidos y ejecutables descargados pueden no ser fiables: inspecciónalos o analízalos antes de abrirlos.

### Descargas anteriores, borrados y compartición

La instalación nueva no inspecciona ni migra descargas de otra instancia. Borrar algo en Seerr, Radarr o Jellyfin **no** lo borra automáticamente de este cliente. Tampoco se eliminan por sí solos los archivos de bibliotecas multimedia. Si lo necesitas, configura las limitaciones de ratio o tiempo de compartición en qBittorrent, respetando las normas de cada tracker. Evita activar borrados automáticos sin considerar los hardlinks de las bibliotecas multimedia.

## Acceso web opcional por WireGuard

El acceso SSH seguirá funcionando. Para publicar adicionalmente el panel **solo en una dirección IPv4 WireGuard asignada al propio servidor Docker**, modifica `.env`:

```dotenv
WG_INTERFACE=wg0
WG_BIND_IP=10.77.0.2
```

La dirección es un ejemplo: utiliza la **IP real del servidor en esa interfaz**, no la IP del portátil ni la IP pública de OVH. Después:

```bash
./stack check --vpn
./stack config --vpn
./stack up --vpn
```

`./stack up --vpn` verifica que esa dirección pertenece a una interfaz WireGuard operativa. Docker publicará el puerto en dicha IP además de `127.0.0.1`; no creará peers, rutas ni reglas de firewall. El equipo de acceso necesita una ruta válida hacia esa IP privada: el túnel casa↔OVH por sí solo no da acceso directo a cualquier cliente externo. Revisa el cortafuegos, porque los puertos publicados por Docker pueden saltarse ciertos filtros de firewall del host. No uses `WG_BIND_IP=0.0.0.0`, no desactives las protecciones CSRF/Host y no publiques el panel con Traefik.

**Persistencia del modo de acceso:** al recrear el servicio, sigue usando `./stack up --vpn` para conservar ese acceso. Si omites `--vpn`, volverá intencionadamente al modo solo SSH. Puedes combinarlo con `--media`.

## Integración opcional con Radarr/Sonarr/Jellyfin

Primero decide dónde se guardarán los datos, **antes de empezar a descargar**. Si Radarr y Sonarr montan `/srv/media` del host como `/data`, la opción más sencilla y compatible con hardlinks es:

```dotenv
DATA_ROOT=/srv/media
```

Mantén `CONFIG_ROOT=/srv/qbittorrent/config` por separado. Los nuevos archivos aparecerán en `/srv/media/torrents/standalone/...`, **sin mezclarse** con los directorios del qBittorrent existente. Radarr y Sonarr los verán como `/data/torrents/standalone/...`, evitando Remote Path Mapping y permitiendo hardlinks cuando origen y destino comparten sistema de archivos. Estar dentro de `/srv/media` no añade automáticamente libros, juegos u otros archivos a Jellyfin: configura sus bibliotecas exclusivamente sobre las rutas multimedia adecuadas en `/data/media`.

Si conservas la ruta independiente por defecto `/srv/qbittorrent/data`, también deberás montarla en Radarr/Sonarr y configurar rutas internas equivalentes o Remote Path Mapping. Los hardlinks solo funcionan en un mismo sistema de archivos. **No cambies `DATA_ROOT` después de descargar sin planificar el traslado de datos y la revisión de rutas.**

Crea la red Docker compartida y activa la integración:

```bash
./stack network-create
./stack up --media
# O bien: ./stack up --media --vpn
```

En el Compose del **otro proyecto**, conecta Radarr y Sonarr a `media-downloads`, conservando todas las redes que ya tengan. Ejemplo de *fragmento* (combínalo con sus servicios originales; no reemplaces todo su Compose):

```yaml
services:
  radarr:
    networks:
      default: {}
      media_downloads: {}
  sonarr:
    networks:
      default: {}
      media_downloads: {}
networks:
  media_downloads:
    external: true
    name: media-downloads
```

`default` es ilustrativo: mantén el nombre real de la red original de tu proyecto Jellyfin. Recrea esos servicios mediante sus **propios** comandos de despliegue. No elimines el qBittorrent anterior salvo que lo decidas de forma independiente más adelante.

Añade un cliente de descarga nuevo en Radarr y Sonarr:

| Campo | Radarr | Sonarr |
| --- | --- | --- |
| Host | `qbittorrent-standalone` | `qbittorrent-standalone` |
| Puerto | `8081` | `8081` |
| SSL | Desactivado (red Docker local) | Desactivado |
| Usuario/contraseña | Credenciales del nuevo qBittorrent | Las mismas |
| Categoría | `movies` | `tv` |
| Ruta de descarga | Visible en `/data` si compartes almacenamiento | Igual |

Este procedimiento **añade** un segundo cliente; las reglas existentes de Radarr/Sonarr seguirán usando el cliente anterior mientras no cambies la selección o prioridad. Pulsa *Test* en ambas aplicaciones y verifica una descarga legal y su importación. Si la validación de cabeceras Host de qBittorrent rechaza el nombre DNS Docker, permite exclusivamente `qbittorrent-standalone` en la lista de dominios admitidos de la interfaz web; no desactives la protección de Host ni CSRF.

> Los contenedores conectados a la misma red Docker pueden comunicarse incluso si el puerto web del host solo escucha en loopback. Mantén credenciales robustas y no conectes contenedores ajenos o no fiables a la red compartida.

## Operación, actualizaciones, copias y recuperación

```bash
./stack check                      # Validación estática; sin Docker
./stack config                     # Inspeccionar la configuración Compose
./stack status
./stack logs --tail 100
./stack down                       # Solo retira contenedores; conserva datos y configuración
./stack up                         # Modo normal, solo SSH
./stack lock --refresh             # Actualizar deliberadamente el digest inmutable
./stack up                         # Recrear con la nueva versión
```

Si utilizas conexiones opcionales, sustituye el último `./stack up` por `./stack up --media`, `./stack up --vpn` o `./stack up --media --vpn`, según corresponda. Un `up` sin opciones retira intencionadamente el acceso adicional y la conexión a la red compartida cuando se recrea el contenedor.

Antes de actualizar, realiza una copia de configuración. El servicio se detiene brevemente para garantizar consistencia:

```bash
sudo mkdir -p /srv/backups/qbittorrent
sudo chown "$(id -u):$(id -g)" /srv/backups/qbittorrent
./stack backup --output "/srv/backups/qbittorrent/settings-$(date +%Y%m%d-%H%M%S).tar.gz"
```

El archivo contiene únicamente **`config/`, `.env`, `images.lock.env`**: no incluye los datos descargados. El script no sobrescribe copias y reinicia el servicio si estaba en marcha. Guarda copias cifradas fuera del host: pueden contener credenciales y sesiones. Haz también copia de `DATA_ROOT` si necesitas recuperar descargas completas o incompletas. Inspecciona el contenido del archivo antes de restaurarlo manualmente, detén el contenedor y conserva propietarios PUID/PGID. Una actualización que modifique appdata podría requerir restaurar la copia anterior para volver atrás; cambiar solamente el digest no revierte esas migraciones.

Si falla el arranque, revisa `./stack logs`, el espacio (`df -h`), `findmnt -T <DATA_ROOT>` si usas otro disco y los propietarios (`stat -c '%u:%g %n' ...`). Los montajes bind impiden crear automáticamente rutas de host inexistentes, pero no detectan la ausencia de un sistema de archivos si queda un directorio local en el mismo punto. `prepare` nunca hace `chown` recursivo. No ejecutes `docker compose down -v` ni borres carpetas de descargas sin querer eliminar esos datos.

### Pruebas

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile stack
./stack check
./stack config                   # Necesita Docker Compose y el lock de imagen
```

Las pruebas locales verifican configuración, digest, protecciones y declaraciones Compose. Antes de utilizarlo en producción también hay que comprobar el pull y arranque reales en Linux, acceso con contraseña temporal, creación de categorías por API, descarga de un torrent legal y, si aplica, conexión por VPN e integración multimedia.

## Política del repositorio

- `README.md` principal en inglés y traducción española completa en `docs/README.es.md`. Mantener ambos sincronizados.
- No subir a Git `.env` reales, digests de despliegue, credenciales, descargas, trackers ni cookies.
- No existen actualizaciones automáticas ni procesos de borrado desatendido.
- La licencia MIT cubre **estos scripts y la configuración del repositorio**, no modifica las licencias propias de qBittorrent ni de LinuxServer.io.
