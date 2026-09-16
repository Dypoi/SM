/* SIMSEK — skrip antarmuka ringan (tanpa dependensi). */
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
})();
