# Path loss with the node on leaves (Cappelle et al. 2025)

"For the RF power transfer, we empirically determined the PL when attaching the node to the leaves of a plant.
For a transmitter at 1 m, a PL of 40 dB can be expected." (main.tex, Sec. III)

- Frequency 915 MHz.
- Distance 1 m; small lab setup (comment by G. Callebaut in main.tex).
- Measurement antenna: a simple dipole (J. Cappelle, Oct 2026). The node's own harvesting antenna is a monopole.
- Node attached to the leaves of a potted plant; photo of the setup: `measurement_setup.jpg` (add it here).
- Free-space reference at 1 m and 915 MHz with isotropic antennas: 31.7 dB. The measured 40 dB is therefore about
  8.3 dB above free space: leaf proximity, antenna detuning, polarisation, matching and antenna gains together.

Still unknown, needed to recreate the setup in Sionna: TX antenna type and gain, TX and node heights, the
orientation of both antennas, and whether the 40 dB includes antenna gains and cable losses.
