import * as THREE from 'three';
import './performance.css';
import {orientationWithYaw,finiteRange} from './rf-inputs.js';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CSS2DObject, CSS2DRenderer } from 'three/addons/renderers/CSS2DRenderer.js';
import './style.css';
import './housionna.css';
import './theme.css';
import './dramco.css';

const app = document.querySelector('#app');
app.innerHTML = `
  <header class="topbar">
    <div class="brand"><img class="brand-logo" src="dramco-mark-white.png" alt="DRAMCO" width="32" height="32"><div><b>HyROPA</b><span>INDOOR VERTICAL FARM TWIN</span></div></div>
    <div class="top-context"><span class="live-dot"></span><span id="scenarioHeading">Loading scene data</span><span class="separator">/</span><span id="frequencyHeading">RF propagation study</span></div>
    <div class="top-actions"><span id="visualWarning" class="visual-warning">VISUAL PLANTS ≠ RF MODEL</span><button id="layersBtn" class="quiet-button panel-button" aria-expanded="true">Layers</button><button id="inspectorBtn" class="quiet-button panel-button" aria-expanded="true">Inspector</button><button id="captureBtn" class="quiet-button">Capture view</button></div>
  </header>
  <main class="workspace">
    <aside class="left-panel">
      <div class="panel-heading"><div><p class="eyebrow">SCENE CONFIGURATION</p><h1 id="environmentHeading">Vertical farm</h1></div><span id="scenarioTag" class="tag">RF SCENE</span></div>
      <label class="field-label" for="sceneSourceSelect">Scene source</label>
      <select id="sceneSourceSelect" class="select-control"><option value="builtin">Built-in demo</option><option value="housionna">HOUSIONNA</option></select>
      <div id="builtinSceneControls">
        <label class="field-label" for="scenarioSelect">Scenario</label>
        <select id="scenarioSelect" class="select-control"></select>
      </div>
      <p id="scenarioDescription" class="muted-copy">Loading simulation-backed scene data…</p>
      <p class="site-note">Research demo. Dimensions and RF materials are placeholders, not measured farm data; do not read the maps as real coverage predictions.</p>
      <section id="housionnaControls" class="housionna-panel hidden" aria-label="HOUSIONNA saved runs">
        <div class="section-title"><span>HOUSIONNA SAVED RUNS</span><span id="housionnaStatus" class="status-pill ready">READY</span></div>
        <label class="field-label" for="housionnaRunSelect">Imported run</label>
        <select id="housionnaRunSelect" class="select-control"></select>
        <div class="run-stepper"><button id="housionnaOlderRun" class="small-button" type="button" aria-label="Previous (older) run">← Older</button><span id="housionnaRunPosition" class="run-position num"></span><button id="housionnaNewerRun" class="small-button" type="button" aria-label="Next (newer) run">Newer →</button></div>
        <div id="housionnaRunChanges" class="run-changes muted-copy" aria-live="polite"></div>
        <details id="runSeries" class="run-series hidden" open>
          <summary id="seriesSummary">Across runs of this scene</summary>
          <p id="seriesBatch" class="series-batch muted-copy hidden"></p>
          <label class="field-label" for="seriesMetric">Value</label>
          <select id="seriesMetric" class="select-control">
            <option value="median_map">Median radio map (dB)</option>
            <option value="mean_link">Mean link gain over RX (dB)</option>
            <option value="reached">Reached map cells (%)</option>
            <option value="paths">Path count</option>
          </select>
          <label class="field-label" for="seriesAxis">Along</label>
          <select id="seriesAxis" class="select-control"></select>
          <div id="seriesFilters" class="series-filters"></div>
          <div id="seriesChart" class="series-chart"></div>
          <div id="seriesTooltip" class="series-tooltip hidden" role="status"></div>
          <details class="series-table"><summary>Show values</summary><div id="seriesTable"></div></details>
        </details>
        <label class="field-label" for="housionnaExportSelect">Available export</label>
        <select id="housionnaExportSelect" class="select-control"></select>
        <button id="importSelectedHousionna" class="small-button housionna-import-selected">Import selected export</button>
        <button id="importAllHousionna" class="small-button housionna-import-selected" disabled>Import all new runs</button>
        <label class="field-label" for="housionnaTxSelect">Transmitter</label>
        <select id="housionnaTxSelect" class="select-control"></select>
        <label class="field-label" for="housionnaResultVersion">Displayed RF result</label>
        <select id="housionnaResultVersion" class="select-control"><option value="original">Original HOUSIONNA result</option><option value="latest" disabled>Latest Sionna rerun</option></select>
        <div id="housionnaLiveComparison" class="housionna-comparison muted-copy" aria-live="polite">Original exported result is selected.</div>
        <div class="housionna-actions"><button id="importLatestHousionna" class="small-button">Import latest Houdini run</button><button id="reloadHousionna" class="small-button">Reload selected</button></div>
        <div id="housionnaRunMetadata" class="housionna-metadata muted-copy" aria-live="polite"></div>
        <div id="housionnaImportStatus" class="housionna-message" aria-live="polite">Saved HOUSIONNA results are read-only.</div>
        <details class="housionna-display" open>
          <summary>Scene display</summary>
          <label class="field-label" for="housionnaGeometryMode">RF geometry</label>
          <select id="housionnaGeometryMode" class="select-control"><option value="solid">Solid</option><option value="wireframe">Wireframe</option><option value="transparent">Transparent</option><option value="object-colors">Object colors</option></select>
          <div id="objectColorLegend" class="object-color-legend hidden"></div>
          <label class="field-label" for="deviceDisplayMode">Device markers</label>
          <select id="deviceDisplayMode" class="select-control"><option value="selected">Selected TX + associated RXs</option><option value="all">All TXs and RXs in this run</option></select>
          <label class="field-label" for="deviceLabelMode">Device labels</label>
          <select id="deviceLabelMode" class="select-control"><option value="selected">Selected devices</option><option value="all">All displayed devices</option><option value="none">Hidden</option></select>
          <label class="compact-check"><input id="measurementMeshToggle" type="checkbox"><span>Show measurement mesh</span></label>
          <label class="compact-check"><input id="coordinateDiagnosticToggle" type="checkbox" checked><span>Show axes, origin and grid</span></label>
          <label class="compact-check"><input id="sceneBoundsToggle" type="checkbox" checked><span>Show scene boundary</span></label>
        </details>
        <details class="comparison-panel">
          <summary>Compare imported runs</summary>
          <label class="field-label" for="compareReference">Reference run</label><select id="compareReference" class="select-control"></select>
          <label class="field-label" for="compareRun">Comparison run</label><select id="compareRun" class="select-control"></select>
          <label class="field-label" for="compareTx">Transmitter</label><select id="compareTx" class="select-control"></select>
          <button id="compareHousionna" class="small-button">Compare runs</button>
          <div id="housionnaComparison" class="housionna-comparison muted-copy" aria-live="polite">Choose two imported runs to compare saved RF outputs.</div>
        </details>
      </section>
      <div class="section-rule"></div>
      <div class="section-title"><span>VIEW LAYERS</span><span class="section-count">06</span></div>
      <div id="layerToggles" class="toggle-list">
        <label><span class="toggle-copy"><i class="swatch swatch-glass"></i>Enclosure panels</span><input type="checkbox" data-layer="shell" checked><b class="toggle-ui"></b></label>
        <label><span class="toggle-copy"><i class="swatch swatch-metal"></i>Rack, trays & lights</span><input type="checkbox" data-layer="structure" checked><b class="toggle-ui"></b></label>
        <label><span class="toggle-copy"><i class="swatch swatch-plant"></i>Detailed visual plants</span><input type="checkbox" data-layer="plants" checked><b class="toggle-ui"></b></label>
        <label><span class="toggle-copy"><i class="swatch swatch-rf"></i>RF plant zones</span><input type="checkbox" data-layer="rfProxy"><b class="toggle-ui"></b></label>
        <label><span class="toggle-copy"><i class="swatch swatch-device"></i>TX / RX markers</span><input type="checkbox" data-layer="devices" checked><b class="toggle-ui"></b></label>
        <label><span class="toggle-copy"><i class="swatch swatch-map"></i>Radio map</span><input type="checkbox" data-layer="map"><b class="toggle-ui"></b></label>
      </div>
      <div class="toggle-subrow"><label for="labelsToggle">Object labels</label><input id="labelsToggle" type="checkbox" checked></div>
      <div class="toggle-subrow"><label for="differenceToggle">Difference map <span class="subtle">scenario − empty</span></label><input id="differenceToggle" type="checkbox"></div>
      <div id="mapControls" class="map-controls hidden">
        <label id="housionnaMapModeLabel" class="field-label hidden" for="housionnaMapMode">Imported radio map</label>
        <select id="housionnaMapMode" class="select-control hidden"><option value="selected">Selected result map</option><option value="difference" disabled>Rerun − original difference</option></select>
        <div id="mapLevelRow" class="hidden"><label class="field-label" for="mapLevel">Map level <span class="subtle">air gap above canopy</span></label><select id="mapLevel" class="select-control"></select></div>
        <label class="field-label" for="mapOpacity">Map opacity <span id="opacityValue">62%</span></label>
        <input id="mapOpacity" type="range" min="15" max="90" value="62">
        <label id="mapHeightLabel" class="field-label" for="mapHeight">Map height <span id="heightValue">1.50 m</span></label>
        <input id="mapHeight" type="range" min="0.5" max="3.5" step="0.05" value="1.5">
        <div id="mapLegend" class="map-legend"></div>
        <div id="zoneReport" class="zone-report hidden" aria-live="polite"></div>
      </div>
      <div class="section-rule"></div>
      <div class="section-title"><span>PROPAGATION</span><span class="section-count">PATHS API</span></div>
      <label class="field-label" for="receiverSelect">Receiver</label>
      <select id="receiverSelect" class="select-control"></select>
      <div id="receiverMetrics" class="receiver-metrics"></div>
      <label class="path-toggle"><input id="pathsToggle" type="checkbox"><span>Show returned paths</span></label>
      <label class="field-label" for="pathFilter">Display</label>
      <select id="pathFilter" class="select-control"><option value="strongest">Strongest path</option><option value="top5">Top 5 paths</option><option value="all">All exported paths</option></select>
      <div class="path-actions"><button id="playPathBtn" class="small-button" disabled>Play pulse</button><span id="pathCountLabel" class="muted-copy">Paths off</span></div>
      <div id="pathLegend" class="path-legend"></div>
      <div class="section-rule"></div>
      <section class="simulation-panel" aria-label="On-demand Sionna simulation">
        <div class="section-title"><span id="simulationPanelTitle">SIONNA RT SIMULATION</span><span id="rfRunStatus" class="status-pill ready">READY</span></div>
        <div id="builtinScenarioRow"><label class="field-label" for="simulationScenario">RF scenario</label>
          <select id="simulationScenario" class="select-control">
            <option value="farm_empty">Empty rack</option><option value="farm_proxy">RF plant proxy</option><option value="farm_dense">Dense canopy proxy</option>
          </select>
        </div>
        <div id="housionnaSimulationContext" class="simulation-help hidden"></div>
        <label class="field-label" for="frequencyGHz">Frequency <span>GHz</span></label>
        <div class="sim-frequency-row"><input id="frequencyGHz" class="number-control" type="number" min="0.1" max="6" step="0.001" value="2.4"><select id="frequencyPreset" class="select-control"><option value="">Presets</option><option value="0.433">433 MHz</option><option value="0.868">868 MHz</option><option value="2.4">2.4 GHz</option><option value="5">5 GHz</option></select></div>
        <div class="field-label">TX position <span>m · drag the marker</span></div>
        <div class="tx-input-grid"><label>X<input id="txX" class="number-control" type="number" step="0.01"></label><label>Y<input id="txY" class="number-control" type="number" step="0.01"></label><label>Z<input id="txZ" class="number-control" type="number" step="0.01"></label></div>
        <label class="field-label" for="txYaw">TX yaw <span>degrees</span></label>
        <input id="txYaw" class="number-control" type="number" min="-360" max="360" step="1" value="0">
        <div id="housionnaTxActions" class="housionna-actions hidden"><button id="resetHousionnaTx" class="small-button">Reset TX position</button></div>
        <div id="housionnaReceiverControls" class="hidden">
          <label class="field-label" for="housionnaReceiverSelection">Receivers for next run <span>Ctrl/⌘ to select</span></label>
          <select id="housionnaReceiverSelection" class="select-control receiver-multi" multiple size="4"></select>
          <label class="field-label" for="pathSamples">Path samples / source</label>
          <input id="pathSamples" class="number-control" type="number" min="1" max="2000000" step="10000" value="1000000">
        </div>
        <p id="txWarning" class="tx-warning hidden"></p>
        <details class="simulation-advanced"><summary>Solver and map settings</summary>
          <label class="field-label" for="solverDepth">Maximum path depth</label><select id="solverDepth" class="select-control"><option value="1">1</option><option value="2">2</option><option value="3" selected>3</option><option value="4">4</option><option value="5">5</option></select>
          <label class="check-row"><input id="losToggle" type="checkbox" checked> Line of sight</label>
          <label class="check-row"><input id="specularToggle" type="checkbox" checked> Specular reflection</label>
          <label class="check-row"><input id="refractionToggle" type="checkbox" checked> Refraction</label>
          <label class="check-row"><input id="diffuseToggle" type="checkbox"> Diffuse reflection</label>
          <label class="check-row"><input id="diffractionToggle" type="checkbox"> Diffraction</label>
          <label class="field-label" for="mapQuality">Radio-map quality</label><select id="mapQuality" class="select-control"><option value="low">Low · 0.30 m</option><option value="medium" selected>Medium · 0.15 m</option><option value="high">High · 0.10 m, slower</option></select>
          <p id="simulationReadOnlyNote" class="simulation-help">Sionna runs only after you press Run. Visual plants remain outside the RF scene.</p>
        </details>
        <button id="runSimulationBtn" class="run-simulation-button">RUN SIONNA</button>
        <button id="runRadioMapBtn" class="small-button run-radio-map-button hidden">RECALCULATE RADIO MAP</button>
        <details class="simulation-diagnostics"><summary>Calculation diagnostics</summary><pre id="simulationDiagnosticsData">No calculation selected.</pre></details>
        <p id="simulationMessage" class="simulation-message" aria-live="polite">RF results match the displayed settings.</p>
        <div id="simulationError" class="simulation-error hidden" role="alert"></div>
        <div id="simulationRuntime" class="simulation-runtime">No on-demand run yet</div>
        <details class="simulation-history"><summary>Recent runs</summary><div id="simulationHistory" class="history-list"><span class="muted-copy">Loading history…</span></div></details>
      </section>
      <div class="section-rule"></div>
      <div class="section-title"><span>CAMERA</span><span class="section-count">ORBIT</span></div>
      <select id="cameraSelect" class="select-control">
        <option value="isometric">Isometric</option><option value="front">Front elevation</option><option value="side">Side elevation</option><option value="top">Top plan</option><option value="selected-object">Selected object</option><option value="selected-tx">Selected transmitter</option><option value="selected-rx">Selected receiver</option><option value="shelf">Shelf close-up</option><option value="tx">TX view</option><option value="RX_A">RX_A view</option><option value="RX_B">RX_B view</option><option value="RX_C">RX_C view</option><option value="fit">Fit scene</option></select>
      <div class="camera-hint">Drag to orbit · right-drag to pan · wheel to zoom</div>
      <div class="bottom-note"><span class="note-icon">i</span><span id="rfStatus">Visual plants are not currently RF simulation geometry.</span></div>
    </aside>
    <section class="viewport-wrap">
      <div class="viewport-toolbar"><div class="view-pill"><span class="view-dot"></span>3D SCENE</div><div id="sceneMeta" class="scene-meta">Loading dimensions…</div><button id="diagnosticsBtn" class="icon-button" title="Toggle diagnostics">Diagnostics</button></div>
      <div id="viewport" class="viewport"><div id="sceneLoading" class="scene-loading"><div class="loading-mark">H</div><b>Building configured farm scene</b><span>Loading exported geometry and Sionna RF outputs</span></div></div>
      <div class="scale-chip"><span class="scale-line"></span><span>1 m</span></div>
      <div id="diagnostics" class="diagnostics hidden"></div>
      <div class="viewport-footer"><span id="legendSemantics">PANELS / RACK <b>VISUAL + RF</b> &nbsp; DETAILED PLANTS <b>VISUAL ONLY</b> &nbsp; RF PLANT ZONES <b>RF ONLY</b></span><span>METRES / Z UP</span></div>
    </section>
    <aside class="right-panel">
      <div class="detail-head"><div><p class="eyebrow">OBJECT INSPECTOR</p><h2 id="detailTitle">Vertical farm</h2></div><span id="detailType" class="tag tag-muted">SCENE</span></div>
      <p id="detailSubtitle" class="muted-copy">Click a shelf, RF plant zone, transmitter, receiver, or returned path.</p>
      <div id="detailBody" class="detail-body"></div>
      <div class="section-rule"></div>
      <div class="section-title"><span>RF SEMANTICS</span><span class="section-count">MODEL SCOPE</span></div>
      <div id="semanticList" class="semantic-list">
        <div><i class="swatch swatch-glass"></i><span>Enclosure panels</span><b>VISUAL + RF</b></div>
        <div><i class="swatch swatch-metal"></i><span>Rack, trays & lights</span><b>VISUAL + RF</b></div>
        <div><i class="swatch swatch-plant"></i><span>Detailed plants</span><b>VISUAL ONLY</b></div>
        <div><i class="swatch swatch-rf"></i><span>Coarse RF plant zones</span><b>RF ONLY</b></div>
        <div><i class="swatch swatch-device"></i><span>TX / RX</span><b>RF</b></div>
      </div>
      <div class="right-footer"><span>SIMULATION BACKEND</span><b id="backendLabel">Sionna RT</b></div>
    </aside>
  </main>`;

const $ = (selector) => document.querySelector(selector);
const viewport = $('#viewport');
let data, activeScenario, activeReceiver = 'RX_A', selectedObject = null;
let scene, camera, renderer, labelRenderer, controls, rootGroup, raycaster, pointer;
let layerGroups = {}, objectMeshes = new Map(), pathCurves = [], heatMesh = null, hoverMesh = null, selectionOutline = null, txGroup = null;
let pulseMesh, pulseCurve = null, pulseRunning = false, pulseStarted = 0, animationId;
let backendInfo = null, apiHistory = [], rfResultsStale = false, lastRunFingerprint = null, displayedScenarioSupported = true;
let simulationRunning = false, simulationClock = null, simulationStartedAt = 0, draggingTx = null;
let housionnaRuns = [], housionnaImports = [], housionnaImportBusy = false;
// The published website (run.py publish) is the same build with <html data-site="static">: it reads plain JSON
// files next to the page and has no Python server, so import, rerun and simulation controls are hidden.
const STATIC_SITE = document.documentElement.dataset.site === 'static';
const SCENE_URL = STATIC_SITE ? 'data/viewer_scene.json' : '/outputs/digital_twin/viewer_scene.json';
const importViewerUrl = (importId) => STATIC_SITE
  ? `data/runs/${encodeURIComponent(importId)}.json`
  : `/api/housionna/imports/${encodeURIComponent(importId)}/viewer`;
const housionnaOriginalResults = new Map(), housionnaLatestResults = new Map();
let renderedGeometry=null;
let frameDirty=true;
const housionnaCompletedFingerprints = new Map(), housionnaDisplayedVersions = new Map();
const housionnaMapQualities = new Map();
const housionnaRestoredReceivers = new Map(), housionnaRestoreJobs = new Map();
const materialCache = new Map();
const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

const interactionColors = {
  los: '#48b98b', specular_reflection: '#5da6ed', refraction: '#e3a54b',
  diffuse_reflection: '#a88ce1', diffuse_scattering: '#a88ce1', diffraction: '#e77c78',
};

// DRAMCO web style: the viewer is dark only (see frontend/src/dramco.css)
const THEME_SCENE={
  dark:{bg:'#0a0a0b',fogNear:22,fogFar:58,exposure:0.95,hemi:['#c9c9c4','#1c1c1f',1.15],ambient:0.3,gridOpacity:0.3},
};
let hemiLight=null,ambientLight=null;
function currentTheme(){return 'dark';}
function applySceneTheme(){
  if(!scene)return;
  const t=THEME_SCENE[currentTheme()];
  scene.background=new THREE.Color(t.bg);
  if(scene.fog){scene.fog.color.set(t.bg);scene.fog.near=t.fogNear;scene.fog.far=t.fogFar;}
  renderer.toneMappingExposure=t.exposure;
  if(hemiLight){hemiLight.color.set(t.hemi[0]);hemiLight.groundColor.set(t.hemi[1]);hemiLight.intensity=t.hemi[2];}
  if(ambientLight)ambientLight.intensity=t.ambient;
  scene.traverse(o=>{if(o.userData?.kind==='coordinate-grid')o.material.opacity=t.gridOpacity;});
  frameDirty=true;
}

function initRenderer() {
  scene = new THREE.Scene();
  scene.background = new THREE.Color('#dce7e6');
  scene.fog = new THREE.Fog('#dce7e6', 26, 64);
  camera = new THREE.PerspectiveCamera(42, 1, 0.1, 120);
  camera.up.set(0, 0, 1);
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false, preserveDrawingBuffer: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.7));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.15;
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.domElement.className = 'webgl-canvas';
  viewport.appendChild(renderer.domElement);
  labelRenderer = new CSS2DRenderer();
  labelRenderer.domElement.className = 'label-layer';
  viewport.appendChild(labelRenderer.domElement);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  controls.dampingFactor = 0.075;
  controls.target.set(6, 4, 1.7);
  controls.minDistance = 0.35;
  controls.maxDistance = 120;
  controls.maxPolarAngle = Math.PI * 0.49;
  hemiLight = new THREE.HemisphereLight('#eff8ee', '#718578', 1.8);
  ambientLight = new THREE.AmbientLight('#ffffff', 0.42);
  scene.add(hemiLight, ambientLight);
  applySceneTheme();
  const key = new THREE.DirectionalLight('#fff2d8', 3.0);
  key.position.set(-5, -7, 15);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  key.shadow.camera.left = -18; key.shadow.camera.right = 18;
  key.shadow.camera.top = 18; key.shadow.camera.bottom = -18;
  key.shadow.bias = -0.0003;
  scene.add(key);
  const fill = new THREE.DirectionalLight('#b7dccb', 0.9);
  fill.position.set(10, 9, 8); scene.add(fill);
  rootGroup = new THREE.Group(); scene.add(rootGroup);
  raycaster = new THREE.Raycaster();
  raycaster.params.Line.threshold = 0.09;
  pointer = new THREE.Vector2();
  viewport.addEventListener('pointermove', onPointerMove, true);
  viewport.addEventListener('pointerdown', onPointerDown, true);
  window.addEventListener('pointerup', onPointerUp, true);
  window.addEventListener('pointercancel', onPointerUp, true);
  const resize = new ResizeObserver(resizeRenderer); resize.observe(viewport);
  window.addEventListener('resize', resizeRenderer);
  renderer.setAnimationLoop(renderFrame);
  controls.addEventListener('change',()=>{frameDirty=true;});
  for(const type of ['input','change','click','pointermove','resize'])window.addEventListener(type,()=>{frameDirty=true;},true);
}

function vec(values) { return new THREE.Vector3(...values.map(Number)); }
function cloneRadioMap(map) {
  if(!map)return map;
  return {...map,surfaces:(map.surfaces||[]).map(surface=>({...surface,
    values_db:[...(surface.values_db||[])],mesh:surface.mesh,
  }))};
}
function housionnaSnapshot(scenario) {
  return {
    transmitter:structuredClone(scenario.transmitter),receivers:structuredClone(scenario.receivers),
    frequency_hz:scenario.frequency_hz,paths:structuredClone(scenario.paths),links:structuredClone(scenario.links),
    receiver_metrics:structuredClone(scenario.receiver_metrics),radio_map:cloneRadioMap(scenario.radio_map),
    solver:structuredClone(scenario.solver),
  };
}
function ensureHousionnaOriginal(scenario) {
  if(scenario?.source_type!=='housionna')return null;
  if(!housionnaOriginalResults.has(scenario.name))housionnaOriginalResults.set(scenario.name,housionnaSnapshot(scenario));
  return housionnaOriginalResults.get(scenario.name);
}
function populateHousionnaReceiverSelection(scenario, selectedNames=null) {
  const select=$('#housionnaReceiverSelection');
  if(!select)return;
  const baseline=ensureHousionnaOriginal(scenario);
  const receivers=baseline?.receivers||scenario.receivers||[];
  const available=new Set(receivers.map(row=>row.name));
  const selected=(selectedNames||housionnaRestoredReceivers.get(scenario.name)||[...select.selectedOptions].map(option=>option.value)).filter(name=>available.has(name));
  const fallback=receivers.slice(0,Math.min(3,receivers.length)).map(row=>row.name);
  const names=selected.length?selected:fallback;
  select.innerHTML=receivers.map(row=>`<option value="${esc(row.name)}">${esc(row.name)}</option>`).join('');
  for(const option of select.options)option.selected=names.includes(option.value);
}
function selectedHousionnaReceivers() {
  return [...$('#housionnaReceiverSelection').selectedOptions].map(option=>option.value);
}
function housionnaSettingsFingerprint() {
  const scenario=data?.scenarios?.[activeScenario];
  if(scenario?.source_type!=='housionna')return '';
  const orientation=scenario.transmitter?.orientation_rad||[0,0,0];
  return JSON.stringify({
    import_id:scenario.import_id,source_run_id:scenario.provenance?.run_folder_name||scenario.run_metadata?.run_id,
    transmitter:scenario.transmitter.name,frequency_hz:Number($('#frequencyGHz').value)*1e9,
    tx_position:[$('#txX').value,$('#txY').value,$('#txZ').value].map(Number),
    tx_orientation:orientationWithYaw(orientation,$('#txYaw').value),
    receiver_ids:selectedHousionnaReceivers().sort(),samples_per_src:Number($('#pathSamples').value),
    solver:{max_depth:Number($('#solverDepth').value),los:$('#losToggle').checked,
      specular_reflection:$('#specularToggle').checked,diffuse_reflection:$('#diffuseToggle').checked,
      refraction:$('#refractionToggle').checked,diffraction:$('#diffractionToggle').checked},
  });
}
function dimensions(bounds) { return [bounds.x_max-bounds.x_min, bounds.y_max-bounds.y_min, bounds.z_max-bounds.z_min]; }
function center(bounds) { return [(bounds.x_min+bounds.x_max)/2, (bounds.y_min+bounds.y_max)/2, (bounds.z_min+bounds.z_max)/2]; }
function disposeGroup(group) {
  const geometries = new Set();
  const materials = new Set();
  const textures = new Set();
  group.traverse((child) => {
    if(child.isCSS2DObject)child.element.remove();
    if (child.geometry && !geometries.has(child.geometry)) {
      geometries.add(child.geometry);
      child.geometry.dispose();
    }
    const childMaterials = Array.isArray(child.material) ? child.material : [child.material];
    for (const material of childMaterials) {
      if (!material || materials.has(material)) continue;
      materials.add(material);
      for (const value of Object.values(material)) {
        if (value?.isTexture && !textures.has(value)) { textures.add(value); value.dispose(); }
      }
      material.dispose();
    }
  });
  while (group.children.length) group.remove(group.children[0]);
}

