(()=>{
'use strict';
const $=selector=>document.querySelector(selector);
const $$=selector=>[...document.querySelectorAll(selector)];
const APP_VERSION='20260908-fluid-bubbles-v21';
const PUSH_SHELL_VERSION='havre-shell-v5',PRIVACY_MODE_KEY='havre-local-only-mode-v1',SESSION_ID_KEY='havre-hidden-session',PUSH_SUBSCRIPTION_ID_KEY='havrePushSubscriptionId',PENDING_INTERACTION_KEY='havre-pending-interaction-v1';
function browserStorage(){try{return globalThis.localStorage||null}catch{return null}}
function browserSessionStorage(){try{return globalThis.sessionStorage||null}catch{return null}}
function storageGet(key,storage=browserStorage()){try{return storage?.getItem(key)??null}catch{return null}}
function storageSet(key,value,storage=browserStorage()){try{if(!storage)return false;storage.setItem(key,String(value));return true}catch{return false}}
function storageRemove(key,storage=browserStorage()){try{if(!storage)return false;storage.removeItem(key);return true}catch{return false}}
function isLoopbackHost(locationLike=globalThis.location){const hostname=String(locationLike?.hostname||'').toLowerCase();return hostname==='127.0.0.1'||hostname==='localhost'||hostname==='::1'||hostname==='[::1]'}
function authorizationRequiredMessage(loopback=isLoopbackHost()){return loopback?'这个浏览器没有本机授权。请运行 .\\scripts\\start_havre_desktop.ps1，并使用它自动打开的新页面。':'这台设备需要先和 HAVRE 安全绑定。'}
function readLocalOnly(storage=browserStorage()){return storageGet(PRIVACY_MODE_KEY,storage)==='1'}
function persistLocalOnly(value,storage=browserStorage()){return storageSet(PRIVACY_MODE_KEY,value?'1':'0',storage)}
function validPendingInteraction(value){const body=value?.body;return value?.schema_version===1&&typeof value.idempotency_key==='string'&&value.idempotency_key.length>0&&value.idempotency_key.length<=200&&typeof body?.message==='string'&&body.message.trim().length>0&&(body.privacy_class==='NORMAL'||body.privacy_class==='LOCAL_ONLY')&&body.memory_eligible===true&&(body.input_origin==null||body.input_origin==='owner_text'||(body.input_origin==='continuation_button'&&body.message==='再说点'&&typeof body.reply_to_event_id==='string'&&typeof body.session_id==='string'))&&(body.session_id==null||typeof body.session_id==='string')&&(body.reply_to_event_id==null||typeof body.reply_to_event_id==='string')&&typeof body.client_created_at==='string'&&Number.isFinite(Date.parse(body.client_created_at))}
function readPendingInteraction(storage=browserSessionStorage()){const raw=storageGet(PENDING_INTERACTION_KEY,storage);if(!raw)return null;try{const value=JSON.parse(raw);if(validPendingInteraction(value))return value}catch{}storageRemove(PENDING_INTERACTION_KEY,storage);return null}
function persistPendingInteraction(value,storage=browserSessionStorage()){return validPendingInteraction(value)&&storageSet(PENDING_INTERACTION_KEY,JSON.stringify(value),storage)}
function removePendingInteraction(storage=browserSessionStorage()){return storageRemove(PENDING_INTERACTION_KEY,storage)}
function createPendingInteraction(message,clientCreatedAt,localOnly=false,sessionId=null,idempotencyKey=globalThis.crypto?.randomUUID?.()){const value={schema_version:1,idempotency_key:idempotencyKey,body:buildInteractionBody(message,clientCreatedAt,localOnly,sessionId)};if(!validPendingInteraction(value))throw new Error('无法建立安全的发送事务。');return value}
function sameClientInstant(left,right){const a=Date.parse(left),b=Date.parse(right);return Number.isFinite(a)&&Number.isFinite(b)&&a===b}
function pendingMatchesTimelineItem(pending,item={}){if(!validPendingInteraction(pending)||item.role!=='user'||!item.request_id)return false;const body=pending.body,itemPrivacy=item.privacy_class||item.effective_privacy_class||null;const inheritedPrivate=body.privacy_class==='NORMAL'&&itemPrivacy==='LOCAL_ONLY'&&item.reply_to_event_id&&/^(?:再说点|再说一点|多说点|多说一点|say more|keep talking)[。.!！?？\s]*$/i.test(body.message);if((item.input_origin||'owner_text')!==(body.input_origin||'owner_text')||item.content!==body.message||(!inheritedPrivate&&itemPrivacy!==body.privacy_class)||!sameClientInstant(item.client_created_at,body.client_created_at)||(body.reply_to_event_id&&String(body.reply_to_event_id)!==String(item.reply_to_event_id)))return false;return body.session_id==null||String(item.session_id)===String(body.session_id)}
function pendingResolution(pending,items=[]){const item=[...items].reverse().find(candidate=>pendingMatchesTimelineItem(pending,candidate));if(!item)return{status:'absent',item:null};if(item.interaction_status==='completed'||item.interaction_status==='failed')return{status:'terminal',item};return{status:'processing',item}}
async function submitPendingInteraction(pending,request=globalThis.fetch,timeoutMs=350000){return withRequestDeadline(async signal=>{if(!validPendingInteraction(pending)||typeof request!=='function')throw new Error('无法恢复安全的发送事务。');const response=await request('/v1/interactions/stream',{method:'POST',credentials:'same-origin',signal,headers:{'Content-Type':'application/json','Idempotency-Key':pending.idempotency_key},body:JSON.stringify(pending.body)});if(!response.ok){if(response.status===401)throw authorizationFailure();throw new Error(`发送失败 (${response.status})`)}const frames=(await response.text()).split('\n').filter(Boolean);let completed=null;for(const line of frames){const value=JSON.parse(line);if(value.type==='error')throw new Error(value.message);if(value.type==='completed')completed=value.interaction}if(!completed)throw new Error('回复没有完成，稍后再试。');return completed},timeoutMs)}
async function submitPendingWithReconciliation(pending,{request=globalThis.fetch,reload=()=>loadTimeline({refreshAfterCurrent:true}),items=()=>state.items}={}){let lastError=null;for(let attempt=0;attempt<2;attempt+=1){try{return{status:'completed',completed:await submitPendingInteraction(pending,request)}}catch(error){lastError=error;let loaded=null;try{loaded=await reload()}catch{return{status:'unknown',item:null,error}}if(loaded==null)return{status:'unknown',item:null,error};const resolution=pendingResolution(pending,items());if(resolution.status!=='absent')return{...resolution,error};if(attempt===0)continue}}return{status:'absent',item:null,error:lastError}}
async function withRequestDeadline(operation,timeoutMs){const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),timeoutMs);try{return await operation(controller.signal)}catch(error){if(controller.signal.aborted)throw new Error('连接等待超时，正在确认消息是否已保存。');throw error}finally{clearTimeout(timer)}}
function retryDraft(item,draft=''){if(item?.role!=='user'||item.interaction_status!=='failed'||item.memory_eligible!==true||!['NORMAL','LOCAL_ONLY'].includes(item.privacy_class)||(item.privacy_class==='NORMAL'&&item.cloud_eligible!==true))return null;if(draft.trim()&&draft.trim()!==item.content)return null;return{message:item.content,localOnly:item.privacy_class==='LOCAL_ONLY',sessionId:item.session_id,replyToEventId:item.reply_to_event_id||null,...(item.input_origin==='continuation_button'?{inputOrigin:item.input_origin}:{})}}
function prepareFailedRetry(item,{focus=true}={}){if(send.disabled&&focus){showToast('先等当前回复结束，原消息还在。');return false}const active=state.pendingInteraction;if(active&&pendingResolution(active,state.items).status!=='terminal'){showToast('上一条还在处理中，先等它结束。');return false}const draft=retryDraft(item,input.value);if(!draft){showToast('原消息仍然保留；请先保存当前草稿，再重试。');return false}if(draft.localOnly&&localRouteAvailable()!==true){showToast('这条消息只能在本机重试；请等本机回复引擎恢复。');return false}if(active)forgetActivePending();if(draft.inputOrigin==='continuation_button'){adoptPendingSession(item);if(focus)void sendMessage({preventDefault(){}},draft.replyToEventId,'continuation_button');else showToast('这次没接上，可以重试续聊。');return true}setLocalOnly(draft.localOnly);adoptPendingSession(item);input.value=draft.message;state.retryContinuation=draft.replyToEventId?{message:draft.message,eventId:draft.replyToEventId}:null;resizeInput();if(focus)input.focus();showToast('回复中断了，原文已恢复；点发送重试。');return true}
const restoredPending=readPendingInteraction();
const state={items:[],cursor:null,hasMore:false,loading:false,sessionId:storageGet(SESSION_ID_KEY),feedbackEvent:null,feedbackRating:'helpful',settings:null,installPrompt:null,localOnly:readLocalOnly(),authorizationRequired:false,routeEvidence:new Map(),pendingInteraction:restoredPending,pendingPersisted:Boolean(restoredPending),animateAssistantEventId:null,enteringEventIds:new Set(),lastReadEventId:null};
const timeline=$('#timeline'),input=$('#messageInput'),send=$('#sendButton'),toast=$('#toast');

