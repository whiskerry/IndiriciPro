# -*- coding: utf-8 -*-
import os
import re
import sys
import json
import time
import shutil
import subprocess
import threading
import datetime
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from pathlib import Path
from urllib.parse import urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# ============================================================================
# DİNAMİK KLASÖR VE ARAÇ YAPILANDIRMASI (PORTABLE + KURULUM UYUMLU)
# ============================================================================
APP_VERSION = "2.0.0"
CHROME_BRIDGE_PORT = 45821

if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent

IS_PORTABLE = (APP_DIR / "portable.flag").exists() or (APP_DIR / "data").exists()

if IS_PORTABLE:
    APP_DATA_DIR = APP_DIR / "data"
    DEFAULT_DOWNLOAD_DIR = APP_DIR / "İndirilenler"
    LOG_DIR = APP_DIR / "Logs"
else:
    APP_DATA_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "IndiriciPro"
    DEFAULT_DOWNLOAD_DIR = Path.home() / "Downloads" / "IndiriciPro"
    LOG_DIR = APP_DATA_DIR / "Logs"

HISTORY_FILE = APP_DATA_DIR / "history.json"
SETTINGS_FILE = APP_DATA_DIR / "settings.json"
MAX_HISTORY_ITEMS = 10


def arac_bul(exe_adi: str) -> Path:
    """
    Harici araçları (N_m3u8DL-RE, ffmpeg, mp4decrypt) şu sırayla arar:
    1) Uygulama klasörü / tools / <exe>
    2) Uygulama klasörü / <exe>
    3) Sistem PATH
    """
    adaylar = [
        APP_DIR / "tools" / exe_adi,
        APP_DIR / exe_adi,
    ]
    for aday in adaylar:
        if aday.exists():
            return aday
    sistemde = shutil.which(exe_adi)
    if sistemde:
        return Path(sistemde)
    return APP_DIR / "tools" / exe_adi


def ikon_bul() -> Path:
    """Gömülü veya yerel uygulama ikonunu (app_icon.ico) döner."""
    meipass = getattr(sys, "_MEIPASS", None)
    adaylar = []
    if meipass:
        adaylar.append(Path(meipass) / "assets" / "app_icon.ico")
        adaylar.append(Path(meipass) / "app_icon.ico")
    adaylar.extend([
        APP_DIR / "assets" / "app_icon.ico",
        APP_DIR / "app_icon.ico",
    ])
    for aday in adaylar:
        if aday.exists():
            return aday
    return None


N_M3U8DL_EXE = arac_bul("N_m3u8DL-RE.exe")
FFMPEG_EXE = arac_bul("ffmpeg.exe")
MP4DECRYPT_EXE = arac_bul("mp4decrypt.exe")
YT_DLP_EXE = arac_bul("yt-dlp.exe")

DIRECT_VIDEO_EXTS = (
    ".mp4", ".m4v", ".webm", ".mkv", ".flv", ".3gp", ".3g2",
    ".mov", ".avi", ".wmv", ".ts", ".m2ts", ".ogv", ".mpeg",
    ".mpg", ".f4v", ".vob",
)


def yt_dlp_gerekli_mi(url: str) -> bool:
    """
    Link .mpd veya .m3u8 manifest ise N_m3u8DL-RE kullanılır;
    YouTube, sosyal medya veya doğrudan video dosyaları (.mp4, .flv, .3gp, .webm, .ts vb.)
    için yt-dlp.exe kullanılır.
    """
    if not url:
        return False
    low = url.lower()
    temiz_yol = low.split("?")[0]
    if temiz_yol.endswith((".mpd", ".m3u8")) or ".mpd/" in temiz_yol or ".m3u8/" in temiz_yol:
        return False
    if "playlist.mpd" in low or "manifest.mpd" in low:
        return False
    return True

DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

ANSI_NEWLINE_RE = re.compile(r"\x1b\[(?:\d*[EFGHKABCD]|\d*;\d*[Hf])")
ANSI_ESCAPE_RE = re.compile(r"\x1b(?:\[[0-9;?]*[a-zA-Z]|\][^\x07]*\x07|[@-Z\\-_])")
TIMESTAMP_SPLIT_RE = re.compile(r"(?<!^)(?=\d{2}:\d{2}:\d{2}\.\d{3}\s+(?:INFO|WARN|ERROR|EXTRA)\s*:)")


def temizle_ve_satirlara_bol(ham_metin: str) -> list:
    """
    ANSI imleç/temizleme kodlarını yeni satıra çevirir, kalan ANSI kodlarını siler
    ve birbirine yapışmış zaman damgalı log satırlarını düzgünce ayırır.
    """
    if not ham_metin:
        return []
    metin = ANSI_NEWLINE_RE.sub("\n", ham_metin)
    metin = ANSI_ESCAPE_RE.sub("", metin)
    metin = metin.replace("\r", "\n")
    satirlar = []
    for parca in metin.split("\n"):
        parca = parca.strip()
        if not parca:
            continue
        for alt in TIMESTAMP_SPLIT_RE.split(parca):
            alt = alt.strip()
            if alt:
                satirlar.append(alt)
    return satirlar


def boyut_formatla(bayt: float) -> str:
    """Bayt cinsinden boyutu okunabilir KB/MB/GB metnine çevirir."""
    if bayt >= 1024 ** 3:
        return f"{bayt / (1024 ** 3):.2f} GB"
    if bayt >= 1024 ** 2:
        return f"{bayt / (1024 ** 2):.2f} MB"
    if bayt >= 1024:
        return f"{bayt / 1024:.1f} KB"
    return f"{int(bayt)} B"


# ============================================================================
# PLATFORM TANIMLARI (ADLANDIRMA ETİKETİ + HEADER BİLGİLERİ)
# ============================================================================
PLATFORMS = [
    {
        "id": "bein",
        "name": "beIN CONNECT / TOD / Digiturk",
        "suffix": "BEIN",
        "origin": "https://www.beinconnect.com.tr",
        "referer": "https://www.beinconnect.com.tr/",
        "keywords": [
            "dtvcdns",
            "dt-vod-",
            "dt-live-",
            "dt-vod",
            "dt-live",
            "bc-hd",
            "pt_mul_dash",
            "bein",
            "todtv",
            "tod.",
            "/tod/",
            "digiturk",
            "digicdn",
        ],
    },
    {
        "id": "tvplus",
        "name": "TV+",
        "suffix": "TVPLUS",
        "origin": "https://tvplus.com.tr",
        "referer": "https://tvplus.com.tr/",
        "keywords": ["tvplus", "turkcelltv", "tcell"],
    },
    {
        "id": "tivibu",
        "name": "Tivibu",
        "suffix": "TIVIBU",
        "origin": "https://www.tivibu.com.tr",
        "referer": "https://www.tivibu.com.tr/",
        "keywords": ["tivibu", "ttnet"],
    },
    {
        "id": "filbox",
        "name": "Filbox",
        "suffix": "FILBOX",
        "origin": "https://www.filbox.com.tr",
        "referer": "https://www.filbox.com.tr/",
        "keywords": ["filbox"],
    },
    {
        "id": "disney",
        "name": "Disney+",
        "suffix": "DISNEY",
        "origin": "https://www.disneyplus.com",
        "referer": "https://www.disneyplus.com/",
        "keywords": ["disney", "dssott", "bamgrid", "disneyplus", "starott"],
    },
    {
        "id": "dsmart",
        "name": "D-Smart / D-Smart GO",
        "suffix": "DSMART",
        "origin": "https://www.dsmartgo.com.tr",
        "referer": "https://www.dsmartgo.com.tr/",
        "keywords": ["dsmart", "d-smart"],
    },
    {
        "id": "kablotv",
        "name": "KabloTV (tvheryerde)",
        "suffix": "KABLOTV",
        "origin": "https://tvheryerde.com",
        "referer": "https://tvheryerde.com/",
        "keywords": ["tvheryerde", "kablotv", "turksat", "kablo"],
    },
    {
        "id": "itunes",
        "name": "Apple TV+ / iTunes",
        "suffix": "ITUNES",
        "origin": "https://tv.apple.com",
        "referer": "https://tv.apple.com/",
        "keywords": ["apple.com", "itunes", "mzstatic", "aaplimg", "tv.apple"],
    },
    {
        "id": "hbomax",
        "name": "HBO / Max",
        "suffix": "HBOMAX",
        "origin": "https://play.max.com",
        "referer": "https://play.max.com/",
        "keywords": [
            "hbomax",
            "hbo.",
            ".hbo",
            "/hbo",
            "max.com",
            "warnermediacdn",
            "hbogo",
            "wbd.com",
            "disco-api",
        ],
    },
]


# ============================================================================
# 4 TEMA (MEVCUT KOYU/AÇIK + MACOS APPLE KOYU/AÇIK)
# ============================================================================
THEMES = {
    "Klasik Koyu (Catppuccin)": {
        "style_kind": "classic",
        "bg": "#1e1e2e",
        "card": "#28283d",
        "border": "#45475a",
        "input_bg": "#313244",
        "input_fg": "#ffffff",
        "key_fg": "#a6e3a1",
        "name_fg": "#f9e2af",
        "fg": "#cdd6f4",
        "muted": "#a6adc8",
        "header_fg": "#f5e0dc",
        "accent": "#89b4fa",
        "accent_fg": "#11111b",
        "info_fg": "#89dceb",
        "success": "#a6e3a1",
        "success_fg": "#11111b",
        "danger": "#f38ba8",
        "danger_fg": "#11111b",
        "btn_bg": "#45475a",
        "btn_fg": "#ffffff",
        "btn_sec_bg": "#585b70",
        "btn_sec_fg": "#ffffff",
        "log_bg": "#11111b",
        "log_fg": "#cdd6f4",
        "diag_bg": "#181825",
        "diag_fg": "#f9e2af",
        "progress_trough": "#313244",
        "progress_bar": "#a6e3a1",
        "bar_video": "#a6e3a1",
        "bar_audio": "#fab387",
        "bar_sub": "#89dceb",
        "bar_mux": "#cba6f7",
        "bar_live": "#f38ba8",
        "tree_bg": "#181825",
        "tree_fg": "#cdd6f4",
        "tree_head_bg": "#313244",
        "tree_head_fg": "#89b4fa",
        "tree_sel_bg": "#45475a",
        "tree_sel_fg": "#ffffff",
        "tab_bg": "#28283d",
        "tab_sel_bg": "#313244",
    },
    "Klasik Açık (Latte)": {
        "style_kind": "classic",
        "bg": "#eff1f5",
        "card": "#ffffff",
        "border": "#ccd0da",
        "input_bg": "#e6e9ef",
        "input_fg": "#4c4f69",
        "key_fg": "#40a02b",
        "name_fg": "#df8e1d",
        "fg": "#4c4f69",
        "muted": "#6c6f85",
        "header_fg": "#1e66f5",
        "accent": "#1e66f5",
        "accent_fg": "#ffffff",
        "info_fg": "#04a5e5",
        "success": "#40a02b",
        "success_fg": "#ffffff",
        "danger": "#d20f39",
        "danger_fg": "#ffffff",
        "btn_bg": "#dce0e8",
        "btn_fg": "#4c4f69",
        "btn_sec_bg": "#ccd0da",
        "btn_sec_fg": "#4c4f69",
        "log_bg": "#f8f9fc",
        "log_fg": "#4c4f69",
        "diag_bg": "#fff9eb",
        "diag_fg": "#8c5200",
        "progress_trough": "#dce0e8",
        "progress_bar": "#40a02b",
        "bar_video": "#40a02b",
        "bar_audio": "#fe640b",
        "bar_sub": "#04a5e5",
        "bar_mux": "#8839ef",
        "bar_live": "#d20f39",
        "tree_bg": "#ffffff",
        "tree_fg": "#4c4f69",
        "tree_head_bg": "#e6e9ef",
        "tree_head_fg": "#1e66f5",
        "tree_sel_bg": "#1e66f5",
        "tree_sel_fg": "#ffffff",
        "tab_bg": "#dce0e8",
        "tab_sel_bg": "#ffffff",
    },
    "macOS Koyu (Apple Dark)": {
        "style_kind": "macos",
        "bg": "#1c1c1e",
        "card": "#2c2c2e",
        "border": "#3a3a3c",
        "input_bg": "#3a3a3c",
        "input_fg": "#f5f5f7",
        "key_fg": "#30d158",
        "name_fg": "#ffd60a",
        "fg": "#f5f5f7",
        "muted": "#98989d",
        "header_fg": "#ffffff",
        "accent": "#0a84ff",
        "accent_fg": "#ffffff",
        "info_fg": "#64d2ff",
        "success": "#30d158",
        "success_fg": "#000000",
        "danger": "#ff453a",
        "danger_fg": "#ffffff",
        "btn_bg": "#3a3a3c",
        "btn_fg": "#f5f5f7",
        "btn_sec_bg": "#48484a",
        "btn_sec_fg": "#ffffff",
        "log_bg": "#141416",
        "log_fg": "#e5e5ea",
        "diag_bg": "#242426",
        "diag_fg": "#ffd60a",
        "progress_trough": "#3a3a3c",
        "progress_bar": "#0a84ff",
        "bar_video": "#30d158",
        "bar_audio": "#ff9f0a",
        "bar_sub": "#64d2ff",
        "bar_mux": "#bf5af2",
        "bar_live": "#ff453a",
        "tree_bg": "#1c1c1e",
        "tree_fg": "#f5f5f7",
        "tree_head_bg": "#2c2c2e",
        "tree_head_fg": "#0a84ff",
        "tree_sel_bg": "#0a84ff",
        "tree_sel_fg": "#ffffff",
        "tab_bg": "#242426",
        "tab_sel_bg": "#2c2c2e",
    },
    "macOS Açık (Apple Light)": {
        "style_kind": "macos",
        "bg": "#f5f5f7",
        "card": "#ffffff",
        "border": "#d1d1d6",
        "input_bg": "#f2f2f7",
        "input_fg": "#1d1d1f",
        "key_fg": "#248a3d",
        "name_fg": "#b25000",
        "fg": "#1d1d1f",
        "muted": "#6e6e73",
        "header_fg": "#1d1d1f",
        "accent": "#007aff",
        "accent_fg": "#ffffff",
        "info_fg": "#007aff",
        "success": "#34c759",
        "success_fg": "#ffffff",
        "danger": "#ff3b30",
        "danger_fg": "#ffffff",
        "btn_bg": "#e5e5ea",
        "btn_fg": "#1d1d1f",
        "btn_sec_bg": "#d1d1d6",
        "btn_sec_fg": "#1d1d1f",
        "log_bg": "#fafafa",
        "log_fg": "#1d1d1f",
        "diag_bg": "#fffaf0",
        "diag_fg": "#8a4b00",
        "progress_trough": "#e5e5ea",
        "progress_bar": "#007aff",
        "bar_video": "#34c759",
        "bar_audio": "#ff9500",
        "bar_sub": "#007aff",
        "bar_mux": "#af52de",
        "bar_live": "#ff3b30",
        "tree_bg": "#ffffff",
        "tree_fg": "#1d1d1f",
        "tree_head_bg": "#f2f2f7",
        "tree_head_fg": "#007aff",
        "tree_sel_bg": "#007aff",
        "tree_sel_fg": "#ffffff",
        "tab_bg": "#e5e5ea",
        "tab_sel_bg": "#ffffff",
    },
}


# ============================================================================
# YARDIMCI FONKSİYONLAR (GİRDİ TEMİZLEME, PLATFORM, GEÇMİŞ & HATA ÇÖZÜMLEME)
# ============================================================================
def ayikla_url_ve_anahtarlar(ham_metin: str):
    """
    Kullanıcı eklentiden tüm komutu veya sadece linki yapıştırdığında:
    1) İçindeki .mpd / .m3u8 linkini (veya genel http linkini) bulur.
    2) Eğer metin içinde KID:KEY varsa onları da otomatik ayıklar.
    """
    if not ham_metin:
        return "", []

    metin = ham_metin.strip()

    mpd_m3u8_match = re.search(
        r'(https?://[^\s"\'<>]+?\.(?:mpd|m3u8)[^\s"\'<>]*)',
        metin,
        re.IGNORECASE,
    )
    if mpd_m3u8_match:
        url = mpd_m3u8_match.group(1)
    else:
        tum_urller = re.findall(r'(https?://[^\s"\'<>]+)', metin, re.IGNORECASE)
        referer_roots = {
            "https://beinconnect.com.tr",
            "https://www.beinconnect.com.tr",
            "https://www.beinconnect.com.tr/",
            "https://todtv.com.tr",
            "https://www.todtv.com.tr",
            "https://tivibu.com.tr",
            "https://www.tivibu.com.tr",
            "https://tvplus.com.tr",
            "https://www.tvplus.com.tr",
            "https://www.filbox.com.tr",
            "https://www.disneyplus.com",
            "https://www.dsmartgo.com.tr",
            "https://tvheryerde.com",
            "https://tv.apple.com",
            "https://play.max.com",
        }
        secilen = ""
        for u in tum_urller:
            u_clean = u.rstrip(".,;\"')")
            if u_clean.lower() not in referer_roots:
                secilen = u_clean
                break
        url = secilen

    bulunan_keyler = re.findall(r"([a-fA-F0-9]{32}:[a-fA-F0-9]{32})", metin)
    return url, bulunan_keyler


