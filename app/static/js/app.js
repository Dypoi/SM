/* SM — skrip antarmuka ringan (tanpa dependensi). */
(function () {
  "use strict";

  // --- Menu samping untuk layar kecil -------------------------------------
  var sidebar = document.getElementById("sidebar");
  var backdrop = document.querySelector(".sidebar-backdrop");

  function bukaSidebar() {
    if (!sidebar) return;
    sidebar.classList.add("open");
    if (backdrop) backdrop.classList.add("show");
  }
  function tutupSidebar() {
    if (!sidebar) return;
    sidebar.classList.remove("open");
    if (backdrop) backdrop.classList.remove("show");
  }
  document.querySelectorAll("[data-sidebar-open]").forEach(function (el) {
    el.addEventListener("click", bukaSidebar);
  });
  document.querySelectorAll("[data-sidebar-close]").forEach(function (el) {
    el.addEventListener("click", tutupSidebar);
  });

  // --- Tutup pesan notifikasi ---------------------------------------------
  document.querySelectorAll(".alert-close").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var alert = btn.closest(".alert");
      if (alert) alert.remove();
    });
  });

  // --- Tab -----------------------------------------------------------------
  document.querySelectorAll("[data-tab]").forEach(function (button) {
    button.addEventListener("click", function () {
      var grup = button.closest(".tabs");
      var target = button.getAttribute("data-tab");
      if (grup) {
        grup.querySelectorAll(".tab").forEach(function (t) { t.classList.remove("active"); });
      }
      button.classList.add("active");
      document.querySelectorAll(".tab-panel").forEach(function (panel) {
        panel.classList.toggle("active", panel.getAttribute("data-panel") === target);
      });
    });
  });

  // --- Unggah berkas: klik & seret-lepas -----------------------------------
  var zone = document.querySelector("[data-upload-zone]");
  if (zone) {
    var input = zone.querySelector('input[type="file"]');
    var label = zone.querySelector("[data-file-name]");

    zone.addEventListener("click", function (event) {
      if (input && event.target !== input) input.click();
    });
    if (input && label) {
      input.addEventListener("change", function () {
        if (input.files && input.files.length) {
          label.textContent = input.files[0].name + " (" + Math.round(input.files[0].size / 1024) + " KB)";
        } else {
          label.textContent = "";
        }
      });
    }
    ["dragenter", "dragover"].forEach(function (nama) {
      zone.addEventListener(nama, function (event) {
        event.preventDefault();
        zone.classList.add("dragover");
      });
    });
    ["dragleave", "drop"].forEach(function (nama) {
      zone.addEventListener(nama, function (event) {
        event.preventDefault();
        zone.classList.remove("dragover");
      });
    });
    zone.addEventListener("drop", function (event) {
      if (input && event.dataTransfer && event.dataTransfer.files.length) {
        input.files = event.dataTransfer.files;
        input.dispatchEvent(new Event("change"));
      }
    });
  }

  // --- Konfirmasi aksi berbahaya ------------------------------------------
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.getAttribute("data-confirm"))) event.preventDefault();
    });
  });

  // --- Saring tabel secara instan (tanpa memuat ulang halaman) -------------
  document.querySelectorAll("[data-filter-target]").forEach(function (input) {
    input.addEventListener("input", function () {
      var query = input.value.toLowerCase().trim();
      var target = document.querySelector(input.getAttribute("data-filter-target"));
      if (!target) return;
      var hasil = 0;
      target.querySelectorAll("tbody tr").forEach(function (row) {
        var cocok = row.textContent.toLowerCase().indexOf(query) !== -1;
        row.style.display = cocok ? "" : "none";
        if (cocok) hasil += 1;
      });
      var info = document.querySelector("[data-filter-info]");
      if (info) info.textContent = query ? hasil + " baris cocok" : "";
    });
  });

  // --- Kirim form otomatis saat filter berubah ----------------------------
  document.querySelectorAll("[data-auto-submit] select, [data-auto-submit] input[type='checkbox']").forEach(function (el) {
    el.addEventListener("change", function () {
      var form = el.closest("form");
      if (form) form.submit();
    });
  });

  // --- Cetak ---------------------------------------------------------------
  document.querySelectorAll("[data-print]").forEach(function (btn) {
    btn.addEventListener("click", function () { window.print(); });
  });

  // --- Salin ke papan klip -------------------------------------------------
  document.querySelectorAll("[data-copy]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var teks = btn.getAttribute("data-copy");
      navigator.clipboard.writeText(teks).then(function () {
        var asal = btn.textContent;
        btn.textContent = "Tersalin!";
        setTimeout(function () { btn.textContent = asal; }, 1600);
      });
    });
  });

  // --- Pilihan siswa pada form anggota ekskul -----------------------------
  var pilihSiswa = document.querySelector("[data-siswa-picker]");
  if (pilihSiswa) {
    var cari = pilihSiswa.querySelector("[data-picker-cari]");
    var daftar = pilihSiswa.querySelector("[data-picker-daftar]");
    var nisnInput = pilihSiswa.querySelector("input[name='nisn']");
    if (cari && daftar) {
      cari.addEventListener("input", function () {
        var query = cari.value.toLowerCase().trim();
        daftar.querySelectorAll("[data-opsi]").forEach(function (opsi) {
          var cocok = opsi.getAttribute("data-cari").indexOf(query) !== -1;
          opsi.style.display = cocok ? "" : "none";
        });
      });
      daftar.addEventListener("click", function (event) {
        var opsi = event.target.closest("[data-opsi]");
        if (!opsi) return;
        event.preventDefault();
        if (nisnInput) nisnInput.value = opsi.getAttribute("data-nisn");
        if (cari) { cari.value = opsi.textContent.trim(); }
        daftar.querySelectorAll("[data-opsi]").forEach(function (item) { item.classList.remove("active"); });
        opsi.classList.add("active");
      });
    }
  }

  // --- Data wali: muncul hanya bila nama ayah kosong ------------------------
  // Aturan: nama ayah diisi -> sistem menganggap siswa tidak punya wali.
  // Isian wali yang tidak sesuai (nama ayah terisi, nama wali sama dengan
  // ayah/ibu, atau kolom wali tanpa nama) DIKOSONGKAN OTOMATIS OLEH SISTEM saat
  // disimpan. Karena itu sisi browser tidak memblokir pengiriman form — hanya
  // memberi catatan supaya pengguna tahu datanya akan dihapus sistem.
  function namaNormal(teks) {
    return (teks || "").replace(/\s+/g, " ").trim().toLowerCase();
  }

  function peringatanForm(form, teks) {
    var kotak = form.querySelector("[data-keluarga-peringatan]");
    if (!kotak) {
      kotak = document.createElement("div");
      kotak.setAttribute("data-keluarga-peringatan", "");
      kotak.className = "alert alert-warn";
      form.insertBefore(kotak, form.firstChild);
    }
    kotak.textContent = teks;
    kotak.hidden = !teks;
    if (teks) kotak.scrollIntoView({ block: "center", behavior: "smooth" });
  }

  document.querySelectorAll("[data-wali-zone]").forEach(function (zone) {
    var form = zone.closest("form");
    var ayahInput = form ? form.querySelector('[name="ayah_nama"]') : null;
    var ibuInput = form ? form.querySelector('[name="ibu_nama"]') : null;
    var namaWali = zone.querySelector('[name="wali_nama"]');
    var ask = zone.querySelector("[data-wali-ask]");
    var fields = zone.querySelector("[data-wali-fields]");
    var note = zone.querySelector("[data-wali-ayah-note]");
    var tombolHapus = zone.querySelector("[data-wali-hapus]");
    var catatanHapus = zone.querySelector("[data-wali-hapus-note]");
    var samaNote = zone.querySelector("[data-wali-sama-note]");
    var labelJawab = zone.querySelector("[data-wali-jawaban]");
    var jawaban = zone.getAttribute("data-ada-wali") === "1" ? "Ya" : "";
    var akanDihapus = false;
    var catatanAsli = catatanHapus ? catatanHapus.textContent : "";

    function isian() {
      return Array.prototype.slice.call(zone.querySelectorAll("input, select, textarea"));
    }

    function adaIsiWali() {
      return isian().some(function (el) { return (el.value || "").trim() !== ""; });
    }

    function terapkan() {
      var ayah = namaNormal(ayahInput ? ayahInput.value : "");
      var ibu = namaNormal(ibuInput ? ibuInput.value : "");
      var namaWaliKini = namaNormal(namaWali ? namaWali.value : "");
      var adaAyah = ayah !== "";
      var bukaWali = !adaAyah && (jawaban === "Ya" || akanDihapus);
      // Nama wali yang sama dengan ayah/ibu bukan kesalahan yang perlu ditolak:
      // sistem mengosongkannya saat disimpan, jadi cukup diberi catatan.
      var waliSama = namaWaliKini !== "" && (namaWaliKini === ayah || namaWaliKini === ibu);

      if (ask) ask.hidden = adaAyah;
      if (note) note.hidden = !adaAyah;
      if (fields) fields.hidden = !bukaWali;
      if (samaNote) samaNote.hidden = !(waliSama && bukaWali);

      // Isian wali hanya dikirim bila memang dipakai, supaya data lama tidak
      // ikut terhapus tanpa sengaja.
      isian().forEach(function (el) { el.disabled = !bukaWali; });

      if (labelJawab) {
        labelJawab.textContent = akanDihapus ? "akan dihapus" : (jawaban || "belum dijawab");
      }
      if (tombolHapus) {
        tombolHapus.disabled = !(adaIsiWali() || zone.getAttribute("data-ada-wali") === "1");
      }
      if (catatanHapus) {
        catatanHapus.textContent = akanDihapus
          ? "Data wali akan dikosongkan saat disimpan. Isian wali yang sama dengan nama ayah/ibu juga dikosongkan otomatis oleh sistem."
          : catatanAsli;
      }
    }

    zone.querySelectorAll("[data-wali-jawab]").forEach(function (tombol) {
      tombol.addEventListener("click", function () {
        jawaban = tombol.getAttribute("data-wali-jawab");
        akanDihapus = false;
        if (jawaban === "Tidak") {
          isian().forEach(function (el) { el.value = ""; });
        }
        zone.querySelectorAll("[data-wali-jawab]").forEach(function (t) {
          t.classList.toggle("active", t === tombol);
        });
        terapkan();
      });
    });

    if (tombolHapus) {
      tombolHapus.addEventListener("click", function () {
        isian().forEach(function (el) { el.value = ""; });
        akanDihapus = true;
        jawaban = "";
        terapkan();
      });
    }

    [ayahInput, ibuInput, namaWali].forEach(function (el) {
      if (el) el.addEventListener("input", terapkan);
    });
    terapkan();
  });

  // --- Nama ayah tidak boleh sama dengan nama ibu ---------------------------
  // Satu-satunya aturan yang masih menolak pengiriman. Data wali tidak diperiksa
  // di sini karena server mengosongkannya otomatis (lihat catatan di atas).
  document.querySelectorAll("form").forEach(function (form) {
    var ayah = form.querySelector('[name="ayah_nama"]');
    var ibu = form.querySelector('[name="ibu_nama"]');
    if (!ayah || !ibu) return;
    form.addEventListener("submit", function (event) {
      var a = namaNormal(ayah.value);
      var i = namaNormal(ibu.value);
      if (a && i && a === i) {
        event.preventDefault();
        peringatanForm(form, "Nama ayah dan nama ibu tidak boleh sama. Mohon periksa kembali.");
        ibu.focus();
        return;
      }
      peringatanForm(form, "");
    });
  });
})();
