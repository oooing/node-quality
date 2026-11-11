import React,{useState,useEffect,useRef,useCallback} from 'react';
import {Card} from '@astryxdesign/core/Card';
import {TextInput} from '@astryxdesign/core/TextInput';
import Tasks from './Tasks.jsx';
import {Search,Star,LayoutGrid,Folder,RefreshCw,Settings,Clock3,ChevronDown,ChevronRight,X,Check,Radio,Settings2,Plus,WifiOff} from 'lucide-react';
import {B,IB,fmt,Score} from './shared.jsx';
import {api} from './api.js';
import Dialogs from './Dialogs.jsx';

function pendingIds(state){return new Set([...(state?.activity?.queued||[]),state?.activity?.active_id].filter(Boolean));}
function canDetect(n){return !n.missing&&!n.unsupported;}
function connection(n){return n.latency?.connectivity||n.last_attempt?.connectivity;}
function latestJob(s,n){return s.ping0_jobs?.filter(j=>j.node_id===n.id).at(-1);}

function LineCard({node:n,best,state,selected,canSwitch,switching,onFavorite,onDetail,onCheck,onLatency,onSwitch,onMenu}){
 const pending=pendingIds(state),active=state.activity.active_id===n.id,queued=pending.has(n.id),conn=connection(n),attempt=n.last_attempt;
 const note=n.rating_state==='score_pending'?'评分待更新':n.rating_state==='review'?'待复查':n.rating_state==='ip_changed'?'新 IP 待评分':'';
 const error=attempt?.status==='error'?(attempt.diagnosis?.message||attempt.error||'检测未完成'):n.missing?'线路已移除':n.unsupported||'';
 const ip=n.rating_state==='ip_changed'?(n.observed_ip||attempt?.observed_ip):n.latest?.ip;
 const latency=queued?'…':n.latency?.status==='error'?'失败':conn?.status==='ok'?`${conn.delay_ms} ms`:conn?.status==='timeout'?'超时':'测速';
 return <Card padding={0} className={`r-card ${best?'r-best':''} ${selected?'r-current':''} ${active?'checking':''}`} data-node={n.id} data-line={n.id} tabIndex={0} aria-busy={active} onContextMenu={e=>{e.preventDefault();onMenu(n)}} onKeyDown={e=>{if(e.key==='ContextMenu'||(e.shiftKey&&e.key==='F10')){e.preventDefault();onMenu(n)}}}>
 {best&&<span className="r-corner" aria-label="首选"><Star size={11} fill="currentColor"/></span>}
 <div className="r-card-head"><h3 title={n.name}>{n.name}</h3><IB label={`${n.favorite?'取消收藏':'收藏'} ${n.name}`} icon={Star} aria-pressed={!!n.favorite} className={`r-favorite ${n.favorite?'is-favorite':''}`} onClick={()=>onFavorite(n)}/></div>
 <div className="r-address"><span>{ip||'尚未取得 IP'}</span>{n.ip_alert&&<button className="r-ip-change" onClick={()=>onDetail(n,'changes')}>IP 已变</button>}<button className="r-delay production-latency" aria-label={`复测延迟 ${n.name}`} disabled={queued||!canDetect(n)} onClick={()=>onLatency(n)}>{latency}</button></div>
 {error?<button className="production-failure" onClick={()=>onDetail(n,'history')} aria-label={`查看失败原因 ${n.name}`}>{error}</button>:note?<span className="production-review">{note}</span>:null}
 {n.latest&&n.rating_state==='connection_failed'?<div className="production-past-score">上次评分 {n.latest.score} /100</div>:n.latest&&n.rating_state!=='ip_changed'?<Score node={n} onExplain={()=>onDetail(n,'risk')}/>:!error?<div className="production-unrated">{n.config_changed?'配置已变，等待检测':active?'正在检测':queued?'等待检测':'尚未检测'}</div>:null}
 <div className="r-card-foot"><B variant="ghost" data-action="history" onClick={()=>onDetail(n)}>详情<ChevronRight size={12}/></B><B variant="ghost" data-action="check" isDisabled={queued||!canDetect(n)} isLoading={active} onClick={()=>onCheck(n)}>{active?'检测中':queued?'排队中':attempt?.status==='error'?'重试':'检测'}</B>{selected?<span className="r-using"><span/>使用中</span>:<B variant="secondary" data-action="switch" isLoading={switching===n.id} isDisabled={!canSwitch||!!switching||!canDetect(n)} onClick={()=>onSwitch(n)}>换用</B>}</div>
 </Card>
}

