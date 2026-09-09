// Real Service Workers on an isolated loopback server; all conversation data is synthetic.
const {chromium}=require(process.env.HAVRE_PLAYWRIGHT_MODULE||'playwright');
const http=require('node:http'),fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),out=path.join(root,'var/pwa-update-20260908');
const names=['havre-chat.html','havre-app.js','havre-app.css','service-worker.js','manifest.webmanifest','havre-icon.svg'];
const current=Object.fromEntries(names.map(name=>[name,fs.readFileSync(path.join(root,'apps/web',name),'utf8')]));
const version=current['service-worker.js'].match(/const APP_VERSION='([^']+)'/)[1];
const legacyDir=process.argv[2];
const legacy=legacyDir?Object.fromEntries(names.map(name=>[name,fs.existsSync(path.resolve(legacyDir,name))?fs.readFileSync(path.resolve(legacyDir,name),'utf8'):current[name]])):null;
let release=version,files=current,offline=false,requests=[],items=[],holdReply=null,releaseReply=null;
const checks=[],errors=[];
const item=(role,content,event_id,request_id='seed')=>({role,content,event_id,request_id,session_id:'synthetic-session',recorded_at:'2026-09-08T22:00:00Z',proactive:false,interaction_status:'completed',privacy_class:'NORMAL',memory_eligible:true,cloud_eligible:true,response_policy_category:'ordinary'});
function reset(){items=[item('user','今天去看展了。','u0'),item('assistant','哪幅画让你多看了一会儿？','a0')];requests=[];}
const server=http.createServer(async(req,res)=>{
 const url=new URL(req.url,'http://localhost');res.setHeader('Cache-Control','no-store');
 if(offline){req.socket.destroy();return;}
 if(url.pathname.startsWith('/v1/')){
  res.setHeader('Content-Type','application/json');
  if(url.pathname==='/v1/product/settings')return res.end(JSON.stringify({auth_capabilities:{owner_primary:false},calendar:{configured:false},reach_out:{}}));
  if(url.pathname==='/v1/timeline')return res.end(JSON.stringify({items,has_more:false,next_cursor:null}));
  if(url.pathname==='/v1/interactions/stream'){
   let body='';for await(const chunk of req)body+=chunk;
   const value=JSON.parse(body);requests.push(value);const n=requests.length;
   const u={...item('user',value.message,'u'+n,'r'+n),input_origin:value.input_origin||'owner_text',reply_to_event_id:value.reply_to_event_id,client_created_at:value.client_created_at,interaction_status:'processing'};
   items.push(u);if(holdReply)await holdReply;u.interaction_status='completed';
   const a=item('assistant','那幅蓝色的？','a'+n,'r'+n);items.push(a);
   res.setHeader('Content-Type','application/x-ndjson');return res.end(JSON.stringify({type:'completed',interaction:{...a,assistant_event_id:a.event_id,user_event_id:u.event_id}})+'\n');
  }
  return res.end('{}');
 }
 const name=url.pathname==='/chat'?'havre-chat.html':path.basename(url.pathname);
 if(!names.includes(name)){res.statusCode=404;return res.end();}
 res.setHeader('Content-Type',name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':name.endsWith('.html')?'text/html':name.endsWith('.svg')?'image/svg+xml':'application/manifest+json');
 res.end(files[name].replaceAll(version,release));
});
const loadedVersion=page=>page.locator('script[src]').getAttribute('src');
async function expectVersion(page,expected){await page.waitForFunction(value=>document.querySelector('script[src]')?.src.includes(value),expected);await page.locator('#message-a0').waitFor();}
async function waitWorker(page,expected){await page.waitForFunction(async value=>(await caches.keys()).includes('havre-static-'+value),expected);await page.waitForFunction(()=>navigator.serviceWorker.controller);}
async function update(page){await page.evaluate(async()=>{await(await navigator.serviceWorker.getRegistration()).update()});}
async function startPage(browser,url,testMode=false){
 const context=await browser.newContext({viewport:{width:390,height:844},serviceWorkers:'allow'});
 await context.addInitScript(mode=>{localStorage.setItem('havre-hidden-session','synthetic-session');if(mode)window.__HAVRE_PWA_TEST_MODE__=true;},testMode);
 const page=await context.newPage();page.on('pageerror',error=>errors.push(String(error)));await page.goto(url);
 await page.evaluate(async()=>{await navigator.serviceWorker.ready;});await page.waitForFunction(()=>navigator.serviceWorker.controller);
 await page.locator('#message-a0').waitFor();return{context,page};
}
(async()=>{
 fs.mkdirSync(out,{recursive:true});await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
 const url=`http://127.0.0.1:${server.address().port}/chat`,browser=await chromium.launch({channel:'msedge',headless:true});
 try{
  if(legacy){
   reset();files=legacy;const {page,context}=await startPage(browser,url);
   await page.locator('#messageInput').fill('还没发出的草稿');const oldScript=await loadedVersion(page);
   files=current;await update(page);await waitWorker(page,version);
   assert.equal(await loadedVersion(page),oldScript);assert.equal(await page.locator('#messageInput').inputValue(),'还没发出的草稿');
   checks.push('actual legacy client remains stale after worker activation; draft preserved');
   await page.locator('#messageInput').fill('');await page.reload();await expectVersion(page,version);
   holdReply=new Promise(resolve=>{releaseReply=resolve;});await page.locator('#sayMoreButton').click();await page.locator('.typing-dots span').first().waitFor();
   assert.equal(await page.locator('.typing-dots span').count(),3);assert.equal(await page.locator('.owner').filter({hasText:'再说点'}).count(),0);
   releaseReply();holdReply=null;await page.locator('#message-a1').waitFor();
   assert.equal(requests[0].input_origin,'continuation_button');assert.equal(requests.length,1);assert.equal(await page.locator('#message-u1').count(),0);
   assert.equal(await page.locator('#message-a1 .bubble').evaluate(el=>getComputedStyle(el).animationName),'bubbleArrive');
   checks.push('legacy to current reload: hidden control, three dots, bubble animation, exactly one origin-qualified request');
   await context.close();
  }
  reset();files=current;release=version;const{page,context}=await startPage(browser,url);
  const next=version+'-test-next';await page.locator('#messageInput').fill('更新时不能丢');release=next;
  await update(page);await waitWorker(page,next);await page.locator('#appUpdateBanner').waitFor();
  // The real controller event has fired; after its grace period the draft must still exist.
  await page.waitForTimeout(2400);assert.ok((await loadedVersion(page)).includes(version));
  assert.equal(await page.locator('#messageInput').inputValue(),'更新时不能丢');
  await page.locator('#applyAppUpdate').click();assert.equal(await page.locator('#messageInput').inputValue(),'更新时不能丢');
  checks.push('controller change and manual update preserve unsent draft');
  await page.screenshot({path:path.join(out,'update-draft-390.png')});
  await page.locator('#messageInput').fill('');await page.locator('#applyAppUpdate').click();await expectVersion(page,next);
  assert.equal(await page.locator('#appUpdateBanner').isVisible(),false);checks.push('manual update reaches new actual script without a repeated update banner');
  // Idle clients apply a real later release automatically.
  release=version+'-test-idle';await update(page);await waitWorker(page,release);await expectVersion(page,release);
  checks.push('idle controller change automatically activates new page');
  // Network navigation and asset requests cannot be silently rewritten to this worker version.
  const newer=version+'-test-online';release=newer;
  const raw=await page.evaluate(async()=>({html:await(await fetch('/chat?notification_open=test')).text(),js:await(await fetch('/assets/havre-app.js?v=future')).text()}));
  assert.ok(raw.html.includes(newer));assert.ok(raw.js.includes(newer));checks.push('network-first HTML and exact asset queries avoid old cache substitution');
  // Reconnect/foreground checks must discover deployment even without a navigation.
  await page.evaluate(()=>window.dispatchEvent(new Event('online')));await expectVersion(page,newer);
  checks.push('returning online checks for and activates new release');
  // Test pending generation against another genuine worker installation.
  holdReply=new Promise(resolve=>{releaseReply=resolve;});await page.locator('#sayMoreButton').click();await page.locator('.thinking').waitFor();
  release=version+'-test-pending';await update(page);await waitWorker(page,release);await page.locator('#appUpdateBanner').waitFor();
  await page.waitForTimeout(2400);assert.ok((await loadedVersion(page)).includes(newer));assert.equal(requests.length,1);assert.equal(await page.locator('.thinking').count(),1);
  releaseReply();holdReply=null;await page.locator('#message-a1').waitFor();await page.locator('#applyAppUpdate').click();await expectVersion(page,release);
  assert.equal(requests.length,1);assert.equal(await page.locator('#message-u1').count(),0);checks.push('in-flight continuation survives update with no duplicate submission');
  // The installed offline snapshot has matching HTML/JS/CSS, and no private cache keys.
  const cacheKeys=await page.evaluate(async()=>{const result=[];for(const name of await caches.keys()){const cache=await caches.open(name);for(const request of await cache.keys())result.push(new URL(request.url).pathname);}return result;});
  assert.ok(cacheKeys.every(key=>!key.startsWith('/v1/')));checks.push('CacheStorage contains public shell only');
  offline=true;await page.reload();assert.ok((await loadedVersion(page)).includes(release));await page.locator('#messageInput').waitFor();
  assert.equal(await page.locator('#appUpdateBanner').isVisible(),false);checks.push('offline reload boots coherent installed version');
  offline=false;await page.evaluate(()=>window.dispatchEvent(new Event('online')));await page.locator('#message-a1').waitFor();
  assert.equal(requests.length,1);checks.push('offline reconnect does not replay a completed continuation');
  for(const width of[390,1100]){await page.setViewportSize({width,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);}
  checks.push('390px and 1100px layouts have no horizontal overflow');
  await context.close();assert.deepEqual(errors,[]);
  fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify({version,checks,errors,legacy:!!legacy,realServiceWorkers:true,syntheticData:true},null,2));
  console.log(JSON.stringify({passed:checks.length,checks,errors}));
 }finally{if(releaseReply)releaseReply();await browser.close();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));}
})().catch(error=>{console.error(error);process.exitCode=1;server.closeAllConnections();server.close();});
