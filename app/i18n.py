"""Lightweight i18n: no new dependency (no Flask-Babel) - just a nested dict of
translations per language, a cookie to remember the person's choice, and a `t(key)`
helper registered as a Jinja global.

Coverage is intentionally incremental: `t()` falls back to the key itself (English)
when a translation is missing, so templates can be migrated one at a time without ever
showing a blank string or crashing on an untranslated page.
"""
from flask import request

SUPPORTED_LANGUAGES = ('en', 'es')
DEFAULT_LANGUAGE = 'en'
LANGUAGE_COOKIE = 'ownfoil_lang'

# {key: {lang: text}}. English is the fallback for any key/language not present here,
# so only Spanish strings that actually differ from the key need an entry - though for
# clarity every translated key lists both.
TRANSLATIONS = {
    'nav.library': {'en': 'Library', 'es': 'Biblioteca'},
    'nav.setup': {'en': 'Setup', 'es': 'Configuración inicial'},
    'nav.admin': {'en': 'Admin', 'es': 'Administración'},
    'nav.login': {'en': 'Login', 'es': 'Iniciar sesión'},
    'nav.logout': {'en': 'Logout', 'es': 'Cerrar sesión'},

    'login.please_login': {'en': 'Please login to your account', 'es': 'Iniciá sesión en tu cuenta'},
    'login.username': {'en': 'Username', 'es': 'Usuario'},
    'login.password': {'en': 'Password', 'es': 'Contraseña'},
    'login.remember_me': {'en': 'Remember me', 'es': 'Recordarme'},
    'login.submit': {'en': 'Login', 'es': 'Iniciar sesión'},

    'settings_nav.settings': {'en': 'Settings', 'es': 'Ajustes'},
    'settings_nav.services': {'en': 'Services', 'es': 'Servicios'},
    'settings_nav.files': {'en': 'Files', 'es': 'Archivos'},
    'settings_nav.tasks': {'en': 'Tasks', 'es': 'Tareas'},
    'settings_nav.stats': {'en': 'Stats', 'es': 'Estadísticas'},

    'language.label': {'en': 'Language', 'es': 'Idioma'},
    'language.en': {'en': 'English', 'es': 'Inglés'},
    'language.es': {'en': 'Spanish', 'es': 'Español'},

    'common.nothing_to_report': {'en': 'Nothing to report.', 'es': 'No hay nada para mostrar.'},
    'common.loading': {'en': 'Loading...', 'es': 'Cargando...'},
    'common.previous': {'en': 'Previous', 'es': 'Anterior'},
    'common.next': {'en': 'Next', 'es': 'Siguiente'},
    'common.files': {'en': 'Files', 'es': 'Archivos'},
    'common.size': {'en': 'Size', 'es': 'Tamaño'},
    'common.title': {'en': 'Title', 'es': 'Título'},
    'common.file': {'en': 'File', 'es': 'Archivo'},
    'common.path': {'en': 'Path', 'es': 'Ruta'},
    'common.type': {'en': 'Type', 'es': 'Tipo'},
    'common.tracked': {'en': 'Tracked', 'es': 'Registrados'},
    'common.owned': {'en': 'Owned', 'es': 'Poseído'},
    'common.status': {'en': 'Status', 'es': 'Estado'},
    'common.extension': {'en': 'Extension', 'es': 'Extensión'},
    'common.library': {'en': 'Library', 'es': 'Biblioteca'},

    'stats.title': {'en': 'Stats', 'es': 'Estadísticas'},
    'stats.subtitle': {'en': 'Library-wide figures, counted at the moment the page loaded.',
                        'es': 'Cifras de toda la biblioteca, calculadas al cargar la página.'},
    'stats.refresh': {'en': 'Refresh', 'es': 'Actualizar'},
    'stats.extensions': {'en': 'Extensions', 'es': 'Extensiones'},
    'stats.libraries': {'en': 'Libraries', 'es': 'Bibliotecas'},
    'stats.verification_status': {'en': 'Verification status', 'es': 'Estado de verificación'},
    'stats.click_row_hint': {'en': 'Click a row to see which titles', 'es': 'Tocá una fila para ver qué títulos son'},
    'stats.verify_now': {'en': 'Verify pending files', 'es': 'Verificar faltantes'},
    'stats.verifying': {'en': 'Verifying...', 'es': 'Verificando...'},
    'stats.verify_queued': {'en': 'Verification queued', 'es': 'Verificación en cola'},
    'stats.verify_failed': {'en': 'Could not start', 'es': 'No se pudo iniciar'},
    'stats.missing_titles': {'en': 'Titles', 'es': 'Títulos'},
    'stats.missing_titles_hint': {
        'en': "These titles have this app type tracked (counted in \"Registered\") "
              "but don't actually own it.",
        'es': 'Estos títulos tienen este tipo de app rastreado (cuenta en '
              '"Registrados") pero no lo poseen en realidad.'},
    'stats.could_not_load_files': {'en': 'Could not load files.', 'es': 'No se pudieron cargar los archivos.'},
    'stats.search_files_placeholder': {'en': 'Search by filename...', 'es': 'Buscar por nombre de archivo...'},
    'stats.clean_record_tooltip': {'en': 'Clean database record only (keeps the file)', 'es': 'Limpiar solo el registro (mantiene el archivo)'},
    'stats.clean_record_base_step1': {
        'en': 'Clean the tracked database record for "{name}" (base game)? This '
              "doesn't delete any file on disk - the file just gets picked up as "
              'brand new on the next scan.',
        'es': 'Limpiar el registro rastreado en la base de datos de "{name}" '
              '(juego base)? Esto no borra ningún archivo del disco — el archivo '
              'se vuelve a detectar como nuevo en el próximo escaneo.'},
    'stats.clean_record_base_step2': {
        'en': 'Also clean every update and DLC tracked for "{name}"? Choose '
              "Cancel to clean only the base game and leave its updates/DLC as they are.",
        'es': '¿Limpiar también todos los updates y DLC rastreados de "{name}"? '
              'Elegí Cancelar para limpiar solo el juego base y dejar sus '
              'updates/DLC como están.'},
    'stats.clean_record_item_confirm': {
        'en': 'Clean the tracked database record for "{name}"? This doesn\'t '
              "delete any file on disk - the file just gets picked up as brand "
              'new on the next scan.',
        'es': 'Limpiar el registro rastreado en la base de datos de "{name}"? '
              'Esto no borra ningún archivo del disco — el archivo se vuelve a '
              'detectar como nuevo en el próximo escaneo.'},
    'stats.clean_record_failed': {'en': 'Could not clean the record.', 'es': 'No se pudo limpiar el registro.'},
    'stats.delete_record_tooltip': {'en': 'Delete the file from disk and its record', 'es': 'Eliminar el archivo del disco y su registro'},
    'stats.delete_record_base_step1': {
        'en': 'DELETE the file for "{name}" (base game) from disk, permanently? '
              "This cannot be undone.",
        'es': 'ELIMINAR el archivo de "{name}" (juego base) del disco, para '
              'siempre? Esto no se puede deshacer.'},
    'stats.delete_record_base_step2': {
        'en': 'Also delete every update and DLC file tracked for "{name}" from '
              'disk? Choose Cancel to delete only the base game and leave its '
              'updates/DLC as they are.',
        'es': '¿Eliminar también del disco todos los archivos de updates y DLC '
              'rastreados de "{name}"? Elegí Cancelar para eliminar solo el '
              'juego base y dejar sus updates/DLC como están.'},
    'stats.delete_record_item_confirm': {
        'en': 'DELETE the file for "{name}" from disk, permanently? This cannot '
              'be undone.',
        'es': 'ELIMINAR el archivo de "{name}" del disco, para siempre? Esto no '
              'se puede deshacer.'},
    'stats.delete_record_failed': {'en': 'Could not delete the file.', 'es': 'No se pudo eliminar el archivo.'},
    'stats.files_page_count': {'en': '{count} file{s} · page {page} of {totalPages}',
                                'es': '{count} archivo{s} · página {page} de {totalPages}'},
    'stats.duplicate_files': {'en': 'Duplicate files', 'es': 'Archivos duplicados'},
    'stats.duplicate_files_hint': {
        'en': 'More than one physical file exists for the same content. Pick which one to keep - the others are deleted, and the one you keep is renamed to drop any "(n)" suffix if that name is free.',
        'es': 'Existe más de un archivo físico para el mismo contenido. Elegí cuál conservar — los demás se eliminan, y el que elijas se renombra para sacarle el sufijo "(n)" si ese nombre queda libre.'},
    'stats.duplicate_keep_this': {'en': 'Keep this one', 'es': 'Conservar este'},
    'stats.duplicate_resolved': {'en': 'Kept, removed the rest.', 'es': 'Conservado, se eliminó el resto.'},
    'stats.duplicate_resolve_failed': {'en': 'Could not resolve this duplicate.', 'es': 'No se pudo resolver este duplicado.'},
    'stats.duplicate_none': {'en': 'No duplicate files right now.', 'es': 'No hay archivos duplicados por ahora.'},
    'stats.duplicate_resolve_by_size': {'en': 'Resolve all by size', 'es': 'Resolver todo por tamaño'},
    'stats.duplicate_keep_largest': {'en': 'Keep the larger one', 'es': 'Conservar el más grande'},
    'stats.duplicate_bulk_resolved': {'en': 'Resolved {n} group(s).', 'es': 'Se resolvieron {n} grupo(s).'},
    'stats.duplicate_bulk_none': {'en': 'Nothing could be resolved automatically - the rest need a manual look.',
                                   'es': 'No se pudo resolver nada automáticamente — el resto necesita revisión manual.'},
    'stats.duplicate_bulk_failed': {'en': 'Could not resolve by size.', 'es': 'No se pudo resolver por tamaño.'},
    'stats.duplicate_bulk_pref_none': {'en': 'No preference (size only)', 'es': 'Sin preferencia (solo tamaño)'},
    'stats.duplicate_bulk_pref_compressed': {'en': 'Prefer compressed (nsz/xcz)', 'es': 'Preferir comprimido (nsz/xcz)'},
    'stats.duplicate_bulk_pref_uncompressed': {'en': 'Prefer uncompressed (nsp/xci)', 'es': 'Preferir sin comprimir (nsp/xci)'},
    'stats.duplicate_bulk_pref_hint': {'en': "If a group mixes a compressed and an uncompressed copy, the dropdown above decides that one first - size alone would always favor the uncompressed copy, since it's bigger.",
                                        'es': 'Si un grupo mezcla una copia comprimida y una sin comprimir, el desplegable de arriba decide ese caso primero — el tamaño solo siempre favorecería a la copia sin comprimir, por pesar más.'},
    'stats.app_types': {'en': 'App types', 'es': 'Tipos de aplicación'},

    'stats.tile.files_note': {'en': '{n} identified', 'es': '{n} identificados'},
    'stats.tile.total_size': {'en': 'Total size', 'es': 'Tamaño total'},
    'stats.tile.total_size_note': {'en': 'across every library', 'es': 'en todas las bibliotecas'},
    'stats.tile.unidentified': {'en': 'Unidentified', 'es': 'Sin identificar'},
    'stats.tile.unidentified_note': {'en': 'files ownfoil could not match', 'es': 'archivos que ownfoil no pudo identificar'},
    'stats.tile.owned_titles': {'en': 'Owned titles', 'es': 'Títulos poseídos'},
    'stats.tile.owned_titles_note': {'en': 'of {n} in the catalogue', 'es': 'de {n} en el catálogo'},
    'stats.tile.complete': {'en': 'Complete', 'es': 'Completos'},
    'stats.tile.complete_note': {'en': 'owned titles with every DLC', 'es': 'títulos poseídos con todo su DLC'},
    'stats.tile.up_to_date': {'en': 'Up to date', 'es': 'Al día'},
    'stats.tile.up_to_date_note': {'en': 'owned titles on the latest update', 'es': 'títulos poseídos en su última versión'},
    'stats.tile.owned_apps': {'en': 'Owned apps', 'es': 'Apps poseídas'},
    'stats.tile.owned_apps_note': {'en': 'of {n} known', 'es': 'de {n} conocidas'},

    'status.valid': {'en': 'Valid', 'es': 'Válido'},
    'status.repack': {'en': 'Repack', 'es': 'Repack'},
    'status.modified': {'en': 'Modified', 'es': 'Modificado'},
    'status.corrupt': {'en': 'Corrupt', 'es': 'Corrupto'},
    'status.signature_ok': {'en': 'Signature ok', 'es': 'Firma ok'},
    'status.signature_failed': {'en': 'Signature failed', 'es': 'Firma inválida'},
    'status.unverified': {'en': 'Unverified', 'es': 'Sin verificar'},

    'tasks.title': {'en': 'Tasks', 'es': 'Tareas'},
    'tasks.subtitle': {'en': 'Live view of the background work queue. Updates stream from the server as tasks progress.',
                        'es': 'Vista en vivo de la cola de trabajo en segundo plano. Se actualiza en tiempo real a medida que avanzan las tareas.'},
    'tasks.queue': {'en': 'Queue', 'es': 'Cola'},
    'tasks.nothing_queued': {'en': 'Nothing queued.', 'es': 'No hay nada en cola.'},
    'tasks.showing_n_oldest': {'en': 'Showing the {n} oldest tasks — more are queued behind them.',
                                'es': 'Mostrando las {n} tareas más antiguas — hay más en cola detrás de ellas.'},
    'tasks.scheduled': {'en': 'Scheduled', 'es': 'Programadas'},
    'tasks.nothing_scheduled': {'en': 'Nothing scheduled.', 'es': 'No hay nada programado.'},
    'tasks.failed': {'en': 'Failed', 'es': 'Fallidas'},
    'tasks.dismiss_all_failed': {'en': 'Dismiss all failed tasks', 'es': 'Descartar todas las tareas fallidas'},
    'tasks.no_failures': {'en': 'No failures.', 'es': 'Sin fallos.'},
    'tasks.workers': {'en': 'Workers', 'es': 'Procesos'},
    'tasks.no_workers_reported': {'en': 'No workers reported.', 'es': 'Ningún proceso reportado.'},
    'tasks.worker_n': {'en': 'Worker {n}', 'es': 'Proceso {n}'},
    'tasks.alive': {'en': 'alive', 'es': 'activo'},
    'tasks.stopped': {'en': 'stopped', 'es': 'detenido'},
    'tasks.idle': {'en': 'Idle', 'es': 'Inactivo'},
    'tasks.cancel': {'en': 'Cancel', 'es': 'Cancelar'},
    'tasks.dismiss': {'en': 'Dismiss', 'es': 'Descartar'},
    'tasks.status_cancelled': {'en': 'cancelled', 'es': 'cancelada'},
    'tasks.status_finished': {'en': 'finished', 'es': 'finalizada'},
    'tasks.status_failed': {'en': 'failed', 'es': 'fallida'},
    'tasks.due_now': {'en': 'due now', 'es': 'ahora'},
    'tasks.in_duration': {'en': 'in {d}', 'es': 'en {d}'},
    'tasks.running_for': {'en': 'running for {d}', 'es': 'corriendo hace {d}'},
    'tasks.left': {'en': '{d} left', 'es': '{d} restante'},
    'tasks.pid': {'en': 'pid {pid}', 'es': 'pid {pid}'},
    'tasks.history': {'en': 'History', 'es': 'Historial'},
    'tasks.no_history': {'en': 'Nothing has finished yet.', 'es': 'Todavía no terminó nada.'},
    'tasks.refresh_history': {'en': 'Refresh history', 'es': 'Actualizar historial'},

    'backup.heading': {'en': 'Backup', 'es': 'Copia de seguridad'},
    'backup.description': {'en': 'Export your current settings to a file, or restore them from a previously exported one.',
                            'es': 'Exportá tu configuración actual a un archivo, o restaurala desde uno exportado antes.'},
    'backup.export': {'en': 'Export settings', 'es': 'Exportar configuración'},
    'backup.import': {'en': 'Import settings', 'es': 'Importar configuración'},
    'backup.import_button': {'en': 'Upload', 'es': 'Subir'},
    'backup.import_success': {'en': 'Settings imported. Reload the page to see them applied.',
                               'es': 'Configuración importada. Recargá la página para verla aplicada.'},
    'backup.import_no_file': {'en': 'Choose a file first.', 'es': 'Elegí un archivo primero.'},
    'backup.import_failed': {'en': 'Could not import: {error}', 'es': 'No se pudo importar: {error}'},

    'danger.heading': {'en': 'Clean Library', 'es': 'Limpiar Biblioteca'},
    'danger.reset_description': {
        'en': "Cleans and resets the library, clearing all tracked file data. "
              "Doesn't delete any files on disk.",
        'es': 'Limpia y restablece la biblioteca, borrando todos los datos de '
              'archivos rastreados. No elimina archivos en el disco.'},
    'danger.reset_bullet_files': {
        'en': "Every tracked file and its verification is erased - can't be undone.",
        'es': 'Se borra cada archivo rastreado y su verificación — no se puede deshacer.'},
    'danger.reset_bullet_kept': {
        'en': 'Titles, apps, settings, and users stay untouched.',
        'es': 'Los títulos, apps, configuración y usuarios quedan intactos.'},
    'danger.reset_bullet_next': {
        'en': "Then just scan again to rediscover everything.",
        'es': 'Después, escaneá de nuevo para redescubrir todo.'},
    'danger.reset_type_to_confirm': {
        'en': 'Type RESET below to confirm.', 'es': 'Escribí RESET abajo para confirmar.'},
    'danger.reset_button': {'en': 'Clean Library', 'es': 'Limpiar Biblioteca'},
    'danger.reset_success': {
        'en': 'Done - {n} file(s) forgotten. Run a scan to rediscover your library.',
        'es': 'Listo — se olvidaron {n} archivo(s). Corré un escaneo para redescubrir tu biblioteca.'},
    'danger.reset_failed': {'en': 'Could not reset.', 'es': 'No se pudo resetear.'},

    'settings.missing_admin_heading': {'en': 'Missing admin account!', 'es': '¡Falta la cuenta de administrador!'},
    'settings.missing_admin_body': {
        'en': 'Ownfoil-Plus requires an admin account to enable authentication. Until an account with admin rights is created, authentication is disabled, anyone can access and change the configuration of your shop!',
        'es': 'Ownfoil-Plus necesita una cuenta de administrador para habilitar la autenticación. Hasta que se cree una cuenta con permisos de administrador, la autenticación está deshabilitada: ¡cualquiera puede acceder y cambiar la configuración de tu tienda!'},
    'settings.missing_admin_link': {'en': 'Add an admin account here under Authentication.',
                                     'es': 'Agregá una cuenta de administrador acá, en Autenticación.'},
    'settings.missing_keys_heading': {'en': 'Missing / invalid console keys file!', 'es': '¡Falta el archivo de claves de consola, o es inválido!'},
    'settings.missing_keys_body': {
        'en': 'Console keys are required to decrypt any Nintendo content, including backups. Ownfoil-Plus uses this to identify files, regardless of the filename.',
        'es': 'Las claves de consola son necesarias para descifrar cualquier contenido de Nintendo, incluidos los backups. Ownfoil-Plus las usa para identificar archivos, sin importar el nombre del archivo.'},
    'settings.missing_keys_warning': {'en': "Titles will be missed or misidentified if you don't fill in your keys!",
                                       'es': 'Si no cargás tus claves, los títulos se van a perder o identificar mal.'},
    'settings.missing_keys_guide_link': {'en': 'See this guide', 'es': 'Mirá esta guía'},
    'settings.missing_keys_guide_suffix': {'en': 'on how to extract the keys from your console, and upload them here in Ownfoil-Plus.',
                                            'es': 'sobre cómo extraer las claves de tu consola, y subilas acá en Ownfoil-Plus.'},
    'settings.missing_keys_fallback': {'en': 'If keys are missing, all files must contain "[TITLEID][vVERSION]", else the file won\'t be recognized.',
                                        'es': 'Si faltan las claves, todos los archivos deben contener "[TITLEID][vVERSION]", si no el archivo no va a ser reconocido.'},
    'settings.missing_host_heading': {'en': 'Missing shop Host!', 'es': '¡Falta el Host de la tienda!'},
    'settings.missing_host_body': {
        'en': 'Host verification from outside the local network is disabled if the shop Host is missing, configure it here in Ownfoil-Plus to prevent someone else stealing from your shop.',
        'es': 'La verificación de Host desde fuera de la red local está deshabilitada si falta el Host de la tienda; configuralo acá en Ownfoil-Plus para evitar que alguien más te robe la tienda.'},

    'auth.heading': {'en': 'Authentication', 'es': 'Autenticación'},
    'auth.user_list_caption': {'en': 'List of users:', 'es': 'Lista de usuarios:'},
    'auth.col_user': {'en': 'User', 'es': 'Usuario'},
    'auth.col_permissions': {'en': 'Permissions', 'es': 'Permisos'},
    'auth.col_actions': {'en': 'Actions', 'es': 'Acciones'},
    'auth.add_new_user': {'en': 'Add new user', 'es': 'Agregar usuario'},
    'auth.add_a_new_user': {'en': 'Add a new user:', 'es': 'Agregar un usuario nuevo:'},
    'auth.username': {'en': 'Username', 'es': 'Usuario'},
    'auth.password': {'en': 'Password', 'es': 'Contraseña'},
    'auth.shop_access': {'en': 'Shop Access', 'es': 'Acceso a la tienda'},
    'auth.backup_access': {'en': 'Backup Access', 'es': 'Acceso a copias de seguridad'},
    'auth.admin_access': {'en': 'Admin Access', 'es': 'Acceso de administrador'},
    'auth.submit': {'en': 'Submit', 'es': 'Guardar'},
    'auth.delete_user': {'en': 'Delete user', 'es': 'Eliminar usuario'},
    'auth.cancel': {'en': 'Cancel', 'es': 'Cancelar'},
    'auth.delete': {'en': 'Delete', 'es': 'Eliminar'},
    'auth.shop': {'en': 'Shop', 'es': 'Tienda'},
    'auth.backup': {'en': 'Backup', 'es': 'Copia de seguridad'},
    'auth.admin': {'en': 'Admin', 'es': 'Administrador'},

    'sections.library': {'en': 'Library', 'es': 'Biblioteca'},
    'sections.compression': {'en': 'File compression', 'es': 'Compresión de archivos'},
    'sections.verification': {'en': 'File verification', 'es': 'Verificación de archivos'},
    'sections.organizer': {'en': 'Organizer', 'es': 'Organizador'},
    'sections.titles': {'en': 'Titles', 'es': 'Títulos'},
    'sections.shop': {'en': 'Shop', 'es': 'Tienda'},
    'sections.clients': {'en': 'Clients', 'es': 'Clientes'},
    'sections.scheduler': {'en': 'Scheduler', 'es': 'Programación'},
    'sections.workers': {'en': 'Workers', 'es': 'Procesos'},
    'sections.discovery': {'en': 'LAN discovery', 'es': 'Descubrimiento en la red local'},
    'sections.media': {'en': 'Local artworks', 'es': 'Artes locales'},

    'media.desc': {'en': "For your shop to be fully self-hosted and not rely on external sources, Ownfoil-Plus can download all artworks locally and serve them to clients. Instead of providing direct eShop links, your Switch will retrieve them from your server and never connect to Nintendo's servers.",
                   'es': 'Para que tu tienda sea completamente autoalojada y no dependa de fuentes externas, Ownfoil-Plus puede descargar todas las artes localmente y servirlas a los clientes. En vez de dar enlaces directos a la eShop, tu Switch las va a obtener de tu servidor y nunca se va a conectar a los servidores de Nintendo.'},
    'media.enabled_label': {'en': 'Download artwork locally', 'es': 'Descargar arte localmente'},
    'media.disk_usage_label': {'en': 'Disk usage', 'es': 'Uso de disco'},
    'media.files_stored': {'en': '{n} file{s} stored', 'es': '{n} archivo{s} almacenado{s}'},
    'media.kind_icon': {'en': 'Icon', 'es': 'Ícono'},
    'media.kind_banner': {'en': 'Banner', 'es': 'Banner'},
    'media.kind_screenshot': {'en': 'Screenshots', 'es': 'Capturas'},
    'media.col_original': {'en': 'Original', 'es': 'Original'},
    'media.col_thumb': {'en': 'Thumb', 'es': 'Miniatura'},
    'media.col_client': {'en': 'Client', 'es': 'Cliente'},
    'media.col_screen': {'en': 'Screen', 'es': 'Pantalla'},
    'media.col_total': {'en': 'Total', 'es': 'Total'},
    'media.col_type': {'en': 'Type', 'es': 'Tipo'},
    'media.submit': {'en': 'Submit', 'es': 'Enviar'},

    'services.title': {'en': 'Services', 'es': 'Servicios'},
    'services.desc': {'en': 'Background services your server offers on the local network.', 'es': 'Servicios en segundo plano que tu servidor ofrece en la red local.'},
    'services.discovery_desc': {'en': "Lets Sphaira and other compatible clients find this shop on the network automatically, with no IP address or port to type in on the console.", 'es': 'Permite que Sphaira y otros clientes compatibles encuentren esta tienda en la red automáticamente, sin tener que tipear una dirección IP ni un puerto en la consola.'},
    'services.discovery_enabled_label': {'en': 'Enable automatic discovery', 'es': 'Habilitar descubrimiento automático'},
    'services.discovery_enabled_help': {'en': 'Answers discovery requests on UDP port {port}.', 'es': 'Responde solicitudes de descubrimiento en el puerto UDP {port}.'},
    'services.discovery_docker_note': {'en': "Running in Docker: discovery only works if the container uses the host's network - <code>--network host</code> with <code>docker run</code>, or <code>network_mode: host</code> in Compose - since it needs a UDP port reachable on the LAN. On Windows, the firewall must also allow this app on private networks.", 'es': 'Si corrés en Docker: el descubrimiento solo funciona si el contenedor usa la red del host - <code>--network host</code> con <code>docker run</code>, o <code>network_mode: host</code> en Compose - ya que necesita un puerto UDP accesible en la red local. En Windows, el firewall también tiene que permitir esta app en redes privadas.'},
    'services.submit': {'en': 'Save', 'es': 'Guardar'},

    'files.title': {'en': 'Files', 'es': 'Archivos'},
    'files.desc': {'en': 'Review and manage every file tracked across your libraries.', 'es': 'Revisá y gestioná todos los archivos rastreados en tus bibliotecas.'},
    'files.tile_all': {'en': 'All files', 'es': 'Todos los archivos'},
    'files.tile_unidentified': {'en': 'Unidentified', 'es': 'No identificados'},
    'files.tile_verification': {'en': 'Verification issues', 'es': 'Problemas de verificación'},
    'files.tile_not_organized': {'en': 'Not organized', 'es': 'No organizados'},
    'files.tile_duplicates': {'en': 'Duplicate groups', 'es': 'Grupos duplicados'},
    'files.search_placeholder': {'en': 'Title, file name or folder', 'es': 'Título, nombre de archivo o carpeta'},
    'files.filter_all': {'en': 'All', 'es': 'Todos'},
    'files.filter_library': {'en': 'Library', 'es': 'Biblioteca'},
    'files.filter_verification': {'en': 'Verification', 'es': 'Verificación'},
    'files.filter_extension': {'en': 'Format', 'es': 'Formato'},
    'files.col_actions': {'en': 'Actions', 'es': 'Acciones'},
    'files.delete_tooltip': {'en': 'Delete this file from disk, permanently', 'es': 'Eliminar este archivo del disco, para siempre'},
    'files.delete_confirm': {'en': 'Delete "{name}" from disk, permanently? This cannot be undone.', 'es': '¿Eliminar "{name}" del disco, para siempre? Esto no se puede deshacer.'},
    'files.delete_failed': {'en': 'Could not delete the file. Check the Tasks log.', 'es': 'No se pudo eliminar el archivo. Revisá el registro de Tareas.'},
    'files.no_results': {'en': 'No files match.', 'es': 'No hay archivos que coincidan.'},
    'files.duplicates_hint': {'en': 'Duplicate files are reviewed and resolved from the Stats page.', 'es': 'Los archivos duplicados se revisan y resuelven desde la página de Estadísticas.'},

    'lib.paths_heading': {'en': 'Paths', 'es': 'Rutas'},
    'lib.paths_desc': {'en': 'Configure directories containing your games.', 'es': 'Configurá los directorios que contienen tus juegos.'},
    'lib.col_path': {'en': 'Path', 'es': 'Ruta'},
    'lib.col_actions': {'en': 'Actions', 'es': 'Acciones'},
    'lib.add_library_path': {'en': 'Add library path', 'es': 'Agregar ruta'},
    'lib.scan_library': {'en': 'Scan library', 'es': 'Escanear biblioteca'},
    'lib.add_a_new_directory': {'en': 'Add a new directory:', 'es': 'Agregar un directorio nuevo:'},
    'lib.path_placeholder': {'en': 'Path', 'es': 'Ruta'},
    'lib.submit': {'en': 'Submit', 'es': 'Guardar'},
    'lib.delete_library_path': {'en': 'Delete library path', 'es': 'Eliminar ruta de biblioteca'},
    'lib.cancel': {'en': 'Cancel', 'es': 'Cancelar'},
    'lib.delete': {'en': 'Delete', 'es': 'Eliminar'},

    'lib.watcher_heading': {'en': 'File watcher', 'es': 'Vigilancia de archivos'},
    'lib.watcher_desc': {'en': 'Monitor library paths for changes. Local paths use native OS events; network filesystems are polled at the interval below.',
                          'es': 'Monitorea las rutas de la biblioteca en busca de cambios. Las rutas locales usan eventos nativos del sistema operativo; los sistemas de archivos de red se consultan en el intervalo de abajo.'},
    'lib.enable_watcher': {'en': 'Enable file watcher', 'es': 'Activar vigilancia de archivos'},
    'lib.polling_interval': {'en': 'Polling interval', 'es': 'Intervalo de consulta'},
    'lib.save': {'en': 'Save', 'es': 'Guardar'},

    'lib.management_heading': {'en': 'Management', 'es': 'Gestión'},
    'lib.management_desc': {'en': 'Configure automated library management.', 'es': 'Configurá la gestión automática de la biblioteca.'},
    'lib.delete_older_updates': {'en': 'Delete older updates', 'es': 'Eliminar updates viejos'},
    'lib.delete_older_updates_help': {'en': 'Deletes older update files when a newer version is available in the library.',
                                       'es': 'Elimina los archivos de update viejos cuando hay una versión más nueva disponible en la biblioteca.'},
    'lib.web_downloads_label': {'en': "Enable downloads from the Library page", 'es': 'Habilitar descargas desde la página de Biblioteca'},
    'lib.web_downloads_help': {'en': "Lets anyone with shop access (admin or not) download a file directly from the browser in the Library page's List view. Off by default - files are served straight from the server's storage, so leave this off unless you actually need it.",
                                'es': 'Permite que cualquier usuario con acceso a la Tienda (sea administrador o no) descargue un archivo directo desde el navegador, en la vista Lista de la Biblioteca. Apagado por defecto — los archivos se sirven directo desde el almacenamiento del servidor, así que dejalo apagado salvo que realmente lo necesites.'},
    'lib.auto_resolve_duplicates_label': {'en': 'Automatically resolve duplicate files',
                                           'es': 'Resolver duplicados automáticamente'},
    'lib.auto_resolve_duplicates_help': {'en': 'When the same content ends up as two or more physical files (e.g. re-downloading something already owned) and every copy has already been fully verified, keep only the healthiest one - Valid beats Repack beats Corrupt - and delete the rest, renaming the survivor to drop any "(n)" suffix. Off by default. Only ever acts when every copy has a complete verdict and there is a single clear best one; a still-unverified file, or a tie between equally-ranked copies, is always left for you to resolve yourself in Settings > Duplicate files.',
                                          'es': 'Cuando el mismo contenido termina en dos o más archivos físicos (por ejemplo, al volver a descargar algo que ya tenías) y cada copia ya fue verificada por completo, conserva solo la más sana — Válido supera a Repack, que supera a Corrupto — y borra el resto, renombrando al que queda para sacarle el sufijo "(n)". Apagado por defecto. Solo actúa cuando todas las copias tienen un veredicto completo y hay una única mejor opción clara; un archivo todavía sin verificar, o un empate entre copias del mismo nivel, siempre queda para que lo resuelvas vos en Settings > Archivos duplicados.'},
    'lib.prefer_multicontent_label': {'en': 'On a tie, prefer multi-content files',
                                       'es': 'En caso de empate, preferir archivos multi-contenido'},
    'lib.prefer_multicontent_help': {'en': 'Only takes effect together with the setting above, and only among copies already tied at the same best verification rank (e.g. both Valid) - it is checked before the compression and size preferences below, but it can never make a worse-verified bundle win over a validly-verified individual file, since the tie-break only starts once every copy already has the same verdict. If the tied copies aren\'t a mix of multi-content and individual files, this settles nothing and the next preference decides instead. Off by default.',
                                      'es': 'Solo tiene efecto junto con la opción de arriba, y únicamente entre copias que ya empataron en el mismo mejor nivel de verificación (por ejemplo, ambas Válidas) — se evalúa antes que las preferencias de compresión y tamaño de abajo, pero nunca puede hacer ganar a un paquete multi-contenido peor verificado por sobre un archivo individual válido, ya que el desempate solo arranca una vez que todas las copias ya tienen el mismo veredicto. Si las copias empatadas no son una mezcla de multi-contenido e individuales, esto no decide nada y pasa a la siguiente preferencia. Apagado por defecto.'},
    'lib.prefer_larger_on_tie_label': {'en': 'On a tie, prefer the larger file',
                                        'es': 'En caso de empate, preferir el archivo más grande'},
    'lib.prefer_larger_on_tie_help': {'en': 'Only takes effect together with the setting above. When two or more copies are tied at the same best rank (e.g. both Valid), keep the larger one instead of leaving the tie for you to resolve manually - by that point every tied copy has already independently passed the same verification, so this only chooses between equally-legitimate files, never a still-unverified one. Off by default.',
                                       'es': 'Solo tiene efecto junto con la opción de arriba. Cuando dos o más copias empatan en el mismo nivel (por ejemplo, ambas Válidas), conserva la más grande en vez de dejarte el empate para resolver a mano — a esa altura cada copia empatada ya pasó la misma verificación por su cuenta, así que esto solo elige entre archivos igualmente legítimos, nunca uno todavía sin verificar. Apagado por defecto.'},
    'lib.compression_preference_label': {'en': 'On a tie between a compressed and an uncompressed copy',
                                          'es': 'En caso de empate entre una copia comprimida y una sin comprimir'},
    'lib.compression_preference_none': {'en': 'No preference (falls back to the size setting above)',
                                         'es': 'Sin preferencia (usa la opción de tamaño de arriba)'},
    'lib.compression_preference_compressed': {'en': 'Prefer the compressed one (nsz/xcz)',
                                               'es': 'Preferir la comprimida (nsz/xcz)'},
    'lib.compression_preference_uncompressed': {'en': 'Prefer the uncompressed one (nsp/xci)',
                                                 'es': 'Preferir la sin comprimir (nsp/xci)'},
    'lib.compression_preference_help': {'en': 'Only takes effect together with "Automatically resolve duplicate files" above. A compressed file is inherently smaller than the same content uncompressed, so relying on size alone would always penalize compression even when you have deliberately turned it on. This is checked first, before the size preference - if the tied copies aren\'t all the same compression status, this decides; the size setting only kicks in if it doesn\'t (e.g. two compressed copies of different sizes). Independent from "On a tie, prefer the larger file" - turning one on does not turn on the other.',
                                        'es': 'Solo tiene efecto junto con "Resolver duplicados automáticamente" de arriba. Un archivo comprimido pesa menos que el mismo contenido sin comprimir, así que basarse solo en el tamaño siempre penalizaría la compresión aunque la hayas activado a propósito. Esto se evalúa primero, antes que la preferencia de tamaño — si las copias empatadas no tienen todas el mismo estado de compresión, esto decide; la opción de tamaño solo entra en juego si no alcanza para decidir (por ejemplo, dos copias comprimidas de distinto tamaño). Es independiente de "En caso de empate, preferir el archivo más grande" — activar una no activa la otra.'},

    'compression.desc': {'en': 'Compress files to save disk space after they are added and organized.',
                          'es': 'Comprime los archivos para ahorrar espacio en disco después de agregarlos y organizarlos.'},
    'compression.enable': {'en': 'Compress files', 'es': 'Comprimir archivos'},
    'compression.enable_help': {'en': 'Compress files to <code>NSZ</code>/<code>XCZ</code> (<code>NSP</code>→<code>NSZ</code>, <code>XCI</code>→<code>XCZ</code>) after they are added and organized. Every compressed file is verified before the original is removed.',
                                 'es': 'Comprime los archivos a <code>NSZ</code>/<code>XCZ</code> (<code>NSP</code>→<code>NSZ</code>, <code>XCI</code>→<code>XCZ</code>) después de agregarlos y organizarlos. Cada archivo comprimido se verifica antes de eliminar el original.'},
    'compression.level_label': {'en': 'Compression level', 'es': 'Nivel de compresión'},
    'compression.level_help': {'en': 'zstandard level (<code>1</code>–<code>22</code>). Higher = smaller files but slower. Default: <code>18</code>.',
                                'es': 'Nivel de zstandard (<code>1</code>–<code>22</code>). Más alto = archivos más chicos pero más lento. Por defecto: <code>18</code>.'},
    'compression.advanced_toggle': {'en': 'Advanced compression options', 'es': 'Opciones avanzadas de compresión'},
    'compression.long_distance': {'en': 'Long-distance mode', 'es': 'Modo de larga distancia'},
    'compression.long_distance_help': {'en': 'Enables zstandard long-distance matching for a better ratio on large files, at higher memory use.',
                                        'es': 'Activa la coincidencia de larga distancia de zstandard para una mejor relación de compresión en archivos grandes, a costa de más uso de memoria.'},
    'compression.mode_label': {'en': 'Compression mode:', 'es': 'Modo de compresión:'},
    'compression.mode_auto': {'en': 'Auto (solid for NSP, block for XCI)', 'es': 'Automático (sólido para NSP, por bloques para XCI)'},
    'compression.mode_solid': {'en': 'Solid (best ratio, not randomly readable)', 'es': 'Sólido (mejor compresión, sin lectura aleatoria)'},
    'compression.mode_block': {'en': 'Block (random read access, slightly larger)', 'es': 'Por bloques (lectura aleatoria, algo más grande)'},
    'compression.mode_help': {'en': 'Block compression allows streaming/mounting without full decompression.',
                               'es': 'La compresión por bloques permite streaming/montaje sin descomprimir todo el archivo.'},
    'compression.block_size_label': {'en': 'Block size exponent:', 'es': 'Exponente del tamaño de bloque:'},
    'compression.block_size_help': {'en': 'Block size is <code>2^x</code> (<code>14</code>–<code>32</code>). Default: <code>20</code> (<code>1 MB</code>). Only used in block mode.',
                                     'es': 'El tamaño de bloque es <code>2^x</code> (<code>14</code>–<code>32</code>). Por defecto: <code>20</code> (<code>1 MB</code>). Solo se usa en modo por bloques.'},
    'compression.threads_label': {'en': 'Threads per file:', 'es': 'Hilos por archivo:'},
    'compression.threads_help': {'en': 'Threads each compression task uses (<code>0</code> = automatic). Note: this multiplies with the number of workers — high values across many workers can oversubscribe the CPU.',
                                  'es': 'Hilos que usa cada tarea de compresión (<code>0</code> = automático). Ojo: esto se multiplica por la cantidad de procesos — valores altos con muchos procesos pueden sobrecargar la CPU.'},

    'verification.desc': {'en': 'Check that files are original and intact. Requires valid console keys.',
                           'es': 'Verifica que los archivos sean originales e íntegros. Requiere claves de consola válidas.'},
    'verification.enable': {'en': 'Verify files', 'es': 'Verificar archivos'},
    'verification.enable_help': {'en': 'Enable file verification: use <code>signature</code> verification to check origin, and <code>hash</code> verification to check integrity.',
                                  'es': 'Activa la verificación de archivos: usa verificación de <code>firma</code> para chequear el origen, y verificación de <code>hash</code> para chequear la integridad.'},
    'verification.signature_only': {'en': 'Signature only', 'es': 'Solo firma'},
    'verification.signature_only_help': {'en': "Checks that the container decrypts and that every <code>NCA</code> header signature is Nintendo's.",
                                          'es': 'Comprueba que el contenedor se descifre y que cada firma de header <code>NCA</code> sea de Nintendo.'},
    'verification.full_hash': {'en': 'Full hash', 'es': 'Hash completo'},
    'verification.full_hash_help': {'en': 'Also hashes every byte of every <code>NCA</code> and compares it against what the file claims, to ensure integrity.',
                                     'es': 'Además calcula el hash de cada byte de cada <code>NCA</code> y lo compara contra lo que el archivo declara, para asegurar la integridad.'},
    'verification.keys_alert': {'en': 'Verification is disabled: no valid console keys are loaded.',
                                 'es': 'La verificación está desactivada: no hay claves de consola válidas cargadas.'},

    'organizer.desc': {'en': 'Keep your library organized.', 'es': 'Mantené tu biblioteca organizada.'},
    'organizer.enable': {'en': 'Enable organizer', 'es': 'Activar organizador'},
    'organizer.enable_help': {'en': 'Enables automatic organization of identified files in the library, according to the templates below.',
                               'es': 'Activa la organización automática de los archivos identificados en la biblioteca, según las plantillas de abajo.'},
    'organizer.remove_empty': {'en': 'Remove empty folders', 'es': 'Eliminar carpetas vacías'},
    'organizer.remove_empty_help': {'en': 'Removes empty folders after organizing files.', 'es': 'Elimina las carpetas vacías después de organizar los archivos.'},
    'organizer.windows_compat': {'en': 'Windows compatible filenames', 'es': 'Nombres de archivo compatibles con Windows'},
    'organizer.windows_compat_help': {'en': 'Ownfoil-Plus enforces filename sanitization depending on the OS running it. Enabling this will sanitize filenames with Windows compatible characters and keep paths within the Windows length limit, this is needed when acessing libraries from Windows systems (e.g. SMB/NFS mount).',
                                       'es': 'Ownfoil-Plus sanea los nombres de archivo según el sistema operativo en el que corre. Activar esto sanea los nombres con caracteres compatibles con Windows y mantiene las rutas dentro del límite de longitud de Windows — necesario si accedés a la biblioteca desde sistemas Windows (ej: montaje SMB/NFS).'},
    'organizer.clean_names_label': {'en': 'Clean names (remove ™, ®, ©, +, :, ／)', 'es': 'Limpiar nombres (quitar ™, ®, ©, +, :, ／)'},
    'organizer.clean_names_help': {'en': 'Strips trademark, registered and copyright symbols, plus "+" and colons/slashes (in either their normal or fullwidth form), from game names when organizing files, similar to Switch Library Manager\'s clean name option.',
                                    'es': 'Quita los símbolos de marca registrada y copyright, además de "+" y dos puntos/barras (en su forma normal o de ancho completo), de los nombres de los juegos al organizar archivos, similar a la opción de limpieza de nombres de Switch Library Manager.'},
    'organizer.show_background_image_label': {'en': 'Show game background image in Library list view',
                                               'es': 'Mostrar imagen de fondo del juego en la vista de lista de la Biblioteca'},
    'organizer.show_background_image_help': {
        'en': "Turns off each game's background artwork behind its row in the Library page's "
              "list view - the cover icon on the left still shows. Only affects that one view, "
              "not the card grid or a game's own detail popup.",
        'es': 'Desactiva la imagen de fondo de cada juego detrás de su fila en la vista de lista de '
              'la página Biblioteca — el icono de portada a la izquierda sigue mostrándose. Solo '
              'afecta esa vista, no la cuadrícula de tarjetas ni el detalle de cada juego.'},
    'organizer.naming_language': {'en': 'Naming language', 'es': 'Idioma de organización'},
    'organizer.naming_language_help': {'en': "Names folders and files using a different region/language than the Titles settings above, independent of what the web UI displays - handy for organizing in English to avoid accents and other symbols a language like Spanish or French brings along.",
                                        'es': 'Nombra carpetas y archivos usando una región/idioma distinto al de la configuración de Títulos de arriba, independiente de lo que muestra la web — útil para organizar en inglés y evitar tildes y otros símbolos que traen idiomas como el español o el francés.'},
    'organizer.same_as_library': {'en': 'Same as library language', 'es': 'Igual que el idioma de la biblioteca'},

    'templates.heading': {'en': 'Templates', 'es': 'Plantillas'},
    'templates.desc': {'en': 'The final computed paths will be relative to the root path of the library, the file extension is added automatically.',
                        'es': 'Las rutas finales calculadas van a ser relativas a la ruta raíz de la biblioteca; la extensión de archivo se agrega automáticamente.'},
    'templates.base': {'en': 'Base template:', 'es': 'Plantilla de juego base:'},
    'templates.update': {'en': 'Update template:', 'es': 'Plantilla de update:'},
    'templates.dlc': {'en': 'DLC template:', 'es': 'Plantilla de DLC:'},
    'templates.multi': {'en': 'Multi-content template:', 'es': 'Plantilla multi-contenido:'},
    'templates.tinfoil_note': {'en': 'Make sure the templates contain <code>[{appId}][v{appVersion}]</code> for Tinfoil to recognize the apps.',
                                'es': 'Asegurate de que las plantillas contengan <code>[{appId}][v{appVersion}]</code> para que Tinfoil reconozca las apps.'},
    'templates.attrs_all': {'en': 'Available attributes for all templates:', 'es': 'Atributos disponibles para todas las plantillas:'},
    'templates.attrs_base_update_dlc': {'en': 'Available attributes for Base, Update, and DLC templates:',
                                         'es': 'Atributos disponibles para las plantillas de Base, Update y DLC:'},
    'templates.attr_extension': {'en': 'File extension (e.g., <code>nsp</code>, <code>nsz</code>)', 'es': 'Extensión de archivo (ej: <code>nsp</code>, <code>nsz</code>)'},
    'templates.attr_title_id': {'en': 'Title ID of the game', 'es': 'Title ID del juego'},
    'templates.attr_title_name': {'en': 'Name of the game title', 'es': 'Nombre del juego'},
    'templates.attr_app_id': {'en': 'Application ID', 'es': 'Application ID'},
    'templates.attr_app_version': {'en': 'Application version', 'es': 'Versión de la aplicación'},
    'templates.attr_patch_level': {'en': 'Patch level', 'es': 'Nivel de parche'},
    'templates.attr_app_name': {'en': 'Name of the application (title or DLC name)', 'es': 'Nombre de la aplicación (nombre del juego o del DLC)'},

    'titles.desc': {'en': 'Titles identification configuration.', 'es': 'Configuración de identificación de títulos.'},
    'titles.region_label': {'en': 'Library Region:', 'es': 'Región de la biblioteca:'},
    'titles.language_label': {'en': 'Library Language:', 'es': 'Idioma de la biblioteca:'},
    'titles.region_language_help': {'en': 'Region and Language used to get games informations.',
                                     'es': 'Región e idioma usados para obtener información de los juegos.'},
    'titles.console_keys_label': {'en': 'Console Keys file:', 'es': 'Archivo de claves de consola:'},
    'titles.console_keys_help': {'en': 'Console keys are required to decrypt any Nintendo content, including backups. Ownfoil-Plus uses this to identify files, regardless of the filename.',
                                  'es': 'Las claves de consola son necesarias para descifrar cualquier contenido de Nintendo, incluidos los backups. Ownfoil-Plus las usa para identificar archivos, sin importar el nombre del archivo.'},
    'titles.master_key_revisions': {'en': 'Master key revisions:', 'es': 'Revisiones de master key:'},

    'shop.desc': {'en': 'Shop configuration and customization.', 'es': 'Configuración y personalización de la tienda.'},
    'shop.name_label': {'en': 'Shop name:', 'es': 'Nombre de la tienda:'},
    'shop.name_help': {'en': "Replaces \"Ownfoil-Plus\" in the navigation bar, browser tab, and app name when added to a home screen, and is given to clients. Leave empty to keep the default.", 'es': 'Reemplaza "Ownfoil-Plus" en la barra de navegación, la pestaña del navegador y el nombre de la app cuando se agrega a la pantalla de inicio, y se le informa a los clientes. Dejalo vacío para mantener el valor por defecto.'},
    'shop.url_label': {'en': 'Shop URL:', 'es': 'URL de la tienda:'},
    'shop.url_help': {'en': 'Configure your shop URL to enable host verification. Host verification from client requests will be enforced if the shop is accessed securely (with <code>https</code>), make sure your reverse proxy does NOT allow insecure connections (or upgrades them to use SSL) and correctly sets the <code>X-Forwarded-Proto</code> header.',
                       'es': 'Configurá la URL de tu tienda para habilitar la verificación de host. La verificación de host se va a exigir si la tienda se accede de forma segura (con <code>https</code>); asegurate de que tu reverse proxy NO permita conexiones inseguras (o las actualice a SSL) y configure correctamente el header <code>X-Forwarded-Proto</code>.'},
    'shop.public': {'en': 'Public shop', 'es': 'Tienda pública'},
    'shop.public_help': {'en': 'If enabled, Shop access from clients does not require authentication.',
                          'es': 'Si está activado, el acceso a la tienda desde clientes no requiere autenticación.'},
    'shop.motd_label': {'en': 'Message of the day:', 'es': 'Mensaje del día:'},
    'shop.motd_help': {'en': 'Message presented in clients after successfully loading your shop.',
                        'es': 'Mensaje que se muestra en los clientes después de cargar tu tienda con éxito.'},

    'clients.tinfoil': {'en': 'Tinfoil', 'es': 'Tinfoil'},
    'clients.sphaira': {'en': 'Sphaira', 'es': 'Sphaira'},
    'clients.cyberfoil': {'en': 'CyberFoil', 'es': 'CyberFoil'},
    'clients.enabled': {'en': 'Enabled', 'es': 'Activado'},
    'clients.tinfoil_enabled_help': {'en': 'Enable or disable Tinfoil client access to the shop.',
                                      'es': 'Activa o desactiva el acceso de clientes Tinfoil a la tienda.'},
    'clients.encrypt_shop': {'en': 'Encrypt shop', 'es': 'Cifrar tienda'},
    'clients.encrypt_shop_help': {'en': 'Serve encrypted and compressed shop, so that only Tinfoil clients can access the content. Strongly suggested to enable it for security.',
                                   'es': 'Sirve la tienda cifrada y comprimida, para que solo los clientes Tinfoil puedan acceder al contenido. Muy recomendado activarlo por seguridad.'},
    'clients.sphaira_enabled_help': {'en': 'Enable or disable Sphaira client access to the shop.',
                                      'es': 'Activa o desactiva el acceso de clientes Sphaira a la tienda.'},
    'clients.cyberfoil_enabled_help': {'en': 'Enable or disable CyberFoil client access to the shop.',
                                        'es': 'Activa o desactiva el acceso de clientes CyberFoil a la tienda.'},

    'scheduler.desc': {'en': 'Configure the periodic jobs. Interval format is <code>number + unit</code> (e.g., <code>2h</code>, <code>30m</code>, <code>1d</code>), with units: <code>s</code> (seconds), <code>m</code> (minutes), <code>h</code> (hours), <code>d</code> (days). Set to <code>0</code> to disable.',
                        'es': 'Configurá las tareas periódicas. El formato de intervalo es <code>número + unidad</code> (ej: <code>2h</code>, <code>30m</code>, <code>1d</code>), con unidades: <code>s</code> (segundos), <code>m</code> (minutos), <code>h</code> (horas), <code>d</code> (días). Poné <code>0</code> para desactivar.'},
    'scheduler.titledb_interval_label': {'en': 'TitleDB update interval:', 'es': 'Intervalo de actualización de TitleDB:'},
    'scheduler.titledb_interval_help': {'en': 'How often to automatically refresh TitleDB and re-process the library.',
                                         'es': 'Cada cuánto actualizar automáticamente TitleDB y reprocesar la biblioteca.'},

    'workers.desc': {'en': 'Configure the number of task worker processes. More workers allow parallel processing of tasks (e.g., scanning, identifying files).',
                      'es': 'Configurá la cantidad de procesos trabajadores de tareas. Más procesos permiten procesar tareas en paralelo (ej: escanear, identificar archivos).'},
    'workers.count_label': {'en': 'Worker count:', 'es': 'Cantidad de procesos:'},
    'workers.count_help': {'en': 'Number of worker processes.', 'es': 'Cantidad de procesos trabajadores.'},
    'workers.io_limit_label': {'en': 'Max concurrent I/O tasks:', 'es': 'Máximo de tareas de E/S concurrentes:'},
    'workers.io_limit_intro': {'en': 'How many disk-heavy tasks (compression, decompression) run at once, independent of worker count. Compressing several multi-GB files in parallel from one disk makes the heads seek back and forth and can collapse throughput, so more is not always faster. Pick based on where your library lives:',
                                'es': 'Cuántas tareas pesadas de disco (compresión, descompresión) corren a la vez, independiente de la cantidad de procesos. Comprimir varios archivos de varios GB en paralelo desde un mismo disco hace que las cabezas salten de un lado a otro y puede desplomar el rendimiento, así que más no siempre es más rápido. Elegí según dónde vive tu biblioteca:'},
    'workers.io_limit_hdd': {'en': 'Network share or a single hard drive (HDD): 1 — avoids seek thrashing; the safe default.',
                              'es': 'Recurso de red o un solo disco rígido (HDD): 1 — evita el salto excesivo de cabezas; la opción segura por defecto.'},
    'workers.io_limit_ssd': {'en': 'SATA SSD: 2–3 — no seek penalty, so limited by CPU.',
                              'es': 'SSD SATA: 2–3 — sin penalización de búsqueda, así que el límite es la CPU.'},
    'workers.io_limit_nvme': {'en': 'NVMe with spare CPU cores: raise toward your core count — each compression uses ~3–4 threads, so the CPU, not the disk, is the ceiling.',
                               'es': 'NVMe con núcleos de CPU libres: subilo hacia tu cantidad de núcleos — cada compresión usa ~3–4 hilos, así que el límite es la CPU, no el disco.'},
    'workers.net_limit_label': {'en': 'Max concurrent network tasks:', 'es': 'Máximo de tareas de red concurrentes:'},
    'workers.net_limit_help': {'en': 'How many artwork downloads run at once, independent of worker count.',
                                'es': 'Cuántas descargas de arte corren a la vez, independiente de la cantidad de procesos.'},

    'library.filter_all': {'en': 'All', 'es': 'Todos'},
    'library.filter_base': {'en': 'Base', 'es': 'Base'},
    'library.filter_dlc': {'en': 'DLC', 'es': 'DLC'},
    'library.filter_owned': {'en': 'Owned', 'es': 'Poseído'},
    'library.filter_missing': {'en': 'Missing', 'es': 'Faltante'},
    'library.filter_up_to_date': {'en': 'Up to date', 'es': 'Al día'},
    'library.filter_missing_update': {'en': 'Missing Update', 'es': 'Falta update'},
    'library.filter_complete': {'en': 'Complete', 'es': 'Completo'},
    'library.filter_missing_dlc': {'en': 'Missing DLC', 'es': 'Falta DLC'},
    'library.filter_health_complete': {'en': 'Complete', 'es': 'Completos'},
    'library.filter_health_incomplete': {'en': 'Incomplete', 'es': 'Incompletos'},
    'library.filter_health_corrupt': {'en': 'Corrupt', 'es': 'Corruptos'},
    'library.filter_health_repack': {'en': 'Repack', 'es': 'Repack'},
    'library.search_placeholder': {'en': 'Search titles...', 'es': 'Buscar títulos...'},
    'library.items_per_page': {'en': 'Items per page', 'es': 'Elementos por página'},
    'library.custom_placeholder': {'en': 'Custom', 'es': 'Personalizado'},
    'library.apply': {'en': 'Apply', 'es': 'Aplicar'},
    'library.details': {'en': 'Details', 'es': 'Detalles'},
    'library.unrecognized': {'en': 'Unrecognized', 'es': 'No reconocido'},
    'library.not_found_in_titledb': {'en': 'not found in titledb', 'es': 'no encontrado en titledb'},
    'library.stat_titles': {'en': 'titles', 'es': 'títulos'},
    'library.stat_complete': {'en': 'complete', 'es': 'completos'},
    'library.stat_up_to_date': {'en': 'up to date', 'es': 'al día'},
    'library.stat_files': {'en': 'files', 'es': 'archivos'},
    'library.version_v0': {'en': 'Version v0', 'es': 'Versión v0'},
    'library.updates_tooltip': {'en': '{name} Updates', 'es': 'Updates de {name}'},
    'library.previous': {'en': 'Previous', 'es': 'Anterior'},
    'library.next': {'en': 'Next', 'es': 'Siguiente'},
    'library.owned': {'en': 'Owned', 'es': 'Poseído'},
    'library.missing': {'en': 'Missing', 'es': 'Faltante'},
    'library.base_game': {'en': 'Base Game', 'es': 'Juego base'},
    'library.updates_section': {'en': 'Updates', 'es': 'Updates'},
    'library.dlc_section': {'en': 'DLC', 'es': 'DLC'},
    'library.older_versions_one': {'en': '{n} older version', 'es': '{n} versión anterior'},
    'library.older_versions_many': {'en': '{n} older versions', 'es': '{n} versiones anteriores'},
    'library.latest_version': {'en': 'Latest Version:', 'es': 'Última versión:'},
    'library.developer': {'en': 'Developer', 'es': 'Desarrollador'},
    'library.publisher': {'en': 'Publisher', 'es': 'Editor'},
    'library.release_date': {'en': 'Release date', 'es': 'Fecha de lanzamiento'},
    'library.number_of_players': {'en': 'Players', 'es': 'Jugadores'},
    'library.genre': {'en': 'Genre', 'es': 'Género'},
    'library.rating': {'en': 'Rating', 'es': 'Clasificación'},
    'library.file_size': {'en': 'File size', 'es': 'Tamaño'},
    'library.languages': {'en': 'Languages', 'es': 'Idiomas'},
    'library.title_id_label': {'en': 'Title ID', 'es': 'Title ID'},
    'library.type_label': {'en': 'Type', 'es': 'Tipo'},
    'library.version_label': {'en': 'Version', 'es': 'Versión'},
    'library.no_more_metadata': {'en': 'No further metadata available for this entry.',
                                  'es': 'No hay más metadatos disponibles para esta entrada.'},
    'library.dlc_fallback_name': {'en': 'DLC', 'es': 'DLC'},
    'library.details_tooltip': {'en': 'Details', 'es': 'Detalles'},
    'library.download_tooltip': {'en': 'Download', 'es': 'Descargar'},
    'library.download_aria': {'en': 'Download {name}', 'es': 'Descargar {name}'},
    'library.metadata_edit': {'en': 'Edit metadata', 'es': 'Editar metadatos'},
    'library.metadata_save': {'en': 'Save', 'es': 'Guardar'},
    'library.metadata_cancel': {'en': 'Cancel', 'es': 'Cancelar'},
    'library.metadata_reset': {'en': 'Reset to downloaded data', 'es': 'Restablecer a los datos descargados'},
    'library.metadata_name_label': {'en': 'Name', 'es': 'Nombre'},
    'library.metadata_developer_label': {'en': 'Developer', 'es': 'Desarrollador'},
    'library.metadata_publisher_label': {'en': 'Publisher', 'es': 'Editor'},
    'library.metadata_release_date_label': {'en': 'Release date', 'es': 'Fecha de lanzamiento'},
    'library.metadata_description_label': {'en': 'Description', 'es': 'Descripción'},
    'library.metadata_edit_hint': {'en': 'Leave a field blank to keep the downloaded value for it. These changes are yours - they stay even after the next titledb update.',
                                    'es': 'Dejá un campo vacío para conservar el valor descargado en ese campo. Estos cambios son tuyos — se mantienen aunque se actualice titledb después.'},
    'library.metadata_saved': {'en': 'Saved.', 'es': 'Guardado.'},
    'library.metadata_save_failed': {'en': 'Could not save.', 'es': 'No se pudo guardar.'},
    'library.metadata_reset_done': {'en': 'Reset to the downloaded data.', 'es': 'Restablecido a los datos descargados.'},
    'library.metadata_reset_failed': {'en': 'Could not reset.', 'es': 'No se pudo restablecer.'},

    # --- Files admin page (/admin/files) --------------------------------------------
    # This page is almost entirely built client-side (filters, table rows, the
    # duplicates/outdated comparison tables, the file drawer) rather than through
    # Jinja, so most of these are read into the page's own `I18N` JS object - the
    # same bridge pattern index.html already uses for the Library page's JS - rather
    # than rendered as template text. A handful of parameterized values use a plain
    # `{name}`-style placeholder meant to be filled in client-side with `.replace()`
    # (the count/size/filename aren't known until the browser has the data), matching
    # `library.updates_tooltip`'s own `{name}` convention above - these are NOT passed
    # through `t()`'s `**kwargs`/`str.format`, since that only works for values the
    # server already knows at render time.

    'files.heading': {'en': 'Files', 'es': 'Archivos'},
    'files.refresh_title': {'en': 'Refresh', 'es': 'Actualizar'},
    'files.manage_desc': {'en': 'Manage library files, actions run as <a href="/admin/tasks">tasks</a>.',
                          'es': 'Gestioná los archivos de la biblioteca; las acciones se ejecutan como <a href="/admin/tasks">tareas</a>.'},

    'files.tab_tile_all': {'en': 'All files', 'es': 'Todos los archivos'},
    'files.tab_tile_unidentified': {'en': 'Unidentified', 'es': 'No identificados'},
    'files.tab_tile_verification': {'en': 'Verification issues', 'es': 'Problemas de verificación'},
    'files.tab_tile_duplicates': {'en': 'Duplicates', 'es': 'Duplicados'},
    'files.tile_outdated': {'en': 'Outdated updates', 'es': 'Actualizaciones obsoletas'},
    'files.tile_pending': {'en': 'Pending', 'es': 'Pendientes'},

    'files.desc_all': {'en': 'Every file in all libraries.', 'es': 'Todos los archivos en todas las bibliotecas.'},
    'files.desc_unidentified': {'en': 'Files Ownfoil-Plus could not match to any known content in the metadata database.',
                                'es': 'Archivos que Ownfoil-Plus no pudo asociar a ningún contenido conocido en la base de metadatos.'},
    'files.desc_verification': {'en': 'Files whose signature or content hash check failed, and files not verified yet.',
                                'es': 'Archivos cuya firma o hash de contenido falló la verificación, y archivos todavía sin verificar.'},
    'files.desc_duplicates': {'en': 'For each content with several copies, the copy recommended and why - or pick one of your own. Nothing is deleted until you choose.',
                              'es': 'Para cada contenido con varias copias, la copia recomendada y por qué — o elegí una por tu cuenta. No se elimina nada hasta que decidas.'},
    'files.desc_outdated': {'en': 'Update files older than the newest update owned for the same title. Files in a multi-content bundle are never removed this way.',
                            'es': 'Archivos de actualización más viejos que la última actualización que tenés para el mismo título. Los archivos dentro de un paquete multi-contenido nunca se eliminan de esta forma.'},
    'files.desc_pending': {'en': 'Files with processing still due given the current settings.',
                           'es': 'Archivos con procesamiento todavía pendiente según la configuración actual.'},

    'files.setting_open_title': {'en': 'Open this setting', 'es': 'Abrir esta opción'},
    'files.value_on': {'en': 'On', 'es': 'Activado'},
    'files.value_off': {'en': 'Off', 'es': 'Desactivado'},
    'files.label_console_keys': {'en': 'Console keys', 'es': 'Claves de consola'},
    'files.value_valid': {'en': 'Valid', 'es': 'Válidas'},
    'files.value_missing': {'en': 'Missing', 'es': 'Faltantes'},
    'files.label_verification': {'en': 'Verification', 'es': 'Verificación'},
    'files.value_needs_keys': {'en': 'Needs keys', 'es': 'Necesita claves'},
    'files.value_full_hash': {'en': 'Full hash', 'es': 'Hash completo'},
    'files.value_signature_only': {'en': 'Signature only', 'es': 'Solo firma'},
    'files.label_automatic_resolution': {'en': 'Automatic resolution', 'es': 'Resolución automática'},
    'files.prefer_larger_on_tie_label': {'en': 'Prefer larger on tie', 'es': 'Preferir el más grande en caso de empate'},
    'files.label_automatic_deletion': {'en': 'Automatic deletion', 'es': 'Eliminación automática'},
    'files.label_organizer': {'en': 'Organizer', 'es': 'Organizador'},
    'files.label_compression': {'en': 'Compression', 'es': 'Compresión'},

    'files.tab_search_placeholder': {'en': 'File name', 'es': 'Nombre de archivo'},
    'files.search_aria': {'en': 'Search files', 'es': 'Buscar archivos'},
    'files.filter_button': {'en': 'Filter', 'es': 'Filtro'},
    'files.previous_page_title': {'en': 'Previous page', 'es': 'Página anterior'},
    'files.next_page_title': {'en': 'Next page', 'es': 'Página siguiente'},

    # --- Files admin page: strings read into the page's JS `I18N` object ----------

    'files.yes': {'en': 'Yes', 'es': 'Sí'},
    'files.no': {'en': 'No', 'es': 'No'},

    'files.ago_template': {'en': '{n} {unit} ago', 'es': 'hace {n} {unit}'},
    'files.unit_seconds': {'en': 's', 'es': 's'},
    'files.unit_minutes': {'en': 'min', 'es': 'min'},
    'files.unit_hours': {'en': 'h', 'es': 'h'},
    'files.unit_days': {'en': 'd', 'es': 'd'},
    'files.unit_months': {'en': 'mo', 'es': 'm'},
    'files.unit_years': {'en': 'y', 'es': 'a'},

    'files.status_valid': {'en': 'Valid', 'es': 'Válido'},
    'files.status_repack': {'en': 'Repack', 'es': 'Repack'},
    'files.status_corrupt': {'en': 'Corrupt', 'es': 'Corrupto'},
    'files.status_signature_ok': {'en': 'Signature ok', 'es': 'Firma correcta'},
    'files.status_signature_failed': {'en': 'Signature failed', 'es': 'Firma incorrecta'},
    'files.status_modified': {'en': 'Modified', 'es': 'Modificado'},
    'files.status_unverified': {'en': 'Unverified', 'es': 'Sin verificar'},

    'files.identified_cnmt_tooltip': {'en': 'Identified from its CNMT', 'es': 'Identificado por su CNMT'},
    'files.identified_filename_tooltip': {'en': 'Identified from its file name only',
                                          'es': 'Identificado solo por el nombre de archivo'},
    'files.not_identified_tooltip': {'en': 'Not identified', 'es': 'No identificado'},

    'files.app_type_base': {'en': 'Base', 'es': 'Base'},
    'files.app_type_update': {'en': 'Update', 'es': 'Actualización'},
    'files.app_type_dlc': {'en': 'DLC', 'es': 'DLC'},

    'files.compressed_tooltip': {'en': 'Compressed', 'es': 'Comprimido'},
    'files.not_compressed_tooltip': {'en': 'Not compressed', 'es': 'Sin comprimir'},
    'files.organized_tooltip': {'en': 'Organized', 'es': 'Organizado'},
    'files.not_organized_tooltip': {'en': 'Not organized', 'es': 'No organizado'},
    'files.verification_tooltip_template': {'en': 'Verification: {status}', 'es': 'Verificación: {status}'},

    'files.bundle_label_template': {'en': 'Bundle: {list}', 'es': 'Paquete: {list}'},

    'files.filter_content_label': {'en': 'Content', 'es': 'Contenido'},
    'files.filter_content_bundle': {'en': 'Bundle', 'es': 'Paquete'},
    'files.filter_format_label': {'en': 'Format', 'es': 'Formato'},
    'files.filter_identified_by_label': {'en': 'Identified by', 'es': 'Identificado por'},
    'files.filter_identified_by_cnmt': {'en': 'CNMT', 'es': 'CNMT'},
    'files.filter_identified_by_filename': {'en': 'File name', 'es': 'Nombre de archivo'},
    'files.label_compressed': {'en': 'Compressed', 'es': 'Comprimido'},
    'files.label_organized': {'en': 'Organized', 'es': 'Organizado'},
    'files.label_library': {'en': 'Library', 'es': 'Biblioteca'},

    'files.action_retry_title': {'en': 'Identify again', 'es': 'Identificar de nuevo'},
    'files.action_verify_title': {'en': 'Verify', 'es': 'Verificar'},
    'files.action_compress_title': {'en': 'Compress', 'es': 'Comprimir'},
    'files.action_decompress_title': {'en': 'Decompress', 'es': 'Descomprimir'},
    'files.action_delete_title': {'en': 'Delete file', 'es': 'Eliminar archivo'},
    'files.busy_identifying': {'en': 'Identifying', 'es': 'Identificando'},
    'files.busy_verifying': {'en': 'Verifying', 'es': 'Verificando'},
    'files.busy_compressing': {'en': 'Compressing', 'es': 'Comprimiendo'},
    'files.busy_decompressing': {'en': 'Decompressing', 'es': 'Descomprimiendo'},
    'files.verify_blocked_needs_keys': {'en': 'Verification needs console keys',
                                        'es': 'La verificación necesita claves de consola'},
    'files.actions_menu_title': {'en': 'Actions', 'es': 'Acciones'},
    'files.remove_filter_title': {'en': 'Remove filter', 'es': 'Quitar filtro'},

    'files.reason_verification': {'en': 'Worse verification', 'es': 'Peor verificación'},
    'files.reason_compressed': {'en': 'Not the preferred compression', 'es': 'No es la compresión preferida'},
    'files.reason_size': {'en': 'Smaller copy', 'es': 'Copia más chica'},
    'files.reason_duplicate': {'en': 'Not the recommended copy', 'es': 'No es la copia recomendada'},
    'files.reason_older_version': {'en': 'Older version', 'es': 'Versión anterior'},

    'files.pill_keep': {'en': 'Keep', 'es': 'Conservar'},
    'files.pill_delete': {'en': 'Delete', 'es': 'Eliminar'},
    'files.pill_undecided': {'en': '?', 'es': '?'},
    'files.keep_this_copy_button': {'en': 'Keep this copy', 'es': 'Conservar esta copia'},
    'files.keep_this_copy_confirm_template': {'en': 'Keep {name} and delete every other copy of this content?',
                                              'es': '¿Conservar {name} y eliminar todas las demás copias de este contenido?'},
    'files.copy_delete_button': {'en': 'Delete', 'es': 'Eliminar'},

    'files.toggle_undecided_title': {'en': 'Undecided - pick a copy to keep below',
                                     'es': 'Sin decidir — elegí abajo qué copia conservar'},
    'files.toggle_delete_group_title': {'en': "Delete this group's copies", 'es': 'Eliminar las copias de este grupo'},
    'files.toggle_keep_group_title': {'en': "Keep all this group's copies", 'es': 'Conservar todas las copias de este grupo'},
    'files.free_template': {'en': '{size} to free', 'es': '{size} para liberar'},

    'files.attr_file': {'en': 'File', 'es': 'Archivo'},
    'files.attr_version': {'en': 'Version', 'es': 'Versión'},
    'files.label_added': {'en': 'Added', 'es': 'Agregado'},
    'files.label_size': {'en': 'Size', 'es': 'Tamaño'},

    'files.column_title': {'en': 'Title', 'es': 'Título'},
    'files.column_state': {'en': 'State', 'es': 'Estado'},

    'files.loading': {'en': 'Loading…', 'es': 'Cargando…'},
    'files.empty_no_files': {'en': 'No files.', 'es': 'No hay archivos.'},
    'files.empty_filtered': {'en': 'No file matches these filters.', 'es': 'Ningún archivo coincide con estos filtros.'},
    'files.empty_unidentified': {'en': 'Every file is identified.', 'es': 'Todos los archivos están identificados.'},
    'files.empty_verification': {'en': 'Every file is verified and passed.',
                                 'es': 'Todos los archivos están verificados y aprobados.'},
    'files.empty_duplicates': {'en': 'No duplicates.', 'es': 'No hay duplicados.'},
    'files.empty_outdated': {'en': 'No outdated updates.', 'es': 'No hay actualizaciones obsoletas.'},
    'files.empty_pending': {'en': 'Nothing left to process.', 'es': 'No queda nada por procesar.'},
    'files.pending_stage_identify': {'en': 'Identify', 'es': 'Identificar'},
    'files.pending_stage_organize': {'en': 'Organize', 'es': 'Organizar'},
    'files.pending_stage_verify': {'en': 'Verify', 'es': 'Verificar'},
    'files.pending_stage_compress': {'en': 'Compress', 'es': 'Comprimir'},
    'files.tile_all_verified': {'en': 'All verified', 'es': 'Todo verificado'},
    'files.tile_processing_due': {'en': 'Processing due', 'es': 'Procesamiento pendiente'},
    'files.tile_unknown_content': {'en': 'Unknown content', 'es': 'Contenido desconocido'},
    'files.filter_any': {'en': 'any', 'es': 'cualquiera'},

    'files.no_match': {'en': 'No match', 'es': 'Sin coincidencia'},
    'files.attempts_suffix': {'en': 'attempt(s)', 'es': 'intento(s)'},
    'files.not_verified_yet': {'en': 'Not verified yet', 'es': 'Todavía sin verificar'},
    'files.not_matched_text': {'en': 'Not matched to any content', 'es': 'No coincide con ningún contenido'},

    'files.section_contents': {'en': 'Contents', 'es': 'Contenido'},
    'files.section_file': {'en': 'File', 'es': 'Archivo'},
    'files.label_signature': {'en': 'Signature', 'es': 'Firma'},
    'files.label_content_hash': {'en': 'Content hash', 'es': 'Hash de contenido'},
    'files.not_checked': {'en': 'Not checked', 'es': 'No verificado'},
    'files.verdict_pass': {'en': 'Pass', 'es': 'Aprobado'},
    'files.verdict_fail': {'en': 'Fail', 'es': 'Falló'},
    'files.label_hash_modified': {'en': 'Modified', 'es': 'Modificado'},
    'files.checked_prefix': {'en': 'Checked ', 'es': 'Verificado el '},

    'files.dt_name': {'en': 'Name', 'es': 'Nombre'},
    'files.dt_path': {'en': 'Path', 'es': 'Ruta'},
    'files.dt_format': {'en': 'Format', 'es': 'Formato'},
    'files.dt_identified': {'en': 'Identified', 'es': 'Identificado'},
    'files.dt_modified': {'en': 'Modified', 'es': 'Modificado'},
    'files.dt_downloads': {'en': 'Downloads', 'es': 'Descargas'},
    'files.compressed_suffix': {'en': ', compressed', 'es': ', comprimido'},
    'files.from_cnmt': {'en': 'From CNMT', 'es': 'Desde CNMT'},
    'files.from_filename': {'en': 'From file name', 'es': 'Desde el nombre de archivo'},
    'files.close_title': {'en': 'Close', 'es': 'Cerrar'},

    'files.confirm_delete_file_template': {'en': 'Delete {name} from disk?', 'es': '¿Eliminar {name} del disco?'},
    'files.confirm_bulk_delete_template': {'en': 'Delete {count} file(s) from disk, freeing {size}?',
                                           'es': '¿Eliminar {count} archivo(s) del disco, liberando {size}?'},
    'files.bulk_delete_failed_template': {'en': '{count} file(s) could not be deleted.',
                                          'es': 'No se pudieron eliminar {count} archivo(s).'},
    'files.bulk_delete_button_template': {'en': 'Delete {count} file(s)', 'es': 'Eliminar {count} archivo(s)'},
    'files.bulk_delete_button_empty': {'en': 'Delete', 'es': 'Eliminar'},

    'files.pager_range_template': {'en': '{first}–{last} of {total}', 'es': '{first}–{last} de {total}'},
    'files.pager_pending_template': {'en': '{shown} shown of {total} with processing due',
                                     'es': '{shown} mostrados de {total} con procesamiento pendiente'},
    'files.pager_removal_template': {'en': '{count} file(s) to delete, freeing {size}',
                                     'es': '{count} archivo(s) para eliminar, liberando {size}'},
    'files.task_failed_template': {'en': '{text} failed: {error}', 'es': '{text} falló: {error}'},
    'files.see_tasks_page': {'en': 'see the Tasks page', 'es': 'revisá la página de Tareas'},

    # --- Setup page ---------------------------------------------------------------
    # A handful of these values deliberately carry their own inline <code>/<strong>
    # markup (and are rendered with `| safe` in the template) instead of being split
    # into separate glue-word keys around hardcoded English tags - every one of them
    # is a fixed string this file itself writes, never request/user data, so there is
    # nothing here for `| safe` to make unsafe. Lines with a real per-request value
    # (shop_name, usernames, addresses) stay split so that value is still emitted
    # through plain `{{ }}` and autoescaped normally.
    'setup.title': {'en': 'Setup Guide', 'es': 'Guía de configuración'},

    'setup.sphaira.heading': {'en': 'Sphaira', 'es': 'Sphaira'},
    'setup.sphaira.intro_before_code': {'en': 'has a built-in', 'es': 'tiene un menú'},
    'setup.sphaira.intro_after_code': {
        'en': 'menu that browses your library by game rather than by file: pick a game, the version and the '
              'DLC you want, and it downloads only what it needs, whatever files they are stored in. Downloads '
              'resume after a dropped connection, and all artworks are served by {shop_name} itself so your '
              'Nintendo Switch never connects to Nintendo\'s servers.',
        'es': 'incorporado que explora tu biblioteca por juego en lugar de por archivo: elegís el juego, la '
              'versión y el DLC que querés, y descarga solo lo necesario, sin importar en qué archivos estén '
              'guardados. Las descargas se reanudan si se corta la conexión, y todas las imágenes las sirve '
              '{shop_name}, así que tu Nintendo Switch nunca se conecta a los servidores de Nintendo.'},

    'setup.discovery.heading': {'en': 'Discovery', 'es': 'Descubrimiento'},
    'setup.discovery.enabled_strong': {'en': 'Discovery is enabled', 'es': 'El descubrimiento está habilitado'},
    'setup.discovery.enabled_rest': {
        'en': ': Sphaira will find this server automatically on your local network.',
        'es': ': Sphaira va a encontrar este servidor automáticamente en tu red local.'},
    'setup.discovery.step_connect': {
        'en': 'Connect your Nintendo Switch to the same network as this server',
        'es': 'Conectá tu Nintendo Switch a la misma red que este servidor'},
    'setup.discovery.step_select_pre': {'en': 'Select', 'es': 'Seleccioná'},
    'setup.discovery.step_select_mid': {'en': ', then', 'es': ', y después'},
    'setup.discovery.step_select_post': {'en': 'in the list', 'es': 'en la lista'},
    'setup.discovery.step_login_authed': {
        'en': 'Accept the login prompt, enter {user} and your password and press', 'es': 'Aceptá el aviso de inicio de sesión, ingresá {user} y tu contraseña y presioná'},
    'setup.discovery.step_login_unauthed': {
        'en': 'Accept the login prompt, enter your {shop_name} username and password and press',
        'es': 'Aceptá el aviso de inicio de sesión, ingresá tu usuario y contraseña de {shop_name} y presioná'},
    'setup.discovery.saved_with_local': {'en': 'The server is saved with its local address',
                                         'es': 'El servidor se guarda con su dirección local'},
    'setup.discovery.saved_with_remote': {
        'en': 'and its remote address {remote_host}, so it keeps working away from home',
        'es': 'y su dirección remota {remote_host}, así que sigue funcionando fuera de casa'},
    'setup.discovery.disabled_strong': {'en': 'Discovery is disabled.', 'es': 'El descubrimiento está deshabilitado.'},
    'setup.discovery.disabled_rest_pre': {'en': 'Enable it in', 'es': 'Habilitalo en'},
    'setup.discovery.disabled_rest_post': {
        'en': 'to let Sphaira find this server by itself, instead of typing its address on the console.',
        'es': 'para que Sphaira encuentre este servidor solo, en vez de escribir su dirección en la consola.'},
    'setup.discovery.services_link': {'en': 'Services', 'es': 'Servicios'},

    'setup.manual.heading': {'en': 'Add the server manually', 'es': 'Agregar el servidor manualmente'},
    'setup.manual.open_menu_pre': {'en': 'In', 'es': 'En'},
    'setup.manual.open_menu_mid': {'en': ', open', 'es': ', abrí'},
    'setup.manual.add_server_pre': {'en': 'Open', 'es': 'Abrí'},
    'setup.manual.add_server_post': {'en': 'and enter the following details:', 'es': 'e ingresá los siguientes datos:'},
    'setup.manual.name_label': {'en': 'Name:', 'es': 'Nombre:'},
    'setup.manual.local_address_label': {'en': 'Local address:', 'es': 'Dirección local:'},
    'setup.manual.remote_address_label': {'en': 'Remote address:', 'es': 'Dirección remota:'},
    'setup.manual.user_label': {'en': 'User:', 'es': 'Usuario:'},
    'setup.manual.pass_label': {'en': 'Pass:', 'es': 'Contraseña:'},
    'setup.manual.press_save': {'en': 'Press <strong>Save</strong>.', 'es': 'Presioná <strong>Save</strong>.'},
    'setup.manual.hint': {
        'en': 'If there is a single server configured it is opened automatically, otherwise select the server '
              'to browse your shop.',
        'es': 'Si hay un único servidor configurado se abre automáticamente; si no, elegí el servidor para '
              'explorar tu tienda.'},
    'setup.manual.local_remote_hint': {
        'en': 'Sphaira uses the local address at home and falls back to the remote one elsewhere.',
        'es': 'Sphaira usa la dirección local en casa y recurre a la remota en cualquier otro lugar.'},

    'setup.legacy.toggle': {'en': 'Legacy clients', 'es': 'Clientes antiguos'},
    'setup.legacy.supported_heading': {'en': 'Supported Clients', 'es': 'Clientes compatibles'},
    'setup.legacy.supported_intro': {
        'en': 'These clients browse the shop from a file list using their own title metadatas, which can '
              'differ from what\'s actually identified by {shop_name}.',
        'es': 'Estos clientes exploran la tienda desde una lista de archivos usando sus propios metadatos, '
              'que pueden diferir de lo que {shop_name} identificó realmente.'},
    'setup.legacy.instructions_heading': {'en': 'Setup Instructions', 'es': 'Instrucciones de configuración'},
    'setup.legacy.local_tab': {'en': 'Local Access', 'es': 'Acceso local'},
    'setup.legacy.remote_tab': {'en': 'Remote Access', 'es': 'Acceso remoto'},
    'setup.legacy.local_alert': {
        'en': 'is for when your Nintendo Switch and {shop_name} server are on the same network (e.g., both on your home WiFi).',
        'es': 'es para cuando tu Nintendo Switch y el servidor de {shop_name} están en la misma red (por ejemplo, ambos en el WiFi de tu casa).'},
    'setup.legacy.remote_alert': {
        'en': 'allows you to access your {shop_name} shop from anywhere over the internet. Requires proper port forwarding or a reverse proxy setup.',
        'es': 'te permite acceder a tu tienda de {shop_name} desde cualquier lugar por internet. Necesita el reenvío de puertos o un reverse proxy bien configurado.'},
    'setup.legacy.no_local_address': {
        'en': 'Unable to determine local server address. Please check your network configuration.',
        'es': 'No se pudo determinar la dirección local del servidor. Revisá la configuración de tu red.'},
    'setup.legacy.no_remote_host': {
        'en': 'Remote host not configured. Please configure the remote host in the',
        'es': 'No hay un host remoto configurado. Configuralo en'},
    'setup.legacy.no_remote_host_post': {'en': 'page under the Shop section.', 'es': 'dentro de la sección Tienda.'},
    'setup.legacy.press_save_reload': {'en': 'Press <strong>Save</strong> to save the location and load the shop',
                                       'es': 'Presioná <strong>Save</strong> para guardar la dirección y cargar la tienda'},
    'setup.legacy.press_save_restart': {'en': 'Press <strong>Save</strong> and <strong>restart Sphaira</strong>',
                                        'es': 'Presioná <strong>Save</strong> y reiniciá Sphaira'},
    'setup.legacy.tinfoil_heading': {'en': 'Tinfoil Setup', 'es': 'Configuración de Tinfoil'},
    'setup.legacy.sphaira_heading': {'en': 'Sphaira (file browser) Setup', 'es': 'Configuración de Sphaira (navegador de archivos)'},
    'setup.legacy.cyberfoil_heading': {'en': 'CyberFoil Setup', 'es': 'Configuración de CyberFoil'},
    'setup.legacy.enter_details': {'en': 'Enter the following details:', 'es': 'Ingresá los siguientes datos:'},
    'setup.legacy.protocol_label': {'en': 'Protocol:', 'es': 'Protocolo:'},
    'setup.legacy.host_label': {'en': 'Host:', 'es': 'Host:'},
    'setup.legacy.port_label': {'en': 'Port:', 'es': 'Puerto:'},
    'setup.legacy.path_label': {'en': 'Path:', 'es': 'Ruta:'},
    'setup.legacy.username_label': {'en': 'Username:', 'es': 'Usuario:'},
    'setup.legacy.password_label': {'en': 'Password:', 'es': 'Contraseña:'},
    'setup.legacy.title_label': {'en': 'Title:', 'es': 'Título:'},
    'setup.legacy.enabled_label': {'en': 'Enabled:', 'es': 'Habilitado:'},
    'setup.legacy.shop_title_label': {'en': 'Shop title:', 'es': 'Título de la tienda:'},
    'setup.legacy.shop_protocol_label': {'en': 'Shop protocol:', 'es': 'Protocolo de la tienda:'},
    'setup.legacy.type_label': {'en': 'Type:', 'es': 'Tipo:'},
    'setup.legacy.url_label': {'en': 'URL:', 'es': 'URL:'},
    'setup.legacy.path_all_hint': {'en': 'for', 'es': 'para'},
    'setup.legacy.path_all_hint_all': {'en': 'all', 'es': 'todo el'},
    'setup.legacy.path_all_hint_post': {'en': 'content, else one of', 'es': 'contenido, o alguno de'},
    'setup.legacy.path_all_hint_tail': {'en': 'to serve specific content.', 'es': 'para servir contenido específico.'},
    'setup.legacy.url_append_hint': {'en': 'Add', 'es': 'Agregá'},
    'setup.legacy.url_append_hint_tail': {'en': 'to serve specific content.', 'es': 'para servir contenido específico.'},
    'setup.legacy.url_append_hint_remote': {'en': 'Append', 'es': 'Agregá'},
    'setup.legacy.tinfoil_file_browser': {'en': 'Navigate to', 'es': 'Navegá a'},
    'setup.legacy.file_browser_new': {'en': 'File Browser', 'es': 'Navegador de archivos'},
    'setup.legacy.new': {'en': 'New', 'es': 'Nuevo'},
    'setup.legacy.on_switch_open': {'en': 'On your Nintendo Switch, open', 'es': 'En tu Nintendo Switch, abrí'},
    'setup.legacy.emummc_pre': {'en': 'Open', 'es': 'Abrí'},
    'setup.legacy.emummc_mid': {'en': 'Install options', 'es': 'Opciones de instalación'},
    'setup.legacy.emummc_post': {'en': 'and turn on', 'es': 'y activá'},
    'setup.legacy.add_mount_pre': {'en': 'Open', 'es': 'Abrí'},
    'setup.legacy.add_mount_post': {'en': 'Enter the following details:', 'es': 'Ingresá los siguientes datos:'},
    'setup.legacy.navigate_filebrowser': {
        'en': 'Navigate to <strong>FileBrowser</strong> → <strong>Options</strong> → <strong>Mount</strong> → Select',
        'es': 'Navegá a <strong>FileBrowser</strong> → <strong>Options</strong> → <strong>Mount</strong> → Seleccioná'},
    'setup.legacy.preview_hint': {
        'en': 'Opening a file will show a preview of its content. To actually install the file, press <strong>Options</strong> → <strong>Install</strong>.',
        'es': 'Al abrir un archivo se muestra una vista previa de su contenido. Para instalarlo de verdad, presioná <strong>Options</strong> → <strong>Install</strong>.'},
    'setup.legacy.refresh_hint': {
        'en': 'To refresh the shop, simply select another <code>Mount</code> then select back {shop_name}.',
        'es': 'Para refrescar la tienda, elegí otro <code>Mount</code> y después volvé a {shop_name}.'},
    'setup.legacy.settings_shop_add': {
        'en': 'Open <strong>Settings</strong> → <strong>Shop</strong> → <strong>Add new shop</strong>',
        'es': 'Abrí <strong>Settings</strong> → <strong>Shop</strong> → <strong>Add new shop</strong>'},
    'setup.legacy.active_shop_hint': {'en': 'Ensure <strong>Active shop</strong> is set to the correct shop',
                                      'es': 'Verificá que <strong>Active shop</strong> apunte a la tienda correcta'},
    'setup.legacy.back_to_eshop': {
        'en': 'Press <strong>Back</strong> to go back to the main menu, and open <strong>Install from eShop</strong> to browse your shop',
        'es': 'Presioná <strong>Back</strong> para volver al menú principal, y abrí <strong>Install from eShop</strong> para explorar tu tienda'},
}


