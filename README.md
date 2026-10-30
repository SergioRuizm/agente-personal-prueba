# Agente Personal

Asistente personal que se ejecuta en Windows y se usa desde el navegador. Puede guardar tareas, apuntes y tarjetas; leer documentos; revisar código; y editar fotos guardando copias.

> **Estado:** proyecto en pruebas, publicado en un repositorio privado de GitHub. No está disponible para descarga pública. Este README describe la versión web de `agente_web.py` y el ejecutable creado con `crear_exe.bat`; no describe una aplicación de escritorio independiente.

## Antes de empezar

- Para usar el `.exe`, no necesitas instalar Python. Para ejecutar el código fuente sí necesitas Python.
- El agente necesita una clave de Google Gemini. Cada persona usa la suya y es responsable de sus límites y condiciones de uso.
- Los mensajes y los documentos que pidas analizar se envían a Google Gemini. No envíes información que no quieras compartir con ese servicio.
- La clave se guarda en `%APPDATA%\AgentePersonal\config.json`. Ese archivo contiene la clave en texto legible: no lo compartas ni lo subas a Internet.
- Conversaciones, tareas y otros datos se guardan en `datos_agente`, junto al programa. Documentos, fotos y código se guardan en `documentos`, `fotos` y `codigo`. Haz copias de seguridad antes de mover o borrar esas carpetas.

## Usar el ejecutable

1. Copia `AgentePersonal.exe` a una carpeta normal en la que puedas guardar archivos. No lo ejecutes desde una carpeta temporal.
2. Haz doble clic en `AgentePersonal.exe`. Mantén abierta la ventana negra que aparece.
3. Abre `http://localhost:8765` en el navegador de ese ordenador e introduce el PIN que muestra la ventana.
4. La primera vez, pega tu clave en la ventana «Clave de Gemini». La aplicación la comprobará con una petición breve y, si Google la acepta, la guardará en este ordenador.
5. Para cambiar una clave más adelante, usa «Clave de Gemini» en el menú lateral. No necesitas editar `config.json`.
6. Para cerrar el agente, vuelve a la ventana negra y pulsa `Ctrl+C`.

La clave se guarda en `%APPDATA%\AgentePersonal\config.json` y contiene texto legible. No compartas ese archivo. Configura o cambia la clave desde el navegador del mismo ordenador donde se ejecuta el agente; por seguridad, no se acepta desde un móvil ni desde otro dispositivo de la red.

## Ejecutar desde el código fuente

Se ha probado la importación de las dependencias con Python 3.14 en Windows. No se ha certificado la compatibilidad con todas las versiones de Python 3.10 o posteriores.

En PowerShell, desde la carpeta que contiene `agente_web.py` y `agente_personal.py`:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe agente_web.py
```

Deja abierta la ventana de PowerShell. Visita `http://localhost:8765`, introduce el PIN y configura la clave desde la interfaz web.

## Crear el ejecutable

Con Python 3.14, PyInstaller y las dependencias instaladas, ejecuta `crear_exe.bat` desde el Explorador de archivos. El ejecutable se genera en `dist\AgentePersonal.exe`.

La compilación de prueba se hizo en Windows con Python 3.14 y PyInstaller 6.17. El motor `agente_personal` se incluye explícitamente porque se carga dinámicamente. Una compilación anterior omitió ese módulo y falló; la compilación actual ya arranca con el módulo incluido. Aún falta repetir la prueba en otro Windows sin Python con esta compilación actualizada.

## Documentos, fotos y código

- Se aceptan documentos PDF, DOCX y archivos de texto con extensiones TXT, MD, CSV, HTML, JSON y XML. Límite de subida: 60 MB.
- Las fotos admiten JPG, JPEG, PNG, WEBP, BMP y GIF. Las ediciones se guardan en `fotos\editadas`; la herramienta de edición no modifica la original.
- Para revisar código, coloca los archivos en `codigo`. Si pides corregir un archivo, revisa los cambios y confirma antes de aplicarlos. Se guarda una copia de seguridad en `codigo\copias_seguridad`.
- El contenido que el agente envía a Gemini puede incluir texto de documentos o código que le pidas leer.

## Acceso desde otro dispositivo

Por defecto, el servidor solo escucha en este ordenador (`127.0.0.1`). Para permitir el acceso desde dispositivos de la misma red privada, inicia el programa desde PowerShell con:

```powershell
py -3.14 agente_web.py --movil
```

Configura o cambia la clave desde el navegador del propio ordenador, no desde el móvil. Si el Firewall de Windows pregunta, permite el acceso solo en redes privadas; no marques redes públicas. El modo móvil expone el servicio en la red local y usa PIN. No expongas el programa directamente a Internet; para acceso remoto, utiliza una VPN privada.

## Estado de las pruebas

- Probado por el usuario: acceso web local, guardar una tarea, leer un documento de prueba, editar una imagen de prueba y conservar conversación y tarea tras reiniciar.
- Probado por el usuario: una compilación anterior del ejecutable abrió la aplicación y respondió a una tarea en otro Windows sin Python; la compilación siguiente falló porque no incluyó el módulo dinámico `agente_personal`.
- Probado durante la preparación: la compilación actual incluye el módulo dinámico y arranca con una configuración de prueba que contiene una clave ficticia; ayuda del ejecutable y compilación con PyInstaller 6.17.
- Probado durante la preparación: sintaxis e importaciones con Python 3.14; compilación con PyInstaller 6.17; ayuda del ejecutable; y pruebas aisladas del formulario de clave, incluido rechazo de claves no válidas y persistencia de una clave ficticia.
- Pendiente: probar esta compilación actualizada en el otro Windows; probar la introducción de una clave real con la nueva interfaz; otros navegadores, lectores de pantalla, macOS y Linux; y revisión completa de seguridad.

## Licencia y contacto

Este proyecto se distribuye bajo la licencia MIT. Puedes consultar los términos en el archivo `LICENSE`. Para preguntas o sugerencias, utiliza GitHub Issues cuando el repositorio esté publicado.