function getMaterial(category, objectId, materialKey = null) {
  const cacheKey = materialKey ? `${category}:${materialKey}` : category;
  if (materialCache.has(cacheKey)) return materialCache.get(cacheKey);
  let material;
  if (category === 'floor') material = new THREE.MeshStandardMaterial({ color: '#a8aaa0', roughness: 0.91, metalness: 0.02 });
  else if (category === 'greenhouse_shell' || category === 'enclosure_panel') material = new THREE.MeshPhysicalMaterial({
    color: '#b9d7d4', roughness: 0.15, metalness: 0.02, transmission: 0.32,
    transparent: true, opacity: category === 'enclosure_panel' ? 0.28 : 0.19, side: THREE.DoubleSide, depthWrite: false,
  });
  else if (category === 'metal_structure' || category === 'shelf_tray' || category === 'equipment') material = new THREE.MeshStandardMaterial({ color: category === 'shelf_tray' ? '#687b70' : '#45575d', roughness: 0.36, metalness: 0.64 });
  else if (category === 'grow_light') material = new THREE.MeshStandardMaterial({ color: '#f3edcf', roughness: 0.28, emissive: '#d8e9a2', emissiveIntensity: 1.0 });
  else material = new THREE.MeshStandardMaterial({ color: '#50865c', roughness: 0.8, metalness: 0.0 });
  materialCache.set(cacheKey, material);
  return material;
}

function boxMesh(object, parent, layerName, options = {}) {
  if (!(parent instanceof THREE.Object3D)) {
    const actualType = parent === null
      ? 'null'
      : Array.isArray(parent)
        ? 'Array'
        : `${parent?.constructor?.name || typeof parent} (${typeof parent})`;
    throw new TypeError(`boxMesh expected a THREE.Object3D parent for "${object.id}" in layer "${layerName}", got ${actualType}`);
  }
  const size = dimensions(object.bounds_m);
  let geometry;
  if (object.mesh_format === 'indexed_triangles') {
    geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(object.vertices.flat(), 3));
    geometry.setIndex(object.faces.flat());
    geometry.computeVertexNormals();
  } else {
    geometry = new THREE.BoxGeometry(...size);
  }
  const baseMaterial = options.material || getMaterial(object.category, object.id, object.material_key);
  const material = object.mesh_format === 'indexed_triangles' ? baseMaterial.clone() : baseMaterial;
  if (object.mesh_format === 'indexed_triangles') material.side = THREE.DoubleSide;
  const mesh = new THREE.Mesh(geometry, material);
  if (object.mesh_format !== 'indexed_triangles') mesh.position.set(...center(object.bounds_m));
  mesh.castShadow = object.mesh_format === 'indexed_triangles'
    ? object.category !== 'floor'
    : ['metal_structure','shelf_tray','vegetation','rf_plant_zone'].includes(object.category);
  mesh.receiveShadow = object.category === 'floor';
  mesh.userData = { kind: 'geometry', object, layer: layerName, rfIncluded: true };
  parent.add(mesh);
  if (options.edges) {
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(geometry), new THREE.LineBasicMaterial({ color: '#2f7658', transparent: true, opacity: 0.9 }));
    edges.position.copy(mesh.position); edges.userData.pickParent = mesh; parent.add(edges);
  }
  objectMeshes.set(object.id, mesh);
  return mesh;
}

function makeLabel(text, kind = '') {
  const el = document.createElement('div');
  el.className = `scene-label ${kind}`;
  el.textContent = text;
  return new CSS2DObject(el);
}

function buildDeviceMarker(name, position, type, detail, scenarioKey = activeScenario) {
  const group = new THREE.Group();
  group.position.copy(vec(position));
  group.userData = { kind: type, name, detail, scenarioKey, rfIncluded: true };
  const markerColor = type === 'transmitter' ? '#df7540' : '#278e83';
  const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.018, 0.025, 0.44, 8), new THREE.MeshStandardMaterial({ color: '#53666a', metalness: 0.08, roughness: 0.72, depthTest: false }));
  stem.rotation.x = Math.PI/2; stem.position.z = 0.22; stem.castShadow = true; stem.renderOrder = 12; stem.userData = group.userData; group.add(stem);
  const marker = new THREE.Mesh(new THREE.SphereGeometry(type === 'transmitter' ? 0.105 : 0.082, 18, 12), new THREE.MeshPhysicalMaterial({ color: markerColor, roughness: 0.32, metalness: 0.02, emissive: markerColor, emissiveIntensity: 0.08, depthTest: false }));
  marker.material.userData.baseEmissive = markerColor;
  marker.position.z = 0; marker.castShadow = true; marker.renderOrder = 13; marker.userData = group.userData; group.add(marker);
  if (type === 'transmitter') {
    const antenna = new THREE.Mesh(new THREE.CylinderGeometry(0.015, 0.015, 0.24, 8), new THREE.MeshStandardMaterial({ color: '#354d54', metalness: 0.04, roughness: 0.7, depthTest: false }));
    antenna.rotation.x = Math.PI/2; antenna.position.z = 0.24; antenna.renderOrder = 12; antenna.userData = group.userData; group.add(antenna);
    const cap = new THREE.Mesh(new THREE.SphereGeometry(0.04, 12, 8), new THREE.MeshStandardMaterial({ color: '#e3a86c', depthTest: false }));
    cap.position.z = 0.38; cap.renderOrder = 13; cap.userData = group.userData; group.add(cap);
  }
  const label = makeLabel(name, type === 'transmitter' ? 'tx-label' : 'rx-label');
  label.position.z = 0.08;
  label.userData = { kind: 'device-label', deviceName: name, deviceType: type, scenarioKey };
  group.add(label);
  layerGroups.devices.add(group);
  objectMeshes.set(name, marker);
  group.rotation.z = Number(detail.orientation_rad?.[0] || 0);
  return group;
}

function seededRandom(seed) {
  let state = seed >>> 0;
  return () => { state = (1664525 * state + 1013904223) >>> 0; return state / 4294967296; };
}

function makeLeafGeometry() {
  const lengthSegments=12,widthSegments=6,positions=[],indices=[];
  for(let i=0;i<=lengthSegments;i++) {
    const u=i/lengthSegments,halfWidth=0.5*Math.pow(Math.sin(Math.PI*u),0.78);
    for(let j=0;j<=widthSegments;j++) {
      const v=(j/widthSegments)*2-1;
      positions.push(u,v*halfWidth,0.10*Math.sin(Math.PI*u)+0.045*(1-v*v)*Math.sin(Math.PI*u));
    }
  }
  for(let i=0;i<lengthSegments;i++)for(let j=0;j<widthSegments;j++) {
    const a=i*(widthSegments+1)+j,b=a+widthSegments+1;
    indices.push(a,b,a+1,b,b+1,a+1);
  }
  const geometry=new THREE.BufferGeometry();
  geometry.setAttribute('position',new THREE.Float32BufferAttribute(positions,3));
  geometry.setIndex(indices);geometry.computeVertexNormals();
  return geometry;
}

function buildVisualPlants(rows, visual) {
  const plantLayer=layerGroups.plants,rootSeed=Number(visual.seed??186);
  const leafGeo=makeLeafGeometry(),stemGeo=new THREE.CylinderGeometry(0.018,0.027,1,7);
  stemGeo.rotateX(Math.PI/2);
  const stemMat=new THREE.MeshStandardMaterial({color:'#ffffff',roughness:0.84});
  const leafMat=new THREE.MeshStandardMaterial({color:'#ffffff',roughness:0.72,side:THREE.DoubleSide,emissive:'#14260d',emissiveIntensity:0.06});
  leafMat.userData.baseEmissive='#14260d';
  const crownGeo=new THREE.SphereGeometry(0.052,12,8);
  const crownMat=new THREE.MeshStandardMaterial({color:'#ffffff',roughness:0.76});
  const palette=['#397b3e','#4b9148','#61a052','#75aa5b','#347248','#88b56a'];
  const shelves=visual.shelves?.length?visual.shelves:rows.map((row,index)=>({id:row.id||row.object?.id||`crop_row_${index+1}`,level:index+1,bounds_m:row.bounds_m,columns:Math.max(8,Math.floor((row.bounds_m.x_max-row.bounds_m.x_min)/(visual.spacing_m||0.42))),rows:1}));
  if(!shelves.length){leafGeo.dispose();stemGeo.dispose();crownGeo.dispose();stemMat.dispose();leafMat.dispose();crownMat.dispose();plantLayer.userData.plantCount=0;plantLayer.userData.leafCount=0;return {plants:0,leaves:0};}
  let totalPlants=0,totalLeaves=0;
  const axisX=new THREE.Vector3(1,0,0);
  for(const [shelfIndex,shelf] of shelves.entries()) {
    const b=shelf.bounds_m,columns=Math.max(1,Number(shelf.columns||1)),rowsPerShelf=Math.max(1,Number(shelf.rows||1));
    const rand=seededRandom((rootSeed+shelfIndex*7919)>>>0),plants=[],leaves=[];
    for(let row=0;row<rowsPerShelf;row++)for(let column=0;column<columns;column++) {
      const cellX=(b.x_max-b.x_min)/columns,cellY=(b.y_max-b.y_min)/rowsPerShelf;
      const x=b.x_min+(column+0.5)*cellX+(rand()-0.5)*cellX*0.17;
      const y=b.y_min+(row+0.5)*cellY+(rand()-0.5)*cellY*0.15;
      const baseZ=Number(b.z_min)+0.012;
      const fallbackHeight=b.z_max==null?0.35:(Number(b.z_max)-Number(b.z_min))*0.72;
      const height=Number(visual.plant_height_m||fallbackHeight)*(0.91+rand()*0.17);
      const stemHeight=height*(0.23+rand()*0.08),color=new THREE.Color(palette[Math.floor(rand()*palette.length)]);
      plants.push({x,y,baseZ,height,stemHeight,color});
      const minLeaves=Number(visual.leaf_count_min||10),maxLeaves=Number(visual.leaf_count_max||14);
      const leafCount=minLeaves+Math.floor(rand()*(maxLeaves-minLeaves+1)),phase=rand()*Math.PI*2;
      for(let leafIndex=0;leafIndex<leafCount;leafIndex++) {
        const angle=phase+leafIndex*2.399+(rand()-0.5)*0.22,tilt=0.14+rand()*0.38;
        const direction=new THREE.Vector3(Math.cos(angle)*Math.cos(tilt),Math.sin(angle)*Math.cos(tilt),Math.sin(tilt)).normalize();
        const crownZ=baseZ+stemHeight*(0.72+0.42*rand()),length=height*(0.38+0.14*rand());
        leaves.push({x,y,z:crownZ,direction,length,width:length*(0.37+0.12*rand()),color:new THREE.Color(palette[Math.floor(rand()*palette.length)])});
      }
    }
    if(!plants.length)continue;
    const shelfGroup=new THREE.Group();shelfGroup.name=shelf.id;
    const pickData={kind:'visual-plant',name:shelf.id,detail:{...shelf,plant_count:plants.length,crop:visual.crop},rfIncluded:false};
    const stemMesh=new THREE.InstancedMesh(stemGeo,stemMat,plants.length);
    const crownMesh=new THREE.InstancedMesh(crownGeo,crownMat,plants.length);
    const leafMesh=new THREE.InstancedMesh(leafGeo,leafMat,leaves.length);
    stemMesh.userData=pickData;crownMesh.userData=pickData;leafMesh.userData=pickData;
    stemMesh.castShadow=true;crownMesh.castShadow=true;leafMesh.castShadow=true;
    const dummy=new THREE.Object3D();
    plants.forEach((plant,index)=>{
      dummy.position.set(plant.x,plant.y,plant.baseZ+plant.stemHeight/2);dummy.scale.set(0.78,0.78,plant.stemHeight);dummy.updateMatrix();
      stemMesh.setMatrixAt(index,dummy.matrix);stemMesh.setColorAt(index,plant.color);
      dummy.position.set(plant.x,plant.y,plant.baseZ+plant.stemHeight*0.9);dummy.scale.set(0.86,0.86,0.8);dummy.updateMatrix();
      crownMesh.setMatrixAt(index,dummy.matrix);crownMesh.setColorAt(index,plant.color);
    });
    leaves.forEach((leaf,index)=>{
      dummy.position.set(leaf.x,leaf.y,leaf.z);dummy.quaternion.setFromUnitVectors(axisX,leaf.direction);
      dummy.scale.set(leaf.length,leaf.width,1);dummy.updateMatrix();leafMesh.setMatrixAt(index,dummy.matrix);leafMesh.setColorAt(index,leaf.color);
    });
    stemMesh.instanceMatrix.needsUpdate=true;crownMesh.instanceMatrix.needsUpdate=true;leafMesh.instanceMatrix.needsUpdate=true;
    if(stemMesh.instanceColor)stemMesh.instanceColor.needsUpdate=true;
    if(crownMesh.instanceColor)crownMesh.instanceColor.needsUpdate=true;
    if(leafMesh.instanceColor)leafMesh.instanceColor.needsUpdate=true;
    shelfGroup.add(stemMesh,crownMesh,leafMesh);plantLayer.add(shelfGroup);
    totalPlants+=plants.length;totalLeaves+=leaves.length;
  }
  plantLayer.userData.plantCount=totalPlants;plantLayer.userData.leafCount=totalLeaves;
  return {plants:totalPlants,leaves:totalLeaves};
}

function createPathPolyline(path, scenario) {
  const rx = scenario.receivers.find((item) => item.name === path.receiver);
  if (!rx) return null;
  const pts = [vec(scenario.transmitter.position_m), ...(path.interaction_vertices_m || []).map(vec), vec(rx.position_m)];
  if (pts.length < 2) return null;
  const types = path.interaction_types || [];
  const color = types.length ? (interactionColors[types[0]] || '#75818b') : interactionColors.los;
  const geometry = new THREE.BufferGeometry().setFromPoints(pts);
  const material = new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.82, depthTest: true });
  const line = new THREE.Line(geometry, material);
  line.userData = { kind: 'path', path, receiver: rx, rfIncluded: true, hoverColor: color };
  line.computeLineDistances?.();
  layerGroups.paths.add(line);
  const curve = new THREE.CurvePath();
  for (let i=0; i<pts.length-1; i++) curve.add(new THREE.LineCurve3(pts[i],pts[i+1]));
  line.userData.line=line;
  pathCurves.push({ line, curve, path });
  return line;
}