export default function App(){
 const [state,setState]=useState(null),[profile,setProfile]=useState(null),[error,setError]=useState(''),[receivedAt,setReceivedAt]=useState(Date.now()),[tick,setTick]=useState(0);
 const [view,setView]=useState(()=>localStorage.getItem('line-view')==='favorites'?'favorites':'lines'),[query,setQuery]=useState(''),[others,setOthers]=useState(false),[scope,setScope]=useState('all');
 const [modal,setModal]=useState(null),[toast,setToast]=useState(''),[pending,setPending]=useState(new Set()),[enqueuing,setEnqueuing]=useState(false),[controls,setControls]=useState({}),[groups,setGroups]=useState({}),[switching,setSwitching]=useState(null);
 const loader=useRef(null),controlLoader=useRef(null),pingSeen=useRef(new Map());
 const notify=useCallback(message=>setToast(message),[]),refresh=useCallback(()=>loader.current?.(),[]);
 useEffect(()=>{let alive=true,loading=false;async function load(){if(loading)return;loading=true;try{const s=await api('/api/state'+(profile?'?profile='+encodeURIComponent(profile):''));if(alive){setState(s);setError('');setReceivedAt(Date.now());if(s.profile_id!==profile)setProfile(s.profile_id);}}catch(e){if(alive)setError(e.message)}finally{loading=false}}loader.current=load;load();const timer=setInterval(load,2000);return()=>{alive=false;clearInterval(timer)}},[profile]);
 useEffect(()=>{const t=setInterval(()=>setTick(t=>t+1),1000);return()=>clearInterval(t)},[]);
 useEffect(()=>{if(!toast)return;const t=setTimeout(()=>setToast(''),4500);return()=>clearTimeout(t)},[toast]);
 const controlIds=state?[...new Set([state.profile_id,...(view==='favorites'?state.favorites.filter(n=>!n.missing).map(n=>n.profile_id):[])].filter(Boolean))].sort().join(','):'';
 useEffect(()=>{let alive=true,loading=false;async function load(){if(loading||!controlIds)return;loading=true;const entries=await Promise.all(controlIds.split(',').map(async id=>{try{return [id,await api('/api/control?profile='+encodeURIComponent(id))]}catch(e){return [id,{profile_id:id,groups:[],can_switch:false,reason:e.message}]}}));if(alive){setControls(Object.fromEntries(entries));setGroups(old=>{const next={...old};for(const [id,c] of entries){const saved=old[id]||localStorage.getItem('clash-group:'+id);next[id]=c.groups.some(g=>g.name===saved)?saved:c.groups[0]?.name||'';}return next;});}loading=false;}controlLoader.current=load;load();const timer=setInterval(load,10000);return()=>{alive=false;clearInterval(timer)}},[controlIds]);
 useEffect(()=>{for(const j of state?.ping0_jobs||[]){const before=pingSeen.current.get(j.job_id);if(before&&before!==j.status){if(j.status==='completed')notify(j.applied_to_current?'Ping0 结果已保存':'IP 已变，结果已保存到原地址记录');if(j.status==='waiting')notify('请在浏览器完成验证，结果会自动保存');if(['error','expired'].includes(j.status))notify(j.error||'补测未完成，请重试');}pingSeen.current.set(j.job_id,j.status)}},[state?.ping0_jobs,notify]);
 async function operate(path,body,message){const key=path+':'+(body?.node_id||body?.profile_id||'');setPending(p=>new Set([...p,key]));try{await api(path,body);if(message)notify(message);await refresh();return true;}catch(e){notify(e.message);return false;}finally{setPending(p=>{const next=new Set(p);next.delete(key);return next})}}
 const viewSource=id=>{setProfile(id);setView('lines');localStorage.setItem('line-view','lines');setQuery('');setScope('all');setOthers(false);setModal(null)};
 const changeView=next=>{setView(next);localStorage.setItem('line-view',next);setScope('all');setQuery('');};
 const onFavorite=n=>operate('/api/favorite',{node_id:n.id,saved:!n.favorite},n.favorite?'已取消收藏':'已加入收藏');
 const onCheck=n=>operate('/api/check',{profile_id:n.profile_id,node_id:n.id},'已加入检测队列');
 const onLatency=n=>operate('/api/latency',{profile_id:n.profile_id,node_id:n.id},'已安排复测延迟');
 async function onPing(n,jobHint){const j=jobHint||latestJob(state,n),key='ping:'+n.id;if(pending.has(key))return;setPending(p=>new Set([...p,key]));try{const r=await api(j?.status==='waiting'?'/api/ping0/reopen':'/api/ping0/open',j?.status==='waiting'?{job_id:j.job_id}:{profile_id:n.profile_id,node_id:n.id});pingSeen.current.set(r.job_id,r.status);notify(r.status==='waiting'?'已打开验证页':'正在查询 Ping0');await refresh();}catch(e){notify(e.message);return false;}finally{setPending(p=>{const next=new Set(p);next.delete(key);return next})}}
 function controlFor(n){const c=controls[n.profile_id],group=c?.groups?.find(g=>g.name===groups[n.profile_id]);return {c,group,eligible:!error&&c?.profile_id===n.profile_id&&c.can_switch&&c.switchable_ids?.includes(n.id)&&group?.members?.includes(n.name)}}
 async function onSwitch(n){const {eligible,group}=controlFor(n);if(!eligible||switching)return;setSwitching(n.id);try{const r=await api('/api/switch',{profile_id:n.profile_id,node_id:n.id,group:group.name});if(!r.verified||!r.persisted)throw new Error('未能确认换用已保存');notify('已换用并保存：'+r.selected);}catch(e){notify(e.message)}finally{await controlLoader.current?.();setSwitching(null)}}
 if(!state)return <div className="production-loading"><img src="/logo.png" width="42" alt=""/><h1>云鉴</h1><p role="status">{error||'正在读取线路…'}</p>{error&&<B variant="primary" onClick={refresh}>重试</B>}</div>;
 const current=state.profiles.find(p=>p.id===state.profile_id),pool=view==='favorites'?state.favorites:state.nodes,search=query.trim().toLowerCase();
 const matches=n=>!search||`${n.name} ${n.latest?.ip||n.observed_ip||''} ${n.profile_name||''}`.toLowerCase().includes(search);
 const byId=new Map(state.nodes.map(n=>[n.id,n])),ranked=state.recommendations.items.filter(r=>byId.has(r.id));
 const ids=new Set(ranked.map(n=>n.id)),recommended=ranked.filter(r=>matches(byId.get(r.id))).map(r=>({...byId.get(r.id),recommendation:r}));
 const rest=state.nodes.filter(n=>!ids.has(n.id)&&matches(n)),favorites=state.favorites.filter(matches);
 const best=recommended[0]&&!recommended[0].recommendation.needs_review?recommended[0].id:null;
 const targets=(scope==='all'?pool:view==='favorites'?favorites:recommended).filter(canDetect),pendingSet=pendingIds(state);
 const changes=pool.filter(n=>n.ip_alert),conditions=state.settings.recommendation;
 const sourceGroups=new Map();for(const p of state.profiles){const origin=p.origin||'其他来源';if(!sourceGroups.has(origin))sourceGroups.set(origin,[]);sourceGroups.get(origin).push(p)}
 const wholeList=scope==='all'&&view==='lines';
 const batchProfiles=new Set(state.activity.batch_profiles||[]);
 const batchPending=wholeList?batchProfiles.has(state.profile_id):targets.some(n=>batchProfiles.has(n.profile_id));
 async function checkScope(){
  if(enqueuing||batchPending||(!wholeList&&!targets.length))return;
  setEnqueuing(true);
  try{
   const groups=wholeList?[{profile_id:state.profile_id}]:Object.entries(targets.reduce((out,n)=>{(out[n.profile_id]??=[]).push(n.id);return out},{})).map(([profile_id,node_ids])=>({profile_id,node_ids}));
   await api('/api/check-batch',{groups});
   notify('已安排，先同步列表再检测');
  }catch(e){notify(e.message)}finally{await refresh();setEnqueuing(false)}
 }

 const lineProps=n=>{const {eligible,group}=controlFor(n);return {node:n,state,best:view==='lines'&&n.id===best,selected:eligible&&group?.selected===n.name,canSwitch:eligible,switching,onFavorite,onCheck,onLatency,onSwitch,onDetail:(n,tab='history')=>setModal({kind:'detail',id:n.id,tab}),onMenu:n=>setModal({kind:'menu',id:n.id})}};
 const regionNames=conditions.regions.map(id=>state.recommendations.regions.find(r=>r.id===id)?.name||({HK:'香港',TW:'台湾',JP:'日本',SG:'新加坡',US:'美国'}[id])||id);
 const ruleSummary=`风险 ≤ ${conditions.max_risk} · ${regionNames.length?regionNames.join('、'):'不限地区'} · 近期确认优先`;
 return <div className="r-app r-h production-app"><aside className="r-sidebar"><div className="r-brand"><img src="/logo.png" width="30" height="30" alt=""/><span>云鉴</span></div><nav className="r-nav" aria-label="页面"><B variant="ghost" icon={LayoutGrid} aria-current={view==='lines'?'page':undefined} onClick={()=>changeView('lines')}>线路</B><B label="收藏" variant="ghost" icon={Star} aria-current={view==='favorites'?'page':undefined} onClick={()=>changeView('favorites')}>收藏<span className="r-nav-count">{state.favorites.length}</span></B></nav><div className="production-source-scroll">{[...sourceGroups].map(([client,profiles])=><section key={client}><div className="r-source-heading"><span>{client}</span></div><div className="r-sources">{profiles.map(p=><button key={p.id} aria-current={view==='lines'&&p.id===state.profile_id?'page':undefined} className={view==='lines'&&p.id===state.profile_id?'is-active':''} onClick={()=>viewSource(p.id)}><Folder size={15}/><span title={p.name}>{p.name}</span><small>{p.node_count}</small></button>)}</div></section>)}</div><div className="production-source-manage"><B variant="ghost" icon={Settings2} onClick={()=>setModal({kind:'sources'})}>线路管理</B></div></aside>
 <div className="r-workspace"><header className="r-header"><h1><strong title={view==='favorites'?'我的收藏':current?.name}>{view==='favorites'?'我的收藏':current?.name||'添加线路'}</strong></h1><div className="r-header-tools"><div className="r-tools"><div className="r-find"><div className="r-search"><TextInput label="搜索线路" isLabelHidden placeholder="搜索线路或 IP" value={query} onChange={setQuery} hasClear size="sm" startIcon={<Search size={15}/>}/></div></div><div className="r-checks"><Tasks state={state} error={error} receivedAt={receivedAt} tick={tick} pendingRequest={pending.has('/api/clear-queue:')} onClear={()=>operate('/api/clear-queue',{},'已清空排队，正在检测的线路会完成')} onViewSource={viewSource}/><B variant="ghost" icon={Clock3} onClick={()=>setModal({kind:'plan'})}>{state.settings.paused?'计划暂停':state.profiles.some(p=>p.enabled)?'自动计划':'未选列表'}</B><div className="r-batch"><select className="r-scope" aria-label="检测范围" value={scope} onChange={e=>setScope(e.target.value)}><option value="all">{view==='favorites'?'全部收藏':'当前列表'}</option><option value="filtered">{view==='favorites'?'搜索结果':'筛选推荐'}</option></select><B variant="primary" icon={RefreshCw} isLoading={enqueuing} isDisabled={!!error||enqueuing||batchPending||(wholeList?!current:!targets.length)} onClick={checkScope}>{batchPending?'同步中':targets.length?`检测 ${targets.length} 条`:'同步检测'}</B></div></div></div></div></header>
 <main className="r-main">{error&&<div className="production-offline" role="alert"><WifiOff size={16}/>{error}<B onClick={refresh} variant="ghost">重试</B></div>}{!state.profiles.length&&view==='lines'?<div className="r-empty"><Folder size={28}/><h2>添加线路</h2><p>同步 Clash，或导入服务商提供的链接。</p><B variant="primary" icon={Plus} onClick={()=>setModal({kind:'sources'})}>添加列表</B></div>:<>

 <div className="r-section-head"><div className="production-recommendation-head"><h2>{view==='favorites'?'已收藏':'推荐线路'}<span>{view==='favorites'?favorites.length:recommended.length}</span></h2>{view==='lines'&&<div className="production-recommendation-rule"><span aria-label="当前推荐规则">{ruleSummary}</span><IB label="推荐设置" icon={Settings} onClick={()=>setModal({kind:'filter'})}/></div>}</div>{changes.length>0&&<B variant="ghost" icon={Radio} onClick={()=>setModal({kind:'changes'})}>{changes.length} 条 IP 变化</B>}</div>
 {view==='favorites'?<div id="favorites-grid">{[...new Set(favorites.map(n=>n.profile_id))].map(id=><section className="production-favorite-source" key={id}><h3>{favorites.find(n=>n.profile_id===id)?.client} · {favorites.find(n=>n.profile_id===id)?.profile_name}</h3><div className="r-grid">{favorites.filter(n=>n.profile_id===id).map(n=><LineCard key={n.id} {...lineProps(n)}/>)}</div></section>)}</div>:<div id="candidates" className="r-grid">{recommended.map(n=><LineCard key={n.id} {...lineProps(n)}/>)}</div>}
 {!(view==='favorites'?favorites.length:recommended.length)&&<div className="r-empty"><Search size={22}/><h3>{view==='favorites'?'没有匹配的收藏':'暂无推荐线路'}</h3><p>{search?'试试其他名称，或清除搜索。':view==='favorites'?'点线路上的星标，即可收藏。':state.recommendations.message}</p>{query&&<B variant="secondary" onClick={()=>setQuery('')}>清除搜索</B>}</div>}
 {view==='lines'&&<section className="r-other"><B variant="ghost" icon={others?ChevronDown:ChevronRight} aria-expanded={others} onClick={()=>setOthers(x=>!x)}>其他线路<span>{rest.length}</span></B>{others&&<><div className="production-clash"><label>切换分组<select aria-label="选择要更换线路的分组" value={groups[state.profile_id]||''} disabled={!controls[state.profile_id]?.groups?.length||!!switching} onChange={e=>{setGroups(g=>({...g,[state.profile_id]:e.target.value}));localStorage.setItem('clash-group:'+state.profile_id,e.target.value)}}>{controls[state.profile_id]?.groups?.map(g=><option key={g.name}>{g.name}</option>)}</select></label><B variant="ghost" onClick={()=>controlLoader.current?.()}>刷新分组</B><p>{controls[state.profile_id]?.can_switch?'只更改所选分组，检测不会切换线路。':controls[state.profile_id]?.reason||'正在读取 Clash…'}</p></div><div id="other-grid" className="r-grid">{rest.map(n=><LineCard key={n.id} {...lineProps(n)}/>)}</div></>}</section>}
 </>}</main></div>
 <Dialogs modal={modal} setModal={setModal} state={state} api={api} refresh={refresh} notify={notify} operate={operate} onCheck={onCheck} onPing={onPing} onLatency={onLatency} onFavorite={onFavorite} onViewSource={viewSource}/>
 {toast&&<div className="r-toast" role="status" id="toast"><Check size={16}/>{toast}<IB label="关闭提示" icon={X} onClick={()=>setToast('')}/></div>}
 </div>
}