def anahtarlari_ayikla(raw_key_text: str):
    """KEY kutusuna girilen metinden KID:KEY listesini döner."""
    if not raw_key_text:
        return []
    keys = re.findall(r"([a-fA-F0-9]{32}:[a-fA-F0-9]{32})", raw_key_text)
    if not keys:
        temiz = raw_key_text.strip().strip('"').strip("'")
        if temiz.startswith("--key"):
            temiz = temiz.replace("--key", "").strip()
        if len(temiz) > 30:
            keys = [temiz]
    benzersiz = []
    for k in keys:
        k_lower = k.lower()
        if k_lower not in benzersiz:
            benzersiz.append(k_lower)
    return benzersiz


def platform_ve_header_tespit(link: str, ozel_cdn: str = "Varsayılan ( Değiştirme )"):
    """
    Link yapısından platformu algılar, gerekirse CDN değiştirir,
    dosya adı etiketini (suffix) ve Header setini döner.
    """
    if ozel_cdn == "Fastly CDN (dt-vod-bc-hd-fastly)":
        link = re.sub(
            r"dt-vod-bc-hd(?:-[a-z0-9-]+)?\.(?:dtvcdns\.com|akamaized\.net)",
            "dt-vod-bc-hd-fastly.dtvcdns.com",
            link,
        )
    elif ozel_cdn == "BytePlus CDN (dt-vod-bc-hd-bytpls)":
        link = re.sub(
            r"dt-vod-bc-hd(?:-[a-z0-9-]+)?\.(?:dtvcdns\.com|akamaized\.net)",
            "dt-vod-bc-hd-bytpls.dtvcdns.com",
            link,
        )

    link_lower = link.lower()
    headers = [
        "-H", f"User-Agent: {DEFAULT_UA}",
        "-H", "accept: */*",
        "-H", "accept-language: tr,en-US;q=0.9,en;q=0.8",
    ]

    platform_name = "Genel / Bilinmeyen Platform"
    platform_suffix = ""
    platform_id = "other"

    for p in PLATFORMS:
        if any(kw in link_lower for kw in p["keywords"]):
            platform_name = p["name"]
            platform_suffix = p["suffix"]
            platform_id = p["id"]
            headers.extend([
                "-H", f"Origin: {p['origin']}",
                "-H", f"Referer: {p['referer']}",
            ])
            break

    # 'vod' geçen linkleri (ör. Tivibu 001.vod_hls.zte.com, dt-vod-) yanlışlıkla canlı yayın sanma!
    is_live = ("vod" not in link_lower) and any(
        x in link_lower
        for x in [
            "/live/",
            "live.",
            "live_",
            "-live",
            "live-",
            "livetv",
            "/pltv/",
            ".isml/",
            "manifest_live",
            "channel_live",
        ]
    )
    return link, platform_name, platform_suffix, platform_id, is_live, headers


def hedef_dosya_adi_olustur(raw_name: str, platform_suffix: str) -> str:
    """
    Film adını temizler ve platform etiketini (BEIN, TVPLUS, TIVIBU vb.) sona ekler.
    Örnek: 'Rambo' + 'BEIN' -> 'Rambo BEIN'
    """
    temiz = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", (raw_name or "").strip()).strip()
    if not temiz:
        temiz = "Smart_Indirme_Cikti"

    if platform_suffix:
        suffix_upper = platform_suffix.upper()
        if not temiz.upper().endswith(" " + suffix_upper) and temiz.upper() != suffix_upper:
            temiz = f"{temiz} {suffix_upper}"
    return temiz


def log_temizle_basarili(calisma_klasoru: Path = None):
    """İşlem başarıyla tamamlandığında tüm log kayıtlarını ve gereksiz meta dosyalarını siler."""
    silinen = 0
    try:
        if LOG_DIR.exists():
            for log_f in LOG_DIR.glob("*.log"):
                try:
                    log_f.unlink()
                    silinen += 1
                except Exception:
                    pass
            try:
                if not any(LOG_DIR.iterdir()):
                    LOG_DIR.rmdir()
            except Exception:
                pass
        if calisma_klasoru and calisma_klasoru.exists():
            for meta_f in calisma_klasoru.glob("*.meta.json"):
                try:
                    meta_f.unlink()
                except Exception:
                    pass
    except Exception:
        pass
    return silinen


def ayar_yukle() -> dict:
    try:
        if SETTINGS_FILE.exists():
            return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"theme": "Klasik Koyu (Catppuccin)"}


def ayar_kaydet(data: dict):
    try:
        APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except Exception:
        pass


def gecmis_yukle() -> list:
    try:
        if HISTORY_FILE.exists():
            data = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data[:MAX_HISTORY_ITEMS]
    except Exception:
        pass
    return []


