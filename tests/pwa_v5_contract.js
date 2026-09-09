'use strict';

const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const root = path.resolve(__dirname, '..');
const locator = '01a044b7-b929-7d1a-a703-055553740f35';

async function testClientBehavior() {
  const appSource = fs.readFileSync(path.join(root, 'apps/web/havre-app.js'), 'utf8');
  assert.ok(appSource.includes('createBubblePacer'));
  assert.ok(appSource.includes("reminders_enabled:$('#reachOutReminders').checked"));
  assert.ok(appSource.includes("friendly_check_ins_enabled:$('#reachOutFriendly').checked"));
  assert.ok(appSource.includes('settings.relationship_initiative_active'));
  assert.ok(appSource.includes('setInterval(()=>refreshVisibleTimeline(),4000)'));
  const elements = {'#messageInput': {value:''}, '#sendButton': {disabled:false}};
  const context = {
    __HAVRE_PWA_TEST_MODE__: true,
    document: {querySelector: selector => elements[selector] ||= {}, querySelectorAll: () => []},
    location: {hostname: '127.0.0.1'},
    localStorage: {getItem: () => null, setItem: () => {}},
    AbortController, setTimeout, clearTimeout,
    console,
  };
  vm.runInNewContext(appSource, context, {filename: 'havre-app.js'});
  const hooks = context.__HAVRE_PWA_TEST__;
  assert.ok(hooks);
  // Fake time proves cancellation rather than merely inspecting a duration literal.
  let now=0,nextTimer=0;const timers=new Map(),revealed=[];
  const schedule=(callback,delay)=>{const id=++nextTimer;timers.set(id,{callback,at:now+delay});return id};
  const clear=id=>timers.delete(id);
  const advance=milliseconds=>{const until=now+milliseconds;while(true){const due=[...timers].filter(([,v])=>v.at<=until).sort((a,b)=>a[1].at-b[1].at)[0];if(!due)break;now=due[1].at;timers.delete(due[0]);due[1].callback()}now=until};
  const pacer=hooks.createBubblePacer(3,index=>revealed.push(index),{schedule,clear});
  advance(3999);assert.deepStrictEqual(revealed,[]);
  advance(1);assert.deepStrictEqual(revealed,[1]);
  pacer.pause();advance(30000);assert.deepStrictEqual(revealed,[1]);
  pacer.resume();advance(3999);assert.deepStrictEqual(revealed,[1]);
  pacer.cancel();advance(30000);pacer.resume();advance(30000);
  assert.deepStrictEqual(revealed,[1]);assert.strictEqual(timers.size,0);
  pacer.finish();assert.deepStrictEqual(revealed,[1,2]);assert.strictEqual(pacer.snapshot().done,true);
  const ordinary={role:'assistant',response_policy_category:'ordinary',request_id:'r',session_id:'s',event_id:'e',content:'第一句。\n\n第二句。'};
  assert.strictEqual(hooks.canPaceReply(ordinary,['第一句。','第二句。']),true);
  for(const change of [{proactive:true},{response_policy_category:null},{response_policy_category:'urgent_safety'},{role:'user'}]){
    assert.strictEqual(hooks.canPaceReply({...ordinary,...change},['一','二']),false);
  }
  assert.strictEqual(hooks.canPaceReply(ordinary,['一'.repeat(400),'二']),false);
  assert.strictEqual(hooks.isContinuationControl({role:'user',content:'再说点'}),false);
  assert.strictEqual(hooks.isContinuationControl({role:'user',input_origin:'continuation_button'}),true);
  const tap=hooks.createPendingInteraction('再说点','2026-09-08T23:00:00Z',false,'session','key');
  tap.body.input_origin='continuation_button';
  assert.strictEqual(hooks.validPendingInteraction(tap),false);
  tap.body.reply_to_event_id='parent';
  assert.strictEqual(hooks.validPendingInteraction(tap),true);
  const tapRow={role:'user',content:'再说点',request_id:'r',session_id:'session',privacy_class:'NORMAL',client_created_at:tap.body.client_created_at,reply_to_event_id:'parent'};
  assert.strictEqual(hooks.pendingMatchesTimelineItem(tap,tapRow),false);
  assert.strictEqual(hooks.pendingMatchesTimelineItem(tap,{...tapRow,input_origin:'continuation_button'}),true);
  const ready={busy:false,draft:'',sessionId:'s',pending:null,focused:false};
  assert.strictEqual(hooks.sayMoreAvailable([ordinary],ready),true);
  for(const change of [{busy:true},{draft:'还没发出的草稿'},{sessionId:'other'},{pending:{}},{focused:true}]){
    assert.strictEqual(hooks.sayMoreAvailable([ordinary],{...ready,...change}),false);
  }
  assert.strictEqual(hooks.sayMoreAvailable([{...ordinary,proactive:true}],ready),false);
  assert.strictEqual(hooks.sayMoreAvailable([{role:'user'}],ready),false);
  // An unread reply is expanded locally; no second request is allowed.
  hooks.state.items=[ordinary];hooks.state.sessionId='s';
  let finished=0;
  hooks.bubblePacers.set('e',{snapshot:()=>({done:false}),finish:()=>{finished++;hooks.bubblePacers.delete('e')}});
  context.fetch=()=>{throw new Error('expanding unread text must not send a request')};
  hooks.updateSayMore();assert.strictEqual(elements['#sayMoreButton'].textContent,'看完这条');
  await hooks.sayMore();assert.strictEqual(finished,1);
  assert.strictEqual(elements['#messageInput'].value,'');
  assert.strictEqual(elements['#sayMoreButton'].textContent,'再说点');

  for(const content of ['```python\nx=1\n```\n\n说明','1. 第一步\n\n2. 第二步','{"key": 42}\n\n说明']){
    assert.strictEqual(hooks.conversationBubbleParts({role:'assistant',content}).length,1);
  }

  assert.ok(hooks.memoryTiming('Memory',{revision:2,created_at:'2026-09-01T12:00:00Z'}).includes('第 2 版'));
  assert.ok(!hooks.memoryTiming('Memory',{created_at:'2020-01-01T00:00:00Z'}).includes('适用期已结束'));
  assert.ok(hooks.memoryTiming('Memory',{valid_to:'2020-01-01T00:00:00Z'}).includes('适用期已结束'));
  const sourceMarkup=hooks.sourcePreview({source_previews:[{source_ref:`event/${locator}`,event_type:'USER_MESSAGE',recorded_at:'2026-09-01T12:00:00Z',content:'<script>private source</script>'}]});
  assert.ok(sourceMarkup.includes(`data-source-event="${locator}"`));
  assert.ok(sourceMarkup.includes('你当时说'));
  assert.ok(!sourceMarkup.includes('<script>private source</script>'));

  assert.ok(appSource.includes('await loadTimeline({refreshAfterCurrent:true})'));
  assert.strictEqual(hooks.isLoopbackHost({hostname: '127.0.0.1'}), true);
  assert.strictEqual(hooks.isLoopbackHost({hostname: 'localhost'}), true);
  assert.strictEqual(hooks.isLoopbackHost({hostname: '::1'}), true);
  assert.strictEqual(hooks.isLoopbackHost({hostname: 'owner.tailnet.ts.net'}), false);
  assert.ok(hooks.authorizationRequiredMessage(true).includes('start_havre_desktop.ps1'));
  assert.ok(hooks.authorizationRequiredMessage(false).includes('安全绑定'));

  const normal = hooks.buildInteractionBody('你好', '2026-09-03T12:00:00Z', false, null);
  const localOnly = hooks.buildInteractionBody(
    '只留在本机', '2026-09-03T12:00:01Z', true, 'session-local',
  );
  assert.strictEqual(normal.privacy_class, 'NORMAL');
  assert.strictEqual(normal.memory_eligible, true);
  assert.strictEqual(localOnly.privacy_class, 'LOCAL_ONLY');
  assert.strictEqual(localOnly.session_id, 'session-local');

  const saved = new Map();
  const storage = {
    getItem: key => saved.get(key) ?? null,
    setItem: (key, value) => saved.set(key, value),
  };
  hooks.persistLocalOnly(true, storage);
  assert.strictEqual(hooks.readLocalOnly(storage), true);
  hooks.persistLocalOnly(false, storage);
  assert.strictEqual(hooks.readLocalOnly(storage), false);
  assert.strictEqual(hooks.storageGet('missing', storage), null);
  assert.strictEqual(hooks.storageSet('key', 'value', storage), true);
  assert.strictEqual(hooks.storageGet('key', storage), 'value');
  const blockedStorage = {
    getItem: () => {throw new Error('SecurityError');},
    setItem: () => {throw new Error('QuotaExceededError');},
    removeItem: () => {throw new Error('SecurityError');},
  };
  assert.strictEqual(hooks.readLocalOnly(blockedStorage), false);
  assert.strictEqual(hooks.persistLocalOnly(true, blockedStorage), false);
  assert.strictEqual(hooks.storageGet('key', blockedStorage), null);
  assert.strictEqual(hooks.storageSet('key', 'value', blockedStorage), false);
  assert.strictEqual(hooks.storageRemove('key', blockedStorage), false);
  const pendingStorageValues = new Map();
  const pendingStorage = {
    getItem: key => pendingStorageValues.get(key) ?? null,
    setItem: (key, value) => pendingStorageValues.set(key, value),
    removeItem: key => pendingStorageValues.delete(key),
  };
  const pending = hooks.createPendingInteraction(
    '断线后仍然只创建一轮',
    '2026-09-03T12:00:02.000Z',
    false,
    null,
    'pending-idempotency-key',
  );
  assert.strictEqual(pending.body.privacy_class, 'NORMAL');
  assert.strictEqual(hooks.persistPendingInteraction(pending, pendingStorage), true);
  await assert.rejects(
    hooks.submitPendingInteraction(pending, async () => ({ok: false, status: 401})),
    /start_havre_desktop\.ps1/,
  );
  assert.strictEqual(
    hooks.readPendingInteraction(pendingStorage).idempotency_key,
    'pending-idempotency-key',
  );
  assert.strictEqual(hooks.persistPendingInteraction(pending, blockedStorage), false);
  assert.strictEqual(hooks.readPendingInteraction(blockedStorage), null);
  assert.strictEqual(hooks.removePendingInteraction(blockedStorage), false);
  const committedUser = {
    event_id: 'user-committed',
    request_id: 'request-committed',
    session_id: 'server-created-session',
    role: 'user',
    content: pending.body.message,
    client_created_at: '2026-09-03T12:00:02+00:00',
    privacy_class: 'NORMAL',
    interaction_status: 'completed',
  };
  assert.strictEqual(hooks.pendingMatchesTimelineItem(pending, committedUser), true);
  const continuation=hooks.createPendingInteraction('再说点',pending.body.client_created_at,false,'s','continue-once');
  continuation.body.reply_to_event_id='bound-parent';
  hooks.persistPendingInteraction(continuation,pendingStorage);
  const restored=hooks.readPendingInteraction(pendingStorage);
  assert.strictEqual(restored.body.reply_to_event_id,'bound-parent');
  const continuedUser={...committedUser,content:'再说点',session_id:'s',reply_to_event_id:'bound-parent',privacy_class:'LOCAL_ONLY'};
  assert.strictEqual(hooks.pendingMatchesTimelineItem(restored,continuedUser),true);
  assert.strictEqual(hooks.pendingMatchesTimelineItem(restored,{...continuedUser,reply_to_event_id:'another-parent'}),false);
  const sent=[];
  await assert.rejects(hooks.submitPendingInteraction(restored,async (_url,options)=>{sent.push(options);throw new Error('disconnect')}),/disconnect/);
  await assert.rejects(hooks.submitPendingInteraction(restored,async (_url,options)=>{sent.push(options);throw new Error('disconnect')}),/disconnect/);
  assert.strictEqual(sent[0].body,sent[1].body);
  assert.strictEqual(JSON.parse(sent[0].body).reply_to_event_id,'bound-parent');
  assert.strictEqual(sent[0].headers['Idempotency-Key'],sent[1].headers['Idempotency-Key']);

  assert.strictEqual(
    hooks.pendingResolution(pending, [committedUser]).status,
    'terminal',
  );
  assert.strictEqual(hooks.pendingResolution(pending, [{
    ...committedUser, interaction_status: 'processing',
  }]).status, 'processing');
  assert.strictEqual(hooks.pendingResolution(pending, []).status, 'absent');

  const failed = {...committedUser, interaction_status: 'failed', memory_eligible: true, cloud_eligible: true};
  assert.strictEqual(hooks.retryDraft(failed, '').message, pending.body.message);
  assert.strictEqual(hooks.retryDraft(failed, 'my new draft'), null);
  assert.strictEqual(hooks.retryDraft({...failed, privacy_class: 'LOCAL_ONLY', cloud_eligible: false}, '').localOnly, true);
  assert.strictEqual(hooks.retryDraft({...failed, privacy_class: 'PRIVATE'}, ''), null);
  assert.strictEqual(hooks.retryDraft({...failed, cloud_eligible: false}, ''), null);
  assert.strictEqual(hooks.retryDraft({...failed, memory_eligible: false}, ''), null);
  assert.strictEqual(hooks.retryDraft(committedUser, ''), null);
  assert.strictEqual(hooks.retryDraft({...failed,reply_to_event_id:'bound-parent'},'').replyToEventId,'bound-parent');
  await assert.rejects(hooks.submitPendingInteraction(pending, async (_url, options) => ({
    ok: true, text: () => new Promise((_resolve, reject) => {
      options.signal.addEventListener('abort', () => reject(new Error('aborted')));
    }),
  }), 10), /连接等待超时/);

  const capturedRetries = [];
  let retryAttempt = 0;
  const disconnectThenComplete = async (_url, options) => {
    capturedRetries.push({
      key: options.headers['Idempotency-Key'],
      body: options.body,
    });
    retryAttempt += 1;
    if (retryAttempt === 1) {
      return {
        ok: true,
        text: async () => {throw new Error('post-commit disconnect');},
      };
    }
    return {
      ok: true,
      text: async () => [
        JSON.stringify({type: 'status', status: 'thinking'}),
        JSON.stringify({type: 'completed', interaction: {
          request_id: 'request-committed',
          session_id: 'server-created-session',
          assistant_event_id: 'assistant-committed',
        }}),
        '',
      ].join('\n'),
    };
  };
  const retried = await hooks.submitPendingWithReconciliation(pending, {
    request: disconnectThenComplete,
    reload: async () => ({items: []}),
    items: () => [],
  });
  assert.strictEqual(retried.status, 'completed');
  assert.strictEqual(capturedRetries.length, 2);
  assert.strictEqual(capturedRetries[0].key, capturedRetries[1].key);
  assert.strictEqual(capturedRetries[0].body, capturedRetries[1].body);
  assert.strictEqual(capturedRetries[0].key, pending.idempotency_key);
  assert.strictEqual(capturedRetries[0].body, JSON.stringify(pending.body));

  let committedRetryCalls = 0;
  const reconciled = await hooks.submitPendingWithReconciliation(pending, {
    request: async () => {
      committedRetryCalls += 1;
      return {
        ok: true,
        text: async () => {throw new Error('post-commit disconnect');},
      };
    },
    reload: async () => ({items: [committedUser]}),
    items: () => [committedUser],
  });
  assert.strictEqual(reconciled.status, 'terminal');
  assert.strictEqual(reconciled.item.request_id, 'request-committed');
  assert.strictEqual(committedRetryCalls, 1);
  assert.ok(hooks.privacyModeNotice(true, true).includes('保持到你主动切回'));
  assert.ok(hooks.privacyModeNotice(true, false).includes('本标签页'));
  assert.ok(hooks.privacyModeNotice(false, true).startsWith('已切回默认回复'));
  assert.ok(hooks.privacyModeNotice(false, false).includes('刷新后请重新确认'));
  assert.deepStrictEqual(
    Array.from(hooks.conversationBubbleParts({role: 'assistant', content: '一句自然回答。'})),
    ['一句自然回答。'],
  );
  assert.deepStrictEqual(
    Array.from(hooks.conversationBubbleParts({role: 'assistant', content: '先回应。\n\n再补一个有用细节。'})),
    ['先回应。', '再补一个有用细节。'],
  );
  const grouped = Array.from(hooks.conversationBubbleParts({
    role: 'assistant', content: '一。\n\n二。\n\n三。\n\n四。',
  }));
  assert.strictEqual(grouped.length, 4);
  assert.strictEqual(grouped[2], '三。');
  assert.strictEqual(grouped[3], '四。');
  const longSplit = Array.from(hooks.conversationBubbleParts({
    role: 'assistant', content: '甲。乙。丙。丁。戊。',
  }));
  assert.deepStrictEqual(longSplit, ['甲。乙。丙。丁。戊。']);
  assert.strictEqual(
    hooks.conversationBubbleParts({role: 'assistant', content: '```js\nconst a=1;\n```\n\n说明'}).length,
    1,
  );
  assert.strictEqual(
    hooks.conversationBubbleParts({role: 'user', content: '第一段\n\n第二段'}).length,
    1,
  );
  assert.deepStrictEqual(
    {...hooks.viewportMetrics({height: 520.4, offsetTop: 76.2}, 844)},
    {height: 520, top: 76},
  );
  const snapshot = [{event_id: 'event-1', role: 'assistant', content: '我在。'}];
  assert.strictEqual(hooks.sameTimelineSnapshot(snapshot, snapshot), true);
  assert.strictEqual(
    hooks.sameTimelineSnapshot(snapshot, [{...snapshot[0], content: '又想到一句。'}]),
    false,
  );
  const visibleConditions = {
    visibility: 'visible', online: true, chatActive: true,
    loading: false, sending: false,
  };
  assert.strictEqual(hooks.shouldRefreshVisibleTimeline(visibleConditions), true);
  assert.strictEqual(
    hooks.shouldRefreshVisibleTimeline({...visibleConditions, visibility: 'hidden'}),
    false,
  );
  assert.strictEqual(
    hooks.shouldRefreshVisibleTimeline({...visibleConditions, sending: true}),
    false,
  );
  assert.strictEqual(hooks.shouldRefreshVisibleTimeline({...visibleConditions, pending: {message: 'processing'}}), true);
  let pollOptions = null;
  assert.strictEqual(await hooks.refreshVisibleTimeline(async options => {
    pollOptions = options;
    return {items: []};
  }, visibleConditions), true);
  assert.strictEqual(pollOptions.refreshAfterCurrent, true);
  assert.strictEqual(pollOptions.silent, true);
  const fakeInput = {style: {}, scrollHeight: 188};
  assert.strictEqual(hooks.resizeInput(fakeInput), 140);
  assert.strictEqual(fakeInput.style.height, '140px');

  const dualSettings = {reply_routes: {
    default: {
      available: true,
      privacy_classes: ['PUBLIC', 'NORMAL'],
      provider_id: 'openai-codex-chatgpt',
      model_version_id: 'gpt-5.6-sol',
      execution_environment: 'cloud',
      label: 'GPT-5.6-sol',
    },
    local_only_available: true,
    local_only: {
      available: true,
      privacy_classes: ['PRIVATE', 'HIGHLY_PRIVATE', 'LOCAL_ONLY'],
      provider_id: 'self-hosted-openai-compatible',
      model_version_id: 'model-qwen3-8b-gguf-q4-k-m-7c41481f',
      adapter_version_id: null,
      execution_environment: 'local',
      label: 'Qwen3-8B Base',
    },
  }};
  assert.strictEqual(hooks.localRouteAvailable(dualSettings), true);
  assert.strictEqual(
    hooks.intendedRouteLabel(false, dualSettings),
    '默认 GPT-5.6-sol；上下文不适合云端时仅本机',
  );
  assert.strictEqual(
    hooks.intendedRouteLabel(true, dualSettings), 'Qwen3-8B Base · 仅本机',
  );
  assert.strictEqual(hooks.thinkingLabel(false, dualSettings), '...');
  assert.strictEqual(hooks.thinkingLabel(true, dualSettings), '...');
  assert.strictEqual(hooks.intendedRouteLabel(false, null), '正在确认回复引擎…');

  const localPrimarySettings = {reply_routes: {
    default: {
      available: true,
      privacy_classes: ['PUBLIC', 'NORMAL', 'PRIVATE', 'HIGHLY_PRIVATE', 'LOCAL_ONLY'],
      provider_id: 'deterministic-local',
      model_version_id: 'deterministic-companion-v1',
      execution_environment: 'local',
      label: 'deterministic-companion-v1',
    },
    local_only_available: true,
    local_only: {
      available: true,
      privacy_classes: ['PRIVATE', 'HIGHLY_PRIVATE', 'LOCAL_ONLY'],
      provider_id: 'deterministic-local',
      model_version_id: 'deterministic-companion-v1',
      execution_environment: 'local',
      label: 'deterministic-companion-v1',
    },
  }};
  assert.strictEqual(
    hooks.intendedRouteLabel(false, localPrimarySettings),
    'deterministic-companion-v1 · 仅本机',
  );

  const noLocalSettings = {reply_routes: {
    default: dualSettings.reply_routes.default,
    local_only_available: false,
    local_only: null,
  }};
  assert.strictEqual(hooks.localRouteAvailable(noLocalSettings), false);
  assert.strictEqual(hooks.configuredRoute(true, noLocalSettings), null);
  assert.strictEqual(
    hooks.intendedRouteLabel(true, noLocalSettings), '仅本机回复不可用',
  );
  assert.strictEqual(
    hooks.intendedRouteLabel(false, noLocalSettings),
    '默认 GPT-5.6-sol；受限上下文不会发送云端',
  );

  assert.strictEqual(hooks.routeLabel({
    provider_id: 'openai-codex-chatgpt', model_version_id: 'gpt-5.6-sol',
    execution_environment: 'cloud',
  }), 'GPT-5.6-sol · 云端');
  assert.strictEqual(hooks.routeLabel({
    provider_id: 'self-hosted-openai-compatible',
    model_version_id: 'model-qwen3-8b-gguf-q4-k-m-7c41481f',
    execution_environment: 'local',
  }), 'Qwen3-8B Base · 仅本机');
  assert.strictEqual(hooks.routeLabel({
    provider_id: 'self-hosted-openai-compatible',
    model_version_id: 'MODEL-QWEN3-8B-GGUF-Q4-K-M-7C41481F',
    adapter_version_id: 'qwen3-8b-stage9a-qlora-seed-9201',
    execution_environment: 'local',
  }), 'Qwen3-8B · qwen3-8b-stage9a-qlora-seed-9201 · 仅本机');
  assert.strictEqual(hooks.routeLabel({}), '');
  const evidence = new Map([['assistant-1', {
    provider_id: 'openai-codex-chatgpt',
    model_version_id: 'gpt-5.6-sol',
    adapter_version_id: null,
    execution_environment: 'cloud',
  }]]);
  const [merged] = hooks.mergeRouteEvidence([{
    event_id: 'assistant-1',
    provider_id: null,
    model_version_id: null,
    adapter_version_id: null,
    execution_environment: null,
    content: 'reply',
  }], evidence);
  assert.strictEqual(merged.provider_id, 'openai-codex-chatgpt');
  assert.strictEqual(merged.model_version_id, 'gpt-5.6-sol');
  assert.strictEqual(merged.execution_environment, 'cloud');
  assert.strictEqual(merged.content, 'reply');
  assert.strictEqual(hooks.interactionFailureLabel({
    role: 'user', interaction_status: 'failed', interaction_error_code: 'provider_failed',
    provider_id: 'openai-codex-chatgpt', model_version_id: 'gpt-5.6-sol',
    execution_environment: 'cloud',
  }), 'GPT-5.6-sol · 云端 未生成回复 · 本次未跨模型重试');
  assert.strictEqual(hooks.interactionFailureLabel({
    role: 'user', interaction_status: 'failed',
  }), '尚未选择回复引擎 未生成回复 · 本次未跨模型重试');
  assert.strictEqual(hooks.interactionFailureLabel({
    role: 'assistant', interaction_status: 'failed',
  }), '');
  assert.strictEqual(hooks.interactionFailureLabel({
    role: 'user', interaction_status: 'completed',
  }), '');

  assert.strictEqual(hooks.APP_VERSION,'20260908-fluid-bubbles-v21');

  let ackCount = 0;
  let openCount = 0;
  await hooks.handleServiceWorkerMessage({
    data: {type: 'HAVRE_NOTIFICATION_OPEN', delivery_locator: locator},
    ports: [{postMessage: value => {
      ackCount += 1;
      assert.strictEqual(value.shell, 'havre-shell-v5');
    }}],
  }, async value => {openCount += 1; assert.strictEqual(value, locator);});
  assert.strictEqual(ackCount, 1);
  assert.strictEqual(openCount, 1);

  let coldLoads = 0;
  let coldResolves = 0;
  await hooks.initializeTimeline(
    async () => {coldLoads += 1;},
    async options => {coldResolves += 1; assert.strictEqual(options.refresh, false);},
  );
  assert.strictEqual(coldLoads, 1);
  assert.strictEqual(coldResolves, 1);

  let failedLoads = 0;
  await assert.rejects(hooks.initializeTimeline(
    async () => {failedLoads += 1; throw new Error('offline');},
    async () => {throw new Error('must not resolve before load');},
  ), /offline/);
  assert.strictEqual(failedLoads, 1);
  let reconnectLoads = 0;
  let reconnectResolves = 0;
  await hooks.handleOnlineReconnect(
    async options => {
      reconnectLoads += 1;
      assert.strictEqual(options.refreshAfterCurrent, true);
    },
    async options => {reconnectResolves += 1; assert.strictEqual(options.refresh, false);},
  );
  assert.strictEqual(reconnectLoads, 1);
  assert.strictEqual(reconnectResolves, 1);

  let releaseFirst;
  let requests = 0;
  let renders = 0;
  const firstGate = new Promise(resolve => {releaseFirst = resolve;});
  const request = async () => {
    requests += 1;
    if (requests === 1) await firstGate;
    return {
      items: [{event_id: `event-${requests}`}],
      next_cursor: null,
      has_more: false,
    };
  };
  const firstLoad = hooks.loadTimeline({}, request, () => {renders += 1;}, () => {});
  const notificationLoad = hooks.loadTimeline(
    {refreshAfterCurrent: true}, request, () => {renders += 1;}, () => {},
  );
  await Promise.resolve();
  assert.strictEqual(requests, 1);
  releaseFirst();
  await Promise.all([firstLoad, notificationLoad]);
  assert.strictEqual(requests, 2);
  assert.strictEqual(renders, 2);
  let releaseStale;
  const stale=hooks.loadTimeline({},()=>new Promise(resolve=>{releaseStale=resolve;}),()=>{throw new Error('stale response must not repaint');},()=>{});
  const optimistic={event_id:'new-optimistic',role:'user',content:'new message'};
  context.__HAVRE_PWA_TIMELINE_TEST__.beginOptimisticTurn(optimistic,{event_id:'new-thinking'});
  releaseStale({items:[{event_id:'old-server-message'}],next_cursor:null,has_more:false});
  assert.strictEqual(await stale,null);
  assert.ok(context.__HAVRE_PWA_TIMELINE_TEST__.items().includes(optimistic));
}

