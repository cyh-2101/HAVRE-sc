// Measure rendered frames of the normal send/receive path, not just an animation name.
const {chromium}=require(process.env.HAVRE_PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'),out=path.join(root,'var/bubble-motion-20260908');
const before=process.argv.includes('--before'),source=before?path.join(out,'before'):path.join(root,'apps/web');
fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:'msedge',headless:true});
 try{
 const context=await browser.newContext({viewport:{width:390,height:844},serviceWorkers:'block',reducedMotion:'no-preference'});
 await context.addInitScript(()=>localStorage.setItem('havre-hidden-session','motion-session'));
 const page=await context.newPage(),errors=[],checks=[];page.on('pageerror',e=>errors.push(String(e)));
 let release,held=new Promise(resolve=>{release=resolve;}),serial=0,multiReply=false;
 const item=(role,content,event_id,request_id='seed')=>({role,content,event_id,request_id,session_id:'motion-session',recorded_at:'2026-09-08T22:00:00Z',privacy_class:'NORMAL',memory_eligible:true,cloud_eligible:true,interaction_status:'completed',response_policy_category:'ordinary'});
 let items=Array.from({length:18},(_,n)=>item(n%2?'assistant':'user','用于滚动检查的日常对话，'+n+'。','history-'+n));
 items.push(item('assistant','最后看到的是哪幅画？','seed-a'));
 await page.route('**/*',async route=>{
  const req=route.request(),url=new URL(req.url());if(url.origin!=='https://havre.test')return route.abort();
  if(url.pathname==='/chat')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(source,'havre-chat.html'))});
  if(url.pathname.startsWith('/assets/')){const name=path.basename(url.pathname),file=path.join(source,name);return route.fulfill({contentType:name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'image/svg+xml',body:fs.readFileSync(fs.existsSync(file)?file:path.join(root,'apps/web',name))});}
  if(url.pathname==='/v1/product/settings')return route.fulfill({json:{auth_capabilities:{owner_primary:false},calendar:{configured:false},reach_out:{}}});
  if(url.pathname==='/v1/timeline')return route.fulfill({json:{items,has_more:false,next_cursor:null}});
  if(url.pathname==='/v1/interactions/stream'){
   const body=req.postDataJSON(),n=++serial;await held;
   const u={...item('user',body.message,'u'+n,'r'+n),input_origin:body.input_origin,client_created_at:body.client_created_at,reply_to_event_id:body.reply_to_event_id};
   const a=item('assistant',multiReply?'我还在想那间蓝色的屋子。\n\n窗外的光照进来，墙上会不会也有淡淡的水纹？':'我还在想那间蓝色的屋子。窗外的光照进来，墙上会不会也有淡淡的水纹？你走出来的时候，有没有还想回头看一眼。','a'+n,'r'+n);
   items.push(u,a);return route.fulfill({contentType:'application/x-ndjson',body:JSON.stringify({type:'completed',interaction:{...a,assistant_event_id:a.event_id,user_event_id:u.event_id}})+'\n'});
  }
  return route.fulfill({json:{}});
 });
 await page.goto('https://havre.test/chat');await page.locator('#sayMoreButton').waitFor();
 await page.locator('#sayMoreButton').click();await page.locator('.thinking').waitFor();await page.waitForTimeout(500);
 const previousTop=await page.locator('#message-seed-a').evaluate(el=>el.getBoundingClientRect().top);
 await page.evaluate(()=>{
  window.motionFrames=[];window.motionDone=false;
  const observer=new MutationObserver(()=>{
   const row=document.querySelector('#message-a1'),bubble=row?.querySelector('.bubble');if(!bubble)return;
   observer.disconnect();let start;
   function sample(now){start??=now;const style=getComputedStyle(bubble),rect=bubble.getBoundingClientRect();window.motionFrames.push({t:now-start,opacity:Number(style.opacity),transform:style.transform,top:rect.top,height:rect.height,previousTop:document.querySelector('#message-seed-a').getBoundingClientRect().top});if(now-start<700)requestAnimationFrame(sample);else window.motionDone=true;}
   requestAnimationFrame(sample);
  });observer.observe(document.querySelector('#timeline'),{childList:true,subtree:true});
 });
 release();await page.waitForFunction(()=>window.motionDone);
 const frames=await page.evaluate(()=>window.motionFrames);
 const result={kind:'real rendered frames, synthetic API, no model calls',previousTop,frames,firstLayoutJump:Math.abs(frames[0].previousTop-previousTop)};
 fs.writeFileSync(path.join(out,before?'before-frames.json':'after-frames.json'),JSON.stringify(result,null,2));
 if(before){console.log(JSON.stringify({before:true,firstLayoutJump:result.firstLayoutJump,frameAt100ms:frames.find(f=>f.t>=100)}));return;}
 assert.ok(result.firstLayoutJump<6,`first-frame history jump: ${result.firstLayoutJump}`);
 assert.ok(frames[0].opacity<.35);const middle=frames.find(f=>f.t>=100);assert.ok(middle.opacity<.85,'entrance must not be practically finished at 100ms');
 assert.ok(Math.abs(frames.at(-1).previousTop-previousTop)>20,'fixture must actually move the history');
 assert.equal(frames.at(-1).opacity,1);assert.ok(new Set(frames.filter(f=>f.t<350).map(f=>f.previousTop.toFixed(1))).size>5);
 checks.push('visible history movement begins without a position jump and continues over multiple frames','new bubble visibly enters instead of practically finishing in the first 100ms');
 // Stable keyed nodes must not restart the current entrance on unrelated updates.
 await page.evaluate(()=>{window.originalRow=document.querySelector('#message-a1');window.removals=0;new MutationObserver(records=>{for(const record of records)for(const node of record.removedNodes)if(node===window.originalRow)window.removals++;}).observe(document.querySelector('#timeline'),{childList:true});});
 items[0]={...items[0],content:items[0].content+'（更正）'};
 await page.evaluate(()=>document.dispatchEvent(new Event('visibilitychange')));
 await page.waitForFunction(()=>document.querySelector('#message-history-0 .bubble').textContent.includes('更正'));
 assert.equal(await page.evaluate(()=>window.removals),0);assert.equal(await page.locator('#message-a1 .bubble-enter').count(),0);
 checks.push('updating an older message keeps current message nodes attached and does not replay entrance');
 await page.reload();await page.locator('#message-a1').waitFor();assert.equal(await page.locator('.bubble-enter').count(),0);checks.push('history reload has no entrance animation');
 multiReply=true;await page.locator('#sayMoreButton').click();await page.locator('#message-a2').waitFor();await page.waitForTimeout(600);
 assert.equal(await page.locator('#message-a2 .bubble:visible').count(),1);
 const reveal=await page.evaluate(()=>new Promise(resolve=>{
  const row=document.querySelector('#message-a2'),second=row.querySelectorAll('.bubble')[1],top=row.getBoundingClientRect().top;
  const observer=new MutationObserver(()=>{if(second.hidden)return;observer.disconnect();requestAnimationFrame(()=>resolve({jump:Math.abs(row.getBoundingClientRect().top-top),opacity:Number(getComputedStyle(second).opacity),moving:row.getAnimations().length>0}));});
  observer.observe(second,{attributes:true,attributeFilter:['hidden']});
 }));
 assert.ok(reveal.jump<6,JSON.stringify(reveal));assert.ok(reveal.opacity<.35);assert.ok(reveal.moving);checks.push('four-second paragraph reveal also moves the preceding content without a jump');
 await page.waitForTimeout(600);multiReply=false;
 await page.emulateMedia({reducedMotion:'reduce'});await page.locator('#sayMoreButton').click();await page.locator('#message-a3').waitFor();
 assert.equal(await page.locator('#message-a3 .bubble').evaluate(el=>getComputedStyle(el).animationName),'none');
 assert.equal(await page.locator('#message-seed-a').evaluate(el=>el.getAnimations().length),0);checks.push('reduced motion disables both bubble and history movement');
 for(const width of[390,1100]){await page.setViewportSize({width,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);}
 checks.push('mobile and desktop remain within viewport');assert.deepEqual(errors,[]);
 fs.writeFileSync(path.join(out,'browser-results.json'),JSON.stringify({checks,errors,framesMeasured:frames.length,firstLayoutJump:result.firstLayoutJump},null,2));console.log(JSON.stringify({checks,errors,framesMeasured:frames.length,firstLayoutJump:result.firstLayoutJump}));
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
