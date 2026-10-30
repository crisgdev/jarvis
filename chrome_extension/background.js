/**
 * JARVIS YouTube Loop - Service Worker (Manifest v3)
 *
 * Hace polling al servidor Flask de JARVIS para detectar comandos de bucle.
 * Cuando detecta uno nuevo, ejecuta document.querySelector('video').loop = true;
 * en la pestaña activa de YouTube mediante chrome.scripting.executeScript.
 */

const FLASK_URL = "http://127.0.0.1:5050";
const POLL_INTERVAL_MS = 3000;

let lastSeenTs = null;

// Verificar si una pestaña es de YouTube
function isYouTubeTab(url) {
  if (!url) return false;
  return url.includes("youtube.com") || url.includes("youtu.be");
}

// Obtener la pestaña activa de YouTube (si la hay)
async function getActiveYouTubeTab() {
  const tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  const tab = tabs[0];
  if (tab && isYouTubeTab(tab.url)) {
    return tab;
  }
  // Si la activa no es YouTube, buscar cualquier pestaña de YouTube
  const allTabs = await chrome.tabs.query({});
  for (const t of allTabs) {
    if (t && isYouTubeTab(t.url)) {
      return t;
    }
  }
  return null;
}

// Ejecutar el bucle en la pestaña indicada
async function enableLoop(tab) {
  try {
    await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => {
        const video = document.querySelector("video");
        if (video) {
          video.loop = true;
          // Intentar reanudar si está pausado (YouTube a veces pausa al cambiar)
          if (video.paused) {
            video.play().catch(() => {});
          }
          return true;
        }
        return false;
      },
    });
    console.log("[JARVIS YouTube Loop] Bucle activado en tab", tab.id);
  } catch (err) {
    console.error("[JARVIS YouTube Loop] Error activando bucle:", err);
  }
}

// Consultar el servidor Flask por un comando nuevo
async function poll() {
  try {
    const res = await fetch(`${FLASK_URL}/status`, { method: "GET" });
    if (!res.ok) return;
    const data = await res.json();
    const cmd = data.last_command || {};
    const ts = cmd.ts;

    if (ts && ts !== lastSeenTs) {
      lastSeenTs = ts;
      const tab = await getActiveYouTubeTab();
      if (tab) {
        await enableLoop(tab);
      } else {
        console.log("[JARVIS YouTube Loop] No hay pestaña de YouTube abierta.");
      }
    }
  } catch (err) {
    // Servidor no disponible aún, ignorar silenciosamente
    console.debug("[JARVIS YouTube Loop] Servidor no disponible:", err.message);
  }
}

// Iniciar polling
setInterval(poll, POLL_INTERVAL_MS);
// Primera consulta inmediata
poll();

console.log("[JARVIS YouTube Loop] Service worker iniciado.");