function testUpdateProtectsUnfinishedWork() {
  let dialog=false,focusedInput=false,reloads=0,stored=new Map();
  const elements={
    '#chatPage':{classList:{contains:()=>true}},'#messageInput':{value:''},
    '#sendButton':{disabled:false},'#timeline':{scrollHeight:500,scrollTop:0,clientHeight:500}
  };
  const context={__HAVRE_PWA_TEST_MODE__:true,
    document:{visibilityState:'visible',activeElement:{matches:()=>focusedInput},querySelector:selector=>selector==='dialog[open],.sheet.open'?dialog:(elements[selector]||={}),querySelectorAll:()=>[]},
    navigator:{onLine:true},location:{hostname:'127.0.0.1',reload:()=>{reloads++;}},
    sessionStorage:{getItem:key=>stored.get(key)||null,setItem:(key,value)=>stored.set(key,value)},
    localStorage:{getItem:()=>null},setTimeout:()=>1,clearTimeout(){},AbortController
  };
  vm.runInNewContext(fs.readFileSync(path.join(root,'apps/web/havre-app.js'),'utf8'),context);
  const hooks=context.__HAVRE_PWA_TEST__;assert.strictEqual(hooks.canApplyAppUpdate(),true);
  const guards=[
    [()=>elements['#messageInput'].value=' ',()=>elements['#messageInput'].value=''],
    [()=>focusedInput=true,()=>focusedInput=false],
    [()=>dialog=true,()=>dialog=false],
    [()=>elements['#sendButton'].disabled=true,()=>elements['#sendButton'].disabled=false],
    [()=>hooks.state.pendingInteraction={},()=>hooks.state.pendingInteraction=null],
    [()=>hooks.state.items=[{role:'user',request_id:'r',interaction_status:'processing'}],()=>hooks.state.items=[]],
    [()=>hooks.state.loading=true,()=>hooks.state.loading=false],
    [()=>hooks.state.focusedHistory=true,()=>hooks.state.focusedHistory=false],
    [()=>elements['#timeline'].scrollTop=-200,()=>elements['#timeline'].scrollTop=0],
    [()=>context.document.visibilityState='hidden',()=>context.document.visibilityState='visible'],
    [()=>context.navigator.onLine=false,()=>context.navigator.onLine=true],
    [()=>elements['#chatPage'].classList.contains=()=>false,()=>elements['#chatPage'].classList.contains=()=>true],
    [()=>hooks.bubblePacers.set('e',{snapshot:()=>({done:false})}),()=>hooks.bubblePacers.clear()]
  ];
  hooks.offerAppUpdate('next-version');
  for(const[block,restore]of guards){block();assert.strictEqual(hooks.canApplyAppUpdate(),false);assert.strictEqual(hooks.applyAppUpdate(),false);assert.strictEqual(reloads,0);restore();}
  assert.strictEqual(hooks.applyAppUpdate(),true);assert.strictEqual(reloads,1);
  assert.strictEqual(hooks.applyAppUpdate(),false,'automatic reload must not loop for the same version');
  assert.strictEqual(hooks.applyAppUpdate({manual:true}),true);
  hooks.offerAppUpdate('another-version');context.sessionStorage.setItem=()=>{throw new Error('blocked storage');};
  assert.strictEqual(hooks.applyAppUpdate(),false,'no reload-loop protection means no automatic reload');
}

