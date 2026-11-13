// The studies the viewer shows by default (and the published website): one batch each, in this order.
// axis: the parameter the study is about, used as the chart's x axis.
// Update the batch ids here after a re-export; everything else follows from the batch's own parameters.
export const STUDIES = [
  {key: 'species', label: 'Plant species', batch: 'V2_batch_01_20261110_125549Z', axis: 'plant_stage',
    about: 'Four crops through growth stages 0–4. One ceiling gateway, 915 MHz.'},
  {key: 'frequency', label: 'Carrier frequency', batch: 'v2_batch_02_20261110_154706Z', axis: 'frequency',
    about: 'Cherry tomato at 868 MHz, 915 MHz, 2.437 GHz (BLE) and 5.18 GHz. One ceiling gateway.'},
  {key: 'gateways', label: 'Gateway density', batch: 'V2_batch_03_20261110_155715Z', axis: 'ap_density',
    about: 'Cherry tomato with 1 to 23 ceiling gateways, from one per 30 m² to one per 1 m². 915 MHz.'},
  {key: 'moisture', label: 'Leaf moisture', batch: 'bacth_04_20261110_160139Z', axis: 'moisture',
    about: 'Cherry tomato with leaf water content from 20 % to 90 %. One ceiling gateway, 915 MHz.'},
];

const gateways = (run) => run?.run_metadata?.rx_count ?? null;
const CROPS = {0: 'Strawberry', 1: 'Sweet basil', 2: 'Lettuce', 3: 'Cherry tomato'};

// How a wedged parameter is named and its values are shown; unknown parameters fall back to their raw name.
export const PARAMS = {
  plant_species: {label: 'Crop', value: (v) => CROPS[v] ?? `Species ${v}`},
  // axis: how the parameter is plotted when it is not a plain number line (run = the run's scene-index entry).
  frequency: {label: 'Frequency', value: (v) => (v >= 1e9 ? `${+(v / 1e9).toFixed(3)} GHz` : `${Math.round(v / 1e6)} MHz`),
    axis: {label: 'Frequency', unit: 'GHz', value: (v) => v / 1e9}},
  // run (optional): the run's scene-index entry; its receiver count is the number of gateways.
  ap_density: {label: 'Gateways', value: (v, run) => gateways(run) ? `${gateways(run)} (1 per ${v} m²)` : `1 per ${v} m²`,
    chip: (v, run) => gateways(run) ? `${gateways(run)}` : `1 per ${v} m²`,
    axis: {label: 'Number of gateways', unit: '', value: (v, run) => run?.run_metadata?.rx_count ?? null}},
  moisture: {label: 'Leaf water', value: (v) => `${v} %`},
  plant_stage: {label: 'Growth stage', value: (v) => String(v)},
};

export const studyOfBatch = (batchId) => STUDIES.find((study) => study.batch === batchId) || null;
