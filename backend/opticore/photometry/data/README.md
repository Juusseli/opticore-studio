# CIE datasets

These tables are unmodified copies of datasets published by the International Commission on Illumination (CIE), Vienna,
Austria, under the Creative Commons Attribution-ShareAlike 4.0 International licence (CC BY-SA 4.0,
https://creativecommons.org/licenses/by-sa/4.0/). They were downloaded on 2026-11-17 from
https://files.cie.co.at/Publications-datasets/. The MD5 sums are those given in the CIE's
metadata and are checked by `backend/tests/test_photometry.py`.

| File | Dataset | Source table | DOI | Range | MD5 |
|---|---|---|---|---|---|
| `CIE_xyz_1931_2deg.csv` | CIE 1931 colour-matching functions, 2 degree observer: λ (nm), x̄, ȳ, z̄ | CIE 018:2019, Table 6 | 10.25039/CIE.DS.xvudnb9b | 360–830 nm, 1 nm | 17cca777db64b17170f06f67ce9d3ab7 |
| `CIE_std_illum_D65.csv` | CIE standard illuminant D65: λ (nm), relative spectral power | ISO/CIE 11664-2:2022, Table B.1 | 10.25039/CIE.DS.hjfjmt59 | 300–830 nm, 1 nm | 03d4eb9b837c60671627c946fb534deb |
| `CIE_sle_scotopic.csv` | CIE spectral luminous efficiency for scotopic vision V′(λ): λ (nm), V′ | CIE 018:2019, Table 2 | 10.25039/CIE.DS.gr6w4b5g | 380–780 nm, 1 nm | 3e45714a429d02e5d1f2a752226d7698 |
| `CIE_xyz_1964_10deg.csv` | CIE 1964 colour-matching functions, 10 degree observer: λ (nm), x̄₁₀, ȳ₁₀, z̄₁₀ | CIE 1964 standard observer | (CIE datasets page) | 360–830 nm, 1 nm | 6140e032f9326d88c5a0959b29b4d8f3 (on download) |
| `CIE_illum_FLs.csv` | CIE illuminants F1–F12 and FL3.1–FL3.15: λ (nm), relative spectral power | CIE 015 | (CIE datasets page) | 380–780 nm, 5 nm | 441613e501ab0a58e62f2669ff005db7 (on download) |
| `CIE_illum_Dxx_comp.csv` | CIE daylight components S0, S1, S2: λ (nm), S0, S1, S2 | CIE 015 | (CIE datasets page) | 300–830 nm, 5 nm | 3068737bc5e8561bd8b3ef9639578d18 (on download) |
| `CIE_illum_C.csv` | CIE illuminant C: λ (nm), relative spectral power | CIE 015 | (CIE datasets page) | 300–780 nm, 5 nm | bb325f040bab332d91f8d9447aa47b78 (on download) |

The last four files (MD5 marked "on download") were downloaded on 2026-11-17 from the same site; the CIE publishes no MD5 sums
for these, so the sums are those of the files as downloaded. The daylight illuminants D50, D55 and D75 are computed from
the daylight components with the CIE formula (CIE 015:2018 §4.1); `tests/test_photometry.py` checks that the same formula
reproduces the D65 table.

Attribution: CIE (2019, 2022), datasets as listed above, International Commission on Illumination (CIE), Vienna,
Austria. The CIE's metadata states linear interpolation between the tabulated wavelengths and zero outside the range.

The photopic spectral luminous efficiency V(λ) is ȳ(λ) of the 1931 observer. CIE standard illuminant A is computed
from its defining formula (Planck's law, ISO/CIE 11664-2) and needs no table.