async function runServiceWorkerClick(ackShell) {
  const workerSource = fs.readFileSync(path.join(root, 'apps/web/service-worker.js'), 'utf8');
  const listeners = {};
  let focusCount = 0;
  let navigateCount = 0;
  class TestMessageChannel {
    constructor() {
      this.port1 = {onmessage: null};
      this.port2 = {postMessage: data => queueMicrotask(() => {
        this.port1.onmessage?.({data});
      })};
    }
  }
  const client = {
    url: 'https://havre.test/chat',
    postMessage: (_message, ports) => {
      assert.strictEqual(focusCount,1,'wake the background page before waiting for acknowledgement');
      if (ackShell) {
        ports[0].postMessage({type: 'HAVRE_NOTIFICATION_OPEN_ACK', shell: ackShell});
      }
    },
    focus: async () => {focusCount += 1; return client;},
    navigate: async target => {
      navigateCount += 1;
      assert.ok(target.includes(`delivery-${locator}`));
      return client;
    },
  };
  const context = {
    self: {
      location: {origin: 'https://havre.test'},
      addEventListener: (name, callback) => {listeners[name] = callback;},
    },
    clients: {
      matchAll: async () => [client],
      openWindow: async () => {throw new Error('unexpected cold open');},
    },
    caches: {}, URL, MessageChannel: TestMessageChannel,
    setTimeout, clearTimeout, queueMicrotask,
  };
  vm.runInNewContext(workerSource, context, {filename: 'service-worker.js'});
  let completion;
  listeners.notificationclick({
    notification: {data: {url: `/chat#delivery-${locator}`, delivery_locator: locator}, close() {}},
    waitUntil: promise => {completion = promise;},
  });
  await completion;
  return {focusCount, navigateCount};
}

