// Dedicated Android QA device only; real UI/OS probes against the private fixture.
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import { resolve, join } from 'node:path';
import { connect } from './desktop-cdp.mjs';

const phase = process.argv[2];
assert(['query', 'modal-open', 'modal-inspect', 'modal-restore', 'keyboard', 'snapshot'].includes(phase));
const directory = resolve('.artifacts/mobile/native-round30');
await mkdir(directory, { recursive: true });
const device = 'emulator-5556';
const adb = (...args) => {
  const value = spawnSync('E:/Android_Studio_SDK/platform-tools/adb.exe', ['-s', device, ...args]);
  if (value.status !== 0) throw new Error(`Dedicated adb command failed: ${value.stderr}`);
  return value.stdout;
};
const client = await connect(9224, 'mobile');
const evidence = {phase, timestamp:new Date().toISOString(), device, scope:'private_synthetic_fixture_real_android_ui'};
const wait = async expression => {
  for(let attempt=0;attempt<150;attempt++) {
    if(await client.evaluate(expression)) return;
    await new Promise(r=>setTimeout(r,100));
  }
  throw new Error(`UI condition did not arrive: ${expression}`);
};
try {
  if(['query','modal-open','keyboard'].includes(phase)) await wait(`!!document.querySelector('.mobile-connection.ready')&&!!document.querySelector('.app-shell')`);
  if (phase === 'query') {
    await client.evaluate(`Array.from(document.querySelectorAll('.mobile-nav button')).find(x=>x.textContent==='轮胎查询').click();true`);
    await wait(`!!document.querySelector('input[placeholder="例如 225/45 R18"]')`);
    await client.evaluate(`(()=>{
      const input=document.querySelector('input[placeholder="例如 225/45 R18"]');
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'265/40R20');
      input.dispatchEvent(new Event('input',{bubbles:true}));
      return true;
    })()`);
    await client.evaluate(`document.querySelector('.query-submit').click();true`);
    await wait(`document.querySelectorAll('.variant-card').length===6`);
    evidence.query=await client.evaluate(`({cards:document.querySelectorAll('.variant-card').length,
      text:document.querySelector('.results-section')?.innerText||document.body.innerText,
      canary:typeof window.filterCanary,width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth})`);
    assert.equal(evidence.query.cards,6);assert.equal(evidence.query.width,evidence.query.scroll);
    assert.equal(evidence.query.canary,'undefined');
    const opened=await client.evaluate(`(()=>{const b=Array.from(document.querySelectorAll('.variant-card button')).find(x=>x.textContent.includes('查看证据'));if(!b)return false;b.click();return true})()`);
    assert(opened);
    await wait(`document.querySelector('.evidence-panel')?.innerText.includes('SHA-256')`);
    evidence.evidence=await client.evaluate(`({text:document.querySelector('.evidence-panel').innerText,dialogs:Array.from(document.querySelectorAll('dialog[open]')).map(x=>x.className)})`);
    adb('shell','input','keyevent','4');
    await new Promise(r=>setTimeout(r,500));
    evidence.afterBack=await client.evaluate(`({dialogs:Array.from(document.querySelectorAll('dialog[open]')).map(x=>x.className),ready:!!document.querySelector('.mobile-connection.ready'),evidenceCleared:document.querySelector('.evidence-panel')?.innerText.includes('把结论放回来源中')})`);
    assert.equal(evidence.afterBack.ready,true);
    assert.equal(evidence.afterBack.evidenceCleared,true);
  }
  if (phase === 'modal-open') {
    await client.evaluate(`Array.from(document.querySelectorAll('.mobile-nav button')).find(x=>x.textContent.includes('来源与证据')).click();true`);
    await wait(`!!document.querySelector('[data-recall-entry]')`);
    await client.evaluate(`document.querySelector('[data-recall-entry]').click();true`);
    await wait(`!!document.querySelector('dialog[open]')`);
    await client.evaluate(`(()=>{const dialog=document.querySelector('.recall-dialog');window.uiQaOriginalRoot=document.querySelector('.app-shell');window.uiQaModalDraft=Array.from(dialog.querySelectorAll('input,select,textarea')).map(x=>({name:x.name,value:x.value}));return true})()`);
    evidence.modal=await client.evaluate(`Array.from(document.querySelectorAll('dialog[open]')).map(x=>({class:x.className,modal:x.matches(':modal')}))`);
  }
  if (phase === 'modal-inspect') {
    await wait(`!!document.querySelector('.mobile-connection.failed')`);
    evidence.modal=await client.evaluate(`(()=>{const b=document.querySelector('.mobile-connect-screen button');const r=b?.getBoundingClientRect();const hit=r?document.elementFromPoint(r.x+r.width/2,r.y+r.height/2):null;return {dialogs:Array.from(document.querySelectorAll('dialog[open]')).map(x=>({class:x.className,modal:x.matches(':modal'),display:getComputedStyle(x).display})),retry:b?.innerText,hit:hit?.tagName,hitClass:hit?.className,retryReceivesPointer:hit===b||b?.contains(hit),text:document.querySelector('.mobile-connect-screen')?.innerText}})()`);
  }
  if (phase === 'modal-restore') {
    const before=await (await fetch('http://127.0.0.1:8003/fixture/state')).json();
    const point=await client.evaluate(`(()=>{const b=document.querySelector('.mobile-connect-screen button');const r=b.getBoundingClientRect();const hit=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);if(hit!==b&&!b.contains(hit))throw new Error('Retry remains blocked');return{x:r.x+r.width/2,y:r.y+r.height/2}})()`);
    await client.call('Input.dispatchMouseEvent',{type:'mousePressed',...point,button:'left',clickCount:1});
    await client.call('Input.dispatchMouseEvent',{type:'mouseReleased',...point,button:'left',clickCount:1});
    await wait(`!!document.querySelector('.mobile-connection.ready')`);
    await wait(`document.querySelector('.recall-dialog')?.matches(':modal')`);
    evidence.restored=await client.evaluate(`({sameRoot:window.uiQaOriginalRoot===document.querySelector('.app-shell'),draft:Array.from(document.querySelector('.recall-dialog').querySelectorAll('input,select,textarea')).map(x=>({name:x.name,value:x.value})),beforeDraft:window.uiQaModalDraft,modal:document.querySelector('.recall-dialog').matches(':modal'),focused:document.activeElement?.tagName})`);
    assert.equal(evidence.restored.sameRoot,true);assert.deepEqual(evidence.restored.draft,evidence.restored.beforeDraft);
    const after=await (await fetch('http://127.0.0.1:8003/fixture/state')).json();
    assert.equal(after.source_calls,before.source_calls);
    const mutations=state=>state.requests.filter(x=>x.method!=='GET');
    assert.deepEqual(mutations(after),mutations(before));
    adb('shell','input','keyevent','4');await new Promise(r=>setTimeout(r,500));
    evidence.restored.afterBack=await client.evaluate(`({modal:!!document.querySelector('.recall-dialog[open]'),ready:!!document.querySelector('.mobile-connection.ready')})`);
    assert.equal(evidence.restored.afterBack.modal,false);assert.equal(evidence.restored.afterBack.ready,true);
  }
  if (phase === 'keyboard') {
    evidence.keyboardBefore=await client.evaluate(`({viewport:visualViewport.height,innerHeight,navDisplay:getComputedStyle(document.querySelector('.mobile-nav')).display})`);
    await client.evaluate(`Array.from(document.querySelectorAll('.mobile-nav button')).find(x=>x.textContent==='轮胎查询').click();window.scrollTo(0,0);true`);
    await new Promise(r=>setTimeout(r,400));
    const target=await client.evaluate(`(()=>{const i=document.querySelector('input[placeholder="例如 225/45 R18"]');i.scrollIntoView({block:'center',behavior:'instant'});const r=i.getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2,dpr:devicePixelRatio}})()`);
    // Native input injection opens the actual Android IME; CDP focus alone is not proof.
    adb('shell','uiautomator','dump','/sdcard/round30-keyboard.xml');
    const hierarchy=adb('shell','cat','/sdcard/round30-keyboard.xml').toString('utf8');
    const inputNode=hierarchy.match(/<node[^>]*class="android.widget.EditText"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*>/);
    if(inputNode){
      const [,left,top,right,bottom]=inputNode.map(Number);
      evidence.tap={x:(left+right)/2,y:(top+bottom)/2,css:target,source:'android_input_bounds'};
    }else{
      // Android accessibility may expose only the WebView. Its real margins anchor CSS coordinates.
      const webview=hierarchy.match(/<node[^>]*class="android.webkit.WebView"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*>/);
      assert(webview,'Actual Android WebView bounds unavailable');
      const [,left,top]=webview.map(Number);
      evidence.tap={x:left+target.x*target.dpr,y:top+target.y*target.dpr,css:target,source:'android_webview_bounds_and_css'};
    }
    adb('shell','input','tap',String(Math.round(evidence.tap.x)),String(Math.round(evidence.tap.y)));
    await wait(`document.documentElement.dataset.keyboardOpen==='true'&&getComputedStyle(document.querySelector('.mobile-nav')).display==='none'`);
    evidence.keyboard=await client.evaluate(`({keyboard:document.documentElement.dataset.keyboardOpen,viewport:visualViewport.height,navDisplay:getComputedStyle(document.querySelector('.mobile-nav')).display,focused:document.activeElement?.tagName,width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth})`);
    evidence.imeVisible=/mInputShown=true/.test(adb('shell','dumpsys','input_method').toString('utf8'));
    assert.equal(evidence.imeVisible,true,'The actual Android IME must be visible');
    assert.equal(evidence.keyboard.keyboard,'true');assert.equal(evidence.keyboard.navDisplay,'none');
    assert.equal(evidence.keyboard.width,evidence.keyboard.scroll);
  }
  evidence.ui=await client.evaluate(`({title:document.title,theme:document.documentElement.dataset.mobileTheme,width:document.documentElement.clientWidth,scroll:document.documentElement.scrollWidth})`);
  const suffix=new Date().toISOString().replace(/[:.]/g,'-');
  evidence.screenshot=join(directory,`ui-${phase}-${suffix}.png`);
  await writeFile(evidence.screenshot,adb('exec-out','screencap','-p'));
  evidence.events=client.events;
  await writeFile(join(directory,`ui-${phase}-${suffix}.json`),JSON.stringify(evidence,null,2));
  console.log(JSON.stringify(evidence,null,2));
}catch(error){
  evidence.failure=error.message;
  const suffix=new Date().toISOString().replace(/[:.]/g,'-');
  evidence.screenshot=join(directory,`ui-${phase}-failure-${suffix}.png`);
  await writeFile(evidence.screenshot,adb('exec-out','screencap','-p'));
  await writeFile(join(directory,`ui-${phase}-failure-${suffix}.json`),JSON.stringify(evidence,null,2));
  console.error(JSON.stringify(evidence,null,2));
  throw error;
}finally{client.close();}