function formatDb(value) { return value == null || !Number.isFinite(Number(value)) ? '—' : `${Number(value).toFixed(2)} dB`; }
function esc(value) { return String(value ?? '').replace(/[&<>"']/g, (char) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char])); }

function sceneSize(scenario) {
  const dimensions=scenario.scene_dimensions_m;
  if(Array.isArray(dimensions)&&dimensions.length>=3)return {width:Number(dimensions[0]),depth:Number(dimensions[1]),height:Number(dimensions[2])};
  const old=scenario.greenhouse;
  return {width:Number(old.length_m),depth:Number(old.width_m),height:Number(old.height_m)};
}
function sceneCenter(scenario) {
  const b=scenario.scene_bounds_m;
  if(b&&['x_min','x_max','y_min','y_max','z_min','z_max'].every(key=>Number.isFinite(Number(b[key]))))return new THREE.Vector3((b.x_min+b.x_max)/2,(b.y_min+b.y_max)/2,(b.z_min+b.z_max)/2);
  const d=sceneSize(scenario);return new THREE.Vector3(d.width/2,d.depth/2,d.height/2);
}
function cameraFitsScene(scenario, position, target) {
  const bounds=scenario.scene_bounds_m, size=Math.max(...Object.values(sceneSize(scenario))), distance=position.distanceTo(target);
  if(!bounds||!Number.isFinite(size)||size<=0||distance<size*0.18||distance>size*8)return false;
  const margin=size*0.18;
  return ['x','y','z'].every((axis,index)=>target.getComponent(index)>=Number(bounds[`${axis}_min`])-margin&&target.getComponent(index)<=Number(bounds[`${axis}_max`])+margin);
}
function addCoordinateDiagnostic(scenario) {
  const bounds=scenario.scene_bounds_m;
  if(!bounds)return;
  const size=Math.max(...Object.values(sceneSize(scenario))), axisLength=Math.max(0.6,size*0.12);
  const axes=new THREE.AxesHelper(axisLength); axes.position.set(0,0,0); axes.userData={kind:'coordinate-axes'}; layerGroups.coordinates.add(axes);
  const origin=new THREE.Mesh(new THREE.SphereGeometry(Math.max(size*0.006,0.035),12,8),new THREE.MeshBasicMaterial({color:'#203940'}));
  origin.position.set(0,0,0);origin.userData={kind:'scene-origin'};layerGroups.coordinates.add(origin);
  const box=new THREE.Box3(new THREE.Vector3(bounds.x_min,bounds.y_min,bounds.z_min),new THREE.Vector3(bounds.x_max,bounds.y_max,bounds.z_max));
  const outline=new THREE.Box3Helper(box,'#597c79');outline.userData={kind:'scene-bounds'};layerGroups.boundary.add(outline);
  const divisions=Math.max(2,Math.min(24,Math.round(size)));
  const grid=new THREE.GridHelper(size*1.25,divisions,'#819b97','#a4b7b2');
  grid.rotation.x=Math.PI/2;grid.position.set((bounds.x_min+bounds.x_max)/2,(bounds.y_min+bounds.y_max)/2,bounds.z_min);
  grid.material.transparent=true;grid.material.opacity=THEME_SCENE[currentTheme()].gridOpacity;grid.material.depthWrite=false;
  grid.userData={kind:'coordinate-grid'};layerGroups.coordinates.add(grid);
}
function layerForCategory(category) {
  if(category==='vegetation'||category==='rf_plant_zone')return 'rfProxy';
  if(['floor','metal_structure','shelf_tray','grow_light','equipment'].includes(category))return 'structure';
  return 'shell';
}

const objectColorPalette=['#4f8179','#c0784d','#617fa5','#96749c','#b39b50','#548c9b','#9c705c','#6d8c5a'];
function objectColorFor(item,index) {
  let hash=2166136261;
  for(const char of String(item.id||index))hash=Math.imul(hash^char.charCodeAt(0),16777619);
  return objectColorPalette[(hash>>>0)%objectColorPalette.length];
}
function solidColorFor(item) {
  const category=String(item.category||'').toLowerCase();
  const itu=String(item.metadata?.itu_type||'').toLowerCase();
  if(category==='floor')return '#c2c2b8';
  if(category==='greenhouse_shell'||category==='enclosure_panel'||itu.includes('glass'))return '#8fb8c0';
  if(category==='metal_structure'||category==='shelf_tray'||itu.includes('metal')||itu.includes('steel'))return '#68777c';
  if(category==='vegetation'||category==='rf_plant_zone'||itu.includes('vegetation'))return '#75946c';
  if(itu.includes('concrete'))return '#a39a8c';
  return '#89969a';
}
function applyHousionnaGeometryMode(scenario) {
  const imported=scenario?.source_type==='housionna';
  const mode=$('#housionnaGeometryMode')?.value||'solid';
  const legend=$('#objectColorLegend');
  if(!imported) { legend?.classList.add('hidden'); return; }
  const rows=scenario.geometry.objects;
  const legendRows=[];
  rows.forEach((item,index)=>{
    const mesh=objectMeshes.get(item.id);
    if(!mesh?.material)return;
    const color=mode==='object-colors'?objectColorFor(item,index):solidColorFor(item);
    const material=mesh.material;
    material.color.set(color);
    material.roughness=0.86;
    material.metalness=0.035;
    material.flatShading=true;
    material.wireframe=mode==='wireframe';
    material.transparent=mode==='transparent'||mode==='wireframe';
    material.opacity=mode==='transparent'?0.32:(mode==='wireframe'?0.82:1);
    material.depthWrite=mode!=='transparent'&&mode!=='wireframe';
    material.side=THREE.DoubleSide;
    material.needsUpdate=true;
    mesh.renderOrder=mode==='transparent'?4:1;
    legendRows.push(`<div><i style="--object-color:${color}"></i><span>${esc(item.name||item.id)}</span><b>${esc(item.material_key||item.metadata?.material_name||item.category)}</b></div>`);
  });
  if(legend){legend.innerHTML=legendRows.join('');legend.classList.toggle('hidden',mode!=='object-colors'||!legendRows.length);}
}
function sameImportedRunEntries(scenario) {
  if(scenario?.source_type!=='housionna')return [];
  return (data.scenario_order||Object.keys(data.scenarios)).map((key)=>[key,data.scenarios[key]])
    .filter(([,row])=>row?.source_type==='housionna'&&row.import_id===scenario.import_id);
}
function buildDeviceMarkers(scenario) {
  for(const [key,mesh] of objectMeshes)if(['transmitter','receiver'].includes(mesh.userData?.kind))objectMeshes.delete(key);
  disposeGroup(layerGroups.devices);
  const displayAll=scenario.source_type==='housionna'&&$('#deviceDisplayMode')?.value==='all';
  const entries=displayAll?sameImportedRunEntries(scenario):[[activeScenario,scenario]];
  txGroup=null;
  const receiverRows=new Map();
  for(const [key,row] of entries){
    const tx=row.transmitter;
    const group=buildDeviceMarker(tx.name||'TX',tx.position_m,'transmitter',tx,key);
    if(key===activeScenario)txGroup=group;
    for(const rx of row.receivers||[])receiverRows.set(`${rx.name}:${rx.position_m.join(',')}`,rx);
  }
  for(const rx of receiverRows.values())buildDeviceMarker(rx.name,rx.position_m,'receiver',rx,activeScenario);
  if(!txGroup)txGroup=layerGroups.devices.children.find((child)=>child.userData?.name===scenario.transmitter.name)||null;
}
function buildMeasurementMesh(scenario) {
  disposeGroup(layerGroups.measurement);
  for(const surface of scenario.radio_map?.surfaces||[]){
    const meshData=surface.mesh;
    if(!meshData?.vertices_m||!meshData?.faces)continue;
    const geometry=new THREE.BufferGeometry();
    geometry.setAttribute('position',new THREE.Float32BufferAttribute(meshData.vertices_m.flat(),3));
    geometry.setIndex(meshData.faces.flat());
    geometry.computeVertexNormals();
    const material=new THREE.MeshBasicMaterial({color:'#344c55',wireframe:true,transparent:true,opacity:0.76,depthWrite:false,side:THREE.DoubleSide});
    const mesh=new THREE.Mesh(geometry,material);
    mesh.userData={kind:'measurement-mesh',name:surface.name,detail:{surface:surface.name,triangle_count:meshData.faces.length,units:surface.units||scenario.radio_map.units},rfIncluded:true};
    layerGroups.measurement.add(mesh);
  }
  layerGroups.measurement.visible=scenario.source_type==='housionna'&&$('#measurementMeshToggle').checked;
}

function updateSceneSemantics(scenario) {
  const imported=scenario.source_type==='housionna';
  $('#visualWarning').textContent=imported?'EXPORTED RF SCENE · READ ONLY':'VISUAL PLANTS ≠ RF MODEL';
  $('#visualWarning').classList.toggle('housionna-warning',imported);
  if(imported){
    $('#semanticList').innerHTML='<div><i class="swatch swatch-rf"></i><span>Exported scene meshes</span><b>RF MODEL</b></div><div><i class="swatch swatch-device"></i><span>TX / RX positions</span><b>EXPORTED</b></div><div><i class="swatch swatch-map"></i><span>Measurement triangles</span><b>RF MAP</b></div><div><i class="swatch swatch-plant"></i><span>Decorative plants</span><b>NOT ADDED</b></div>';
    $('#legendSemantics').innerHTML='HOUSIONNA PLY <b>RF GEOMETRY</b> &nbsp; DEVICE POSITIONS <b>EXPORTED</b> &nbsp; TRIANGLE MAP <b>SAVED PATH GAIN</b>';
    const shell=$('[data-layer="shell"]').closest('label');
    shell.hidden=true;
    $('[data-layer="structure"]').closest('label').querySelector('.toggle-copy').lastChild.textContent=' Exported scene geometry';
    $('[data-layer="plants"]').closest('label').hidden=true;
  } else {
    $('#semanticList').innerHTML='<div><i class="swatch swatch-glass"></i><span>Enclosure panels</span><b>VISUAL + RF</b></div><div><i class="swatch swatch-metal"></i><span>Rack, trays & lights</span><b>VISUAL + RF</b></div><div><i class="swatch swatch-plant"></i><span>Detailed plants</span><b>VISUAL ONLY</b></div><div><i class="swatch swatch-rf"></i><span>Coarse RF plant zones</span><b>RF ONLY</b></div><div><i class="swatch swatch-device"></i><span>TX / RX</span><b>RF</b></div>';
    $('#legendSemantics').innerHTML='PANELS / RACK <b>VISUAL + RF</b> &nbsp; DETAILED PLANTS <b>VISUAL ONLY</b> &nbsp; RF PLANT ZONES <b>RF ONLY</b>';
    $('[data-layer="shell"]').closest('label').hidden=false;
    $('[data-layer="plants"]').closest('label').hidden=false;
    $('[data-layer="structure"]').closest('label').querySelector('.toggle-copy').lastChild.textContent=' Rack, trays & lights';
  }
}
function buildScenario({preserveView = false} = {}) {
  frameDirty=true;
  const scenario=data.scenarios[activeScenario];
  if(!scenarioReady(scenario))return;  // HOUSIONNA stubs are loaded by ensureHousionnaImport first
  if(preserveView&&scenario.source_type==='housionna'&&renderedGeometry===scenario.geometry&&layerGroups.devices){
    buildDeviceMarkers(scenario);
    updateMap();setLayerVisibility();setScenarioSummary(scenario);buildReceiverSelector(scenario);refreshReceiverMetrics(scenario);refreshPaths();
    $('#scenarioHeading').textContent=scenario.label;$('#frequencyHeading').textContent=`${(scenario.frequency_hz/1e9).toFixed(2)} GHz propagation study`;
    $('#scenarioTag').textContent=scenario.material_status;
    $('#scenarioDescription').textContent=scenario.description||'Simulation-backed scene.';
    const triangles=scenario.geometry.objects.reduce((sum,item)=>sum+(item.triangle_count??item.faces?.length??0),0);
    renderDiagnostics(scenario,{},triangles);
    const key=selectedObject?.object?.id||selectedObject?.name;
    selectObject(objectMeshes.get(key)?.userData||{kind:'scene',name:scenario.environment?.label||'Scene',detail:scenario,rfIncluded:true});
    return;
  }
  renderedGeometry=scenario.geometry;
  const savedCamera=preserveView&&camera?camera.position.clone():null;
  const savedTarget=preserveView&&controls?controls.target.clone():null;
  const savedUp=preserveView&&camera?camera.up.clone():null;
  pulseRunning=false;if(pulseMesh)pulseMesh.visible=false;
  if($('#playPathBtn'))$('#playPathBtn').textContent='Play pulse';
  const selectedKey=selectedObject?.object?.id||selectedObject?.name||null;
  disposeGroup(rootGroup);heatMesh=null;materialCache.clear();objectMeshes.clear();pathCurves=[];layerGroups={};
  for(const key of ['shell','structure','plants','rfProxy','devices','paths','map','measurement','coordinates','boundary']) {layerGroups[key]=new THREE.Group();rootGroup.add(layerGroups[key]);}
  for(const object of scenario.geometry.objects) {
    const layer=layerForCategory(object.category);
    if(layer==='rfProxy') {
      const proxyMaterial=new THREE.MeshPhysicalMaterial({color:'#3d8b5b',roughness:0.82,transparent:true,opacity:0.23,side:THREE.DoubleSide,depthWrite:false});
      boxMesh(object,layerGroups.rfProxy,'rfProxy',{material:proxyMaterial,edges:true});
      const level=object.metadata?.level;
      const label=makeLabel(`${object.id} / RF ONLY`,'proxy-label');
      label.position.set(...center(object.bounds_m));label.position.z+=dimensions(object.bounds_m)[2]/2+0.035;layerGroups.rfProxy.add(label);
    } else boxMesh(object,layerGroups[layer],layer);
  }
  const plantRows=scenario.geometry.objects.filter(item=>item.category==='vegetation');
  const plantStats=buildVisualPlants(plantRows,scenario.visual_plants||{});
  for(const position of scenario.environment?.grow_light_positions_m||[]) {
    const light=new THREE.PointLight('#edffd1',2.2,Math.max(...Object.values(sceneSize(scenario)))*0.72,1.6);
    light.position.copy(vec(position));layerGroups.structure.add(light);
  }
  buildDeviceMarkers(scenario);
  addCoordinateDiagnostic(scenario);
  buildMeasurementMesh(scenario);
  applyHousionnaGeometryMode(scenario);
  const hasRfPlants=scenario.geometry.objects.some(item=>item.category==='rf_plant_zone'||item.category==='vegetation');
  const hasVisualPlants=scenario.geometry.objects.some(item=>item.category==='vegetation')&&Boolean(scenario.visual_plants?.planting_pattern);
  $('[data-layer="plants"]').closest('label').hidden=!hasVisualPlants;
  $('[data-layer="rfProxy"]').closest('label').hidden=!hasRfPlants;
  $('[data-layer="rfProxy"]').checked=hasRfPlants;
  $('[data-layer="plants"]').checked=scenario.visual_plants?.visible_by_default!==false;
  $('#differenceToggle').checked=false;
  $('#differenceToggle').disabled=scenario.source_type==='housionna';
  $('#differenceToggle').closest('.toggle-subrow').classList.toggle('hidden',scenario.source_type==='housionna');
  syncMapLevels(scenario);
  updateSceneSemantics(scenario);
  setLayerVisibility();setScenarioSummary(scenario);buildReceiverSelector(scenario);refreshReceiverMetrics(scenario);
  selectedObject=selectedKey&&objectMeshes.has(selectedKey)?objectMeshes.get(selectedKey).userData:null;
  $('#scenarioHeading').textContent=scenario.label;
  $('#frequencyHeading').textContent=`${(scenario.frequency_hz/1e9).toFixed(2)} GHz propagation study`;
  $('#scenarioTag').textContent=scenario.material_status;
  $('#scenarioDescription').textContent=scenario.description||'Simulation-backed scene.';
  $('#environmentHeading').textContent=scenario.environment?.label||'CEA greenhouse';
  const d=sceneSize(scenario);
  const triangleCount=scenario.geometry.objects.reduce((sum,item)=>sum+(item.triangle_count??item.faces?.length??0),0);
  $('#sceneMeta').textContent=scenario.source_type==='housionna'
    ?`${d.width.toFixed(2)} x ${d.depth.toFixed(2)} x ${d.height.toFixed(2)} m | ${scenario.geometry.objects.length} RF mesh objects | ${triangleCount.toLocaleString()} triangles`
    :`${d.width.toFixed(2)} x ${d.depth.toFixed(2)} x ${d.height.toFixed(2)} m | ${scenario.geometry.objects.length} RF objects`;
  $('#backendLabel').textContent=backendInfo?.backend||`Sionna RT ${data.sionna_version}`;
  renderDiagnostics(scenario,plantStats,triangleCount);
  if(!selectedObject)selectObject({kind:'scene',name:scenario.environment?.label||'Scene',detail:scenario,rfIncluded:true});
  else selectObject(selectedObject);
  if(savedCamera&&savedTarget&&cameraFitsScene(scenario,savedCamera,savedTarget)){camera.position.copy(savedCamera);camera.up.copy(savedUp);controls.target.copy(savedTarget);camera.lookAt(savedTarget);controls.update();}
  else focusScene('isometric');
  updateMap();refreshPaths();
}

function renderDiagnostics(scenario,plantStats,triangleCount) {
  const d=sceneSize(scenario);
  const imported=scenario.source_type==='housionna';
  const run=scenario.run_metadata||{};
  const provenance=scenario.provenance||{};
  const surfaceTriangles=(scenario.radio_map?.surfaces||[]).reduce((sum,surface)=>sum+(surface.mesh?.faces?.length||surface.values_db?.length||0),0);
  let rows;
  if(imported) {
    const warnings=provenance.validation_warnings||[];
    rows=[
      ['Run ID',run.run_id||provenance.run_folder_name||'unknown'],
      ['Source scene',run.scene_name||'unknown'],
      ['Frequency',`${(scenario.frequency_hz/1e9).toFixed(3)} GHz`],
      ['Selected TX',scenario.transmitter.name],
      ['Run devices',`${run.tx_count??1} TX / ${run.rx_count??scenario.receivers.length} RX`],
      ['RF mesh objects',scenario.geometry.objects.length],
      ['RF scene triangles',triangleCount.toLocaleString()],
      ['Measurement triangles / TX',surfaceTriangles.toLocaleString()],
      ['Map cells across all TXs',Number(run.radio_map_triangle_count||0).toLocaleString()],
      ['Bounds X/Y/Z',`${d.width.toFixed(3)} x ${d.depth.toFixed(3)} x ${d.height.toFixed(3)} m`],
      ['Coordinates','XYZ metres / Z up / pass-through'],
      ['Geometry display',$('#housionnaGeometryMode').value],
      ['Path endpoint check',`${provenance.max_path_endpoint_error_m==null?'not recorded':`${Number(provenance.max_path_endpoint_error_m).toExponential(2)} m`} / ${provenance.path_endpoint_tolerance_m==null?'default tolerance':`${Number(provenance.path_endpoint_tolerance_m).toExponential(2)} m tolerance`}`],
      ['Importer warnings',warnings.length?warnings.join('; '):'none reported'],
    ];
  } else {
    rows=[
      ['Scenario',scenario.label],
      ['Sionna RT',backendInfo?.sionna_version||data.sionna_version],
      ['Backend',backendInfo?.backend||data.backend.runtime],
      ['Frequency',`${(scenario.frequency_hz/1e9).toFixed(3)} GHz`],
      ['Scene dimensions',`${d.width.toFixed(2)} x ${d.depth.toFixed(2)} x ${d.height.toFixed(2)} m`],
      ['RF objects',scenario.geometry.objects.length],
      ['Receivers',scenario.receivers.length],
      ['Map grid',scenario.radio_map.shape_yx?.join(' x ')||`${scenario.radio_map.values_db.length} x ${scenario.radio_map.values_db[0]?.length}`],
      ['Visual plants',`${plantStats.plants} instances / ${plantStats.leaves} leaves`],
      ['Last runtime',$('#simulationRuntime').textContent],
    ];
  }
  $('#diagnostics').innerHTML=`<b>DIAGNOSTICS</b>${rows.map(([label,value])=>`<span>${esc(label)}</span><strong>${esc(value)}</strong>`).join('')}<span>Displayed paths</span><strong id="diagPaths">0</strong>`;
}

function setScenarioSummary(scenario) {
  const d=sceneSize(scenario);
  $('#scenarioDescription').title=`From ${data.source}`;
  $('#detailSubtitle').textContent=scenario.source_type==='housionna'
    ?`Exported HOUSIONNA scene / ${d.width.toFixed(2)} m X / ${d.depth.toFixed(2)} m Y / ${d.height.toFixed(2)} m Z`
    :`Configured RF scene / ${d.width.toFixed(2)} m wide / ${d.depth.toFixed(2)} m deep / ${d.height.toFixed(2)} m high`;
}

function buildReceiverSelector(scenario) {
  const select = $('#receiverSelect');
  const current = activeReceiver;
  select.innerHTML = scenario.receivers.map((rx)=>`<option value="${esc(rx.name)}">${esc(rx.name)} · ${esc(rx.role || 'receiver')}</option>`).join('');
  activeReceiver = scenario.receivers.some((rx)=>rx.name===current) ? current : scenario.receivers[0]?.name;
  select.value = activeReceiver;
}

function receiverMetric(scenario, name) { return scenario.receiver_metrics.find((item)=>item.receiver===name) || null; }

function refreshReceiverMetrics(scenario) {
  const metric = receiverMetric(scenario,activeReceiver);
  $('#receiverMetrics').innerHTML = metric ? `
    <div class="metric-strip"><div><span>VALID PATHS</span><b>${metric.path_count}</b></div><div><span>LOS</span><b class="${metric.los_present?'good':'bad'}">${metric.los_present?'YES':'NO'}</b></div></div>
    <div class="metric-line"><span>Transmitter</span><b>${esc(scenario.transmitter.name)}</b></div>
    <div class="metric-line"><span>Strongest path</span><b>${formatDb(metric.strongest_path_db)}</b></div>
    <div class="metric-line"><span>Path delay</span><b>${metric.strongest_path_delay_ns == null ? '—' : `${Number(metric.strongest_path_delay_ns).toFixed(2)} ns`}</b></div>
    <div class="metric-line"><span>Aggregate Σ|a|²</span><b>${formatDb(metric.aggregate_path_coefficient_power_db)}</b></div>
    <div class="metric-line"><span>Refraction paths</span><b>${metric.interaction_path_counts?.refraction || 0}</b></div>
    ${metric.link_metrics ? `<div class="metric-line"><span>Coherent link gain</span><b>${formatDb(metric.link_metrics.gain_db_coherent)}</b></div><div class="metric-line"><span>Delay spread</span><b>${metric.link_metrics.delay_spread_ns == null ? '—' : `${Number(metric.link_metrics.delay_spread_ns).toFixed(3)} ns`}</b></div>` : ''}` : '<div class="muted-copy">No saved receiver metrics.</div>';
  refreshPaths();
}

function setLayerVisibility() {
  if(!layerGroups.shell)return;
  layerGroups.shell.visible=$('[data-layer="shell"]').checked;
  layerGroups.structure.visible=$('[data-layer="structure"]').checked;
  layerGroups.plants.visible=$('[data-layer="plants"]').checked;
  layerGroups.rfProxy.visible=$('[data-layer="rfProxy"]').checked;
  layerGroups.devices.visible=$('[data-layer="devices"]').checked;
  layerGroups.paths.visible=$('#pathsToggle').checked;
  layerGroups.map.visible=$('[data-layer="map"]').checked;
  if(layerGroups.measurement)layerGroups.measurement.visible=data.scenarios[activeScenario]?.source_type==='housionna'&&$('#measurementMeshToggle').checked;
  if(layerGroups.coordinates)layerGroups.coordinates.visible=$('#coordinateDiagnosticToggle').checked;
  if(layerGroups.boundary)layerGroups.boundary.visible=$('#sceneBoundsToggle').checked;
  const scenario=data.scenarios[activeScenario];
  const labelMode=scenario?.source_type==='housionna'?$('#deviceLabelMode').value:'all';
  const selectedDeviceNames=new Set([scenario?.transmitter?.name,...(scenario?.receivers||[]).map(row=>row.name)]);
  layerGroups.devices.traverse(item=>{
    if(!item.isCSS2DObject)return;
    const label=item.userData||{};
    item.visible=$('#labelsToggle').checked&&(labelMode==='all'||(labelMode==='selected'&&selectedDeviceNames.has(label.deviceName)));
  });
  for(const object of layerGroups.rfProxy.children)if(object.isCSS2DObject)object.visible=$('#labelsToggle').checked;
  const measurementAvailable=Boolean(scenario?.radio_map?.surfaces?.length);
  $('#measurementMeshToggle').disabled=!measurementAvailable;
  if(!measurementAvailable)$('#measurementMeshToggle').checked=false;
  $('#mapControls').classList.toggle('hidden',!$('[data-layer="map"]').checked);
  const imported=scenario?.source_type==='housionna';
  const hasRfPlants=scenario?.geometry.objects.some(item=>item.category==='rf_plant_zone'||item.category==='vegetation');
  $('[data-layer="shell"]').closest('label').hidden=imported;
  $('[data-layer="plants"]').closest('label').hidden=imported||!scenario?.geometry.objects.some(item=>item.category==='vegetation');
  $('[data-layer="rfProxy"]').closest('label').hidden=imported||!hasRfPlants;
  $('[data-layer="structure"]').closest('label').querySelector('.toggle-copy').lastChild.textContent=imported?' Exported scene geometry':' Rack, trays & lights';
  $('#rfStatus').textContent=imported
    ?'Showing the exported HOUSIONNA scene meshes and saved RF results. No decorative plants are generated.'
    :$('[data-layer="rfProxy"]').checked
      ?'RF plant zones are coarse Sionna proxies. Detailed instanced plants remain visual-only.'
      :'Detailed instanced plants are visual-only; the RF plant-zone layer is independently hidden.';
}

function housionnaRadioMapDifference(scenario) {
  const original=housionnaOriginalResults.get(activeScenario),latest=housionnaLatestResults.get(activeScenario);
  if(!original||!latest||!latest.radio_map?.metadata)return {map:null,reason:'Run a new radio map before comparing original and rerun values.'};
  if(!Number.isFinite(Number(original.frequency_hz))||!Number.isFinite(Number(latest.frequency_hz))||
     Math.abs(Number(original.frequency_hz)-Number(latest.frequency_hz))>1) {
    return {map:null,reason:'Radio-map difference requires matching carrier frequencies.'};
  }
  if(latest.radio_map.metadata.frequency_hz!=null&&
     Math.abs(Number(latest.radio_map.metadata.frequency_hz)-Number(latest.frequency_hz))>1) {
    return {map:null,reason:'The latest radio map was calculated at a different frequency from its path result.'};
  }
  const first=original.radio_map?.surfaces||[],second=latest.radio_map?.surfaces||[];
  if(!first.length||first.length!==second.length)return {map:null,reason:'Original and rerun measurement surfaces do not match.'};
  const surfaces=[];let jointlyValid=0;const deltas=[];
  for(let surfaceIndex=0;surfaceIndex<first.length;surfaceIndex++) {
    const left=first[surfaceIndex],right=second[surfaceIndex],mesh=left.mesh;
    if(!mesh||!right.mesh||left.quantity!=='path_gain'||right.quantity!=='path_gain'||
       left.name!==right.name||left.mesh_ref!==right.mesh_ref||
       left.mesh.vertices_m!==right.mesh.vertices_m||left.mesh.faces!==right.mesh.faces||
       left.values_db.length!==mesh.faces.length||right.values_db.length!==mesh.faces.length) {
      return {map:null,reason:'Radio-map difference requires identical measurement triangle geometry and ordering.'};
    }
    const values=left.values_db.map((value,index)=>{
      const rerun=right.values_db[index];
      if(value==null||rerun==null||!Number.isFinite(Number(value))||!Number.isFinite(Number(rerun)))return null;
      const delta=Number(rerun)-Number(value);jointlyValid++;deltas.push(delta);return delta;
    });
    surfaces.push({...right,values_db:values,mesh});
  }
  const maxAbs=deltas.length?Math.max(...deltas.map(Math.abs)):0;
  return {map:{...latest.radio_map,surfaces,quantity:'path_gain_difference',units:'Rerun − original path gain, dB',
    min_db:-maxAbs,max_db:maxAbs,center_m:original.radio_map.center_m,
    metadata:{...latest.radio_map.metadata,comparison:'rerun_minus_original',jointly_valid_cells:jointlyValid}},reason:null};
}

function syncHousionnaMapMode() {
  const imported=data?.scenarios?.[activeScenario]?.source_type==='housionna';
  $('#housionnaMapModeLabel').classList.toggle('hidden',!imported);
  $('#housionnaMapMode').classList.toggle('hidden',!imported);
  $('#housionnaMapMode').disabled=!imported;
  const differenceOption=$('#housionnaMapMode').querySelector('option[value="difference"]');
  if(imported) {
    const difference=housionnaRadioMapDifference(data.scenarios[activeScenario]);
    differenceOption.disabled=Boolean(difference.reason);
    if(differenceOption.disabled&&$('#housionnaMapMode').value==='difference')$('#housionnaMapMode').value='selected';
    differenceOption.title=difference.reason||'Same frequency, measurement geometry, face ordering, and path-gain quantity verified.';
  }
}

// Vertical-farm runs solve one map per shelf level, in the air gap above the canopy. The level selector picks one;
// the map then sits at that plane's real height (the height slider is only free for single-plane maps).
const ZONE_NAMES={front_opening:'In front',over_canopy:'Over canopy',rack_other:'Beside canopy',outside:'Outside rack'};
function syncMapLevels(scenario) {
  const planes=scenario.map_planes||[],select=$('#mapLevel');
  $('#mapLevelRow').classList.toggle('hidden',!planes.length);
  if(!planes.length){select.innerHTML='';return;}
  const kept=Number(select.value),levels=planes.map((plane)=>plane.level);
  const primaryZ=Number(scenario.radio_map?.center_m?.[2]);
  select.innerHTML=planes.map((plane)=>`<option value="${plane.level}">Level ${plane.level} · ${Number(plane.height_m).toFixed(2)} m</option>`).join('');
  const primary=planes.find((plane)=>Math.abs(Number(plane.height_m)-primaryZ)<1e-6)?.level??levels[0];
  select.value=String(levels.includes(kept)?kept:primary);
}
function selectedMapPlane(scenario) {
  const planes=scenario.map_planes||[];
  if(!planes.length)return null;
  return planes.find((plane)=>plane.level===Number($('#mapLevel').value))||planes[0];
}
function renderZoneReport(scenario,level) {
  const panel=$('#zoneReport');
  if(!level){panel.classList.add('hidden');return;}
  panel.classList.remove('hidden');
  const row=(scenario.zone_report||[]).find((item)=>item.level===level.level);
  if(!row){panel.innerHTML=`<div class="legend-title">CANOPY EFFECT · LEVEL ${level.level}</div><p class="muted-copy">The empty rack is the reference. Choose a canopy scenario to see its effect per zone.</p>`;return;}
  const labels=scenario.zone_labels||{},sensitivity=scenario.coverage_threshold?.receiver_sensitivity_dbm;
  const pct=(value)=>`${Math.round(Number(value)*100)}%`;
  const db=(value)=>value==null?'—':`${value>0?'+':''}${Number(value).toFixed(1)} dB`;
  panel.innerHTML=`<div class="legend-title">CANOPY EFFECT VS EMPTY · LEVEL ${level.level}</div>
    <div class="zone-coverage">Coverage <b class="num">${pct(row.coverage_empty)} → ${pct(row.coverage_scenario)}</b>${sensitivity==null?'':` <span class="subtle">at ${sensitivity} dBm (placeholder)</span>`}</div>
    <table class="zone-table"><thead><tr><th scope="col">Zone</th><th scope="col">Median Δ</th><th scope="col">Coverage</th></tr></thead><tbody>${Object.entries(row.zones).map(([zone,stats])=>`<tr><th scope="row" title="${esc(labels[zone]||zone)}">${esc(ZONE_NAMES[zone]||zone)}</th><td class="num">${db(stats.median_delta_db)}</td><td class="num">${pct(stats.coverage_empty)} → ${pct(stats.coverage_scenario)}</td></tr>`).join('')}</tbody></table>
    <p class="muted-copy">Median over cells with signal in both maps. Placeholder materials: not a real-farm prediction.</p>`;
}

function scenarioReady(scenario) {
  return Boolean(scenario)&&!scenario.stub;
}

function updateMap() {
  frameDirty=true;
  if (!activeScenario || !layerGroups.map) return;
  const scenario = data.scenarios[activeScenario];
  const isDiff = $('#differenceToggle').checked;
  const level = selectedMapPlane(scenario);
  renderZoneReport(scenario, level);
  syncHousionnaMapMode();
  let map = scenario.radio_map;
  if(scenario.source_type==='housionna'&&$('#housionnaMapMode').value==='difference') {
    const difference=housionnaRadioMapDifference(scenario);
    if(difference.reason){$('#mapLegend').textContent=difference.reason;return;}
    map=difference.map;
  }
  if (!isDiff && map.surfaces?.length) {
    updateTriangleRadioMap(scenario, map);
    return;
  }
  disposeGroup(layerGroups.map);heatMesh=null;
  const values = level ? (isDiff ? level.difference_db : level.values_db)
    : (isDiff ? scenario.difference_map_db : scenario.radio_map.values_db);
  if (!Array.isArray(values) || !values.length || !Array.isArray(values[0]) || !values[0].length) {
    $('#mapLegend').textContent = 'No saved difference map for this scenario.';
    return;
  }
  const rows=values.length, cols=values[0].length;
  const maxAbs = Math.max(1,...values.flat().map((v)=>Math.abs(Number(v))));
  const minVal = Math.min(...values.flat().map(Number)), maxVal = Math.max(...values.flat().map(Number));
  const canvas = document.createElement('canvas'); canvas.width=cols; canvas.height=rows;
  const ctx=canvas.getContext('2d');
  const image=ctx.createImageData(cols,rows);
  for(let y=0;y<rows;y++) for(let x=0;x<cols;x++) {
    const value=Number(values[y][x]);
    const color=isDiff ? diffColor(value/maxAbs) : absoluteColor((value-minVal)/Math.max(1e-6,maxVal-minVal));
    const offset=((rows-1-y)*cols+x)*4;
    image.data[offset]=color[0]; image.data[offset+1]=color[1]; image.data[offset+2]=color[2]; image.data[offset+3]=255;
  }
  ctx.putImageData(image,0,0);
  const texture=new THREE.CanvasTexture(canvas); texture.colorSpace=THREE.SRGBColorSpace; texture.magFilter=THREE.LinearFilter; texture.minFilter=THREE.LinearFilter; texture.needsUpdate=true;
  const mapHeight=Number(level ? level.height_m : map.center_m[2]);
  const heightControl=$('#mapHeight');
  heightControl.disabled=Boolean(level);$('#mapHeightLabel').childNodes[0].textContent=level?'Plane height ':'Map height ';
  heightControl.min=String(Math.min(0,mapHeight));heightControl.max=String(Math.max(sceneSize(scenario).height,mapHeight));
  heightControl.step=String(Math.max(sceneSize(scenario).height/80,0.01));heightControl.value=String(mapHeight);
  $('#heightValue').textContent=`${mapHeight.toFixed(2)} m`;
  const plane=new THREE.PlaneGeometry(map.size_m[0],map.size_m[1]);
  const mat=new THREE.MeshBasicMaterial({map:texture,transparent:true,opacity:Number($('#mapOpacity').value)/100,side:THREE.DoubleSide,depthWrite:false});
  heatMesh=new THREE.Mesh(plane,mat);
  // Use the exact plane height: the slider snaps to its step, which would shift the map by up to a step.
  heatMesh.position.set(map.center_m[0],map.center_m[1],mapHeight);
  const levelName=level?` · level ${level.level}`:'';
  heatMesh.rotation.z=0; heatMesh.userData={kind:'radio-map',name:isDiff?`${scenario.label} − Empty map difference${levelName}`:`${scenario.label} radio map${levelName}`,detail:{values_db:values,units:isDiff?'dB difference':'path gain (dB)',grid:[rows,cols]},rfIncluded:true};
  layerGroups.map.add(heatMesh);
  const edge = new THREE.LineSegments(new THREE.EdgesGeometry(plane),new THREE.LineBasicMaterial({color:isDiff?'#61485f':'#477f87',transparent:true,opacity:0.48}));
  edge.position.copy(heatMesh.position); layerGroups.map.add(edge);
  $('#mapLegend').innerHTML = isDiff ? `<div class="legend-title">${esc(scenario.label.toUpperCase())} − EMPTY · dB</div><div class="legend-ramp diff-ramp"></div><div class="legend-range"><span>−${maxAbs.toFixed(1)}</span><span>0</span><span>+${maxAbs.toFixed(1)}</span></div>` : `<div class="legend-title">PATH GAIN · dB</div><div class="legend-ramp abs-ramp"></div><div class="legend-range"><span>${minVal.toFixed(1)}</span><span>${((minVal+maxVal)/2).toFixed(1)}</span><span>${maxVal.toFixed(1)}</span></div>`;
  layerGroups.map.visible=$('[data-layer="map"]').checked;
}

function updateTriangleRadioMap(scenario, map) {
  const {min:minVal,max:maxVal,count:cellCount}=finiteRange(map.surfaces.flatMap(surface=>surface.values_db||[]));
  const range = Math.max(1e-6, maxVal - minVal);
  const centerZ = Number(map.center_m?.[2] || 0);
  const heightControl = $('#mapHeight');
  const bounds = scenario.scene_bounds_m;
  heightControl.min = String(Math.min(bounds?.z_min ?? 0, centerZ));
  heightControl.max = String(Math.max(bounds?.z_max ?? sceneSize(scenario).height, centerZ));
  heightControl.step = String(Math.max(sceneSize(scenario).height / 80, 0.01));
  heightControl.value = String(centerZ);
  heightControl.disabled = true;
  $('#mapHeightLabel').childNodes[0].textContent = 'Exported map position ';
  $('#heightValue').textContent = `${centerZ.toFixed(2)} m`;

  const reusable=heatMesh?.userData?.surfaceMeshes?.length===map.surfaces.length&&
    map.surfaces.every((surface,index)=>heatMesh.userData.surfaceMeshes[index]===surface.mesh);
  if(!reusable){
    disposeGroup(layerGroups.map);
    heatMesh=new THREE.Group();
    heatMesh.userData.surfaceMeshes=map.surfaces.map(surface=>surface.mesh);
    layerGroups.map.add(heatMesh);
  }
  Object.assign(heatMesh.userData,{ kind: 'radio-map', name: `${scenario.label} measurement-surface radio map`, rfIncluded: true });
  for (const [surfaceIndex,surface] of map.surfaces.entries()) {
    const meshData = surface.mesh;
    if (!meshData?.vertices_m || !meshData?.faces) continue;
    let mesh=reusable?heatMesh.children[surfaceIndex]:null;
    const positions=mesh?null:new Float32Array(meshData.faces.length*9);
    const colors=mesh?mesh.geometry.getAttribute('color').array:new Float32Array(meshData.faces.length*12);
    let validCells = 0;
    for (let faceIndex = 0; faceIndex < meshData.faces.length; faceIndex++) {
      const rawValue = surface.values_db?.[faceIndex];
      const value = Number(rawValue);
      const valid=rawValue!=null&&Number.isFinite(value);
      const difference=map.quantity==='path_gain_difference';
      const maxAbs=Math.max(Math.abs(minVal),Math.abs(maxVal),1e-12);
      const color=valid?(difference?diffColor(value/maxAbs):absoluteColor((value-minVal)/range)).map(channel=>channel/255):[0,0,0];
      const face = meshData.faces[faceIndex];
      for (const [corner,vertexIndex] of face.entries()) {
        const point = meshData.vertices_m[vertexIndex];
        if (!point) continue;
        const vertex=faceIndex*3+corner;
        if(positions)positions.set(point,vertex*3);
        colors.set([...color,valid?1:0],vertex*4);
      }
      if(valid)validCells++;
    }
    if(!mesh){
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.BufferAttribute(colors, 4).setUsage(THREE.DynamicDrawUsage));
    const material = new THREE.MeshBasicMaterial({
      vertexColors: true, transparent: true, opacity: Number($('#mapOpacity').value) / 100,
      side: THREE.DoubleSide, depthWrite: false,
    });
    mesh = new THREE.Mesh(geometry, material);
    heatMesh.add(mesh);
    }
    mesh.geometry.getAttribute('color').needsUpdate=true;
    mesh.userData = {
      kind: 'radio-map', name: `${scenario.label} · ${surface.name}`,
      detail: { units: surface.units || map.units, surface: surface.name, cell_count: validCells },
      rfIncluded: true,
    };
  }
  const mapSource=map.metadata?`SIONNA RT ${esc(map.metadata.quality||'rerun')} · ${Number(map.metadata.samples_per_tx||0).toLocaleString()} samples`:'ORIGINAL HOUSIONNA EXPORT';
  const mapInputs=map.metadata?`${(map.metadata.frequency_hz/1e9).toFixed(3)} GHz · TX [${map.metadata.tx_position_m.map(v=>Number(v).toFixed(2)).join(', ')}] m · depth ${map.metadata.solver.max_depth}`:'Source frequency and TX placement';
  const difference=map.quantity==='path_gain_difference';
  $('#mapLegend').innerHTML = `<div class="legend-title">${difference?'RERUN − ORIGINAL':'TRIANGLE PATH GAIN'} TX ${esc(scenario.transmitter.name)} dB</div><div class="legend-range"><span>${mapSource}</span></div><div class="legend-ramp ${difference?'diff-ramp':'abs-ramp'}"></div><div class="legend-range"><span>${minVal.toFixed(1)}</span><span>${difference?'0.0':((minVal + maxVal) / 2).toFixed(1)}</span><span>${maxVal.toFixed(1)}</span></div>`;
  layerGroups.map.visible = $('[data-layer="map"]').checked;
  $('#mapLegend').insertAdjacentHTML('beforeend',`<div class="map-inputs">${esc(mapInputs)} · ${cellCount.toLocaleString()} valid / ${map.surfaces.reduce((n,s)=>n+s.values_db.length,0).toLocaleString()} triangles. Missing cells are transparent.</div>`);
  if(!cellCount)$('#mapLegend').textContent='No valid triangles. Missing RF values are transparent; no values were invented.';
}


function setRadioMapOpacity(opacity) {
  if (!heatMesh) return;
  heatMesh.traverse((item) => {
    if (item.material && 'opacity' in item.material) item.material.opacity = opacity;
  });
}

function absoluteColor(t) {
  const stops=[[42,72,112],[42,125,142],[49,169,128],[156,201,82],[244,222,70]];
  const v=Math.max(0,Math.min(0.9999,t))*(stops.length-1), i=Math.floor(v), f=v-i;
  return stops[i].map((value,j)=>Math.round(value*(1-f)+stops[i+1][j]*f));
}
function diffColor(t) {
  const stops=[[63,116,174],[156,190,212],[231,234,229],[230,171,128],[177,74,66]];
  const v=(Math.max(-1,Math.min(1,t))+1)*0.5*(stops.length-1), i=Math.min(stops.length-2,Math.floor(v)), f=v-i;
  return stops[i].map((value,j)=>Math.round(value*(1-f)+stops[i+1][j]*f));
}

function refreshPaths() {
  if (!layerGroups.paths || !activeScenario) return;
  disposeGroup(layerGroups.paths); pathCurves=[]; pulseCurve=null;
  if(rfResultsStale) {
    layerGroups.paths.visible=false;
    $('#pathLegend').innerHTML='<span>Paths hidden because RF settings changed</span>';
    $('#pathCountLabel').textContent='Stale paths hidden';
    $('#playPathBtn').disabled=true;
    $('#diagPaths') && ($('#diagPaths').textContent='stale');
    return;
  }
  const scenario=data.scenarios[activeScenario];
  const all=scenario.paths.filter((path)=>path.receiver===activeReceiver).sort((a,b)=>pathMagnitude(b)-pathMagnitude(a));
  const mode=$('#pathFilter').value;
  const chosen=mode==='strongest'?all.slice(0,1):mode==='top5'?all.slice(0,5):all;
  let chosenPath=null;
  chosen.forEach((path,index)=>{
    const line=createPathPolyline(path,scenario);
    if (line && index===0) chosenPath={line,path};
  });
  layerGroups.paths.visible=$('#pathsToggle').checked;
  const types=[...new Set(chosen.flatMap((path)=>path.interaction_types?.length?path.interaction_types:['los']))];
  $('#pathLegend').innerHTML=types.map((type)=>`<span><i style="background:${interactionColors[type]||'#75818b'}"></i>${esc(type.replaceAll('_',' '))}</span>`).join('')||'<span>No saved paths for this receiver</span>';
  $('#pathCountLabel').textContent=$('#pathsToggle').checked?`${chosen.length} / ${all.length} shown / ${scenario.transmitter.name}`:`Paths off / ${scenario.transmitter.name}`;
  $('#diagPaths') && ($('#diagPaths').textContent=$('#pathsToggle').checked?String(chosen.length):'0');
  $('#playPathBtn').disabled=!chosenPath || reducedMotion;
  if (chosenPath) pulseCurve=pathCurves.find((item)=>item.line===chosenPath.line)?.curve || null;
  $('#playPathBtn').title=reducedMotion?'Disabled by reduced-motion preference':'Animate a pulse on the strongest displayed path';
}
function pathMagnitude(path) { return Number(path.magnitude_db ?? path.coefficient_magnitude_db_re_1 ?? -300); }

function showValue(label,value) { return `<div class="property-row"><span>${esc(label)}</span><b>${esc(value)}</b></div>`; }
function materialText(key,scenario) {
  const material=scenario.materials?.[key];
  if(!material) return key||'—';
  const eps=material.relative_permittivity;
  const sigma=material.conductivity_s_per_m;
  return `${key} · εᵣ ${eps ?? '—'} · σ ${sigma ?? '—'} S/m`;
}

function selectObject(object) {
  selectedObject=object;
  if(selectionOutline){scene.remove(selectionOutline);selectionOutline.geometry.dispose();selectionOutline.material.dispose();selectionOutline=null;}
  const mesh=object.kind==='path'?object.line
    :object.kind==='radio-map'?heatMesh
      :object.kind==='measurement-mesh'?layerGroups.measurement.children.find(item=>item.userData.name===object.name)
        :objectMeshes.get(object.name||object.object?.id);
  if(mesh?.isObject3D&&mesh.geometry&&object.kind!=='path'&&object.kind!=='visual-plant') {
    selectionOutline=new THREE.LineSegments(new THREE.EdgesGeometry(mesh.geometry),new THREE.LineBasicMaterial({color:'#fff7da',depthTest:false,transparent:true,opacity:0.95}));
    selectionOutline.position.copy(mesh.position);selectionOutline.rotation.copy(mesh.rotation);selectionOutline.scale.copy(mesh.scale);selectionOutline.renderOrder=50;scene.add(selectionOutline);
  }
  const scenario=data.scenarios[activeScenario],d=sceneSize(scenario),imported=scenario.source_type==='housionna';
  let title=object.name||'Scene',type='OBJECT',subtitle='Selected element',body='',selectedReceiverMetric=null;
  if(object.kind==='scene') {
    const triangleCount=scenario.geometry.objects.reduce((sum,item)=>sum+(item.triangle_count??item.faces?.length??0),0);
    const plantCount=scenario.geometry.objects.filter(item=>item.category==='rf_plant_zone'||item.category==='vegetation').length;
    type='SCENE';title=scenario.environment?.label||'CEA greenhouse';subtitle=`${d.width.toFixed(2)} x ${d.depth.toFixed(2)} x ${d.height.toFixed(2)} m`;
    body=showValue('RF scene mesh objects',scenario.geometry.objects.length)+showValue('RF scene triangles',triangleCount)+showValue('RF plant zones',plantCount)+showValue('RF material status',scenario.material_status);
    if(imported)body+=showValue('HOUSIONNA run',scenario.run_metadata?.run_id||scenario.provenance?.run_folder_name)+showValue('Source scene',scenario.run_metadata?.scene_name||'unknown')+showValue('Selected TX',scenario.transmitter.name)+showValue('TX / RX count',`${scenario.run_metadata?.tx_count??1} / ${scenario.run_metadata?.rx_count??scenario.receivers.length}`)+showValue('Measurement triangles / TX',(scenario.radio_map?.surfaces||[]).reduce((sum,row)=>sum+(row.mesh?.faces?.length||row.values_db?.length||0),0))+showValue('Coordinate frame','XYZ metres, Z up; exporter transform already applied');
    else body+=showValue('Visual plants',`${layerGroups.plants.userData.plantCount||0} instanced plants / visual-only`)+showValue('Scene data',data.source);
  } else if(object.kind==='geometry') {
    const item=object.object,size=dimensions(item.bounds_m),material=materialText(item.material_key,scenario),meta=item.metadata||{};
    type=item.category.toUpperCase().replaceAll('_',' ');title=item.name||item.id;subtitle=`${size.map(v=>v.toFixed(2)).join(' x ')} m / ${item.category}`;
    body=showValue('Object name',item.name||item.object_name||item.id)+showValue('Object ID',item.id)+showValue('Category',item.category)+showValue('Bounds X/Y/Z',`${size.map(v=>v.toFixed(3)).join(' x ')} m`)+showValue('Triangles',item.triangle_count??item.faces?.length??'-')+showValue('Viewer material',visualMaterial(item.category,item,scenario))+showValue('RF material',material)+showValue('Included in Sionna',item.rf_relevant===false?'No':'Yes / exported RF object');
    if(meta.scene_shape_id)body+=showValue('Sionna shape ID',meta.scene_shape_id);
    if(meta.mesh_file)body+=showValue('Source mesh',meta.mesh_file);
    if(meta.itu_type)body+=showValue('ITU material type',meta.itu_type);
    if(imported)body+=showValue('Rendering mode',$('#housionnaGeometryMode').value+' / viewer only')+showValue('Source run',scenario.provenance?.run_folder_name||scenario.run_metadata?.run_id)+showValue('Import revision',scenario.import_id||scenario.run_metadata?.import_id);
    if(meta.shelf_id)body+=showValue('Shelf / level',`${meta.shelf_id} / ${meta.level??''}`);
    if(meta.rf_role)body+=showValue('Model role',meta.rf_role);
    if(item.category==='rf_plant_zone'||item.category==='vegetation')body+=showValue('RF status',scenario.material_status)+showValue('Detailed visual plants in RF','No / separate visual-only instancing');
  } else if(object.kind==='visual-plant') {
    const plant=object.detail||{},b=plant.bounds_m||{},plantHeight=Number(scenario.visual_plants?.plant_height_m||0);
    type='VISUAL ONLY';title=`${plant.id||object.name||'Growing shelf'}`;subtitle=`Leafy crop / level ${plant.level??'-'}`;
    body=showValue('Shelf ID',plant.id||object.name)+showValue('Level',plant.level??'?')+showValue('Category','Decorative crop instances')+showValue('Plant count',plant.plant_count??'-')+showValue('Planting grid',`${plant.columns??'-'} columns / ${plant.rows??'-'} rows`)+showValue('Crop',plant.crop||'Procedural leafy greens')+showValue('Footprint',Number.isFinite(b.x_min)?`${(b.x_max-b.x_min).toFixed(3)} x ${(b.y_max-b.y_min).toFixed(3)} m`:'Instanced shelf bed')+showValue('Approx. plant height',plantHeight?`${plantHeight.toFixed(2)} m`:'Procedural')+showValue('RF enabled','No / visual-only geometry');
  } else if(object.kind==='transmitter') {
    const tx=object.detail;type='TRANSMITTER';title=tx.name||'TX';subtitle=`${tx.position_m.map(v=>Number(v).toFixed(3)).join(', ')} m`;
    body=showValue('Position',`${tx.position_m.map(v=>Number(v).toFixed(6)).join(', ')} m`)+showValue('Frequency',`${(scenario.frequency_hz/1e9).toFixed(3)} GHz`)+showValue('Power',tx.power_dbm==null?'Not recorded':`${tx.power_dbm} dBm`)+showValue('Orientation',`${(tx.orientation_rad||[]).map(v=>Number(v).toFixed(4)).join(', ')} rad`)+showValue('RF status',imported?'Saved HOUSIONNA transmitter':'Simulation transmitter');
    if(!imported)body+=showValue('Array',`${scenario.antenna.rows} x ${scenario.antenna.columns} / ${scenario.antenna.pattern}`)+showValue('Polarization',scenario.antenna.polarization);
  } else if(object.kind==='receiver') {
    const rx=object.detail;selectedReceiverMetric=receiverMetric(scenario,rx.name);activeReceiver=rx.name;$('#receiverSelect').value=rx.name;refreshReceiverMetrics(scenario);
    type='RECEIVER';title=rx.name;subtitle=rx.role||'Exported receiver';
    body=showValue('Position',`${rx.position_m.map(v=>Number(v).toFixed(6)).join(', ')} m`)+showValue('Orientation',`${(rx.orientation_rad||[]).map(v=>Number(v).toFixed(4)).join(', ')} rad`)+showValue('Scenario',scenario.label)+showValue('Paths',selectedReceiverMetric?.path_count??'-')+showValue('LOS',selectedReceiverMetric?.los_present?'Yes':'No')+showValue('Strongest path coefficient',formatDb(selectedReceiverMetric?.strongest_path_db))+showValue('Strongest delay',selectedReceiverMetric?.strongest_path_delay_ns==null?'-':`${Number(selectedReceiverMetric.strongest_path_delay_ns).toFixed(3)} ns`)+showValue('Aggregate path coefficient power',`${formatDb(selectedReceiverMetric?.aggregate_path_coefficient_power_db)} / not RSS`)+showValue('Refraction paths',selectedReceiverMetric?.interaction_path_counts?.refraction??0)+showValue('CIR',`${scenario.paths.filter(p=>p.receiver===rx.name).length} exported Sionna paths`);
  } else if(object.kind==='path') {
    const path=object.path,angles=path.source_angles_rad||{};type='SIONNA PATH';title=`${path.receiver} / path ${path.path_index}`;subtitle=path.interaction_types?.length?path.interaction_types.join(' / '):'LOS';
    body=showValue('TX / RX',`${scenario.transmitter.name} / ${path.receiver}`)+showValue('Complex coefficient',`${Number(path.a_real||0).toExponential(4)} + j${Number(path.a_imag||0).toExponential(4)}`)+showValue('Magnitude',formatDb(pathMagnitude(path)))+showValue('Delay',`${Number(path.delay_ns??path.delay_s*1e9).toFixed(4)} ns`)+showValue('Path length',`${Number(path.path_length_m_from_delay??path.delay_s*299792458).toFixed(3)} m`)+showValue('Interaction types',path.interaction_types?.join(', ')||'None / LOS')+showValue('Interaction IDs',path.interaction_type_ids?.join(', ')||'None')+showValue('Objects',path.interacted_objects?.join(', ')||'None')+showValue('Primitive IDs',path.interacted_primitives?.join(', ')||'None')+showValue('Interaction vertices',path.interaction_vertices_m?.length||0)+showValue('TX angles theta/phi',`${angles.theta_t??'-'} / ${angles.phi_t??'-'} rad`)+showValue('RX angles theta/phi',`${angles.theta_r??'-'} / ${angles.phi_r??'-'} rad`)+showValue('Doppler',path.doppler_hz==null?'Not recorded':`${path.doppler_hz} Hz`);
    pulseCurve=pathCurves.find(entry=>entry.path===path)?.curve||pulseCurve;
  } else if(object.kind==='radio-map') {
    type='RF MAP';title=object.name;subtitle=object.detail.units;
    body=showValue('Scenario',scenario.label)+showValue('Values','Saved Sionna radio-map output')+showValue('Display','Exported values mapped to their source geometry');
  } else if(object.kind==='measurement-mesh') {
    type='MEASUREMENT MESH';title=object.detail.surface;subtitle=`${Number(object.detail.triangle_count).toLocaleString()} source triangles`;
    body=showValue('Surface',object.detail.surface)+showValue('Triangles',object.detail.triangle_count)+showValue('Units',object.detail.units)+showValue('Coordinates','Source XYZ metres / no viewer translation');
  }
  if(object.kind==='scene'&&scenario.provenance)body+=showValue('Source',scenario.provenance.pipeline)+showValue('Source Sionna RT',scenario.provenance.source_sionna_rt||'unknown');
  if(object.kind==='receiver'&&selectedReceiverMetric?.link_metrics)body+=showValue('Coherent link gain',formatDb(selectedReceiverMetric.link_metrics.gain_db_coherent))+showValue('Incoherent link gain',formatDb(selectedReceiverMetric.link_metrics.gain_db_incoherent))+showValue('Delay spread',selectedReceiverMetric.link_metrics.delay_spread_ns==null?'\u2014':`${Number(selectedReceiverMetric.link_metrics.delay_spread_ns).toFixed(3)} ns`)+showValue('CFR samples',selectedReceiverMetric.link_metrics.cfr_db?.length||0);
  if(object.kind==='radio-map'&&object.detail.surface)body=showValue('Measurement surface',object.detail.surface)+showValue('Valid triangles',object.detail.cell_count||0)+showValue('Scenario',scenario.label)+showValue('Values','Saved HOUSIONNA/Sionna path gain')+showValue('Display','One color per source triangle; missing cells are omitted');
  $('#detailTitle').textContent=title;$('#detailType').textContent=type;$('#detailSubtitle').textContent=subtitle;$('#detailBody').innerHTML=body;
  refreshPaths();
}

function visualMaterial(category,item=null,scenario=null) {
  if(scenario?.source_type==='housionna') {
    const mode=$('#housionnaGeometryMode').value;
    if(mode==='wireframe')return 'Triangle wireframe / viewer only';
    if(mode==='transparent')return 'Neutral translucent surface / viewer only';
    if(mode==='object-colors')return `Object color ${objectColorFor(item,0)} / viewer only`;
    if(String(item?.metadata?.itu_type||'').toLowerCase().includes('concrete'))return 'Matte neutral concrete / viewer only';
    return 'Neutral RF-category color / viewer only';
  }
  return ({floor:'Matte floor surface',greenhouse_shell:'Low-iron greenhouse glazing',enclosure_panel:'Frosted enclosure panel',metal_structure:'Powder-coated rack steel',shelf_tray:'Grow-tray surface',grow_light:'LED grow-light diffuser',equipment:'Equipment enclosure',vegetation:'Procedural leafy crop',rf_plant_zone:'Transparent RF-only canopy proxy'})[category]||'PBR scene material';
}

function focusScene(mode) {
  const scenario=data.scenarios[activeScenario];
  const d=sceneSize(scenario),sceneScale=Math.max(d.width,d.depth,d.height,1);
  let centerPoint=sceneCenter(scenario),scale=sceneScale,offset;
  camera.up.set(0,0,1);
  if(mode==='selected-object') {
    const object=selectedObject;
    if(object?.object?.bounds_m) {
      const bounds=object.object.bounds_m;
      centerPoint.set((bounds.x_min+bounds.x_max)/2,(bounds.y_min+bounds.y_max)/2,(bounds.z_min+bounds.z_max)/2);
      scale=Math.max(...dimensions(bounds),0.8);
    } else if(object?.kind==='transmitter'||object?.kind==='receiver') {
      centerPoint.copy(vec(object.detail.position_m));scale=1.6;
    } else if(object?.kind==='path') {
      const points=[scenario.transmitter.position_m,...(object.path.interaction_vertices_m||[]),scenario.receivers.find(row=>row.name===object.path.receiver)?.position_m].filter(Boolean).map(vec);
      if(points.length)centerPoint.copy(points.reduce((sum,row)=>sum.add(row),new THREE.Vector3()).multiplyScalar(1/points.length));
      scale=Math.max(2,sceneScale*0.45);
    }
    offset=new THREE.Vector3(scale*0.95,-scale*1.45,scale*0.85);
  } else if(mode==='selected-tx'||mode==='tx') {
    centerPoint.copy(vec(scenario.transmitter.position_m));scale=Math.max(2,sceneScale*0.42);
    offset=new THREE.Vector3(0,-scale*1.45,scale*0.85);
  } else if(mode==='selected-rx') {
    const rx=scenario.receivers.find(item=>item.name===activeReceiver)||scenario.receivers[0];
    if(rx)centerPoint.copy(vec(rx.position_m));scale=Math.max(2,sceneScale*0.42);
    offset=new THREE.Vector3(scale*0.75,-scale*1.25,scale*0.85);
  } else if(mode==='top'){offset=new THREE.Vector3(0.01,0.01,sceneScale*1.9);camera.up.set(0,1,0);}
  else if(mode==='front')offset=new THREE.Vector3(0,-sceneScale*1.9,sceneScale*0.10);
  else if(mode==='side')offset=new THREE.Vector3(sceneScale*1.95,0,sceneScale*0.12);
  else if(mode==='shelf') {
    const levels=scenario.environment?.shelf_levels_m||[];
    const z=levels.length?Number(levels[Math.floor(levels.length/2)]):d.height*0.5;
    centerPoint.set(d.width/2,scenario.environment?.depth_m*0.55||d.depth*0.55,z+0.16);
    offset=new THREE.Vector3(0,-sceneScale*0.95,sceneScale*0.26);
  } else if(mode.startsWith('RX_')) {
    const rx=scenario.receivers.find(item=>item.name.toLowerCase()===mode.toLowerCase());
    if(rx)centerPoint.copy(vec(rx.position_m));
    offset=new THREE.Vector3(sceneScale*0.50,-sceneScale*0.76,sceneScale*0.30);
  } else if(mode==='isometric')offset=new THREE.Vector3(sceneScale*1.05,-sceneScale*1.8,sceneScale*1.1);
  else offset=new THREE.Vector3(sceneScale*1.25,-sceneScale*1.9,sceneScale*1.25);
  controls.minDistance=Math.max(0.35,scale*0.14);controls.maxDistance=Math.max(120,sceneScale*10);
  controls.target.copy(centerPoint);camera.position.copy(centerPoint).add(offset);camera.lookAt(centerPoint);controls.update();
}

function onPointerMove(event) {
  if(draggingTx&&event.pointerId===draggingTx.pointerId) {
    const rect=renderer.domElement.getBoundingClientRect();pointer.set(((event.clientX-rect.left)/rect.width)*2-1,-((event.clientY-rect.top)/rect.height)*2+1);
    raycaster.setFromCamera(pointer,camera);
    const plane=new THREE.Plane(new THREE.Vector3(0,0,1),-draggingTx.z);
    const point=raycaster.ray.intersectPlane(plane,new THREE.Vector3());
    if(point) {
      const bounds=txBounds(data.scenarios[activeScenario]);
      point.x=THREE.MathUtils.clamp(point.x,bounds.x[0],bounds.x[1]);
      point.y=THREE.MathUtils.clamp(point.y,bounds.y[0],bounds.y[1]);
      txGroup.position.x=point.x;txGroup.position.y=point.y;
      setTransmitterPositionFields(txGroup.position.toArray());
      updateTransmitterData();updateTxWarning();markResultsStale();
    }
    viewport.style.cursor='grabbing';event.preventDefault();return;
  }
  const rect=renderer.domElement.getBoundingClientRect(); pointer.set(((event.clientX-rect.left)/rect.width)*2-1,-((event.clientY-rect.top)/rect.height)*2+1);
  raycaster.setFromCamera(pointer,camera);
  const objects=[]; rootGroup.traverse((child)=>{ if((child.isMesh||child.isLine)&&isVisibleInScene(child)&&child.userData.kind) objects.push(child); });
  const hit=raycaster.intersectObjects(objects,false)[0];
  viewport.style.cursor=hit?'pointer':'grab';
  if(hoverMesh && hoverMesh!==hit?.object) { setHover(hoverMesh,false); hoverMesh=null; }
  if(hit && hit.object!==hoverMesh) { hoverMesh=hit.object; setHover(hoverMesh,true); }
}
function setHover(object,on) {
  const target=object.userData.pickParent||object;
  if(target.isLine&&target.material) { target.material.opacity=on?1:0.82; target.material.color.set(on?'#fff4bd':target.userData.hoverColor||'#73818a'); }
  else if(target.material?.emissive) { target.material.emissive.set(on?'#bcd9b4':target.material.userData.baseEmissive||'#000000'); target.material.emissiveIntensity=on?0.18:(target.material.userData.baseEmissive?0.08:0); }
}
function onPointerDown(event) {
  if(event.button!==0||event.target!==renderer.domElement) return;
  const rect=renderer.domElement.getBoundingClientRect(); pointer.set(((event.clientX-rect.left)/rect.width)*2-1,-((event.clientY-rect.top)/rect.height)*2+1);
  raycaster.setFromCamera(pointer,camera);
  const objects=[]; rootGroup.traverse((child)=>{ if((child.isMesh||child.isLine)&&isVisibleInScene(child)&&child.userData.kind) objects.push(child); });
  const hit=raycaster.intersectObjects(objects,false)[0]; if(!hit) return;
  const object=hit.object.userData.pickParent||hit.object;
  if(object.userData.kind==='transmitter'&&
     !STATIC_SITE&&(activeScenario.startsWith('farm_')||data.scenarios[activeScenario]?.source_type==='housionna')&&
     (!object.userData.scenarioKey||object.userData.scenarioKey===activeScenario)&&!simulationRunning) {
    event.preventDefault();event.stopPropagation();
    selectObject(txGroup.userData);
    draggingTx={pointerId:event.pointerId,z:txGroup.position.z,moved:false};
    controls.enabled=false;renderer.domElement.setPointerCapture?.(event.pointerId);viewport.style.cursor='grabbing';
    return;
  }
  if(object.userData.kind==='transmitter'&&object.userData.scenarioKey&&object.userData.scenarioKey!==activeScenario) {
    const next=data.scenarios[object.userData.scenarioKey];
    if(next?.source_type==='housionna') {
      activeScenario=object.userData.scenarioKey;rfResultsStale=false;
      $('#housionnaRunSelect').value=next.import_id;$('#housionnaTxSelect').value=activeScenario;
      buildScenario({preserveView:true});syncSimulationControls(next);renderHousionnaMetadata(next);
      const selected=objectMeshes.get(next.transmitter.name);
      if(selected)selectObject(selected.userData);
      return;
    }
  }
  if(object.userData.kind==='path') { pulseCurve=pathCurves.find((entry)=>entry.line===object)?.curve||pulseCurve; }
  selectObject(object.userData);
}

function onPointerUp(event) {
  if(!draggingTx||event.pointerId!==draggingTx.pointerId)return;
  try{renderer.domElement.releasePointerCapture?.(event.pointerId);}catch{}
  draggingTx=null;controls.enabled=true;viewport.style.cursor='grab';
  if(txGroup){setTransmitterPositionFields(txGroup.position.toArray());updateTransmitterData();updateTxWarning();markResultsStale();selectObject(txGroup.userData);}
}

function txBounds(scenario) {
  if(scenario?.source_type==='housionna') {
    const bounds=scenario.geometry?.bounds_m||scenario.scene_bounds_m||{};
    return Object.fromEntries(['x','y','z'].map(axis=>{
      const low=Number(bounds[`${axis}_min`]||0),high=Number(bounds[`${axis}_max`]||0);
      const margin=Math.max(1,(high-low)*0.25);
      return [axis,[low-margin,high+margin]];
    }));
  }
  const env=scenario.environment||{},width=Number(env.width_m||sceneSize(scenario).width),depth=Number(env.depth_m||sceneSize(scenario).depth),height=Number(env.height_m||sceneSize(scenario).height);
  return {x:[-0.20,width+0.20],y:[-0.55,depth+0.10],z:[0.05,height]};
}

function setTransmitterPositionFields(position) {
  ['txX','txY','txZ'].forEach((id,index)=>{$(`#${id}`).value=Number(position[index]).toFixed(3);});
}

function updateTransmitterData() {
  if(!txGroup||!data.scenarios[activeScenario])return;
  const tx=data.scenarios[activeScenario].transmitter;
  tx.position_m=txGroup.position.toArray().map(Number);
  tx.orientation_rad[0]=Number($('#txYaw').value)*Math.PI/180;
  txGroup.userData.detail=tx;
  if(selectedObject?.kind==='transmitter')selectObject(txGroup.userData);
}

function updateTransmitterFromFields() {
  const scenario=data?.scenarios?.[activeScenario];
  const imported=scenario?.source_type==='housionna';
  if(!txGroup||(!imported&&!['farm_empty','farm_proxy','farm_dense'].includes(activeScenario)))return;
  const position=[$('#txX').value,$('#txY').value,$('#txZ').value].map(Number);
  if(position.some(value=>!Number.isFinite(value)))return;
  const bounds=txBounds(imported?scenario:data.scenarios[$('#simulationScenario').value]);
  if(position[0]<bounds.x[0]||position[0]>bounds.x[1]||position[1]<bounds.y[0]||position[1]>bounds.y[1]||position[2]<bounds.z[0]||position[2]>bounds.z[1])return;
  txGroup.position.set(...position);updateTransmitterData();
  txGroup.rotation.z=Number($('#txYaw').value)*Math.PI/180;
}

function isVisibleInScene(object) {
  for (let item = object; item && item !== rootGroup.parent; item = item.parent) {
    if (!item.visible) return false;
  }
  return true;
}

function resizeRenderer() {
  if(!renderer||!viewport.clientWidth||!viewport.clientHeight) return;
  const w=viewport.clientWidth,h=viewport.clientHeight;
  camera.aspect=w/h; camera.updateProjectionMatrix(); renderer.setSize(w,h,false); labelRenderer.setSize(w,h);
}

function renderFrame(time) {
  if(controls?.update())frameDirty=true;
  if(!frameDirty&&!pulseRunning)return;
  if(pulseRunning && pulseCurve && pulseMesh) {
    const t=((time-pulseStarted)%2600)/2600;
    pulseMesh.position.copy(pulseCurve.getPointAt(t));
  }
  renderer?.render(scene,camera); labelRenderer?.render(scene,camera);
  frameDirty=false;
}

function addPulseMesh() {
  if(pulseMesh) { scene.remove(pulseMesh); pulseMesh.geometry.dispose(); pulseMesh.material.dispose(); }
  pulseMesh=new THREE.Mesh(new THREE.SphereGeometry(0.065,16,12),new THREE.MeshBasicMaterial({color:'#fff2ba'}));
  pulseMesh.visible=false; scene.add(pulseMesh);
}

function captureView() {
  renderer.render(scene,camera);
  const link=document.createElement('a'); link.download=`greenhouse-${activeScenario}-${Date.now()}.png`;
  link.href=renderer.domElement.toDataURL('image/png'); link.click();
}

function showError(error) {
  $('#scenarioHeading').textContent='Viewer initialization failed';
  const details = [];
  if (error.resource) details.push(`<span><b>Failed resource:</b> ${esc(error.resource)}</span>`);
  if (error.status) details.push(`<span><b>HTTP status:</b> ${esc(error.status)}</span>`);
  details.push(`<span><b>JavaScript error:</b> ${esc(error.message||error)}</span>`);
  $('#sceneLoading').innerHTML=`<b>3D viewer failed to initialize</b>${details.join('')}`;
  $('#sceneLoading').classList.add('error');
}

function collectSimulationSettings() {
  const scenario=$('#simulationScenario').value;
  const active=data?.scenarios?.[activeScenario];
  const activeOrientation=active?.transmitter?.orientation_rad||[0,0,0];
  return {
    scenario,
    frequency_hz:Number($('#frequencyGHz').value)*1e9,
    tx:{position_m:[$('#txX').value,$('#txY').value,$('#txZ').value].map(Number),orientation_rad:orientationWithYaw(activeOrientation,$('#txYaw').value)},
    receiver_set:'default',
    solver:{max_depth:Number($('#solverDepth').value),specular_reflection:$('#specularToggle').checked,refraction:$('#refractionToggle').checked},
    map_quality:$('#mapQuality').value,
  };
}

function normalizedSettings(settings) {
  return {
    scenario:settings.scenario,
    frequency_hz:Number.isFinite(settings.frequency_hz)?Math.round(settings.frequency_hz):null,
    tx:{position_m:settings.tx.position_m.map(value=>Number.isFinite(value)?Number(value.toFixed(6)):null),orientation_rad:settings.tx.orientation_rad.map(value=>Number.isFinite(value)?Number(value.toFixed(8)):null)},
    receiver_set:settings.receiver_set,
    solver:{max_depth:settings.solver.max_depth,specular_reflection:settings.solver.specular_reflection,refraction:settings.solver.refraction},
    map_quality:settings.map_quality,
  };
}

function settingsFingerprint(settings=collectSimulationSettings()) { return JSON.stringify(normalizedSettings(settings)); }

function syncHousionnaControls(scenario) {
  ensureHousionnaOriginal(scenario);
  const key=scenario.name,latest=housionnaLatestResults.get(key),version=housionnaDisplayedVersions.get(key)||'original';
  $('#builtinScenarioRow').classList.add('hidden');
  $('#housionnaSimulationContext').classList.remove('hidden');
  $('#housionnaSimulationContext').textContent=`Source ${scenario.provenance?.run_folder_name||scenario.run_metadata?.run_id} · original exported XML/PLY materials · XYZ metres, Z up`;
  $('#housionnaReceiverControls').classList.remove('hidden');
  $('#housionnaTxActions').classList.remove('hidden');
  $('#runRadioMapBtn').classList.remove('hidden');
  $('#simulationPanelTitle').textContent='SIONNA RT SIMULATION';
  populateHousionnaReceiverSelection(scenario);
  $('#frequencyGHz').value=(Number(scenario.frequency_hz)/1e9).toFixed(3).replace(/0+$/,'').replace(/\.$/,'');
  const tx=scenario.transmitter;
  setTransmitterPositionFields(tx.position_m);
  $('#txYaw').value=(Number(tx.orientation_rad?.[0]||0)*180/Math.PI).toFixed(1);
  const solver=scenario.solver?.path_solver||{};
  $('#solverDepth').value=String(solver.max_depth||3);
  $('#losToggle').checked=solver.los??true;
  $('#specularToggle').checked=solver.specular_reflection??true;
  $('#diffuseToggle').checked=solver.diffuse_reflection??false;
  $('#refractionToggle').checked=solver.refraction??true;
  $('#diffractionToggle').checked=solver.diffraction??false;
  $('#pathSamples').value=String(solver.samples_per_source||1_000_000);
  const mapQuality=housionnaMapQualities.get(key)||scenario.radio_map?.metadata?.quality||'low';
  $('#mapQuality').value=mapQuality;
  $('#mapQuality').querySelector('option[value="low"]').textContent='Low · 100k samples/TX';
  $('#mapQuality').querySelector('option[value="medium"]').textContent='Medium · 500k samples/TX';
  $('#mapQuality').querySelector('option[value="high"]').textContent='High · 2M samples/TX';
  const limits=txBounds(scenario);
  [['txX',limits.x],['txY',limits.y],['txZ',limits.z]].forEach(([id,range])=>{const input=$(`#${id}`);input.min=String(range[0]);input.max=String(range[1]);});
  const latestOption=$('#housionnaResultVersion').querySelector('option[value="latest"]');
  latestOption.disabled=!latest;
  if(!latest&&version==='latest')housionnaDisplayedVersions.set(key,'original');
  $('#housionnaResultVersion').value=latest&&housionnaDisplayedVersions.get(key)==='latest'?'latest':'original';
  $('#resetHousionnaTx').disabled=!housionnaOriginalResults.has(key);
  const completed=housionnaCompletedFingerprints.get(key);
  if(!completed)housionnaCompletedFingerprints.set(key,housionnaSettingsFingerprint());
  rfResultsStale=housionnaSettingsFingerprint()!==housionnaCompletedFingerprints.get(key);
  setRunStatus(rfResultsStale?'stale':'current',rfResultsStale
    ?'RF RESULTS OUT OF DATE — RERUN REQUIRED'
    :latest&&housionnaDisplayedVersions.get(key)==='latest'
      ?'Saved Sionna results are selected. The map legend shows its calculation inputs; paths and RX metrics retain their own inputs.'
      :'Original HOUSIONNA propagation results are selected.');
  $('#simulationReadOnlyNote').textContent='Change TX pose, frequency, selected receivers, sample count, or solver settings and run Sionna against this exported scene. Geometry and materials stay fixed.';
  if(!latest){
    $('#simulationRuntime').textContent='Original HOUSIONNA export';
    $('#housionnaLiveComparison').textContent='No Sionna rerun selected for this transmitter.';
    $('#simulationDiagnosticsData').textContent=JSON.stringify({source_run_id:scenario.provenance?.run_folder_name,transmitter:scenario.transmitter.name,result:'original HOUSIONNA export'},null,2);
  }
  updateTxWarning();
  setSimulationInputsDisabled(false);
}

function syncSimulationControls(scenario) {
  if(!scenario)return;
  if(scenario.source_type==='housionna') {
    syncHousionnaControls(scenario);
    return;
  }
  $('#builtinScenarioRow').classList.remove('hidden');
  $('#housionnaSimulationContext').classList.add('hidden');
  $('#housionnaReceiverControls').classList.add('hidden');
  $('#housionnaTxActions').classList.add('hidden');
  $('#runRadioMapBtn').classList.add('hidden');
  $('#simulationPanelTitle').textContent='ON-DEMAND SIONNA RT';
  $('#mapQuality').querySelector('option[value="low"]').textContent='Low · 0.30 m';
  $('#mapQuality').querySelector('option[value="medium"]').textContent='Medium · 0.15 m';
  $('#mapQuality').querySelector('option[value="high"]').textContent='High · 0.10 m, slower';
  const farmScenarios=['farm_empty','farm_proxy','farm_dense'];
  const saved=scenario.live_configuration||{};
  const chosen=farmScenarios.includes(scenario.name)?scenario.name:(farmScenarios.includes(saved.scenario)?saved.scenario:'farm_proxy');
  const settingsSource=farmScenarios.includes(scenario.name)?scenario:(data.scenarios[chosen]||scenario);
  $('#simulationScenario').value=chosen;
  $('#frequencyGHz').value=(Number(saved.frequency_hz||settingsSource.frequency_hz||2.4e9)/1e9).toFixed(3).replace(/0+$/,'').replace(/\.$/,'');
  const position=saved.tx?.position_m||settingsSource.transmitter?.position_m||[0.625,-0.28,1.08];
  setTransmitterPositionFields(position);
  const orientation=saved.tx?.orientation_rad||settingsSource.transmitter?.orientation_rad||[0,0,0];
  $('#txYaw').value=(Number(orientation[0]||0)*180/Math.PI).toFixed(1);
  const solver=saved.solver||settingsSource.solver?.path_solver||{};
  $('#solverDepth').value=String(solver.max_depth||3);
  $('#losToggle').checked=solver.los??true;
  $('#specularToggle').checked=solver.specular_reflection??true;
  $('#diffuseToggle').checked=solver.diffuse_reflection??false;
  $('#refractionToggle').checked=solver.refraction??true;
  $('#diffractionToggle').checked=solver.diffraction??false;
  const map= saved.map_quality||((settingsSource.solver?.radio_map_solver?.cell_size_m?.[0]||0.15)<=0.11?'high':'medium');
  $('#mapQuality').value=map;
  const limits=txBounds(settingsSource);
  [['txX',limits.x],['txY',limits.y],['txZ',limits.z]].forEach(([id,range])=>{const input=$(`#${id}`);input.min=String(range[0]);input.max=String(range[1]);});
  lastRunFingerprint=settingsFingerprint();
  displayedScenarioSupported=farmScenarios.includes(scenario.name)&&chosen===scenario.name;
  const importedResult=scenario.source_type==='housionna';
  rfResultsStale=!displayedScenarioSupported;
  setRunStatus(rfResultsStale?'stale':'current',rfResultsStale?'The displayed scene differs from the editable vertical-farm RF scenario.':'RF results match the displayed settings.');
  if(rfResultsStale)refreshPaths();
  updateTxWarning();
  setSimulationInputsDisabled(false);
  $('#simulationReadOnlyNote').textContent=importedResult
    ?'This scene contains saved HOUSIONNA results. On-demand runs are available after switching to a built-in demo.'
    :'Editable RF controls apply to the built-in vertical-farm simulation only.';
  if(saved.run_id) {
    $('#simulationRuntime').textContent=`Last run ${Number(saved.duration_seconds||0).toFixed(1)} s`;
  } else if(scenario.run_metadata?.run_id) {
    $('#simulationRuntime').textContent=`Last run ${scenario.run_metadata.run_id.slice(0,8)}`;
  }
}

function setRunStatus(state,message) {
  const badge=$('#rfRunStatus');badge.className=`status-pill ${state}`;badge.textContent=state.toUpperCase();
  $('#simulationMessage').textContent=message;
}

function setSimulationInputsDisabled(disabled) {
  const imported=data?.scenarios?.[activeScenario]?.source_type==='housionna';
  const readOnly=!imported&&$('#sceneSourceSelect')?.value==='housionna';
  const locked=disabled||readOnly;
  ['simulationScenario','frequencyGHz','frequencyPreset','txX','txY','txZ','txYaw','solverDepth','losToggle','specularToggle','diffuseToggle','refractionToggle','diffractionToggle','mapQuality','pathSamples','housionnaReceiverSelection'].forEach(id=>{$(`#${id}`).disabled=locked||(id==='simulationScenario'&&imported);});
  $('#runSimulationBtn').disabled=locked||backendInfo?.available===false;
  $('#runSimulationBtn').textContent=disabled?'SIONNA RUNNING':readOnly?'SAVED RF - READ ONLY':imported?'RUN SIONNA RT':'RUN SIONNA';
  $('#runRadioMapBtn').disabled=locked||!imported||backendInfo?.available===false;
  ['sceneSourceSelect','housionnaRunSelect','housionnaTxSelect','scenarioSelect'].forEach(id=>{$(`#${id}`).disabled=disabled;});
  $('#housionnaResultVersion').disabled=disabled||!imported;
  $('#resetHousionnaTx').disabled=disabled||!imported;
}

function rememberLatest(scenario,snapshot){
  housionnaLatestResults.delete(scenario.name);housionnaLatestResults.set(scenario.name,snapshot);
  for(const key of housionnaLatestResults.keys()){
    if(housionnaLatestResults.size<=12)break;
    if(key===activeScenario||housionnaRestoreJobs.has(key))continue;
    const old=housionnaOriginalResults.get(key),row=data.scenarios[key];
    if(old&&row)applyHousionnaSnapshot(row,old);
    housionnaLatestResults.delete(key);housionnaDisplayedVersions.delete(key);housionnaCompletedFingerprints.delete(key);housionnaRestoredReceivers.delete(key);
  }
}

function markResultsStale() {
  if(simulationRunning)return;
  const scenario=data?.scenarios?.[activeScenario];
  if(scenario?.source_type==='housionna') {
    const expected=housionnaCompletedFingerprints.get(activeScenario);
    const stale=Boolean(expected&&housionnaSettingsFingerprint()!==expected);
    if(stale!==rfResultsStale){rfResultsStale=stale;refreshPaths();}
    setSimulationInputsDisabled(false);
    if(stale)setRunStatus('stale','RF RESULTS OUT OF DATE — RERUN REQUIRED. Existing paths are hidden; the displayed radio map is from the selected saved result.');
    else setRunStatus('current','RF inputs match the selected saved result.');
    return;
  }
  const stale=settingsFingerprint()!==lastRunFingerprint||!displayedScenarioSupported;
  if(stale!==rfResultsStale) {
    rfResultsStale=stale;
    refreshPaths();
  }
  if(stale)setRunStatus('stale','RF results are out of date. The map and metrics are from the last run; old paths are hidden.');
  else setRunStatus('current','RF results match the displayed settings.');
}

function updateTxWarning() {
  const warning=$('#txWarning');
  const current=data?.scenarios?.[activeScenario];
  const displayed=current?.source_type==='housionna'?current:data?.scenarios?.[$('#simulationScenario').value];
  if(!displayed||!displayed.geometry?.objects) {warning.classList.add('hidden');return;}
  const pos=[$('#txX').value,$('#txY').value,$('#txZ').value].map(Number);
  const source=displayed.source_type==='housionna'?displayed:(data.scenarios[$('#simulationScenario').value]||displayed),limits=txBounds(source),axes=['X','Y','Z'];
  const outside=pos.findIndex((value,index)=>!Number.isFinite(value)||value<limits[['x','y','z'][index]][0]||value>limits[['x','y','z'][index]][1]);
  if(outside>=0){warning.textContent=`TX ${axes[outside]} is outside the allowed scene bounds plus margin.`;warning.classList.remove('hidden');return;}
  const floors=displayed.geometry.objects.filter(item=>item.category==='floor'&&pos[0]>=item.bounds_m.x_min&&pos[0]<=item.bounds_m.x_max&&pos[1]>=item.bounds_m.y_min&&pos[1]<=item.bounds_m.y_max);
  if(floors.some(item=>pos[2]<=item.bounds_m.z_max)) {warning.textContent='TX is at or below the exported floor surface. Source placements stay unchanged until you move it.';warning.classList.remove('hidden');return;}
  const collisions=displayed.geometry.objects.filter(item=>item.category!=='floor'&&['x','y','z'].every((axis,index)=>pos[index]>=item.bounds_m[`${axis}_min`]&&pos[index]<=item.bounds_m[`${axis}_max`])).map(item=>item.id);
  if(collisions.length) {warning.textContent=`TX may overlap exported RF object bounds: ${collisions.slice(0,2).join(', ')}${collisions.length>2?'…':''}.`;warning.classList.remove('hidden');}
  else warning.classList.add('hidden');
}

async function apiJson(url,{timeoutMs=20000,...options}={}) {
  const started=performance.now(),controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeoutMs);
  let response;
  let body;
  let headersAt,downloadAt,parseAt;
  try{
    response=await fetch(url,{cache:'no-store',...options,signal:controller.signal});headersAt=performance.now();
    const text=await response.text();downloadAt=performance.now();
    try{body=JSON.parse(text);}catch(error){throw new Error(`Invalid JSON from ${url}: ${error.message}`);}
    parseAt=performance.now();
  }catch(error){error.resource=url;error.status=response?.status;if(error.name==='AbortError')error=new Error(`Request timed out after ${Math.round(timeoutMs/1000)} s: ${url}. The calculation may still be running; refresh to reconnect.`);throw error;}
  finally{clearTimeout(timer);}
  if(!response.ok) {
    const error=new Error(body.error||`HTTP ${response.status} while requesting ${url}`);error.resource=url;error.status=response.status;throw error;
  }
  return {response,body,timing:{headers_ms:headersAt-started,download_ms:downloadAt-headersAt,parse_ms:parseAt-downloadAt,total_ms:parseAt-started}};
}

function formatRuntime(seconds) { return Number.isFinite(Number(seconds))?`${Number(seconds).toFixed(1)} s`:'—'; }

function renderHistory(rows) {
  apiHistory=Array.isArray(rows)?rows:[];
  $('#simulationHistory').innerHTML=apiHistory.length?apiHistory.map(row=>{
    const tx=(row.tx_position_m||[]).map(value=>Number(value).toFixed(2)).join(', ');
    const when=row.timestamp_utc?new Date(row.timestamp_utc).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'}):'Recent';
    return `<button class="history-item" data-run-id="${esc(row.run_id)}" ${row.status==='complete'?'':'disabled'}><span><b>${esc(row.scenario||'Run')}</b><small>${when} · ${(Number(row.frequency_hz||0)/1e9).toFixed(3)} GHz</small></span><span><b>${formatRuntime(row.duration_seconds)}</b><small>TX ${esc(tx)}</small></span></button>`;
  }).join(''):'<span class="muted-copy">No on-demand runs saved yet.</span>';
}

async function loadApiStatus() {
  try {
    const {body}=await apiJson('/api/status');backendInfo=body.backend||null;renderHistory(body.recent_runs||[]);
    $('#backendLabel').textContent=backendInfo?.backend||'Sionna RT';
    const latest=body.recent_runs?.[0];
    if(latest)$('#simulationRuntime').textContent=`Most recent ${formatRuntime(latest.duration_seconds)} · ${latest.run_id.slice(0,8)}`;
    if(!backendInfo?.available) {
      $('#runSimulationBtn').disabled=true;
      setRunStatus('failed',backendInfo?.error||'Sionna backend is unavailable.');
    }
    if(activeScenario)buildScenario({preserveView:true});
  } catch(error) { console.error('Could not load live simulation status',error); }
}

function applyLiveResult(runId,result,cached,duration) {
  const key=result.name;
  data.scenarios[key]=result;
  activeScenario=key;$('#scenarioSelect').value=key;
  displayedScenarioSupported=true;
  $('#differenceToggle').checked=false;
  syncSimulationControls(result);
  rfResultsStale=false;
  buildScenario({preserveView:true});
  lastRunFingerprint=settingsFingerprint();
  const runMeta=result.run_metadata||{};
  $('#simulationRuntime').textContent=`${cached?'Cached':'Completed'} in ${formatRuntime(duration)} · ${runId.slice(0,8)}`;
  const warning=result.tx_geometry_warning||[];
  setRunStatus('complete',cached?'Loaded cached result.':`Simulation finished in ${formatRuntime(duration)}.${warning.length?` TX overlaps ${warning.join(', ')}.`:''}`);
  $('#simulationError').classList.add('hidden');
  if(warning.length){$('#txWarning').textContent=`Sionna TX is inside RF geometry: ${warning.join(', ')}`;$('#txWarning').classList.remove('hidden');}
  renderHistory([{run_id:runId,scenario:key,status:'complete',frequency_hz:result.frequency_hz,tx_position_m:result.transmitter.position_m,duration_seconds:duration,timestamp_utc:runMeta.timestamp_utc},...apiHistory.filter(row=>row.run_id!==runId)].slice(0,10));
}

function collectHousionnaRequest() {
  const scenario=data?.scenarios?.[activeScenario];
  const tx=[$('#txX').value,$('#txY').value,$('#txZ').value].map(Number);
  const orientation=scenario?.transmitter?.orientation_rad||[0,0,0];
  const frequency=Number($('#frequencyGHz').value)*1e9;
  const samples=Number($('#pathSamples').value);
  const receivers=selectedHousionnaReceivers();
  if(!scenario||scenario.source_type!=='housionna')throw new Error('Select an imported HOUSIONNA run and transmitter first.');
  if(!Number.isFinite(frequency)||frequency<100e6||frequency>6e9)throw new Error('Frequency must be between 0.1 and 6 GHz.');
  if(tx.some(value=>!Number.isFinite(value)))throw new Error('TX position must contain finite X, Y and Z values.');
  if(!Number.isInteger(samples)||samples<1||samples>2_000_000)throw new Error('Path samples must be an integer from 1 to 2,000,000.');
  if(receivers.length<1||receivers.length>8)throw new Error('Select between one and eight receivers.');
  return {
    source_run_id:scenario.provenance?.run_folder_name||scenario.run_metadata?.run_id,
    import_id:scenario.import_id,transmitter:scenario.transmitter.name,receiver_ids:receivers,
    frequency_hz:frequency,tx_position:tx,
    tx_orientation:orientationWithYaw(orientation,$('#txYaw').value),
    samples_per_src:samples,seed:42,
    solver:{max_depth:Number($('#solverDepth').value),los:$('#losToggle').checked,
      specular_reflection:$('#specularToggle').checked,diffuse_reflection:$('#diffuseToggle').checked,
      refraction:$('#refractionToggle').checked,diffraction:$('#diffractionToggle').checked},
  };
}

async function pollHousionnaJob(endpoint,jobId,initial={}) {
  let job=initial;const deadline=performance.now()+1000*(Number(initial.timeout_seconds)||600)+30000;
  while(true) {
    if(job.status==='completed'||job.status==='failed')break;
    if(performance.now()>deadline){const error=new Error('Stopped waiting for the worker. Refresh to reconnect or inspect the job diagnostics.');error.jobId=jobId;throw error;}
    await new Promise(resolve=>setTimeout(resolve,300));
    job=(await apiJson(`/api/housionna/simulations/${encodeURIComponent(jobId)}/status`)).body;
    if(job.status==='completed'||job.status==='failed')break;
    const elapsed=Number(job.elapsed_seconds||((performance.now()-simulationStartedAt)/1000));
    setRunStatus('running',`${job.message||'Running Sionna RT'} · elapsed ${elapsed.toFixed(1)} s`);
  }
  const {body:final,timing}=await apiJson(`/api/housionna/simulations/${encodeURIComponent(jobId)}`);
  if(final.status!=='completed'){const error=new Error(final.error||job.error||'Sionna worker failed.');error.jobId=jobId;throw error;}
  final.transfer_timing=timing;final.cache_hit=initial.cache_hit||false;
  return final;
}

function setHousionnaComparison(comparison,metadata) {
  const rows=comparison?.receivers||[];
  const text=rows.map(row=>{
    const oldCount=row.path_count?.original??0,newCount=row.path_count?.rerun??0;
    const oldGain=row.aggregate_channel_gain_db?.coherent?.original,newGain=row.aggregate_channel_gain_db?.coherent?.rerun;
    const delta=oldGain==null||newGain==null?'':` · coherent Δ ${(Number(newGain)-Number(oldGain)).toFixed(3)} dB`;
    return `${row.receiver}: ${oldCount} → ${newCount} paths${delta}`;
  }).join('\n');
  $('#housionnaLiveComparison').textContent=`Latest Sionna run ${metadata?.run_id||''} · ${formatRuntime(metadata?.duration_seconds)}\nCompared with original HOUSIONNA results\n${text||'No receiver comparison was returned.'}`;
}

function applyHousionnaSnapshot(scenario,snapshot) {
  for(const key of ['transmitter','receivers','frequency_hz','paths','links','receiver_metrics','radio_map','solver'])
    scenario[key]=key==='radio_map'?cloneRadioMap(snapshot[key]):structuredClone(snapshot[key]);
}

function installHousionnaPathResult(scenario,job) {
  const original=ensureHousionnaOriginal(scenario);
  const receiverNames=(job.result.receivers||[]).map(row=>row.name);
  const latest={...housionnaSnapshot(scenario),...structuredClone(job.result),
    radio_map:cloneRadioMap(original.radio_map),run_metadata:scenario.run_metadata,
    latest_sionna:{run_id:job.run_id,metadata:job.metadata,comparison:job.comparison},
  };
  rememberLatest(scenario,latest);
  housionnaRestoredReceivers.set(scenario.name,receiverNames);
  housionnaDisplayedVersions.set(scenario.name,'latest');
  applyHousionnaSnapshot(scenario,latest);
  scenario.latest_sionna=latest.latest_sionna;
  if(activeScenario===scenario.name) {
    syncSimulationControls(scenario);
    housionnaCompletedFingerprints.set(scenario.name,housionnaSettingsFingerprint());
    latest.path_fingerprint=housionnaSettingsFingerprint();
    rfResultsStale=false;
    buildScenario({preserveView:true});
    $('#housionnaResultVersion').value='latest';
    setHousionnaComparison(job.comparison,job.metadata);
    const counts=(job.comparison?.receivers||[]).map(row=>`${row.receiver} ${row.path_count.original}→${row.path_count.rerun}`).join(' · ');
    setRunStatus('complete',`Sionna paths restored in ${formatRuntime(job.metadata?.duration_seconds)}${counts?` · ${counts}`:''}. The radio map shows the original export unless a matching rerun map is restored.`);
    $('#simulationRuntime').textContent=`Sionna RT ${formatRuntime(job.metadata?.duration_seconds)} · ${job.run_id.slice(0,8)}`;
    $('#simulationError').classList.add('hidden');
  }
  return latest;
}

async function restoreLatestHousionnaResults(scenarioKey=activeScenario) {
  if(STATIC_SITE)return;  // reruns live on the local server only
  const scenario=data?.scenarios?.[scenarioKey];
  if(scenario?.source_type!=='housionna'||housionnaLatestResults.has(scenarioKey))return;
  if(housionnaRestoreJobs.has(scenarioKey))return housionnaRestoreJobs.get(scenarioKey);
  const restore=(async()=>{
    try {
      const sourceRunId=scenario.provenance?.run_folder_name||scenario.run_metadata?.run_id;
      const query=new URLSearchParams({source_run_id:sourceRunId,import_id:scenario.import_id,transmitter:scenario.transmitter.name});
      const {body:index}=await apiJson(`/api/housionna/simulations/latest?${query}`);
      if(!index.latest_path_run_id&&index.latest_radio_map_run_id){
        const {body:mapJob}=await apiJson(`/api/housionna/simulations/${encodeURIComponent(index.latest_radio_map_run_id)}`);
        if(mapJob.status!=='completed'||!mapJob.radio_map)return;
        if(data?.scenarios?.[scenarioKey]!==scenario||(simulationRunning&&activeScenario===scenarioKey)||housionnaLatestResults.has(scenarioKey))return;
        installHousionnaMapResult(scenario,mapJob);
        if(activeScenario===scenarioKey)setRunStatus(rfResultsStale?'stale':'complete','Saved radio map restored. Paths and RX metrics retain their own calculation settings.');
        return;
      }
      if(!index.latest_path_run_id)return;
      const {body:pathJob}=await apiJson(`/api/housionna/simulations/${encodeURIComponent(index.latest_path_run_id)}`);
      if(pathJob.status!=='completed'||!pathJob.result)return;
      let job={...pathJob,run_id:pathJob.run_id||index.latest_path_run_id};
      let mapJob=null;
      if(index.latest_radio_map_run_id) {
        try {
          const {body}=await apiJson(`/api/housionna/simulations/${encodeURIComponent(index.latest_radio_map_run_id)}`);
          if(body.status==='completed'&&body.radio_map)mapJob=body;
        } catch(error) { console.warn('Saved HOUSIONNA radio map could not be restored',error); }
      }
      if(data?.scenarios?.[scenarioKey]!==scenario||(simulationRunning&&activeScenario===scenarioKey)||housionnaLatestResults.has(scenarioKey))return;
      installHousionnaPathResult(scenario,job);
      if(mapJob) {
        installHousionnaMapResult(scenario,mapJob);
        if(activeScenario===scenarioKey)setRunStatus(rfResultsStale?'stale':'complete',`Saved ${mapJob.radio_map.metadata.quality} map restored; its inputs are shown in the legend.${rfResultsStale?' Paths and RX metrics need a separate rerun.':''}`);
      }
    } catch(error) {
      console.warn('Could not restore a saved HOUSIONNA Sionna result',error);
    } finally {
      housionnaRestoreJobs.delete(scenarioKey);
    }
  })();
  housionnaRestoreJobs.set(scenarioKey,restore);
  return restore;
}

async function runHousionnaSimulation() {
  if(simulationRunning)return;
  let payload;
  try{payload=collectHousionnaRequest();}
  catch(error){showSimulationError(error);setRunStatus('failed','Correct the highlighted RF setting before running.');return;}
  simulationRunning=true;simulationStartedAt=performance.now();setSimulationInputsDisabled(true);$('#simulationError').classList.add('hidden');
  setRunStatus('running','Starting isolated Sionna RT worker… elapsed 0.0 s');
  try {
    const {body}=await apiJson('/api/housionna/simulate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const job=await pollHousionnaJob('paths',body.job_id,body);
    const scenario=data.scenarios[job.result.name];
    if(!scenario)throw new Error('The completed result refers to an imported scene that is no longer loaded.');
    installHousionnaPathResult(scenario,job);
  } catch(error) {
    showSimulationError(error);setRunStatus('failed',`Sionna simulation failed${error.status?` (HTTP ${error.status})`:''}.`);
  } finally {
    simulationRunning=false;setSimulationInputsDisabled(false);if(simulationClock){clearInterval(simulationClock);simulationClock=null;}
  }
}

function installHousionnaMapResult(scenario,job,payload=null) {
  const original=ensureHousionnaOriginal(scenario);
  const latest=housionnaLatestResults.get(scenario.name)||{...housionnaSnapshot(scenario),path_fingerprint:housionnaCompletedFingerprints.get(scenario.name),latest_sionna:{}};
  const surfaces=(job.radio_map?.surfaces||[]).map(surface=>{
    const existing=original.radio_map?.surfaces?.find(row=>row.mesh_ref===surface.mesh_ref&&row.name===surface.name);
    if(!existing?.mesh||surface.values_db?.length!==existing.mesh.faces.length)throw new Error(`Radio-map values do not align with source triangles for ${surface.name}.`);
    return {...surface,mesh:existing.mesh};
  });
  if(!surfaces.length)throw new Error('Sionna returned no measurement-surface data.');
  const metadata=job.radio_map.metadata;
  if(metadata.source_sha256!==scenario.provenance.source_sha256||metadata.import_id!==scenario.import_id||metadata.transmitter!==scenario.transmitter.name)throw new Error('Map provenance does not match the selected source export and TX. Reload the export.');
  const range=finiteRange(surfaces.flatMap(row=>row.values_db));
  latest.radio_map={...original.radio_map,surfaces,quantity:'path_gain',min_db:range.count?range.min:null,max_db:range.count?range.max:null,metadata};
  latest.latest_sionna={...latest.latest_sionna,radio_map_metadata:metadata,radio_map_comparison:job.comparison};
  latest.transmitter={...structuredClone(scenario.transmitter),position_m:[...metadata.tx_position_m],orientation_rad:[...(metadata.tx_orientation_rad||scenario.transmitter.orientation_rad)]};
  latest.frequency_hz=metadata.frequency_hz;
  latest.solver=structuredClone(latest.solver);latest.solver.path_solver={...latest.solver.path_solver,...metadata.solver};
  rememberLatest(scenario,latest);housionnaMapQualities.set(scenario.name,metadata.quality);
  // Paths and link metrics retain their own inputs; a map run does not certify them.
  scenario.radio_map=latest.radio_map;scenario.latest_sionna=latest.latest_sionna;
  scenario.transmitter=structuredClone(latest.transmitter);scenario.frequency_hz=latest.frequency_hz;scenario.solver=structuredClone(latest.solver);
  housionnaDisplayedVersions.set(scenario.name,'latest');
  if(activeScenario===scenario.name){
    $('#housionnaResultVersion').value='latest';
    $('#housionnaResultVersion').querySelector('option[value="latest"]').disabled=false;
    $('[data-layer="map"]').checked=true;
    if(!payload){syncSimulationControls(scenario);buildScenario({preserveView:true});}
    else{updateMap();setLayerVisibility();}
    rfResultsStale=housionnaSettingsFingerprint()!==housionnaCompletedFingerprints.get(scenario.name);
    refreshPaths();
  }
  return latest;
}

async function finishHousionnaMap(job,scenario,payload,timings={}){
  setRunStatus('running','Updating visualization');
  const updateAt=performance.now();installHousionnaMapResult(scenario,job,payload);
  timings.visualization_update_ms=performance.now()-updateAt;
  await new Promise(resolve=>{
    // Background tabs may suspend animation frames. Always restore the controls.
    const timer=setTimeout(resolve,250);
    requestAnimationFrame(()=>{frameDirty=true;requestAnimationFrame(()=>{clearTimeout(timer);resolve();});});
  });
  timings.total_click_to_visible_ms=performance.now()-simulationStartedAt;
  Object.assign(timings,{result_download_ms:job.transfer_timing?.download_ms||0,result_parse_ms:job.transfer_timing?.parse_ms||0,result_headers_ms:job.transfer_timing?.headers_ms||0});
  const metadata=job.radio_map.metadata,total=formatRuntime(timings.total_click_to_visible_ms/1000),solver=formatRuntime(metadata.solver_seconds);
  setRunStatus(rfResultsStale?'stale':'complete',`${job.cache_hit?'Loaded cached simulation':'Radio map complete'} · total ${total} · solver ${solver} · ${metadata.quality} ${Number(metadata.samples_per_tx).toLocaleString()} samples/TX${rfResultsStale?' · Paths and RX metrics require a separate rerun.':''}`);
  const valid=Number(metadata.valid_triangle_count??finiteRange(job.radio_map.surfaces.flatMap(s=>s.values_db)).count),cells=Number(metadata.measurement_triangle_count);
  const backend=metadata.software?.variant?.startsWith('cuda')?'CUDA GPU':'LLVM CPU';
  $('#simulationRuntime').textContent=`TX ${metadata.transmitter} · ${backend} · ${valid.toLocaleString()} / ${cells.toLocaleString()} valid triangles · ${cells?((1-valid/cells)*100).toFixed(1):'0.0'}% missing · depth ${metadata.solver.max_depth} · ${(metadata.frequency_hz/1e9).toFixed(3)} GHz`;
  const comparison=job.comparison;
  $('#housionnaLiveComparison').textContent=comparison?.compatible?`Rerun − original: ${Number(comparison.valid_cells).toLocaleString()} jointly valid triangles · mean |Δ| ${Number(comparison.mean_absolute_delta_db).toFixed(3)} dB · RMS ${Number(comparison.rms_delta_db).toFixed(3)} dB. Sampling agreement does not validate the physical model.`:`Map comparison unavailable: ${comparison?.reason||'Compatibility was not established.'}`;
  $('#simulationDiagnosticsData').textContent=JSON.stringify({job_id:job.job_id,cache_hit:job.cache_hit,backend:metadata.software,client_ms:timings,worker_profile:metadata.profile,execution:metadata.execution},null,2);
  void apiJson('/api/housionna/client-timing',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({run_id:job.job_id,timings_ms:timings})}).catch(error=>console.warn('Could not save browser timings',error));
}

async function runHousionnaRadioMap() {
  if(simulationRunning)return;
  const clickedAt=performance.now(),scenario=data.scenarios[activeScenario];
  let payload;
  try{payload=collectHousionnaRequest();payload.quality=$('#mapQuality').value;}
  catch(error){showSimulationError(error);setRunStatus('failed','Correct the RF settings before running.');return;}
  const timings={request_preparation_ms:performance.now()-clickedAt};
  simulationRunning=true;simulationStartedAt=clickedAt;setSimulationInputsDisabled(true);$('#simulationError').classList.add('hidden');
  setRunStatus('running','Preparing simulation');
  $('#simulationDiagnosticsData').textContent=JSON.stringify({status:'preparing',message:'Preparing the current radio-map request.'},null,2);
  try{
    const submittedAt=performance.now();
    const {body}=await apiJson('/api/housionna/radio-map',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    timings.submission_roundtrip_ms=performance.now()-submittedAt;
    const pollAt=performance.now(),job=await pollHousionnaJob('radio_map',body.job_id,body);
    timings.wait_and_result_ms=performance.now()-pollAt;
    await finishHousionnaMap(job,scenario,payload,timings);
  }catch(error){showSimulationError(error);setRunStatus('failed','Radio-map calculation stopped. Previous results are retained; inspect diagnostics and retry.');}
  finally{simulationRunning=false;setSimulationInputsDisabled(false);}
}

async function reconnectHousionnaJob(){
  try{
    const {body:{job}}=await apiJson('/api/housionna/simulations/active');
    if(!job||simulationRunning)return;
    const find=()=>Object.values(data.scenarios).find(row=>row.source_type==='housionna'&&row.import_id===job.import_id&&row.transmitter.name===job.transmitter);
    if(!find())return;
    await ensureHousionnaImport(job.import_id);  // the job's run may still be a stub
    const scenario=find();
    if(activeScenario!==scenario.name){setSourceControls('housionna');populateSourceSelectors(job.import_id,job.transmitter);}
    activeScenario=scenario.name;buildScenario({preserveView:true});syncSimulationControls(scenario);
    simulationRunning=true;simulationStartedAt=performance.now()-1000*Number(job.elapsed_seconds||0);setSimulationInputsDisabled(true);
    setRunStatus('running',`Reconnected to ${job.task} calculation`);
    const result=await pollHousionnaJob(job.task,job.job_id,job);
    if(job.task==='radio_map')await finishHousionnaMap(result,scenario,null);
    else installHousionnaPathResult(scenario,result);
  }catch(error){showSimulationError(error);setRunStatus('failed','Could not reconnect to the calculation. Saved results remain available.');}
  finally{simulationRunning=false;setSimulationInputsDisabled(false);}
}

async function runSimulation() {
  if(data?.scenarios?.[activeScenario]?.source_type==='housionna')return runHousionnaSimulation();
  if($('#sceneSourceSelect').value==='housionna') {setRunStatus('current','Import a HOUSIONNA run before starting a Sionna simulation.');return;}
  if(simulationRunning)return;
  const settings=collectSimulationSettings();
  if(!Number.isFinite(settings.frequency_hz)||settings.tx.position_m.some(value=>!Number.isFinite(value))) {
    const error=new Error('Frequency and TX position must contain valid numbers.');showSimulationError(error);return;
  }
  const limits=txBounds(data.scenarios[settings.scenario]);
  const outside=settings.tx.position_m.findIndex((value,index)=>value<limits[['x','y','z'][index]][0]||value>limits[['x','y','z'][index]][1]);
  if(settings.frequency_hz<100e6||settings.frequency_hz>6e9||outside>=0) {
    const error=new Error(outside>=0?`TX ${'XYZ'[outside]} is outside allowed farm bounds.`:'Frequency must be between 0.1 and 6 GHz.');
    showSimulationError(error);setRunStatus('failed','Correct the highlighted RF setting before running.');return;
  }
  simulationRunning=true;simulationStartedAt=performance.now();setSimulationInputsDisabled(true);$('#simulationError').classList.add('hidden');
  setRunStatus('running','Running Sionna RT… elapsed 0.0 s');
  simulationClock=setInterval(()=>setRunStatus('running',`Running Sionna RT… elapsed ${((performance.now()-simulationStartedAt)/1000).toFixed(1)} s`),500);
  try {
    const {response,body}=await apiJson('/api/simulate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(settings)});
    let job=body;
    while(job.status==='running') {
      await new Promise(resolve=>setTimeout(resolve,650));
      const polled=await apiJson(`/api/simulation/${encodeURIComponent(job.run_id)}`);job=polled.body;
      setRunStatus('running',`Running Sionna RT… elapsed ${Number(job.elapsed_seconds||((performance.now()-simulationStartedAt)/1000)).toFixed(1)} s`);
    }
    if(job.status!=='complete'||!job.result)throw new Error(job.error||'Sionna did not return a completed result.');
    const cached=Boolean(job.cached||body.cached);
    const duration=job.duration_seconds??body.duration_seconds;
    applyLiveResult(job.run_id,job.result,cached,duration);
  } catch(error) {
    showSimulationError(error);setRunStatus('failed',`Simulation failed${error.status?` (HTTP ${error.status})`:''}.`);
  } finally {
    simulationRunning=false;setSimulationInputsDisabled(false);if(simulationClock){clearInterval(simulationClock);simulationClock=null;}
  }
}

function showSimulationError(error) {
  const panel=$('#simulationError');
  const label=error.resource?`${error.resource}${error.status?` · HTTP ${error.status}`:''}`:'';
  panel.innerHTML=`${label?`<b>${esc(label)}</b><br>`:''}${esc(error.message||error)}`;panel.classList.remove('hidden');
  console.error('On-demand Sionna simulation failed',error);
  if(error.jobId)void apiJson(`/api/housionna/simulations/${encodeURIComponent(error.jobId)}/diagnostics`).then(({body})=>{$('#simulationDiagnosticsData').textContent=JSON.stringify(body,null,2);}).catch(diagnosticError=>console.warn('Could not load worker diagnostics',diagnosticError));
}

async function loadHistoryResult(runId) {
  if(simulationRunning)return;
  try {
    const {body}=await apiJson(`/api/simulation/${encodeURIComponent(runId)}`);
    if(body.status!=='complete'||!body.result)throw new Error(body.error||'This run has no completed result.');
    applyLiveResult(runId,body.result,false,body.duration_seconds);
    setRunStatus('complete',`Loaded saved simulation ${runId.slice(0,8)}.`);
  } catch(error) {showSimulationError(error);setRunStatus('failed','Could not load the selected saved run.');}
}

function builtinScenarioNames() {
  return data.scenario_order.filter((name)=>data.scenarios[name]?.source_type!=='housionna');
}

function housionnaGroups() {
  const groups=new Map();
  for(const key of data.scenario_order) {
    const scenario=data.scenarios[key];
    if(scenario?.source_type!=='housionna')continue;
    const id=scenario.import_id||scenario.run_metadata?.import_id;
    if(!id)continue;
    if(!groups.has(id))groups.set(id,{import_id:id,run_id:scenario.run_metadata?.run_id||scenario.provenance?.run_folder_name||id,
      scene_name:scenario.run_metadata?.scene_name,imported_at_utc:scenario.run_metadata?.imported_at_utc,
      frequency_hz:scenario.frequency_hz,batch_id:scenario.run_metadata?.batch?.id||null,
      parameters:scenario.run_metadata?.parameters||null,wedge_index:scenario.run_metadata?.wedge?.wedgeindex??null,scenario_keys:[]});
    groups.get(id).scenario_keys.push(key);
  }
  return [...groups.values()].reverse();
}

function setSourceControls(source) {
  const previous=$('#sceneSourceSelect').value;
  $('#sceneSourceSelect').value=source;
  $('#builtinSceneControls').classList.toggle('hidden',source!=='builtin');
  $('#housionnaControls').classList.toggle('hidden',source!=='housionna');
  if(source!==previous) {
    if(source==='housionna') {
      $('#housionnaGeometryMode').value='solid';
      $('#deviceDisplayMode').value='selected';
      $('#deviceLabelMode').value='selected';
      $('#measurementMeshToggle').checked=false;
      $('#coordinateDiagnosticToggle').checked=false;
      $('#sceneBoundsToggle').checked=false;
    } else {
      $('#deviceDisplayMode').value='selected';
      $('#deviceLabelMode').value='all';
      $('#measurementMeshToggle').checked=false;
      $('#coordinateDiagnosticToggle').checked=true;
      $('#sceneBoundsToggle').checked=true;
    }
  }
}

function populateHousionnaTxSelect(group, preferredTx) {
  const select=$('#housionnaTxSelect');
  const keys=group?.scenario_keys||[];
  select.innerHTML=keys.map((key)=>{
    const tx=data.scenarios[key].transmitter?.name||key;
    return `<option value="${esc(key)}">${esc(tx)}</option>`;
  }).join('');
  const key=keys.find((value)=>data.scenarios[value].transmitter?.name===preferredTx)||keys[0];
  if(key)select.value=key;
  return key;
}

// Procedural tests produce many runs of one scene: step through them in export order and show what changed.
function housionnaRunsByTime() {
  return housionnaGroups().sort((a,b)=>String(a.run_id).localeCompare(String(b.run_id))||String(a.imported_at_utc||'').localeCompare(String(b.imported_at_utc||'')));
}
// The stepper walks one batch in work-item order, or the single (non-batch) runs in export order.
function stepperRuns(batchId) {
  return batchId
    ?housionnaRunsByTime().filter((group)=>group.batch_id===batchId).sort((a,b)=>(a.wedge_index??0)-(b.wedge_index??0)||String(a.run_id).localeCompare(String(b.run_id)))
    :housionnaRunsByTime().filter((group)=>!group.batch_id);
}
function stepHousionnaRun(delta) {
  const current=housionnaGroups().find((group)=>group.import_id===$('#housionnaRunSelect').value);
  const runs=stepperRuns(current?.batch_id),index=runs.findIndex((group)=>group.import_id===current?.import_id);
  const target=runs[index+delta];if(!target)return;
  $('#housionnaRunSelect').value=target.import_id;$('#housionnaRunSelect').dispatchEvent(new Event('change'));
}
function runScenarioFor(group,txName) {
  const keys=group.scenario_keys||[];
  return data.scenarios[keys.find((key)=>data.scenarios[key]?.transmitter?.name===txName)||keys[0]];
}
function surfaceBounds(scenario) {
  if(scenario?.stub)return scenario.summary?.surface_bounds||null;
  const boxes=(scenario?.radio_map?.surfaces||[]).map((surface)=>surface.mesh?.bounds_m).filter(Boolean);
  if(!boxes.length)return null;
  const box={};for(const axis of 'xyz'){box[`${axis}_min`]=Math.min(...boxes.map((b)=>b[`${axis}_min`]));box[`${axis}_max`]=Math.max(...boxes.map((b)=>b[`${axis}_max`]));}
  return box;
}
function medianDb(scenario) {
  if(scenario?.stub)return scenario.summary?.median_db??null;
  const values=(scenario?.radio_map?.surfaces||[]).flatMap((surface)=>surface.values_db||[]).filter((value)=>value!=null).sort((a,b)=>a-b);
  return values.length?values[Math.floor(values.length/2)]:null;
}
// Batch work items are "<batch>.wiNNN"; wedged Houdini attributes are TOPS_<name> (see run_metadata.parameters).
const runLabel=(runId)=>String(runId??'').replace('.',' · ');
const paramLabel=(key)=>key.replace(/^TOPS_/,'').replace(/_/g,' ');
const paramValue=(value)=>value==null?'—':String(+Number(value).toFixed(3));
function flatSettings(value,prefix='') {
  if(!value||typeof value!=='object')return {[prefix]:value};
  return Object.entries(value).reduce((out,[key,inner])=>({...out,...flatSettings(inner,prefix?`${prefix}.${key}`:key)}),{});
}
function runChanges(previous,current) {
  const changes=[],fmt=(value,digits=2)=>Number(value).toFixed(digits),pm=previous.run_metadata||{},cm=current.run_metadata||{};
  const pa=pm.parameters||{},pc=cm.parameters||{};
  for(const key of [...new Set([...Object.keys(pa),...Object.keys(pc)])].sort())
    if(paramValue(pa[key])!==paramValue(pc[key]))changes.push(`${paramLabel(key)} ${paramValue(pa[key])} → ${paramValue(pc[key])}`);
  if(previous.frequency_hz!==current.frequency_hz)changes.push(`frequency ${fmt(previous.frequency_hz/1e9,3)} → ${fmt(current.frequency_hz/1e9,3)} GHz`);
  for(const [key,label] of [['tx_count','TX'],['rx_count','RX'],['mesh_count','scene objects']])if(pm[key]!==cm[key])changes.push(`${label} ${pm[key]??'?'} → ${cm[key]??'?'}`);
  const a=surfaceBounds(previous),b=surfaceBounds(current);
  if(a&&b)for(const axis of 'xyz') {
    const centreA=(a[`${axis}_min`]+a[`${axis}_max`])/2,centreB=(b[`${axis}_min`]+b[`${axis}_max`])/2;
    const sizeA=a[`${axis}_max`]-a[`${axis}_min`],sizeB=b[`${axis}_max`]-b[`${axis}_min`];
    if(Math.abs(centreA-centreB)>0.01)changes.push(`measurement surface ${axis} ${fmt(centreA)} → ${fmt(centreB)} m`);
    else if(Math.abs(sizeA-sizeB)>0.01)changes.push(`measurement surface ${axis}-size ${fmt(sizeA)} → ${fmt(sizeB)} m`);
  }
  const from=previous.transmitter?.position_m,to=current.transmitter?.position_m;
  if(from&&to&&previous.transmitter.name===current.transmitter.name) {
    const moved=Math.hypot(...to.map((value,index)=>value-from[index]));
    if(moved>0.01)changes.push(`${current.transmitter.name} moved ${fmt(moved)} m`);
  }
  const settingsA=flatSettings(previous.solver),settingsB=flatSettings(current.solver);
  for(const key of new Set([...Object.keys(settingsA),...Object.keys(settingsB)]))
    if(JSON.stringify(settingsA[key])!==JSON.stringify(settingsB[key]))changes.push(`${key} ${settingsA[key]??'—'} → ${settingsB[key]??'—'}`);
  const medianA=medianDb(previous),medianB=medianDb(current);
  if(medianA!=null&&medianB!=null&&Math.abs(medianA-medianB)>=0.05)changes.push(`median map ${fmt(medianA,1)} → ${fmt(medianB,1)} dB`);
  return changes;
}
// One series (a value per run of this scene), so no legend box: the Value selector names it.
// Colour is DRAMCO --data-1, the guide's first data token for dark backgrounds (contrast checked on --card).
const SERIES_METRICS={
  median_map:{label:'Median radio map',unit:'dB',value:(scenario)=>medianDb(scenario)},
  mean_link:{label:'Mean link gain over RX',unit:'dB',value:(scenario)=>{
    if(scenario.stub)return scenario.summary?.mean_link_db??null;
    const gains=(scenario.links||[]).map((link)=>link.gain_db_coherent).filter((value)=>value!=null);
    return gains.length?gains.reduce((sum,value)=>sum+value,0)/gains.length:null;}},
  reached:{label:'Reached map cells',unit:'%',value:(scenario)=>{
    if(scenario.stub)return scenario.summary?.reached_pct??null;
    const values=(scenario.radio_map?.surfaces||[]).flatMap((surface)=>surface.values_db||[]);
    return values.length?100*values.filter((value)=>value!=null).length/values.length:null;}},
  paths:{label:'Path count',unit:'',value:(scenario)=>scenario.stub?scenario.summary?.path_count??null:(scenario.paths||[]).length},
};
const SERIES_AXES={
  surface_x:{label:'Measurement surface x',unit:'m',value:(s)=>{const b=surfaceBounds(s);return b?(b.x_min+b.x_max)/2:null;}},
  surface_y:{label:'Measurement surface y',unit:'m',value:(s)=>{const b=surfaceBounds(s);return b?(b.y_min+b.y_max)/2:null;}},
  surface_z:{label:'Measurement surface z',unit:'m',value:(s)=>{const b=surfaceBounds(s);return b?(b.z_min+b.z_max)/2:null;}},
  tx_x:{label:'TX x',unit:'m',value:(s)=>s.transmitter?.position_m?.[0]??null},
  tx_y:{label:'TX y',unit:'m',value:(s)=>s.transmitter?.position_m?.[1]??null},
  tx_z:{label:'TX z',unit:'m',value:(s)=>s.transmitter?.position_m?.[2]??null},
  frequency:{label:'Frequency',unit:'GHz',value:(s)=>s.frequency_hz?s.frequency_hz/1e9:null},
  rx_count:{label:'RX count',unit:'',value:(s)=>s.run_metadata?.rx_count??null},
};
function niceTicks(min,max,count=4) {
  if(!(max>min)){const pad=Math.abs(min)*0.05||1;min-=pad;max+=pad;}
  const raw=(max-min)/count,power=10**Math.floor(Math.log10(raw)),step=[1,2,2.5,5,10].map((f)=>f*power).find((v)=>v>=raw);
  const start=Math.floor(min/step)*step,ticks=[];
  for(let value=start;value<=max+step*0.5;value+=step)ticks.push(+value.toFixed(10));
  return {ticks,min:ticks[0],max:ticks.at(-1)};
}
// A batch (one Houdini cook) is its own series in work-item order; other runs group by scene name.
let seriesFilter={batch:null,current:null,values:{}};
function seriesPoints(scenario) {
  const scene=scenario.run_metadata?.scene_name,txName=scenario.transmitter?.name,batch=scenario.run_metadata?.batch?.id;
  const runs=batch
    ?stepperRuns(batch)
    :housionnaRunsByTime().filter((group)=>group.scene_name===scene&&!group.batch_id);
  return runs.map((group,index)=>{
    const run=runScenarioFor(group,txName);
    return {group,index,run:run?.transmitter?.name===txName?run:null};
  });
}
function renderRunSeries(scenario) {
  const panel=$('#runSeries'),allPoints=scenario?.source_type==='housionna'?seriesPoints(scenario):[];
  panel.classList.toggle('hidden',allPoints.length<2);
  if(allPoints.length<2)return;
  const fmt=(value,unit)=>{
    if(value==null)return '—';
    let text=Number(value).toFixed(Math.abs(value)>=100?0:2);
    if(text.includes('.'))text=text.replace(/0+$/,'').replace(/\.$/,'');  // trim decimals only, never 100 -> 1
    return `${text}${unit?` ${unit}`:''}`;
  };
  const batch=scenario.run_metadata?.batch||null,currentId=scenario.import_id||scenario.run_metadata?.import_id;
  // Wedged parameters that differ inside this batch. Several can vary at once (nested wedges), so all but the
  // x axis become filters, set to the current run's values whenever another run is opened.
  const params=batch?[...new Set(allPoints.flatMap((p)=>Object.keys(p.group.parameters||{})))]
    .filter((key)=>new Set(allPoints.map((p)=>JSON.stringify(p.group.parameters?.[key]??null))).size>1).sort():[];
  const own=scenario.run_metadata?.parameters||{};
  const fresh=batch&&seriesFilter.batch!==batch.id;
  if(fresh||(batch&&seriesFilter.current!==currentId&&params.some((key)=>!['any',own[key]].includes(seriesFilter.values[key]))))
    seriesFilter={batch:batch.id,current:currentId,values:Object.fromEntries(params.map((key)=>[key,own[key]]))};
  seriesFilter.current=currentId;
  $('#seriesSummary').textContent=batch?'Across this batch':'Across runs of this scene';
  // Offer an x axis for every quantity that actually varies across this series.
  const axisSelect=$('#seriesAxis'),kept=axisSelect.value;
  const paramAxes=params.map((key)=>[`param:${key}`,{label:paramLabel(key),unit:'',param:key,value:(run,group)=>group?.parameters?.[key]??null}]);
  const varying=Object.entries(SERIES_AXES).filter(([,axis])=>{
    const values=allPoints.filter((p)=>p.run).map((p)=>axis.value(p.run)).filter((v)=>v!=null).map((v)=>v.toFixed(3));
    return new Set(values).size>1;});
  const axes=Object.fromEntries([...paramAxes,...varying]);
  axisSelect.innerHTML=['<option value="order">Run order</option>',...Object.entries(axes).map(([key,axis])=>`<option value="${esc(key)}">${esc(axis.label)}${axis.unit?` (${axis.unit})`:''}</option>`)].join('');
  const wedged=batch&&scenario.run_metadata?.wedge?.wedgeattribs?`param:${scenario.run_metadata.wedge.wedgeattribs}`:null;
  const has=(key)=>key&&[...axisSelect.options].some((o)=>o.value===key);
  axisSelect.value=!fresh&&has(kept)?kept:has(wedged)?wedged:paramAxes[0]?.[0]||(has(kept)?kept:'order');
  const metric=SERIES_METRICS[$('#seriesMetric').value]||SERIES_METRICS.median_map,axisKey=axisSelect.value,axis=axes[axisKey];
  const filterKeys=params.filter((key)=>key!==axis?.param);
  $('#seriesFilters').innerHTML=filterKeys.map((key)=>{
    const values=[...new Set(allPoints.map((p)=>p.group.parameters?.[key]).filter((v)=>v!=null))].sort((a,b)=>a-b),selected=seriesFilter.values[key];
    return `<label class="field-label" for="seriesFilter-${esc(key)}">${esc(paramLabel(key))}</label><select id="seriesFilter-${esc(key)}" class="select-control" data-param="${esc(key)}"><option value="any"${selected==='any'?' selected':''}>Any</option>${
      values.map((v)=>`<option value="${esc(JSON.stringify(v))}"${v===selected?' selected':''}>${esc(paramValue(v))}</option>`).join('')}</select>`;
  }).join('');
  $('#seriesFilters').querySelectorAll('select').forEach((select)=>select.addEventListener('change',()=>{
    seriesFilter.values[select.dataset.param]=select.value==='any'?'any':JSON.parse(select.value);
    renderRunSeries(data.scenarios[activeScenario]);
  }));
  const points=allPoints.filter((p)=>filterKeys.every((key)=>seriesFilter.values[key]==='any'||p.group.parameters?.[key]===seriesFilter.values[key]))
    .map((p,index)=>({...p,index}));
  $('#seriesBatch').classList.toggle('hidden',!batch);
  if(batch)$('#seriesBatch').textContent=`Batch ${batch.id} · ${allPoints.length}${batch.items?` of ${batch.items}`:''} work items imported${filterKeys.length?` · ${points.length} match the filters`:''}`;
  const rows=points.map((p)=>({...p,x:axis?(p.run?axis.value(p.run,p.group):null):p.index+1,y:p.run?metric.value(p.run):null}));
  const plotted=rows.filter((row)=>row.x!=null&&row.y!=null).sort((a,b)=>a.x-b.x||a.index-b.index);
  const xLabel=axis?`${axis.label}${axis.unit?` (${axis.unit})`:''}`:'Run (oldest first)';
  $('#seriesTable').innerHTML=`<table class="zone-table"><thead><tr><th scope="col">Run</th><th scope="col">${esc(axis?axis.label:'#')}</th><th scope="col">${esc(metric.label)}</th></tr></thead><tbody>${
    rows.map((row)=>`<tr${row.group.import_id===currentId?' class="current"':''}><th scope="row">${esc(runLabel(row.group.run_id))}</th><td class="num">${axis?fmt(row.x,axis.unit):row.x}</td><td class="num">${row.run?fmt(row.y,metric.unit):`no ${esc(scenario.transmitter?.name||'TX')}`}</td></tr>`).join('')}</tbody></table>`;
  const chart=$('#seriesChart');
  if(plotted.length<2){chart.innerHTML=`<p class="muted-copy">Fewer than two runs ${filterKeys.length?'match these filters and ':''}have this value for the selected transmitter.</p>`;return;}
  const width=Math.max(220,chart.clientWidth||250),height=168,pad={l:38,r:12,t:12,b:34};
  const xs=niceTicks(Math.min(...plotted.map((r)=>r.x)),Math.max(...plotted.map((r)=>r.x)),axis?4:Math.min(plotted.length-1,5));
  const ys=niceTicks(Math.min(...plotted.map((r)=>r.y)),Math.max(...plotted.map((r)=>r.y)),3);
  const sx=(v)=>pad.l+(v-xs.min)/(xs.max-xs.min||1)*(width-pad.l-pad.r),sy=(v)=>pad.t+(1-(v-ys.min)/(ys.max-ys.min||1))*(height-pad.t-pad.b);
  const xTicks=axis?xs.ticks:xs.ticks.filter((t)=>Number.isInteger(t)&&t>=1&&t<=points.length);
  const current=plotted.find((row)=>row.group.import_id===currentId);
  // A line implies continuity; when several runs share an x value, show the points only.
  const drawLine=!axis||new Set(plotted.map((row)=>row.x.toFixed(6))).size===plotted.length;
  chart.innerHTML=`<svg class="series-svg" viewBox="0 0 ${width} ${height}" width="${width}" height="${height}" aria-label="${esc(metric.label)} along ${esc(xLabel)}">
    ${ys.ticks.map((t)=>`<line class="grid" x1="${pad.l}" x2="${width-pad.r}" y1="${sy(t)}" y2="${sy(t)}"/><text class="tick" x="${pad.l-6}" y="${sy(t)+3}" text-anchor="end">${fmt(t,'')}</text>`).join('')}
    <line class="axis" x1="${pad.l}" x2="${width-pad.r}" y1="${height-pad.b}" y2="${height-pad.b}"/>
    ${xTicks.map((t)=>`<text class="tick" x="${sx(t)}" y="${height-pad.b+13}" text-anchor="middle">${fmt(t,'')}</text>`).join('')}
    <text class="axis-title" x="${(pad.l+width-pad.r)/2}" y="${height-4}" text-anchor="middle">${esc(xLabel)}</text>
    ${drawLine?`<polyline class="series-line" points="${plotted.map((r)=>`${sx(r.x)},${sy(r.y)}`).join(' ')}"/>`:''}
    ${plotted.map((r)=>`<circle class="series-dot${r===current?' current':''}" cx="${sx(r.x)}" cy="${sy(r.y)}" r="${r===current?5:4}"/>`).join('')}
    ${current?`<text class="series-value" x="${Math.min(sx(current.x)+8,width-pad.r)}" y="${sy(current.y)-8}" text-anchor="${sx(current.x)+8>width-70?'end':'start'}">${fmt(current.y,metric.unit)}</text>`:''}
    ${plotted.map((r,i)=>`<circle class="series-hit" data-index="${i}" cx="${sx(r.x)}" cy="${sy(r.y)}" r="12" tabindex="0" role="button" aria-label="${esc(runLabel(r.group.run_id))}: ${esc(fmt(r.y,metric.unit))}. Open this run."/>`).join('')}
  </svg>`;
  const tooltip=$('#seriesTooltip');
  const show=(event)=>{
    const row=plotted[Number(event.target.dataset.index)];if(!row)return;
    tooltip.innerHTML=`<b>${esc(runLabel(row.group.run_id))}</b><br>${esc(metric.label)}: ${esc(fmt(row.y,metric.unit))}${axis?`<br>${esc(axis.label)}: ${esc(fmt(row.x,axis.unit))}`:''}`;
    const box=event.target.getBoundingClientRect(),host=panel.getBoundingClientRect(),plotTop=chart.getBoundingClientRect().top-host.top;
    tooltip.classList.remove('hidden');
    const above=box.top-host.top-tooltip.offsetHeight-4;  // flip below the point when it would cover the controls
    tooltip.style.left=`${Math.max(0,Math.min(box.left-host.left-60,host.width-150))}px`;
    tooltip.style.top=`${above>=plotTop?above:box.bottom-host.top+4}px`;
  };
  const hide=()=>tooltip.classList.add('hidden');
  const open=(event)=>{const row=plotted[Number(event.target.dataset.index)];if(!row||row.group.import_id===currentId)return;
    $('#housionnaRunSelect').value=row.group.import_id;$('#housionnaRunSelect').dispatchEvent(new Event('change'));};
  chart.querySelectorAll('.series-hit').forEach((hit)=>{
    hit.addEventListener('mouseenter',show);hit.addEventListener('focus',show);
    hit.addEventListener('mouseleave',hide);hit.addEventListener('blur',hide);
    hit.addEventListener('click',open);hit.addEventListener('keydown',(event)=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();open(event);}});
  });
}

function syncRunStepper(scenario) {
  renderRunSeries(scenario);
  const runs=stepperRuns(scenario?.run_metadata?.batch?.id),index=runs.findIndex((group)=>group.import_id===(scenario?.import_id||scenario?.run_metadata?.import_id));
  const visible=scenario?.source_type==='housionna'&&index>=0;
  $('.run-stepper').classList.toggle('hidden',!visible||runs.length<2);
  $('#housionnaRunChanges').classList.toggle('hidden',!visible);
  if(!visible)return;
  $('#housionnaOlderRun').disabled=index<=0;$('#housionnaNewerRun').disabled=index>=runs.length-1;
  $('#housionnaRunPosition').textContent=`${index+1} / ${runs.length}`;
  $('#housionnaRunPosition').title=scenario.run_metadata?.batch?.id?`Work item ${index+1} of ${runs.length} imported in this batch`:`Run ${index+1} of ${runs.length} single runs`;
  if(index<=0){$('#housionnaRunChanges').textContent=scenario.run_metadata?.batch?.id?'First imported work item of this batch.':'Oldest imported run.';return;}
  const previous=runScenarioFor(runs[index-1],scenario.transmitter?.name);
  const changes=previous?runChanges(previous,scenario):[];
  $('#housionnaRunChanges').innerHTML=changes.length
    ?`<b>Since ${esc(runLabel(runs[index-1].run_id))}:</b> ${changes.map(esc).join(' · ')}`
    :`<b>Since ${esc(runLabel(runs[index-1].run_id))}:</b> no change in settings, devices or measurement surface.`;
}

function renderHousionnaMetadata(scenario) {
  syncRunStepper(scenario);
  const target=$('#housionnaRunMetadata');
  if(!scenario||scenario.source_type!=='housionna') {
    target.textContent=housionnaGroups().length?'Select an imported HOUSIONNA run.':'No imported HOUSIONNA runs are available yet.';
    return;
  }
  const meta=scenario.run_metadata||{}, mapTriangles=(scenario.radio_map?.surfaces||[]).reduce((sum,row)=>sum+(row.mesh?.faces?.length||row.values_db?.length||0),0);
  const runId=meta.run_id||scenario.provenance?.run_folder_name||'unknown';
  const allMapSamples=Number(meta.radio_map_triangle_count??mapTriangles);
  const wedged=Object.entries(meta.parameters||{}).map(([key,value])=>`${esc(paramLabel(key))} ${esc(paramValue(value))}`).join(' / ');
  target.innerHTML=`<b>${esc(runLabel(runId))}</b>${meta.scene_name?` / ${esc(meta.scene_name)}`:''}<br>${wedged?`${wedged}<br>`:''}${(Number(scenario.frequency_hz)/1e9).toFixed(3)} GHz / ${meta.tx_count??1} TX / ${meta.rx_count??scenario.receivers.length} RX / ${meta.mesh_count??scenario.geometry.objects.length} RF scene meshes<br>${meta.path_count??scenario.paths.length} total paths / ${allMapSamples.toLocaleString()} map samples across TXs<br>Selected ${esc(scenario.transmitter.name)}: ${scenario.paths.length} paths / ${mapTriangles.toLocaleString()} measurement triangles`;
}

function populateSourceSelectors(preferredImportId=null, preferredTx=null) {
  const builtinNames=builtinScenarioNames();
  $('#scenarioSelect').innerHTML=builtinNames.map((name)=>`<option value="${esc(name)}">${esc(data.scenarios[name].label)}</option>`).join('');
  if(builtinNames.includes(activeScenario))$('#scenarioSelect').value=activeScenario;
  const groups=housionnaGroups();
  const option=(group)=>{
    const suffix=group.import_id.split('-').at(-1)?.slice(0,8)||'';
    if(!group.batch_id)return `<option value="${esc(group.import_id)}">${esc(runLabel(group.run_id))} · ${esc(group.scene_name||'scene')} · ${esc(suffix)}</option>`;
    // Inside a batch the work item and its wedged values say more than the shared scene name.
    const wedged=Object.entries(group.parameters||{}).map(([key,value])=>`${paramLabel(key)} ${paramValue(value)}`).join(', ');
    return `<option value="${esc(group.import_id)}">${esc(String(group.run_id).split('.').at(-1))}${wedged?` · ${esc(wedged)}`:''}</option>`;
  };
  const singles=groups.filter((group)=>!group.batch_id);
  const batches=[...new Set(groups.filter((group)=>group.batch_id).map((group)=>group.batch_id))].sort().reverse();
  $('#housionnaRunSelect').innerHTML=[
    singles.length?`<optgroup label="Single runs">${singles.map(option).join('')}</optgroup>`:'',
    ...batches.map((batch)=>{const items=stepperRuns(batch);return `<optgroup label="Batch ${esc(batch)} (${items.length})">${items.map(option).join('')}</optgroup>`;}),
  ].join('');
  const activeGroupId=preferredImportId||data.scenarios[activeScenario]?.import_id||groups[0]?.import_id;
  const group=groups.find((item)=>item.import_id===activeGroupId)||groups[0];
  if(group) {
    $('#housionnaRunSelect').value=group.import_id;
    populateHousionnaTxSelect(group,preferredTx||data.scenarios[activeScenario]?.transmitter?.name);
  } else {
    $('#housionnaRunSelect').innerHTML='<option value="">No imported runs</option>';
    $('#housionnaTxSelect').innerHTML='<option value="">No transmitters</option>';
  }
  const validExports=housionnaRuns.filter((row)=>row.status==='valid');
  const exportSelect=$('#housionnaExportSelect'),oldExport=exportSelect.value;
  exportSelect.innerHTML=housionnaRuns.map((row)=>{
    const alreadyImported=groups.some((item)=>item.run_id===row.run_id);
    const label=`${row.run_id} / ${row.status==='valid'?(alreadyImported?'imported':'ready to import'):row.status}`;
    return `<option value="${esc(row.run_id)}" ${row.status==='valid'?'':'disabled'}>${esc(label)}</option>`;
  }).join('')||'<option value="">No discovered exports</option>';
  if(validExports.some((row)=>row.run_id===oldExport))exportSelect.value=oldExport;
  else if(validExports[0])exportSelect.value=validExports[0].run_id;
  $('#importSelectedHousionna').disabled=housionnaImportBusy||validExports.length===0;
  populateComparisonSelectors();
}

function populateComparisonSelectors() {
  const fallback=housionnaGroups().map((group)=>({import_id:group.import_id,run_id:group.run_id,scene_name:group.scene_name,transmitters:group.scenario_keys.map((key)=>data.scenarios[key].transmitter.name)}));
  const imports=housionnaImports.length?housionnaImports:fallback;
  const optionHtml=imports.map((row)=>`<option value="${esc(row.import_id)}">${esc(row.run_id||row.import_id)} · ${esc(row.scene_name||'scene')}</option>`).join('');
  for(const id of ['compareReference','compareRun']) {
    const select=$(`#${id}`), old=select.value;
    select.innerHTML=optionHtml||'<option value="">No imported runs</option>';
    if(imports.some((row)=>row.import_id===old))select.value=old;
  }
  updateCompareTxOptions();
  $('#compareHousionna').disabled=imports.length===0;
}

function updateCompareTxOptions() {
  const ref=housionnaImports.find((row)=>row.import_id===$('#compareReference').value);
  const comp=housionnaImports.find((row)=>row.import_id===$('#compareRun').value);
  const refTx=ref?.transmitters||housionnaGroups().find((row)=>row.import_id===$('#compareReference').value)?.scenario_keys.map((key)=>data.scenarios[key].transmitter.name)||[];
  const compTx=comp?.transmitters||housionnaGroups().find((row)=>row.import_id===$('#compareRun').value)?.scenario_keys.map((key)=>data.scenarios[key].transmitter.name)||[];
  const common=refTx.filter((name)=>compTx.includes(name));
  const select=$('#compareTx'), old=select.value;
  select.innerHTML=common.map((name)=>`<option value="${esc(name)}">${esc(name)}</option>`).join('');
  if(common.includes(old))select.value=old;
  $('#compareHousionna').disabled=common.length===0;
}

async function chooseSceneSource(source, importId=null, transmitterName=null) {
  if(source==='builtin') {
    const names=builtinScenarioNames();
    if(!names.length)return;
    setSourceControls('builtin');
    if(!names.includes(activeScenario))activeScenario=names.includes('farm_proxy')?'farm_proxy':names[0];
    $('#scenarioSelect').value=activeScenario;
    rfResultsStale=false;buildScenario({preserveView:true});syncSimulationControls(data.scenarios[activeScenario]);
    return;
  }
  setSourceControls('housionna');
  const groups=housionnaGroups();
  if(!groups.length) {
    $('#housionnaRunMetadata').textContent='No imported HOUSIONNA results are loaded.';
    setHousionnaStatus('ready','Choose Import latest Houdini run to load a completed export.');
    $('#simulationReadOnlyNote').textContent='HOUSIONNA is selected. Import a saved run to inspect results; live Sionna edits stay disabled.';
    setSimulationInputsDisabled(false);
    return;
  }
  const group=groups.find((item)=>item.import_id===importId)||groups.find((item)=>item.import_id===data.scenarios[activeScenario]?.import_id)||groups[0];
  try {await ensureHousionnaImport(group.import_id);}
  catch(error){setHousionnaStatus('failed',`Could not load ${group.run_id}: ${error.message||error}`);return;}
  const key=group.scenario_keys.find((name)=>data.scenarios[name].transmitter?.name===transmitterName)||group.scenario_keys[0];
  activeScenario=key;$('#housionnaRunSelect').value=group.import_id;populateHousionnaTxSelect(group,data.scenarios[key].transmitter.name);
  $('#scenarioSelect').value=builtinScenarioNames()[0]||'';
  rfResultsStale=false;buildScenario({preserveView:true});syncSimulationControls(data.scenarios[activeScenario]);
  renderHousionnaMetadata(data.scenarios[activeScenario]);
  void restoreLatestHousionnaResults(activeScenario);
}

function setHousionnaStatus(state,message) {
  const badge=$('#housionnaStatus');badge.className=`status-pill ${state}`;badge.textContent=state.replaceAll('_',' ').toUpperCase();
  $('#housionnaImportStatus').textContent=message;
}

async function loadHousionnaCatalog() {
  // The first look at a new batch validates every work item once (about a minute for 280); later loads are quick.
  const slow=setTimeout(()=>setHousionnaStatus('running','Checking exports… a new batch takes up to a few minutes the first time.'),3000);
  const [runsResult,importsResult]=await Promise.allSettled([apiJson('/api/housionna/runs',{timeoutMs:600000}),apiJson('/api/housionna/imports')]);
  clearTimeout(slow);
  if(runsResult.status==='fulfilled')housionnaRuns=runsResult.value.body.runs||[];
  if(importsResult.status==='fulfilled')housionnaImports=importsResult.value.body.imports||[];
  syncImportAllButton();
  populateSourceSelectors(data.scenarios[activeScenario]?.import_id,data.scenarios[activeScenario]?.transmitter?.name);
  const valid=housionnaRuns.filter((row)=>row.status==='valid').length;
  const incomplete=housionnaRuns.filter((row)=>row.status!=='valid').length;
  if(runsResult.status==='rejected')setHousionnaStatus('failed',`Run discovery failed: ${runsResult.reason.message}`);
  else if(housionnaImports.length)setHousionnaStatus('ready',`${valid} valid export${valid===1?'':'s'} discovered · ${housionnaImports.length} import revision${housionnaImports.length===1?'':'s'} available${incomplete?` · ${incomplete} incomplete/invalid folder${incomplete===1?'':'s'} excluded`:''}.`);
  else setHousionnaStatus('ready',valid?`${valid} completed export${valid===1?'':'s'} available to import.`:'No valid completed export found in the configured directory.');
}

async function refreshViewerScene(importId,txName) {
  const {body:next}=await apiJson(SCENE_URL);
  if(next.schema_version!==1||!next.scenarios)throw new Error('Refreshed viewer data has an unsupported schema');
  resolveViewerAssets(next);data=next;rememberHousionnaStubs();
  await ensureHousionnaImport(importId);
  housionnaOriginalResults.clear();housionnaLatestResults.clear();housionnaDisplayedVersions.clear();housionnaCompletedFingerprints.clear();
  const target=Object.values(data.scenarios).find((scenario)=>scenario.source_type==='housionna'&&scenario.import_id===importId&&scenario.transmitter?.name===txName)
    ||Object.values(data.scenarios).find((scenario)=>scenario.source_type==='housionna'&&scenario.import_id===importId);
  if(!target)throw new Error('The imported run was not present in the normalized viewer scene');
  activeScenario=target.name;populateSourceSelectors(importId,txName);setSourceControls('housionna');
  rfResultsStale=false;buildScenario({preserveView:true});syncSimulationControls(data.scenarios[activeScenario]);
  renderHousionnaMetadata(data.scenarios[activeScenario]);
  void restoreLatestHousionnaResults(activeScenario);
  await loadHousionnaCatalog();
}

// One import job, polled to completion. Shared by single imports and "Import all new runs".
async function runHousionnaImportJob(runId=null,onProgress=()=>{},{rebuildScene=true}={}) {
  const route=runId?'/api/housionna/import':'/api/housionna/import-latest';
  const body=rebuildScene?{run_id:runId}:{run_id:runId,rebuild_scene:false};
  const options=runId?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{method:'POST'};
  let job=(await apiJson(route,options)).body;
  while(job.status==='running') {
    onProgress(job);
    await new Promise((resolve)=>setTimeout(resolve,500));
    job=(await apiJson(`/api/housionna/jobs/${encodeURIComponent(job.job_id)}`)).body;
  }
  if(job.status!=='complete')throw new Error(job.error||job.message||'HOUSIONNA import failed');
  return job;
}
// A run is new when no import carries its source fingerprint (so a re-exported folder counts as new too).
function newHousionnaExports() {
  // Keyed by run id and content: two work items can export identical inputs and still both need importing.
  const known=new Set(housionnaImports.map((row)=>`${row.run_id}\n${row.source_sha256}`));
  return housionnaRuns.filter((row)=>row.status==='valid'&&!known.has(`${row.run_id}\n${row.source_sha256}`))
    .sort((a,b)=>String(a.run_id).localeCompare(String(b.run_id)));
}
function syncImportAllButton() {
  const count=newHousionnaExports().length,button=$('#importAllHousionna');
  button.textContent=count?`Import all new runs (${count})`:'All runs imported';
  button.disabled=housionnaImportBusy||count===0;
}
async function importAllNewHousionna() {
  if(housionnaImportBusy)return;
  const pending=newHousionnaExports();if(!pending.length){syncImportAllButton();return;}
  housionnaImportBusy=true;
  ['importLatestHousionna','reloadHousionna','importSelectedHousionna','importAllHousionna'].forEach((id)=>{$(`#${id}`).disabled=true;});
  const failed=[];let last=null;
  try {
    for(const [index,row] of pending.entries()) {
      const prefix=`Importing ${index+1} of ${pending.length}: ${row.run_id}`;
      setHousionnaStatus('running',`${prefix}…`);
      try {
        const job=await runHousionnaImportJob(row.run_id,(running)=>setHousionnaStatus('running',`${prefix} · ${running.message||'running'}`),{rebuildScene:false});
        last={job,runId:row.run_id,tx:row.transmitters?.[0]||'tx_0'};
      } catch(error) {failed.push(`${row.run_id} (${error.message||error})`);}
    }
    if(last) {
      // Rebuild the scene data once for the whole batch: re-importing the last run is a cache hit plus the rebuild.
      setHousionnaStatus('running',`Updating the viewer scene with ${pending.length-failed.length} new run${pending.length-failed.length===1?'':'s'}…`);
      await runHousionnaImportJob(last.runId);
      await refreshViewerScene(last.job.import_id,last.tx);
    }
    const done=pending.length-failed.length;
    setHousionnaStatus(failed.length?'failed':'complete',`Imported ${done} of ${pending.length} new run${pending.length===1?'':'s'}${failed.length?` · failed: ${failed.join('; ')}`:''}`);
  } catch(error) {
    setHousionnaStatus('failed',error.message||String(error));
  } finally {
    housionnaImportBusy=false;$('#importLatestHousionna').disabled=false;$('#reloadHousionna').disabled=false;
    $('#importSelectedHousionna').disabled=!housionnaRuns.some((row)=>row.status==='valid');
    syncImportAllButton();
  }
}

async function importHousionna(runId=null) {
  if(housionnaImportBusy)return;
  housionnaImportBusy=true;$('#importLatestHousionna').disabled=true;$('#reloadHousionna').disabled=true;
  setHousionnaStatus('running',runId?`Validating selected run ${runId}…`:'Discovering runs…');
  try {
    const job=await runHousionnaImportJob(runId,(running)=>setHousionnaStatus('running',running.message||'Import is running'));
    const available=housionnaRuns.find((row)=>row.run_id===job.run_id||row.run_id===runId);
    const currentTx=data.scenarios[activeScenario]?.transmitter?.name;
    const selected=available?.transmitters?.includes(currentTx)?currentTx:(available?.transmitters?.[0]||'tx_0');
    await refreshViewerScene(job.import_id,selected);
    setHousionnaStatus('complete',`${job.message} · ${job.run_metadata?.run_id||job.run_id} · ${Number(job.duration_seconds||0).toFixed(2)} s`);
  } catch(error) {
    setHousionnaStatus('failed',error.message||String(error));
  } finally {
    housionnaImportBusy=false;$('#importLatestHousionna').disabled=false;$('#reloadHousionna').disabled=false;
    $('#importSelectedHousionna').disabled=!housionnaRuns.some((row)=>row.status==='valid');
    syncImportAllButton();
  }
}

async function compareHousionnaRuns() {
  const output=$('#housionnaComparison');output.textContent='Checking frequency, geometry, devices, and measurement-triangle correspondence…';
  $('#compareHousionna').disabled=true;
  try {
    const {body}=await apiJson('/api/housionna/compare',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({
      reference_id:$('#compareReference').value,comparison_id:$('#compareRun').value,transmitter:$('#compareTx').value,
    })});
    const compatible=body.compatibility.status==='compatible';
    const map=body.radio_map.delta_statistics;
    const flags=body.compatibility;
    output.innerHTML=`<b>${compatible?"Metadata compatible":"Metadata differs"}</b><br>Frequency ${flags.same_frequency?"matches":"differs"} / geometry ${flags.same_scene_geometry?"matches":"differs"} / TX-RX ${flags.same_transmitter_configuration&&flags.same_receiver_configuration?"match":"differ"}<br>Materials ${flags.same_material_definitions?"match":"differ"} / solver ${flags.same_solver_settings?"matches":"differs"}<br><b>Radio map:</b> ${esc(body.radio_map.reason)}${body.radio_map.compatible&&map?`<br>${map.valid_cells.toLocaleString()} shared cells / mean delta ${Number(map.mean_delta_db).toFixed(2)} dB / mean absolute delta ${Number(map.mean_absolute_delta_db).toFixed(2)} dB / RMS ${Number(map.rms_delta_db).toFixed(2)} dB`:""}<br>${body.link_deltas.map((row)=>`${esc(row.receiver)}: ${row.path_count_reference} -> ${row.path_count_comparison} paths / coherent gain delta ${row.coherent_gain_delta_db==null?"-":`${Number(row.coherent_gain_delta_db).toFixed(2)} dB`} / strongest delay delta ${row.strongest_path_delay_delta_ns==null?"-":`${Number(row.strongest_path_delay_delta_ns).toFixed(3)} ns`} / spread delta ${row.delay_spread_delta_ns==null?"-":`${Number(row.delay_spread_delta_ns).toFixed(3)} ns`}`).join("<br>")}`;
  } catch(error) {output.textContent=`Comparison failed: ${error.message||error}`;}
  finally {updateCompareTxOptions();}
}

