import React from 'react';
import {Button} from '@astryxdesign/core/Button';
const labelOf=children=>React.Children.toArray(children).map(c=>typeof c==='string'||typeof c==='number'?String(c):React.isValidElement(c)?labelOf(c.props.children):'').join('');
export function B({children,icon:Icon,size='sm',...props}){return <Button label={props.label||labelOf(children)} size={size} icon={Icon?<Icon size={15} strokeWidth={1.7}/>:undefined} {...props}><span className="r-btn-content">{children}</span></Button>}
export function IB({label,icon:Icon,...props}){return <Button label={label} isIconOnly size="sm" variant="ghost" icon={<Icon size={16} strokeWidth={1.7}/>} {...props}/>}
export const fmt=value=>value?new Date(typeof value==='number'?value*1000:value).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}):'尚未检测';
export function grade(score){return [[15,'极度纯净',''],[25,'纯净',''],[40,'中性','warn'],[50,'轻度风险','warn'],[70,'中度风险','bad'],[100,'极度风险','bad']].find(x=>score<=x[0])||[100,'未评分',''];}
export function Score({node,n,onExplain}){const v=node||n,latest=v?.latest;const supplement=latest?.ping0_latest;
 if(!latest)return <span className="r-muted">{v?.missing?'线路已移除':v?.unsupported||'尚未评分'}</span>;
 return <div className="r-score-row"><button className="production-score" onClick={onExplain} aria-label={`IPPure 风险 ${latest.score}，查看说明`}><span className="r-provider">IPPure</span><strong>{latest.score}</strong><span className="r-outof">/100</span></button>{supplement?.status==='ok'&&supplement.ip===latest.ip?<button className="r-ping-inline production-score" onClick={onExplain} aria-label={`Ping0 风险 ${supplement.score}%`}>Ping0 <b>{supplement.score}</b><span>%</span></button>:null}<span className={`r-risk-label ${grade(latest.score)[2]?'is-caution':''}`}>{grade(latest.score)[1]}</span></div>
}
