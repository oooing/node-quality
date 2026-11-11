import React, {useEffect, useMemo, useState} from 'react';
import {Dialog} from '@astryxdesign/core/Dialog';
import {TextInput} from '@astryxdesign/core/TextInput';
import {Switch} from '@astryxdesign/core/Switch';
import {CheckboxInput} from '@astryxdesign/core/CheckboxInput';
import {X, Star, RefreshCw, ArrowRight, CircleAlert, FolderOpen} from 'lucide-react';
import {B, IB, fmt, grade} from './shared.jsx';
import './dialogs.css';

const preferred = [['HK','香港'],['TW','台湾'],['JP','日本'],['SG','新加坡'],['US','美国']];
const detailTabs = [['history','历史记录'],['changes','IP 变化'],['risk','风险说明']];
const profileName = (state, id) => state?.profiles?.find(p=>p.id===id)?.name || '已移除列表';

function Diagnosis({record}) {
  if (!record || record.status !== 'error') return null;
  const d = record.diagnosis;
  return <div className="production-error" role="status"><CircleAlert size={16}/><div>
    <strong>{d?.message || record.error || '本次检测未完成'}</strong>
    {(d?.detail || d?.evidence?.length || d?.suggestion) && <details><summary>诊断详情</summary>
      {d.detail && <p>{d.detail}</p>}{d.evidence?.length > 0 && <ul>{d.evidence.map((e,i)=><li key={i}>{e}</li>)}</ul>}
      {d.suggestion && <p>{d.suggestion}</p>}</details>}
  </div></div>;
}

