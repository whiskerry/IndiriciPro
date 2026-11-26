# İndirici Pro

Modern, hızlı ve çok temalı **DASH (`.mpd`) / HLS (`.m3u8`)** akış indirme arayüzü (**N_m3u8DL-RE** GUI).

> **Not:** Bu proje, açık kaynaklı medya araçları (`N_m3u8DL-RE`, `FFmpeg`, `Bento4/mp4decrypt`) için geliştirilmiş bir masaüstü grafik arayüzüdür. Yalnızca yasal erişim hakkına sahip olduğunuz içeriklerin kişisel arşivi ve teknik test amaçlı kullanımı için tasarlanmıştır.

---

## Öne Çıkan Özellikler

- **Çift İndirme Motoru (`N_m3u8DL-RE` + `yt-dlp`):** `.mpd` / `.m3u8` yayınları için `N_m3u8DL-RE`; YouTube, Vimeo, Dailymotion, TikTok, X/Twitter, Instagram, Twitch ve doğrudan video dosyaları (`.mp4`, `.flv`, `.3gp`, `.webm`, `.mkv`, `.mov`, `.avi`, `.ts` vb.) için otomatik `yt-dlp`.
- **Chrome Eklentisi (`chrome-extension/`):** Tarayıcıda açtığınız sayfalardaki yayınları ve YouTube videolarını tek tıkla **İndirici Pro**'ya veya **Toplu İndirme Kuyruğu**na gönderir (`--key ` önekini ve başlıklardaki `izle` ekini otomatik temizler).
- **Çok Renkli Canlı İlerleme & Hız Paneli:** Video (Yeşil), Ses (Turuncu), Altyazı (Mavi), Birleştirme/Muxing (Mor) ve Canlı Kayıt (Kırmızı) aşamalarını anlık hız (`MB/s`), inen boyut, parça sayısı ve kalan süre ile gösterir.
- **4 Farklı Arayüz Teması:** Klasik Koyu (Catppuccin), Klasik Açık (Latte), macOS Koyu (Apple Dark) ve macOS Açık (Apple Light).
- **JSON ile Toplu İndirme Kuyruğu:** Çoklu indirme listelerini (JSON) içe aktarıp bölüm adlarını düzenleyerek sırayla otomatik indirebilirsiniz.
- **Otomatik Format Yönetimi:** Video + Ses indirmelerinde `.mkv`, yalnızca ses indirmelerinde `.m4a` çıktısı üretir.
- **Canlı Yayın Kaydı & Otomatik Birleştirme:** Süre limitli canlı kayıt alır ve kayıt sonunda parçaları otomatik olarak tek bir `.mkv` dosyasında birleştirir.
- **Son 10 İndirme Geçmişi:** Tek tıkla önceki indirmelerin bağlantısını ve parametrelerini geri doldurur.
- **Akıllı Hata Teşhisi & Otomatik Log Temizliği:** Başarılı işlemlerde gereksiz log ve geçici dosyaları siler; hata durumunda logu koruyup Türkçe çözüm önerisi sunar.
- **Tam Taşınabilir (Portable) & Kurulabilir (Setup):** İndirme klasörünü dilediğiniz gibi seçebilirsiniz.

---

## Chrome Eklentisi Kurulumu

1. `chrome-extension/` klasörünü (veya Releases sayfasındaki `IndiriciPro_Chrome_Extension.zip` dosyasını açarak) bilgisayarınızda bir yere çıkarın.
2. Chrome'da `chrome://extensions` adresini açın ve sağ üstten **Geliştirici modu**nu açın.
3. **Paketlenmemiş öğe yükle** butonuna tıklayıp `chrome-extension` klasörünü seçin.
4. **İndirici Pro** açıkken eklentide `● Bağlı` yazısı görünür ve tek tıkla yayın gönderebilirsiniz.

---

## Kurulum Seçenekleri

### 1. Kurulum Dosyası (`IndiriciPro_Setup.exe`) — Önerilen
1. **Releases** sayfasından `IndiriciPro_Setup.exe` dosyasını indirin.
2. Kurulum sihirbazını tamamlayın ve Masaüstü / Başlat Menüsü kısayolundan çalıştırın.

### 2. Taşınabilir Sürüm (`IndiriciPro_Portable.zip`)
1. **Releases** sayfasından `IndiriciPro_Portable.zip` dosyasını indirin.
2. Herhangi bir klasöre veya USB belleğe çıkartın.
3. `IndiriciPro.exe` dosyasına çift tıklayın (ayarlar ve geçmiş `data/` klasöründe saklanır).

### 3. Kaynak Koddan Çalıştırma
- Python 3.10+ (Windows, dahili `tkinter` ile)
- `tools/` klasörüne şu açık kaynak araçları yerleştirin:
  - `N_m3u8DL-RE.exe`
  - `ffmpeg.exe`
  - `mp4decrypt.exe`
- Çalıştırın:
  ```powershell
  python indirici_pro.py
  ```

---

## Kendi Derlemenizi Oluşturma

Proje kök klasöründe:
```powershell
.\scripts\build_all.ps1
```
Bu komut sırasıyla:
1. PyInstaller ile `IndiriciPro.exe` dosyasını üretir,
2. `release/IndiriciPro_Portable.zip` taşınabilir paketini oluşturur,
3. Inno Setup (`ISCC.exe`) ile `release/IndiriciPro_Setup.exe` kurulum dosyasını derler.

---

## Kullanılan Açık Kaynak Araçlar

- [N_m3u8DL-RE](https://github.com/nilaoda/N_m3u8DL-RE)
- [FFmpeg](https://ffmpeg.org/)
- [Bento4 (mp4decrypt)](https://www.bento4.com/)

## Lisans

Bu proje [MIT Lisansı](LICENSE) ile lisanslanmıştır.
