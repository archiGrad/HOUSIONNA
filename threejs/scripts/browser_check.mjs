// Isolated local Chromium pass; uses a fresh profile, never a user's browser session.
import { spawn } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import os from 'node:os';
import { mkdtemp,rm } from 'node:fs/promises';

const url=process.argv[2]||'http://127.0.0.1:8765/digital-twin/';
const output=path.resolve(process.argv[3]||'outputs/performance_refinement/browser');
const mode=process.argv[4]||'smoke';
await mkdir(output,{recursive:true});
const profile=await mkdtemp(path.join(os.tmpdir(),'hyropa-browser-'));
const browser=spawn('C:/Program Files/Google/Chrome/Application/chrome.exe',[
  '--headless=new','--no-first-run','--no-default-browser-check','--remote-debugging-pipe',
  `--user-data-dir=${profile}`,'--window-size=1440,1100',
  '--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader','--disable-background-networking','--no-proxy-server','about:blank'
],{windowsHide:true,stdio:['ignore','ignore','pipe','pipe','pipe']});
let browserLog='';browser.stderr.on('data',data=>{browserLog=(browserLog+data.toString()).slice(-20000);});
let socket;let nextId=0;const pending=new Map(),errors=[],network=[],responses=new Map();
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function send(method,params={}){
  const id=++nextId;
  return new Promise((resolve,reject)=>{
    pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params,...(socket.sessionId&&!method.startsWith('Browser.')&&!method.startsWith('Target.')?{sessionId:socket.sessionId}:{})}));
    const timer=setTimeout(()=>{if(pending.has(id)){pending.delete(id);reject(new Error(`CDP timeout: ${method}`));}},30000);
    pending.get(id).timer=timer;
  });
}
async function evaluate(expression){
  const value=await send('Runtime.evaluate',{expression,awaitPromise:true,returnByValue:true});
  if(value.exceptionDetails)throw new Error(JSON.stringify(value.exceptionDetails));
  return value.result.value;
}
async function waitFor(expression,timeout=60000){
  const start=Date.now();
  while(Date.now()-start<timeout){if(await evaluate(expression))return;await sleep(150);}
  throw new Error(`UI wait expired: ${expression}`);
}
async function screenshot(name){
  const result=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true});
  await writeFile(path.join(output,name),Buffer.from(result.data,'base64'));
}
async function click(selector){
  const position=await evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});if(!e||e.disabled)throw Error('Unavailable control');e.scrollIntoView({block:'center'});const r=e.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);
  await send('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',clickCount:1,...position});
  await send('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',clickCount:1,...position});
}
try{
  socket={send:data=>browser.stdio[3].write(data+'\0'),close:()=>{}};
  let buffered='';
  function received(msg){
    if(msg.id){const call=pending.get(msg.id);if(call){clearTimeout(call.timer);pending.delete(msg.id);msg.error?call.reject(new Error(JSON.stringify(msg.error))):call.resolve(msg.result)}return;}
    if(msg.method==='Runtime.exceptionThrown')errors.push(msg.params.exceptionDetails);
    if(msg.method==='Network.responseReceived')responses.set(msg.params.requestId,msg.params.response);
    if(msg.method==='Runtime.consoleAPICalled'&&msg.params.type==='error')errors.push({console:msg.params.args.map(a=>a.value||a.description)});
    if(msg.method==='Network.loadingFinished'){
      const response=responses.get(msg.params.requestId);
      if(response)network.push({url:response.url,status:response.status,encoded_bytes:msg.params.encodedDataLength});
    }
  }
  browser.stdio[4].on('data',data=>{buffered+=data.toString();let end;while((end=buffered.indexOf('\0'))>=0){const part=buffered.slice(0,end);buffered=buffered.slice(end+1);if(part)received(JSON.parse(part));}});
  const target=await send('Target.createTarget',{url:'about:blank'});
  const attached=await send('Target.attachToTarget',{targetId:target.targetId,flatten:true});
  socket.sessionId=attached.sessionId;
  await send('Page.enable');await send('Runtime.enable');await send('Network.enable');await send('Performance.enable');
  const loadedAt=performance.now();await send('Page.navigate',{url});
  await waitFor(`document.querySelector('.webgl-canvas')&&!document.querySelector('#sceneLoading')`);
  const loadedMs=performance.now()-loadedAt;
  await sleep(1500);
  await screenshot('loaded.png');
  const initial=await evaluate(`({scene:document.querySelector('#sceneMeta').textContent,source:document.querySelector('#sceneSourceSelect').value,run:document.querySelector('#housionnaRunSelect').value,tx:document.querySelector('#housionnaTxSelect').value,status:document.querySelector('#simulationMessage').textContent})`);
  const report={mode,url,initial,load_to_canvas_ms:loadedMs,errors,network};
  if(mode==='map'||mode==='baseline'||mode==='regression'||mode==='visual'){
    await waitFor(`!document.querySelector('#housionnaExportSelect').textContent.includes('No discovered')`,25000);
    await waitFor(`!document.querySelector('#runRadioMapBtn').disabled`,15000);
    if(mode==='regression')await evaluate(`(()=>{const e=document.querySelector('#housionnaResultVersion');e.value='original';e.dispatchEvent(new Event('change',{bubbles:true}))})()`);
    await evaluate(`(()=>{const e=document.querySelector('#mapQuality');e.value='low';e.dispatchEvent(new Event('change',{bubbles:true}))})()`);
    const clickAt=performance.now();await click('#runRadioMapBtn');
    try{await waitFor(`!document.querySelector('#runRadioMapBtn').disabled&&!document.querySelector('#rfRunStatus').classList.contains('running')`,140000);}catch(error){report.wait_error=error.message;}
    await evaluate(`new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))`);
    report.click_to_visible_ms=performance.now()-clickAt;
    report.final=await evaluate(`({status:document.querySelector('#rfRunStatus').textContent,message:document.querySelector('#simulationMessage').textContent,error:document.querySelector('#simulationError').textContent,legend:document.querySelector('#mapLegend').textContent,diagnostics:document.querySelector('#simulationDiagnosticsData')?.textContent})`);
    await screenshot('map-result.png');
    if(report.final.status==='FAILED'||report.wait_error)throw Error('Map did not complete: '+JSON.stringify(report.final));
  }
  if(mode==='regression'){
    report.additional=[];
    const setValue=async(selector,value)=>evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('change',{bubbles:true}))})()`);
    const txX=await evaluate(`Number(document.querySelector('#txX').value)`);
    await setValue('#txX',String(txX+0.111));
    await setValue('#txYaw','23');
    for(const label of ['modified_tx_low','exact_repeat']){
      const start=performance.now();await click('#runRadioMapBtn');
      await waitFor(`!document.querySelector('#runRadioMapBtn').disabled&&!document.querySelector('#rfRunStatus').classList.contains('running')`,140000);
      const state=await evaluate(`({status:document.querySelector('#rfRunStatus').textContent,message:document.querySelector('#simulationMessage').textContent,diagnostics:document.querySelector('#simulationDiagnosticsData').textContent})`);
      if(state.status==='FAILED'){
        await waitFor(`document.querySelector('#simulationDiagnosticsData').textContent.includes('diagnostic_id')`,15000);
        const diagnostic=await evaluate(`JSON.parse(document.querySelector('#simulationDiagnosticsData').textContent)`);
        report.additional.push({case:label,status:'failed',message:state.message,diagnostics:diagnostic,controls_recovered:true});break;
      }
      const diagnostic=JSON.parse(state.diagnostics);
      if(Math.abs(diagnostic.execution.request.tx_orientation[0]-23*Math.PI/180)>1e-7||diagnostic.execution.request.tx_orientation[2]!==0)throw Error('Yaw did not reach Sionna in its Z-axis slot');
      report.additional.push({case:label,elapsed_ms:performance.now()-start,cache_hit:diagnostic.cache_hit,client_ms:diagnostic.client_ms});
    }
    await screenshot('modified-map.png');
    const beforeReload=await evaluate(`JSON.parse(document.querySelector('#simulationDiagnosticsData').textContent).job_id`);
    await send('Page.reload');await waitFor(`document.querySelector('.webgl-canvas')&&!document.querySelector('#sceneLoading')`);
    await waitFor(`document.querySelector('#mapLegend').textContent.includes('SIONNA RT')`,15000);
    const restored=await evaluate(`({txX:document.querySelector('#txX').value,yaw:document.querySelector('#txYaw').value,message:document.querySelector('#simulationMessage').textContent,map:document.querySelector('#mapLegend').textContent})`);
    if(report.additional.every(r=>r.status!=='failed')&&(Math.abs(Number(restored.txX)-(txX+.111))>1e-6||Number(restored.yaw)!==23))throw Error('Changed map inputs were lost on refresh');
    report.refresh={run_id:beforeReload,...restored};
    const largeRun=await evaluate(`Array.from(document.querySelector('#housionnaRunSelect').options).find(e=>e.textContent.includes('20261007_195457Z'))?.value`);
    if(!largeRun)throw Error('Large import is missing');
    const switches=[];
    for(let i=0;i<3;i++){
      const start=performance.now();await setValue('#housionnaRunSelect',largeRun);
      const txCount=await evaluate(`document.querySelector('#housionnaTxSelect').options.length`);
      if(txCount!==102)throw Error('Expected 102 TXs, found '+txCount);
      const last=await evaluate(`document.querySelector('#housionnaTxSelect').options[101].value`);
      await setValue('#housionnaTxSelect',last);
      switches.push({run:largeRun,tx_count:txCount,elapsed_ms:performance.now()-start});
      await setValue('#housionnaRunSelect',initial.run);
    }
    await setValue('#housionnaRunSelect',largeRun);await sleep(500);
    await screenshot('large-102-tx.png');report.switches=switches;
    const postsBefore=network.filter(r=>r.url.endsWith('/api/housionna/radio-map')||r.url.endsWith('/api/housionna/simulate')).length;
    await setValue('#cameraSelect','top');
    await evaluate(`(()=>{const e=document.querySelector('[data-layer="map"]');e.checked=!e.checked;e.dispatchEvent(new Event('change',{bubbles:true}));e.checked=!e.checked;e.dispatchEvent(new Event('change',{bubbles:true}))})()`);
    await sleep(500);
    const postsAfter=network.filter(r=>r.url.endsWith('/api/housionna/radio-map')||r.url.endsWith('/api/housionna/simulate')).length;
    if(postsAfter!==postsBefore)throw Error('Camera/layer action launched an RF request');
    report.camera_and_layers_trigger_no_rf_request=true;
  }
  if(mode==='visual'){
    const setValue=async(selector,value)=>evaluate(`(()=>{const e=document.querySelector(${JSON.stringify(selector)});e.value=${JSON.stringify(value)};e.dispatchEvent(new Event('change',{bubbles:true}))})()`);
    const postsBefore=network.filter(r=>r.url.endsWith('/api/housionna/radio-map')||r.url.endsWith('/api/housionna/simulate')).length;
    await setValue('#housionnaMapMode','difference');await sleep(300);await screenshot('difference-map.png');
    await setValue('#housionnaMapMode','selected');
    await send('Page.reload');await waitFor(`document.querySelector('#mapLegend')?.textContent.includes('SIONNA RT')`,30000);
    report.completed_refresh=await evaluate(`({map:document.querySelector('#mapLegend').textContent,txX:document.querySelector('#txX').value})`);
    const largeRun=await evaluate(`Array.from(document.querySelector('#housionnaRunSelect').options).find(e=>e.textContent.includes('20261007_195457Z'))?.value`);
    await setValue('#housionnaRunSelect',largeRun);
    report.large_tx_count=await evaluate(`document.querySelector('#housionnaTxSelect').options.length`);
    if(report.large_tx_count!==102)throw Error('102-TX import failed');
    const last=await evaluate(`document.querySelector('#housionnaTxSelect').options[101].value`);
    await setValue('#housionnaTxSelect',last);await setValue('#cameraSelect','top');await sleep(300);
    const selected=await evaluate(`({heading:document.querySelector('#scenarioHeading').textContent,details:document.querySelector('#detailBody').textContent,labels:Array.from(document.querySelectorAll('.tx-label')).map(e=>e.textContent)})`);
    if(!selected.heading.includes('tx_101')||!selected.details.includes('Selected TXtx_101')||selected.labels.length!==1||selected.labels[0]!=='tx_101')throw Error('Selected TX/inspector/marker mismatch: '+JSON.stringify(selected));
    report.large_selected_tx=selected;await screenshot('large-last-tx.png');
    await setValue('#sceneSourceSelect','builtin');report.builtin=[];
    for(const name of ['farm_empty','farm_proxy','farm_dense']){
      await setValue('#scenarioSelect',name);await setValue('#cameraSelect','isometric');await sleep(300);
      report.builtin.push(await evaluate(`({name:${JSON.stringify(name)},scene:document.querySelector('#sceneMeta').textContent,semantics:document.querySelector('#legendSemantics').textContent})`));
      await screenshot(name+'.png');
    }
    const postsAfter=network.filter(r=>r.url.endsWith('/api/housionna/radio-map')||r.url.endsWith('/api/housionna/simulate')).length;
    if(postsBefore!==postsAfter)throw Error('Inspection action launched an RF calculation');
    report.inspection_triggers_no_rf_request=true;
  }
  report.memory=await send('Performance.getMetrics');
  report.errors=errors;report.network=network;
  await writeFile(path.join(output,'browser-report.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify({mode,load_ms:loadedMs,click_ms:report.click_to_visible_ms,status:report.final?.status,error_count:errors.length,initial}));
}catch(error){
  let state;
  try{state=await evaluate(`({status:document.querySelector('#rfRunStatus')?.textContent,message:document.querySelector('#simulationMessage')?.textContent,error:document.querySelector('#simulationError')?.textContent,disabled:document.querySelector('#runRadioMapBtn')?.disabled})`);await screenshot('failure.png');}catch{}
  await writeFile(path.join(output,'failure.json'),JSON.stringify({error:error.message,state,errors,network},null,2));
  throw error;
}finally{
  await writeFile(path.join(output,'browser-process.log'),browserLog);
  if(socket){try{await send('Browser.close')}catch{}socket.close();}
  browser.kill();
  await rm(profile,{recursive:true,force:true,maxRetries:3}).catch(()=>{});
}