// The scene file lists HOUSIONNA scenarios as small stubs (scenario.stub). A run's full scenarios are
// fetched when it is selected; at most HOUSIONNA_LOADED_LIMIT runs stay loaded, older ones revert to stubs.
const HOUSIONNA_LOADED_LIMIT=4;
const housionnaStubs=new Map(),housionnaLoaded=new Map(),housionnaLoading=new Map();
function rememberHousionnaStubs() {
  housionnaStubs.clear();housionnaLoaded.clear();
  for(const [key,scenario] of Object.entries(data.scenarios))if(scenario?.stub)housionnaStubs.set(key,scenario);
}
function importScenarioKeys(importId) {
  return data.scenario_order.filter((key)=>data.scenarios[key]?.source_type==='housionna'&&data.scenarios[key].import_id===importId);
}
async function ensureHousionnaImport(importId) {
  const keys=importScenarioKeys(importId);
  if(!keys.length||keys.every((key)=>!data.scenarios[key].stub)){if(keys.length)housionnaLoaded.set(importId,performance.now());return;}
  if(!housionnaLoading.has(importId))housionnaLoading.set(importId,(async()=>{
    $('#housionnaImportStatus').textContent='Loading the selected run…';
    const {body}=await apiJson(importViewerUrl(importId));
    resolveViewerAssets(body);
    for(const key of body.scenario_order)if(data.scenarios[key])data.scenarios[key]=body.scenarios[key];
    housionnaLoaded.set(importId,performance.now());
    // Keep memory bounded: put the least recently used runs (never the one on screen) back to stubs.
    const activeImport=data.scenarios[activeScenario]?.import_id;
    for(const [id] of [...housionnaLoaded].sort((a,b)=>a[1]-b[1])) {
      if(housionnaLoaded.size<=HOUSIONNA_LOADED_LIMIT)break;
      if(id===importId||id===activeImport)continue;
      for(const key of importScenarioKeys(id))if(housionnaStubs.has(key))data.scenarios[key]=housionnaStubs.get(key);
      housionnaLoaded.delete(id);
    }
    $('#housionnaImportStatus').textContent=STATIC_SITE?'Published results. This public view is read-only.':'';
  })().finally(()=>housionnaLoading.delete(importId)));
  await housionnaLoading.get(importId);
}

