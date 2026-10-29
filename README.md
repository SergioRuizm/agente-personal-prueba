# Agente Personal

Asistente personal que se ejecuta en Windows y se usa desde el navegador. Puede guardar tareas, apuntes y tarjetas; leer documentos; revisar código; y editar fotos guardando copias.

> **Estado:** proyecto en pruebas. Aún no hay una publicación oficial en GitHub. Este README describe la versión web de `agente_web.py` y el ejecutable creado con `crear_exe.bat`; no describe una aplicación de escritorio independiente.

## Antes de empezar

- Para usar el `.exe`, no necesitas instalar Python. Para ejecutar el código fuente sí necesitas Python.
- El agente necesita una clave de Google Gemini. Cada persona usa la suya y es responsable de sus límites y condiciones de uso.
- Los mensajes y los documentos que pidas analizar se envían a Google Gemini. No envíes información que no quieras compartir con ese servicio.
- La clave se guarda en `%APPDATA%\AgentePersonal\config.json`. Ese archivo contiene la clave en texto legible: no lo compartas ni lo subas a Internet.
- Conversaciones, tareas y otros datos se guardan en `datos_agente`, junto al programa. Documentos, fotos y código se guardan en `documentos`, `fotos` y `codigo`. Haz copias de seguridad antes de mover o borrar esas carpetas.

## Usar el ejecutable

1. Copia `AgentePersonal.exe` a una carpeta normal en la que puedas guardar archivos. No lo ejecutes desde una carpeta temporal.
2. Haz doble clic en `AgentePersonal.exe`. Mantén abierta la ventana negra que aparece.
3. La primera vez, introduce tu clave de Gemini en esa ventana. No se mostrarán los caracteres mientras escribes. La aplicación intentará guardarla para los próximos usos.
4. Abre `http://localhost:8765` en el navegador de ese ordenador e introduce el PIN que muestra la ventana.
5. Para cerrar el agente, vuelve a la ventana negra y pulsa `Ctrl+C`.

Si la clave no se puede guardar, la ventana lo indicará. Si Gemini rechaza la clave, crea o revisa una clave en [Google AI Studio](https://aistudio.google.com/app/apikey) y actualiza el valor `clave` de `%APPDATA%\AgentePersonal\config.json` con el agente cerrado.

## Ejecutar desde el código fuente

Se ha probado la importación de las dependencias con Python 3.14 en Windows. No se ha certificado la compatibilidad con todas las versiones de Python 3.10 o posteriores.

En PowerShell, desde la carpeta que contiene `agente_web.py` y `agente_personal.py`:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe agente_web.py
```

La primera vez se pedirá la clave en la ventana de PowerShell. Deja esa ventana abierta y visita `http://localhost:8765` en el navegador.

## Crear el ejecutable

Con Python 3.14, PyInstaller y las dependencias instaladas, ejecuta `crear_exe.bat` desde el Explorador de archivos. El ejecutable se genera en `dist\AgentePersonal.exe`.

La compilación de prueba se hizo en Windows con Python 3.14 y PyInstaller 6.17. El ejecutable abrió la aplicación y respondió a una tarea de prueba. Aún no se ha verificado en una máquina cuya ausencia de Python se haya confirmado ni se han probado todas las funciones del `.exe`.

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

El `.exe` también acepta `--movil` si se inicia desde una terminal. Necesitarás el PIN. No expongas el programa directamente a Internet; para acceso remoto, utiliza una VPN privada. El acceso desde otros dispositivos aumenta el riesgo y no se recomienda en redes públicas.

## Estado de las pruebas

- Probado por el usuario: acceso web local, guardar una tarea, leer un documento de prueba, editar una imagen de prueba y conservar conversación y tarea tras reiniciar.
- Probado por el usuario: el ejecutable respondió a una tarea en otro ordenador después de introducir una clave válida. No se confirmó si ese ordenador tenía Python instalado.
- Probado durante la preparación: sintaxis e importaciones con Python 3.14; compilación con PyInstaller 6.17; ayuda del ejecutable; guardar y reutilizar una clave ficticia.
- Pendiente: probar todas las funciones del ejecutable en un Windows sin Python confirmado; otros navegadores, lectores de pantalla, macOS y Linux; y revisión completa de seguridad y publicación.

## Licencia y contacto

Este proyecto se distribuye bajo la licencia MIT. Puedes consultar los términos en el archivo `LICENSE`. Para preguntas o sugerencias, utiliza GitHub Issues cuando el repositorio esté publicado.