function readableError(detail,status){if(/belief[_ ]key already/.test(detail))return '这条记忆已经有对应的理解，请在“我对你的理解”里查看或纠正。';if(status===409)return '这条记录刚刚有了更新，请重新打开后再试。';return /[\u4e00-\u9fff]/.test(detail)?detail:'暂时没能完成这一步。请稍后再试，已保存的内容仍在。'}
function showToast(message){toast.textContent=message;toast.hidden=false;clearTimeout(showToast.timer);showToast.timer=setTimeout(()=>toast.hidden=true,4200)}
function enterAuthorizationRequiredState(loopback=isLoopbackHost()){
  if(!loopback){$('#pairDialog').showModal();return}
  state.authorizationRequired=true;
  const banner=$('#authBanner');banner.textContent=authorizationRequiredMessage(true);banner.hidden=false;
  $('#presence').textContent='等待本机授权';$('#brainLabel').textContent='需要本机授权';$('#sendState').textContent='请通过启动器打开';
  input.disabled=true;send.disabled=true;$('#privacyMode').disabled=true;$('#loadOlder').hidden=true;
}
function leaveAuthorizationRequiredState(){
  if(!state.authorizationRequired)return;
  state.authorizationRequired=false;$('#authBanner').hidden=true;$('#presence').textContent='在这里';$('#sendState').textContent='';input.disabled=false;send.disabled=false;updatePrivacyUI();
}
function authorizationFailure(){const loopback=isLoopbackHost();enterAuthorizationRequiredState(loopback);return new Error(authorizationRequiredMessage(loopback))}
async function api(path,options={}){return withRequestDeadline(async signal=>{const response=await fetch(path,{credentials:'same-origin',headers:{'Content-Type':'application/json',...(options.headers||{})},...options,signal});if(response.status===401)throw authorizationFailure();if(!response.ok){let value={};try{value=await response.json()}catch{}const detail=typeof value.detail==='string'?value.detail:value.detail?.message||`请求失败 (${response.status})`;throw new Error(readableError(detail,response.status))}return response.status===204?null:response.json()},20000)}
function text(value){return String(value??'').replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]))}
function showPageError(root,error,retry){root.innerHTML=`<div class="page-error" role="status"><p>暂时没能加载，已保存的内容不会因此丢失。</p><button type="button" class="secondary-button">再试一次</button></div>`;root.querySelector('button').onclick=retry;console.debug(error)}
function editMemoryText(title,initial,{belief=false}={}){const dialog=$('#memoryEditDialog');$('#memoryEditTitle').textContent=title;$('#memoryEditText').value=initial;$('#memoryEditKindLabel').hidden=!belief;dialog.returnValue='';return new Promise(resolve=>{dialog.addEventListener('close',()=>{const value=$('#memoryEditText').value.trim();resolve(dialog.returnValue==='save'&&value?{text:value,kind:$('#memoryEditKind').value}:null)},{once:true});dialog.showModal();$('#memoryEditText').focus()})}
function filterMemory(){const query=($('#memorySearch')?.value||'').trim().toLocaleLowerCase(),cards=[...$('#memoryContent').querySelectorAll('.memory-card:not(.understanding-card)')];let found=0;for(const card of cards){const matches=!query||card.textContent.toLocaleLowerCase().includes(query);card.hidden=!matches;if(matches){found++;if(query)card.closest('details.memory-group')?.setAttribute('open','')}}$('#memorySearchStatus').textContent=query?`找到 ${found} 条相关内容`:''}
function localDay(value){return new Intl.DateTimeFormat('zh-CN',{year:'numeric',month:'long',day:'numeric',weekday:'short'}).format(new Date(value))}
function clock(value){return new Intl.DateTimeFormat('zh-CN',{hour:'2-digit',minute:'2-digit'}).format(new Date(value))}
function sameDay(a,b){return new Date(a).toLocaleDateString()===new Date(b).toLocaleDateString()}
function resizeInput(target=input){target.style.height='auto';const height=Math.min(target.scrollHeight,140);target.style.height=height+'px';return height}
// Preserve complete thoughts and structured output; never chop sentences or code.
function conversationBubbleParts(item={}){
  const content=String(item.content||'').trim();
  if(!content||item.role!=='assistant'||item.proactive||content.includes('```')||/^\s*(?:[-*+] |\d+[.)] |[|{[])/m.test(content))return[content];
  return content.split(/\n\s*\n+/).map(value=>value.trim()).filter(Boolean);
}
function canPaceReply(item,parts){
  const owner=state.items.find(turn=>turn.role==='user'&&turn.request_id&&turn.request_id===item.request_id);
  if(owner&&/详细|完整|展开|步骤|代码|函数|JSON|SQL|in detail|step.by.step/i.test(owner.content))return false;
  return item.role==='assistant'&&!item.proactive&&item.response_policy_category==='ordinary'&&
    parts.length>1&&parts.length<=3&&parts.join('\n\n').length<=360;
}
// This controls presentation of one already saved Event, never model execution.
function createBubblePacer(count,reveal,{schedule=setTimeout,clear=clearTimeout,onChange=()=>{}}={}){
  let shown=1,timer=null,paused=false,cancelled=false;
  const snapshot=()=>({shown,total:count,paused,cancelled,done:shown>=count});
  function stop(){if(timer!==null)clear(timer);timer=null}
  function arm(){if(timer!==null||paused||cancelled||shown>=count)return;timer=schedule(()=>{timer=null;reveal(shown++);onChange(snapshot());arm()},4000)}
  const control={snapshot,pause(){stop();paused=true;onChange(snapshot())},resume(){if(cancelled)return;paused=false;onChange(snapshot());arm()},cancel(){stop();cancelled=true;onChange(snapshot())},finish(){stop();while(shown<count)reveal(shown++);onChange(snapshot())}};
  arm();return control;
}
const bubblePacers=new Map();
function cancelBubblePacing(){for(const controller of bubblePacers.values())controller.cancel()}
function updateBubblePacing(){const pause=Boolean(input.value.trim())||document.visibilityState==='hidden';for(const controller of bubblePacers.values())pause?controller.pause():controller.resume()}
function sayMoreAvailable(items=state.items,{busy=send.disabled,draft=input.value,sessionId=state.sessionId,pending=state.pendingInteraction,focused=state.focusedHistory}={}){
  const last=items.at(-1);
  return !busy&&!pending&&!focused&&!String(draft||'').trim()&&last?.role==='assistant'&&!last.proactive&&
    Boolean(last.request_id&&last.session_id)&&String(last.session_id)===String(sessionId);
}
function isContinuationControl(item){return item?.role==='user'&&item.input_origin==='continuation_button'}
function continuationRetryAvailable(){return state.pendingInteraction?.body.input_origin==='continuation_button'&&!send.disabled&&!input.value.trim()&&!state.focusedHistory}
function updateSayMore(){const button=$('#sayMoreButton');if(!button)return;const pacer=bubblePacers.get(String(state.items.at(-1)?.event_id));button.textContent=continuationRetryAvailable()?'重试续聊':pacer&&!pacer.snapshot().done?'看完这条':'再说点';button.hidden=!(sayMoreAvailable()||continuationRetryAvailable());button.disabled=send.disabled}
async function sayMore(){
  if(continuationRetryAvailable()){await sendMessage({preventDefault(){}},state.pendingInteraction.body.reply_to_event_id,'continuation_button');return}
  if(!sayMoreAvailable())return;
  // A control request retains privacy, exact reply binding and idempotent recovery.
  const parent=state.items.at(-1),pacer=bubblePacers.get(String(parent.event_id));
  if(pacer&&!pacer.snapshot().done){pacer.finish();updateSayMore();return}
  await sendMessage({preventDefault(){}},parent.event_id,'continuation_button');
}

function modelLabel(modelId,adapterId=null,local=false){const normalized=typeof modelId==='string'?modelId.toLowerCase():'';if(normalized.includes('gpt-5.6-sol'))return'GPT-5.6-sol';if(normalized.includes('qwen3-8b'))return adapterId?`Qwen3-8B · ${adapterId}`:'Qwen3-8B Base';return modelId||(local?'本机模型':'GPT')}
function routeLabel(item={}){const provider=item.provider_id||item.provider?.provider_id||null,model=item.model_version_id||item.provider?.model_version_id||null,adapter=item.adapter_version_id||item.provider?.adapter_version_id||null,environment=item.execution_environment||item.provider?.execution_environment||null,privacy=item.effective_privacy_class||item.privacy_class||null,label=adapter?modelLabel(model,adapter,environment==='local'):item.label||modelLabel(model,null,environment==='local');if(environment==='cloud'||provider==='openai-codex-chatgpt')return`${label} · 云端`;if(environment==='local'||provider==='self-hosted-openai-compatible'||provider?.startsWith('deterministic-local'))return`${label} · 仅本机`;if(privacy==='LOCAL_ONLY')return model?`${label} · 仅本机`:'仅本机';return model?label:''}
function configuredRoute(localOnly,settings=state.settings){const routes=settings?.reply_routes;if(!routes)return null;if(localOnly){if(routes.local_only_available===false||routes.local_only?.available===false)return null;return routes.local_only||null}return routes.default?.available===false?null:routes.default||null}
function localRouteAvailable(settings=state.settings){if(!settings)return null;const route=configuredRoute(true,settings);return Boolean(route&&route.execution_environment==='local'&&route.privacy_classes?.includes('LOCAL_ONLY'))}
function intendedRouteLabel(localOnly=state.localOnly,settings=state.settings){if(!settings)return'正在确认回复引擎…';const configured=configuredRoute(localOnly,settings);if(!configured)return localOnly?'仅本机回复不可用':'回复引擎不可用';if(!localOnly&&configured.execution_environment==='cloud'){const name=configured.label||modelLabel(configured.model_version_id);return localRouteAvailable(settings)===true?`默认 ${name}；上下文不适合云端时仅本机`:`默认 ${name}；受限上下文不会发送云端`}return routeLabel(configured)||configured.label||'回复引擎'}
function thinkingLabel(){return'...'}
function privacyModeNotice(localOnly,persisted){if(localOnly)return persisted?'已切换为仅本机；这个选择会保持到你主动切回。':'已在本标签页切换为仅本机；浏览器未能保存此选择，刷新后请重新确认。';return persisted?'已切回默认回复；此前仅本机的对话不会发送给 GPT。':'已在本标签页切回默认回复；浏览器未能保存此选择，刷新后请重新确认。'}
function updatePrivacyUI(){const button=$('#privacyMode');if(!button)return;button.setAttribute('aria-pressed',String(state.localOnly));button.textContent=state.localOnly?'✓ 仅本机':'仅本机';if(state.authorizationRequired){button.disabled=true;button.title='请通过 HAVRE 启动器获得本机授权';$('#brainLabel').textContent='需要本机授权';return}const availability=localRouteAvailable();button.disabled=send.disabled||(!state.localOnly&&availability!==true);button.title=state.localOnly?'保持在本机；再次点击可切回默认回复':availability===null?'正在确认本机回复引擎':availability?'点击后，本条及后续消息只交给本机模型':'当前没有可用的本机回复引擎';$('#brainLabel').textContent=intendedRouteLabel()}
function setLocalOnly(value,{announce=false,storage=browserStorage()}={}){const next=Boolean(value);if(next&&localRouteAvailable()!==true){if(announce)showToast('当前没有可用的本机回复引擎。');return false}state.localOnly=next;const persisted=persistLocalOnly(state.localOnly,storage);updatePrivacyUI();if(announce)showToast(privacyModeNotice(state.localOnly,persisted));return true}
function buildInteractionBody(message,clientCreatedAt,localOnly=state.localOnly,sessionId=state.sessionId){return{message,privacy_class:localOnly?'LOCAL_ONLY':'NORMAL',memory_eligible:true,session_id:sessionId,client_created_at:clientCreatedAt}}
function interactionFailureLabel(item={}){if(item.role!=='user'||item.interaction_status!=='failed')return'';const actual=routeLabel(item);return`${actual||'尚未选择回复引擎'} 未生成回复 · 本次未跨模型重试`}
function rememberCompletedRoute(completed){if(completed?.assistant_event_id){cancelBubblePacing();const id=String(completed.assistant_event_id);state.routeEvidence.set(id,completed);state.animateAssistantEventId=id;state.enteringEventIds.add(id)}}
function mergeRouteEvidence(items,evidenceByEvent=state.routeEvidence){const fields=['provider_id','model_version_id','adapter_version_id','execution_environment','effective_privacy_class'];return items.map(item=>{const evidence=evidenceByEvent.get(String(item.event_id));if(!evidence)return item;const merged={...item};for(const field of fields)if(merged[field]==null&&evidence[field]!=null)merged[field]=evidence[field];return merged})}
function timelineItemFingerprint(item={}){return[item.event_id,item.role,item.content,item.recorded_at,item.interaction_status,item.provider_id,item.model_version_id,item.proactive,item.response_policy_category,item.input_origin,item.thinking].map(value=>String(value??'')).join('\u001f')}
function sameTimelineSnapshot(left=[],right=[]){return left.length===right.length&&left.every((item,index)=>timelineItemFingerprint(item)===timelineItemFingerprint(right[index]))}
function beginOptimisticTurn(temporary,thinking){state.timelineEpoch=(state.timelineEpoch||0)+1;state.items.push(temporary,thinking);state.enteringEventIds.add(temporary.event_id);state.enteringEventIds.add(thinking.event_id)}
function setPage(name){$$('.page').forEach(page=>page.classList.toggle('active',page.id===`${name}Page`));$$('.nav-item').forEach(button=>button.classList.toggle('active',button.dataset.page===name));const notificationHash=/^#(?:message|delivery)-/.test(location.hash)?location.hash:'';history.replaceState(null,'',name==='chat'?`/chat${notificationHash}`:`/chat#${name}`);if(name==='diary')loadDiary();if(name==='memory')loadMemory();if(name==='chat')requestAnimationFrame(()=>timeline.scrollTop=timeline.scrollHeight)}

function pendingThinkingItem(items=state.items){const last=items.at(-1);return last?.role==='user'&&last.request_id&&last.interaction_status==='processing'?{event_id:`thinking-persisted-${last.request_id}`,role:'assistant',thinking:true,content:'...',recorded_at:last.recorded_at}:null}
const timelineMotions=new Map();
function reducedMotion(){return Boolean(globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches)}
function cancelTimelineMotion(){for(const animation of timelineMotions.values())animation.cancel();timelineMotions.clear()}
function captureTimelinePositions(enabled=true){
  if(!enabled||reducedMotion()||document.visibilityState!=='visible'){cancelTimelineMotion();return null}
  const viewport=timeline.getBoundingClientRect(),positions=new Map();
  for(const row of timeline.querySelectorAll('.message-row,.date-separator')){
    const rect=row.getBoundingClientRect();if(rect.bottom>viewport.top&&rect.top<viewport.bottom)positions.set(row,rect.top);
  }
  // Capture the currently visible positions before cancelling an interrupted move.
  cancelTimelineMotion();return positions;
}
function animateTimelinePositions(positions){
  if(!positions||reducedMotion())return;
  for(const [row,top] of positions){
    if(!row.isConnected||typeof row.animate!=='function')continue;
    const delta=top-row.getBoundingClientRect().top;if(Math.abs(delta)<.5)continue;
    const animation=row.animate([{transform:`translateY(${delta}px)`},{transform:'translateY(0)'}],{duration:460,easing:'cubic-bezier(.22,.7,.25,1)'});
    timelineMotions.set(row,animation);animation.onfinish=()=>{if(timelineMotions.get(row)===animation)timelineMotions.delete(row)};
  }
}
function renderTimeline({preserve=false}={}){
  const positions=captureTimelinePositions(!preserve);
  for(const [id,controller] of bubblePacers){if(!state.items.some(item=>String(item.event_id)===id)){controller.cancel();bubblePacers.delete(id)}}
  const oldHeight=timeline.scrollHeight,oldTop=timeline.scrollTop;
  const existing=new Map([...timeline.querySelectorAll('.message-row')].map(node=>[node.id,node]));
  const dates=new Map([...timeline.querySelectorAll('.date-separator')].map(node=>[node.dataset.day,node])),nodes=[];
  let previous=null;
  for(const item of [...state.items,...(pendingThinkingItem()?[pendingThinkingItem()]:[])]){
    if(isContinuationControl(item)&&item.interaction_status!=='failed'){state.enteringEventIds.delete(String(item.event_id));continue}
    if(!previous||!sameDay(previous.recorded_at,item.recorded_at)){
      const day=localDay(item.recorded_at),separator=dates.get(day)||document.createElement('div');
      dates.delete(day);separator.className='date-separator';separator.dataset.day=day;separator.textContent=day;nodes.push(separator);
    }
    const fingerprint=timelineItemFingerprint(item),old=existing.get(`message-${item.event_id}`),row=old?.dataset.fingerprint===fingerprint?old:renderMessage(item);
    row.dataset.fingerprint=fingerprint;nodes.push(row);previous=item;
  }
  // Keep unchanged rows attached: removing/reinserting them restarts CSS animation.
  const keep=new Set(nodes);
  for(const node of timeline.querySelectorAll('.message-row,.date-separator'))if(!keep.has(node))node.remove();
  let cursor=timeline.querySelector('.message-row,.date-separator');
  for(const node of nodes){if(node===cursor)cursor=cursor.nextElementSibling;else timeline.insertBefore(node,cursor)}
  $('#emptyChat').hidden=state.items.length>0;$('#loadOlder').hidden=!state.hasMore;
  timeline.scrollTop=preserve?oldTop+timeline.scrollHeight-oldHeight:timeline.scrollHeight;
  animateTimelinePositions(positions);highlightFromHash();updateSayMore();
}
function enterBubble(bubble){bubble.classList.add('bubble-enter');bubble.addEventListener('animationend',event=>{if(event.target===bubble)bubble.classList.remove('bubble-enter')},{once:true})}
function renderMessage(item){
  const entering=state.enteringEventIds.delete(String(item.event_id));
  if(isContinuationControl(item)){const row=document.createElement('div');row.className='message-row continuation-status';row.id=`message-${item.event_id}`;row.setAttribute('role','status');const label=document.createElement('span');label.textContent='这次没接上。';const retry=document.createElement('button');retry.type='button';retry.className='quiet-button';retry.textContent='重试续聊';retry.addEventListener('click',()=>prepareFailedRetry(item));row.append(label,retry);return row}
  if(item.thinking){const row=document.createElement('div');row.className='message-row assistant thinking';row.id=`message-${item.event_id}`;row.setAttribute('role','status');row.setAttribute('aria-label','正在回复');const bubble=document.createElement('div');bubble.className='bubble typing-dots';bubble.setAttribute('aria-hidden','true');for(let n=0;n<3;n++){const dot=document.createElement('span');dot.textContent='.';bubble.append(dot)}if(entering)enterBubble(bubble);row.append(bubble);return row}
  const failed=interactionFailureLabel(item),row=document.createElement('div');
  row.className=`message-row ${item.role==='user'?'owner':'assistant'}${failed?' failed':''}`;row.id=`message-${item.event_id}`;
  const wrap=document.createElement('div');wrap.className='message-wrap';
  const stack=document.createElement('div');stack.className='bubble-stack';
  const parts=conversationBubbleParts(item),id=String(item.event_id);
  const animate=id===state.animateAssistantEventId&&canPaceReply(item,parts)&&!globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  // A re-render of a changed Event must not revive its old scheduled presentation.
  if(bubblePacers.has(id)){bubblePacers.get(id).cancel();bubblePacers.delete(id)}
  const bubbles=parts.map((part,index)=>{const bubble=document.createElement('div');bubble.className='bubble';bubble.textContent=part;bubble.hidden=animate&&index>0;if(entering&&!bubble.hidden)enterBubble(bubble);stack.append(bubble);return bubble});
  const meta=document.createElement('div');meta.className='message-meta';
  const baseLabel=item.proactive?'HAVRE 主动发来':clock(item.recorded_at),route=item.role==='assistant'?routeLabel(item):(!failed&&(item.effective_privacy_class||item.privacy_class)==='LOCAL_ONLY'?'仅本机':'');
  meta.innerHTML=`<span>${text(baseLabel)}</span>${route?`<span class="route-label">${text(route)}</span>`:''}${failed?`<span class="failure-label">${text(failed)}</span>`:''}`;
  if(item.role==='assistant'){const actions=document.createElement('span');actions.className='message-actions';actions.innerHTML=`<button data-action="helpful" aria-label="有帮助">♡</button><button data-action="feedback">反馈</button>`;actions.addEventListener('click',event=>messageAction(event,item));meta.append(actions)}
  if(retryDraft(item,'')!==null){const retry=document.createElement('button');retry.className='quiet-button';retry.type='button';retry.textContent='重试';retry.addEventListener('click',()=>prepareFailedRetry(item));meta.append(retry)}
  wrap.append(stack,meta);row.append(wrap);
  if(animate){
    const remaining=document.createElement('button');remaining.type='button';remaining.className='quiet-button remaining-reply';wrap.append(remaining);
    const controller=createBubblePacer(parts.length,index=>{
      const nearBottom=timeline.scrollHeight-timeline.scrollTop-timeline.clientHeight<100;
      const positions=captureTimelinePositions(nearBottom);
      bubbles[index].hidden=false;enterBubble(bubbles[index]);
      if(nearBottom)timeline.scrollTop=timeline.scrollHeight;
      animateTimelinePositions(positions);
    },{onChange:view=>{if(view.done)bubblePacers.delete(id);remaining.hidden=view.done;remaining.textContent=`查看余下 ${view.total-view.shown} 条`;updateSayMore();if(view.done&&state.items.at(-1)?.event_id===item.event_id&&document.visibilityState==='visible')markRead(item.event_id)}});
    bubblePacers.set(id,controller);remaining.textContent=`查看余下 ${parts.length-1} 条`;
    remaining.addEventListener('click',()=>controller.finish());updateBubblePacing();
  }
  if(id===state.animateAssistantEventId)state.animateAssistantEventId=null;
  return row;
}
async function messageAction(event,item){const action=event.target.dataset.action;if(!action)return;state.feedbackEvent=item;state.feedbackRating=action==='helpful'?'helpful':'mixed';$('#feedbackText').value=item.feedback?.reason_text||'';$('[data-rating]').forEach(choice=>choice.setAttribute('aria-pressed',String(choice.dataset.rating===state.feedbackRating)));$('#feedbackDialog').showModal()}
async function loadTimeline(
  {older=false,refreshAfterCurrent=false,silent=false,throughEventId=null}={},request=api,render=renderTimeline,mark=markRead
){
  if(older&&!state.hasMore)return;
  if(state.loading){
    if(refreshAfterCurrent){
      await state.loadingPromise;
      return loadTimeline({older:false,silent,throughEventId},request,render,mark);
    }
    return state.loadingPromise;
  }
  state.loading=true;
  const timelineEpoch=state.timelineEpoch||0;
  const operation=(async()=>{try{
    let url='/v1/timeline?limit=60';
    if(throughEventId)url+=`&through_event_id=${encodeURIComponent(throughEventId)}`;
    if(older&&state.cursor)url+=`&before_at=${encodeURIComponent(state.cursor.before_at)}&before_event_id=${state.cursor.before_event_id}`;
    const data=await request(url);if(timelineEpoch!==(state.timelineEpoch||0))return null;const items=mergeRouteEvidence(data.items),nextItems=older?[...items,...state.items]:items,changed=!state.timelineLoaded||older||!sameTimelineSnapshot(state.items,nextItems),nearBottom=!Number.isFinite(timeline.scrollHeight)||timeline.scrollHeight-timeline.scrollTop-timeline.clientHeight<100;if(state.timelineLoaded&&!older&&!throughEventId){for(const item of nextItems){if(item.role==='assistant'&&!state.items.some(old=>old.event_id===item.event_id))state.enteringEventIds.add(String(item.event_id))}}state.timelineLoaded=true;state.focusedHistory=Boolean(throughEventId)||(older&&state.focusedHistory);if($('#returnLatest'))$('#returnLatest').hidden=!state.focusedHistory&&!older;if(!older&&nextItems.some(item=>item.role==='user'&&!state.items.some(previous=>previous.event_id===item.event_id)))cancelBubblePacing();state.items=nextItems;state.cursor=data.next_cursor;state.hasMore=data.has_more;if(changed)render({preserve:older||!nearBottom});const last=state.items.at(-1);if(last&&nearBottom)mark(last.event_id);return data;
  }catch(error){if(silent)console.debug(error);else showToast(error.message);return null}finally{state.loading=false}})();
  state.loadingPromise=operation;
  try{return await operation}finally{if(state.loadingPromise===operation)state.loadingPromise=null}
}
async function markRead(eventId){const pacing=bubblePacers.get(String(eventId));if(pacing&&!pacing.snapshot().done)return;const value=String(eventId);if(state.lastReadEventId===value)return;try{await api('/v1/timeline/read',{method:'POST',body:JSON.stringify({event_id:eventId})});state.lastReadEventId=value}catch(error){if(!error.message.includes('Pair this browser'))console.debug(error)}}
function highlightFromHash(){const match=location.hash.match(/^#message-(.+)$/);if(!match)return;const node=document.getElementById(`message-${match[1]}`);if(node){node.classList.add('highlight');node.scrollIntoView({block:'center'});setTimeout(()=>node.classList.remove('highlight'),4000)}}
async function resolveDeliveryHash({refresh=true}={}){const match=location.hash.match(/^#delivery-([0-9a-f-]{36})$/);if(!match)return;try{const value=await api(`/v1/push/navigation/${match[1]}`);if(refresh)await loadTimeline({refreshAfterCurrent:true});if(!state.items.some(item=>String(item.event_id)===String(value.event_id)))await loadTimeline({refreshAfterCurrent:true,throughEventId:value.event_id});history.replaceState(null,'',`/chat#message-${value.event_id}`);highlightFromHash()}catch(error){showToast(error.message)}}
async function openNotification(locator){if(typeof locator!=='string'||!/^[0-9a-f-]{36}$/.test(locator))return;setPage('chat');history.replaceState(null,'',`/chat#delivery-${locator}`);await resolveDeliveryHash()}

function activatePendingInteraction(pending){state.pendingInteraction=pending;state.pendingPersisted=persistPendingInteraction(pending)}
function forgetActivePending(){state.pendingInteraction=null;state.pendingPersisted=false;removePendingInteraction()}
function adoptPendingSession(item){if(!item?.session_id)return;state.sessionId=String(item.session_id);storageSet(SESSION_ID_KEY,state.sessionId)}
async function resumePendingInteraction({retryAbsent=true,quiet=false}={}){const pending=state.pendingInteraction;if(!pending)return'none';const resolution=pendingResolution(pending,state.items);if(resolution.status==='terminal'){adoptPendingSession(resolution.item);forgetActivePending();if(resolution.item.interaction_status==='failed'){prepareFailedRetry(resolution.item,{focus:false})}else if(input.value.trim()===pending.body.message)input.value='';resizeInput();return'terminal'}if(resolution.status==='processing'){if(!quiet)showToast('上一条消息已收到，仍在处理中；不会重复发送。');return'processing'}const draft=input.value.trim();if(draft&&draft!==pending.body.message){showToast('上一条发送结果尚未确认；当前草稿已保留，请先等待或恢复上一条。');return'blocked'}if(pending.body.input_origin!=='continuation_button')input.value=pending.body.message;resizeInput();if(retryAbsent)await sendMessage({preventDefault(){}});return'absent'}

async function sendMessage(event,replyToEventId=null,inputOrigin='owner_text'){
  if(state.pendingInteraction?.body.input_origin==='continuation_button'&&!input.value.trim()){inputOrigin='continuation_button';replyToEventId=state.pendingInteraction.body.reply_to_event_id}
  if(!replyToEventId&&state.retryContinuation?.message===input.value.trim())replyToEventId=state.retryContinuation.eventId;
  event.preventDefault();
  const message=inputOrigin==='continuation_button'?'再说点':input.value.trim();
  if(!message||send.disabled)return;
  cancelBubblePacing();updateSayMore();
  let pending=state.pendingInteraction;
  if(pending&&(pending.body.message!==message||(pending.body.input_origin||'owner_text')!==inputOrigin)){
    const loaded=await loadTimeline({refreshAfterCurrent:true});
    const resolution=loaded==null?{status:'unknown'}:pendingResolution(pending,state.items);
    if(resolution.status==='terminal'){adoptPendingSession(resolution.item);forgetActivePending();pending=null}
    else{showToast('上一条发送结果尚未确认；当前草稿已保留，不会创建可能重复的新一轮。');return}
  }
  if(!pending){
    pending=createPendingInteraction(message,new Date().toISOString(),state.localOnly,state.sessionId);
    if(replyToEventId){pending.body.reply_to_event_id=replyToEventId;const parent=state.items.find(item=>String(item.event_id)===String(replyToEventId));if((parent?.privacy_class||parent?.effective_privacy_class)==='LOCAL_ONLY')pending.body.privacy_class='LOCAL_ONLY'}
    if(inputOrigin==='continuation_button')pending.body.input_origin=inputOrigin;
    activatePendingInteraction(pending);state.retryContinuation=null;
  }
  const localOnly=pending.body.privacy_class==='LOCAL_ONLY',createdAt=pending.body.client_created_at,privacyButton=$('#privacyMode');
  send.disabled=true;
  if(privacyButton)privacyButton.disabled=true;
  input.value='';
  resizeInput();
  $('#sendState').textContent='';
  const temporary={event_id:`temp-${crypto.randomUUID()}`,role:'user',input_origin:pending.body.input_origin,content:pending.body.message,recorded_at:createdAt,client_created_at:createdAt,proactive:false,privacy_class:pending.body.privacy_class};
  const thinking={event_id:`thinking-${crypto.randomUUID()}`,role:'assistant',thinking:true,content:thinkingLabel(),recorded_at:new Date().toISOString(),proactive:false};
  beginOptimisticTurn(temporary,thinking);
  renderTimeline();
  const clearOptimistic=()=>{state.items=state.items.filter(item=>item!==temporary&&item!==thinking);renderTimeline()};
  try{
    const outcome=await submitPendingWithReconciliation(pending,{
      reload:()=>loadTimeline({refreshAfterCurrent:true}),
    });
    if(outcome.status==='completed'){
      rememberCompletedRoute(outcome.completed);
      adoptPendingSession(outcome.completed);
      forgetActivePending();
      const loaded=await loadTimeline({refreshAfterCurrent:true});
      if(loaded==null){clearOptimistic();showToast('回复已保存，正在重新加载。')}
    }else if(outcome.status==='terminal'){
      adoptPendingSession(outcome.item);
      forgetActivePending();
      if(outcome.item.interaction_status==='completed')showToast('回复已经保存；刚才只是连接中断。');
      else prepareFailedRetry(outcome.item,{focus:false});
    }else if(outcome.status==='processing'){
      showToast('消息已收到，仍在处理中；不会重复发送。');
    }else{
      clearOptimistic();
      if(!input.value.trim()&&pending.body.input_origin!=='continuation_button')input.value=pending.body.message;
      resizeInput();
      const suffix=state.pendingPersisted?'再次发送会沿用同一请求，不会创建重复轮次。':'浏览器未能保存续传信息；请不要刷新本页。';
      showToast(`${outcome.error?.message||'发送结果暂时无法确认。'} ${suffix}`);
    }
  }finally{
    send.disabled=false;
    updatePrivacyUI();
    $('#sendState').textContent='';
    if(inputOrigin!=='continuation_button')input.focus();updateSayMore();
  }
}

async function saveFeedback(){if(!state.feedbackEvent)return;try{const existing=state.feedbackEvent.feedback;await api('/v1/feedback',{method:'POST',body:JSON.stringify({assistant_event_id:state.feedbackEvent.event_id,rating:state.feedbackRating,reason_text:$('#feedbackText').value.trim()||null,expected_revision:existing?.revision||0})});$('#feedbackDialog').close();showToast('反馈已经保存，原始回复仍会保留。');loadTimeline()}catch(error){showToast(error.message)}}

async function loadDiary(){const list=$('#diaryList');list.hidden=false;list.innerHTML='<p>正在读取每天凌晨 5 点整理的日记…</p>';$('#diaryDetail').hidden=true;try{const entries=await api('/v1/diary?limit=90');if(!entries.length){list.innerHTML='<div class="empty-state"><h1>还没有日记</h1><p>每天凌晨 5 点，HAVRE 会整理刚结束的一天；只有有意义的内容或 private 本地记录才会出现。</p></div>';return}list.innerHTML='';for(const entry of entries){const button=document.createElement('button');button.className='diary-card';button.dataset.month=String(entry.month||Number(entry.local_date.slice(5,7)));const privateNote=Number(entry.private_source_count||0)>0?` · ${Number(entry.private_source_count)} 条 private 本地记录`:'';button.innerHTML=`<span class="diary-date">${text(new Intl.DateTimeFormat('en-US',{month:'short',day:'numeric'}).format(new Date(entry.local_date+'T12:00:00')))}</span><span><h3>${text(entry.title)}</h3><p>${text(entry.preview_text)}${text(privateNote)}</p></span>`;button.onclick=()=>openDiary(entry.local_date);list.append(button)}}catch(error){showPageError(list,error,loadDiary)}}
async function openDiary(day){try{const entry=await api(`/v1/diary/${day}`),detail=$('#diaryDetail'),privateSources=collection(entry.private_sources),quality=collection(entry.quality_review),updates=entry.automatic_updates||{};const sourceBlock=entry.sources.length?`<details class="diary-sources"><summary>查看这页非私密依据（${entry.sources.length} 条）</summary><div class="transcript">${entry.sources.map(source=>`<div class="transcript-line"><time>${text(clock(source.recorded_at))}</time><div><strong>${source.role==='user'?'你':'HAVRE'}</strong><br>${text(source.content)}</div></div>`).join('')}</div></details>`:'';const privateBlock=privateSources.length?`<details class="private-transcript"><summary>Private 聊天记录（${privateSources.length} 条，仅本地，未交给 GPT 总结）</summary><div class="transcript">${privateSources.map(source=>`<div class="transcript-line"><time>${text(clock(source.recorded_at))}</time><div><strong>${source.role==='user'?'你':'HAVRE'} · ${text(source.privacy_class)}</strong><br>${text(source.content)}</div></div>`).join('')}</div></details>`:'';const audit=(quality.length||updates.memory||updates.user_model)?`<details class="diary-audit"><summary>关于这次回顾</summary><p>这次回顾也检查了我们的聊天${quality.length?`，记录 ${quality.length} 条改进建议`:''}${updates.memory||updates.user_model?`；自动更新 ${Number(updates.memory||0)} 条记忆、${Number(updates.user_model||0)} 条理解`:''}。修改建议已留在本机，等你决定是否用于改进系统。</p></details>`:'';detail.innerHTML=`<button class="text-button" id="backDiary">← 返回日记</button><p class="eyebrow">${text(entry.local_date)}</p><h2>${text(entry.title)}</h2><p>${text(entry.summary_text)}</p><p class="message-meta">${entry.finalized_at?'已在跨日后定稿':'今天继续聊天时会安全更新'} · ${entry.sources.length} 条非私密依据</p>${audit}${privateBlock}${sourceBlock}`;$('#diaryList').hidden=true;detail.hidden=false;$('#backDiary').onclick=()=>{detail.hidden=true;$('#diaryList').hidden=false}}catch(error){showToast(error.message)}}

function collection(value){return Array.isArray(value)?value:value?Object.values(value):[]}
function memoryContent(kind,item){
  if(kind==='Belief')return item.revision?.statement||'还没有可读表述';
  return item.content_text||item.statement||item.title||item.summary||item.summary_text||'未提供可读内容';
}
function memorySource(kind,item){
  if(kind==='Memory')return item.created_by==='owner_delegated_gpt'?'这是我从我们非私密的聊天里认真记下来的；你随时可以纠正或删除。':'这是你确认过、希望我以后能自然记起的事。';
  if(kind==='Proposal')return '我觉得这件事也许值得记住，但先由你决定。';
  if(kind==='Belief')return item.effective_status==='candidate'?'这是我对你的一个暂时理解，等你确认。':'这是目前用来更好理解你的信息；不对时可以改。';
  return item.status?`现在：${item.status}`:'';
}
function memoryTiming(kind,item,now=Date.now()){
  const revision=kind==='Belief'?(item.revision||{}):item,parts=[];
  const created=revision.created_at||revision.learned_at;
  if(created&&!Number.isNaN(Date.parse(created)))parts.push(`更新于 ${new Date(created).toLocaleDateString('zh-CN')}`);
  if(Number(revision.revision)>1)parts.push(`第 ${Number(revision.revision)} 版 · 已保留先前记录`);
  const from=Date.parse(revision.valid_from),to=Date.parse(revision.valid_to);
  if(Number.isFinite(to)&&to<now)parts.push('适用期已结束');
  else if(Number.isFinite(from)&&from>now)parts.push(`从 ${new Date(from).toLocaleDateString('zh-CN')} 起适用`);
  else if(Number.isFinite(to))parts.push(`适用至 ${new Date(to).toLocaleDateString('zh-CN')}`);
  return parts.join(' · ');
}
function sourcePreview(item){
  const sources=collection(item.source_previews);
  if(!sources.length)return '<p class="message-meta">暂无可展开的原始对话来源。</p>';
  return `<details class="memory-sources"><summary>从那次聊天记下的 · ${sources.length} 条依据</summary>${sources.map(source=>{
    const match=String(source.source_ref||'').match(/^event\/([0-9a-f-]{36})$/);
    const jump=match?`<button class="text-button" data-source-event="${match[1]}">回到这段聊天</button>`:'';
    return `<div class="memory-source"><p class="message-meta">${text(new Date(source.recorded_at).toLocaleString())} · ${source.event_type==='USER_MESSAGE'?'你当时说':'HAVRE 当时说'}</p><p>${text(source.content||'来源已擦除或没有可显示文字')}</p>${jump}</div>`;
  }).join('')}</details>`;
}
async function openSourceEvent(eventId){
  if(!/^[0-9a-f-]{36}$/.test(eventId))return;
  setPage('chat');
  history.replaceState(null,'',`/chat#message-${eventId}`);
  const data=await loadTimeline({refreshAfterCurrent:true,throughEventId:eventId});
  if(data)highlightFromHash();
}
function kindLabel(kind){return({Memory:'我记得',Proposal:'等你确认',Belief:'我对你的理解'}[kind]||kind)}
function memoryCard(kind,item){
  const id=item.memory_id||item.candidate_id||item.revision?.belief_id||item.goal_id||item.proposal_id||'';
  const canMutate=state.settings?.auth_capabilities?.mutate_memory!==false;
  const content=memoryContent(kind,item);
  let actions='',contentMarkup=`<h3>${text(content)}</h3>`;
  if(canMutate&&kind==='Memory'&&item.memory_id)actions=`<div class="card-actions"><button data-memory-to-belief="${id}">加入对我的理解</button><button data-memory-correct="${id}">纠正</button><button data-memory-delete="${id}">不再参考</button></div>`;
  if(canMutate&&kind==='Proposal'&&item.candidate_id){contentMarkup=`<label class="proposal-label">确认前可改写<textarea class="proposal-editor" rows="3">${text(content)}</textarea></label>`;actions=`<div class="card-actions"><button data-candidate-accept="${id}">按这段确认</button><button data-candidate-reject="${id}">不记这个</button></div>`;}
  if(canMutate&&kind==='Belief'&&item.effective_status==='candidate')actions=`<div class="card-actions"><button data-belief-accept="${id}" data-belief-revision="${item.revision?.revision}">确认这个理解</button><button data-belief-reject="${id}" data-belief-revision="${item.revision?.revision}">拒绝</button></div>`;
  if(canMutate&&kind==='Belief'&&item.effective_status==='active')actions=`<div class="card-actions"><button data-belief-reject="${id}" data-belief-revision="${item.revision?.revision}">这个理解不对</button></div>`;
  return `<article class="memory-card"><span class="kind">${text(kindLabel(kind))}</span>${contentMarkup}<p class="message-meta">${text(memoryTiming(kind,item))}</p><p>${text(memorySource(kind,item))}</p>${sourcePreview(item)}${actions}</article>`;
}
function goalStatus(value){return({active:'进行中',paused:'暂时放下',completed:'已完成',abandoned:'已结束'}[value]||value||'')}
function goalCard(item){const next=item.next_action?`<p><strong>下一步：</strong>${text(item.next_action)}</p>`:'',due=item.review_at?`<p><strong>想再看一眼：</strong>${text(new Date(item.review_at).toLocaleString())}</p>`:'';return `<article class="memory-card goal-card"><span class="kind">${text(item.task_type==='exam'?'考试':'目标')}</span><h3>${text(item.task_name||item.title)}</h3>${item.course_name?`<p>${text(item.course_name)}</p>`:''}${next}${due}<p>${text(goalStatus(item.status))}</p></article>`}
function renderGoalGroups(goals){const courses=goals.filter(item=>item.display_category==='course'),other=goals.filter(item=>item.display_category!=='course');const courseNames=[...new Set(courses.map(item=>item.course_name||'课程'))];const courseHtml=courseNames.map(name=>{const items=courses.filter(item=>(item.course_name||'课程')===name);return `<section class="goal-subgroup"><h3>${text(name)}</h3>${items.map(goalCard).join('')}</section>`}).join('');return `<details class="memory-group"><summary><span>课程 · 作业与考试</span><small>${courses.length}</small></summary><div>${courses.length?courseHtml:'<p class="message-meta">当前没有课程目标。</p>'}</div></details><details class="memory-group"><summary><span>其他目标</span><small>${other.length}</small></summary><div>${other.length?other.map(goalCard).join(''):'<p class="message-meta">你在聊天里明确告诉我想记录什么后，目标会出现在这里。</p>'}</div></details>`}
async function loadMemory(){
  const root=$('#memoryContent');root.innerHTML='<p>正在读取 HAVRE 的理解…</p>';
  try{
    const data=await api('/v1/product/memory'),status=data.understanding_status||{};
    const jobs=status.realtime_jobs||{},progress=jobs.retrying?'最近的记忆整理暂时受阻，原始聊天仍在；系统会重试。':jobs.pending?'正在整理最近的聊天，稍后会更新在这里。':'';const explanation=progress||(status.explanation||'这里是我目前真正记得、或正在向你确认的事情。');
    const canMutate=state.settings?.auth_capabilities?.mutate_memory!==false;
    const groups=[['等你确认',collection(data.memory_candidates),'Proposal',true],['我记得的事',collection(data.memories),'Memory',true],['我对你的理解',collection(data.beliefs).filter(item=>['active','candidate'].includes(item.effective_status)),'Belief',true]];
    const reviewNote=!canMutate&&(collection(data.memory_candidates).length||collection(data.beliefs).some(item=>item.effective_status==='candidate'))?'<p class="review-gate">这台设备只能查看，不能完成持久审核。</p>':'';
    root.innerHTML=`<section class="memory-card understanding-card"><span class="kind">HAVRE 记得</span><p>${text(explanation)}</p>${reviewNote}</section>`+groups.map(([title,items,kind,open])=>`<details class="memory-group"${open?' open':''}><summary><span>${text(title)}</span><small>${items.length}</small></summary><div>${items.length?items.map(item=>memoryCard(kind,item)).join(''):'<p class="message-meta">当前没有这一类记录。</p>'}</div></details>`).join('')+renderGoalGroups(collection(data.goals));
    root.onclick=memoryAction;filterMemory();
  }catch(error){showPageError(root,error,loadMemory);}
}
async function memoryAction(event){
  const sourceButton=event.target.closest('[data-source-event]');
  if(sourceButton){await openSourceEvent(sourceButton.dataset.sourceEvent);return;}
  const correct=event.target.dataset.memoryCorrect,remove=event.target.dataset.memoryDelete,accept=event.target.dataset.candidateAccept,reject=event.target.dataset.candidateReject,toBelief=event.target.dataset.memoryToBelief,beliefAccept=event.target.dataset.beliefAccept,beliefReject=event.target.dataset.beliefReject;
  if(!correct&&!remove&&!accept&&!reject&&!toBelief&&!beliefAccept&&!beliefReject)return;
  try{
    if(correct){const edit=await editMemoryText('纠正这段记忆',event.target.closest('.memory-card')?.querySelector('h3')?.textContent||'');if(!edit)return;const content=edit.text;await api(`/v1/memories/${correct}/correct`,{method:'POST',body:JSON.stringify({content_text:content,reason:'Owner correction from Daily Companion Memory view'})});}
    else if(remove){if(!confirm('不再把这条当作当前记忆？原始聊天和修订记录仍会保留。'))return;await api(`/v1/memories/${remove}/retract`,{method:'POST',body:JSON.stringify({reason:'Owner retraction from Daily Companion Memory view'})});}
    else if(accept){const content=event.target.closest('.memory-card')?.querySelector('.proposal-editor')?.value.trim();if(!content)return;await api(`/v1/memory/candidates/${accept}/accept`,{method:'POST',body:JSON.stringify({reason:'Owner accepted from Daily Companion Memory view',importance:null,content_text:content})});}
    else if(reject){await api(`/v1/memory/candidates/${reject}/reject`,{method:'POST',body:JSON.stringify({reason:'Owner rejected from Daily Companion Memory view'})});}
    else if(toBelief){const initial=event.target.closest('.memory-card')?.querySelector('h3')?.textContent||'',edit=await editMemoryText('让我更了解你',initial,{belief:true});if(!edit)return;const statement=edit.text,preference=edit.kind==='preference';await api(`/v1/product/memory/${toBelief}/user-model-proposal`,{method:'POST',body:JSON.stringify({statement,belief_type:preference?'preference':'fact',confidence:.7,reason:'Owner proposed from confirmed Memory view'})});}
    else if(beliefAccept||beliefReject){const id=beliefAccept||beliefReject,revision=Number(event.target.dataset.beliefRevision);await api(`/v1/user-model/beliefs/${id}/transitions`,{method:'POST',body:JSON.stringify({revision,transition_type:beliefAccept?'activated':'invalidated',reason:beliefAccept?'Owner activated from Daily Companion Memory view':'Owner rejected from Daily Companion Memory view',evidence:[]})});}
    showToast('记好了，之后会按你修正的理解来。');loadMemory();
  }catch(error){showToast(error.message);}
}

async function createPair(){try{const value=await api('/v1/devices/pair',{method:'POST'});const result=$('#pairCreateResult');result.hidden=false;result.innerHTML=`<strong>临时代码：${text(value.code)}</strong><br><small>Pairing ID<br>${text(value.pairing_id)}</small><br><small>${new Date(value.expires_at).toLocaleTimeString()} 前有效，仅能使用一次。</small>`;$('#pairingId').value=value.pairing_id;$('#pairingCode').value=value.code}catch(error){showToast(error.message)}}
async function claimPair(){try{await api('/v1/devices/pair/claim',{method:'POST',body:JSON.stringify({pairing_id:$('#pairingId').value.trim(),code:$('#pairingCode').value.trim(),display_name:$('#deviceName').value.trim(),device_kind:/iPhone|iPad/i.test(navigator.userAgent)?'iphone':'browser'})});$('#pairDialog').close();showToast('这台设备已安全绑定。');await loadTimeline();loadSettings()}catch(error){showToast(error.message)}}
async function revokeDevice(id){try{await api(`/v1/devices/${id}/revoke`,{method:'POST'});showToast('已断开这台设备，也关闭了它的通知。');loadSettings()}catch(error){showToast(error.message)}}
function urlBase64ToUint8Array(value){const padding='='.repeat((4-value.length%4)%4),base64=(value+padding).replace(/-/g,'+').replace(/_/g,'/'),raw=atob(base64);return Uint8Array.from([...raw].map(char=>char.charCodeAt(0)))}
async function enablePush(){try{if(!('serviceWorker'in navigator)||!('PushManager'in window)||!('Notification'in window))throw new Error('这个浏览器不支持 Web Push。');const registration=await navigator.serviceWorker.ready;const existing=await registration.pushManager.getSubscription();const savedId=storageGet(PUSH_SUBSCRIPTION_ID_KEY);if(existing){if(savedId)await api(`/v1/push/subscriptions/${savedId}/revoke`,{method:'POST'});await existing.unsubscribe();storageRemove(PUSH_SUBSCRIPTION_ID_KEY);showToast('已关闭这台设备的通知。');return loadSettings()}const config=await api('/v1/pwa/config');if(!config.web_push_available)throw new Error('通知暂时不可用，聊天仍可正常使用。');const permission=await Notification.requestPermission();if(permission!=='granted')throw new Error('通知权限没有开启。');const subscription=await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:urlBase64ToUint8Array(config.vapid_public_key)});const json=subscription.toJSON();const saved=await api('/v1/push/subscriptions',{method:'POST',body:JSON.stringify({endpoint:json.endpoint,p256dh:json.keys.p256dh,auth:json.keys.auth,expires_at:json.expirationTime?new Date(json.expirationTime).toISOString():null,preview_level:'private'})});const remembered=storageSet(PUSH_SUBSCRIPTION_ID_KEY,saved.subscription_id);showToast(remembered?'已为这台设备开启通知；锁屏只显示有新消息。':'通知已开启，但浏览器未保存设置；可在已绑定设备中关闭。');loadSettings()}catch(error){showToast(error.message)}}
async function saveReachOut(){try{const cooldown=$('#reachOutCooldown').value;await api('/v1/product/reach-out',{method:'POST',body:JSON.stringify({enabled:$('#reachOutEnabled').checked,reminders_enabled:$('#reachOutReminders').checked,friendly_check_ins_enabled:$('#reachOutFriendly').checked,cooldown_seconds:cooldown?Number(cooldown):null,quiet_start:$('#quietStart').value||null,quiet_end:$('#quietEnd').value||null})});showToast('主动联系设置已保存。');loadSettings()}catch(error){showToast(error.message)}}

async function loadSettings(){try{
  const settings=await api('/v1/product/settings');leaveAuthorizationRequiredState();state.settings=settings;updatePrivacyUI();
  const primary=settings.auth_capabilities?.owner_primary!==false;document.body.classList.toggle('paired-device',!primary);
  let devices=[];if(primary)devices=await api('/v1/devices');
  $('#calendarStatus').textContent=settings.calendar.configured?`已导入 · ${settings.calendar.status} · 最近导入 ${settings.calendar.last_import_at?new Date(settings.calendar.last_import_at).toLocaleString():'暂无记录'}`:'尚未导入课程表';
  $('#calendarToggle').checked=settings.calendar.status==='enabled';$('#calendarToggle').disabled=!primary||!settings.calendar.configured;
  $('#strongStatus').textContent=settings.brain?.reason||'回复引擎状态暂不可用。';const reach=settings.reach_out;
  $('#reachOutEnabled').checked=Boolean(reach?.global_enabled);const permissions=reach?.category_permissions||{};$('#reachOutReminders').checked=permissions.owner_reminder!=='denied';$('#reachOutFriendly').checked=permissions.relationship_follow_up==='allowed'&&permissions.conversation_continuation!=='denied';$('#reachOutFriendlyStatus').textContent=settings.relationship_initiative_active?'已经开始：聊天停一分钟时可以自然接一句；仍没回复，半小时后最多再接一句，然后停。':'自然接话暂时没有运行；这个开关仍会保留你的选择。';$('#reachOutCooldown').value=reach?.cooldown_seconds==null?'':String(reach.cooldown_seconds);
  const quiet=reach?.quiet_hours?.[0];$('#quietStart').value=quiet?.start_local?.slice(0,5)||'';$('#quietEnd').value=quiet?.end_local?.slice(0,5)||'';
  let subscribed=false;if('serviceWorker'in navigator&&'PushManager'in window){const registration=await navigator.serviceWorker.ready;subscribed=Boolean(await registration.pushManager.getSubscription())}
  $('#pushStatus').textContent=subscribed?'这台设备已登记通知。是否能收到锁屏提醒，还取决于系统权限和通知服务；锁屏不展示聊天内容。':settings.web_push_available?'可以开启通知；只有点击按钮后才会请求系统权限。':'通知暂时不可用，聊天仍可正常使用。';
  $('#enablePush').textContent=subscribed?'关闭这台设备的通知':'开启通知';
  $('#deviceList').innerHTML=primary?(devices.length?devices.map(device=>`<div class="device-row"><span>${text(device.display_name)}<small>${text(device.device_kind)} · ${device.revoked_at?'已撤销':'已连接'}</small></span>${device.revoked_at?'':`<button data-revoke-device="${device.device_id}" class="text-button">撤销</button>`}</div>`).join(''):'<p>还没有已绑定设备。</p>'):'<p>请在你的电脑上管理已绑定设备。</p>';
}catch(error){showToast(error.message)}}


function openSettings(){const sheet=$('#settingsSheet');state.settingsReturnFocus=document.activeElement;sheet.classList.add('open');sheet.setAttribute('aria-hidden','false');$('#app').inert=true;sheet.querySelector('.sheet-panel button')?.focus();loadSettings()}
function closeSettings(){const sheet=$('#settingsSheet');sheet.classList.remove('open');sheet.setAttribute('aria-hidden','true');$('#app').inert=false;state.settingsReturnFocus?.focus()}
function viewportMetrics(viewport=window.visualViewport,fallbackHeight=window.innerHeight){return{height:Math.max(1,Math.round(viewport?.height||fallbackHeight)),top:Math.max(0,Math.round(viewport?.offsetTop||0))}}
function settingsKeyboard(event){const sheet=$('#settingsSheet');if(!sheet.classList.contains('open'))return;if(event.key==='Escape'){event.preventDefault();closeSettings();return}if(event.key!=='Tab')return;const items=[...sheet.querySelectorAll('button,input,select,a[href]')].filter(el=>!el.disabled&&el.getClientRects().length);const first=items[0],last=items.at(-1);if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus()}else if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus()}}
function updateViewport(){const metrics=viewportMetrics();document.documentElement.style.setProperty('--app-height',`${metrics.height}px`);document.documentElement.style.setProperty('--app-top',`${metrics.top}px`);if(document.activeElement===input)requestAnimationFrame(()=>{window.scrollTo(0,0);timeline.scrollTop=timeline.scrollHeight})}
async function toggleCalendar(){try{const enabled=$('#calendarToggle').checked;await api('/v1/product/calendar',{method:'POST',body:JSON.stringify({enabled})});showToast(enabled?'已允许 HAVRE 参考课程安排。':'已停止在聊天中参考课程安排。');loadSettings()}catch(error){$('#calendarToggle').checked=!$('#calendarToggle').checked;showToast(error.message)}}

async function handleOnlineReconnect(load=loadTimeline,resolve=resolveDeliveryHash){
  $('#networkBanner').hidden=true;const loaded=await load({refreshAfterCurrent:true});await resolve({refresh:false});if(loaded!==null)await resumePendingInteraction();
}
function handleServiceWorkerMessage(event,open=openNotification){
  if(event.data?.type!=='HAVRE_NOTIFICATION_OPEN')return;
  event.ports[0]?.postMessage({type:'HAVRE_NOTIFICATION_OPEN_ACK',shell:PUSH_SHELL_VERSION});
  return open(event.data.delivery_locator);
}
let appUpdateVersion=null,appUpdateTimer=null,appUpdateChecking=false,lastAppUpdateCheck=0;
function canApplyAppUpdate(){
  return document.visibilityState==='visible'&&navigator.onLine!==false&&
    $('#chatPage')?.classList.contains('active')&&!state.focusedHistory&&!state.loading&&
    !send.disabled&&!state.pendingInteraction&&!pendingThinkingItem()&&input.value.length===0&&
    !document.querySelector('dialog[open],.sheet.open')&&
    !document.activeElement?.matches('input,textarea,select,[contenteditable="true"]')&&
    ![...bubblePacers.values()].some(controller=>!controller.snapshot().done)&&
    timeline.scrollHeight-timeline.scrollTop-timeline.clientHeight<=100;
}
function applyAppUpdate({manual=false}={}){
  if(!appUpdateVersion||!canApplyAppUpdate()){
    if(manual)showToast('先完成当前输入或回复，再更新；内容会留在这里。');return false;
  }
  // A failed/offline navigation must not create an automatic reload loop.
  const key='havre-last-app-update';
  if(!manual&&storageGet(key,browserSessionStorage())===appUpdateVersion)return false;
  if(!storageSet(key,appUpdateVersion,browserSessionStorage())&&!manual)return false;
  location.reload();return true;
}
function offerAppUpdate(version){
  if(!version||version===APP_VERSION)return;
  appUpdateVersion=version;const banner=$('#appUpdateBanner');if(banner)banner.hidden=false;
  clearTimeout(appUpdateTimer);appUpdateTimer=setTimeout(()=>applyAppUpdate(),2000);
}
async function handleControllerChange(){
  const controller=navigator.serviceWorker?.controller;if(!controller)return;
  const channel=new MessageChannel();
  const version=await new Promise(resolve=>{
    const timer=setTimeout(()=>{channel.port1.close();resolve(null)},2000);
    channel.port1.onmessage=event=>{clearTimeout(timer);channel.port1.close();resolve(event.data?.type==='HAVRE_APP_VERSION'?event.data.version:null)};
    try{controller.postMessage({type:'HAVRE_APP_VERSION'},[channel.port2])}catch{clearTimeout(timer);channel.port1.close();resolve(null)}
  });
  offerAppUpdate(version);
}
async function checkAppUpdate({force=false}={}){
  if(!('serviceWorker'in navigator)||document.visibilityState!=='visible'||navigator.onLine===false||appUpdateChecking)return;
  if(!force&&Date.now()-lastAppUpdateCheck<60000)return;
  appUpdateChecking=true;lastAppUpdateCheck=Date.now();
  try{const registration=await navigator.serviceWorker.getRegistration();if(registration)await registration.update();await handleControllerChange()}
  catch{/* Offline update checks leave the installed shell available. */}
  finally{appUpdateChecking=false}
}
async function initializeTimeline(load=loadTimeline,resolve=resolveDeliveryHash){
  const loaded=await load();await resolve({refresh:false});if(loaded!==null)await resumePendingInteraction();
}
function shouldRefreshVisibleTimeline({visibility=globalThis.document?.visibilityState,online=globalThis.navigator?.onLine,chatActive=$('#chatPage')?.classList?.contains('active'),loading=state.loading,sending=send.disabled,readingHistory=Number.isFinite(timeline.scrollHeight)&&timeline.scrollHeight-timeline.scrollTop-timeline.clientHeight>100}={}){return visibility==='visible'&&online!==false&&chatActive&&!loading&&!sending&&!readingHistory&&!state.focusedHistory}
async function refreshVisibleTimeline(load=loadTimeline,conditions={}){if(!shouldRefreshVisibleTimeline(conditions))return false;const loaded=await load({refreshAfterCurrent:true,silent:true});if(loaded!==null)await resumePendingInteraction({retryAbsent:false,quiet:true});return loaded!==null}
if(globalThis.__HAVRE_PWA_TEST_MODE__){
  globalThis.__HAVRE_PWA_TIMELINE_TEST__={beginOptimisticTurn,items:()=>state.items,setState:value=>Object.assign(state,value)};
  globalThis.__HAVRE_PWA_TEST__={APP_VERSION,canApplyAppUpdate,applyAppUpdate,offerAppUpdate,checkAppUpdate,state,isContinuationControl,pendingThinkingItem,continuationRetryAvailable,bubblePacers,createBubblePacer,canPaceReply,sayMoreAvailable,sayMore,renderMessage,renderTimeline,cancelBubblePacing,updateBubblePacing,updateSayMore,memoryTiming,sourcePreview,withRequestDeadline,retryDraft,authorizationRequiredMessage,buildInteractionBody,configuredRoute,conversationBubbleParts,createPendingInteraction,handleControllerChange,handleOnlineReconnect,handleServiceWorkerMessage,initializeTimeline,intendedRouteLabel,interactionFailureLabel,isLoopbackHost,localRouteAvailable,loadTimeline,mergeRouteEvidence,pendingMatchesTimelineItem,pendingResolution,persistLocalOnly,persistPendingInteraction,privacyModeNotice,readLocalOnly,readPendingInteraction,refreshVisibleTimeline,removePendingInteraction,resizeInput,routeLabel,sameTimelineSnapshot,shouldRefreshVisibleTimeline,storageGet,storageRemove,storageSet,submitPendingInteraction,submitPendingWithReconciliation,thinkingLabel,timelineItemFingerprint,validPendingInteraction,viewportMetrics};
  return;
}
$('#applyAppUpdate')?.addEventListener('click',()=>applyAppUpdate({manual:true}));
$('#sayMoreButton').addEventListener('click',sayMore);
document.addEventListener('visibilitychange',updateBubblePacing);
$('#memorySearch').addEventListener('input',filterMemory);
document.addEventListener('keydown',settingsKeyboard);

$$('[data-page]').forEach(button=>button.addEventListener('click',()=>{closeSettings();setPage(button.dataset.page)}));$('#settingsButton').onclick=openSettings;$$('[data-close-sheet]').forEach(button=>button.onclick=closeSettings);$('#composer').addEventListener('submit',sendMessage);$('#privacyMode').onclick=()=>setLocalOnly(!state.localOnly,{announce:true});input.addEventListener('input',()=>{state.retryContinuation=null;resizeInput();updateViewport();updateBubblePacing();updateSayMore()});input.addEventListener('focus',updateViewport);input.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing){event.preventDefault();$('#composer').requestSubmit()}});$('#returnLatest').onclick=()=>{history.replaceState(null,'','/chat');loadTimeline({refreshAfterCurrent:true})};$('#loadOlder').onclick=()=>loadTimeline({older:true});$('#historySentinel').addEventListener('mouseenter',()=>state.hasMore&&loadTimeline({older:true}));$('#saveFeedback').onclick=saveFeedback;$$('[data-rating]').forEach(button=>button.onclick=event=>{event.preventDefault();state.feedbackRating=button.dataset.rating;$('[data-rating]').forEach(choice=>choice.setAttribute('aria-pressed',String(choice===button)))});$('#addDevice').onclick=()=>$('#pairDialog').showModal();$('#createPairCode').onclick=createPair;$('#claimDevice').onclick=claimPair;$('#enablePush').onclick=enablePush;$('#saveReachOut').onclick=saveReachOut;$('#calendarToggle').onchange=toggleCalendar;$('#deviceList').onclick=event=>event.target.dataset.revokeDevice&&revokeDevice(event.target.dataset.revokeDevice);$('#strongInfo').onclick=()=>showToast(state.settings?.brain?.reason||'回复引擎状态暂不可用。');
window.addEventListener('online',()=>handleOnlineReconnect());window.addEventListener('offline',()=>$('#networkBanner').hidden=false);window.addEventListener('hashchange',()=>{if(['#diary','#memory'].includes(location.hash))setPage(location.hash.slice(1));else if(location.hash.startsWith('#delivery-'))resolveDeliveryHash();else highlightFromHash()});window.visualViewport?.addEventListener('resize',updateViewport);window.visualViewport?.addEventListener('scroll',updateViewport);window.addEventListener('resize',updateViewport);window.addEventListener('beforeinstallprompt',event=>{event.preventDefault();state.installPrompt=event;$('#installPwa').hidden=false});$('#installPwa').onclick=async()=>{if(state.installPrompt){state.installPrompt.prompt();await state.installPrompt.userChoice;state.installPrompt=null;$('#installPwa').hidden=true}};
updatePrivacyUI();updateViewport();if('serviceWorker'in navigator){navigator.serviceWorker.addEventListener('message',handleServiceWorkerMessage);navigator.serviceWorker.addEventListener('controllerchange',()=>handleControllerChange());navigator.serviceWorker.register('/service-worker.js',{updateViaCache:'none'}).then(()=>checkAppUpdate({force:true})).catch(()=>{})}const initial=['#diary','#memory'].includes(location.hash)?location.hash.slice(1):'chat';setPage(initial);loadSettings();initializeTimeline();setInterval(()=>refreshVisibleTimeline(),4000);document.addEventListener('visibilitychange',()=>{refreshVisibleTimeline();checkAppUpdate()});window.addEventListener('online',()=>checkAppUpdate({force:true}));setInterval(()=>{checkAppUpdate();if(appUpdateVersion)applyAppUpdate()},60000);
})();
