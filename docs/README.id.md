# NVDA MCP

NVDA MCP menghubungkan asisten AI dengan pembaca layar [NVDA](https://www.nvaccess.org) melalui
[Model Context Protocol](https://modelcontextprotocol.io) (MCP).
Asisten bekerja dari apa yang diketahui dan diucapkan NVDA, bertindak lewat NVDA dengan keyboard dan mouse, dan
mendengar hasilnya. Karena itu asisten bisa mengerjakan yang paling dibutuhkan pengguna pembaca layar: membuat
aplikasi yang tidak bisa dipakai dengan NVDA menjadi bisa dipakai, menjangkau yang tidak terjangkau keyboard,
mencari tahu mengapa NVDA diam, dan membantu orang lain dari jauh dengan MCP Access. Anda mendengar setiap
langkahnya, dan kendali tetap di tangan Anda.

## Mengapa add-on ini ada

Masih banyak aplikasi yang tidak bisa dipakai dengan pembaca layar. NVDA hanya mengucapkan "tombol" atau
"panel", dan orang yang membutuhkan aplikasi itu tidak bisa memakainya. Selama ini hanya ada dua jalan: menunggu
pembuat aplikasinya memperbaiki, yang sering tidak pernah terjadi, atau menulis add-on NVDA, yang butuh keahlian
dan berjam-jam pengujian dengan telinga, dengan pengguna tunanetra mencoba setiap perubahan lalu melaporkan apa
yang diucapkan NVDA.

Asisten AI yang bisa menulis kode tidak menyelesaikan ini sendirian, karena ia tidak bisa mendengar apa yang
didengar pengguna pembaca layar. Data aksesibilitas mentah dari Windows bukan apa yang diucapkan NVDA: NVDA
menggabungkan beberapa antarmuka aksesibilitas, mode jelajah, dan add-on yang Anda pasang. Asisten yang memakai
komputer dengan melihat tangkapan layar juga meninggalkan pengguna pembaca layar: ia mengeklik hal-hal yang tidak
pernah Anda dengar, dan gambar layar bukan apa yang Anda alami.

NVDA MCP memberi asisten pandangan dan suara NVDA: kontrol yang sedang fokus, pohon aksesibilitas, teks dokumen
atau halaman web, dan persis apa yang diucapkan NVDA. Dengan itu, asisten bisa menyelesaikan seluruh
lingkarannya sendiri. Ia mencari apa yang tidak bisa dibaca NVDA, menulis add-on kecil untuk memperbaikinya,
memuatnya ke NVDA yang sedang berjalan, lalu mendengar sendiri apakah NVDA sekarang mengucapkan yang benar.
Orang yang membutuhkan perbaikan tidak lagi menjadi pengujinya: cukup bilang "ini tidak bisa dipakai",
mendengarkan, dan memutuskan. Dari pengguna menjadi pembuat.

Saat asisten bertindak, ia memakai keyboard melalui NVDA, seperti yang Anda lakukan, hanya setelah Anda
mengizinkannya, dan NVDA mengumumkan setiap langkahnya. Dengan MCP Access, asisten juga bisa membantu orang lain
dari jauh, lewat NVDA mereka dan dengan izin mereka.

Add-on [Proton VPN Accessibility](https://github.com/InfiArtt/protonvpn-nvda) dan
[NYK DAEMON82 MKN-09 Access](https://github.com/InfiArtt/nyk-daemon82-nvda) dibuat dengan cara ini.

## Kegunaannya

Untuk pengguna NVDA:

- **Membuat aplikasi bisa dipakai.** Katakan kepada asisten "NVDA cuma bilang tombol di sini". Asisten mencari
  apa yang tidak bisa dibaca NVDA, menulis add-on kecil yang memperbaikinya, mengujinya dengan NVDA, lalu
  mengemasnya supaya bisa Anda pasang.
- **Mendapat bantuan dari jauh.** Dengan MCP Access, orang yang Anda percaya membantu dengan asisten AI-nya
  lewat NVDA Anda, sementara Anda tetap memegang kendali dan mendengar setiap langkahnya.
- **Membaca yang tidak bisa dibaca NVDA.** Saat sebuah aplikasi hanya terbaca "panel", asisten bisa membaca
  teks di layar dengan pengenalan teks Windows, seperti NVDA+R.
- **Menjangkau yang tidak terjangkau keyboard.** Tombol dan kenop yang digambar di kanvas, seperti di banyak
  plugin audio, game, dan installer: asisten menemukannya lalu mengeklik, men-scroll, atau menyeret dengan mouse,
  dan memberi tahu apa yang terjadi.
- **Melewati aplikasi yang membingungkan.** Tanyakan Anda sedang di mana, apa isi sebuah jendela, di mana sebuah
  kontrol, atau mengapa sebuah tombol tidak bernama, dan dapatkan jawaban berdasarkan apa yang benar-benar
  dilihat NVDA, lengkap dengan tombol yang perlu ditekan.
- **Melaporkan masalah.** Asisten mengumpulkan faktanya dan menulis laporan bug untuk pembuat aplikasi,
  untuk Anda kirim sendiri.
- **Mengerjakan tugas berulang.** Asisten bisa berpindah di dalam aplikasi dengan keyboard, mengetik teks,
  berganti jendela, dan menunggu sesuatu terjadi, misalnya balasan chat.
- **Belajar.** Tanyakan perintah NVDA apa saja yang berlaku di tempat Anda berada, atau apa fungsi sebuah tombol di sini.
- **Bertanya ke AI mana pun, bahkan tanpa MCP.** Satu perintah NVDA menyalin apa yang dilihat NVDA di tempat
  Anda berada, siap ditempel ke ChatGPT, Gemini, atau chat apa pun.
- **Bertanya tentang yang Anda dengar.** Asisten bisa membaca apa yang diucapkan NVDA, untuk mengulang sesuatu
  yang terlewat atau meringkas dialog yang panjang.

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
- **Teman, relawan, pelatih, dan staf dukungan** yang membantu pengguna pembaca layar, dari sebelahnya atau,
  dengan MCP Access, dari jauh.

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

## MCP Access: bantuan dari jauh

**Akses awal (early access).** MCP Access masih baru: untuk sekarang gratis selagi kami mempelajari cara orang
memakainya, dan bisa berubah. Ceritakan pengalaman Anda di [GitHub issues](https://github.com/InfiArtt/nvda-mcp/issues).

MCP Access membuat orang yang Anda percaya bisa membantu dari komputernya sendiri, dengan asisten AI-nya yang
bekerja lewat NVDA **Anda**. Asisten mereka melihat apa yang dilihat NVDA di komputer Anda, mengobrol dengan Anda,
dan, kalau Anda izinkan, menekan tombol dan memakai mouse di sana. Anda mendengar semua yang terjadi. Orang yang
dibantu cukup punya NVDA dan add-on ini: tanpa asisten AI, akun, atau langganan.

### Meminta bantuan

1. Di Gestur Masukan, kategori NVDA MCP, beri tombol untuk *Membagikan komputer ini ke penolong lewat MCP Access*
   dan *Membuka jendela MCP Access, untuk mengobrol dengan penolong*.
2. Tekan yang pertama. NVDA menyalin kode seperti `K7Q4-9XMC-4TRW-PH3N-AD6F` ke clipboard. Kirim ke penolong
   Anda, misalnya lewat pesan. Kode hanya bisa dipakai sekali, selama 10 menit.
3. Saat penolong tersambung, NVDA bertanya apakah mereka boleh melihat komputer ini, dengan **Tidak** terfokus.
   NVDA menyebut nama yang mereka berikan, misalnya "Rafli (AI assistant)", dan kode sesi singkat yang bisa Anda
   cocokkan dengan mereka.
4. Kalau asisten mereka ingin menekan tombol, memakai mouse, atau mengambil gambar layar, NVDA bertanya lagi,
   sekali untuk tombol dan mouse dan sekali untuk gambar di sesi ini. Anda mendengar setiap tombol.
5. Mengobrol dengan mereka di jendela MCP Access: percakapan Anda, kolom untuk membalas (Enter mengirim), dan
   tombol untuk berhenti berbagi. Pesan dari mereka didahului bunyi dan diucapkan sebagai pesan dari mereka,
   walaupun jendelanya tertutup. Escape menutup jendela; berbagi tetap berjalan.
6. Berhenti berbagi kapan saja, dengan tombol di jendela itu atau *Berhenti membagikan komputer ini lewat MCP
   Access*. Berbagi juga berakhir setelah dua jam.

### Menolong orang lain

Tempel kode yang mereka kirim ke asisten Anda, misalnya "bantu temanku, kodenya K7Q4-9XMC-4TRW-PH3N-AD6F", atau
pilih prompt siap pakai `help_someone`. Asisten tersambung dengan `nvda_access_connect`, lalu semua alat NVDA
bekerja di komputer mereka sampai `nvda_access_disconnect`. Asisten mengobrol dengan mereka lewat
`nvda_access_send_message` dan `nvda_access_messages`, dan mereka melihatnya sebagai "*nama Anda* (AI
assistant)", jadi mereka selalu tahu yang berbicara adalah AI. Dalam mode *talk* (`nvda_access_set_mode`),
asisten hanya membaca dan mengobrol, tanpa bertindak di komputer mereka. Kode aman ditempel: hanya sekali pakai
dan kedaluwarsa setelah 10 menit.

### Saat mereka menulis ketika Anda sedang pergi

Asisten AI hanya bekerja selama punya giliran: saat Anda menulis kepadanya, atau selama ia sedang bekerja. Pesan
dari orang yang Anda bantu tidak memulai giliran dengan sendirinya, jadi seberapa cepat pesan itu dijawab
tergantung asisten Anda:

- **Claude Code**, termasuk tab Code di aplikasi Claude: pesan mereka bisa membangunkannya. Setelah tersambung,
  asisten memantau file kotak masuk kecil dengan pemantau latar belakang, dan menjawab setiap pesan begitu
  datang, walaupun Anda sedang pergi. File itu ada di folder sementara milik Anda sendiri dan dihapus saat sesi
  berakhir.
  Orang yang Anda bantu hanya bisa meminta asisten bertindak di komputer mereka sendiri: di setiap pesan, NVDA
  MCP mengingatkan asisten Anda agar tidak pernah menjalankan program, perintah, atau file di komputer Anda
  untuk mereka. Itu instruksi, bukan kunci, jadi selama asisten memantau pesan, biarkan Claude Code tetap
  bertanya sebelum menjalankan perintah: jangan tinggalkan dalam mode yang melewati permintaan izin.
- **Antigravity, Codex, Cursor, OpenCode, dan lainnya**: sepengetahuan kami, mereka tidak bisa dibangunkan dari
  luar. Asisten menjawab selama sedang dalam giliran, dengan menunggu pesan berikutnya lewat
  `nvda_access_messages`; pesan yang datang selagi asisten mengerjakan hal lain ikut muncul di hasil berikutnya.
  Di antara giliran, pesan menunggu sampai Anda menulis lagi ke asisten Anda.

### Cara perlindungannya

- **Terenkripsi ujung ke ujung.** Kedua komputer menyepakati kunci dari kode dan kunci acak baru
  (X25519 dan AES-256-GCM). Relay di antaranya, yang dijalankan InfiArtt di `wss://infiartt.com/mcp-access/v1`
  di belakang Cloudflare, hanya meneruskan data yang tidak bisa dibacanya, dan tidak pernah melihat kodenya.
  Kode yang bocor setelah sesi selesai tidak bisa membuka sesi itu.
- **TLS 1.3 yang ketat** ke relay, dengan sertifikat yang selalu diperiksa.
- **Kode hanya sekali pakai**, kedaluwarsa setelah 10 menit, dan relay membatasi seberapa sering kode boleh dicoba.
- **Anda mengizinkan penolong dulu**, lalu sekali lagi sebelum tombol atau aksi mouse pertama dan gambar layar
  pertama mereka di setiap sesi, walaupun keduanya dimatikan di pengaturan NVDA MCP. Centang *Jangan pernah izinkan
  penolong MCP Access menekan tombol* atau *Jangan pernah izinkan penolong MCP Access mengambil gambar layar* untuk
  menolak sama sekali.
- **Beberapa alat tidak pernah bisa dipakai lewat MCP Access:** memuat ulang add-on, menjalankan perintah NVDA,
  log dan pengaturan NVDA, dan membaca HTML halaman web.
- **Kedua komputer perlu versi NVDA MCP yang sama**; kalau tidak, sambungan ditolak dengan pesan yang jelas.
- **Setiap sambungan dan aksi dicatat** di catatan aksi komputer Anda.
- Jangan pernah memberi tahu kata sandi kepada penolong, dan tutup jendela pribadi sebelum berbagi.

## Keamanan

Membaca selalu diizinkan. Semua yang bertindak di komputer Anda **mati sampai Anda menyalakannya**:
menekan tombol, mengetik, memakai mouse, berganti jendela, mengaktifkan kontrol, berpindah di halaman web,
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

Untuk MCP Access:

- **Jangan pernah izinkan penolong MCP Access menekan tombol** (mati secara bawaan; NVDA bertanya sekali per sesi).
  Ini juga berlaku untuk mouse.
- **Jangan pernah izinkan penolong MCP Access mengambil gambar layar** (mati secara bawaan; NVDA bertanya sekali
  per sesi).
- **Alamat relay MCP Access** (`wss://infiartt.com/mcp-access/v1` secara bawaan).

Perintah di Gestur Masukan, kategori NVDA MCP (tanpa tombol bawaan):

- Melaporkan apakah NVDA MCP berjalan dan apakah boleh menekan tombol.
- Menghentikan klien MCP menekan tombol sampai Anda menyetujui lagi.
- Membuka catatan aksi yang telah dilakukan klien MCP.
- Menyalin apa yang dilihat NVDA di sini, untuk ditempel ke obrolan dengan asisten AI mana pun: aplikasinya,
  kontrol yang terfokus, kontrol di jendela itu, dan ucapan NVDA terakhir. Bisa dipakai tanpa klien MCP.
- Membagikan komputer ini ke penolong lewat MCP Access, atau menyebutkan siapa yang tersambung.
- Berhenti membagikan komputer ini lewat MCP Access.
- Membuka jendela MCP Access, untuk mengobrol dengan penolong.

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
  lalu mengemasnya), `report_problem` (menulis laporan bug untuk pembuat aplikasi) dan `help_someone`
  (menolong orang lewat MCP Access dengan kode yang mereka kirim).
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