async function testStaticCacheLifecycle() {
  const workerSource = fs.readFileSync(path.join(root, 'apps/web/service-worker.js'), 'utf8');
  const listeners = {};
  const opened = [];
  const precached = [];
  const deleted = [];
  let claimed = 0;
  let skipped = 0;
  const clientApi = {claim: async () => {claimed += 1;}};
  const context = {
    self: {
      location: {origin: 'https://havre.test'},
      clients: clientApi,
      skipWaiting: async () => {skipped += 1;},
      addEventListener: (name, callback) => {listeners[name] = callback;},
    },
    clients: clientApi,
    caches: {
      open: async name => {
        opened.push(name);
        return {addAll: async entries => {precached.push(...entries);}};
      },
      keys: async () => ['havre-shell-v5', 'havre-static-old', 'unrelated-cache'],
      delete: async name => {deleted.push(name); return true;},
    },
    URL, setTimeout, clearTimeout,
  };
  vm.runInNewContext(workerSource, context, {filename: 'service-worker.js'});

  let install;
  listeners.install({waitUntil: promise => {install = promise;}});
  await install;
  assert.deepStrictEqual(opened, ['havre-static-20260908-fluid-bubbles-v21']);
  assert.ok(precached.includes('/assets/havre-app.js?v=20260908-fluid-bubbles-v21'));
  assert.ok(precached.includes('/assets/havre-app.css?v=20260908-fluid-bubbles-v21'));
  assert.strictEqual(skipped, 1);

  let activate;
  listeners.activate({waitUntil: promise => {activate = promise;}});
  await activate;
  assert.deepStrictEqual(deleted.sort(), ['havre-shell-v5', 'havre-static-old']);
  assert.strictEqual(claimed, 1);
}