def gecmis_kaydet(items: list):
    try:
        APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text(
            json.dumps(items[:MAX_HISTORY_ITEMS], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def _baslik_ve_bolum_temizle(title: str, page_url: str, fallback_idx: int) -> str:
    """
    WidevineProxy2 JSON kaydındaki 'title' ve sayfa 'url' bilgisinden
    temiz ve ayırt edici film/dizi bölüm adı üretir.
    Örn: title='MobLand - Aksiyon - beIN CONNECT', url='.../2sezon-v1399/song-2-26-eylul'
         -> 'MobLand S02 - Song 2'
    """
    temiz_baslik = (title or "").strip()
    if temiz_baslik:
        # Platform / kategori eklerini temizle (ilk anlamlı parçayı al)
        parcalar = [p.strip() for p in re.split(r"\s*[-|–]\s*", temiz_baslik) if p.strip()]
        if parcalar:
            temiz_baslik = parcalar[0]

    sezon_ek = ""
    bolum_ek = ""
    if page_url:
        try:
            yol = urlparse(page_url).path.strip("/")
            segmentler = [s for s in yol.split("/") if s]
            for seg in segmentler:
                sz_m = re.match(r"^(\d+)[-_]?sezon", seg, re.IGNORECASE)
                if sz_m:
                    sezon_ek = f"S{int(sz_m.group(1)):02d}"
            if segmentler:
                son_seg = segmentler[-1]
                # Sondaki tarih eklerini (ör: -19-eylul, -21-kasim) yumuşakça temizle
                son_seg = re.sub(
                    r"-\d{1,2}-(?:ocak|subat|mart|nisan|mayis|haziran|temmuz|agustos|eylul|ekim|kasim|aralik)$",
                    "",
                    son_seg,
                    flags=re.IGNORECASE,
                )
                son_seg_temiz = son_seg.replace("-", " ").replace("_", " ").strip()
                if son_seg_temiz and son_seg_temiz.lower() != temiz_baslik.lower():
                    bolum_ek = " ".join(w.capitalize() for w in son_seg_temiz.split())
        except Exception:
            pass

    if temiz_baslik:
        if sezon_ek and bolum_ek:
            return f"{temiz_baslik} {sezon_ek} - {bolum_ek}"
        if bolum_ek:
            return f"{temiz_baslik} - {bolum_ek}"
        if sezon_ek:
            return f"{temiz_baslik} {sezon_ek}"
        return temiz_baslik
    if bolum_ek:
        return bolum_ek
    return f"Indirme_{fallback_idx:02d}"


def json_kuyruk_ayikla(json_yolu: Path) -> list:
    """
    WidevineProxy2 JSON dosyasını (pssh -> {keys, manifests, title, url, timestamp})
    veya standart JSON listesini ([{name, url, key}, ...]) okuyup kuyruk listesi döner.
    """
    ham = json.loads(json_yolu.read_text(encoding="utf-8-sig"))
    sonuclar = []

    if isinstance(ham, dict):
        # WidevineProxy2 formatı: dict değerleri içinde 'manifests' veya 'keys' bulunur
        kayitlar = []
        for _, val in ham.items():
            if isinstance(val, dict) and ("manifests" in val or "url" in val):
                kayitlar.append(val)
        # Yakalanma sırasına göre sırala (Bölüm 1 -> Bölüm N)
        kayitlar.sort(key=lambda x: x.get("timestamp", 0))

        for idx, item in enumerate(kayitlar, start=1):
            manifests = item.get("manifests") or []
            manifest_url = ""
            if isinstance(manifests, list) and manifests:
                # En güncel manifesti al
                manifests_sorted = sorted(
                    [m for m in manifests if isinstance(m, dict) and m.get("url")],
                    key=lambda m: m.get("timestamp", 0),
                )
                if manifests_sorted:
                    manifest_url = manifests_sorted[-1].get("url", "").strip()
            if not manifest_url:
                u = item.get("manifest_url") or item.get("mpd") or ""
                manifest_url = u.strip()
            if not manifest_url:
                continue

            key_list = []
            raw_keys = item.get("keys") or []
            if isinstance(raw_keys, list):
                for ko in raw_keys:
                    if isinstance(ko, dict) and ko.get("kid") and ko.get("k"):
                        key_list.append(f"{ko['kid']}:{ko['k']}".lower())
                    elif isinstance(ko, str) and ":" in ko:
                        key_list.append(ko.strip().lower())
            elif isinstance(raw_keys, str):
                key_list.extend(anahtarlari_ayikla(raw_keys))

            ad = _baslik_ve_bolum_temizle(item.get("title", ""), item.get("url", ""), idx)
            _, _, suffix, _, is_live, _ = platform_ve_header_tespit(manifest_url)
            sonuclar.append({
                "name": ad,
                "url": manifest_url,
                "key": " ".join(dict.fromkeys(key_list)),
                "platform": suffix or "GENEL",
                "is_live": is_live,
                "status": "⏳ Bekliyor",
            })

    elif isinstance(ham, list):
        # Standart liste formatı: [{"name": "...", "url": "...", "key": "..."}, ...]
        for idx, item in enumerate(ham, start=1):
            if not isinstance(item, dict):
                continue
            manifest_url = (
                item.get("url")
                or item.get("mpd")
                or item.get("manifest")
                or item.get("link")
                or ""
            ).strip()
            if not manifest_url:
                continue
            ad = (item.get("name") or item.get("title") or f"Indirme_{idx:02d}").strip()
            raw_key = item.get("key") or item.get("keys") or ""
            if isinstance(raw_key, list):
                key_str = " ".join(
                    f"{k['kid']}:{k['k']}" if isinstance(k, dict) and "kid" in k and "k" in k else str(k)
                    for k in raw_key
                )
            else:
                key_str = str(raw_key).strip()
            _, _, suffix, _, is_live, _ = platform_ve_header_tespit(manifest_url)
            sonuclar.append({
                "name": ad,
                "url": manifest_url,
                "key": key_str,
                "platform": suffix or "GENEL",
                "is_live": is_live,
                "status": "⏳ Bekliyor",
            })

    return sonuclar


def hata_analiz_et(
    cikti_metni: str,
    return_code: int,
    link: str,
    secilen_format: str,
    log_dosyasi: Path = None,
):
    """
    N_m3u8DL-RE çıktısını ve log dosyasını inceleyerek hatanın tam sebebini
    ve Türkçe çözüm önerisini üretir.
    """
    log_icerik = ""
    try:
        if log_dosyasi and log_dosyasi.exists():
            log_icerik = log_dosyasi.read_text(encoding="utf-8", errors="ignore")
        elif LOG_DIR.exists():
            log_dosyalari = sorted(
                LOG_DIR.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True
            )
            if log_dosyalari:
                son_log = log_dosyalari[0]
                if (datetime.datetime.now().timestamp() - son_log.stat().st_mtime) < 180:
                    log_icerik = son_log.read_text(encoding="utf-8", errors="ignore")
                    log_dosyasi = son_log
    except Exception:
        pass

    birlesik = (cikti_metni + "\n" + log_icerik).lower()
    cozumler = []

    if "responseended" in birlesik or "the response ended prematurely" in birlesik:
        cozumler.append(
            "🔴 HATA KODU: ResponseEnded (Sunucu Bağlantıyı Erken Kesti)\n"
            "• SEBEBİ: İndirmeye çalıştığınız yayın çok büyük olduğu için CDN bağlantıyı erken kesti.\n"
            "• ÇÖZÜM 1: 'CDN Sunucusu' seçeneğini 'Fastly CDN' yapıp tekrar başlatın.\n"
            "• ÇÖZÜM 2: 1080p yerine 720p seçin veya tarayıcıdan yeni bir MPD linki kopyalayın."
        )
    elif "download first segment failed" in birlesik:
        cozumler.append(
            "🔴 HATA KODU: İlk Segment İndirilemedi (Download first segment failed)\n"
            "• SEBEBİ: Manifest okundu ancak medya segmentine erişilemedi (token süresi dolmuş veya IP değişmiş olabilir).\n"
            "• ÇÖZÜM: 'CDN Sunucusu'nu Fastly CDN'e çevirin veya tarayıcıdan taze link alıp tekrar deneyin."
        )

    if "403 (forbidden)" in birlesik or "status code: 403" in birlesik or "403 forbidden" in birlesik:
        cozumler.append(
            "🔴 HATA KODU: HTTP 403 Forbidden (Erişim Reddedildi)\n"
            "• SEBEBİ: CDN sunucusu güvenlik anahtarını (token/hmac) veya Referer başlığını reddetti.\n"
            "• ÇÖZÜM: Linkin süresi dolmuş olabilir. Tarayıcıda sayfayı yenileyip yeni MPD linkini yapıştırın."
        )

    if "404 (not found)" in birlesik or "status code: 404" in birlesik:
        cozumler.append(
            "🔴 HATA KODU: HTTP 404 Not Found (Dosya Bulunamadı)\n"
            "• SEBEBİ: Manifest linki veya segment yolu sunucuda mevcut değil.\n"
            "• ÇÖZÜM: Linkin eksiksiz kopyalandığından emin olun."
        )

    if "not valid" in birlesik and "format=" in birlesik:
        cozumler.append(
            f"🔴 HATA KODU: '{secilen_format}' Birleştirme Formatı Geçersiz\n"
            "• ÇÖZÜM: Sadece ses indirirken 'M4A (Sadece Ses)', video+ses için 'MKV' seçin."
        )

    if "decrypt" in birlesik and ("error" in birlesik or "failed" in birlesik):
        cozumler.append(
            "🔴 HATA KODU: Şifre Çözme (Decryption) Hatası\n"
            "• SEBEBİ: Girilen KID:KEY anahtarı yanlış, eksik veya mp4decrypt.exe çalışamadı.\n"
            "• ÇÖZÜM: KEY kutusuna 32 haneli KID:KEY çiftini doğru girdiğinizden emin olun."
        )
    elif "cenc" in birlesik and "kid:" in birlesik and "--key" not in birlesik:
        kid_eslesme = re.search(r"kid:\s*([a-f0-9]{32})", birlesik)
        kid_bilgi = f" (Algılanan KID: {kid_eslesme.group(1)})" if kid_eslesme else ""
        cozumler.append(
            f"⚠️ UYARI: Yayın DRM (CENC) Şifreli{kid_bilgi} Ancak KEY Girilmedi!\n"
            "• ÇÖZÜM: 2. kutuya KID:KEY şifre çözme anahtarını girip tekrar indirin."
        )

    if "no streams selected" in birlesik or "nothing to download" in birlesik:
        cozumler.append(
            "🔴 HATA KODU: Seçilen Kriterlere Uygun Akış Bulunamadı!\n"
            "• SEBEBİ: Yayında seçtiğiniz dilde (ör. 'tr') ses/altyazı etiketi bulunmuyor olabilir.\n"
            "• ÇÖZÜM: Ses dilini 'Türkçe + Tanımsız (tr/und)' veya 'Tüm Ses Dilleri' yapıp deneyin."
        )

    if not cozumler:
        if return_code == 0:
            return "✅ İŞLEM BAŞARILI: Dosyanız seçili indirme klasörüne kaydedildi ve gereksiz loglar temizlendi."
        else:
            log_not = f"\n• Hata Log Dosyası: {log_dosyasi}" if (log_dosyasi and log_dosyasi.exists()) else ""
            return (
                f"⚠️ BİLİNMEYEN HATA (Çıkış Kodu: {return_code}){log_not}\n"
                "• Lütfen işlem günlüğünün son satırlarını veya log dosyasını kontrol edin."
            )

    if return_code != 0 and log_dosyasi and log_dosyasi.exists():
        cozumler.append(f"📄 Hata incelemesi için log korundu: {log_dosyasi}")

    return "\n\n".join(cozumler)


def sure_metnini_saniyeye_cevir(sure_str: str) -> int:
    """'01m30s' veya '01h02m10s' biçimindeki süreyi saniyeye çevirir."""
    m = re.match(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$", sure_str.strip())
    if not m:
        return 0
    saat = int(m.group(1) or 0)
    dk = int(m.group(2) or 0)
    sn = int(m.group(3) or 0)
    return saat * 3600 + dk * 60 + sn


def canli_spam_satiri_mi(temiz_satir: str) -> bool:
    """Canlı yayın ve VOD ilerleme barı tekrar satırlarını günlük kutusundan filtreler."""
    s = temiz_satir.strip()
    if not s:
        return True
    # INFO / WARN / ERROR / EXTRA log satırlarını ASLA gizleme
    if re.match(r"^\d{2}:\d{2}:\d{2}\.\d{3}\s*(?:INFO|WARN|ERROR|EXTRA)\s*:", s):
        return False
    # yt-dlp ilerleme satırları (günlüğü doldurmasın, üst barı güncellesin)
    if s.startswith("[download]") and "%" in s and ("at " in s or "ETA" in s or "of " in s):
        return True
    # N_m3u8DL-RE boş/çizgili ilerleme satırları (ör: '0/100 0.00% - - --:--:--', '---')
    if "------" in s or "--:--:--" in s or "0/100 0.00%" in s:
        return True
    # VOD ilerleme barı satırları
    if re.search(r"\d+(?:\.\d+)?%", s) and re.search(
        r"(?:MBps|KBps|Bps|MB/s|KB/s|━|─|\[#|Waiting|Recording)", s, re.IGNORECASE
    ):
        return True
    # Sadece yüzde / tire / bekleme / kayıt parçacıkları
    if re.match(r"^(?:-|100%|0%|\d+(?:\.\d+)?%\s*-?)$", s):
        return True
    if any(k in s for k in ("Waiting", "Recording", "0.00Bps(")):
        return True
    if re.match(r"^-?(?:Vid|Aud|Sub)\s+", s) and ("Kbps" in s or "stpp" in s or "m0" in s):
        return True
    if re.match(r"^(?:tur|tr|en|eng)\s*\|\s*stpp", s, re.IGNORECASE):
        return True
    if re.match(r"^\d+(?:\.\d+)?(?:KBps|MBps|Bps)$", s, re.IGNORECASE):
        return True
    return False


def ilerleme_satiri_cozumle(temiz_satir: str, canli_limit_sn: int = 0):
    """
    N_m3u8DL-RE çıktı satırından yüzde, hız, boyut, parça sayısı, kalan süre
    ve bar renk aşamasını (video/audio/sub/mux/live) ayıklar.
    """
    bilgi = {}
    low = temiz_satir.lower()

    # yt-dlp ilerleme satırı desteği:
    # Örn: [download]  42.3% of  150.25MiB at   12.40MiB/s ETA 00:08
    if low.startswith("[download]"):
        if "destination:" in low:
            if any(ext in low for ext in (".m4a", ".opus", ".webm.part", ".mp3", ".aac")) and "f140" in low or low.endswith((".m4a", ".aac", ".opus", ".mp3")):
                bilgi["stage"] = "🎵 İndiriliyor: Ses Akışı (yt-dlp)"
                bilgi["bar_kind"] = "audio"
                bilgi["reset_bar"] = True
            else:
                bilgi["stage"] = "⬇ İndiriliyor: Video Akışı (yt-dlp)"
                bilgi["bar_kind"] = "video"
                bilgi["reset_bar"] = True
        y_m = re.search(r"(\d{1,3}(?:\.\d+)?)%", temiz_satir)
        if y_m:
            bilgi["percent"] = min(100.0, float(y_m.group(1)))
        b_m = re.search(r"of\s+~?\s*([\d.]+\s*[KMG]?i?B)", temiz_satir, re.IGNORECASE)
        if b_m:
            bilgi["size"] = b_m.group(1)
        h_m = re.search(r"at\s+([\d.]+\s*[KMG]?i?B/s)", temiz_satir, re.IGNORECASE)
        if h_m:
            bilgi["speed"] = h_m.group(1)
        e_m = re.search(r"ETA\s+(\d{2}:\d{2}(?::\d{2})?)", temiz_satir, re.IGNORECASE)
        if e_m:
            bilgi["eta"] = e_m.group(1)
        return bilgi
    if low.startswith("[merger]") or low.startswith("[extractaudio]") or low.startswith("[videoremuxer]"):
        bilgi["stage"] = "🎬 Çıktı Dosyası Birleştiriliyor (FFmpeg)..."
        bilgi["bar_kind"] = "mux"
        bilgi["pulse"] = True
        return bilgi

    # Akış türü / aşama ve bar rengi tespiti
    if "start downloading...vid" in low:
        bilgi["stage"] = "⬇ İndiriliyor: Video Akışı"
        bilgi["bar_kind"] = "video"
        bilgi["reset_bar"] = True
    elif "start downloading...aud" in low:
        bilgi["stage"] = "🎵 İndiriliyor: Ses Akışı"
        bilgi["bar_kind"] = "audio"
        bilgi["reset_bar"] = True
    elif "start downloading...sub" in low:
        bilgi["stage"] = "💬 İndiriliyor: Altyazı"
        bilgi["bar_kind"] = "sub"
        bilgi["reset_bar"] = True
    elif "binary merging" in low:
        bilgi["stage"] = "🧩 Parçalar Birleştiriliyor..."
        bilgi["bar_kind"] = "mux"
        bilgi["pulse"] = True
    elif "decrypting" in low:
        bilgi["stage"] = "🔓 DRM Şifresi Çözülüyor..."
        bilgi["bar_kind"] = "mux"
        bilgi["pulse"] = True
    elif "muxing to" in low:
        bilgi["stage"] = "🎬 Çıktı Dosyası Birleştiriliyor (Muxing)..."
        bilgi["bar_kind"] = "mux"
        bilgi["pulse"] = True

    # Canlı yayın ilerleme tespiti (ör: 01m55s/01m55s 16/16 Waiting veya Recording)
    if "waiting" in low or "recording" in low:
        bilgi["bar_kind"] = "live"
        sure_m = re.search(r"(\d{2}m\d{2}s|\d{2}h\d{2}m\d{2}s)\s*/\s*(\d{2}m\d{2}s|\d{2}h\d{2}m\d{2}s)", temiz_satir)
        if sure_m:
            kayit_str = sure_m.group(1)
            kayit_sn = sure_metnini_saniyeye_cevir(kayit_str)
            if canli_limit_sn > 0:
                hedef_dk = canli_limit_sn // 60
                hedef_sn = canli_limit_sn % 60
                hedef_str = f"{hedef_dk:02d}m{hedef_sn:02d}s"
                yuzde = min(100.0, (kayit_sn / canli_limit_sn) * 100.0)
                bilgi["percent"] = yuzde
                bilgi["stage"] = f"🔴 Canlı Yayın Kaydediliyor: {kayit_str} / {hedef_str}"
                kalan = max(0, canli_limit_sn - kayit_sn)
                bilgi["eta"] = f"{kalan // 3600:02d}:{(kalan % 3600) // 60:02d}:{kalan % 60:02d}"
            else:
                bilgi["stage"] = f"🔴 Canlı Yayın Kaydediliyor: {kayit_str}"
        parca_m = re.search(r"\b(\d+/\d+)\b", temiz_satir)
        if parca_m:
            bilgi["segments"] = parca_m.group(1)
        hiz_eslesmeler = re.findall(
            r"(\d+(?:\.\d+)?\s*(?:GBps|MBps|KBps|Bps|GB/s|MB/s|KB/s|B/s))",
            temiz_satir,
        )
        if hiz_eslesmeler:
            bilgi["speed"] = hiz_eslesmeler[-1].replace("ps", "/s")
        return bilgi

    yuzde_m = re.search(r"(\d{1,3}(?:\.\d+)?)%", temiz_satir)
    if yuzde_m:
        val = float(yuzde_m.group(1))
        if 0.0 <= val <= 100.0:
            bilgi["percent"] = val

    hiz_eslesmeler = re.findall(
        r"(\d+(?:\.\d+)?\s*(?:GBps|MBps|KBps|Bps|GB/s|MB/s|KB/s|B/s))",
        temiz_satir,
    )
    if hiz_eslesmeler:
        bilgi["speed"] = hiz_eslesmeler[-1].replace("ps", "/s")

    boyut_m = re.search(
        r"(\d+(?:\.\d+)?\s*(?:GB|MB|KB|B)\s*/\s*\d+(?:\.\d+)?\s*(?:GB|MB|KB|B))",
        temiz_satir,
        re.IGNORECASE,
    )
    if boyut_m:
        bilgi["size"] = boyut_m.group(1)

    parca_m = re.search(r"\b(\d+/\d+)\b", temiz_satir)
    if parca_m:
        bilgi["segments"] = parca_m.group(1)

    eta_m = re.search(r"\b(\d{2}:\d{2}:\d{2})\b", temiz_satir)
    if eta_m and not re.match(r"^\d{2}:\d{2}:\d{2}\.\d+", temiz_satir.strip()):
        bilgi["eta"] = eta_m.group(1)

    return bilgi


# ============================================================================
# ANA GÖRSEL ARAYÜZ (GUI) SINIFI
# ============================================================================
class IndiriciProApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        mod_etiket = " (Portable)" if IS_PORTABLE else ""
        self.root.title(f"İndirici Pro v{APP_VERSION}{mod_etiket}")
        self.root.geometry("1060x850")
        self.root.minsize(960, 760)

        ico = ikon_bul()
        if ico:
            try:
                self.root.iconbitmap(str(ico))
            except Exception:
                pass

        self.aktif_islem: subprocess.Popen = None
        self.calisiyor = False
        self.kullanici_durdurdu = False
        self.son_ilerleme_zamani = 0.0
        self.kuyruk = []
        self.kuyruk_calisiyor = False
        self.aktif_kuyruk_idx = -1

        self.ayarlar = ayar_yukle()
        kayitli_tema = self.ayarlar.get("theme", "Klasik Koyu (Catppuccin)")
        if kayitli_tema not in THEMES:
            kayitli_tema = "Klasik Koyu (Catppuccin)"
        self.aktif_tema_adi = kayitli_tema

        kayitli_klasor = self.ayarlar.get("download_dir", "")
        self.download_dir = Path(kayitli_klasor) if kayitli_klasor else DEFAULT_DOWNLOAD_DIR
        self.temp_work_dir = self.download_dir / "_temp"

        self.gecmis = gecmis_yukle()

        # Tema güncellendiğinde renkleri yenilenecek tk widget referansları
        self._tk_entries = []
        self._tk_primary_btns = []
        self._tk_sec_btns = []
        self._tk_accent_btns = []
        self._tk_cards = []
        self._mac_dots_frame = None

        self._arayuz_olustur()
        self.temayi_uygula(self.aktif_tema_adi, kaydet=False)
        self._gecmis_tablosunu_yenile()
        self._ortam_kontrol()
        self._chrome_koprusunu_baslat()

    # ------------------------------------------------------------------------
    # ARAYÜZ OLUŞTURMA
    # ------------------------------------------------------------------------
    def _arayuz_olustur(self):
        # ÜST BAŞLIK ÇUBUĞU
        self.ust_frame = ttk.Frame(self.root)
        self.ust_frame.pack(fill="x", padx=14, pady=(10, 6))

        # macOS Trafik Işıkları (Sadece macOS temalarında görünür)
        self._mac_dots_frame = tk.Frame(self.ust_frame)
        for dot_color in ("#ff5f56", "#ffbd2e", "#27c93f"):
            tk.Label(
                self._mac_dots_frame,
                text="●",
                fg=dot_color,
                font=("Segoe UI", 12),
                padx=2,
            ).pack(side="left")

        self.baslik_lbl = ttk.Label(
            self.ust_frame,
            text="🎬 İNDİRİCİ PRO — MULTI-PLATFORM STREAM İNDİRİCİ",
            style="Header.TLabel",
        )
        self.baslik_lbl.pack(side="left", padx=(4, 10))

        # Sağ üst kontroller: Tema seçici + JSON + Geçmiş + Klasör Seç + Klasör Aç
        self.klasor_btn = tk.Button(
            self.ust_frame,
            text="📂 İndirilenler",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=9,
            pady=4,
            cursor="hand2",
            command=self.klasoru_ac,
        )
        self.klasor_btn.pack(side="right", padx=(4, 0))
        self._tk_primary_btns.append(self.klasor_btn)

        self.klasor_sec_btn = tk.Button(
            self.ust_frame,
            text="📁 Klasör Seç",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=9,
            pady=4,
            cursor="hand2",
            command=self.klasor_sec,
        )
        self.klasor_sec_btn.pack(side="right", padx=4)
        self._tk_primary_btns.append(self.klasor_sec_btn)

        self.gecmis_hizli_btn = tk.Button(
            self.ust_frame,
            text=f"📜 Geçmiş ({len(self.gecmis)})",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=10,
            pady=4,
            cursor="hand2",
            command=self.gecmis_sekmesini_ac,
        )
        self.gecmis_hizli_btn.pack(side="right", padx=4)
        self._tk_primary_btns.append(self.gecmis_hizli_btn)

        self.json_hizli_btn = tk.Button(
            self.ust_frame,
            text="📂 JSON Ekle",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=10,
            pady=4,
            cursor="hand2",
            command=self.json_dosyasi_ekle,
        )
        self.json_hizli_btn.pack(side="right", padx=4)
        self._tk_accent_btns.append(self.json_hizli_btn)

        self.tema_var = tk.StringVar(value=self.aktif_tema_adi)
        self.tema_combo = ttk.Combobox(
            self.ust_frame,
            textvariable=self.tema_var,
            state="readonly",
            width=24,
            values=list(THEMES.keys()),
        )
        self.tema_combo.pack(side="right", padx=(4, 6))
        self.tema_combo.bind("<<ComboboxSelected>>", self._tema_secildi)

        self.tema_lbl = ttk.Label(self.ust_frame, text="🎨 Tema:", style="SubHeader.TLabel")
        self.tema_lbl.pack(side="right", padx=(0, 2))

        # --------------------------------------------------------------------
        # 1. BÖLÜM: YAYIN BİLGİLERİ
        # --------------------------------------------------------------------
        girdi_frame = ttk.LabelFrame(self.root, text=" 1. Yayın Bilgileri (Link / Key / Dosya Adı) ")
        girdi_frame.pack(fill="x", padx=14, pady=4, ipady=4)

        # Satır 1: URL
        ttk.Label(girdi_frame, text="Manifest (MPD/M3U8) veya Eklenti Komutu:").grid(
            row=0, column=0, sticky="w", padx=10, pady=(6, 3)
        )
        self.url_var = tk.StringVar()
        self.url_var.trace_add("write", self._url_veya_isim_degisti)
        self.url_entry = tk.Entry(
            girdi_frame,
            textvariable=self.url_var,
            font=("Consolas", 9),
            relief="flat",
        )
        self.url_entry.grid(row=0, column=1, sticky="ew", padx=6, pady=(6, 3), ipady=5)
        self._tk_entries.append((self.url_entry, "input_fg"))

        url_btn_frame = ttk.Frame(girdi_frame, style="Card.TFrame")
        url_btn_frame.grid(row=0, column=2, padx=8, pady=(6, 3))

        btn_yapistir = tk.Button(
            url_btn_frame,
            text="📋 Yapıştır",
            font=("Segoe UI", 8, "bold"),
            relief="flat",
            padx=9,
            pady=4,
            cursor="hand2",
            command=self.url_yapistir,
        )
        btn_yapistir.pack(side="left", padx=2)
        self._tk_sec_btns.append(btn_yapistir)

        btn_analiz = tk.Button(
            url_btn_frame,
            text="🔍 Akışları Analiz Et",
            font=("Segoe UI", 8, "bold"),
            relief="flat",
            padx=9,
            pady=4,
            cursor="hand2",
            command=self.manifest_analiz_et,
        )
        btn_analiz.pack(side="left", padx=2)
        self._tk_accent_btns.append(btn_analiz)

        # Satır 2: KEY
        ttk.Label(girdi_frame, text="Şifre Çözme Anahtarı (KID:KEY - Çoklu Olabilir):").grid(
            row=1, column=0, sticky="w", padx=10, pady=3
        )
        self.key_var = tk.StringVar()
        self.key_entry = tk.Entry(
            girdi_frame,
            textvariable=self.key_var,
            font=("Consolas", 9),
            relief="flat",
        )
        self.key_entry.grid(row=1, column=1, sticky="ew", padx=6, pady=3, ipady=5)
        self._tk_entries.append((self.key_entry, "key_fg"))

        btn_key_yap = tk.Button(
            girdi_frame,
            text="📋 Key Yapıştır",
            font=("Segoe UI", 8, "bold"),
            relief="flat",
            padx=9,
            pady=4,
            cursor="hand2",
            command=self.key_yapistir,
        )
        btn_key_yap.grid(row=1, column=2, padx=8, pady=3, sticky="ew")
        self._tk_sec_btns.append(btn_key_yap)

        # Satır 3: Dosya Adı + Algılanan Platform & Çıktı Adı Önizleme
        ttk.Label(girdi_frame, text="Film / Dosya Adı (Örn: Rambo):").grid(
            row=2, column=0, sticky="w", padx=10, pady=(3, 6)
        )

        isim_alt_frame = ttk.Frame(girdi_frame, style="Card.TFrame")
        isim_alt_frame.grid(row=2, column=1, sticky="ew", padx=6, pady=(3, 6))

        self.name_var = tk.StringVar(value="")
        self.name_var.trace_add("write", self._url_veya_isim_degisti)
        self.name_entry = tk.Entry(
            isim_alt_frame,
            textvariable=self.name_var,
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            width=26,
        )
        self.name_entry.pack(side="left", fill="x", expand=True, ipady=5)
        self._tk_entries.append((self.name_entry, "name_fg"))

        self.platform_bilgi_lbl = ttk.Label(
            isim_alt_frame,
            text="Platform: Bekleniyor...",
            style="Info.TLabel",
        )
        self.platform_bilgi_lbl.pack(side="right", padx=(10, 4))

        btn_temizle = tk.Button(
            girdi_frame,
            text="🧹 Temizle",
            font=("Segoe UI", 8, "bold"),
            relief="flat",
            padx=9,
            pady=4,
            cursor="hand2",
            command=self.formu_temizle,
        )
        btn_temizle.grid(row=2, column=2, padx=8, pady=(3, 6), sticky="ew")
        self._tk_primary_btns.append(btn_temizle)

        # Satır 4: Canlı Çıktı Dosya Adı Önizleme
        self.cikti_onizleme_lbl = ttk.Label(
            girdi_frame,
            text="📁 Kaydedilecek Dosya: Smart_Indirme_Cikti.mkv",
            style="Muted.TLabel",
        )
        self.cikti_onizleme_lbl.grid(row=3, column=1, columnspan=2, sticky="w", padx=6, pady=(0, 4))

        girdi_frame.columnconfigure(1, weight=1)

        # --------------------------------------------------------------------
        # 2. BÖLÜM: İNDİRME MODU VE FORMAT SEÇİMİ
        # --------------------------------------------------------------------
        secim_frame = ttk.LabelFrame(
            self.root, text=" 2. İndirme Modu ve Format Seçimi (Video+Ses = MKV | Sadece Ses = M4A) "
        )
        secim_frame.pack(fill="x", padx=14, pady=4, ipady=4)

        self.preset_var = tk.StringVar(value="1")
        preset_bar = ttk.Frame(secim_frame, style="Card.TFrame")
        preset_bar.pack(fill="x", padx=10, pady=(6, 4))

        presets = [
            ("1. En İyi Video + TR Ses (.mkv)", "1"),
            ("2. Sadece TR Ses (.m4a)", "2"),
            ("3. Sadece Altyazı (.srt)", "3"),
            ("4. Tümünü İndir (.mkv)", "4"),
            ("5. Özel / Manuel", "5"),
        ]
        for text, val in presets:
            ttk.Radiobutton(
                preset_bar,
                text=text,
                variable=self.preset_var,
                value=val,
                command=self._preset_degisti,
            ).pack(side="left", padx=(0, 14))

        detay_grid = ttk.Frame(secim_frame, style="Card.TFrame")
        detay_grid.pack(fill="x", padx=10, pady=4)

        ttk.Label(detay_grid, text="Görüntü:").grid(row=0, column=0, sticky="w", padx=(0, 4), pady=3)
        self.video_secim = ttk.Combobox(
            detay_grid,
            state="readonly",
            width=23,
            values=[
                "En İyi Kalite (Otomatik)",
                "1080p (Full HD)",
                "720p (HD)",
                "480p / 432p (SD)",
                "360p / 270p (Düşük)",
                "Video İndirme (Kapalı)",
            ],
        )
        self.video_secim.current(0)
        self.video_secim.grid(row=0, column=1, sticky="w", padx=(0, 14), pady=3)
        self.video_secim.bind("<<ComboboxSelected>>", self._format_otomatik_ayarla)

        ttk.Label(detay_grid, text="Ses Dili:").grid(row=0, column=2, sticky="w", padx=(0, 4), pady=3)
        self.ses_secim = ttk.Combobox(
            detay_grid,
            state="readonly",
            width=25,
            values=[
                "Sadece Türkçe (tr/tur)",
                "Türkçe + Tanımsız (tr/und)",
                "Sadece İngilizce (en/eng)",
                "Türkçe ve İngilizce (tr/en)",
                "Tüm Ses Dilleri (Hepsi)",
                "En İyi Tek Ses (Otomatik)",
                "Ses İndirme (Kapalı)",
            ],
        )
        self.ses_secim.current(0)
        self.ses_secim.grid(row=0, column=3, sticky="w", padx=(0, 14), pady=3)
        self.ses_secim.bind("<<ComboboxSelected>>", self._format_otomatik_ayarla)

        ttk.Label(detay_grid, text="Altyazı:").grid(row=0, column=4, sticky="w", padx=(0, 4), pady=3)
        self.altyazi_secim = ttk.Combobox(
            detay_grid,
            state="readonly",
            width=22,
            values=[
                "Sadece Türkçe (tr/tur)",
                "Tüm Altyazılar (tr/en/vb.)",
                "Sadece İngilizce (en)",
                "Altyazı İndirme (Kapalı)",
            ],
        )
        self.altyazi_secim.current(0)
        self.altyazi_secim.grid(row=0, column=5, sticky="w", pady=3)

        ttk.Label(detay_grid, text="Çıktı Formatı:").grid(row=1, column=0, sticky="w", padx=(0, 4), pady=4)
        self.format_secim = ttk.Combobox(
            detay_grid,
            state="readonly",
            width=23,
            values=[
                "MKV (Video+Ses+Altyazı)",
                "M4A (Sadece Ses)",
                "MP4 (Video+Ses)",
                "Otomatik / Ham (.srt / .m4a)",
                "TS (Canlı Yayın Kaydı)",
            ],
        )
        self.format_secim.current(0)
        self.format_secim.grid(row=1, column=1, sticky="w", padx=(0, 14), pady=4)
        self.format_secim.bind("<<ComboboxSelected>>", lambda *_: self._url_veya_isim_degisti())

        ttk.Label(detay_grid, text="CDN Sunucusu:").grid(row=1, column=2, sticky="w", padx=(0, 4), pady=4)
        self.cdn_secim = ttk.Combobox(
            detay_grid,
            state="readonly",
            width=25,
            values=[
                "Varsayılan ( Değiştirme )",
                "Fastly CDN (dt-vod-bc-hd-fastly)",
                "BytePlus CDN (dt-vod-bc-hd-bytpls)",
            ],
        )
        self.cdn_secim.current(0)
        self.cdn_secim.grid(row=1, column=3, sticky="w", padx=(0, 14), pady=4)

        self.canli_mod_var = tk.BooleanVar(value=False)
        self.canli_chk = ttk.Checkbutton(
            detay_grid,
            text="Canlı (Dk):",
            variable=self.canli_mod_var,
        )
        self.canli_chk.grid(row=1, column=4, sticky="w", padx=(0, 4), pady=4)
        self.canli_dk_var = tk.StringVar(value="5")
        self.canli_entry = tk.Entry(
            detay_grid,
            textvariable=self.canli_dk_var,
            font=("Segoe UI", 9),
            relief="flat",
            width=10,
        )
        self.canli_entry.grid(row=1, column=5, sticky="w", pady=4, ipady=3)
        self._tk_entries.append((self.canli_entry, "input_fg"))

        # --------------------------------------------------------------------
        # 3. BÖLÜM: BAŞLAT / DURDUR BUTONLARI
        # --------------------------------------------------------------------
        aksiyon_frame = ttk.Frame(self.root)
        aksiyon_frame.pack(fill="x", padx=14, pady=4)

        self.baslat_btn = tk.Button(
            aksiyon_frame,
            text="🚀 İNDİRMEYİ BAŞLAT",
            font=("Segoe UI", 11, "bold"),
            relief="flat",
            padx=20,
            pady=7,
            cursor="hand2",
            command=self.indirmeyi_baslat,
        )
        self.baslat_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.durdur_btn = tk.Button(
            aksiyon_frame,
            text="⏹ İŞLEMİ DURDUR",
            font=("Segoe UI", 10, "bold"),
            relief="flat",
            padx=16,
            pady=7,
            cursor="hand2",
            state="disabled",
            command=self.islemi_durdur,
        )
        self.durdur_btn.pack(side="right")

        # --------------------------------------------------------------------
        # 4. BÖLÜM: CANLI İNDİRME İLERLEME ÇUBUĞU VE HIZ GÖSTERGESİ
        # --------------------------------------------------------------------
        prog_frame = ttk.LabelFrame(self.root, text=" 3. İndirme İlerlemesi ve Hız Göstergesi ")
        prog_frame.pack(fill="x", padx=14, pady=4, ipady=4)

        prog_ust = ttk.Frame(prog_frame, style="Card.TFrame")
        prog_ust.pack(fill="x", padx=10, pady=(4, 2))

        self.asama_lbl = ttk.Label(prog_ust, text="⏸ Hazır — İndirme bekleniyor", style="Info.TLabel")
        self.asama_lbl.pack(side="left")

        self.yuzde_lbl = ttk.Label(prog_ust, text="% 0.0", style="Percent.TLabel")
        self.yuzde_lbl.pack(side="right")

        self.progress_var = tk.DoubleVar(value=0.0)
        self.progress_bar = ttk.Progressbar(
            prog_frame,
            orient="horizontal",
            mode="determinate",
            maximum=100.0,
            variable=self.progress_var,
            style="Download.Horizontal.TProgressbar",
        )
        self.progress_bar.pack(fill="x", padx=10, pady=4)

        prog_alt = ttk.Frame(prog_frame, style="Card.TFrame")
        prog_alt.pack(fill="x", padx=10, pady=(2, 4))

        self.hiz_lbl = ttk.Label(prog_alt, text="⚡ Hız: --", style="Metric.TLabel")
        self.hiz_lbl.pack(side="left", padx=(0, 24))

        self.boyut_lbl = ttk.Label(prog_alt, text="📦 Boyut: --", style="Metric.TLabel")
        self.boyut_lbl.pack(side="left", padx=(0, 24))

        self.parca_lbl = ttk.Label(prog_alt, text="🧩 Parça: --", style="Metric.TLabel")
        self.parca_lbl.pack(side="left", padx=(0, 24))

        self.eta_lbl = ttk.Label(prog_alt, text="⏱ Kalan Süre: --", style="Metric.TLabel")
        self.eta_lbl.pack(side="right")

        # --------------------------------------------------------------------
        # 5. BÖLÜM: SEKMELİ ALT PANEL (GÜNLÜK & TEŞHİS  |  SON 10 GEÇMİŞ)
        # --------------------------------------------------------------------
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=14, pady=(4, 10))

        # SEKME 1: Canlı Günlük ve Hata Çözümleyici
        self.tab_log = ttk.Frame(self.notebook, style="Card.TFrame")
        self.notebook.add(self.tab_log, text="  📟 Canlı İndirme Günlüğü & Hata Teşhisi  ")

        log_box = ttk.Frame(self.tab_log, style="Card.TFrame")
        log_box.pack(fill="both", expand=True, padx=6, pady=(6, 4))

        self.log_text = tk.Text(
            log_box,
            font=("Consolas", 9),
            relief="flat",
            height=9,
            wrap="word",
        )
        log_scroll = ttk.Scrollbar(log_box, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_scroll.set)
        log_scroll.pack(side="right", fill="y")
        self.log_text.pack(side="left", fill="both", expand=True)

        self.hata_text = tk.Text(
            self.tab_log,
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            height=5,
            wrap="word",
        )
        self.hata_text.pack(fill="x", padx=6, pady=(2, 6))
        self._hata_yaz(
            "💡 Hazır. Linki yapıştırıp film adını yazdıktan sonra 'İNDİRMEYİ BAŞLAT' butonuna basın.\n"
            "İşlem başarılı olursa log kayıtları otomatik silinir; hata olursa log korunur ve çözümü burada gösterilir."
        )

        # SEKME 2: Son 10 İndirme Geçmişi
        self.tab_history = ttk.Frame(self.notebook, style="Card.TFrame")
        self.notebook.add(self.tab_history, text="  📜 Son 10 İndirme Geçmişi (Tıkla & Tekrar İndir)  ")

        hist_ust = ttk.Frame(self.tab_history, style="Card.TFrame")
        hist_ust.pack(fill="x", padx=8, pady=(8, 4))

        ttk.Label(
            hist_ust,
            text="💡 Bir kayda tıkladığınızda Film Adı, MPD/M3U8 Linki ve KEY otomatik olarak yukarıya doldurulur.",
            style="Muted.TLabel",
        ).pack(side="left")

        btn_hist_sil = tk.Button(
            hist_ust,
            text="🧹 Tümünü Temizle",
            font=("Segoe UI", 8, "bold"),
            relief="flat",
            padx=8,
            pady=3,
            cursor="hand2",
            command=self.gecmisi_temizle,
        )
        btn_hist_sil.pack(side="right", padx=(4, 0))
        self._tk_primary_btns.append(btn_hist_sil)

        btn_hist_tek_sil = tk.Button(
            hist_ust,
            text="🗑 Seçiliyi Sil",
            font=("Segoe UI", 8, "bold"),
            relief="flat",
            padx=8,
            pady=3,
            cursor="hand2",
            command=self.secili_gecmisi_sil,
        )
        btn_hist_tek_sil.pack(side="right", padx=4)
        self._tk_primary_btns.append(btn_hist_tek_sil)

        btn_hist_doldur = tk.Button(
            hist_ust,
            text="📥 Seçili Kaydı Doldur",
            font=("Segoe UI", 8, "bold"),
            relief="flat",
            padx=10,
            pady=3,
            cursor="hand2",
            command=lambda: self._gecmisten_yukle(sekme_degistir=True),
        )
        btn_hist_doldur.pack(side="right", padx=4)
        self._tk_accent_btns.append(btn_hist_doldur)

        tree_frame = ttk.Frame(self.tab_history, style="Card.TFrame")
        tree_frame.pack(fill="both", expand=True, padx=8, pady=(2, 8))

        cols = ("no", "name", "platform", "status", "date", "key", "url")
        self.history_tree = ttk.Treeview(
            tree_frame,
            columns=cols,
            show="headings",
            selectmode="browse",
            height=9,
        )
        self.history_tree.heading("no", text="#")
        self.history_tree.heading("name", text="Film / Dosya Adı")
        self.history_tree.heading("platform", text="Platform")
        self.history_tree.heading("status", text="Durum")
        self.history_tree.heading("date", text="Tarih")
        self.history_tree.heading("key", text="KID:KEY")
        self.history_tree.heading("url", text="MPD / M3U8 Linki")

        self.history_tree.column("no", width=32, anchor="center", stretch=False)
        self.history_tree.column("name", width=180, anchor="w")
        self.history_tree.column("platform", width=90, anchor="center", stretch=False)
        self.history_tree.column("status", width=95, anchor="center", stretch=False)
        self.history_tree.column("date", width=125, anchor="center", stretch=False)
        self.history_tree.column("key", width=170, anchor="w")
        self.history_tree.column("url", width=260, anchor="w")

        hist_scroll = ttk.Scrollbar(tree_frame, command=self.history_tree.yview)
        self.history_tree.configure(yscrollcommand=hist_scroll.set)
        hist_scroll.pack(side="right", fill="y")
        self.history_tree.pack(side="left", fill="both", expand=True)

        self.history_tree.bind("<<TreeviewSelect>>", lambda e: self._gecmisten_yukle(sekme_degistir=False))
        self.history_tree.bind("<Double-1>", lambda e: self._gecmisten_yukle(sekme_degistir=True))

        # SEKME 3: Toplu İndirme Kuyruğu (JSON)
        self.tab_queue = ttk.Frame(self.notebook, style="Card.TFrame")
        self.notebook.add(self.tab_queue, text="  📋 Toplu İndirme Kuyruğu (0)  ")

        q_ust = ttk.Frame(self.tab_queue, style="Card.TFrame")
        q_ust.pack(fill="x", padx=8, pady=(8, 4))

        self.kuyruk_ozet_lbl = ttk.Label(
            q_ust,
            text="💡 WidevineProxy2 veya liste JSON ekleyerek birden fazla bölümü/filmi sırayla indirebilirsiniz. (Adı değiştirmek için çift tıklayın)",
            style="Muted.TLabel",
        )
        self.kuyruk_ozet_lbl.pack(side="left")

        q_btn_bar = ttk.Frame(self.tab_queue, style="Card.TFrame")
        q_btn_bar.pack(fill="x", padx=8, pady=(0, 6))

        btn_q_json = tk.Button(
            q_btn_bar,
            text="📂 JSON Dosyası Ekle",
            font=("Segoe UI", 8, "bold"),
            relief="flat",
            padx=10,
            pady=4,
            cursor="hand2",
            command=self.json_dosyasi_ekle,
        )
        btn_q_json.pack(side="left", padx=(0, 4))
        self._tk_accent_btns.append(btn_q_json)

        btn_q_form = tk.Button(
            q_btn_bar,
            text="➕ Mevcut Formu Kuyruğa Ekle",
            font=("Segoe UI", 8, "bold"),
            relief="flat",
            padx=9,
            pady=4,
            cursor="hand2",
            command=self.formdan_kuyruga_ekle,
        )
        btn_q_form.pack(side="left", padx=4)
        self._tk_sec_btns.append(btn_q_form)

        btn_q_rename = tk.Button(
            q_btn_bar,
            text="✏️ Adı Düzenle",
            font=("Segoe UI", 8, "bold"),
            relief="flat",
            padx=9,
            pady=4,
            cursor="hand2",
            command=self.kuyruk_adi_duzenle,
        )
        btn_q_rename.pack(side="left", padx=4)
        self._tk_primary_btns.append(btn_q_rename)

        self.kuyruk_baslat_btn = tk.Button(
            q_btn_bar,
            text="▶ Kuyruğu Başlat (Sırayla İndir)",
            font=("Segoe UI", 9, "bold"),
            relief="flat",
            padx=12,
            pady=4,
            cursor="hand2",
            command=self.kuyrugu_baslat,
        )
        self.kuyruk_baslat_btn.pack(side="right", padx=(6, 0))
        self._tk_accent_btns.append(self.kuyruk_baslat_btn)

        btn_q_temizle = tk.Button(
            q_btn_bar,
            text="🧹 Temizle",
            font=("Segoe UI", 8, "bold"),
            relief="flat",
            padx=8,
            pady=4,
            cursor="hand2",
            command=self.kuyrugu_temizle,
        )
        btn_q_temizle.pack(side="right", padx=4)
        self._tk_primary_btns.append(btn_q_temizle)

        btn_q_sil = tk.Button(
            q_btn_bar,
            text="🗑 Seçiliyi Sil",
            font=("Segoe UI", 8, "bold"),
            relief="flat",
            padx=8,
            pady=4,
            cursor="hand2",
            command=self.kuyruk_secili_sil,
        )
        btn_q_sil.pack(side="right", padx=4)
        self._tk_primary_btns.append(btn_q_sil)

        q_tree_frame = ttk.Frame(self.tab_queue, style="Card.TFrame")
        q_tree_frame.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        q_cols = ("no", "name", "platform", "status", "key", "url")
        self.queue_tree = ttk.Treeview(
            q_tree_frame,
            columns=q_cols,
            show="headings",
            selectmode="browse",
            height=8,
        )
        self.queue_tree.heading("no", text="#")
        self.queue_tree.heading("name", text="Film / Bölüm Adı (Çift Tıkla: Düzenle)")
        self.queue_tree.heading("platform", text="Platform")
        self.queue_tree.heading("status", text="Durum")
        self.queue_tree.heading("key", text="KID:KEY")
        self.queue_tree.heading("url", text="Manifest URL")

        self.queue_tree.column("no", width=34, anchor="center", stretch=False)
        self.queue_tree.column("name", width=260, anchor="w")
        self.queue_tree.column("platform", width=85, anchor="center", stretch=False)
        self.queue_tree.column("status", width=110, anchor="center", stretch=False)
        self.queue_tree.column("key", width=175, anchor="w")
        self.queue_tree.column("url", width=260, anchor="w")

        q_scroll = ttk.Scrollbar(q_tree_frame, command=self.queue_tree.yview)
        self.queue_tree.configure(yscrollcommand=q_scroll.set)
        q_scroll.pack(side="right", fill="y")
        self.queue_tree.pack(side="left", fill="both", expand=True)

        self.queue_tree.bind("<Double-1>", lambda e: self.kuyruk_adi_duzenle())

    # ------------------------------------------------------------------------
    # TEMA MOTORU (4 MOD: KLASİK KOYU/AÇIK + MACOS KOYU/AÇIK)
    # ------------------------------------------------------------------------
    def _tema_secildi(self, _event=None):
        secilen = self.tema_var.get()
        if secilen in THEMES:
            self.temayi_uygula(secilen, kaydet=True)

    def temayi_uygula(self, tema_adi: str, kaydet: bool = True):
        t = THEMES[tema_adi]
        self.aktif_tema_adi = tema_adi
        if kaydet:
            self.ayarlar["theme"] = tema_adi
            ayar_kaydet(self.ayarlar)

        self.root.configure(bg=t["bg"])

        # macOS temasında trafik ışıklarını göster
        if t["style_kind"] == "macos":
            self._mac_dots_frame.configure(bg=t["bg"])
            for child in self._mac_dots_frame.winfo_children():
                child.configure(bg=t["bg"])
            self._mac_dots_frame.pack(side="left", before=self.baslik_lbl, padx=(0, 8))
        else:
            self._mac_dots_frame.pack_forget()

        style = ttk.Style()
        style.theme_use("clam")

        style.configure("TFrame", background=t["bg"])
        style.configure("Card.TFrame", background=t["card"], relief="flat")
        style.configure(
            "TLabelframe",
            background=t["card"],
            foreground=t["accent"],
            bordercolor=t["border"],
            relief="solid",
        )
        style.configure(
            "TLabelframe.Label",
            background=t["card"],
            foreground=t["accent"],
            font=("Segoe UI", 10, "bold"),
        )
        style.configure(
            "TLabel",
            background=t["card"],
            foreground=t["fg"],
            font=("Segoe UI", 9),
        )
        style.configure(
            "Header.TLabel",
            background=t["bg"],
            foreground=t["header_fg"],
            font=("Segoe UI", 13, "bold"),
        )
        style.configure(
            "SubHeader.TLabel",
            background=t["bg"],
            foreground=t["muted"],
            font=("Segoe UI", 9, "bold"),
        )
        style.configure(
            "Muted.TLabel",
            background=t["card"],
            foreground=t["muted"],
            font=("Segoe UI", 8, "italic"),
        )
        style.configure(
            "Info.TLabel",
            background=t["card"],
            foreground=t["info_fg"],
            font=("Segoe UI", 9, "bold"),
        )
        style.configure(
            "Percent.TLabel",
            background=t["card"],
            foreground=t["accent"],
            font=("Segoe UI", 11, "bold"),
        )
        style.configure(
            "Metric.TLabel",
            background=t["card"],
            foreground=t["fg"],
            font=("Segoe UI", 9, "bold"),
        )
        style.configure(
            "TRadiobutton",
            background=t["card"],
            foreground=t["fg"],
            font=("Segoe UI", 9, "bold"),
            focuscolor=t["card"],
        )
        style.map(
            "TRadiobutton",
            background=[("active", t["card"])],
            foreground=[("selected", t["accent"])],
        )
        style.configure(
            "TCheckbutton",
            background=t["card"],
            foreground=t["fg"],
            font=("Segoe UI", 9, "bold"),
            focuscolor=t["card"],
        )
        style.map(
            "TCheckbutton",
            background=[("active", t["card"])],
            foreground=[("selected", t["danger"])],
        )
        style.configure(
            "TCombobox",
            fieldbackground=t["input_bg"],
            background=t["btn_bg"],
            foreground=t["input_fg"],
            arrowcolor=t["input_fg"],
            bordercolor=t["border"],
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", t["input_bg"])],
            foreground=[("readonly", t["input_fg"])],
            selectbackground=[("readonly", t["accent"])],
            selectforeground=[("readonly", t["accent_fg"])],
        )
        style.configure(
            "Download.Horizontal.TProgressbar",
            troughcolor=t["progress_trough"],
            background=t["progress_bar"],
            bordercolor=t["border"],
            lightcolor=t["progress_bar"],
            darkcolor=t["progress_bar"],
            thickness=16,
        )
        style.configure(
            "TNotebook",
            background=t["bg"],
            bordercolor=t["border"],
        )
        style.configure(
            "TNotebook.Tab",
            background=t["tab_bg"],
            foreground=t["muted"],
            padding=(12, 6),
            font=("Segoe UI", 9, "bold"),
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", t["tab_sel_bg"])],
            foreground=[("selected", t["accent"])],
        )
        style.configure(
            "Treeview",
            background=t["tree_bg"],
            fieldbackground=t["tree_bg"],
            foreground=t["tree_fg"],
            rowheight=26,
            font=("Segoe UI", 9),
            bordercolor=t["border"],
        )
        style.configure(
            "Treeview.Heading",
            background=t["tree_head_bg"],
            foreground=t["tree_head_fg"],
            font=("Segoe UI", 9, "bold"),
            relief="flat",
        )
        style.map(
            "Treeview",
            background=[("selected", t["tree_sel_bg"])],
            foreground=[("selected", t["tree_sel_fg"])],
        )

        # Standart tk widget'larını renklendir
        for entry, fg_key in self._tk_entries:
            entry.configure(
                bg=t["input_bg"],
                fg=t[fg_key],
                insertbackground=t["input_fg"],
                highlightthickness=1,
                highlightbackground=t["border"],
                highlightcolor=t["accent"],
            )

        for btn in self._tk_primary_btns:
            btn.configure(bg=t["btn_bg"], fg=t["btn_fg"], activebackground=t["accent"], activeforeground=t["accent_fg"])
        for btn in self._tk_sec_btns:
            btn.configure(bg=t["btn_sec_bg"], fg=t["btn_sec_fg"], activebackground=t["accent"], activeforeground=t["accent_fg"])
        for btn in self._tk_accent_btns:
            btn.configure(bg=t["accent"], fg=t["accent_fg"], activebackground=t["btn_sec_bg"], activeforeground=t["btn_sec_fg"])

        self.baslat_btn.configure(bg=t["success"], fg=t["success_fg"], activebackground=t["accent"], activeforeground=t["accent_fg"])
        self.durdur_btn.configure(bg=t["danger"], fg=t["danger_fg"])

        self.log_text.configure(bg=t["log_bg"], fg=t["log_fg"], insertbackground=t["log_fg"])
        self.hata_text.configure(bg=t["diag_bg"], fg=t["diag_fg"], insertbackground=t["diag_fg"])

    # ------------------------------------------------------------------------
    # GEÇMİŞ (SON 10 KAYIT) YÖNETİMİ
    # ------------------------------------------------------------------------
    def _gecmise_ekle(self, raw_name: str, final_name: str, suffix: str, url: str, key: str, status: str):
        simdi = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
        yeni_kayit = {
            "name": raw_name.strip() or final_name,
            "final_name": final_name,
            "platform": suffix or "GENEL",
            "url": url,
            "key": key,
            "preset": self.preset_var.get(),
            "date": simdi,
            "status": status,
        }
        # Aynı URL zaten varsa eski kaydı çıkarıp en üste taşı
        self.gecmis = [item for item in self.gecmis if item.get("url") != url]
        self.gecmis.insert(0, yeni_kayit)
        self.gecmis = self.gecmis[:MAX_HISTORY_ITEMS]
        gecmis_kaydet(self.gecmis)
        self.root.after(0, self._gecmis_tablosunu_yenile)

    def _gecmis_durum_guncelle(self, url: str, yeni_durum: str):
        for item in self.gecmis:
            if item.get("url") == url:
                item["status"] = yeni_durum
                break
        gecmis_kaydet(self.gecmis)
        self.root.after(0, self._gecmis_tablosunu_yenile)

    def _gecmis_tablosunu_yenile(self):
        for row_id in self.history_tree.get_children():
            self.history_tree.delete(row_id)

        for idx, item in enumerate(self.gecmis, start=1):
            key_str = item.get("key", "")
            key_goster = (key_str[:22] + "...") if len(key_str) > 25 else (key_str or "Şifresiz")
            url_str = item.get("url", "")
            url_goster = (url_str[:55] + "...") if len(url_str) > 58 else url_str
            self.history_tree.insert(
                "",
                "end",
                iid=str(idx - 1),
                values=(
                    idx,
                    item.get("final_name") or item.get("name", ""),
                    item.get("platform", "GENEL"),
                    item.get("status", "-"),
                    item.get("date", ""),
                    key_goster,
                    url_goster,
                ),
            )
        self.gecmis_hizli_btn.configure(text=f"📜 Geçmiş ({len(self.gecmis)})")

    def gecmis_sekmesini_ac(self):
        self.notebook.select(self.tab_history)

    def _gecmisten_yukle(self, sekme_degistir: bool = False):
        sel = self.history_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if idx < 0 or idx >= len(self.gecmis):
            return

        item = self.gecmis[idx]
        self.url_var.set(item.get("url", ""))
        self.key_var.set(item.get("key", ""))
        self.name_var.set(item.get("name", ""))
        if item.get("preset") in ("1", "2", "3", "4", "5"):
            self.preset_var.set(item["preset"])
            self._preset_degisti()

        self._hata_yaz(
            f"✅ Geçmişten yüklendi: {item.get('final_name', item.get('name'))} ({item.get('platform', 'GENEL')})\n"
            "• MPD/M3U8 linki ve KEY otomatik dolduruldu. '🚀 İNDİRMEYİ BAŞLAT' butonuna basarak tekrar indirebilirsiniz."
        )
        if sekme_degistir:
            self.notebook.select(self.tab_log)

    def secili_gecmisi_sil(self):
        sel = self.history_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if 0 <= idx < len(self.gecmis):
            self.gecmis.pop(idx)
            gecmis_kaydet(self.gecmis)
            self._gecmis_tablosunu_yenile()

    def gecmisi_temizle(self):
        if not self.gecmis:
            return
        if messagebox.askyesno("Geçmişi Temizle", "Son 10 indirme kaydının tamamı silinsin mi?"):
            self.gecmis = []
            gecmis_kaydet(self.gecmis)
            self._gecmis_tablosunu_yenile()

    # ------------------------------------------------------------------------
    # TOPLU İNDİRME KUYRUĞU (JSON) YÖNETİMİ
    # ------------------------------------------------------------------------
    def json_dosyasi_ekle(self):
        dosya_yolu = filedialog.askopenfilename(
            title="Toplu İndirme JSON Dosyası Seç (WidevineProxy2 / Liste)",
            initialdir=str(self.download_dir) if self.download_dir.exists() else str(Path.home()),
            filetypes=[("JSON Dosyaları", "*.json"), ("Tüm Dosyalar", "*.*")],
        )
        if not dosya_yolu:
            return
        try:
            yeniler = json_kuyruk_ayikla(Path(dosya_yolu))
        except Exception as e:
            messagebox.showerror("JSON Hatası", f"JSON dosyası okunamadı:\n{e}")
            return

        if not yeniler:
            messagebox.showwarning(
                "Kayıt Bulunamadı",
                "Seçilen JSON dosyasında geçerli bir MPD/M3U8 manifest linki bulunamadı.",
            )
            return

        mevcut_urller = {x["url"] for x in self.kuyruk}
        eklenen = 0
        for item in yeniler:
            if item["url"] not in mevcut_urller:
                self.kuyruk.append(item)
                mevcut_urller.add(item["url"])
                eklenen += 1

        self._kuyruk_tablosunu_yenile()
        self.notebook.select(self.tab_queue)
        self._hata_yaz(
            f"📂 JSON yüklendi: {Path(dosya_yolu).name}\n"
            f"• {eklenen} yeni içerik kuyruğa eklendi (Toplam: {len(self.kuyruk)}).\n"
            "• İsterseniz çift tıklayıp adları düzenleyebilir, ardından '▶ Kuyruğu Başlat' ile sırayla indirebilirsiniz."
        )

    def formdan_kuyruga_ekle(self):
        ham_url = self.url_var.get().strip()
        url, _ = ayikla_url_ve_anahtarlar(ham_url)
        if not url or not url.startswith("http"):
            messagebox.showwarning("Eksik Bilgi", "Kuyruğa eklemek için önce yukarıya geçerli bir link yapıştırın.")
            return
        _, _, suffix, _, is_live, _ = platform_ve_header_tespit(url)
        ad = self.name_var.get().strip() or f"Indirme_{len(self.kuyruk) + 1:02d}"
        self.kuyruk.append({
            "name": ad,
            "url": url,
            "key": self.key_var.get().strip(),
            "platform": suffix or "GENEL",
            "is_live": is_live,
            "status": "⏳ Bekliyor",
        })
        self._kuyruk_tablosunu_yenile()
        self.notebook.select(self.tab_queue)

    def kuyruk_adi_duzenle(self):
        sel = self.queue_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if not (0 <= idx < len(self.kuyruk)):
            return
        mevcut_ad = self.kuyruk[idx]["name"]
        yeni_ad = simpledialog.askstring(
            "Dosya Adını Düzenle",
            "Yeni film / bölüm adını girin (platform etiketi otomatik eklenecektir):",
            initialvalue=mevcut_ad,
            parent=self.root,
        )
        if yeni_ad and yeni_ad.strip():
            self.kuyruk[idx]["name"] = yeni_ad.strip()
            self._kuyruk_tablosunu_yenile()

    def kuyruk_secili_sil(self):
        sel = self.queue_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if self.kuyruk_calisiyor and idx == self.aktif_kuyruk_idx:
            messagebox.showwarning("Aktif İndirme", "Şu an inen kaydı silemezsiniz; önce işlemi durdurun.")
            return
        if 0 <= idx < len(self.kuyruk):
            self.kuyruk.pop(idx)
            if self.aktif_kuyruk_idx > idx:
                self.aktif_kuyruk_idx -= 1
            self._kuyruk_tablosunu_yenile()

    def kuyrugu_temizle(self):
        if not self.kuyruk:
            return
        if self.kuyruk_calisiyor:
            messagebox.showwarning("Kuyruk Çalışıyor", "Kuyruğu temizlemek için önce aktif işlemi durdurun.")
            return
        if messagebox.askyesno("Kuyruğu Temizle", "Kuyruktaki tüm kayıtlar silinsin mi?"):
            self.kuyruk = []
            self.aktif_kuyruk_idx = -1
            self._kuyruk_tablosunu_yenile()

    def _kuyruk_tablosunu_yenile(self):
        for row_id in self.queue_tree.get_children():
            self.queue_tree.delete(row_id)

        tamamlanan = 0
        bekleyen = 0
        for idx, item in enumerate(self.kuyruk, start=1):
            st = item.get("status", "⏳ Bekliyor")
            if "Tamamlandı" in st:
                tamamlanan += 1
            elif "Bekliyor" in st:
                bekleyen += 1
            key_str = item.get("key", "")
            key_goster = (key_str[:22] + "...") if len(key_str) > 25 else (key_str or "Şifresiz")
            url_str = item.get("url", "")
            url_goster = (url_str[:55] + "...") if len(url_str) > 58 else url_str
            self.queue_tree.insert(
                "",
                "end",
                iid=str(idx - 1),
                values=(
                    idx,
                    item.get("name", ""),
                    item.get("platform", "GENEL"),
                    st,
                    key_goster,
                    url_goster,
                ),
            )
        self.notebook.tab(self.tab_queue, text=f"  📋 Toplu İndirme Kuyruğu ({len(self.kuyruk)})  ")
        self.kuyruk_ozet_lbl.configure(
            text=f"📋 Kuyruk: {len(self.kuyruk)} dosya  |  ✅ {tamamlanan} tamamlandı  |  ⏳ {bekleyen} bekliyor  (Adı değiştirmek için çift tıklayın)"
        )

    def kuyrugu_baslat(self):
        if self.calisiyor:
            messagebox.showinfo("İşlem Devam Ediyor", "Şu anda aktif bir indirme zaten çalışıyor.")
            return
        if not self.kuyruk:
            messagebox.showinfo("Kuyruk Boş", "Önce '📂 JSON Dosyası Ekle' ile indirme listesi yükleyin.")
            return
        bekleyen_var = any("Tamamlandı" not in x.get("status", "") for x in self.kuyruk)
        if not bekleyen_var:
            if messagebox.askyesno("Tümü İndirildi", "Kuyruktaki tüm dosyalar zaten indirildi. Hepsi sıfırlanıp tekrar indirilsin mi?"):
                for x in self.kuyruk:
                    x["status"] = "⏳ Bekliyor"
                self._kuyruk_tablosunu_yenile()
            else:
                return

        self.kuyruk_calisiyor = True
        self.kullanici_durdurdu = False
        self._sonraki_kuyruk_ogesini_baslat()

    def _sonraki_kuyruk_ogesini_baslat(self):
        if not self.kuyruk_calisiyor or self.kullanici_durdurdu:
            self.kuyruk_calisiyor = False
            self.aktif_kuyruk_idx = -1
            return

        sonraki_idx = -1
        for i, item in enumerate(self.kuyruk):
            if "Tamamlandı" not in item.get("status", "") and "Hatalı" not in item.get("status", ""):
                sonraki_idx = i
                break

        if sonraki_idx == -1:
            # Kuyruk tamamlandı!
            self.kuyruk_calisiyor = False
            self.aktif_kuyruk_idx = -1
            basarili = sum(1 for x in self.kuyruk if "Tamamlandı" in x.get("status", ""))
            hatali = sum(1 for x in self.kuyruk if "Hatalı" in x.get("status", ""))
            ozet = (
                f"🎉 TOPLU İNDİRME KUYRUĞU TAMAMLANDI!\n"
                f"• Başarılı: {basarili} dosya  |  Hatalı: {hatali} dosya\n"
                f"• Kayıt Klasörü: {self.download_dir}"
            )
            self._hata_yaz(ozet)
            self._log_yaz("\n" + "=" * 75 + "\n" + ozet + "\n")
            self._kuyruk_tablosunu_yenile()
            return

        self.aktif_kuyruk_idx = sonraki_idx
        oge = self.kuyruk[sonraki_idx]
        oge["status"] = "⬇ İndiriliyor..."
        self._kuyruk_tablosunu_yenile()

        # Formu otomatik doldur ve indirmeyi başlat
        self.url_var.set(oge["url"])
        self.key_var.set(oge["key"])
        self.name_var.set(oge["name"])
        self.canli_mod_var.set(bool(oge.get("is_live", False)))

        gorev = self.komutu_olustur(sadece_analiz=False)
        if not gorev:
            oge["status"] = "❌ Hatalı"
            self._kuyruk_tablosunu_yenile()
            self.root.after(200, self._sonraki_kuyruk_ogesini_baslat)
            return

        gorev["queue_index"] = sonraki_idx
        gorev["queue_total"] = len(self.kuyruk)

        self.log_text.delete("1.0", "end")
        self._ilerleme_sifirla(f"🚀 [{sonraki_idx + 1}/{len(self.kuyruk)}] Başlatılıyor: {gorev['final_name']}")
        self._gecmise_ekle(
            raw_name=gorev["raw_name"],
            final_name=gorev["final_name"],
            suffix=gorev["suffix"],
            url=gorev["url"],
            key=self.key_var.get().strip(),
            status="İndiriliyor...",
        )
        self._log_yaz(
            f"[Kuyruk {sonraki_idx + 1}/{len(self.kuyruk)}] Dosya Adı: {gorev['final_name']}\n"
            f"[Kayıt Klasörü] {self.download_dir}\n"
            + "=" * 75 + "\n"
        )
        self._hata_yaz(
            f"⏳ Kuyruk İndiriliyor ({sonraki_idx + 1}/{len(self.kuyruk)}): {gorev['final_name']}"
        )
        threading.Thread(
            target=self._calistir_worker, args=(gorev, False), daemon=True
        ).start()

    # ------------------------------------------------------------------------
    # CHROME EKLENTİSİ YEREL KÖPRÜSÜ (127.0.0.1:45821)
    # ------------------------------------------------------------------------
    def _chrome_koprusunu_baslat(self):
        app_ref = self

        class BridgeHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass  # Konsol çıktısı üretme

            def _send_json(self, code: int, payload: dict):
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_OPTIONS(self):
                self._send_json(200, {"ok": True})

            def do_GET(self):
                if self.path.startswith("/ping"):
                    self._send_json(200, {
                        "ok": True,
                        "app": "Indirici Pro",
                        "version": APP_VERSION,
                        "queue_count": len(app_ref.kuyruk),
                    })
                else:
                    self._send_json(404, {"ok": False, "error": "Not found"})

            def do_POST(self):
                if not self.path.startswith("/send"):
                    self._send_json(404, {"ok": False, "error": "Not found"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    raw = self.rfile.read(length) if length > 0 else b"{}"
                    data = json.loads(raw.decode("utf-8", errors="replace"))
                    url = (data.get("url") or "").strip()
                    name = (data.get("name") or "").strip()
                    key = (data.get("key") or "").strip()
                    mode = (data.get("mode") or "fill").strip().lower()
                    if not url or not url.startswith("http"):
                        self._send_json(400, {"ok": False, "error": "Geçersiz URL"})
                        return
                    app_ref.root.after(0, lambda: app_ref._chrome_istegini_isle(url, name, key, mode))
                    self._send_json(200, {"ok": True, "mode": mode})
                except Exception as e:
                    self._send_json(500, {"ok": False, "error": str(e)})

        def _server_worker():
            try:
                srv = ThreadingHTTPServer(("127.0.0.1", CHROME_BRIDGE_PORT), BridgeHandler)
                srv.daemon_threads = True
                self._bridge_server = srv
                self._log_yaz(f"[Chrome Köprüsü] Aktif (http://127.0.0.1:{CHROME_BRIDGE_PORT})\n")
                srv.serve_forever()
            except OSError:
                # Port zaten kullanımdaysa sessizce geç
                pass

        threading.Thread(target=_server_worker, daemon=True).start()

    def _chrome_istegini_isle(self, url: str, name: str, key: str, mode: str):
        _, _, suffix, _, is_live, _ = platform_ve_header_tespit(url)
        temiz_keyler = anahtarlari_ayikla(key)
        key = " ".join(temiz_keyler) if temiz_keyler else key.replace("--key", "").strip()
        temiz_ad = name
        if temiz_ad:
            parcalar = [p.strip() for p in re.split(r"\s*[-|–]\s*", temiz_ad) if p.strip()]
            if parcalar:
                temiz_ad = parcalar[0]
            temiz_ad = re.sub(
                r"\s+(?:full\s+hd\s+|hd\s+|full\s+|canl[ıi]\s+|t[üu]rk[çc]e\s+dublaj\s+|altyaz[ıi]l[ıi]\s+|tek\s+par[çc]a\s+)?[iİıI]zle\s*$",
                "",
                temiz_ad,
                flags=re.IGNORECASE,
            ).strip()

        if mode == "queue":
            self.kuyruk.append({
                "name": temiz_ad or f"Chrome_{len(self.kuyruk) + 1:02d}",
                "url": url,
                "key": key,
                "platform": suffix or "GENEL",
                "is_live": is_live,
                "status": "⏳ Bekliyor",
            })
            self._kuyruk_tablosunu_yenile()
            self.notebook.select(self.tab_queue)
            self._hata_yaz(f"🌐 Chrome eklentisinden kuyruğa eklendi: {temiz_ad or url[:45]}")
        else:
            self.url_var.set(url)
            if key:
                self.key_var.set(key)
            if temiz_ad:
                self.name_var.set(temiz_ad)
            self.canli_mod_var.set(is_live)
            self._hata_yaz(
                f"🌐 Chrome eklentisinden alındı: {temiz_ad or 'Yeni Yayın'} [{suffix or 'GENEL'}]\n"
                "• İsterseniz KEY ekleyip '🚀 İNDİRMEYİ BAŞLAT' butonuna basabilirsiniz."
            )
            if mode == "start" and not self.calisiyor:
                self.indirmeyi_baslat()

        # Pencereyi öne getir
        try:
            self.root.deiconify()
            self.root.lift()
            self.root.attributes("-topmost", True)
            self.root.after(200, lambda: self.root.attributes("-topmost", False))
        except Exception:
            pass

    # ------------------------------------------------------------------------
    # OLAY YÖNETİCİLERİ VE KONTROLLER
    # ------------------------------------------------------------------------
    def _ortam_kontrol(self):
        try:
            self.download_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        eksikler = []
        if not N_M3U8DL_EXE.exists():
            eksikler.append(str(N_M3U8DL_EXE))
        if not FFMPEG_EXE.exists():
            eksikler.append(str(FFMPEG_EXE))
        if not MP4DECRYPT_EXE.exists():
            eksikler.append(str(MP4DECRYPT_EXE))

        if eksikler:
            self._hata_yaz(
                "⚠️ EKSİK DOSYA UYARISI:\n"
                + "\n".join(f"• Bulunamadı: {e}" for e in eksikler)
            )
        else:
            yt_durum = "Hazır" if YT_DLP_EXE.exists() else "Bulunamadı (YouTube/MP4 için tools/yt-dlp.exe ekleyin)"
            self._log_yaz(
                f"[Sistem] Araçlar hazır (N_m3u8DL-RE, ffmpeg, mp4decrypt | yt-dlp: {yt_durum}).\n"
                f"[Sistem] İndirme Klasörü: {self.download_dir}\n"
            )

    def _preset_degisti(self):
        secim = self.preset_var.get()
        if secim == "1":  # En İyi Video + Türkçe Ses (.mkv)
            self.video_secim.current(0)    # En İyi Kalite
            self.ses_secim.current(0)      # Sadece Türkçe
            self.altyazi_secim.current(0)  # Sadece Türkçe
            self.format_secim.current(0)   # MKV
        elif secim == "2":  # Sadece Türkçe Ses (.m4a)
            self.video_secim.current(5)    # Video Kapalı
            self.ses_secim.current(0)      # Sadece Türkçe
            self.altyazi_secim.current(3)  # Altyazı Kapalı
            self.format_secim.current(1)   # M4A (Sadece Ses)
        elif secim == "3":  # Sadece Altyazı (.srt)
            self.video_secim.current(5)    # Video Kapalı
            self.ses_secim.current(6)      # Ses Kapalı
            self.altyazi_secim.current(1)  # Tüm Altyazılar
            self.format_secim.current(3)   # Otomatik / Ham
        elif secim == "4":  # Tümünü İndir (.mkv)
            self.video_secim.current(0)    # En İyi Kalite
            self.ses_secim.current(4)      # Tüm Ses Dilleri
            self.altyazi_secim.current(1)  # Tüm Altyazılar
            self.format_secim.current(0)   # MKV
        self._url_veya_isim_degisti()

    def _format_otomatik_ayarla(self, _event=None):
        """Sadece ses seçildiyse M4A, video+ses seçildiyse MKV olarak otomatik ayarlar."""
        v_kapali = "Kapalı" in self.video_secim.get()
        a_kapali = "Kapalı" in self.ses_secim.get()
        if v_kapali and not a_kapali:
            self.format_secim.current(1)  # M4A (Sadece Ses)
        elif not v_kapali and not a_kapali:
            if "M4A" in self.format_secim.get() or "Otomatik" in self.format_secim.get():
                self.format_secim.current(0)  # MKV
        self._url_veya_isim_degisti()

    def _aktif_uzanti_tahmin(self) -> str:
        v_kapali = "Kapalı" in self.video_secim.get()
        a_kapali = "Kapalı" in self.ses_secim.get()
        f_sec = self.format_secim.get()
        if v_kapali and not a_kapali:
            return ".m4a"
        if v_kapali and a_kapali:
            return ".srt"
        if "MP4" in f_sec:
            return ".mp4"
        if "TS" in f_sec:
            return ".ts"
        return ".mkv"

    def _url_veya_isim_degisti(self, *_):
        ham = self.url_var.get().strip()
        suffix = ""
        if not ham:
            self.platform_bilgi_lbl.configure(text="Platform: Bekleniyor...")
            self.canli_mod_var.set(False)
        else:
            url, bulunan_keyler = ayikla_url_ve_anahtarlar(ham)
            if bulunan_keyler and not self.key_var.get().strip():
                self.key_var.set(" ".join(bulunan_keyler))
            if url:
                _, platform, suffix, _, is_live, _ = platform_ve_header_tespit(url)
                self.canli_mod_var.set(is_live)
                if yt_dlp_gerekli_mi(url):
                    if "youtube.com" in url.lower() or "youtu.be" in url.lower():
                        self.platform_bilgi_lbl.configure(text="YouTube | yt-dlp Motoru")
                    else:
                        self.platform_bilgi_lbl.configure(text="Doğrudan Video / Web | yt-dlp")
                else:
                    tur = "🔴 CANLI" if is_live else "VOD"
                    etiket = f" [{suffix}]" if suffix else ""
                    self.platform_bilgi_lbl.configure(text=f"{platform}{etiket} | {tur}")

        hedef_ad = hedef_dosya_adi_olustur(self.name_var.get(), suffix)
        uzanti = self._aktif_uzanti_tahmin()
        self.cikti_onizleme_lbl.configure(
            text=f"📁 Kaydedilecek Dosya: {self.download_dir}\\{hedef_ad}{uzanti}"
        )

    def url_yapistir(self):
        try:
            pano = self.root.clipboard_get()
            url, bulunan_keyler = ayikla_url_ve_anahtarlar(pano)
            self.url_var.set(url if url else pano.strip())
            if bulunan_keyler:
                self.key_var.set(" ".join(bulunan_keyler))
        except tk.TclError:
            pass

    def key_yapistir(self):
        try:
            pano = self.root.clipboard_get()
            keys = anahtarlari_ayikla(pano)
            self.key_var.set(" ".join(keys) if keys else pano.strip())
        except tk.TclError:
            pass

    def formu_temizle(self):
        self.url_var.set("")
        self.key_var.set("")
        self.name_var.set("")
        self.log_text.delete("1.0", "end")
        self._ilerleme_sifirla()
        self._hata_yaz("💡 Form temizlendi. Yeni bir link yapıştırabilirsiniz.")

    def klasoru_ac(self):
        self.download_dir.mkdir(parents=True, exist_ok=True)
        os.startfile(str(self.download_dir))

    def klasor_sec(self):
        secilen = filedialog.askdirectory(
            title="İndirilen Dosyaların Kaydedileceği Klasörü Seçin",
            initialdir=str(self.download_dir) if self.download_dir.exists() else str(Path.home()),
        )
        if secilen:
            self.download_dir = Path(secilen)
            self.temp_work_dir = self.download_dir / "_temp"
            self.ayarlar["download_dir"] = str(self.download_dir)
            ayar_kaydet(self.ayarlar)
            self._url_veya_isim_degisti()
            self._log_yaz(f"[Sistem] İndirme klasörü güncellendi: {self.download_dir}\n")

    def _log_yaz(self, metin: str):
        def _ekle():
            self.log_text.insert("end", metin)
            self.log_text.see("end")
        self.root.after(0, _ekle)

    def _hata_yaz(self, metin: str):
        def _guncelle():
            self.hata_text.delete("1.0", "end")
            self.hata_text.insert("1.0", metin)
        self.root.after(0, _guncelle)

    def _bar_rengi_ayarla(self, bar_kind: str):
        """Aynı ilerleme çubuğunun rengini aşamaya göre (video/audio/sub/mux/live) değiştirir."""
        t = THEMES.get(self.aktif_tema_adi, THEMES["Klasik Koyu (Catppuccin)"])
        renk_haritasi = {
            "video": t["bar_video"],
            "audio": t["bar_audio"],
            "sub": t["bar_sub"],
            "mux": t["bar_mux"],
            "live": t["bar_live"],
        }
        renk = renk_haritasi.get(bar_kind, t["bar_video"])
        style = ttk.Style()
        style.configure(
            "Download.Horizontal.TProgressbar",
            troughcolor=t["progress_trough"],
            background=renk,
            bordercolor=t["border"],
            lightcolor=renk,
            darkcolor=renk,
            thickness=16,
        )
        self.yuzde_lbl.configure(foreground=renk)

    def _ilerleme_sifirla(self, asama="⏸ Hazır — İndirme bekleniyor"):
        def _reset():
            self.progress_bar.stop()
            self.progress_bar.configure(mode="determinate")
            self._bar_rengi_ayarla("video")
            self.progress_var.set(0.0)
            self.yuzde_lbl.configure(text="% 0.0")
            self.asama_lbl.configure(text=asama)
            self.hiz_lbl.configure(text="⚡ Hız: --")
            self.boyut_lbl.configure(text="📦 Boyut: --")
            self.parca_lbl.configure(text="🧩 Parça: --")
            self.eta_lbl.configure(text="⏱ Kalan Süre: --")
        self.root.after(0, _reset)

    def _ilerleme_guncelle(self, bilgi: dict, zorla: bool = False):
        simdi = time.monotonic()
        if not zorla and (simdi - self.son_ilerleme_zamani) < 0.07:
            return
        self.son_ilerleme_zamani = simdi

        def _uygula():
            if "bar_kind" in bilgi:
                self._bar_rengi_ayarla(bilgi["bar_kind"])
            if bilgi.get("pulse"):
                if str(self.progress_bar.cget("mode")) != "indeterminate":
                    self.progress_bar.configure(mode="indeterminate")
                    self.progress_bar.start(14)
                self.yuzde_lbl.configure(text="⚙️ İşleniyor")
            else:
                if str(self.progress_bar.cget("mode")) == "indeterminate":
                    self.progress_bar.stop()
                    self.progress_bar.configure(mode="determinate")
                if bilgi.get("reset_bar"):
                    self.progress_var.set(0.0)
                    self.yuzde_lbl.configure(text="% 0.0")
                if "percent" in bilgi:
                    p = bilgi["percent"]
                    self.progress_var.set(p)
                    self.yuzde_lbl.configure(text=f"% {p:.1f}")
            if "stage" in bilgi:
                self.asama_lbl.configure(text=bilgi["stage"])
            if "speed" in bilgi:
                self.hiz_lbl.configure(text=f"⚡ Hız: {bilgi['speed']}")
            if "size" in bilgi:
                self.boyut_lbl.configure(text=f"📦 Boyut: {bilgi['size']}")
            if "segments" in bilgi:
                self.parca_lbl.configure(text=f"🧩 Parça: {bilgi['segments']}")
            if "eta" in bilgi:
                self.eta_lbl.configure(text=f"⏱ Kalan Süre: {bilgi['eta']}")
        self.root.after(0, _uygula)

    # ------------------------------------------------------------------------
    # KOMUT OLUŞTURUCU
    # ------------------------------------------------------------------------
    def komutu_olustur(self, sadece_analiz=False):
        ham_url = self.url_var.get().strip()
        url, _ = ayikla_url_ve_anahtarlar(ham_url)
        if not url or not url.startswith("http"):
            messagebox.showerror("Hata", "Lütfen geçerli bir MPD veya M3U8 linki yapıştırın!")
            return None

        url, platform_name, suffix, platform_id, is_live, headers = platform_ve_header_tespit(
            url, self.cdn_secim.get()
        )

        raw_name = self.name_var.get().strip()
        hedef_isim = hedef_dosya_adi_olustur(raw_name, suffix)

        # YouTube, sosyal medya veya doğrudan video (.mp4/.flv/.3gp/.webm/.ts vb.) için yt-dlp motoru
        if yt_dlp_gerekli_mi(url):
            if not YT_DLP_EXE.exists():
                messagebox.showerror(
                    "yt-dlp Bulunamadı",
                    f"YouTube ve doğrudan video linkleri için yt-dlp.exe gereklidir:\n{YT_DLP_EXE}",
                )
                return None

            v_sec = self.video_secim.get()
            a_sec = self.ses_secim.get()
            s_sec = self.altyazi_secim.get()
            f_sec = self.format_secim.get()
            video_kapali = "Kapalı" in v_sec
            ses_kapali = "Kapalı" in a_sec
            sadece_ses = video_kapali and not ses_kapali

            cmd = [str(YT_DLP_EXE), "--no-color", "--newline"]
            if FFMPEG_EXE.exists():
                cmd.extend(["--ffmpeg-location", str(FFMPEG_EXE)])

            if sadece_analiz:
                cmd.extend(["-F", url])
                return {
                    "cmd": cmd,
                    "url": url,
                    "raw_name": raw_name or hedef_isim,
                    "final_name": hedef_isim,
                    "suffix": suffix,
                    "log_file": None,
                    "audio_only": False,
                    "live_limit_sec": 0,
                    "engine": "yt-dlp",
                }

            # Çıktı şablonu: kullanıcı isim girdiyse onu kullan, boşsa yt-dlp'nin %(title)s başlığını kullan
            if raw_name:
                cikti_sablon = str(self.download_dir / f"{hedef_isim}.%(ext)s")
            else:
                cikti_sablon = str(self.download_dir / "%(title)s.%(ext)s")

            cmd.extend(["-N", "8", "-o", cikti_sablon])

            if sadece_ses:
                cmd.extend(["-f", "bestaudio/best", "-x", "--audio-format", "m4a"])
            else:
                if "1080p" in v_sec:
                    fmt = "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best"
                elif "720p" in v_sec:
                    fmt = "bestvideo[height<=720]+bestaudio/best[height<=720]/best"
                elif "480p" in v_sec:
                    fmt = "bestvideo[height<=480]+bestaudio/best[height<=480]/best"
                elif "360p" in v_sec:
                    fmt = "bestvideo[height<=360]+bestaudio/best[height<=360]/best"
                else:
                    fmt = "bestvideo+bestaudio/best"
                cmd.extend(["-f", fmt])

                if "MP4" in f_sec:
                    cmd.extend(["--merge-output-format", "mp4"])
                else:
                    cmd.extend(["--merge-output-format", "mkv"])

            if "Kapalı" not in s_sec:
                if "İngilizce" in s_sec:
                    cmd.extend(["--write-subs", "--sub-langs", "en", "--convert-subs", "srt"])
                elif "Türkçe" in s_sec:
                    cmd.extend(["--write-subs", "--sub-langs", "tr", "--convert-subs", "srt"])
                else:
                    cmd.extend(["--write-subs", "--sub-langs", "tr,en", "--convert-subs", "srt"])

            cmd.append(url)
            return {
                "cmd": cmd,
                "url": url,
                "raw_name": raw_name or hedef_isim,
                "final_name": hedef_isim,
                "suffix": suffix,
                "log_file": None,
                "audio_only": sadece_ses,
                "live_limit_sec": 0,
                "engine": "yt-dlp",
            }

        cmd = [
            str(N_M3U8DL_EXE),
            url,
            "--save-dir", str(self.download_dir),
            "--tmp-dir", str(self.temp_work_dir),
            "--save-name", hedef_isim,
            "--no-ansi-color",
            "--write-meta-json", "false",
        ]
        if FFMPEG_EXE.exists():
            cmd.extend(["--ffmpeg-binary-path", str(FFMPEG_EXE)])
        if MP4DECRYPT_EXE.exists():
            cmd.extend(["--decryption-binary-path", str(MP4DECRYPT_EXE)])

        log_dosyasi = None
        if sadece_analiz:
            cmd.extend(["--skip-download", "--no-log"])
            cmd.extend(headers)
            return {
                "cmd": cmd,
                "url": url,
                "raw_name": raw_name or hedef_isim,
                "final_name": hedef_isim,
                "suffix": suffix,
                "log_file": None,
                "audio_only": False,
                "live_limit_sec": 0,
            }

        # İndirme için canlı ilerleme + özel log dosyası yolu (başarılı olursa silinecek)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        zaman_damgasi = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        log_dosyasi = LOG_DIR / f"indirme_{zaman_damgasi}.log"
        cmd.extend([
            "--force-ansi-console",
            "--del-after-done", "true",
            "--log-file-path", str(log_dosyasi),
        ])

        # Görüntü Seçimi
        v_sec = self.video_secim.get()
        video_kapali = "Kapalı" in v_sec
        if video_kapali:
            cmd.extend(["--drop-video", "all"])
        elif "1080p" in v_sec:
            cmd.extend(["--select-video", 'res="1920*":for=best'])
        elif "720p" in v_sec:
            cmd.extend(["--select-video", 'res="1280*":for=best'])
        elif "480p" in v_sec:
            cmd.extend(["--select-video", 'res="768*|640*|854*|480*":for=best'])
        elif "360p" in v_sec:
            cmd.extend(["--select-video", 'res="640*|480*":for=worst'])
        else:
            cmd.extend(["--select-video", "for=best"])

        # Ses Seçimi
        a_sec = self.ses_secim.get()
        ses_kapali = "Kapalı" in a_sec
        if ses_kapali:
            cmd.extend(["--drop-audio", "all"])
        elif "Sadece Türkçe" in a_sec:
            cmd.extend(["--select-audio", "lang=tr|tur|turkish:for=all"])
        elif "Türkçe + Tanımsız" in a_sec:
            cmd.extend(["--select-audio", "lang=tr|tur|turkish|und:for=all"])
        elif "Sadece İngilizce" in a_sec:
            cmd.extend(["--select-audio", "lang=en|eng|english:for=all"])
        elif "Türkçe ve İngilizce" in a_sec:
            cmd.extend(["--select-audio", "lang=tr|tur|turkish|en|eng:for=all"])
        elif "Tüm Ses Dilleri" in a_sec:
            cmd.extend(["--select-audio", "all"])
        else:
            cmd.extend(["--select-audio", "for=best"])

        # Altyazı Seçimi
        s_sec = self.altyazi_secim.get()
        if "Kapalı" in s_sec:
            cmd.extend(["--drop-subtitle", "all"])
        elif "Sadece Türkçe" in s_sec:
            cmd.extend(["--select-subtitle", "lang=tr|tur|turkish:for=all"])
        elif "Sadece İngilizce" in s_sec:
            cmd.extend(["--select-subtitle", "lang=en|eng|english:for=all"])
        else:
            cmd.extend(["--select-subtitle", "all"])

        # Şifre Çözme Anahtarları (KEY)
        keys = anahtarlari_ayikla(self.key_var.get())
        for k in keys:
            cmd.extend(["--key", k])

        # Çıktı Formatı Kuralları:
        # - Sadece ses indiriliyorsa -> .m4a (mux eklenmez, gerekirse indirme sonrası m4a'ya dönüştürülür)
        # - Video + Ses indiriliyorsa -> varsayılan MKV (-M format=mkv)
        f_sec = self.format_secim.get()
        sadece_ses = video_kapali and not ses_kapali
        canli_aktif = self.canli_mod_var.get() or is_live
        live_limit_sec = 0

        if canli_aktif:
            dk_str = self.canli_dk_var.get().strip()
            dk = int(dk_str) if dk_str.isdigit() and int(dk_str) > 0 else 5
            live_limit_sec = dk * 60
            limit_str = f"{dk // 60:02d}:{dk % 60:02d}:00"
            cmd.extend([
                "--live-record-limit", limit_str,
            ])
            if not video_kapali:
                if "TS" in f_sec:
                    cmd.extend(["-M", "format=ts"])
                elif "MP4" in f_sec:
                    cmd.extend(["-M", "format=mp4"])
                else:
                    # Canlı yayınlarda (özellikle stpp altyazılı TV+/Tivibu) MKV sorunsuz birleştirir
                    cmd.extend(["-M", "format=mkv"])
        else:
            if sadece_ses:
                # Sadece ses -> saf .m4a olarak insin
                pass
            elif video_kapali and ses_kapali:
                # Sadece altyazı -> .srt
                pass
            elif "MP4" in f_sec:
                cmd.extend(["-M", "format=mp4"])
            elif "TS" in f_sec:
                cmd.extend(["-M", "format=ts"])
            else:
                # Video + Ses -> MKV
                cmd.extend(["-M", "format=mkv"])

        cmd.extend(headers)
        return {
            "cmd": cmd,
            "url": url,
            "raw_name": raw_name or hedef_isim,
            "final_name": hedef_isim,
            "suffix": suffix,
            "log_file": log_dosyasi,
            "audio_only": sadece_ses,
            "live_limit_sec": live_limit_sec,
        }

    # ------------------------------------------------------------------------
    # CANLI YAYIN PARÇALARINI OTOMATİK BİRLEŞTİRME (DASH .m4s -> MKV / M4A)
    # ------------------------------------------------------------------------
    def _canli_parcalari_birlestir(self, hedef_isim: str, sadece_ses: bool = False) -> Path:
        """
        N_m3u8DL-RE canlı yayın kaydını bitirdiğinde parçaları geçici çalışma
        klasöründe bırakır. Bu fonksiyon şifresi çözülmüş _init_dec.mp4 + *_dec.m4s
        parçalarını sırayla birleştirip ffmpeg ile tek bir MKV (veya M4A) dosyasına paketler
        ve geçici klasörü temizler.
        """
        uzanti = ".m4a" if sadece_ses else self._aktif_uzanti_tahmin()
        hedef_dosya = self.download_dir / f"{hedef_isim}{uzanti}"
        gecici_klasor = self.temp_work_dir / hedef_isim

        # Zaten çıktı dosyası oluştuysa dokunma
        mevcut = [f for f in self.download_dir.glob(f"{hedef_isim}.*") if f.is_file() and f.suffix.lower() in (".mkv", ".mp4", ".ts", ".m4a")]
        if mevcut and not gecici_klasor.exists():
            return mevcut[0]

        if not gecici_klasor.exists() or not gecici_klasor.is_dir():
            return mevcut[0] if mevcut else None

        if not FFMPEG_EXE.exists():
            self._log_yaz("[Hata] ffmpeg.exe bulunamadığı için canlı yayın parçaları birleştirilemedi.\n")
            return None

        self._ilerleme_guncelle(
            {"bar_kind": "mux", "pulse": True, "stage": "🎬 Canlı Yayın Parçaları Birleştiriliyor (MKV)..."},
            zorla=True,
        )
        self._log_yaz(f"[Birleştirme] Canlı yayın parçaları birleştiriliyor: {gecici_klasor}\n")

        birlesen_dosyalar = []
        try:
            alt_klasorler = sorted([d for d in gecici_klasor.iterdir() if d.is_dir()], key=lambda p: p.name)
            for idx, alt in enumerate(alt_klasorler):
                alt_low = alt.name.lower()
                # Altyazı klasörlerini (stpp/wvtt/sub) ikili birleştirmeye katma
                if any(k in alt_low for k in ("stpp", "wvtt", "subtitle", "_sub")):
                    continue

                init_dosya = alt / "_init_dec.mp4"
                if not init_dosya.exists():
                    init_dosya = alt / "_init.mp4"

                parcalar = list(alt.glob("*_dec.m4s"))
                if not parcalar:
                    parcalar = list(alt.glob("*_dec.ts"))
                if not parcalar:
                    parcalar = [p for p in alt.glob("*.m4s") if not p.name.startswith("_")]
                if not parcalar:
                    parcalar = [p for p in alt.glob("*.ts") if not p.name.startswith("_")]

                if not parcalar:
                    continue

                def _sirala_anahtar(p: Path):
                    m = re.match(r"(\d+)", p.name)
                    return (0, int(m.group(1))) if m else (1, p.name)

                parcalar.sort(key=_sirala_anahtar)

                cikis_parca = gecici_klasor / f"_merged_{idx}.mp4"
                with open(cikis_parca, "wb") as out_f:
                    if init_dosya.exists():
                        with open(init_dosya, "rb") as in_f:
                            shutil.copyfileobj(in_f, out_f)
                    for parca in parcalar:
                        with open(parca, "rb") as in_f:
                            shutil.copyfileobj(in_f, out_f)

                if cikis_parca.stat().st_size > 0:
                    birlesen_dosyalar.append(cikis_parca)

            if not birlesen_dosyalar:
                return mevcut[0] if mevcut else None

            # Eğer İndirilenler'de aynı isimle .srt altyazı oluştuysa onu da MKV içine ekle
            srt_dosyalari = [
                f for f in self.download_dir.glob(f"{hedef_isim}*.srt") if f.is_file()
            ] if not sadece_ses and uzanti == ".mkv" else []

            ffmpeg_cmd = [str(FFMPEG_EXE), "-y"]
            for bf in birlesen_dosyalar:
                ffmpeg_cmd.extend(["-i", str(bf)])
            for sf in srt_dosyalari:
                ffmpeg_cmd.extend(["-i", str(sf)])

            ffmpeg_cmd.extend(["-c", "copy", str(hedef_dosya)])

            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
            res = subprocess.run(
                ffmpeg_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
            )

            if res.returncode == 0 and hedef_dosya.exists() and hedef_dosya.stat().st_size > 0:
                self._log_yaz(
                    f"[Birleştirme] ✅ Başarılı: {hedef_dosya.name} ({boyut_formatla(hedef_dosya.stat().st_size)})\n"
                )
                # Geçici klasörü ve MKV içine gömülen ayrı srt/m4a dosyalarını temizle
                shutil.rmtree(gecici_klasor, ignore_errors=True)
                for sf in srt_dosyalari:
                    sf.unlink(missing_ok=True)
                return hedef_dosya
            else:
                self._log_yaz(f"[Birleştirme Hatası] ffmpeg kodu {res.returncode}: {res.stderr[-400:]}\n")
                return None
        except Exception as e:
            self._log_yaz(f"[Birleştirme Hatası] {e}\n")
            return None

    # ------------------------------------------------------------------------
    # SES DOSYASI M4A GARANTİLEYİCİ
    # ------------------------------------------------------------------------
    def _sadece_ses_m4a_garantile(self, hedef_isim: str):
        """
        Sadece ses indirildiğinde çıkan dosya .m4a değilse (.aac / .mp4 / .ts),
        ffmpeg ile kayıpsız olarak .m4a formatına çevirir.
        """
        if not FFMPEG_EXE.exists():
            return
        try:
            for dosya in self.download_dir.glob(f"{hedef_isim}*"):
                if not dosya.is_file():
                    continue
                ext = dosya.suffix.lower()
                if ext in (".aac", ".mp4", ".ts", ".eac3", ".ec3"):
                    hedef_m4a = dosya.with_suffix(".m4a")
                    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
                    res = subprocess.run(
                        [str(FFMPEG_EXE), "-y", "-i", str(dosya), "-c", "copy", str(hedef_m4a)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=creationflags,
                    )
                    if res.returncode == 0 and hedef_m4a.exists():
                        dosya.unlink(missing_ok=True)
                        self._log_yaz(f"[Format] Ses dosyası .m4a formatına düzenlendi: {hedef_m4a.name}\n")
        except Exception:
            pass

    # ------------------------------------------------------------------------
    # MANIFEST ANALİZİ VE İNDİRME İŞLEMLERİ
    # ------------------------------------------------------------------------
    def manifest_analiz_et(self):
        if self.calisiyor:
            return
        gorev = self.komutu_olustur(sadece_analiz=True)
        if not gorev:
            return

        self.notebook.select(self.tab_log)
        self.log_text.delete("1.0", "end")
        self._ilerleme_sifirla("🔍 Manifest akışları analiz ediliyor...")
        self._log_yaz(f"[Analiz] Manifest taranıyor: {gorev['url']}\n" + "-" * 75 + "\n")
        self._hata_yaz("🔍 Yayın içindeki görüntü, ses ve altyazı kanalları analiz ediliyor...")
        threading.Thread(
            target=self._calistir_worker, args=(gorev, True), daemon=True
        ).start()

    def indirmeyi_baslat(self):
        if self.calisiyor:
            return
        gorev = self.komutu_olustur(sadece_analiz=False)
        if not gorev:
            return

        self.kullanici_durdurdu = False
        self.notebook.select(self.tab_log)
        self.log_text.delete("1.0", "end")
        self._ilerleme_sifirla("🚀 İndirme başlatılıyor...")

        # Geçmişe hemen kaydet (sonrasında Başarılı/Hatalı olarak güncellenecek)
        self._gecmise_ekle(
            raw_name=gorev["raw_name"],
            final_name=gorev["final_name"],
            suffix=gorev["suffix"],
            url=gorev["url"],
            key=self.key_var.get().strip(),
            status="İndiriliyor...",
        )

        self._log_yaz(
            f"[Başlatılıyor] Dosya Adı: {gorev['final_name']}\n"
            f"[Kayıt Klasörü] {self.download_dir}\n"
            + "=" * 75 + "\n"
        )
        self._hata_yaz("⏳ İndirme işlemi devam ediyor... Hız ve ilerleme yukarıdaki panelden canlı izlenebilir.")
        threading.Thread(
            target=self._calistir_worker, args=(gorev, False), daemon=True
        ).start()

    def islemi_durdur(self):
        self.kuyruk_calisiyor = False
        if self.aktif_islem and self.calisiyor:
            try:
                self.kullanici_durdurdu = True
                self.aktif_islem.terminate()
                self._log_yaz("\n[Kullanıcı] İşlem durduruldu.\n")
                self._ilerleme_guncelle({"stage": "⏹ İşlem durduruldu"}, zorla=True)
                self._hata_yaz("⏹ İşlem kullanıcı tarafından durduruldu.")
            except Exception as e:
                self._log_yaz(f"\n[Hata] Durdurma hatası: {e}\n")

    def _klasor_boyutu_hesapla(self, hedef_isim: str) -> int:
        """Aktif indirmenin geçici ve çıktı dosyalarının toplam boyutunu bayt olarak hesaplar."""
        toplam = 0
        try:
            for kok in (self.temp_work_dir, self.download_dir):
                if not kok.exists():
                    continue
                for oge in kok.iterdir():
                    if not oge.name.startswith(hedef_isim):
                        continue
                    if oge.is_file():
                        try:
                            toplam += oge.stat().st_size
                        except OSError:
                            pass
                    elif oge.is_dir():
                        for alt in oge.rglob("*"):
                            if alt.is_file():
                                try:
                                    toplam += alt.stat().st_size
                                except OSError:
                                    pass
        except Exception:
            pass
        return toplam

    def _disk_hiz_izleyici(self, hedef_isim: str, dur_olayi: threading.Event, son_stdout_hiz_ref: list):
        """
        Özellikle 1 Segment (tek parça büyük MP4) indirmelerinde N_m3u8DL-RE stdout'tan
        hız göndermese bile diskteki anlık büyümeden indirme hızını ve inen boyutu canlı gösterir.
        """
        onceki_boyut = self._klasor_boyutu_hesapla(hedef_isim)
        onceki_zaman = time.monotonic()

        while not dur_olayi.wait(0.8):
            simdi = time.monotonic()
            # Stdout'tan son 1.8 saniye içinde canlı hız geldiyse disk tahminini gösterme
            if (simdi - son_stdout_hiz_ref[0]) < 1.8:
                onceki_boyut = self._klasor_boyutu_hesapla(hedef_isim)
                onceki_zaman = simdi
                continue

            guncel_boyut = self._klasor_boyutu_hesapla(hedef_isim)
            dt = max(simdi - onceki_zaman, 0.1)
            fark = max(0, guncel_boyut - onceki_boyut)
            hiz_bps = fark / dt

            if guncel_boyut > 0:
                bilgi = {
                    "size": f"{boyut_formatla(guncel_boyut)} (İniyor...)",
                }
                if hiz_bps > 0:
                    bilgi["speed"] = f"{boyut_formatla(hiz_bps)}/s"
                self._ilerleme_guncelle(bilgi, zorla=True)

            onceki_boyut = guncel_boyut
            onceki_zaman = simdi

    def _calistir_worker(self, gorev: dict, sadece_analiz: bool):
        self.calisiyor = True
        self.root.after(0, lambda: self.baslat_btn.configure(state="disabled"))
        self.root.after(0, lambda: self.durdur_btn.configure(state="normal"))

        tum_cikti = []
        return_code = -1
        cmd = gorev["cmd"]
        url = gorev["url"]
        log_file = gorev["log_file"]

        izleyici_dur = threading.Event()
        son_stdout_hiz_ref = [0.0]

        if not sadece_analiz:
            threading.Thread(
                target=self._disk_hiz_izleyici,
                args=(gorev["final_name"], izleyici_dur, son_stdout_hiz_ref),
                daemon=True,
            ).start()

        try:
            self.download_dir.mkdir(parents=True, exist_ok=True)
            self.temp_work_dir.mkdir(parents=True, exist_ok=True)
            creationflags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
            # cwd olarak download_dir verilir (temp_work_dir verilmez!), böylece N_m3u8DL-RE
            # --tmp-dir klasörünü silerken Windows 'used by another process' kilidine takılmaz.
            self.aktif_islem = subprocess.Popen(
                cmd,
                cwd=str(self.download_dir),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=0,
                creationflags=creationflags,
            )

            # ANSI imleç kodları ve \r/\n ayrıştırması: hiçbir satır tamponda takılı kalmaz
            stdout_pipe = self.aktif_islem.stdout
            kalan_parca = ""
            while True:
                chunk = stdout_pipe.read(4096)
                if not chunk:
                    break
                text_chunk = chunk.decode("utf-8", errors="replace")
                birlesik = kalan_parca + text_chunk

                # Eğer bloğun sonunda satır sonu / ANSI imleç kodu yoksa, son tamamlanmamış parçayı
                # sadece kısa bir normal metinse sakla; ilerleme bilgisi içeriyorsa hemen işle!
                son_karakter_bitti = birlesik.endswith(("\n", "\r")) or bool(
                    re.search(r"\x1b\[(?:\d*[EFGHKABCD]|\d*;\d*[Hf])$", birlesik)
                )
                satirlar = temizle_ve_satirlara_bol(birlesik)
                if not son_karakter_bitti and satirlar:
                    son = satirlar[-1]
                    # İlerleme verisi veya tam log satırı değilse bir sonraki chunk ile birleşsin
                    if not re.search(r"(?:%|MBps|KBps|MB/s|KB/s|Start downloading|Binary merging|Decrypting|Muxing)", son, re.IGNORECASE) and len(son) < 120:
                        kalan_parca = son
                        satirlar = satirlar[:-1]
                    else:
                        kalan_parca = ""
                else:
                    kalan_parca = ""

                for temiz in satirlar:
                    if not sadece_analiz:
                        bilgi = ilerleme_satiri_cozumle(
                            temiz, canli_limit_sn=gorev.get("live_limit_sec", 0)
                        )
                        if bilgi:
                            if "speed" in bilgi or "percent" in bilgi:
                                son_stdout_hiz_ref[0] = time.monotonic()
                            zorla = any(
                                k in bilgi for k in ("stage", "bar_kind", "reset_bar", "pulse")
                            )
                            self._ilerleme_guncelle(bilgi, zorla=zorla)

                    if not canli_spam_satiri_mi(temiz):
                        tum_cikti.append(temiz + "\n")
                        self._log_yaz(temiz + "\n")

            if kalan_parca.strip():
                for temiz in temizle_ve_satirlara_bol(kalan_parca):
                    tum_cikti.append(temiz + "\n")
                    self._log_yaz(temiz + "\n")

            self.aktif_islem.wait()
            return_code = self.aktif_islem.returncode

        except Exception as e:
            hata_str = f"\n[Kritik Hata] N_m3u8DL-RE çalıştırılamadı: {e}\n"
            tum_cikti.append(hata_str)
            self._log_yaz(hata_str)

        finally:
            izleyici_dur.set()
            self.calisiyor = False
            self.aktif_islem = None
            self.root.after(0, lambda: self.baslat_btn.configure(state="normal"))
            self.root.after(0, lambda: self.durdur_btn.configure(state="disabled"))

        birlesik_cikti = "".join(tum_cikti)

        if sadece_analiz:
            akislar = [
                satir.strip()
                for satir in tum_cikti
                if any(k in satir for k in ["Vid ", "Aud ", "Sub ", "Extracted,"])
            ]
            if akislar:
                ozet = "✅ YAYINDA BULUNAN AKIŞLAR (Görüntü / Ses / Altyazı):\n" + "\n".join(
                    f"• {a.split('INFO :')[-1].strip()}" for a in akislar[:12]
                )
                self._hata_yaz(ozet)
                self._ilerleme_guncelle({"percent": 100.0, "stage": "✅ Analiz Tamamlandı"}, zorla=True)
            else:
                rapor = hata_analiz_et(birlesik_cikti, return_code, url, self.format_secim.get())
                self._hata_yaz(rapor)
                self._ilerleme_guncelle({"stage": "⚠️ Analiz Başarısız"}, zorla=True)
        else:
            if return_code == 0 and not self.kullanici_durdurdu:
                olusan_dosya = self._canli_parcalari_birlestir(
                    gorev["final_name"], sadece_ses=gorev["audio_only"]
                )
                if gorev["audio_only"]:
                    self._sadece_ses_m4a_garantile(gorev["final_name"])
                silinen = log_temizle_basarili(self.temp_work_dir)
                try:
                    if self.temp_work_dir.exists() and not any(self.temp_work_dir.iterdir()):
                        self.temp_work_dir.rmdir()
                except Exception:
                    pass
                self._gecmis_durum_guncelle(url, "✅ Başarılı")
                self._ilerleme_guncelle(
                    {
                        "bar_kind": "video",
                        "pulse": False,
                        "percent": 100.0,
                        "stage": f"✅ Tamamlandı: {gorev['final_name']}",
                        "eta": "00:00:00",
                    },
                    zorla=True,
                )
                kayit_yol = str(olusan_dosya) if olusan_dosya else f"{self.download_dir}\\{gorev['final_name']}{self._aktif_uzanti_tahmin()}"
                rapor = (
                    f"✅ İŞLEM BAŞARIYLA TAMAMLANDI!\n"
                    f"• Kaydedilen Dosya: {kayit_yol}\n"
                    f"• Temizlik: Tüm log kayıtları ({silinen} adet) otomatik olarak silindi."
                )
                self._hata_yaz(rapor)
                self._log_yaz("\n" + "=" * 75 + "\n" + rapor + "\n")
                q_idx = gorev.get("queue_index", -1)
                if 0 <= q_idx < len(self.kuyruk):
                    self.kuyruk[q_idx]["status"] = "✅ Tamamlandı"
                    self.root.after(0, self._kuyruk_tablosunu_yenile)
                if self.kuyruk_calisiyor and not self.kullanici_durdurdu:
                    self.root.after(500, self._sonraki_kuyruk_ogesini_baslat)
            elif self.kullanici_durdurdu:
                self._gecmis_durum_guncelle(url, "⏹ Durduruldu")
                q_idx = gorev.get("queue_index", -1)
                if 0 <= q_idx < len(self.kuyruk):
                    self.kuyruk[q_idx]["status"] = "⏹ Durduruldu"
                    self.root.after(0, self._kuyruk_tablosunu_yenile)
            else:
                self._gecmis_durum_guncelle(url, "❌ Hatalı")
                self._ilerleme_guncelle({"stage": "❌ İndirme Hatası (Log korundu)"}, zorla=True)
                # C# unhandled exception gibi sadece ekrana düşen hataları da log dosyasına ekle
                if log_file and log_file.exists() and tum_cikti:
                    try:
                        with open(log_file, "a", encoding="utf-8", errors="replace") as lf:
                            lf.write("\n\n--- CONSOLE OUTPUT (TAIL) ---\n")
                            lf.write("".join(tum_cikti[-60:]))
                    except Exception:
                        pass
                rapor = hata_analiz_et(
                    birlesik_cikti, return_code, url, self.format_secim.get(), log_dosyasi=log_file
                )
                self._hata_yaz(rapor)
                self._log_yaz("\n" + "=" * 75 + "\n" + rapor + "\n")
                q_idx = gorev.get("queue_index", -1)
                if 0 <= q_idx < len(self.kuyruk):
                    self.kuyruk[q_idx]["status"] = "❌ Hatalı"
                    self.root.after(0, self._kuyruk_tablosunu_yenile)
                if self.kuyruk_calisiyor and not self.kullanici_durdurdu:
                    self.root.after(500, self._sonraki_kuyruk_ogesini_baslat)


if __name__ == "__main__":
    root = tk.Tk()
    app = IndiriciProApp(root)
    root.mainloop()
