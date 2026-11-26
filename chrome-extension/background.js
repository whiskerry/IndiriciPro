// İndirici Pro Chrome Eklentisi — Arka Plan Akış Yakalayıcı (Manifest V3)
const MAX_PER_TAB = 25;

// Sekme bazlı yakalanan yayınlar (session storage üzerinde saklanır, SW uyanınca kaybolmaz)
async function getTabStreams(tabId) {
  const key = `tab_${tabId}`;
  const res = await chrome.storage.session.get(key);
  return Array.isArray(res[key]) ? res[key] : [];
}

async function setTabStreams(tabId, items) {
  const key = `tab_${tabId}`;
  await chrome.storage.session.set({ [key]: items });
  updateBadge(tabId, items.length);
}

function updateBadge(tabId, count) {
  const text = count > 0 ? String(count) : "";
  chrome.action.setBadgeText({ tabId, text }).catch(() => {});
  chrome.action.setBadgeBackgroundColor({ tabId, color: "#0a84ff" }).catch(() => {});
}

function detectPlatform(url) {
  const u = url.toLowerCase();
  if (/(dtvcdns|dt-vod|dt-live|bc-hd|pt_mul_dash|bein|todtv|digiturk)/.test(u)) return "BEIN";
  if (/(tvplus|turkcelltv)/.test(u)) return "TVPLUS";
  if (/(tivibu|ttnet)/.test(u)) return "TIVIBU";
  if (/filbox/.test(u)) return "FILBOX";
  if (/(disney|dssott|bamgrid)/.test(u)) return "DISNEY";
  if (/(dsmart|d-smart)/.test(u)) return "DSMART";
  if (/(tvheryerde|kablotv|turksat)/.test(u)) return "KABLOTV";
  if (/(apple\.com|itunes|mzstatic)/.test(u)) return "ITUNES";
  if (/(hbomax|hbo\.|\.hbo|max\.com|warnermediacdn)/.test(u)) return "HBOMAX";
  return "STREAM";
}

function cleanTitle(rawTitle) {
  if (!rawTitle) return "";
  let t = rawTitle.trim();
  const parts = t.split(/\s*[-|–]\s*/).map((p) => p.trim()).filter(Boolean);
  if (parts.length > 0) {
    t = parts[0];
  }
  // TV+ vb. sitelerdeki sondaki "izle", "full izle", "hd izle", "canlı izle" eklerini temizle
  t = t.replace(/\s+(?:full\s+hd\s+|hd\s+|full\s+|canl[ıi]\s+|t[üu]rk[çc]e\s+dublaj\s+|altyaz[ıi]l[ıi]\s+|tek\s+par[çc]a\s+)?[iİıI]zle\s*$/gi, "").trim();
  return t;
}

const VIDEO_EXT_RE = /\.(mp4|m4v|webm|mkv|flv|3gp|3g2|mov|avi|wmv|ts|m2ts|ogv|mpeg|mpg|f4v|vob)$/i;
const SEGMENT_SKIP_RE = /(?:^|\/|_|-)(?:seg|segment|chunk|frag|part|init)[-_]?\d*\.(?:ts|m4s|mp4|webm)$/i;

function detectMediaInfo(url) {
  if (!url || !url.startsWith("http")) return null;
  const low = url.toLowerCase();
  // YouTube ham googlevideo parça isteklerini listeyi kirletmemesi için atla (sayfa linki yakalanır)
  if (low.includes("googlevideo.com/videoplayback")) return null;

  const clean = low.split("?")[0];
  if (clean.endsWith(".mpd") || clean.includes(".mpd/") || low.includes("playlist.mpd") || low.includes("manifest.mpd")) {
    return { kind: "DASH" };
  }
  if (clean.endsWith(".m3u8") || clean.includes(".m3u8/")) {
    return { kind: "HLS" };
  }
  const extMatch = clean.match(VIDEO_EXT_RE);
  if (extMatch) {
    if (SEGMENT_SKIP_RE.test(clean)) return null;
    return { kind: extMatch[1].toUpperCase() };
  }
  return null;
}

const DRM_PLATFORMS = new Set([
  "BEIN", "TVPLUS", "TIVIBU", "FILBOX", "DISNEY", "DSMART", "KABLOTV", "ITUNES", "HBOMAX",
]);

chrome.webRequest.onBeforeRequest.addListener(
  async (details) => {
    if (details.tabId < 0) return;
    const url = details.url;
    const media = detectMediaInfo(url);
    if (!media) return;

    const platform = detectPlatform(url);
    const isManifest = media.kind === "DASH" || media.kind === "HLS";

    // DRM platformlarının (beIN, TV+, Tivibu vb.) DASH/HLS içindeki ham .mp4/.ts akış parçalarını gizle
    if (!isManifest && (DRM_PLATFORMS.has(platform) || url.toLowerCase().includes("_dash_"))) {
      return;
    }

    let tabTitle = "";
    try {
      const tab = await chrome.tabs.get(details.tabId);
      tabTitle = (tab && tab.title) ? tab.title : "";
    } catch (_) {}

    const list = await getTabStreams(details.tabId);

    // Eğer bu sekmede aynı sunucudan zaten bir DASH/HLS manifest yakalandıysa,
    // o sunucunun alt .mp4/.ts parçalarını listeye ekleme
    let host = "";
    try { host = new URL(url).hostname; } catch (_) {}
    if (!isManifest && host && list.some((x) => (x.kind === "DASH" || x.kind === "HLS") && x.url.includes(host))) {
      return;
    }

    // Yeni bir DASH/HLS manifest geldiğinde aynı sunucudan önceden düşmüş alt .mp4 parçalarını temizle
    let filtered = list.filter((item) => {
      if (item.url === url) return false;
      if (isManifest && host && item.kind !== "DASH" && item.kind !== "HLS" && item.url.includes(host)) {
        return false;
      }
      return true;
    });

    filtered.unshift({
      url,
      title: cleanTitle(tabTitle),
      platform,
      kind: media.kind,
      time: new Date().toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit", second: "2-digit" }),
    });

    await setTabStreams(details.tabId, filtered.slice(0, MAX_PER_TAB));
  },
  { urls: ["<all_urls>"] }
);

// Sekme kapandığında temizle
chrome.tabs.onRemoved.addListener((tabId) => {
  chrome.storage.session.remove(`tab_${tabId}`).catch(() => {});
});

// Yeni sayfaya gidildiğinde önceki sayfanın linklerini temizle
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.status === "loading" && changeInfo.url) {
    setTabStreams(tabId, []);
  }
});

// Popup'tan gelen mesajlar
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "GET_STREAMS") {
    getTabStreams(msg.tabId).then((items) => sendResponse({ items }));
    return true;
  }
  if (msg.type === "CLEAR_STREAMS") {
    setTabStreams(msg.tabId, []).then(() => sendResponse({ ok: true }));
    return true;
  }
});