def current_language():
    """The person's chosen language for this request: the cookie if it's one we
    support, otherwise the default. Never raises on a missing/garbled cookie."""
    lang = request.cookies.get(LANGUAGE_COOKIE)
    return lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE


def t(key, **kwargs):
    """Translate `key` for the current request's language. Falls back to English, then
    to the raw key itself, so a missing translation is visible-but-harmless rather than
    a crash. `**kwargs` are applied with str.format for the rare parameterized string."""
    entry = TRANSLATIONS.get(key)
    if entry is None:
        text = key
    else:
        lang = current_language()
        text = entry.get(lang) or entry.get(DEFAULT_LANGUAGE) or key
    return text.format(**kwargs) if kwargs else text


def register_i18n(app):
    """Wire `t()` into Jinja and add the language-switch route. Call once from
    create_app."""
    app.jinja_env.globals['t'] = t
    app.jinja_env.globals['current_language'] = current_language
    app.jinja_env.globals['SUPPORTED_LANGUAGES'] = SUPPORTED_LANGUAGES

    from flask import redirect, request as flask_request

    @app.route('/set-language/<lang>')
    def set_language(lang):
        target = lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
        next_url = flask_request.referrer or '/'
        resp = redirect(next_url)
        # A year is plenty for a UI preference; the cookie is not sensitive, so no
        # need for the shorter-lived, stricter handling session cookies get.
        resp.set_cookie(LANGUAGE_COOKIE, target, max_age=60 * 60 * 24 * 365, samesite='Lax')
        return resp
