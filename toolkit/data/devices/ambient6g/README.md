# AMBIENT-6G harvester dataset — rectifier upper bounds

Source: https://github.com/AMBIENT-6G/dataset-harvesters (webtool https://ambient-6g.github.io/dataset-harvesters/webtool/),
commit recorded in the first line of `rectifier_envelope.csv`. The repository has no license file yet; ask the
AMBIENT-6G team (G. Callebaut) how to cite it before publishing results based on it.

`rectifier_envelope.csv` is made by `python scripts/import_ambient6g.py`. The dataset measures the rectifiers of
the e-peas AEM30940 evaluation kits without the charger: C031 at 915 MHz (swept 850–950 MHz) and C041 at 2450 MHz
(swept 2450–2550 MHz), each with a low-power (SMS7630005LF) and a high-power (SMS7621005LF) rectifier, from −25 to
+10 dBm. The DC power goes into a load held at a target voltage of 0.25 to 2 V. For each rectifier, frequency and
input power, the envelope keeps the best efficiency over those target voltages, i.e. what an ideal maximum-power-point
charger could take from the rectifier.

| Column | Meaning |
|---|---|
| `rectifier`, `band_mhz` | rectifier and the band its kit is tuned for |
| `frequency_mhz`, `input_power_dbm` | measurement point |
| `efficiency` | DC power / RF input power, as a fraction (the dataset gives percent) |
| `target_mv` | the load voltage at which that efficiency was reached |

## How the engine uses it

The `rectifier_*` harvesters in `config/applications.yaml` take the measured frequency closest to their
`frequency_hz` and one rectifier path (or, with `rectifier: best`, the better path at each input power). They are
upper bounds: they leave out charger losses, leakage and quiescent currents, which the measured device of
`../cappelle2025/` includes. That device uses the kit's high-power input (SMS7621005LF): `rectifier_bound_915`.
Alone, this rectifier converts 11 % at −15 dBm and under 2 % at −17.5 dBm, so it sets the device's −15 dBm
threshold; the charger roughly halves the efficiency above it. The low-power input (SMS7630005LF,
`rectifier_low_915`) still converts 23 % at −20 dBm.

## Data note

Rows with a DC power of 4294967295 pW (2^32 − 1) are clipped readings, mostly at +9 and +10 dBm with the high-power
rectifier; their efficiency (54.07 % and 42.95 %) is the clipped power divided by the input power. The import script
drops them. Worth reporting to the dataset maintainers.