async function testStaticFetchUsesCanonicalAwaitedCacheKey() {
  const listeners={},matched=[],stored=[],fetched=[];
  const fresh={ok:true,type:'basic',kind:'fresh',clone:()=>({kind:'clone'})};
  const cached={kind:'cached'};let offline=false,releasePut;
  const cacheWrite=new Promise(resolve=>{releasePut=resolve;});
  const context={
    self:{location:{origin:'https://havre.test'},addEventListener:(name,callback)=>{listeners[name]=callback;}},
    clients:{},URL,setTimeout,clearTimeout,
    caches:{open:async()=>({match:async key=>{matched.push(key);return key==='/chat'?cached:null;},put:async key=>{stored.push(key);await cacheWrite;}})},
    fetch:async request=>{fetched.push(request.url);if(offline)throw new Error('offline');return fresh;}
  };
  vm.runInNewContext(fs.readFileSync(path.join(root,'apps/web/service-worker.js'),'utf8'),context);
  const dispatch=(url,method='GET')=>{let promise;listeners.fetch({request:{url:'https://havre.test'+url,method},respondWith:value=>{promise=value;},waitUntil(){}});return promise;};
  assert.strictEqual(await dispatch('/chat?notification_open='+locator),fresh,'online navigation must bypass an existing cache');
  assert.deepStrictEqual(stored,[],'do not overwrite the coherent installed offline HTML with a different release');
  offline=true;
  assert.strictEqual(await dispatch('/chat?notification_open='+locator),cached);
  offline=false;
  assert.strictEqual(await dispatch('/assets/havre-app.js?v=20260908-fluid-bubbles-v21'),fresh,'render must not wait for cache disk writes');
  assert.deepStrictEqual(stored,['/assets/havre-app.js?v=20260908-fluid-bubbles-v21']);releasePut();
  for(const url of ['/assets/havre-app.js?v=future-release','/assets/havre-app.js?v=old-release','/v1/timeline','/v1/interactions/stream','/metrics']){
    assert.strictEqual(dispatch(url),undefined,'unknown versions and private APIs must pass through: '+url);
  }
  assert.strictEqual(dispatch('/chat','POST'),undefined);
  let version;
  listeners.message({data:{type:'HAVRE_APP_VERSION'},ports:[{postMessage:value=>{version=value.version;}}]});
  assert.strictEqual(version,'20260908-fluid-bubbles-v21');
}

