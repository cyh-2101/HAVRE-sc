const {chromium}=require(process.env.HAVRE_PLAYWRIGHT_MODULE||'playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve('.'),out=path.join(root,'var/natural-chat-20260908');
fs.mkdirSync(out,{recursive:true});
(async()=>{
const browser=await chromium.launch({channel:'msedge',headless:true,args:['--disable-background-networking']});
try{
const context=await browser.newContext({serviceWorkers:'block',viewport:{width:390,height:844}});
await context.addInitScript(()=>{localStorage.setItem('havre-hidden-session','session-synthetic');});
const page=await context.newPage(),errors=[],requests=[];page.on('pageerror',e=>{errors.push(String(e));console.error('PAGE_ERROR',String(e))});page.on('console',m=>console.log('BROWSER',m.type(),m.text()));
let releaseFirst;const firstHeld=new Promise(resolve=>releaseFirst=resolve);
let mode='normal',processingUser=null;
const session_id='session-synthetic';let serial=0;
const item=(role,content,event_id,request_id='seed')=>({role,content,event_id,request_id,session_id,recorded_at:new Date(Date.now()+serial).toISOString(),proactive:false,interaction_status:'completed',response_policy_category:role==='assistant'?'ordinary':null,privacy_class:'NORMAL',memory_eligible:true,cloud_eligible:true,provider_id:role==='assistant'?'openai-codex-chatgpt':null,model_version_id:role==='assistant'?'gpt-5.6-sol':null,execution_environment:'cloud'});
let items=[item('user','今天去看了个小展，最后那间全是蓝色的。','seed-u'),item('assistant','听着像一下走进水底了。','seed-a')];
await page.route('**/*',async route=>{
 const req=route.request(),url=new URL(req.url());if(url.origin!=='https://havre.test')return route.abort();
 if(url.pathname==='/chat')return route.fulfill({contentType:'text/html',body:fs.readFileSync(path.join(root,'apps/web/havre-chat.html'))});
 if(url.pathname.startsWith('/assets/')){const name=path.basename(url.pathname);return route.fulfill({contentType:name.endsWith('.js')?'text/javascript':name.endsWith('.css')?'text/css':'image/svg+xml',body:fs.readFileSync(path.join(root,'apps/web',name))});}
 if(url.pathname==='/v1/product/settings')return route.fulfill({json:{auth_capabilities:{owner_primary:false},calendar:{configured:false,status:'disabled'},reach_out:{},reply_routes:{default:{provider_id:'openai-codex-chatgpt',model_version_id:'gpt-5.6-sol',execution_environment:'cloud',available:true},local_only:{provider_id:'self-hosted-openai-compatible',execution_environment:'local',available:true,privacy_classes:['LOCAL_ONLY'],model_version_id:'qwen3-8b'},local_only_available:true}}});
 if(url.pathname==='/v1/timeline')return route.fulfill({json:{items,has_more:false,next_cursor:null}});
 if(url.pathname==='/v1/timeline/read')return route.fulfill({json:{}});
 if(url.pathname==='/v1/interactions/stream'){
   const body=req.postDataJSON();console.log('SUBMIT',body.message);requests.push({body,key:req.headers()['idempotency-key']});serial++;if(serial===1)await firstHeld;
   const request_id='r'+serial,u=item('user',body.message,'u'+serial,request_id);u.privacy_class=body.privacy_class;u.client_created_at=body.client_created_at;u.reply_to_event_id=body.reply_to_event_id||null;u.input_origin=body.input_origin||'owner_text';
   if(mode==='fail'){mode='normal';u.interaction_status='failed';items=[...items,u];return route.fulfill({status:503,json:{detail:'synthetic failure'}})}
   if(mode==='processing'){u.interaction_status='processing';items=[...items,u];processingUser=u;return route.abort()}
   const content=body.message==='再说点'?'那间的光是深蓝还是浅蓝？\n\n要是墙上也有水纹，应该挺好看的。\n\n你在那里待了多久？':body.message.includes('函数')?'```python\ndef double(x):\n    return x * 2\n```\n\n这个函数返回输入的两倍。':'好，听你的。';
   const a=item('assistant',content,'a'+serial,request_id);a.privacy_class=body.privacy_class;if(body.privacy_class==='LOCAL_ONLY'){a.execution_environment='local';a.provider_id='self-hosted-openai-compatible';a.model_version_id='qwen3-8b';a.cloud_eligible=false;}
   items=[...items,u,a];return route.fulfill({contentType:'application/x-ndjson',body:JSON.stringify({type:'completed',interaction:{...a,assistant_event_id:a.event_id,user_event_id:u.event_id}})+'\n'});
 }
 return route.fulfill({json:{}});
});
await page.goto('https://havre.test/chat');await page.locator('#sayMoreButton').waitFor({state:'visible'});
const layouts=[];
for(const width of [390,1100]){await page.setViewportSize({width,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);await page.screenshot({path:path.join(out,`chat-${width}.png`)});layouts.push({width,overflow:false});}
await page.setViewportSize({width:390,height:844});
await page.locator('#messageInput').fill('尚未发送的草稿');assert.equal(await page.locator('#sayMoreButton').isVisible(),false);assert.equal(requests.length,0);
await page.locator('#messageInput').fill('');const frozen=new Date();await page.clock.install({time:frozen});await page.clock.pauseAt(frozen);
assert.equal(await page.locator('.bubble-enter').count(),0);
await page.locator('#sayMoreButton').click();await page.locator('.thinking').waitFor();
assert.equal(await page.locator('.thinking').textContent(),'...');
assert.equal(await page.locator('.thinking .message-actions').count(),0);
assert.equal(await page.locator('#sendState').innerText(),'');
assert.equal(await page.locator('#messageInput').inputValue(),'');
assert.equal(await page.locator('.owner').filter({hasText:'再说点'}).count(),0);
assert.equal(await page.locator('.typing-dots span').count(),3);
assert.equal(await page.locator('.typing-dots span').first().evaluate(el=>getComputedStyle(el).animationName),'typingDot');
await page.screenshot({path:path.join(out,'chat-waiting-390.png')});
releaseFirst();await page.locator('#message-a1').waitFor();
assert.equal(await page.locator('#message-u1').count(),0);
assert.equal(await page.locator('#message-a1 .bubble').first().evaluate(el=>getComputedStyle(el).animationName),'bubbleArrive');
assert.equal(requests[0].body.input_origin,'continuation_button');
assert.equal(requests.length,1);assert.equal(requests[0].body.message,'再说点');assert.equal(requests[0].body.reply_to_event_id,'seed-a');assert.equal(requests[0].body.session_id,session_id);assert.equal(requests[0].body.privacy_class,'NORMAL');assert.ok(requests[0].key);
assert.equal(await page.locator('#message-a1 .bubble:visible').count(),1);
await page.clock.runFor(3999);assert.equal(await page.locator('#message-a1 .bubble:visible').count(),1);
await page.clock.runFor(1);assert.equal(await page.locator('#message-a1 .bubble:visible').count(),2);assert.equal(await page.locator('#message-a1 .bubble').nth(1).evaluate(el=>getComputedStyle(el).animationName),'bubbleArrive');
await page.locator('#messageInput').fill('等一下');await page.clock.runFor(20000);assert.equal(await page.locator('#message-a1 .bubble:visible').count(),2);
await page.locator('#messageInput').fill('');await page.clock.runFor(4000);assert.equal(await page.locator('#message-a1 .bubble:visible').count(),3);
await page.locator('#sayMoreButton').click();await page.locator('#message-a2').waitFor();assert.equal(requests[1].body.reply_to_event_id,'a1');
assert.equal(await page.locator('#message-a2 .bubble:visible').count(),1);
await page.locator('#messageInput').fill('先停一下，说别的');await page.locator('#sendButton').click();await page.locator('#message-a3').waitFor();
await page.clock.runFor(20000);assert.equal(await page.locator('#message-a2 .bubble:visible').count(),1);
await page.locator('#message-a2 .remaining-reply').click();assert.equal(await page.locator('#message-a2 .bubble:visible').count(),3);
await page.locator('#messageInput').fill('请写一个函数');await page.locator('#sendButton').click();await page.locator('#message-a4').waitFor();
assert.equal(await page.locator('#message-a4 .bubble').count(),1);assert.match(await page.locator('#message-a4 .bubble').innerText(),/return x \* 2/);
await page.locator('#privacyMode').click();await page.locator('#sayMoreButton').click();await page.locator('#message-a5').waitFor();assert.equal(requests.at(-1).body.privacy_class,'LOCAL_ONLY');
assert.equal(await page.locator('#message-a5 .route-label').innerText(),'Qwen3-8B Base · 仅本机');
assert.equal(await page.locator('#sayMoreButton').innerText(),'看完这条');
const beforeExpand=requests.length;await page.locator('#sayMoreButton').click();
assert.equal(requests.length,beforeExpand);assert.equal(await page.locator('#message-a5 .bubble:visible').count(),3);
assert.equal(await page.locator('#sayMoreButton').innerText(),'再说点');
await page.screenshot({path:path.join(out,'chat-interrupted-390.png')});
await page.clock.runFor(1000);
await page.reload();await page.locator('#message-a5').waitFor();
assert.equal(await page.locator('#message-u1').count(),0);
assert.equal(await page.locator('#message-u2').count(),0);
assert.equal(await page.locator('#message-u5').count(),0);
assert.equal(await page.locator('.bubble-enter').count(),0);
// A typed continuation is still a real owner message.
await page.locator('#messageInput').fill('再说点');await page.locator('#sendButton').click();await page.locator('#message-a6').waitFor();
assert.equal(requests.at(-1).body.input_origin,undefined);
assert.equal(await page.locator('#message-u6 .bubble').innerText(),'再说点');
await page.emulateMedia({reducedMotion:'reduce'});
assert.equal(await page.locator('#message-a6 .bubble').first().evaluate(el=>getComputedStyle(el).animationName),'none');
// Durable failures remain actionable, without forging a user utterance or opening the keyboard.
await page.clock.runFor(12000);mode='fail';
await page.locator('#sayMoreButton').click();await page.locator('.continuation-status').waitFor();
const failedTap=requests.at(-1);assert.equal(await page.locator('#messageInput').inputValue(),'');
assert.equal(await page.locator('.continuation-status').getAttribute('class'),'message-row continuation-status');
await page.locator('.continuation-status button').click();await page.locator('#message-a8').waitFor();
assert.equal(requests.at(-1).body.reply_to_event_id,failedTap.body.reply_to_event_id);
assert.equal(requests.at(-1).body.input_origin,'continuation_button');assert.notEqual(requests.at(-1).key,failedTap.key);
await page.clock.runFor(12000);mode='processing';
await page.locator('#sayMoreButton').click();await page.locator('.thinking').waitFor();
await page.reload();await page.locator('.thinking').waitFor();
assert.equal(await page.locator('#message-u9').count(),0);assert.equal(await page.locator('#messageInput').inputValue(),'');
assert.equal(await page.locator('.thinking').textContent(),'...');
const duringProcessing=requests.length;
processingUser.interaction_status='completed';items=[...items,item('assistant','还有个办法，等你看完这条再试。','a9',processingUser.request_id)];mode='normal';
await page.reload();await page.locator('#message-a9').waitFor();
assert.equal(await page.locator('.thinking').count(),0);assert.equal(requests.length,duringProcessing);
assert.deepEqual(errors,[]);
const result={kind:'Real Edge DOM with synthetic mocked API; no model calls or owner data',layouts,checks:['failed control has explicit retry without a user bubble','retry retains exact parent and origin','processing dots survive reload','completed reconciliation sends no new request','button tap hidden during send and after reload','typed continuation remains visible','waiting only animated three dots without feedback','fresh bubble entrance and no replay on history load','reduced motion disables animation','draft protection','explicit continuation has one request and idempotency key','session and privacy preserved','3999ms hidden then 4000ms visible','typing pauses','clearing draft resumes','new message cancels old automatic reveal','saved remainder remains accessible','code is complete and unsplit','LOCAL_ONLY continuation stays local','exact parent binding','unread expansion makes zero requests'],pageErrors:errors,requests:requests.length};fs.writeFileSync(path.join(out,'ui-verification.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}catch(error){const page=browser.contexts()[0]?.pages()[0];if(page){console.log('DOM',await page.locator('#timeline').innerText());console.log('TOAST',await page.locator('#toast').innerText());await page.screenshot({path:path.join(out,'ui-failure.png')})}throw error}finally{await browser.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
