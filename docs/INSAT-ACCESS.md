# INSAT-3D / 3DR access

Working. Search needs no account and runs today; downloads need a free MOSDAC
account that only you can create.

```bash
make insat-status     # what is reachable, and whether downloads are enabled
make insat-plan       # size a download before committing to it
```

## Why this matters

[docs/FINDING-eye-detection.md](FINDING-eye-detection.md) measured why IR
centre-fixing could not beat motion extrapolation. Both dominant error terms
come from MODIS being polar-orbiting:

| source | contribution |
|---|---|
| 4 km nearest-neighbour centring | ~4–6 km |
| ±30 min **estimated** overpass time × ~12 kt | ~11 km |

INSAT-3DR removes both. It is geostationary, so imagery has a **published**
acquisition timestamp instead of one inferred from an equator-crossing time.

| | MODIS (current) | INSAT-3DR |
|---|---|---|
| Fani-window granules | 18 usable day passes | **1,947** |
| cadence | ~4 per day | 8.1 min measured (30 min full disk + rapid-scan sectors) |
| timestamp | estimated, ±30 min | published, exact |
| channels | Band 31 only, via colormap inversion | 6 native channels, L1B radiance |

## Access model

Taken from MOSDAC's own published client
([mdapi.zip](https://www.mosdac.gov.in/software/mdapi.zip), documented at
[downloadapi-manual](https://mosdac.gov.in/downloadapi-manual)). `mosdac.py`
reimplements the same calls rather than executing that script.

| endpoint | auth | status |
|---|---|---|
| `apios/datasets.json` (search) | none | **working** |
| `download_api/gettoken` | username + password | needs your account |
| `download_api/download` | bearer token | needs your account |

### Coverage

| dataset | Fani 2019 | Mocha 2023 | recent |
|---|---|---|---|
| `3DIMG_L1B_STD` (INSAT-3D) | 38 | 44 | 47 |
| `3RIMG_L1B_STD` (INSAT-3DR) | **222** | **252** | 48 |
| `3SIMG_L1B_STD` (INSAT-3S) | — | — | 96 |

`—` means the satellite was not in service on that date, not an error. The
catalogue lags roughly a month behind real time, so "today" returns nothing.

**3DR is the right choice** for all three case studies: it is the only one
covering 2019 through 2023 densely.

## Enabling downloads — your one step

I cannot create accounts or handle passwords, so this part is yours:

1. Register once at <https://mosdac.gov.in/signup/>
2. Export the credentials:
   ```bash
   export MOSDAC_USERNAME='your-username-or-email'
   export MOSDAC_PASSWORD='your-password'
   ```
3. Confirm: `make insat-status` should show `downloads available`

Credentials are read from **the environment only**. They are never written to
disk, never logged, and never committed. `tests/test_mosdac_credentials.py`
enforces all of that, including a behavioural test that a rejected login does
not put the password value into the exception. MOSDAC's own client stores the
password in a `config.json`; this one deliberately does not, and a test fails if
that ever changes.

## Sizing a download first

3DR granules average **297 MB**, so the full Fani window is 564 GB. Thin it:

```
3RIMG_L1B_STD  2019-04-25 .. 2019-05-05
  native cadence      8.1 min
  full archive        1,947 granules, 564.5 GB
  thinned to 180 min     88 granules,  25.5 GB
```

| cadence | granules | size |
|---|---|---|
| 60 min | 264 | 76.5 GB |
| 180 min | 88 | 25.5 GB |
| 360 min | 44 | 12.8 GB |

180 min is the sensible starting point: it is 4× denser than the 4 passes/day
MODIS gives, with exact timestamps, at 25 GB.

```bash
.venv/bin/python -m cyclops.data.insat_cli fetch \
  --sat 3DR --start 2019-04-25 --end 2019-05-05 --every 180
```

## The HDF5 reader

Written. `cyclops/data/insat_reader.py`.

```bash
make insat-selftest                                    # 14 checks, no account needed
python -m cyclops.data.insat_reader describe file.h5   # run this on the FIRST real granule
python -m cyclops.data.insat_reader read file.h5 17.0 85.0
```

### The one thing that matters

L1B stores raw detector **counts** plus a per-calibration lookup table, not
physical values. Brightness temperature is `IMG_TIR1_TEMP[IMG_TIR1]`.

Reading `IMG_TIR1` directly raises no error and yields plausible-looking
integers — it just silently is not temperature. The reader applies the LUT, and
`test_lut_is_applied_not_raw_counts` range-checks the output because nothing
else would catch it.

| variable | meaning |
|---|---|
| `IMG_TIR1` | counts, 2-D, 4 km, carries `_FillValue` |
| `IMG_TIR1_TEMP` | LUT: count → brightness temperature (K) |
| `Longitude`, `Latitude` | 2-D geolocation, same grid |
| `IMG_WV`, `Longitude_WV` | water vapour, 8 km |
| `Acquisition_Start_Time` | `%d-%b-%YT%H:%M:%S` |

Layout taken from satpy's `insat3d_img_l1b_h5`, the maintained reference reader.

### Resampling

Full-disk geostationary geolocation is 2-D, so the storm crop is a nearest-
neighbour KD-tree query — what `pyresample.kd_tree.resample_nearest` does
internally, done with scipy so the demo does not need the whole geospatial
stack. Source pixels beyond a metric cutoff are left invalid, so the disk edge
and any data gap stay visible as gaps instead of being stretched.

### Validation status

Tested end to end against a **synthetic granule** built to the documented layout:
LUT direction, fill masking, geolocation, resampling, and recovery of a known
eye (−24.3 °C read vs −20 °C built) and eyewall (−84.9 vs −85.0). The decisive
check is that `centre_fix` and `dvorak` run on an INSAT scene **unchanged** and
return a 10.2 km centre error and `EYE T7.0` — INSAT is a genuine drop-in for
MODIS, not a parallel path.

It has **not** been run on a real MOSDAC granule, because that needs an account.
`describe()` is built for that moment: point it at the first real file and it
prints the actual structure, so a layout difference shows up immediately instead
of becoming wrong temperatures. A granule with an unexpected layout raises
`InsatFormatError` naming what is missing.
