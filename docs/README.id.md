# NVDA MCP

NVDA MCP menghubungkan asisten AI dengan pembaca layar [NVDA](https://www.nvaccess.org) melalui
[Model Context Protocol](https://modelcontextprotocol.io) (MCP).
Asisten bisa membaca apa yang dibaca NVDA dan mendengar apa yang diucapkan NVDA. Jika Anda izinkan, asisten juga
bisa menekan tombol, dan Anda mendengar setiap langkahnya lewat NVDA, seolah-olah Anda sendiri yang menekannya.

## Mengapa add-on ini ada

Asisten AI sekarang bisa mengerjakan sesuatu di komputer, bukan hanya menjawab pertanyaan. Kebanyakan bekerja
dengan melihat tangkapan layar lalu mengeklik apa yang terlihat. Bagi pengguna pembaca layar, ada dua masalah:

- **Anda tidak bisa mengikuti apa yang dikerjakan asisten.** Ia mengeklik hal-hal yang tidak pernah Anda dengar,
  di tempat yang mungkin tidak ditampilkan pembaca layar Anda.
- **Tangkapan layar bukan yang Anda alami.** Yang penting bagi pengguna pembaca layar adalah kontrol mana yang
  sedang fokus, nama, peran dan statusnya, serta apa yang diucapkan NVDA tentangnya. Gambar layar tidak memuat
  sebagian besar informasi itu.

NVDA sudah mengetahui semua itu, karena begitulah cara Anda memakai komputer. NVDA MCP memberi asisten pandangan
yang sama: kontrol yang sedang fokus, pohon aksesibilitas, teks dokumen atau halaman web, dan persis apa yang
diucapkan NVDA. Saat asisten bertindak, ia memakai keyboard melalui NVDA, seperti yang Anda lakukan, dan NVDA
mengumumkan hasilnya. Anda dan asisten bekerja dari informasi yang sama, dan kendali tetap di tangan Anda.

## Kegunaannya

Untuk pengguna NVDA:

- **"NVDA tadi bilang apa?"** Asisten membaca riwayat ucapan NVDA, jadi Anda bisa bertanya tentang sesuatu yang
  terlewat, atau meminta ringkasan dialog yang panjang.
- **Melewati aplikasi yang membingungkan atau tidak aksesibel.** Tanyakan apa isi sebuah jendela, di mana sebuah
  kontrol, atau mengapa sebuah tombol tidak bernama, dan dapatkan jawaban berdasarkan apa yang benar-benar
  dilihat NVDA.
- **Mengerjakan tugas berulang.** Asisten bisa berpindah di dalam aplikasi dengan keyboard, mengetik teks,
  berganti jendela, dan menunggu sesuatu terjadi, misalnya balasan chat.
- **Belajar.** Tanyakan perintah NVDA apa saja yang berlaku di tempat Anda berada, atau apa fungsi sebuah tombol di sini.
- **Membuat aplikasi bisa dipakai.** Katakan kepada asisten "NVDA cuma bilang tombol di sini". Asisten mencari
  apa yang tidak bisa dibaca NVDA, menulis add-on kecil yang memperbaikinya, mengujinya dengan NVDA, lalu
  mengemasnya supaya bisa Anda pasang.
- **Membaca yang tidak bisa dibaca NVDA.** Saat sebuah aplikasi hanya terbaca "panel", asisten bisa membaca
  teks di layar dengan pengenalan teks Windows, seperti NVDA+R.
- **Melaporkan masalah.** Asisten mengumpulkan faktanya dan menulis laporan bug untuk pembuat aplikasi,
  untuk Anda kirim sendiri.
- **Bertanya ke AI mana pun, bahkan tanpa MCP.** Satu perintah NVDA menyalin apa yang dilihat NVDA di tempat
  Anda berada, siap ditempel ke ChatGPT, Gemini, atau chat apa pun.

Untuk developer dan penguji:

- **Melihat apa yang diumumkan NVDA** untuk setiap kontrol tanpa memindahkan fokus, dan menemukan kontrol yang
  tidak berlabel atau tidak bersuara.
- **Memeriksa urutan Tab** sebuah dialog atau halaman: nama ganda, jebakan keyboard, kontrol yang tidak diucapkan NVDA.
- **Mencari tahu mengapa NVDA diam**: merekam event yang ditangani NVDA dan apa yang diucapkannya untuk masing-masing.
- **Tes regresi**: merekam apa yang diucapkan NVDA selama serangkaian penekanan tombol, lalu membandingkannya
  dengan percobaan berikutnya.
- **Mengembangkan add-on NVDA lebih cepat**: membaca log NVDA, melihat info developer seperti NVDA+F1,
  dan memuat ulang kode add-on.

## Untuk siapa

- **Pengguna tunanetra dan low vision** yang memakai NVDA dan menginginkan asisten AI yang bekerja bersama pembaca
  layar mereka, bukan mengakalinya.
- **Developer add-on NVDA**, yang bisa menguji apa yang diucapkan NVDA karena add-on mereka tanpa melakukan
  setiap langkah secara manual.
- **Developer aplikasi Windows dan situs web**, yang ingin memeriksa hasil kerja mereka dengan pembaca layar sungguhan.
- **Penguji aksesibilitas, auditor, dan tim QA**, yang membutuhkan pemeriksaan berulang atas apa yang diumumkan
  pembaca layar.
- **Pelatih dan staf dukungan** yang membantu pengguna pembaca layar dan ingin memahami apa yang mereka dengar.

## Yang dibutuhkan

- Windows dengan NVDA 2025.1 atau lebih baru.
- Asisten AI yang mendukung MCP, misalnya Claude Code, Claude Desktop, Codex CLI, Cursor, atau VS Code.
- [uv](https://docs.astral.sh/uv/), yang mengunduh dan menjalankan server NVDA MCP untuk Anda.
  Jika Anda sudah punya Python 3.11 atau lebih baru, Anda bisa memakai pip atau pipx.

NVDA MCP terdiri dari dua bagian: add-on ini, dan program kecil bernama **server nvda-mcp** yang dijalankan oleh
asisten Anda. Add-on diambil dari Add-on Store NVDA; servernya dari Python Package Index (PyPI).
Keduanya gratis dan open source.

## Cara memasang

1. **Pasang add-on.** Di NVDA, buka Alat, lalu Add-on Store. Cari NVDA MCP, pasang, lalu mulai ulang NVDA.
2. **Pasang uv**, jika belum ada. Buka command prompt dan jalankan:

   ```
   winget install --id=astral-sh.uv -e
   ```

   Tutup command prompt lalu buka yang baru, supaya uv ditemukan.
3. **Hubungkan asisten Anda.** Di NVDA, buka Pengaturan (NVDA+N, Preferensi, Pengaturan), lalu kategori
   **NVDA MCP**. Pilih asisten Anda di *Siapkan klien MCP ini* dan tekan **Pasang sekarang**.
   NVDA bertanya dulu sebelum mengubah apa pun, lalu meminta Anda memulai ulang asistennya.
   - Untuk Claude Desktop, Antigravity, dan Cursor, NVDA MCP menambahkan dirinya ke file pengaturan asisten,
     membiarkan isi lainnya, dan menyimpan salinan file lama dengan tambahan `.bak` di namanya.
   - Untuk Claude Code dan Codex CLI, NVDA MCP menjalankan perintah penyiapan asisten itu untuk Anda.
   - Untuk asisten lain, pilih *Klien lain*, tekan **Salin perintah penyiapan**, lalu tempelkan pengaturannya
     ke file pengaturan MCP asisten itu. **Salin perintah penyiapan** juga bisa dipakai untuk semua asisten di
     atas, kalau Anda ingin melakukannya sendiri.

   Perintahnya mirip `claude mcp add --scope user nvda -- uvx nvda-mcp==1.0.0`: perintah ini menyuruh asisten
   Anda menjalankan versi server yang cocok dengan add-on Anda.

Jalankan asisten Anda dan tanyakan misalnya "apa yang sedang fokus di NVDA?". Ia menjawab tanpa menekan tombol apa pun.

### Dengan pip atau pipx, bukan uv

```
pipx install nvda-mcp
claude mcp add --scope user nvda -- nvda-mcp
```

Pakai versi yang sama dengan add-on, dan perbarui keduanya bersamaan. Dengan pip biasa, jalankan
`python -m nvda_mcp` jika perintah `nvda-mcp` tidak ditemukan.

## Keamanan

Membaca selalu diizinkan. Semua yang bertindak di komputer Anda **mati sampai Anda menyalakannya**:
menekan tombol, mengetik, berganti jendela, mengaktifkan kontrol, berpindah di halaman web,
menjalankan perintah NVDA, dan memuat ulang add-on.

Di Pengaturan NVDA, kategori **NVDA MCP**:

- **Izinkan klien MCP, seperti asisten AI, terhubung ke NVDA** (menyala secara bawaan).
- **Izinkan klien MCP menekan tombol** (mati secara bawaan).
- **Tanyakan sebelum penekanan tombol pertama setelah NVDA dimulai** (menyala secara bawaan). NVDA bertanya
  kepada Anda, dengan tombol **Tidak** yang terfokus, dan menyebut nama program yang meminta, sesuai nama yang
  diberikan program itu sendiri.
- **Hanya izinkan klien MCP mengontrol aplikasi ini** (kosong secara bawaan, artinya semua).
  Misalnya `notepad, winword`. Aplikasi lain ditolak.
- **Catat setiap aksi yang dilakukan klien MCP** (menyala secara bawaan), di `%APPDATA%\nvda\nvdaMcp\actions.log`.
- **Izinkan klien MCP membaca HTML halaman web melalui remote debugging browser** (mati secara bawaan),
  untuk pengembang add-on aplikasi web. Browser juga bertanya kepada Anda sebelum setiap sambungan baru.
- **Izinkan klien MCP mengambil gambar kontrol di layar** (mati secara bawaan), untuk pengembang yang ingin
  membandingkan tampilan sebuah kontrol dengan apa yang diucapkan NVDA. Tetap berfungsi saat Tirai Layar menyala.
- **Jumlah ucapan yang diingat** (500 secara bawaan).

Perintah di Gestur Masukan, kategori NVDA MCP (tanpa tombol bawaan):

- Melaporkan apakah NVDA MCP berjalan dan apakah boleh menekan tombol.
- Menghentikan klien MCP menekan tombol sampai Anda menyetujui lagi.
- Membuka catatan aksi yang telah dilakukan klien MCP.
- Menyalin apa yang dilihat NVDA di sini, untuk ditempel ke obrolan dengan asisten AI mana pun: aplikasinya,
  kontrol yang terfokus, kontrol di jendela itu, dan ucapan NVDA terakhir. Bisa dipakai tanpa klien MCP.

Cara koneksinya dilindungi:

- Add-on hanya mendengarkan di komputer Anda sendiri (127.0.0.1), di port acak.
- Setiap permintaan butuh token rahasia yang dibuat baru setiap kali NVDA dimulai, disimpan di tempat yang hanya
  bisa dibaca akun Windows Anda.
- Permintaan dari halaman web ditolak.
- Tidak ada yang berjalan di layar aman (masuk Windows, UAC), dan permintaan ditolak saat Windows terkunci.
- Pengaturannya disimpan di konfigurasi dasar NVDA, jadi profil konfigurasi tidak bisa menyalakan penekanan tombol.

## Privasi

Add-on ini sendiri tidak mengirim apa pun ke internet. Tetapi **apa yang dibaca asisten sampai ke asisten itu**,
dan sebagian besar asisten mengirimkannya ke server penyedianya. Itu bisa mencakup teks di layar Anda,
apa yang diucapkan NVDA, isi dokumen dan jendela chat, serta apa pun yang dibacakan NVDA saat Anda mengetik.
Asisten juga bisa membaca jendela yang tidak sedang Anda lihat, misalnya jendela chat di belakang
atau di virtual desktop lain.

Jika Anda mengizinkannya membaca HTML halaman web (mati secara bawaan), perhatikan bahwa menyalakan remote
debugging di browser membuat program yang Anda izinkan bisa menjangkau semua tab dan situs yang sedang
login di browser itu, dan program lain di komputer Anda juga bisa meminta tersambung. NVDA MCP hanya membaca
halaman yang sedang Anda kerjakan, tidak pernah menjalankan skrip atau membaca cookie, dan NVDA memberi tahu
sebelum tersambung. Matikan remote debugging setelah selesai.

Jika Anda mengizinkannya mengambil gambar kontrol (mati secara bawaan), setiap gambar memperlihatkan bagian
layar itu, apa pun isinya, dan dikirim ke penyedia asisten seperti semua yang dibacanya.
Setiap gambar dicatat di catatan aksi.

Jika Anda memakai perintah yang menyalin apa yang dilihat NVDA, baca dulu isinya sebelum dikirim:
isinya memuat kontrol dan teks jendela itu, serta ucapan NVDA terakhir, yang bisa berasal dari jendela lain.

Asisten bisa membaca teks di layar dengan pengenalan teks Windows (`nvda_recognize_text`), seperti NVDA+R.
Yang dibaca adalah jendela atau kontrol yang diminta, apa pun yang tampil di sana, dan setiap pemakaiannya
dicatat di catatan aksi.

- Sebelum mengerjakan sesuatu yang pribadi, seperti perbankan, kata sandi, atau pesan pribadi,
  tutup asisten Anda atau matikan *Izinkan klien MCP terhubung* di pengaturan NVDA.
- Riwayat ucapan NVDA hanya disimpan di memori, dan terhapus saat NVDA dimulai ulang.
- Catatan aksi tetap berada di komputer Anda.

## Alat

Daftar lengkap alat yang dilihat asisten ada di [README berbahasa Inggris](../README.md#tools).
Ada juga prompt siap pakai yang memandu asisten mengerjakan tugas umum dengan alat-alat itu, dalam urutan
yang tepat:

- Untuk semua orang: `explain_screen` (saya di mana dan apa yang bisa saya lakukan di sini), `make_accessible`
  (mencari apa yang menghalangi NVDA di sebuah aplikasi, menulis add-on kecil untuk memperbaikinya, mengujinya,
  lalu mengemasnya) dan `report_problem` (menulis laporan bug untuk pembuat aplikasi).
- Untuk pengembang: `audit_accessibility`, `build_addon`, `why_silent` dan `check_labels`.

Klien yang mendukung prompt MCP menampilkannya sebagai perintah; di Claude Code, misalnya, ketik
`/mcp__nvda__make_accessible`.
Setiap aksi melaporkan apa yang diucapkan NVDA sesudahnya dan ke mana fokus berpindah, dan bisa menunggu
pengumuman yang diharapkan, misalnya "terkirim" atau judul sebuah dialog.

## Dukung NVDA MCP

NVDA MCP gratis, dan dibuat di waktu luang. Jika add-on ini membantu Anda, Anda bisa mendukung pengembangannya
dengan berdonasi melalui [PayPal](https://paypal.me/rafli23115). Ada juga tombol **Donasi** di Pengaturan NVDA,
kategori NVDA MCP.

## Lainnya

- [Memakai NVDA MCP](using.md) (bahasa Inggris): memperbarui, memulai ulang server, dan yang perlu dilakukan
  jika ada yang tidak berjalan.
- [Yang baru](../CHANGELOG.md) di setiap versi (bahasa Inggris).
- Pertanyaan dan laporan bug: [GitHub issues](https://github.com/InfiArtt/nvda-mcp/issues).

## Lisensi

Hak cipta (C) 2026 InfiArtt.
NVDA MCP adalah perangkat lunak bebas di bawah [GNU General Public License, versi 2](../COPYING.txt) atau yang lebih baru.
Perangkat lunak lain yang dipakainya beserta lisensinya tercantum di [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)
(bahasa Inggris).
