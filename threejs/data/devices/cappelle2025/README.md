# Cappelle et al. 2025 — RF-powered batteryless plant movement sensor

Device data for the application engine (`config/applications.yaml`, profile `wpt`).
Source: J. Cappelle et al., "RF-powered batteryless plant movement sensor for precision agriculture", arXiv:2509.13004.
The paper's LaTeX source and the Otii measurement project are in `../../IEEE_Sensors_2025___RF_Power_Plant_Sensor_GROWTH_1/`
and `../../meas RF powered/`.

| File | Content |
|---|---|
| `fig4_charge_time.csv` | Fig. 4 of the paper, from `figures/energy_harvesting.tex`: charge time of the buffer against RF input power at 915 MHz, for 470 uF and 1 mF, from a cold start and between successive measurements (minutes in the source, seconds here). |
| `node.yaml` | harvester, buffer thresholds, quiescent currents, BLE settings and the energy per cycle |
| `path_loss_setup.md` | the 40 dB at 1 m measurement with the node on leaves |
| `harvester_efficiency.csv` | (expected later) the efficiency curve of the harvester chain |

## How the engine uses it

The net power stored in the buffer is P_net = 1/2 C (V_on^2 - V_off^2) / t for successive measurements (and
1/2 C V_on^2 / t from a cold start). Both capacitors give the same P_net at each input power, as they should:
about 1.9 uW at -15 dBm (6 % of the RF input) up to about 300 uW at 0 dBm (30 %). P_net already includes the
harvester's conversion losses, leakage and quiescent currents during charging, so the engine adds no extra
quiescent power for this device. Below -15 dBm (not measured, the harvester's minimum input) nothing is harvested.
