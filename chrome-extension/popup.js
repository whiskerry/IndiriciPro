const BRIDGE_URL = "http://127.0.0.1:45821";

const statusBadge = document.getElementById("statusBadge");
const streamList = document.getElementById("streamList");
const countText = document.getElementById("countText");
const clearBtn = document.getElementById("clearBtn");
const keyInput = document.getElementById("keyInput");
const toastEl = document.getElementById("toast");

let activeTabId = null;
let bridgeOnline = false;

function cleanKeys(rawText) {
  if (!rawText) return "";
  const matches = rawText.match(/[a-fA-F0-9]{32}:[a-fA-F0-9]{32}/g);
  if (matches && matches.length > 0) {
    const unique = [...new Set(matches.map((k) => k.toLowerCase()))];
    return unique.join(" ");
  }
  return rawText
    .replace(/(?:^|\s)--?key\s+/gi, " ")
    .replace(/["']/g, "")
    .replace(/\s+/g, " ")
    .trim();
}

keyInput.addEventListener("paste", () => {
  setTimeout(() => {
    const cleaned = cleanKeys(keyInput.value);
    if (cleaned !== keyInput.value) {
      keyInput.value = cleaned;
    }
  }, 0);
});

keyInput.addEventListener("blur", () => {
  keyInput.value = cleanKeys(keyInput.value);
});

function showToast(msg, isError = false) {
  toastEl.textContent = msg;
  toastEl.className = "toast" + (isError ? " err" : "");
  setTimeout(() => {
    toastEl.className = "toast hidden";
  }, 2400);
}

async function checkBridge() {
  try {
    const res = await fetch(`${BRIDGE_URL}/ping`, { method: "GET" });
    if (res.ok) {
      const data = await res.json();
      bridgeOnline = true;
      statusBadge.textContent = `● Bağlı (v${data.version || "2.0"})`;
      statusBadge.className = "status online";
      return;
    }
  } catch (_) {}
  bridgeOnline = false;
  statusBadge.textContent = "● İndirici Pro Kapalı";
  statusBadge.className = "status offline";
}

async function sendToApp(item, mode) {
  if (!bridgeOnline) {
    await checkBridge();
    if (!bridgeOnline) {
      showToast("İndirici Pro açık değil! Önce programı başlatın.", true);
      return;
    }
  }
  try {
    const res = await fetch(`${BRIDGE_URL}/send`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        url: item.url,
        name: item.title || "",
        key: cleanKeys(keyInput.value),
        mode,
      }),
    });
    if (res.ok) {
      showToast(mode === "queue" ? "✅ Kuyruğa eklendi!" : "✅ İndirici Pro'ya gönderildi!");
    } else {
      showToast("Gönderilemedi (HTTP " + res.status + ")", true);
    }
  } catch (e) {
    showToast("Bağlantı hatası: İndirici Pro açık mı?", true);
  }
}

function renderStreams(items) {
  countText.textContent = `Yakalanan Yayınlar (${items.length})`;
  if (!items.length) {
    streamList.innerHTML = `
      <div class="empty">
        Bu sekmede henüz MPD veya M3U8 yayını yakalanmadı.<br />
        Videoyu oynattığınızda yayınlar burada otomatik görünecektir.
      </div>`;
    return;
  }

  streamList.innerHTML = "";
  for (const item of items) {
    const card = document.createElement("div");
    card.className = "card";

    const top = document.createElement("div");
    top.className = "card-top";

    const title = document.createElement("div");
    title.className = "card-title";
    title.textContent = item.title || "İsimsiz Yayın";
    title.title = item.title || "";

    const badges = document.createElement("div");
    badges.className = "badges";
    badges.innerHTML = `<span class="badge">${item.platform}</span><span class="badge kind">${item.kind}</span>`;

    top.appendChild(title);
    top.appendChild(badges);

    const urlDiv = document.createElement("div");
    urlDiv.className = "card-url";
    urlDiv.textContent = item.url;
    urlDiv.title = item.url;

    const actions = document.createElement("div");
    actions.className = "actions";

    const btnFill = document.createElement("button");
    btnFill.className = "btn btn-primary";
    btnFill.textContent = "📥 Forma Gönder";
    btnFill.addEventListener("click", () => sendToApp(item, "fill"));

    const btnQueue = document.createElement("button");
    btnQueue.className = "btn btn-queue";
    btnQueue.textContent = "➕ Kuyruğa Ekle";
    btnQueue.addEventListener("click", () => sendToApp(item, "queue"));

    const btnCopy = document.createElement("button");
    btnCopy.className = "btn btn-copy";
    btnCopy.textContent = "📋";
    btnCopy.title = "Linki Kopyala";
    btnCopy.addEventListener("click", async () => {
      await navigator.clipboard.writeText(item.url);
      showToast("📋 Link panoya kopyalandı!");
    });

    actions.appendChild(btnFill);
    actions.appendChild(btnQueue);
    actions.appendChild(btnCopy);

    card.appendChild(top);
    card.appendChild(urlDiv);
    card.appendChild(actions);
    streamList.appendChild(card);
  }
}

clearBtn.addEventListener("click", async () => {
  if (activeTabId == null) return;
  await chrome.runtime.sendMessage({ type: "CLEAR_STREAMS", tabId: activeTabId });
  renderStreams([]);
});

function detectVideoPage(tab) {
  if (!tab || !tab.url) return null;
  const u = tab.url;
  const low = u.toLowerCase();
  let platform = null;
  if (low.includes("youtube.com/watch") || low.includes("youtube.com/shorts/") || low.includes("youtu.be/")) {
    platform = "YOUTUBE";
  } else if (low.includes("vimeo.com/")) {
    platform = "VIMEO";
  } else if (low.includes("dailymotion.com/video/")) {
    platform = "DAILYMOTION";
  } else if (low.includes("tiktok.com/") && low.includes("/video/")) {
    platform = "TIKTOK";
  } else if ((low.includes("x.com/") || low.includes("twitter.com/")) && low.includes("/status/")) {
    platform = "X/TWITTER";
  } else if (low.includes("instagram.com/reel/") || low.includes("instagram.com/p/")) {
    platform = "INSTAGRAM";
  } else if (low.includes("twitch.tv/videos/")) {
    platform = "TWITCH";
  }
  if (!platform) return null;

  let clean = (tab.title || "").replace(/^\(\d+\)\s*/, "").trim();
  const parts = clean.split(/\s*[-|–]\s*/).map((p) => p.trim()).filter(Boolean);
  if (parts.length > 0) clean = parts[0];
  return {
    url: u,
    title: clean || platform + " Video",
    platform,
    kind: "yt-dlp",
  };
}

async function init() {
  checkBridge();
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab && tab.id != null) {
    activeTabId = tab.id;
    const res = await chrome.runtime.sendMessage({ type: "GET_STREAMS", tabId: activeTabId });
    const items = (res && res.items) ? [...res.items] : [];
    const pageVideo = detectVideoPage(tab);
    if (pageVideo && !items.some((x) => x.url === pageVideo.url)) {
      items.unshift(pageVideo);
    }
    renderStreams(items);
  }
}

init();