function resolveViewerAssets(viewerData) {
  for(const scenario of Object.values(viewerData.scenarios)) {
    if(scenario.geometry_ref) {
      const geometry=viewerData.assets?.geometries?.[scenario.geometry_ref];
      if(!geometry)throw new Error(`Viewer geometry asset is missing: ${scenario.geometry_ref}`);
      scenario.geometry=geometry;
    }
    for(const surface of scenario.radio_map?.surfaces||[]) {
      if(surface.mesh_ref) {
        const mesh=viewerData.assets?.meshes?.[surface.mesh_ref];
        if(!mesh)throw new Error(`Viewer radio-map mesh asset is missing: ${surface.mesh_ref}`);
        surface.mesh=mesh;
      }
    }
  }
}

function wireUI() {
  $('#sceneSourceSelect').addEventListener('change',(event)=>chooseSceneSource(event.target.value));
  $('#scenarioSelect').addEventListener('change',(event)=>{ activeScenario=event.target.value;rfResultsStale=false;buildScenario();syncSimulationControls(data.scenarios[activeScenario]); });
  $('#housionnaRunSelect').addEventListener('change',async(event)=>{
    const group=housionnaGroups().find((item)=>item.import_id===event.target.value);if(!group)return;
    const currentTx=data.scenarios[activeScenario]?.transmitter?.name;
    try {await ensureHousionnaImport(group.import_id);}
    catch(error){setHousionnaStatus('failed',`Could not load ${group.run_id}: ${error.message||error}`);return;}
    if($('#housionnaRunSelect').value!==group.import_id)return;  // a newer selection won the race
    const key=populateHousionnaTxSelect(group,currentTx);if(!key)return;
    activeScenario=key;rfResultsStale=false;buildScenario({preserveView:true});syncSimulationControls(data.scenarios[activeScenario]);renderHousionnaMetadata(data.scenarios[activeScenario]);void restoreLatestHousionnaResults(activeScenario);
  });
  $('#housionnaOlderRun').addEventListener('click',()=>stepHousionnaRun(-1));
  ['seriesMetric','seriesAxis'].forEach((id)=>$(`#${id}`).addEventListener('change',()=>renderRunSeries(data.scenarios[activeScenario])));
  // Redraw at the new width when a side panel is resized.
  let seriesWidth=0;
  new ResizeObserver(([entry])=>{const width=Math.round(entry.contentRect.width);
    if(width&&Math.abs(width-seriesWidth)>4){seriesWidth=width;renderRunSeries(data.scenarios[activeScenario]);}}).observe($('#seriesChart'));
  $('#housionnaNewerRun').addEventListener('click',()=>stepHousionnaRun(1));
  $('#housionnaTxSelect').addEventListener('change',async(event)=>{
    if(!data.scenarios[event.target.value])return;
    try {await ensureHousionnaImport(data.scenarios[event.target.value].import_id);}
    catch(error){setHousionnaStatus('failed',error.message||String(error));return;}
    activeScenario=event.target.value;rfResultsStale=false;buildScenario({preserveView:true});syncSimulationControls(data.scenarios[activeScenario]);renderHousionnaMetadata(data.scenarios[activeScenario]);void restoreLatestHousionnaResults(activeScenario);
  });
  $('#housionnaResultVersion').addEventListener('change',(event)=>{
    const scenario=data.scenarios[activeScenario],mode=event.target.value;
    if(scenario?.source_type!=='housionna')return;
    const snapshot=mode==='latest'?housionnaLatestResults.get(activeScenario):housionnaOriginalResults.get(activeScenario);
    if(!snapshot){event.target.value='original';return;}
    applyHousionnaSnapshot(scenario,snapshot);housionnaDisplayedVersions.set(activeScenario,mode);
    buildScenario({preserveView:true});syncSimulationControls(scenario);
    housionnaCompletedFingerprints.set(activeScenario,mode==='latest'?(snapshot.path_fingerprint||housionnaCompletedFingerprints.get(activeScenario)):housionnaSettingsFingerprint());markResultsStale();refreshPaths();
    setRunStatus('current',mode==='original'?'Original HOUSIONNA paths and radio map are selected.':'Latest Sionna rerun is selected; its map is current only if it has been recalculated.');
  });
  $('#resetHousionnaTx').addEventListener('click',()=>{
    const scenario=data.scenarios[activeScenario],baseline=housionnaOriginalResults.get(activeScenario);
    if(scenario?.source_type!=='housionna'||!baseline)return;
    scenario.transmitter=structuredClone(baseline.transmitter);
    setTransmitterPositionFields(scenario.transmitter.position_m);
    $('#txYaw').value=(Number(scenario.transmitter.orientation_rad?.[0]||0)*180/Math.PI).toFixed(1);
    if(txGroup){txGroup.position.copy(vec(scenario.transmitter.position_m));txGroup.rotation.z=Number(scenario.transmitter.orientation_rad?.[0]||0);}
    updateTxWarning();markResultsStale();
  });
  $('#runRadioMapBtn').addEventListener('click',runHousionnaRadioMap);
  $('#importLatestHousionna').addEventListener('click',()=>importHousionna());
  $('#importAllHousionna').addEventListener('click',importAllNewHousionna);
  $('#importSelectedHousionna').addEventListener('click',()=>{
    const runId=$('#housionnaExportSelect').value;
    if(runId)importHousionna(runId);
  });
  $('#reloadHousionna').addEventListener('click',()=>{
    const runId=data.scenarios[activeScenario]?.run_metadata?.run_id||data.scenarios[activeScenario]?.provenance?.run_folder_name;
    if(runId)importHousionna(runId);else setHousionnaStatus('failed','Select an imported HOUSIONNA run first.');
  });
  $('#compareReference').addEventListener('change',updateCompareTxOptions);
  $('#compareRun').addEventListener('change',updateCompareTxOptions);
  $('#compareHousionna').addEventListener('click',compareHousionnaRuns);
  $('#simulationScenario').addEventListener('change',()=>{updateTxWarning();markResultsStale();});
  ['frequencyGHz','txX','txY','txZ','txYaw','solverDepth','losToggle','specularToggle','diffuseToggle','refractionToggle','diffractionToggle','mapQuality','pathSamples'].forEach(id=>{
    const changed=()=>{
      if(id==='frequencyGHz'&&$('#frequencyPreset').value!==$('#frequencyGHz').value)$('#frequencyPreset').value='';
      if(['txX','txY','txZ','txYaw'].includes(id))updateTransmitterFromFields();
      updateTxWarning();
      if(id==='mapQuality'&&data?.scenarios?.[activeScenario]?.source_type==='housionna'){
        housionnaMapQualities.set(activeScenario,$('#mapQuality').value);
        setSimulationInputsDisabled(false);
        if(!rfResultsStale)setRunStatus('stale','Radio-map quality changed. Recalculate the map to use this sample level.');
      } else markResultsStale();
    };
    $(`#${id}`).addEventListener('input',changed);
    $(`#${id}`).addEventListener('change',changed);
  });
  $('#housionnaReceiverSelection').addEventListener('change',markResultsStale);
  $('#frequencyPreset').addEventListener('change',(event)=>{if(event.target.value){$('#frequencyGHz').value=event.target.value;updateTxWarning();markResultsStale();}});
  $('#runSimulationBtn').addEventListener('click',runSimulation);
  $('#simulationHistory').addEventListener('click',(event)=>{const button=event.target.closest('[data-run-id]');if(button&&!button.disabled)loadHistoryResult(button.dataset.runId);});
  window.addEventListener('keydown',(event)=>{
    if(event.ctrlKey&&event.key==='Enter'&&!event.repeat&&!/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName||'')) {event.preventDefault();runSimulation();}
  });
  document.querySelectorAll('[data-layer]').forEach((element)=>element.addEventListener('change',()=>{ setLayerVisibility(); if(element.dataset.layer==='map') updateMap(); }));
  $('#labelsToggle').addEventListener('change',setLayerVisibility);
  $('#differenceToggle').addEventListener('change',updateMap);
  $('#mapLevel').addEventListener('change',updateMap);
  $('#housionnaMapMode').addEventListener('change',updateMap);
  $('#mapOpacity').addEventListener('input',(event)=>{ $('#opacityValue').textContent=`${event.target.value}%`; setRadioMapOpacity(Number(event.target.value)/100); });
  $('#mapHeight').addEventListener('input',(event)=>{ $('#heightValue').textContent=`${Number(event.target.value).toFixed(2)} m`; if(heatMesh) { const map=data.scenarios[activeScenario].radio_map; if(map.surfaces?.length)return; heatMesh.position.z=Number(event.target.value); } });
  $('#receiverSelect').addEventListener('change',(event)=>{ activeReceiver=event.target.value; refreshReceiverMetrics(data.scenarios[activeScenario]); });
  $('#pathsToggle').addEventListener('change',()=>{ setLayerVisibility(); refreshPaths(); });
  $('#pathFilter').addEventListener('change',refreshPaths);
  $('#cameraSelect').addEventListener('change',(event)=>focusScene(event.target.value));
  $('#housionnaGeometryMode').addEventListener('change',()=>{const scenario=data.scenarios[activeScenario];applyHousionnaGeometryMode(scenario);renderDiagnostics(scenario,{plants:0,leaves:0},scenario.geometry.objects.reduce((sum,item)=>sum+(item.triangle_count??item.faces?.length??0),0));});
  $('#deviceDisplayMode').addEventListener('change',()=>{buildDeviceMarkers(data.scenarios[activeScenario]);setLayerVisibility();});
  $('#deviceLabelMode').addEventListener('change',setLayerVisibility);
  ['measurementMeshToggle','coordinateDiagnosticToggle','sceneBoundsToggle'].forEach((id)=>$(`#${id}`).addEventListener('change',setLayerVisibility));
  $('#captureBtn').addEventListener('click',captureView);
  const workspace=$('.workspace');
  const layersButton=$('#layersBtn');
  const inspectorButton=$('#inspectorBtn');
  if(matchMedia('(max-width: 900px)').matches) {
    workspace.classList.add('inspector-hidden');
    inspectorButton.setAttribute('aria-expanded','false');
  }
  layersButton.addEventListener('click',()=>{
    if(matchMedia('(max-width: 620px)').matches) {
      const open=!$('.left-panel').classList.contains('open');
      $('.left-panel').classList.toggle('open',open);
      workspace.classList.toggle('layers-hidden',!open);
      layersButton.setAttribute('aria-expanded',String(open));
    } else {
      const hidden=workspace.classList.toggle('layers-hidden');
      layersButton.setAttribute('aria-expanded',String(!hidden));
    }
  });
  inspectorButton.addEventListener('click',()=>{
    const hidden=workspace.classList.toggle('inspector-hidden');
    inspectorButton.setAttribute('aria-expanded',String(!hidden));
  });
  // Side panels can be swiped or dragged open/closed by their inner edge; the 3D scene takes whatever width is left.
  const desktopLayout=()=>matchMedia('(min-width: 901px)').matches;
  const panelWidths={left:286,right:298};
  let liveWidth=null;
  const applyLayout=()=>{
    if(!desktopLayout()){workspace.style.gridTemplateColumns='';return;}
    const width=(side)=>liveWidth&&liveWidth.side===side?liveWidth.width:panelWidths[side];
    const leftHidden=workspace.classList.contains('layers-hidden'),rightHidden=workspace.classList.contains('inspector-hidden');
    const cols=[];
    if(!leftHidden)cols.push(`${width('left')}px`);
    cols.push('minmax(300px,1fr)');
    if(!rightHidden)cols.push(`${width('right')}px`);
    workspace.style.gridTemplateColumns=cols.join(' ');
    // Grips sit on the scene side of each panel edge, so they never overlap the panel's scrollbar.
    const leftGrip=workspace.querySelector('.panel-handle[data-side="left"]');
    const rightGrip=workspace.querySelector('.panel-handle[data-side="right"]');
    if(leftGrip)leftGrip.style.left=`${leftHidden?0:width('left')}px`;
    if(rightGrip)rightGrip.style.right=`${rightHidden?0:width('right')}px`;
  };
  [['left','layers-hidden',layersButton],['right','inspector-hidden',inspectorButton]].forEach(([side,hiddenClass,button])=>{
    const handle=document.createElement('div');
    handle.className='panel-handle';
    handle.dataset.side=side;
    handle.tabIndex=0;
    handle.setAttribute('role','separator');
    handle.setAttribute('aria-orientation','vertical');
    handle.setAttribute('aria-label',side==='left'?'Resize layers panel':'Resize inspector panel');
    workspace.appendChild(handle);
    const setHidden=(on)=>{workspace.classList.toggle(hiddenClass,on);button.setAttribute('aria-expanded',String(!on));};
    const sign=side==='left'?1:-1;
    handle.addEventListener('pointerdown',(e)=>{
      if(!desktopLayout())return;
      handle.setPointerCapture(e.pointerId);
      const startX=e.clientX,startW=workspace.classList.contains(hiddenClass)?0:panelWidths[side];
      let lastX=e.clientX,lastT=performance.now(),speed=0;
      handle.onpointermove=(ev)=>{
        const now=performance.now();
        if(now>lastT)speed=(ev.clientX-lastX)/(now-lastT);
        lastX=ev.clientX;lastT=now;
        liveWidth={side,width:Math.max(0,Math.min(520,startW+sign*(ev.clientX-startX)))};
        applyLayout();
      };
      const finish=()=>{
        handle.onpointermove=null;
        const w=liveWidth?liveWidth.width:startW;
        liveWidth=null;
        const flickOpen=sign*speed>0.6,flickClose=sign*speed<-0.6;
        const open=flickOpen||(!flickClose&&w>=140);
        if(open)panelWidths[side]=Math.max(200,w);
        setHidden(!open);
        applyLayout();
      };
      handle.onpointerup=finish;
      handle.onpointercancel=finish;
    });
    handle.addEventListener('keydown',(e)=>{
      if(!desktopLayout())return;
      const grow=side==='left'?'ArrowRight':'ArrowLeft';
      if(e.key!==grow&&e.key!==(side==='left'?'ArrowLeft':'ArrowRight'))return;
      e.preventDefault();
      if(workspace.classList.contains(hiddenClass)){if(e.key===grow)setHidden(false);}
      else panelWidths[side]=Math.max(200,Math.min(520,panelWidths[side]+(e.key===grow?16:-16)));
      applyLayout();
    });
  });
  new MutationObserver(applyLayout).observe(workspace,{attributes:true,attributeFilter:['class']});
  addEventListener('resize',applyLayout);
  applyLayout();
  $('#diagnosticsBtn').addEventListener('click',()=>$('#diagnostics').classList.toggle('hidden'));
  $('#playPathBtn').addEventListener('click',()=>{ if(reducedMotion||!pulseCurve) return; pulseRunning=!pulseRunning; pulseStarted=performance.now(); pulseMesh.visible=pulseRunning; $('#playPathBtn').textContent=pulseRunning?'Pause pulse':'Play pulse'; });
}

