<a href="https://www.espressif.com">
    <img src="https://www.espressif.com/sites/all/themes/espressif/logo-black.svg" align="right" height="20" />
</a>

# CHANGELOG

> All notable changes to this project are documented in this file.
> This list is not exhaustive - only important changes, fixes, and new features in the code are reflected here.

<div align="center">
    <a href="https://keepachangelog.com/en/1.1.0/">
        <img alt="Static Badge" src="https://img.shields.io/badge/Keep%20a%20Changelog-v1.1.0-salmon?logo=keepachangelog&logoColor=black&labelColor=white&link=https%3A%2F%2Fkeepachangelog.com%2Fen%2F1.1.0%2F">
    </a>
    <a href="https://www.conventionalcommits.org/en/v1.0.0/">
        <img alt="Static Badge" src="https://img.shields.io/badge/Conventional%20Commits-v1.0.0-pink?logo=conventionalcommits&logoColor=black&labelColor=white&link=https%3A%2F%2Fwww.conventionalcommits.org%2Fen%2Fv1.0.0%2F">
    </a>
    <a href="https://semver.org/spec/v2.0.0.html">
        <img alt="Static Badge" src="https://img.shields.io/badge/Semantic%20Versioning-v2.0.0-grey?logo=semanticrelease&logoColor=black&labelColor=white&link=https%3A%2F%2Fsemver.org%2Fspec%2Fv2.0.0.html">
    </a>
</div>
<hr>

## v1.4.2 (2025-11-11)

### 🐛 Bug Fixes

- Corrected paths on Windows for the GDB *(Jakub Kocka - 49c7eb8)*


## v1.4.1 (2025-06-30)

### 🐛 Bug Fixes

- Decode addresses in a case-insensitive manner *(Peter Dragun - 36a2c6d)*


## v1.4.0 (2025-06-23)

### ✨ New Features

- Batch requests and extract fn/paths from addr2line *(Nebojsa Cvetkovic - 29d0f91)*


## v1.3.0 (2025-03-07)

### ✨ New Features

- Add support for esp32h21 and esp32h4 targets *(Peter Dragun - efef577)*

---

## v1.2.1 (2024-09-03)

### 🐛 Bug Fixes

- PcAddressMatcher for single elf file *(Peter Dragun - 641a7ec)*

---

## v1.2.0 (2024-09-02)

### ✨ New Features

- Add support for multiple ELF files *(Peter Dragun - 8e5c87f)*

### 🐛 Bug Fixes

- Catch exception when the ELF file is modified *(Jaroslav Burian - 112cf24)*

---

## v1.1.0 (2024-05-21)

### ✨ New Features

- add support for esp32c61 *(Peter Dragun - 23cdea9)*
- add support for esp32c5 *(Peter Dragun - e983453)*

---

## v1.0.1 (2023-12-08)

---

## v1.0.0 (2023-12-05)

### ✨ New Features

- add addr2line and panic_output_decoder from esp-idf-monitor *(Peter Dragun - 04a195e)*

---

<div align="center">
    <small>
        <b>
            <a href="https://www.github.com/espressif/cz-plugin-espressif">Commitizen Espressif plugin</a>
        </b>
    <br>
        <sup><a href="https://www.espressif.com">Espressif Systems CO LTD. (2025)</a><sup>
    </small>
</div>
