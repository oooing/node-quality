import React,{useState} from 'react';
import {Dialog} from '@astryxdesign/core/Dialog';
import {ProgressBar} from '@astryxdesign/core/ProgressBar';
import {Activity,History,X} from 'lucide-react';
import {B,IB,fmt} from './shared.jsx';

const stages={network:'准备连接',starting:'开始检测',connectivity:'测试连接',connectivity_retry:'尝试另一个测试网站',dns:'查找检测网站地址',risk_wait:'等待评分查询',risk:'查询 IP 和风险',diagnosis:'诊断连接问题'};
export default function Tasks({state,error,receivedAt,tick,onClear,pendingRequest,onViewSource}){
 const [open,setOpen]=useState(false),a=state.activity,lists=a.lists||[];
 const pending=r=>r.active||r.queued>0||r.syncing||(!state.settings.paused&&r.enabled&&r.remaining>0);
 const busy=lists.some(pending)||!!a.active_id||!!a.updating;
 const cooling=busy&&a.cooldown_until*1000>Date.now();
 const title=error?'连接中断':cooling?'等待重试':busy?'后台检测':'检测记录';
 const activeName=state.profiles.find(p=>p.id===a.active_profile_id)?.name||'其他列表';
 const elapsed=Math.floor((a.elapsed_seconds||0)+Math.max(0,(Date.now()-receivedAt)/1000));
 const stage=a.active_kind==='latency'?'复测延迟':stages[a.stage?.stage]||'检测中';
 const ordered=[...lists].sort((x,y)=>Number(pending(y))-Number(pending(x)));
 const status=r=>r.syncing?'同步列表':r.active?stage:r.queued?'排队中':pending(r)?cooling?'等待重试':'等待检测':!r.checked_at?'尚未检测':r.remaining?'有待检测线路':'检测完成';
 return <>
  <B variant="secondary" className={`production-task-trigger ${busy&&!cooling&&!error?'is-running':''}`} icon={busy?Activity:History} onClick={()=>setOpen(true)} aria-haspopup="dialog">{title}</B>
  <Dialog isOpen={open} onOpenChange={setOpen} padding={0} width={520} className="r-dialog production-dialog" aria-labelledby="task-title">
   <div className="r-dialog-head"><h2 id="task-title">{busy?'检测任务':'检测记录'}</h2><IB label="关闭任务" icon={X} onClick={()=>setOpen(false)}/></div>
   <div className="r-dialog-body production-tasks">
    {error?<p role="alert">连接中断，进度暂未更新。</p>:<>
     {a.active_id&&<div className="production-task-now" role="status"><strong>{activeName}</strong><span>{stage} · {elapsed} 秒</span><p>{a.active_name}</p></div>}
     {cooling&&<p className="production-service-note">等待网站允许查询，约 {Math.ceil((a.cooldown_until*1000-Date.now())/60000)} 分钟后重试。</p>}
    </>}
    {!lists.length&&<p className="r-note">添加列表后，可在这里查看检测进度。</p>}
    {ordered.map(r=><article key={r.profile_id} className="production-task-list" data-task-profile={r.profile_id}>
     <header><button onClick={()=>{setOpen(false);onViewSource(r.profile_id)}}>{r.name}</button><span>{error?'暂未更新':status(r)}</span></header>
     <div className="production-coverage"><span>{r.checked_at||pending(r)?`近 24 小时已检查 ${r.completed} / ${r.total}`:'尚无检测记录'}</span>{r.failed>0&&<span>失败 {r.failed}</span>}</div>
     {!error&&pending(r)&&!r.syncing&&a.active_kind!=='latency'&&r.remaining>0&&<ProgressBar label={`${r.name}检测进度`} isLabelHidden value={r.completed} max={Math.max(1,r.total)}/>}
     {r.checked_at&&<small>最近检查 {fmt(r.checked_at)}</small>}
     {r.skipped>0&&<small> · {r.skipped} 条不支持检测</small>}
    </article>)}
    {a.message&&<p className="production-service-note">{a.message}</p>}
   </div>
   <div className="r-dialog-foot">{(a.queued.length>0||a.batch_profiles?.length>0)?<B variant="ghost" isDisabled={pendingRequest||!!error} onClick={onClear}>清空排队</B>:<span/>}<B variant="primary" onClick={()=>setOpen(false)}>完成</B></div>
  </Dialog>
 </>;
}
