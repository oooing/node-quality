'use strict';
const $ = id => document.getElementById(id);
const token = new URLSearchParams(location.hash.slice(1)).get('token') || sessionStorage.getItem('app-token');
if (token) sessionStorage.setItem('app-token', token);
history.replaceState(null, '', location.pathname);
let current = null, snapshot = null, lastRender = '', loading = false, toastTimer;
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
document.querySelectorAll('.close').forEach(b=>b.addEventListener('click',()=>b.closest('dialog').close()));
document.querySelectorAll('dialog').forEach(d=>d.addEventListener('click',e=>{if(e.target===d){const r=d.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)d.close();}}));
function card(node, first=false) {
  const c=el('article',null,'card'+(first?' first':'')); c.dataset.node=node.id;
  if(first){const fold=el('span',null,'fold');fold.setAttribute('role','img');fold.setAttribute('aria-label','首选');fold.title='首选';c.append(fold);}
  const head=el('div',null,'card-head'), name=el('span',node.name,'card-name');name.title=node.name;head.append(name);
  const latest=node.latest, attempt=node.last_attempt, connection=attempt?.connectivity;
  if(connection?.status==='ok')head.append(el('span',connection.delay_ms+' ms','latency'));
  c.append(head);
  const active=snapshot.activity.active_id===node.id, queued=snapshot.activity.queued.includes(node.id);
  if(attempt?.status==='error'){
    const error=el('div',attempt.error||'本次检测未完成','error');error.title=attempt.error||'';c.append(error);
    if(latest)c.append(el('div','上次 '+latest.ip+' · 风险 '+latest.score,'ip muted'));
  } else if(latest){
    c.append(el('div',latest.ip+(latest.ip_changed?' · IP 已变化':''),'ip muted'));
    const row=el('div',null,'score-row'), button=el('button',null,'score-button'); button.dataset.action='risk';
    button.setAttribute('aria-label',`IPPure 风险 ${latest.score}，查看说明`);
    button.append(el('span','IPPure','score-unit'),el('span',String(latest.score),'score-number'),el('span','/ 100','score-unit'));
    const g=grade(latest.score);row.append(button,el('span',g[1],'grade '+g[2]));c.append(row);
  } else c.append(el('div',node.unsupported || (active?'正在检测…':queued?'等待检测':node.config_changed?'配置已更新，待检测':'待检测'),'state-line'));
  const actions=el('div',null,'card-actions'), hist=el('button',attempt?fmt(attempt.checked_at):'历史');hist.dataset.action='history';hist.title='查看最近 10 次记录';actions.append(hist);
  const check=el('button',active?'检测中…':queued?'已排队':'检测');check.dataset.action='check';check.disabled=active||queued||Boolean(node.unsupported);actions.append(check);c.append(actions);return c;
}
function renderCards() {
  if(!snapshot)return;
  const key=JSON.stringify([snapshot.profile_id,snapshot.nodes,snapshot.recommendations.items.map(n=>n.id),snapshot.activity.active_id,snapshot.activity.queued,$('search').value]);
  if(key===lastRender)return;lastRender=key;
  const ids=new Set(snapshot.recommendations.items.map(n=>n.id)), byId=new Map(snapshot.nodes.map(n=>[n.id,n]));
  $('candidates').replaceChildren(...snapshot.recommendations.items.map((n,i)=>card(byId.get(n.id),i===0)));
  const other=snapshot.nodes.filter(n=>!ids.has(n.id)), search=$('search').value.trim().toLowerCase();
  $('other-grid').replaceChildren(...other.filter(n=>n.name.toLowerCase().includes(search)).map(n=>card(n)));
  $('candidate-count').textContent=ids.size;$('other-count').textContent=other.length;
  $('empty').hidden=ids.size>0;$('empty').textContent=snapshot.recommendations.message;
}
function render() {
  const s=snapshot, profiles=s.profiles; current=s.profile_id;
  const signature=JSON.stringify(profiles.map(p=>[p.id,p.name,p.enabled]));
  if($('profiles').dataset.signature!==signature){$('profiles').replaceChildren(...profiles.map(p=>{const o=el('option',p.name+(p.enabled?'':' · 未启用'));o.value=p.id;return o;}));$('profiles').dataset.signature=signature;}
  $('profiles').value=current||'';
  $('onboarding').hidden=profiles.length>0;$('results').hidden=!profiles.length;
  const p=profiles.find(p=>p.id===current), a=s.activity;
  let status=s.settings.paused?'自动检测已暂停':'自动检测已开启';
  if(a.updating)status='正在更新订阅…';
  else if(a.active_name){const stage={starting:'准备检测',connectivity:'检查连通',risk:'查询风险'}[a.stage?.stage]||'检测';status=stage+' · '+a.active_name;}
  else if(a.queued.length)status+=' · '+a.queued.length+' 个排队中';
  else if(profiles.length){const count=s.nodes.filter(n=>n.last_attempt).length;status+=' · 已检查 '+count+' / '+s.nodes.length;}
  $('status').textContent=status;$('pause').textContent=s.settings.paused?'继续自动检测':'暂停自动检测';
  $('updated').textContent=p?.last_update?'更新于 '+fmt(p.last_update):'';
  $('refresh').disabled=!p||a.updating===current||p.mode==='file';$('check-all').disabled=!s.nodes.length;
  const message=[p?.error,a.message].filter(Boolean).join(' ');$('notice').textContent=message;$('notice').hidden=!message;
  $('scope').textContent='风险 ≤ '+s.settings.recommendation.max_risk+' · '+s.settings.recommendation.fresh_hours+' 小时内';
  renderCards();
}
async function refresh(){if(loading)return;loading=true;const requested=current;try{const received=await api('/api/state'+(requested?'?profile='+encodeURIComponent(requested):''));if(requested===current){snapshot=received;render();}}catch(e){$('status').textContent=e.message;}finally{loading=false;if(current!==requested&&requested!==null)refresh();}}
$('profiles').addEventListener('change',()=>{current=$('profiles').value;$('search').value='';lastRender='';refresh();});
$('search').addEventListener('input',renderCards);
$('pause').addEventListener('click',()=>snapshot&&act('/api/settings',{paused:!snapshot.settings.paused}));
$('check-all').addEventListener('click',()=>act('/api/check',{profile_id:current},'已加入检测队列'));
$('refresh').addEventListener('click',()=>act('/api/refresh',{profile_id:current},'已安排更新'));
document.addEventListener('click',async event=>{
  const b=event.target.closest('[data-action]');if(!b)return;const node=b.closest('[data-node]')?.dataset.node;
  if(b.dataset.action==='risk')openDialog('risk-dialog');
  if(b.dataset.action==='check')act('/api/check',{profile_id:current,node_id:node},'已加入检测队列');
  if(b.dataset.action==='history'){
    $('history-title').textContent=snapshot.nodes.find(n=>n.id===node)?.name||'历史记录';
    $('history-content').textContent='正在读取…';openDialog('history-dialog');
    try{const rows=await api('/api/history?node='+encodeURIComponent(node));$('history-content').replaceChildren(...rows.map(r=>{
      const d=el('div',null,'history-row'), h=el('header');h.append(el('span',fmt(r.checked_at),'muted'),el('span',null,'spacer'));
      if(r.status==='ok'){const g=grade(r.score);h.append(el('strong',r.score+' / 100'));d.append(h,el('p',r.ip+' · '+g[1]+(r.ip_changed?' · IP 已变化':'')));}
      else d.append(h,el('p',r.error||'未完成检测'));
      if(r.connectivity)d.append(el('p',r.connectivity.status==='ok'?'连通 '+r.connectivity.delay_ms+' ms':'连通测试未通过','muted'));return d;
    }));if(!rows.length)$('history-content').textContent='还没有检测记录。';}catch(e){$('history-content').textContent=e.message;}
  }
});
$('settings').addEventListener('click',()=>{
  if(!snapshot)return;const s=snapshot.settings,r=s.recommendation;
  $('max-risk').value=r.max_risk;$('fresh-hours').value=r.fresh_hours;$('limit').value=r.limit;
  for(const k of ['update','candidate','other'])$(k+'-hours').value=s[k+'_hours'];
  const preferred=['HK','TW','JP','SG','US'], all=[...snapshot.recommendations.regions];
  for(const [id,name] of [['HK','香港'],['TW','台湾'],['JP','日本'],['SG','新加坡'],['US','美国']])if(!all.some(x=>x.id===id))all.push({id,name});
  for(const id of r.regions||[])if(!all.some(x=>x.id===id))all.push({id,name:id});
  all.sort((a,b)=>(preferred.includes(a.id)?preferred.indexOf(a.id):99)-(preferred.includes(b.id)?preferred.indexOf(b.id):99));
  $('regions').replaceChildren(...all.map(region=>{const l=el('label',null,'chip'),i=el('input');i.type='checkbox';i.value=region.id;i.checked=(r.regions||[]).includes(region.id);l.append(i,el('span',region.name));return l;}));
  openDialog('settings-dialog');
});
$('clear-regions').addEventListener('click',()=>document.querySelectorAll('#regions input').forEach(i=>i.checked=false));
$('settings-form').addEventListener('submit',async e=>{e.preventDefault();const body={recommendation:{max_risk:Number($('max-risk').value),fresh_hours:Number($('fresh-hours').value),limit:Number($('limit').value),regions:[...document.querySelectorAll('#regions input:checked')].map(i=>i.value)}};for(const k of ['update','candidate','other'])body[k+'_hours']=Number($(k+'-hours').value);if(await act('/api/settings',body,'已保存'))$('settings-dialog').close();});
function subscriptions(){if(!snapshot)return;$('subscription-list').replaceChildren(...snapshot.profiles.map(p=>{const l=el('label',null,'subscription'),input=el('input');input.type='checkbox';input.value=p.id;input.checked=p.enabled;l.append(input,el('span',p.name),el('small',(p.current?'Clash 当前订阅 · ':'')+p.node_count+' 个节点 · '+(p.mode==='remote'?'链接自动更新':p.mode==='cache'?'跟随本地缓存':'本地文件')));return l;}));openDialog('subscriptions-dialog');}
$('subscriptions').addEventListener('click',subscriptions);$('welcome-add').addEventListener('click',subscriptions);
$('save-subscriptions').addEventListener('click',async()=>{if(await act('/api/enable',{ids:[...document.querySelectorAll('#subscription-list input:checked')].map(i=>i.value)},'已保存'))$('subscriptions-dialog').close();});
$('rescan').addEventListener('click',async()=>{await act('/api/discover',{},'已重新读取 Clash');subscriptions();});
$('scan-directory').addEventListener('click',async()=>{if(await act('/api/discover',{directory:$('directory').value.trim()}))subscriptions();});
$('add-form').addEventListener('submit',async e=>{e.preventDefault();if(await act('/api/add',{name:$('add-name').value,url:$('add-url').value.trim()},'订阅已添加')){$('add-url').value='';subscriptions();}});
$('file').addEventListener('change',async()=>{const file=$('file').files[0];if(!file)return;if(file.size>8*1024*1024){toast('文件超过 8 MB');return;}if(await act('/api/add',{name:$('add-name').value||file.name,text:await file.text()},'文件已导入'))subscriptions();$('file').value='';});
refresh();setInterval(refresh,2000);
