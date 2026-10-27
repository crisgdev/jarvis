"""Listener de Wake-on-LAN controlado por Telegram.

Correr este script en un dispositivo que este SIEMPRE ENCENDIDO y conectado
a la MISMA red de casa que la PC a encender (celular con Termux, Raspberry,
mini-PC, otro PC, router con Python...):

    python wake_listener.py

Cuando le escribas por Telegram "prende la pc" (o "enciende", "wol"), el
script envia el paquete magico wake-on-LAN a la MAC de config.json (wol.mac)
y la PC se enciende SOLO si tiene activado Wake-on-LAN en Windows/BIOS.

IMPORTANTE:
- El paquete magico viaja por la red local, asi que este dispositivo DEBE
  estar en la misma red que la PC. NO funciona desde el celular con datos.
- Usa un bot de Telegram IPSO (puede ser el mismo de JARVIS si este script
  corre solo cuando la PC esta apagada). TELEGRAM_BOT_TOKEN en .env.
- Solo el dueno (TELEGRAM_ALLOWED_USER_IDS en .env) puede encender.
"""

import json
import re
import socket
import sys
import time
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
API = "https://api.telegram.org/bot{token}/{method}"


def load_env():
    env = {}
    env_path = BASE_DIR / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return env


def load_config():
    cfg = {}
    cfg_path = BASE_DIR / "config.json"
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    return cfg


def _wol_payload(mac: str) -> bytes:
    clean = re.sub(r"[^0-9a-fA-F]", "", mac or "")
    if len(clean) != 12:
        raise ValueError(f"MAC invalida: {mac!r}")
    return b"\xff" * 6 + bytes.fromhex(clean) * 16


def send_wol(mac: str, broadcast: str, port: int) -> bool:
    payload = _wol_payload(mac)
    targets = list(dict.fromkeys([broadcast, "255.255.255.255"]))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for t in targets:
            sock.sendto(payload, (t, port))
    print(f"[WOL] Paquete enviado a {mac} -> {', '.join(f'{t}:{port}' for t in targets)}")
    return True


def api_call(token: str, method: str, data=None, timeout: int = 30) -> dict:
    req = urllib.request.Request(API.format(token=token, method=method),
                                 data=json.dumps(data).encode() if data else None,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def allowed_ids(env) -> set[int]:
    raw = env.get("TELEGRAM_ALLOWED_USER_IDS", "")
    ids = set()
    for part in raw.replace(",", " ").split():
        try:
            ids.add(int(part))
        except ValueError:
            pass
    return ids


def main():
    env = load_env()
    token = (env.get("TELEGRAM_WOL_BOT_TOKEN") or env.get("TELEGRAM_BOT_TOKEN") or "").strip()
    if not token:
        print("[ERROR] TELEGRAM_BOT_TOKEN no esta en .env")
        return

    cfg = load_config()
    wol = cfg.get("wol", {})
    mac = env.get("WOL_MAC") or wol.get("mac", "")
    broadcast = env.get("WOL_BROADCAST") or wol.get("broadcast") or "255.255.255.255"
    port = int(wol.get("port") or env.get("WOL_PORT") or 9)
    owners = allowed_ids(env)

    if "--test" in sys.argv:
        try:
            me = api_call(token, "getMe", timeout=15)
            if me.get("ok"):
                bot = me["result"]
                print(f"[TEST] Bot OK: @{bot.get('username')} (id {bot.get('id')})")
                if not owners:
                    print("[TEST] OJO: TELEGRAM_ALLOWED_USER_IDS vacio en .env: nadie podra encender.")
                if not mac:
                    print("[TEST] OJO: WOL_MAC vacio: no hay MAC a la que enviar el paquete.")
                print("[TEST] Escucha 'prende la pc' y envia el paquete WOL a la LAN.")
                return
            print(f"[TEST] getMe fallo: {me}")
        except Exception as e:
            print(f"[TEST] No se puede conectar a Telegram: {e}")
            print("[TEST] Revisa: Wi-Fi conectado, bateria sin restricciones, y el token.")
        return

    try:
        send_wol(mac, broadcast, port)
        print("[WOL] Test de paquete enviado al arrancar (si la PC estaba off ya se esta encendiendo).")
    except Exception as e:
        print(f"[ERROR] MAC no valida ({e}). Configura wol.mac en config.json")

    offset = 0
    backoff = 2
    print("[LISTENER] Escuchando Telegram (Ctrl+C para salir)...")
    while True:
        try:
            res = api_call(token, "getUpdates", {"offset": offset, "timeout": 10})
            backoff = 2
        except Exception as e:
            print(f"[ERROR] getUpdates: {e}")
            print(f"[INFO] Reintentando en {backoff}s (si repite: revisa Wi-Fi/ahorro de bateria)")
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)
            continue

        for upd in res.get("result", []):
            offset = upd["update_id"] + 1
            msg = upd.get("message") or {}
            text = (msg.get("text") or "").strip().lower()
            user = msg.get("from", {}).get("id")
            chat = msg.get("chat", {}).get("id")

            if text in ("/start", "/help"):
                api_call(token, "sendMessage", {
                    "chat_id": chat,
                    "text": f"Listener WOL activo. Tu id es {user}. Di 'prende la pc' para encenderla."
                })
                continue

            if user not in owners:
                continue
            if not any(k in text for k in ("prende", "enciende", "encender", "wol", "prende la pc")):
                continue

            print(f"[WOL] Orden recibida: '{text}'")
            try:
                send_wol(mac, broadcast, port)
                api_call(token, "sendMessage", {"chat_id": chat, "text": "Enviando paquete wake-on-LAN a la PC."})
            except Exception as e:
                print(f"[ERROR] {e}")
                api_call(token, "sendMessage", {"chat_id": chat, "text": f"Error: {e}"})

        time.sleep(0.5)


if __name__ == "__main__":
    main()