async function start() {
  try {
    data=(await apiJson(SCENE_URL)).body;
    if(data.schema_version!==1||!data.scenarios) throw new Error('Unsupported viewer scene data schema');
    resolveViewerAssets(data);rememberHousionnaStubs();
    activeScenario=data.featured_scenario||'current';
    if(data.scenarios[activeScenario]?.stub) {
      try {await ensureHousionnaImport(data.scenarios[activeScenario].import_id);}
      catch(error) {
        // The scene file can list an import that has since been removed: open the built-in scene instead of failing.
        console.warn('Featured HOUSIONNA run could not be loaded; opening the built-in scene',error);
        activeScenario=data.scenario_order.find((key)=>data.scenarios[key]?.source_type!=='housionna')||activeScenario;
      }
    }
    const initialScenario=data.scenarios[activeScenario];
    populateSourceSelectors(initialScenario?.import_id,initialScenario?.transmitter?.name);
    const initialSource=initialScenario?.source_type==='housionna'?'housionna':'builtin';
    setSourceControls(initialSource);
    if(initialSource==='housionna')renderHousionnaMetadata(initialScenario);
    $('#scenarioSelect').value=activeScenario;
    initRenderer(); addPulseMesh(); wireUI();
    buildScenario();
    syncSimulationControls(data.scenarios[activeScenario]);
    $('#sceneLoading').remove();
    if(STATIC_SITE) {
      const runs=housionnaGroups().length;
      setHousionnaStatus('ready',`Published results · ${runs} run${runs===1?'':'s'}. This public view is read-only.`);
      return;
    }
    loadApiStatus();
    await loadHousionnaCatalog();
    await restoreLatestHousionnaResults(activeScenario);
    await reconnectHousionnaJob();
  } catch(error) { showError(error); console.error('3D viewer failed to initialize',error); }
}

start();
