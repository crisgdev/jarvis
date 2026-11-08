# Termux: listener de Wake-on-LAN

Guia para convertir tu celular Android en el receptor que enciende la laptop
por Telegram desde casa (mismo Wi-Fi). Uso el script `wake_listener.py`.

## Requisitos

- Celular **Android** con [Termux](https://termux.dev) instalado.
- Laptop con Wake-on-LAN activado (`enable_wol.ps1`) y conectada por **ethernet**
  y **cargador** (un laptop despierta por WOL casi siempre solo enchufado).

## Instalacion (una sola vez)

1) Actualizar e instalar Python:

```bash
pkg update
pkg install python -y
```

2) Dar permiso de almacenamiento (para importar el archivo):

```bash
termux-setup-storage
```
   Acepta el permiso que aparece.

3) Pasar `wake_listener.py` de la laptop al celular:
   - En la laptop: Telegram (escritorio/navegador) -> *Mensajes guardados* ->
     envía el archivo `wake_listener.py`.
   - En el celular: ábrelo y toca descargar (queda en `Descargas`).
   - En Termux:

```bash
ls /sdcard/Download/          # ver el nombre exacto del archivo
cp /sdcard/Download/wake_listener.py ~/
```

4) Crear el `.env` junto al script (con TUS datos):

```bash
cat > ~/.env << 'EOF'
TELEGRAM_BOT_TOKEN=TU_TOKEN_DEL_BOT
TELEGRAM_ALLOWED_USER_IDS=TU_ID_DE_TELEGRAM
WOL_MAC=00:00:00:00:00:00
WOL_BROADCAST=192.168.1.255
EOF
```
   - `TELEGRAM_BOT_TOKEN` y `TELEGRAM_ALLOWED_USER_IDS`: igual que en el `.env` de la laptop.
   - `WOL_BROADCAST`: broadcast de la subred de tu casa (averiguable con `ipconfig` en la
     laptop: la IP es `192.168.X.Y` y el broadcast es `192.168.X.255`).
   - Si quieres un bot exclusivo para encender la PC, crépalo con BotFather y usa
     `TELEGRAM_WOL_BOT_TOKEN` en lugar de `TELEGRAM_BOT_TOKEN`.

## Probar

```bash
cd ~ && python wake_listener.py
```

Debe salir `[WOL] Paquete enviado...` y luego `[LISTENER] Escuchando Telegram...`.

- Envía `/start` al bot desde tu Telegram: te responde el id y confirma el listener.
- Con la laptop **apagada y enchufada**: escribe `prende la pc` (o "enciende la
  laptop") y la laptop debe encender.

## Importante

- El listener debe estar corriend el termux y el celular conectado al **mismo Wi-Fi
  de casa**: el paquete mágico viaja solo por la red local. Con datos móviles NO llega.
- Conflictos de updates: si la laptop está ENCENDIDA y JARVIS está corriendo y usas
  el MISMO bot, dos procesos se pelean por los mensajes. Ese caso no importa (la
  laptop ya está encendida); para usos paralelos usa `TELEGRAM_WOL_BOT_TOKEN`.
- Si el celular "mata" Termux en segundo plano: quita la optimización de batería de
  Termux (Ajustes -> Bateria -> Termux -> Sin restricciones). Para la prueba basta
  mantener Termux en primer plano.

## Deshacer / reversibilidad

Nada de esto cambia la laptop. El cambio en la laptop (WOL + Fast Startup Off) se
revierte con:

```powershell
powershell -ExecutionPolicy Bypass -File .\enable_wol.ps1 -Undo
```