(async () => {
  const htmlSource = fs.readFileSync(path.join(root, 'apps/web/havre-chat.html'), 'utf8');
  const appSource = fs.readFileSync(path.join(root, 'apps/web/havre-app.js'), 'utf8');
  const workerSource = fs.readFileSync(path.join(root, 'apps/web/service-worker.js'), 'utf8');
  assert.ok(htmlSource.includes('id="privacyMode"'));
  assert.ok(htmlSource.includes('aria-pressed="false"'));
  assert.ok(htmlSource.includes('正在确认回复引擎…'));
  assert.ok(htmlSource.includes('id="privacyMode"'));
  assert.ok(htmlSource.includes('title="正在确认本机回复引擎" disabled'));
  assert.ok(htmlSource.includes('havre-app.js?v=20260908-fluid-bubbles-v21'));
  assert.ok(htmlSource.includes('havre-app.css?v=20260908-fluid-bubbles-v21'));
  assert.ok(htmlSource.includes('id="reachOutFriendlyStatus"'));
  assert.ok(workerSource.includes("PUSH_SHELL_VERSION='havre-shell-v5'"));
  assert.ok(workerSource.includes("CACHE='havre-static-20260908-fluid-bubbles-v21'"));
  assert.ok(workerSource.includes("LEGACY_CACHES=new Set(['havre-shell-v5'])"));
  assert.ok(workerSource.includes('event.waitUntil(cache.put(fallback,response.clone()).catch(()=>{}))'));
  assert.ok(workerSource.includes('if(cached)return cached'));
  assert.ok(appSource.includes("updateViaCache:'none'"));
  assert.ok(appSource.includes("addEventListener('controllerchange'"));
  assert.ok(appSource.includes("PENDING_INTERACTION_KEY='havre-pending-interaction-v1'"));
  assert.ok(appSource.includes("'Idempotency-Key':pending.idempotency_key"));
  assert.ok(!appSource.includes("'Idempotency-Key':crypto.randomUUID()"));
  await testClientBehavior();
  testUpdateProtectsUnfinishedWork();
  await testStaticCacheLifecycle();
  await testStaticFetchUsesCanonicalAwaitedCacheKey();
  assert.deepStrictEqual(
    await runServiceWorkerClick('havre-shell-v5'),
    {focusCount: 1, navigateCount: 0},
  );
  assert.deepStrictEqual(
    await runServiceWorkerClick('havre-shell-v4'),
    {focusCount: 1, navigateCount: 1},
  );
  console.log('pwa-v5-contract: ok');
})().catch(error => {console.error(error); process.exitCode = 1;});
