# Third-party notices

OptiCore Studio's own code is licensed under the GNU Affero General Public
License, version 3 or later (see [LICENSE](LICENSE)). The data files and
dependencies below keep their own licences. Each data file in the repository
is listed here with its source; the per-folder README files give checksums and
details.

## Data included in this repository

| Files | Contents | Source | Licence |
|---|---|---|---|
| `backend/opticore/photometry/data/CIE_*.csv` | CIE colour-matching functions (1931 2°, 1964 10°), illuminants D65, C, F1–F12, FL3.x, daylight components S0–S2, scotopic V′(λ) | International Commission on Illumination (CIE), Vienna; DOIs and MD5 sums in `backend/opticore/photometry/data/README.md` | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/), unmodified |
| `backend/opticore/materials/data/oic2019_yucca_targets.csv` | OIC 2019 Manufacturing Problem target transmittance | D. Poitras, L. Li, M. R. Jacobson, C. C. Cooksey, Figshare doi:10.6084/m9.figshare.9915800; Appl. Opt. 59(5), A31 (2020) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/), converted to CSV with the values unchanged |
| `backend/opticore/materials/data/coating_materials.json` | thin-film and metal optical constants n, k | refractiveindex.info database (M. N. Polyanskiy); the original measurement is cited per entry | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) |
| `backend/opticore/materials/data/catalog.json` | dispersion coefficients and properties of the built-in glasses, crystals and polymers | transcribed from public manufacturer datasheets and peer-reviewed literature (source per entry); SCHOTT thermal data via refractiveindex.info (CC0) | factual data, cited per entry |
| `frontend/public/samples/eiffel-tower.jpg` | photograph for the live-image examples | Jebulon, Wikimedia Commons | [CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/) |
| `frontend/public/samples/pillars-of-creation.jpg` | Hubble image of the Pillars of Creation (1995) | NASA, Jeff Hester and Paul Scowen (Arizona State University) | public domain (NASA material) |

Details of the images are in `frontend/public/samples/CREDITS.md`, and details of
the material and coating data in `backend/opticore/materials/data/README.md`.
Data generated here from these sources (`builtin_coatings.json`,
`coating_examples.json`, `stock_generic.json`) is part of OptiCore Studio.
`coating_examples.json` contains the OIC 2019 targets as above.

## Dependencies (installed by pip and npm, not included in this repository)

| Package | Licence |
|---|---|
| NumPy | BSD-3-Clause (with bundled 0BSD, MIT, Zlib, CC0 parts) |
| SciPy | BSD-3-Clause |
| FastAPI, Pydantic | MIT |
| Uvicorn, Starlette | BSD-3-Clause |
| PyYAML | MIT |
| cadquery-ocp (OpenCascade bindings) | Apache-2.0; bundles Open CASCADE Technology (LGPL-2.1 with the OCCT exception) and VTK (BSD-3-Clause) |
| React, React DOM, three.js, @react-three/fiber, @react-three/drei, @react-three/postprocessing, Zustand, plotly.js | MIT |
| postprocessing | Zlib |
| lucide-react | ISC |
| Inter and JetBrains Mono fonts (@fontsource-variable) | SIL Open Font License 1.1 (included in the built user interface) |

The development dependencies (pytest, httpx, Vite, Vitest, TypeScript, oxlint and
their dependencies) are used only for building and testing.

## The installable packages

The Windows installer and the Linux AppImage contain the Python runtime, the
Python dependencies above (with their own dependencies), and the user interface
built from the npm packages above. Each package has a `licenses` folder. It holds
the licence text of every bundled component and an index, `licenses/README.txt`,
collected by `packaging/collect_licenses.py`.

The program is built with PyInstaller. Its bootloader is under GPL-2.0 with an
exception that allows distribution with any program. Open CASCADE Technology
(LGPL-2.1 with the OCCT exception) is shipped as separate shared libraries, which
can be replaced. The Windows installer is made with Inno Setup.

## Trademarks

SCHOTT, CDGM, OHARA, HOYA, Zemax, OpticStudio, CODE V and other product and
company names are trademarks of their owners. They are used only to identify
compatible data and file formats. OptiCore Studio is not affiliated with or
endorsed by them.
