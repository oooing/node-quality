'use strict';
const $ = id => document.getElementById(id);
const token = new URLSearchParams(location.hash.slice(1)).get('token') || sessionStorage.getItem('app-token');
if (token) sessionStorage.setItem('app-token', token);
history.replaceState(null, '', location.pathname);
let current = null, snapshot = null, lastRender = '', loading = false, toastTimer;
let receivedAt = 0, connectionError = '';
let control = null, controlLoading = false, targetGroup = '', switching = null;
let view = localStorage.getItem('line-view')==='favorites'?'favorites':'lines';
const findNode = id => snapshot?.nodes.find(n=>n.id===id)||snapshot?.favorites?.find(n=>n.id===id);
const starPath='m11.525 2.295-2.31 4.679-5.163.753a1 1 0 0 0-.554 1.706l3.736 3.64-.882 5.141a1 1 0 0 0 1.451 1.054L12 16.54l4.617 2.428a1 1 0 0 0 1.451-1.054l-.882-5.14 3.736-3.641a1 1 0 0 0-.554-1.706l-5.163-.753-2.31-4.679a1 1 0 0 0-1.794 0Z';
function starIcon(){const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('aria-hidden','true');const p=document.createElementNS(svg.namespaceURI,'path');p.setAttribute('d',starPath);svg.append(p);return svg;}
const openingPing0 = new Set(), ping0Seen = new Map();
const el = (tag, text, cls) => { const n = document.createElement(tag); if (text != null) n.textContent = text; if (cls) n.className = cls; return n; };
const fmt = value => value ? new Date(typeof value === 'number' ? value * 1000 : value).toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}) : '尚未检测';
function grade(score) { return [[15,'极度纯净',''],[25,'纯净',''],[40,'中性','warn'],[50,'轻度风险','warn'],[70,'中度风险','bad'],[100,'极度风险','bad']].find(x=>score<=x[0]); }
function toast(message) { $('toast').textContent=message; $('toast').hidden=false; clearTimeout(toastTimer); toastTimer=setTimeout(()=>$('toast').hidden=true,4000); }
async function api(path, body) {
  const response = await fetch(path,{method:body?'POST':'GET',headers:{'X-App-Token':token||'',...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{})});
  const data = await response.json(); if(!response.ok) throw new Error(data.error || '操作未完成'); return data;
}
async function act(path, body, message) { try { await api(path,body); if(message) toast(message); await refresh(); return true; } catch(error) { toast(error.message); return false; } }
function openDialog(id) { const d=$(id); if(!d.open)d.showModal(); }
function setView(next){view=next;localStorage.setItem('line-view',view);lastRender='';if(snapshot)render();}
$('view-lines').addEventListener('click',()=>setView('lines'));
$('view-favorites').addEventListener('click',()=>setView('favorites'));
$('view-ip-changes').addEventListener('click',()=>showIpChanges());
function showIpChanges(id){
  const all=[...new Map([...(snapshot.favorites||[]),...snapshot.nodes].map(n=>[n.id,n])).values()];
  const rows=all.filter(n=>n.ip_alert&&(!id||n.id===id));
  $('ip-change-content').replaceChildren(...rows.map(n=>{const row=el('div',null,'ip-change-row');row.dataset.node=n.id;const a=n.ip_alert;
    row.append(el('strong',n.name),el('p',a.previous_ip+' → '+a.current_ip,'ip-change-values'),el('p',fmt(a.checked_at),'muted'));
    const ack=el('button','已知晓');ack.dataset.action='ack-ip';row.append(ack);return row;}));
  if(rows.length)openDialog('ip-change-dialog');
}
let menuAnchor=null;
function closeMenu(restore=false){$('node-menu').hidden=true;if(restore)menuAnchor?.focus();}
function openNodeMenu(card,x,y){
  const node=findNode(card.dataset.node);if(!node)return;menuAnchor=card;
  const menu=$('node-menu');menu.dataset.node=node.id;
  const items=[['favorite',node.favorite?'取消收藏':'收藏线路'],['view-source','查看线路'],['history','查看记录'],['latency','复测延迟']];
  menu.replaceChildren(...items.map(([action,label])=>{const b=el('button',label);b.type='button';b.setAttribute('role','menuitem');b.dataset.action=action;b.disabled=action==='latency'&&Boolean(node.missing||node.unsupported);return b;}));
  menu.hidden=false;menu.style.left=Math.max(4,Math.min(x,innerWidth-menu.offsetWidth-6))+'px';menu.style.top=Math.max(4,Math.min(y,innerHeight-menu.offsetHeight-6))+'px';menu.querySelector('button').focus();
}
document.addEventListener('contextmenu',e=>{const c=e.target.closest('.card[data-node]');if(c){e.preventDefault();openNodeMenu(c,e.clientX,e.clientY);}});
document.addEventListener('keydown',e=>{
  if(e.key==='Escape')closeMenu(true);
  const c=e.target.closest('.card[data-node]');if(c&&(e.key==='ContextMenu'||(e.shiftKey&&e.key==='F10'))){e.preventDefault();const r=c.getBoundingClientRect();openNodeMenu(c,r.left+16,r.top+24);}
  if(!$('node-menu').hidden&&['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();const items=[...$('node-menu').querySelectorAll('button:not(:disabled)')],i=items.indexOf(document.activeElement);items[(i+(e.key==='ArrowDown'?1:-1)+items.length)%items.length].focus();}
});
document.addEventListener('pointerdown',e=>{if(!e.target.closest('#node-menu'))closeMenu();});
document.addEventListener('scroll',()=>closeMenu(),true);
document.querySelectorAll('.close').forEach(b=>b.addEventListener('click',()=>b.closest('dialog').close()));
document.querySelectorAll('dialog').forEach(d=>d.addEventListener('click',e=>{if(e.target===d){const r=d.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)d.close();}}));
function card(node, first=false) {
  const c=el('article',null,'card'+(first?' first':'')); c.dataset.node=node.id;c.tabIndex=0;
  if(first){const fold=el('span',null,'fold');fold.setAttribute('role','img');fold.setAttribute('aria-label','首选');fold.title='近期确认的低风险线路，不代表速度最快';c.append(fold);}
  const head=el('div',null,'card-head'), name=el('span',node.name,'card-name');name.title=node.name;head.append(name);
  const save=el('button',null,'favorite-toggle');save.dataset.action='favorite';save.setAttribute('aria-label',node.favorite?'取消收藏':'收藏线路');save.setAttribute('aria-pressed',String(Boolean(node.favorite)));save.title=node.favorite?'取消收藏':'收藏线路';save.append(starIcon());head.append(save);
  if(node.ip_alert){c.classList.add('ip-changed');const badge=el('button','IP 已变','ip-change-badge');badge.dataset.action='ip-change';badge.title=node.ip_alert.previous_ip+' → '+node.ip_alert.current_ip;badge.setAttribute('aria-label','查看 IP 变化');head.append(badge);}
  const latest=node.latest, attempt=node.last_attempt, connection=node.latency?.connectivity||attempt?.connectivity;
  const measuring=snapshot.activity.active_id===node.id||snapshot.activity.queued.includes(node.id);
  const ms=el('button',measuring?'…':node.latency?.status==='error'?'失败':connection?.status==='ok'?connection.delay_ms+' ms':connection?.status==='timeout'?'超时':'测速','latency');ms.type='button';ms.dataset.action='latency';ms.setAttribute('aria-label','复测延迟 '+node.name);ms.title=node.latency?.error||(connection?.checked_at?'上次测速 '+fmt(connection.checked_at)+'；点击复测':'仅测试延迟，不查询风险值');ms.disabled=measuring||Boolean(node.unsupported)||node.missing;head.append(ms);
  c.append(head);
  const active=snapshot.activity.active_id===node.id, queued=snapshot.activity.queued.includes(node.id);
  if(active){c.classList.add('checking');c.setAttribute('aria-busy','true');}
  const rating=node.rating_state;
  if(attempt?.status==='error'){
    const error=el('button',attempt.diagnosis?.message||attempt.error||'本次检测未完成','error failure-reason');error.type='button';error.dataset.action='diagnosis';error.setAttribute('aria-label','查看失败原因');error.title=attempt.diagnosis?.detail||attempt.error||'';c.append(error);
    if(rating==='ip_changed')c.append(el('div','新 IP '+(node.observed_ip||attempt.observed_ip)+' · 待评分','ip muted'));
    else if(latest)c.append(el('div','上次 '+latest.ip+' · 风险 '+latest.score,'ip muted'));
  } else if(rating==='ip_changed'){
    c.append(el('div','IP 已变更，待评分','state-line'),el('div',node.observed_ip||attempt?.observed_ip,'ip muted'));
  } else if(latest){
    const ip=el('div',latest.ip+(latest.ip_changed?' · IP 已变更':''),'ip muted');
    const note=rating==='score_pending'?'评分待更新':rating==='review'?'待复查':'';
    if(note){const badge=el('span',note,'review-badge');badge.title=rating==='score_pending'?(attempt?.error||'线路连接通过，评分暂未更新'):'评分已超过一天，保留上次结果，等待复查';ip.append(badge);}
    c.append(ip);
    const row=el('div',null,'score-row'), button=el('button',null,'score-button'); button.dataset.action='risk';
    button.setAttribute('aria-label',`IPPure 风险 ${latest.score}，查看说明`);
    button.append(el('span','IPPure','score-unit'),el('span',String(latest.score),'score-number'),el('span','/ 100','score-unit'));
    const g=grade(latest.score), supplement=latest.ping0_latest;
    row.append(button);
    if(supplement?.status==='ok'&&supplement.ip===latest.ip){
      const b=el('button',null,'score-button ping0-score');b.dataset.action='ping0-risk';
      b.title=supplement.label+' · '+fmt(supplement.checked_at);b.setAttribute('aria-label',`Ping0 风险 ${supplement.score}%，${supplement.label}`);
      b.append(el('span','Ping0','score-unit'),el('span',String(supplement.score),'score-number'),el('span','%','score-unit'));row.append(b);
    }else row.append(el('span',g[1],'grade '+g[2]));c.append(row);
  } else c.append(el('div',node.unsupported || (active?'正在检测…':queued?'等待检测':node.config_changed?'线路已更新，等待重新检测。':'尚未检测'),'state-line'));
  const actions=el('div',null,'card-actions'), hist=el('button',latest&&rating!=='ip_changed'?fmt(latest.checked_at):attempt?fmt(attempt.checked_at):'记录');hist.dataset.action='history';hist.title=latest&&rating!=='ip_changed'?'评分检测于 '+fmt(latest.checked_at)+'；点击查看记录':'查看最近 10 次检测结果';actions.append(hist);
  const check=el('button',active?'正在检测':queued?'等待检测':'检测');check.dataset.action='check';check.disabled=active||queued||Boolean(node.unsupported);
  if(active){const spinner=el('span',null,'spinner');spinner.setAttribute('aria-hidden','true');check.prepend(spinner);}
  actions.append(check);
  const job=ping0Job(node.id), waiting=job?.status==='waiting';
  if((latest&&rating!=='ip_changed')||job){const ping=el('button',openingPing0.has(node.id)||job?.status==='checking'?'正在查询':waiting?'去验证':'补充检测');ping.dataset.action='ping0';
    ping.disabled=openingPing0.has(node.id)||job?.status==='checking'||(!latest&&!waiting);
    ping.title=job?.error||job?.message||(latest?'补充检测上次测得的 IP '+latest.ip+'（'+fmt(latest.checked_at)+'）':'请先检测这条线路');actions.append(ping);}
  const group=selectedGroup(), selected=canSwitch(node)&&group.selected===node.name;
  c.classList.toggle('in-use',selected);
  if(selected){
    const status=el('span','使用中','current-state');
    status.setAttribute('aria-label','使用中 '+node.name);actions.append(status);
  }else{
    const change=el('button',switching===node.id?'切换中':'换用','switch-node');change.dataset.action='switch';
    change.disabled=Boolean(switching||!canSwitch(node));
    change.title=canSwitch(node)?'只更换此分组的线路：'+group.name:(control?.reason||'此线路不在当前 Clash 手动代理组中');
    change.setAttribute('aria-label','换用 '+node.name);actions.append(change);
  }
  c.append(actions);return c;
}
function renderCards() {
  if(!snapshot)return;
  const key=JSON.stringify([view,snapshot.favorites,snapshot.profile_id,snapshot.nodes,snapshot.recommendations.items.map(n=>[n.id,n.needs_review]),snapshot.activity.active_id,snapshot.activity.queued,$('search').value,snapshot.ping0_jobs,control,targetGroup,switching,[...openingPing0]]);
  if(key===lastRender)return;lastRender=key;
  const ids=new Set(snapshot.recommendations.items.map(n=>n.id)), byId=new Map(snapshot.nodes.map(n=>[n.id,n]));
  const shown=snapshot.recommendations.items;
  $('candidates').replaceChildren(...shown.map((n,i)=>card(byId.get(n.id),i===0&&!n.needs_review)));
  const other=snapshot.nodes.filter(n=>!ids.has(n.id)), search=$('search').value.trim().toLowerCase();
  $('other-grid').replaceChildren(...other.filter(n=>n.name.toLowerCase().includes(search)).map(n=>card(n)));
  $('candidate-count').textContent=ids.size;$('other-count').textContent=other.length;
  $('empty').hidden=ids.size>0;$('empty').textContent=snapshot.recommendations.message;
  const groups=new Map();for(const n of snapshot.favorites||[]){const key=n.client+' · '+n.profile_name;if(!groups.has(key))groups.set(key,[]);groups.get(key).push(n);}
  $('favorites-grid').replaceChildren(...[...groups].map(([title,nodes])=>{const section=el('section',null,'favorite-group');section.append(el('h2',title));const grid=el('div',null,'grid');grid.append(...nodes.map(n=>card(n)));section.append(grid);return section;}));
  $('favorites-empty').hidden=Boolean(snapshot.favorites?.length);
  const changedFavorites=(snapshot.favorites||[]).filter(n=>n.ip_alert).length;$('view-favorites').textContent='我的收藏'+(changedFavorites?' · '+changedFavorites+' !':'');
  const alerts=(view==='favorites'?snapshot.favorites||[]:snapshot.nodes).filter(n=>n.ip_alert);
  $('ip-change-notice').hidden=!alerts.length;$('ip-change-text').textContent=alerts.length+' 条线路的 IP 已变化';
}
function render() {
  const s=snapshot, profiles=s.profiles; current=s.profile_id;
  renderSourcePicker(profiles);
  $('onboarding').hidden=profiles.length>0||view==='favorites';$('results').hidden=!profiles.length||view==='favorites';
  $('favorites-page').hidden=view!=='favorites';document.querySelector('.source-picker').hidden=view==='favorites';$('check-all').hidden=view==='favorites';$('refresh').hidden=view==='favorites';
  $('view-lines').setAttribute('aria-current',view==='lines'?'page':'false');$('view-favorites').setAttribute('aria-current',view==='favorites'?'page':'false');
  const p=profiles.find(p=>p.id===current), a=s.activity;
  renderActivity();$('pause').setAttribute('aria-checked',String(!s.settings.paused));$('pause').disabled=false;
  $('updated').textContent=p?.last_update?'更新于 '+fmt(p.last_update):'';$('updated').hidden=view==='favorites';
  $('refresh').disabled=!p||a.updating===current||p.mode==='file';$('check-all').disabled=!s.nodes.length;
  const message=[p?.error,a.message].filter(Boolean).join(' ');$('notice').textContent=message;$('notice').hidden=!message;
  $('scope').textContent='风险 ≤ '+s.settings.recommendation.max_risk+' · 优先近期确认';
  renderControl();renderPing0Jobs();
  renderCards();
}
function selectedGroup(){return control?.groups?.find(g=>g.name===targetGroup);}
function canSwitch(node){return Boolean(control?.profile_id===current&&control.can_switch&&control.switchable_ids.includes(node.id)&&selectedGroup()?.members.includes(node.name));}
function renderControl(){
  const groups=control?.profile_id===current?control.groups:[];
  const key=JSON.stringify(groups.map(g=>g.name));
  if($('clash-group').dataset.key!==key){$('clash-group').replaceChildren(...groups.map(g=>{const o=el('option',g.name);o.value=g.name;return o;}));$('clash-group').dataset.key=key;}
  $('clash-group').value=targetGroup;$('clash-group').disabled=!groups.length||Boolean(switching);$('clash-refresh').disabled=controlLoading||Boolean(switching);
  $('clash-note').textContent=controlLoading&&!control?'读取 Clash…':control?.can_switch?'已选用：'+(selectedGroup()?.selected||'—')+(control.mode==='rule'?' · 只影响使用这个分组的连接':' · Clash 全局连接'):control?.reason||'未连接 Clash';
}
async function loadControl(){
  if(!current||controlLoading)return;const requested=current;controlLoading=true;renderControl();
  try{const next=await api('/api/control?profile='+encodeURIComponent(requested));if(current===requested){control=next;const saved=localStorage.getItem('clash-group:'+current);if(!next.groups.some(g=>g.name===targetGroup))targetGroup=next.groups.some(g=>g.name===saved)?saved:next.groups[0]?.name||'';}}
  catch(e){if(current===requested)control={profile_id:current,groups:[],can_switch:false,reason:e.message};}
  finally{controlLoading=false;renderControl();renderCards();if(current!==requested)loadControl();}
}
function ping0Job(id){return snapshot?.ping0_jobs?.filter(j=>j.node_id===id).at(-1);}
function renderPing0Jobs(){for(const job of snapshot.ping0_jobs||[]){const before=ping0Seen.get(job.job_id);if(before&&before!==job.status){if(job.status==='completed')toast(job.applied_to_current?'Ping0 结果已保存，可在检测记录中查看。':'IP 已变更，本次结果已存入之前地址的记录。');if(['error','expired'].includes(job.status))toast(job.error||'补充检测未完成，请重试。');if(job.status==='waiting')toast('请在浏览器完成验证，结果会自动保存。');}ping0Seen.set(job.job_id,job.status);}}
async function openPing0(id){
  if(openingPing0.has(id))return;openingPing0.add(id);renderCards();const job=ping0Job(id);
  try{const result=await api(job?.status==='waiting'?'/api/ping0/reopen':'/api/ping0/open',job?.status==='waiting'?{job_id:job.job_id}:{profile_id:findNode(id)?.profile_id||current,node_id:id});ping0Seen.set(result.job_id,result.status);toast(result.status==='waiting'?'已打开验证页':'正在查询 Ping0');}
  catch(e){toast(e.message);}finally{openingPing0.delete(id);await refresh();renderCards();}
}
async function switchNode(id){
  const node=findNode(id);if(switching||!node||!canSwitch(node))return;
  const profile=current,group=targetGroup;switching=id;renderCards();
  try{const result=await api('/api/switch',{profile_id:profile,node_id:id,group});if(!result.verified||!result.persisted)throw new Error('未能确认换用已保存');toast('已换用并保存：'+result.selected);}
  catch(e){toast(e.message);}finally{switching=null;await loadControl();renderCards();}
}
function renderActivity(){
  if(!snapshot)return;
  const a=snapshot.activity, p=a.progress, profile=snapshot.profiles.find(p=>p.id===snapshot.profile_id);
  const since=(performance.now()-receivedAt)/1000;
  let status='等待下次计划', state='idle';
  if(connectionError){status='暂时无法更新进度，正在重新连接。';state='offline';}
  else if(a.updating){status='正在更新线路列表';state='updating';}
  else if(a.active_id){
    const stage=(a.active_kind==='latency'&&a.stage?.stage!=='diagnosis'?'复测延迟':null)||{network:'准备连接',starting:'开始检测',connectivity:'测试连接',connectivity_retry:'尝试连接另一个测试网站',dns:'查找检测网站地址',risk:'查询 IP 和风险评分',diagnosis:'检查连接失败的原因'}[a.stage?.stage]||'检测中';
    status=(a.active_profile_id!==snapshot.profile_id?'其他来源 · ':'')+stage+' · '+a.active_name;state='active';
  }else if(a.cooldown_until*1000>Date.now()){
    const remaining=Math.ceil((a.cooldown_until*1000-Date.now())/1000);
    status='等待重试 · '+Math.floor(remaining/60)+':'+String(remaining%60).padStart(2,'0');state='waiting';
  }else if(a.queued.length){status=a.queued.length+' 个排队中';state='queued';}
  else if(snapshot.settings.paused){status='自动检测已关闭';state='paused';}
  else if(!profile?.enabled){status=profile?'这个来源只在手动操作时检测':'等待添加列表';}
  else if(p.remaining){const seconds=Math.max(0,Math.ceil(a.wait_seconds-since));status=seconds?seconds+' 秒后继续检测':'准备检测下一线路';state='queued';}
  else if(p.total){status='本轮已完成，之后会按计划重测。';state='complete';}
  if($('status').textContent!==status)$('status').textContent=status;
  $('status').title=status;$('detection').dataset.state=state;
  $('elapsed').hidden=state!=='active';
  if(state==='active')$('elapsed').textContent=Math.floor(a.elapsed_seconds+since)+' 秒';
  $('progress-area').hidden=view==='favorites'||!snapshot.nodes.length;
  $('progress-count').textContent='已完成 '+p.completed+' / '+p.total;
  $('progress-detail').textContent=['剩余 '+p.remaining,p.failed?'失败 '+p.failed:'',p.skipped?'不支持 '+p.skipped:''].filter(Boolean).join(' · ');
  $('progress').max=Math.max(1,p.total);$('progress').value=p.completed;
  $('progress').setAttribute('aria-valuetext',`已完成 ${p.completed}，共 ${p.total} 个；剩余 ${p.remaining}，失败 ${p.failed}`);
  $('progress-area').title='已完成包含成功和失败；待检测、待重测计入剩余，不支持的单独统计。';
}
async function refresh(){if(loading)return;loading=true;const requested=current;try{const received=await api('/api/state'+(requested?'?profile='+encodeURIComponent(requested):''));if(requested===current){snapshot=received;receivedAt=performance.now();connectionError='';render();if(!control)loadControl();}}catch(e){connectionError=e.message;if(snapshot)renderActivity();else $('status').textContent=e.message;}finally{loading=false;if(current!==requested&&requested!==null)refresh();}}
function viewProfile(id){current=id;control=null;targetGroup='';$('search').value='';lastRender='';refresh();}
$('profiles').addEventListener('change',()=>viewProfile($('profiles').value));
$('clients').addEventListener('change',()=>{
  const profiles=snapshot.profiles.filter(p=>sourceClient(p)===$('clients').value);
  const next=profiles.find(p=>p.current)||profiles.find(p=>p.enabled)||profiles[0];
  if(next)viewProfile(next.id);
});
$('clash-group').addEventListener('change',()=>{targetGroup=$('clash-group').value;localStorage.setItem('clash-group:'+current,targetGroup);renderControl();renderCards();});
$('clash-refresh').addEventListener('click',loadControl);
$('extension-folder').addEventListener('click',()=>act('/api/extension-folder',{}));
$('search').addEventListener('input',renderCards);
$('pause').addEventListener('click',()=>snapshot&&act('/api/settings',{paused:!snapshot.settings.paused}));
$('check-all').addEventListener('click',()=>act('/api/check',{profile_id:current},'已排队，轮到后自动开始。'));
$('refresh').addEventListener('click',()=>act('/api/refresh',{profile_id:current},'已安排更新，请稍候。'));
document.addEventListener('click',async event=>{
  const b=event.target.closest('[data-action]');if(!b)return;const node=b.closest('[data-node]')?.dataset.node;
  if(b.closest('#node-menu'))closeMenu();
  if(b.dataset.action==='risk')openDialog('risk-dialog');
  if(b.dataset.action==='ping0-risk')openDialog('ping0-dialog');
  if(b.dataset.action==='ping0')openPing0(node);
  if(b.dataset.action==='switch')switchNode(node);
  if(b.dataset.action==='check')act('/api/check',{profile_id:findNode(node)?.profile_id||current,node_id:node},'已排队，轮到后自动开始。');
  if(b.dataset.action==='latency')act('/api/latency',{profile_id:findNode(node)?.profile_id||current,node_id:node},'已安排复测延迟');
  if(b.dataset.action==='favorite')act('/api/favorite',{node_id:node,saved:!findNode(node)?.favorite},findNode(node)?.favorite?'已取消收藏':'已收藏');
  if(b.dataset.action==='ip-change')showIpChanges(node);
  if(b.dataset.action==='ack-ip'){await act('/api/ip-ack',{node_id:node});$('ip-change-dialog').close();}
  if(b.dataset.action==='view-source'){const n=findNode(node);setView('lines');if(n)viewProfile(n.profile_id);}
  if(b.dataset.action==='history'||b.dataset.action==='diagnosis'){
    $('history-title').textContent=findNode(node)?.name||'检测记录';
    $('history-content').textContent='正在读取…';openDialog('history-dialog');
    try{const [rows,supplements]=await Promise.all([api('/api/history?node='+encodeURIComponent(node)),api('/api/ping0/history?node='+encodeURIComponent(node))]);$('history-content').replaceChildren(...rows.map(r=>{
      const d=el('div',null,'history-row'), h=el('header');h.append(el('span',fmt(r.checked_at),'muted'),el('span',null,'spacer'));
      if(r.status==='ok'){const g=grade(r.score);h.append(el('strong',r.score+' / 100'));d.append(h,el('p',r.ip+' · '+g[1]+(r.ip_changed?' · IP 已变更':'')));}
      else {
        d.append(h,el('p',r.diagnosis?.message||r.error||'未完成检测'));
        if(r.diagnosis){
          const reason=r.diagnosis, detail=el('details',null,'diagnosis-detail');detail.append(el('summary','诊断详情'));
          if(reason.detail)detail.append(el('p',reason.detail));
          if(reason.evidence?.length){const list=el('ul');for(const item of reason.evidence)list.append(el('li',item));detail.append(list);}
          if(reason.suggestion)detail.append(el('p',reason.suggestion,'muted'));
          d.append(detail);
        }
      }
      if(r.previous_ip)d.append(el('p','IP 变化：'+r.previous_ip+' → '+(r.observed_ip||r.ip),'ip-change-history'));
      if(r.connectivity)d.append(el('p',r.connectivity.status==='ok'?'连接耗时 '+r.connectivity.delay_ms+' 毫秒':'本次连接测试未通过。','muted'));return d;
    }));if(!rows.length)$('history-content').textContent='还没有记录，检测一次就能查看。';
    if(supplements.length){$('history-content').append(el('h3','补测记录'));const currentIp=snapshot.nodes.find(n=>n.id===node)?.latest?.ip;
      for(const r of supplements){const d=el('div',null,'history-row'),h=el('header');h.append(el('span',fmt(r.checked_at),'muted'),el('span',null,'spacer'),el('strong',r.score+'%'));d.append(h,el('p',r.ip+' · '+r.label+(currentIp&&r.ip!==currentIp?' · 之前地址':'')));$('history-content').append(d);}}
    }catch(e){$('history-content').textContent=e.message;}
  }
});
function openSettings(page='sources'){
  if(!snapshot)return;const s=snapshot.settings,r=s.recommendation;
  $('max-risk').value=r.max_risk;$('auto-enabled').checked=!s.paused;
  const preferred=['HK','TW','JP','SG','US'], all=[...snapshot.recommendations.regions];
  for(const [id,name] of [['HK','香港'],['TW','台湾'],['JP','日本'],['SG','新加坡'],['US','美国']])if(!all.some(x=>x.id===id))all.push({id,name});
  for(const id of r.regions||[])if(!all.some(x=>x.id===id))all.push({id,name:id});
  all.sort((a,b)=>(preferred.includes(a.id)?preferred.indexOf(a.id):99)-(preferred.includes(b.id)?preferred.indexOf(b.id):99));
  $('regions').replaceChildren(...all.map(region=>{const l=el('label',null,'chip'),i=el('input');i.type='checkbox';i.value=region.id;i.checked=(r.regions||[]).includes(region.id);l.append(i,el('span',region.name));return l;}));
  renderSources();showSettingsPage(page);openDialog('settings-dialog');
}
$('settings').addEventListener('click',()=>openSettings());
$('clear-regions').addEventListener('click',()=>document.querySelectorAll('#regions input').forEach(i=>i.checked=false));
$('settings-form').addEventListener('submit',async e=>{e.preventDefault();const body={recommendation:{max_risk:Number($('max-risk').value),regions:[...document.querySelectorAll('#regions input:checked')].map(i=>i.value)}};if(!$('panel-automatic').hidden)body.paused=!$('auto-enabled').checked;if(await act('/api/settings',body,'已保存'))$('settings-dialog').close();});
function sourceName(p){return p.name||'未命名列表';}
function sourceClient(p){return p?.origin||'其他来源';}
function sourceGroups(profiles){
  const groups=new Map();
  for(const p of profiles){const client=sourceClient(p);if(!groups.has(client))groups.set(client,[]);groups.get(client).push(p);}
  return groups;
}
function renderSourcePicker(profiles){
  const selected=profiles.find(p=>p.id===current),client=sourceClient(selected),groups=sourceGroups(profiles);
  const signature=JSON.stringify([...groups.keys()]);
  if($('clients').dataset.signature!==signature){$('clients').replaceChildren(...[...groups.keys()].map(name=>{const o=el('option',name);o.value=name;return o;}));$('clients').dataset.signature=signature;}
  $('clients').value=selected?client:'';$('clients').disabled=!profiles.length;
  const items=groups.get(client)||[],key=JSON.stringify(items.map(p=>[p.id,p.name,p.enabled]));
  if($('profiles').dataset.signature!==key){$('profiles').replaceChildren(...items.map(p=>{const o=el('option',sourceName(p)+(p.enabled?'':' · 仅手动'));o.value=p.id;return o;}));$('profiles').dataset.signature=key;}
  $('profiles').value=current||'';$('profiles').disabled=!items.length;
  $('clients').title=selected?client:'选择客户端';$('profiles').title=selected?sourceName(selected):'选择订阅';
}
function renderSources(){if(!snapshot)return;$('subscription-list').replaceChildren(...[...sourceGroups(snapshot.profiles)].map(([client,profiles])=>{
  const group=el('section',null,'source-group');group.setAttribute('aria-label',client);group.append(el('h4',client));
  group.append(...profiles.map(p=>{
  const row=el('div',null,'source-row'),info=el('div',null,'source-info'),name=el('strong',sourceName(p));name.title=p.name;
  info.append(name,el('small',p.node_count+' 条线路'+(p.current?' · 正在使用':'')));
  const label=el('label',null,'source-toggle'),input=el('input');input.type='checkbox';input.value=p.id;input.checked=p.enabled;input.setAttribute('aria-label','自动检测 '+sourceName(p));
  label.append(el('span','自动检测'),input);row.append(info,label);return row;
  }));return group;
}));}
function subscriptions(){openSettings('sources');}
$('welcome-add').addEventListener('click',subscriptions);
function showSettingsPage(page){
  document.querySelectorAll('[data-page]').forEach(b=>{const active=b.dataset.page===page;b.setAttribute('aria-selected',String(active));b.tabIndex=active?0:-1;});
  for(const id of ['sources','recommend','automatic'])$('panel-'+id).hidden=id!==page;
  $('settings-form').hidden=page==='sources';$('save-settings').textContent=page==='automatic'?'保存设置':'保存设置';
  document.querySelector('.settings-content').scrollTop=0;
}
document.querySelectorAll('[data-page]').forEach(b=>{
  b.addEventListener('click',()=>showSettingsPage(b.dataset.page));
  b.addEventListener('keydown',e=>{const tabs=[...document.querySelectorAll('[data-page]')],index=tabs.indexOf(b);let next;
    if(['ArrowDown','ArrowRight'].includes(e.key))next=(index+1)%tabs.length;
    if(['ArrowUp','ArrowLeft'].includes(e.key))next=(index+tabs.length-1)%tabs.length;
    if(e.key==='Home')next=0;if(e.key==='End')next=tabs.length-1;
    if(next!==undefined){e.preventDefault();tabs[next].focus();showSettingsPage(tabs[next].dataset.page);}
  });
});
$('save-subscriptions').addEventListener('click',async()=>{if(await act('/api/enable',{ids:[...document.querySelectorAll('#subscription-list input:checked')].map(i=>i.value)},'已保存'))$('settings-dialog').close();});
$('rescan').addEventListener('click',async()=>{const b=$('rescan');b.disabled=true;try{const result=await api('/api/discover',{});await refresh();renderSources();toast('已同步 '+result.count+' 个线路列表'+(result.removed?' · 移出 '+result.removed+' 个在 Clash 中删除的列表':''));}catch(e){toast(e.message);}finally{b.disabled=false;}});
$('scan-directory').addEventListener('click',async()=>{if(await act('/api/discover',{directory:$('directory').value.trim()}))subscriptions();});
$('add-form').addEventListener('submit',async e=>{e.preventDefault();if(await act('/api/add',{name:$('add-name').value,url:$('add-url').value.trim()},'线路列表已添加')){$('add-url').value='';subscriptions();}});
$('file').addEventListener('change',async()=>{const file=$('file').files[0];if(!file)return;if(file.size>8*1024*1024){toast('文件超过 8 MB');return;}if(await act('/api/add',{name:$('add-name').value||file.name,text:await file.text()},'文件已导入'))subscriptions();$('file').value='';});
refresh();setInterval(refresh,2000);setInterval(renderActivity,1000);setInterval(loadControl,10000);