export default function Dialogs({modal, setModal, state, api, refresh, notify, operate, onCheck, onPing, onLatency, onFavorite, onViewSource}) {
  const [busy,setBusy] = useState('');
  const [error,setError] = useState('');
  const [risk,setRisk] = useState(30);
  const [regions,setRegions] = useState([]);
  const [enabled,setEnabled] = useState([]);
  const [automatic,setAutomatic] = useState(false);
  const [name,setName] = useState('');
  const [url,setUrl] = useState('');
  const [directory,setDirectory] = useState('');
  const [tab,setTab] = useState('history');
  const [history,setHistory] = useState([]);
  const [pingHistory,setPingHistory] = useState([]);
  const [historyError,setHistoryError] = useState('');
  const [historyLoading,setHistoryLoading] = useState(false);
  const [retry,setRetry] = useState(0);
  const [detailState,setDetailState] = useState(null);
  const allNodes = useMemo(()=>[...new Map([...(state?.favorites||[]),...(state?.nodes||[])].map(n=>[n.id,n])).values()],[state?.nodes,state?.favorites]);
  const baseNode = allNodes.find(n=>n.id===modal?.id);
  const node = modal?.id && detailState?.node?.id===modal.id ? {...baseNode,...detailState.node} : baseNode;
  const changes = allNodes.filter(n=>n.ip_alert);
  const profileGroups = [...new Set((state?.profiles||[]).map(p=>p.origin||'其他来源'))];
  const choices = useMemo(()=>{
    const map = new Map(preferred.map(([id,name])=>[id,{id,name}]));
    for (const r of state?.recommendations?.regions || []) if(!map.has(r.id)) map.set(r.id,r);
    for (const id of regions) if(!map.has(id)) map.set(id,{id,name:id});
    return [...map.values()];
  },[state?.recommendations?.regions,regions]);
  const queued = Boolean(node && ((state?.activity?.queued||[]).includes(node.id) || state?.activity?.active_id===node.id));
  const pingJob = (detailState?.jobs || state?.ping0_jobs || []).filter(j=>j.node_id===modal?.id).at(-1);

  useEffect(()=>{
    if (!modal) return;
    setError('');setBusy('');setDetailState(null);
    setRisk(state?.settings?.recommendation?.max_risk ?? 30);
    setRegions(state?.settings?.recommendation?.regions || []);
    setEnabled((state?.profiles||[]).filter(p=>p.enabled).map(p=>p.id));
    setAutomatic(!state?.settings?.paused);
    setTab(modal.tab || 'history');
    if(modal.kind==='detail'){setHistory([]);setPingHistory([]);setHistoryError('');}
  },[modal?.kind,modal?.id]);

  // Detail polling also covers a favorite from a different list. It never changes the selected list.
  useEffect(()=>{
    if(modal?.kind!=='detail' || !modal.id) return;
    let alive=true, running=false;
    const id=modal.id, profile=baseNode?.profile_id;
    const load=async(initial=false)=>{
      if(running)return;running=true;
      if(initial)setHistoryLoading(true);
      try{
        const [records,supplements,sourceState] = await Promise.all([
          api('/api/history?node='+encodeURIComponent(id)),
          api('/api/ping0/history?node='+encodeURIComponent(id)),
          profile ? api('/api/state?profile='+encodeURIComponent(profile)) : Promise.resolve(null),
        ]);
        if(alive){setHistory(records);setPingHistory(supplements);setHistoryError('');
          if(sourceState)setDetailState({node:sourceState.nodes.find(n=>n.id===id),jobs:sourceState.ping0_jobs});}
      }catch(e){if(alive)setHistoryError(e.message || '记录暂时无法读取');}
      finally{running=false;if(alive)setHistoryLoading(false);}
    };
    load(true);const timer=setInterval(()=>load(),2000);
    return()=>{alive=false;clearInterval(timer)};
  },[modal?.kind,modal?.id,baseNode?.profile_id,retry]);

  async function task(key, callback) {
    if(busy)return false;
    setBusy(key);setError('');
    try{return await callback();}
    catch(e){setError(e.message || '操作未完成，请重试');return false;}
    finally{setBusy('');}
  }
  async function post(path,body,message) {
    await api(path,body);await refresh();if(message)notify(message);
  }
  async function saveFilter() {
    if(risk===''||!Number.isFinite(Number(risk))||Number(risk)<0||Number(risk)>100){setError('风险上限需在 0–100 之间');return;}
    await task('save',async()=>{await post('/api/settings',{recommendation:{max_risk:Number(risk),regions}},'推荐条件已保存');setModal(null);});
  }
  async function savePlan() {
    await task('save',async()=>{
      // When pausing, stop scheduling before changing the enabled sources.
      if(!automatic){
        await api('/api/settings',{paused:true});
        try{await api('/api/enable',{ids:enabled});}
        catch(e){await refresh();throw new Error('自动检测已暂停，列表选择未保存：'+e.message);}
      }else{
        await api('/api/enable',{ids:enabled});
        try {await api('/api/settings',{paused:false});}
        catch(e){await refresh();throw new Error('列表选择已保存，自动开关未保存：'+e.message);}
      }
      await refresh();notify('检测计划已保存');setModal(null);
    });
  }
  async function discover(custom=false) {
    if(custom&&!directory.trim()){setError('请填写配置文件夹路径');return;}
    await task('discover',async()=>{
      const result=await api('/api/discover',custom?{directory:directory.trim()}:{});
      await refresh();notify(`已同步 ${result.count} 个列表${result.removed?`，移除 ${result.removed} 个旧列表`:''}`);
    });
  }
  async function addUrl(e) {
    e.preventDefault();if(!url.trim())return;
    await task('add',async()=>{await post('/api/add',{name:name.trim(),url:url.trim()},'线路列表已添加');setUrl('');setName('');});
  }
  async function addFile(e) {
    const file=e.target.files?.[0];e.target.value='';if(!file)return;
    if(file.size>8*1024*1024){setError('文件超过 8 MB');return;}
    await task('file',async()=>{await post('/api/add',{name:name.trim()||file.name,text:await file.text()},'文件已导入');setName('');});
  }
  const action = (key, callback) => task(key,async()=>{const result=await callback(node, key==='ping'?pingJob:undefined);if(result!==false)setRetry(x=>x+1);return result;});
  const unavailable = !node || node.missing || Boolean(node.unsupported);
  const latest = node?.latest;
  const reason = node?.last_attempt;
  const latestPing = latest?.ping0_latest;
  const hasScore = typeof latest?.score==='number' && Number.isFinite(latest.score);
  const changedIP = node?.rating_state==='ip_changed';
  const connectivity = node?.latency?.connectivity || reason?.connectivity;
  const ratingNote = {review:'待复查',score_pending:'评分待更新',ip_changed:'新 IP 待评分',connection_failed:'连接未确认',unrated:'尚未检测'}[node?.rating_state];
  const title = {filter:'推荐设置',plan:'自动计划',sources:'线路管理',changes:'IP 变化'}[modal?.kind] || node?.name || '线路详情';

  return <Dialog isOpen={!!modal} onOpenChange={open=>!open&&!busy&&setModal(null)} padding={0} width={modal?.kind==='menu'?340:modal?.kind==='sources'?620:560} className="r-dialog production-dialog" aria-labelledby="production-dialog-title">
    <div className="r-dialog-head"><h2 id="production-dialog-title">{title}</h2><IB label="关闭" icon={X} isDisabled={!!busy} onClick={()=>setModal(null)}/></div>
    <div className="r-dialog-body">
      {error&&<div className="production-error" role="alert"><CircleAlert size={16}/><span>{error}</span></div>}
      {modal?.kind==='filter'&&<>
        <div className="r-setting-label"><label htmlFor="production-risk">风险上限</label><span>越低越严格</span></div>
        <div className="production-risk-input"><input id="production-risk" aria-label="风险上限" type="number" min="0" max="100" step="1" value={risk} onChange={e=>setRisk(e.target.value)} disabled={!!busy}/><span>/ 100</span></div>
        <div className="r-presets">{[10,30,50,100].map(n=><B key={n} variant={Number(risk)===n?'primary':'secondary'} aria-pressed={Number(risk)===n} isDisabled={!!busy} onClick={()=>setRisk(n)}>{n===100?'不限':`${n} 分`}</B>)}</div>
        <div className="r-setting-label"><h3>地区</h3><B variant="ghost" isDisabled={!!busy} onClick={()=>setRegions([])}>清空选择</B></div>
        <div className="r-regions">{choices.map(r=><CheckboxInput key={r.id} label={r.name} isDisabled={!!busy} value={regions.includes(r.id)} onChange={checked=>setRegions(xs=>checked?[...xs,r.id]:xs.filter(x=>x!==r.id))}/>)}</div>
        <p className="r-note">不选则不限地区。优先近期确认，再看低风险，同分看历史。</p>
        <p className="r-note">仅影响推荐线路，不会隐藏你的收藏。</p>
      </>}
      {modal?.kind==='plan'&&<div className="r-plan">
        <div className="r-setting-label"><Switch label="自动检测" isDisabled={!!busy} value={automatic} onChange={setAutomatic}/><span>{automatic?enabled.length?`${enabled.length} 个列表`:'未选列表':'已暂停'}</span></div>
        <p className="r-note">每天更新并检测勾选的列表，不跟随当前页面。</p>
        <div className="r-plan-sources">{profileGroups.map(group=><section className="production-source-group" key={group}><h3>{group}</h3>{(state?.profiles||[]).filter(p=>(p.origin||'其他来源')===group).map(p=><div className="r-plan-source" key={p.id}><CheckboxInput label={p.name||'未命名列表'} isDisabled={!!busy} value={enabled.includes(p.id)} onChange={checked=>setEnabled(xs=>checked?[...xs,p.id]:xs.filter(x=>x!==p.id))}/><span>{p.node_count} 条</span></div>)}</section>)}</div>
        {!state?.profiles?.length&&<p className="r-note">暂无列表，请先在线路管理中添加。</p>}
        {automatic&&!enabled.length&&<div className="production-error"><CircleAlert size={16}/><span>未选列表，不会开始自动检测。</span></div>}
        <p className="r-note">应用退出后停止；关闭开关不取消手动排队。</p>
        <details className="production-advanced"><summary>网页助手</summary><p>Ping0 验证后，扩展会自动带回结果。</p><B variant="secondary" icon={FolderOpen} isDisabled={!!busy} onClick={()=>task('extension',()=>post('/api/extension-folder',{}))}>打开文件</B></details>
      </div>}
      {modal?.kind==='sources'&&<>
        <div className="production-source-toolbar"><B variant="secondary" icon={RefreshCw} isDisabled={!!busy} isLoading={busy==='discover'} onClick={()=>discover()}>同步列表</B><span className="r-note">读取客户端，不改原配置。</span></div>
        {profileGroups.map(group=><section className="production-source-group" key={group}><h3>{group}</h3>{(state?.profiles||[]).filter(p=>(p.origin||'其他来源')===group).map(p=><div className="production-source-row" key={p.id}><div><strong>{p.name||'未命名列表'}</strong><span>{p.node_count} 条{p.current?' · Clash 当前列表':''}</span>{p.error&&<span className="production-source-error">{p.error}</span>}</div><span className="r-note">{p.enabled?'自动检测':'仅手动'}</span></div>)}</section>)}
        {!state?.profiles?.length&&<p className="r-note">没有发现列表，可粘贴链接或导入文件。</p>}
        <details className="production-advanced" open={!state?.profiles?.length}><summary>添加列表</summary><form className="production-form" onSubmit={addUrl}>
          <TextInput label="列表名称" value={name} onChange={setName} placeholder="可以不填" maxLength={120} isDisabled={!!busy}/>
          <TextInput label="导入链接" type="url" value={url} onChange={setUrl} placeholder="服务商提供的线路链接" autoComplete="off" spellCheck={false} isDisabled={!!busy}/>
          <div className="production-form-actions"><label className="production-file">导入文件<input type="file" accept=".yaml,.yml" onChange={addFile} disabled={!!busy} aria-label="导入 YAML 文件"/></label><B variant="primary" type="submit" isDisabled={!!busy||!url.trim()} isLoading={busy==='add'}>添加</B></div>
        </form></details>
        <details className="production-advanced"><summary>手动查找</summary><div className="production-form"><TextInput label="配置目录" value={directory} onChange={setDirectory} placeholder="Clash 配置文件夹路径" isDisabled={!!busy}/><B variant="secondary" isDisabled={!!busy||!directory.trim()} onClick={()=>discover(true)}>读取列表</B></div></details>
      </>}
      {modal?.kind==='changes'&&<div className="r-changes-list">{changes.map(n=><div className="r-change-row" key={n.id}><strong>{n.name}</strong><div><span>{n.ip_alert.previous_ip}</span><ArrowRight size={14}/><b>{n.ip_alert.current_ip}</b></div><B variant="ghost" isDisabled={!!busy} onClick={()=>task(n.id,()=>post('/api/ip-ack',{node_id:n.id}))}>已知晓</B></div>)}{!changes.length&&<p className="r-note">当前线路与收藏没有待查看的 IP 变化。</p>}</div>}
      {modal?.kind==='menu'&&node&&<div className="production-menu"><B variant="ghost" icon={Star} isDisabled={!!busy} onClick={()=>task('favorite',async()=>{if(await onFavorite(node)!==false)setModal(null)})}>{node.favorite?'取消收藏':'收藏线路'}</B><B variant="ghost" isDisabled={!!busy} onClick={()=>setModal({kind:'detail',id:node.id})}>查看详情</B><B variant="ghost" isDisabled={!!busy||unavailable||queued} onClick={()=>task('latency',async()=>{if(await onLatency(node)!==false)setModal(null)})}>复测延迟</B>{onViewSource&&!node.missing&&<B variant="ghost" isDisabled={!!busy} onClick={()=>{onViewSource(node.profile_id);setModal(null)}}>查看列表</B>}</div>}
      {modal?.kind==='detail'&&(node?<>
        <div className="r-detail-meta"><span>{node.profile_name||profileName(state,node.profile_id)}</span><span>{node.observed_ip||latest?.ip||'尚未取得 IP'}</span><IB icon={Star} label={node.favorite?'取消收藏':'收藏线路'} aria-pressed={!!node.favorite} className={`r-favorite ${node.favorite?'is-favorite':''}`} isDisabled={!!busy} onClick={()=>action('favorite',onFavorite)}/></div>
        <div className="production-detail-score">{changedIP?<span>新 IP 尚无评分</span>:hasScore?<><span>IPPure</span><strong>{latest.score}</strong><span>/100</span><span>{grade(latest.score)?.[1]}</span></>:<span>{node.unsupported||'尚无风险评分'}</span>}{!changedIP&&latestPing?.status==='ok'&&latestPing.ip===latest?.ip&&<span className="production-ping">Ping0 <b>{latestPing.score}%</b></span>}</div>
        {changedIP&&hasScore&&<p className="r-note">上次地址 {latest.ip} · IPPure {latest.score} /100 · {grade(latest.score)?.[1]}</p>}
        {connectivity?.status==='ok'&&<p className="r-note">连接耗时 {connectivity.delay_ms} 毫秒{node.latency?.checked_at?` · ${fmt(node.latency.checked_at)}`:''}</p>}
        {ratingNote&&<p className="r-note">{ratingNote}{latest&&node.rating_state!=='current'?` · 上次评分 ${fmt(latest.checked_at)}`:''}</p>}
        <Diagnosis record={reason}/>
        {node.latency?.status==='error'&&<div className="production-error"><CircleAlert size={16}/><span>{node.latency.error||'延迟复测未完成'}</span></div>}
        <div className="r-detail-actions"><B variant="primary" icon={RefreshCw} isDisabled={!!busy||unavailable||queued} isLoading={busy==='check'} onClick={()=>action('check',onCheck)}>{queued?'已排队':'重新检测'}</B><B variant="secondary" isDisabled={!!busy||unavailable||!hasScore||pingJob?.status==='checking'} isLoading={busy==='ping'} onClick={()=>action('ping',onPing)}>{pingJob?.status==='waiting'?'打开验证':pingJob?.status==='checking'?'补测中':'Ping0 补测'}</B><B variant="ghost" isDisabled={!!busy||unavailable||queued} onClick={()=>action('latency',onLatency)}>复测延迟</B></div>
        {pingJob&&<div className={`production-job ${['error','expired'].includes(pingJob.status)?'production-error':''}`} role="status">{({checking:'正在查询 Ping0…',waiting:'请在浏览器完成验证，结果会自动保存。',completed:pingJob.applied_to_current?'Ping0 结果已保存。':'IP 已变化，补测已存入之前地址的记录。'})[pingJob.status]||pingJob.error||pingJob.message}</div>}
        <nav className="r-tabs" aria-label="线路详情">{detailTabs.map(([id,label])=><B key={id} variant={tab===id?'secondary':'ghost'} aria-pressed={tab===id} onClick={()=>setTab(id)}>{label}</B>)}</nav>
        {tab==='history'&&<>
          {historyError&&<div className="production-error" role="alert"><span>{historyError}</span><B variant="ghost" onClick={()=>setRetry(x=>x+1)}>重试</B></div>}
          {historyLoading&&!history.length&&<p className="r-note">正在读取记录…</p>}
          {!historyLoading&&!historyError&&!history.length&&<p className="r-note">暂无记录，检测后可在这里查看。</p>}
          <div className="production-history">{history.map((r,i)=><article className="production-history-record" key={`${r.checked_at}-${i}`}><header><span>{fmt(r.checked_at)}</span>{r.status==='ok'&&<strong>{r.score} /100</strong>}</header>{r.status==='ok'?<p>{r.ip} · {grade(r.score)?.[1]}</p>:<Diagnosis record={r}/>}{r.previous_ip&&<p>IP 变化：{r.previous_ip} → {r.observed_ip||r.ip}</p>}{r.connectivity&&<p className="r-note">{r.connectivity.status==='ok'?`连接耗时 ${r.connectivity.delay_ms} 毫秒`:'本次连接测试未通过。'}</p>}</article>)}</div>
          {pingHistory.length>0&&<section className="production-history"><h3>补测记录</h3>{pingHistory.map((r,i)=><article className="production-history-record" key={`${r.checked_at}-${i}`}><header><span>{fmt(r.checked_at)}</span><strong>{r.score}%</strong></header><p>{r.ip} · {r.label}{latest?.ip&&r.ip!==latest.ip?' · 之前地址':''}</p></article>)}</section>}
        </>}
        {tab==='changes'&&<>{node.ip_alert?<div className="r-detail-change"><p>{node.ip_alert.previous_ip}<ArrowRight size={14}/><strong>{node.ip_alert.current_ip}</strong></p><p className="r-note">{fmt(node.ip_alert.checked_at)}</p><B variant="secondary" isDisabled={!!busy} onClick={()=>task('ack',async()=>{await post('/api/ip-ack',{node_id:node.id},'已确认 IP 变化');setRetry(x=>x+1)})}>已知晓</B></div>:<p className="r-note">没有待确认的变化，过往变化保留在历史中。</p>}</>}
        {tab==='risk'&&<div className="r-risk-help"><p>IPPure 为 0–100 分，越低越好；不代表封禁概率或连接速度。</p><div className="production-tiers">{[['0–15','极度纯净'],['＞15–25','纯净'],['＞25–40','中性'],['＞40–50','轻度风险'],['＞50–70','中度风险'],['＞70–100','极度风险']].map(([range,label])=><React.Fragment key={range}><span>{range}</span><strong>{label}</strong></React.Fragment>)}</div><p>Ping0 为 0–100%，两家分开显示，推荐使用 IPPure。</p><p>补测查询上次取得的 IP；确认最新地址请重新检测。</p></div>}
      </>:<p className="r-note">这条线路已不在当前列表，刷新后重试。</p>)}
    </div>
    {modal?.kind!=='menu'&&<div className="r-dialog-foot">{modal?.kind==='filter'?<B variant="ghost" isDisabled={!!busy} onClick={()=>{setRisk(30);setRegions([])}}>重置</B>:<span className="r-note">{modal?.kind==='plan'?'不切换正在使用的线路':''}</span>}<B variant="primary" isDisabled={!!busy} isLoading={busy==='save'} onClick={modal?.kind==='filter'?saveFilter:modal?.kind==='plan'?savePlan:()=>setModal(null)}>{['filter','plan'].includes(modal?.kind)?'保存':'完成'}</B></div>}
  </Dialog>;
}
