# Canopy physics sanity study

This is a controlled software experiment at 2.4 GHz on the narrow 0.6 m canopy geometry. It is not a calibrated crop or greenhouse prediction.

## Existing/current implementation inspected

- Three longitudinal canopy rows are generated as three separate, closed cuboid OBJ meshes. Each row mesh has 8 vertices and 6 quad faces.
- `canopy_placeholder` is assigned to all three rows: epsilon_r=8, conductivity=0.25 S/m, RadioMaterial thickness=0.8 m, scattering coefficient=0, XPD=0, Lambertian pattern (inactive because scattering is zero).
- PathSolver and RadioMapSolver have LOS, specular reflection, and refraction enabled; diffuse reflection and diffraction are disabled; max depth is 2.
- Thus transmission is enabled in the current case. Sionna exposes refraction interactions and intersected object IDs; the saved per-path table records them directly.
- Sionna's installed RadioMaterial/PathSolver documentation describes a plane-slab Fresnel model at intersected surfaces, assumes thin materials for transmitted rays, and warns the approach may be inaccurate for very thick objects. This is not volumetric plant transport.

## Core radio-map comparison

All values below are dB differences from empty, computed from 10 log10(path_gain) with values below 1e-15 floored for display.

| Scenario | Mean abs Δ (dB) | Median Δ (dB) | Min Δ (dB) | Max Δ (dB) |
|---|---:|---:|---:|---:|
| empty | 0.000 | 0.000 | 0.000 | 0.000 |
| transparent | 7.167 | -2.688 | -101.240 | 0.000 |
| weak_loss | 14.967 | -10.085 | -101.434 | 9.895 |
| current | 24.200 | -10.088 | -105.570 | 14.241 |

## Single-factor map diagnostics vs current

| Diagnostic | Mean abs map change (dB) | Controlled change |
|---|---:|---|
| current_refraction_off | 6.203 | Set PathSolver and RadioMapSolver refraction to false; leave current material and geometry unchanged. |
| current_lower_permittivity | 0.254 | Lower epsilon_r only relative to current. |
| current_lower_conductivity | 10.478 | Lower conductivity only relative to current. |
| current_thinner_slab | 4.856 | Lower RadioMaterial slab thickness only relative to current; mesh geometry is unchanged. |

## Representative receivers

See `comparison/representative_receivers.csv` for each receiver and core case. Aggregate coefficient power is Σ|a|², not RSS; LOS/interactions are taken from Sionna's exposed interaction tensors.

| Case | Receiver | Paths | LOS | Paths with refraction | Two canopy refractions | Strongest coeff (dB re 1) |
|---|---|---:|:---:|---:|---:|---:|
| empty | RX_A | 26 | yes | 0 | 0 | -40.4 |
| empty | RX_B | 25 | yes | 0 | 0 | -55.6 |
| empty | RX_C | 25 | yes | 0 | 0 | -59.4 |
| transparent | RX_A | 15 | yes | 0 | 0 | -40.4 |
| transparent | RX_B | 15 | yes | 0 | 0 | -55.6 |
| transparent | RX_C | 7 | no | 1 | 1 | -59.4 |
| weak_loss | RX_A | 15 | yes | 0 | 0 | -40.4 |
| weak_loss | RX_B | 23 | yes | 0 | 0 | -55.6 |
| weak_loss | RX_C | 7 | no | 1 | 1 | -76.9 |
| current | RX_A | 15 | yes | 0 | 0 | -40.4 |
| current | RX_B | 23 | yes | 0 | 0 | -55.6 |
| current | RX_C | 6 | no | 0 | 0 | -76.9 |

## Core interaction settings

The flags below are shared by PathSolver and RadioMapSolver in each listed case.

| Case | LOS | Specular reflection | Refraction/transmission | Diffuse scattering | Diffraction |
|---|:---:|:---:|:---:|:---:|:---:|
| empty | on | on | on | off | off |
| transparent | on | on | on | off | off |
| weak_loss | on | on | on | off | off |
| current | on | on | on | off | off |

## Diagnostic interaction settings

| Diagnostic | LOS | Specular reflection | Refraction/transmission | Diffuse scattering | Diffraction |
|---|:---:|:---:|:---:|:---:|:---:|
| current_refraction_off | on | on | off | off | off |
| current_lower_permittivity | on | on | on | off | off |
| current_lower_conductivity | on | on | on | off | off |
| current_thinner_slab | on | on | on | off | off |

## Direct geometric TX-to-RX canopy intersections

These are independent segment/AABB tests against the generated canopy boxes, not Sionna path classifications.

| Receiver | Canopy rows intersected | Segment distance inside canopy (m) | Entry to exit (m) |
|---|---|---:|---|
| RX_A | none (0 row intersections) | 0.000 | â€” |
| RX_B | none (0 row intersections) | 0.000 | â€” |
| RX_C | canopy_row_02 (1 row intersections) | 2.330 | canopy_row_02: (5.125, 3.7, 1.663) â†’ (7.375, 4.3, 1.587) |

## Transparent-control map diagnostics

Against empty with the matched epsilon_r=1, sigma=0 control: mean absolute difference 7.167 dB; median signed difference -2.688 dB; 95th percentile absolute difference 22.097 dB; max absolute difference 101.240 dB; cells over 1 dB 150/234; cells over 3 dB 108/234. Values use the same 1e-15 path-gain display floor.
RX_C already gives a direct segment that crosses canopy_row_02, so no extra RX_CANOPY_TEST receiver is required.

## Interpretation limits

The transparent case is an epsilon_r=1, conductivity=0 free-space-matched interface control; it retains the same closed mesh and slab-thickness field. It is not a physical crop. The weak-loss case is an arbitrary test material, not a realistic vegetation recommendation.
The current material's 0.8 m slab thickness is larger than the 0.6 m row plan width and is applied through Sionna's slab-interface model. That is a likely modeling mismatch; the one-factor thickness/epsilon/conductivity/refraction diagnostics quantify sensitivity within this solver, not truth about plants.
A ray path with two refraction interactions on canopy-row objects is counted as a traversal of the proxy. The far receiver was moved from the old RX_C position (which lay inside the box) to the far aisle at [10, 5, 1.5] m; all study scenarios use this same position.
## Conclusion from this run

- The current case is approximately opaque to the selected RX_C path at these solver settings: it produced 0 paths with two refractions on a canopy row. The matched control produced 1, and weak-loss produced 1. This is a finite-sample result, not proof transmission is mathematically impossible.
- Geometry plus finite path/map-solver interaction leaves a 7.17 dB mean-absolute map residual in the free-space-matched case. Its strongest RX_C traversal path is -59.4 dB; the saved path table gives its delay and object sequence.
- The strongest weak-loss RX_C traversal path is -92.5 dB, versus -59.4 dB for the matched control. The current case found no traversal path observed.
- In the one-factor map probes, lowering conductivity changed the map by 10.48 dB mean absolute, versus 0.25 dB for lowering epsilon_r and 4.86 dB for reducing slab thickness. Among tested factors, conductivity had the largest measured map effect; these chosen values do not establish whether the original value is physically too high.
- Turning refraction off changed the current map by 6.20 dB mean absolute. The current core case already has refraction enabled, so disabled transmission does not explain its current result.
- The box model is appropriate only as a software demonstration. First obtain crop dielectric/measurement evidence (recommendation D); then compare a sparse/open canopy proxy (B) against this block representation. Do not add low-poly leaves/stems before the material model is grounded.
