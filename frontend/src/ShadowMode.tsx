import {useEffect,useRef,useState} from 'react'
import * as echarts from 'echarts'
import snapshot from './site-demo-report.json'

type Series={day:string[],baseline:number[],candidate:number[],observed?:(number|null)[]}
type Indicator={n:number,nse:number|null,bias_pct:number|null,r2:number|null,mae?:number,kind?:string,calibration_factor?:number}
type Consent={baseline:{name:string,status:string,detail:string},candidate:{name:string,status:string,detail:string}}
type Cal={status:string,used:boolean,params?:{mu_a_scale:number,alpha_scale:number},train_days?:number,test_days?:number,notes?:string[],held_out?:{nh4_error_before:number,nh4_error_after:number,improvement_pct:number}}
type Report={site:string,synthetic?:boolean,calibration?:Cal|null,window:{start:string,end:string,days:number,warmup_days_excluded:number},current_control:{do_setpoint:number},candidate:{so_ref?:number}|null,
 validation:{evaluated_on?:string,status:string,indicators:Record<string,Indicator>,reasons:string[],thresholds:{nse_min:number,bias_max_pct:number,do_mae_max?:number}},
 consents:Consent[],low_do_share:{baseline:number,candidate:number},
 appraisal:{baseline:Money,candidate:Money,difference:{energy_pct:number,energy_kwh:number,cost_gbp:number,carbon_t:number}|null},
 recommendation:{status:string,reason:string,checks:{name:string,ok:boolean,detail:string}[],staged_setpoints:number[],statement:string}|null,
 sweep:{so_ref:number,energy_kwh_per_day:number,cost_gbp:number,mean_effluent_nh4:number,low_do_pct:number,consents_exceeded:string[]}[]|null,
 data_quality:{file:string,rows_read:number,days:number,issues:string[],notes:string[]},assumptions:string[],
 series:{effluent_nh4:Series,aeration_kwh_d:Series}}
type Money={energy_kwh:number,energy_kwh_per_day:number,cost_gbp:number,carbon_t:number,cost_gbp_range:number[],carbon_t_range:number[],calibrated:boolean,annualised:{energy_kwh:number,cost_gbp:number,carbon_t:number,note:string}}
const VERDICT:Record<string,[string,string]>={validated:['good','The model reproduces your recorded data.'],partly_validated:['warn','The model matches on the one indicator that could be checked.'],
 not_validated:['bad','The model does NOT reproduce your recorded data well enough. Treat everything below as research only.'],cannot_validate:['warn','There was nothing recorded to check the model against. Treat everything below as research only.']}
const REC:Record<string,string>={ready_for_operator_review:'good',research_only:'warn',rejected:'bad'}

function Lines({s,title,unit}:{s:Series,title:string,unit:string}){
 const el=useRef<HTMLDivElement>(null)
 useEffect(()=>{if(!el.current||!s.day.length)return;const c=echarts.init(el.current)
  c.setOption({animation:false,grid:{left:54,right:16,top:34,bottom:30},textStyle:{color:'#92aaa9'},tooltip:{trigger:'axis'},legend:{top:0,textStyle:{color:'#92aaa9'}},
   xAxis:{type:'category',data:s.day,axisLabel:{interval:Math.max(Math.floor(s.day.length/6),0)}},yAxis:{type:'value',scale:true,name:unit,splitLine:{lineStyle:{color:'#26363e'}}},
   series:[{name:'Model, today',type:'line',data:s.baseline,showSymbol:false,lineStyle:{color:'#92aaa9',width:2}},
    {name:'Model, candidate',type:'line',data:s.candidate,showSymbol:false,lineStyle:{color:'#51e1ca',width:2}},
    ...(s.observed?[{name:'Recorded',type:'scatter',data:s.observed,symbolSize:7,itemStyle:{color:'#e08a4b'}}]:[])]})
  const obs=new ResizeObserver(()=>c.resize());obs.observe(el.current);return()=>{obs.disconnect();c.dispose()}},[s])
 return <><h3>{title}</h3><div ref={el} className="plot" role="img" aria-label={title+', daily, model against recorded'}/></>
}

export default function ShadowMode(){
 const [r,setR]=useState<Report|null>(snapshot&&(snapshot as any).site?snapshot as unknown as Report:null),[source,setSource]=useState('Bundled demo report')
 useEffect(()=>{fetch('/api/site/report').then(x=>x.ok?x.json():Promise.reject()).then((d:Report)=>{setR(d);setSource('Latest report on this computer')}).catch(()=>{})},[])
 if(!r)return <section className="panel content"><small>SHADOW MODE</small><h2>Site shadow mode</h2><p>No report yet. Run <code>python -m aera.site demo --out results/site/demo</code> and reload.</p></section>
 const [vc,vt]=VERDICT[r.validation.status],ap=r.appraisal,d=ap.difference,rec=r.recommendation
 return <section className="panel content"><small>SHADOW MODE · ADVICE ONLY · {source.toUpperCase()}</small><h2>{r.site}</h2>
  <details className="how" open><summary><b>How to read this page</b></summary>
   <p>Shadow mode takes a works's own recorded data, replays it through a model of the plant, and asks two questions. First: <b>does the model reproduce what really happened?</b> If not, nothing else on this page can be trusted. Second: <b>what would change if the dissolved oxygen setpoint were different?</b> It never connects to a plant and never changes a setting: people make any change.</p>
   <p>To run it on your own data: <code>python -m aera.site init my_works</code>, put your historian export in the folder, edit <code>site.toml</code>, then <code>python -m aera.site check</code> and <code>python -m aera.site replay</code>. Full guide: docs/START_HERE.md.</p></details>
  <p className="muted">Window {r.window.start.slice(0,10)} to {r.window.end.slice(0,10)} ({r.window.days} days; the first {r.window.warmup_days_excluded} are model warm-up and not counted).</p>
  {r.synthetic&&<div className="banner warn"><b>SYNTHETIC DATA.</b> This report is a demonstration. The "recorded" data was generated by the model itself, so the fit is artificially good, and nothing here says anything about a real works.</div>}
  <div className={'banner '+vc}><b>Can the model be trusted on your data?</b> {vt}</div>
  {rec&&d&&<div className={'banner '+REC[rec.status]}><b>Recommendation: {rec.status.replace(/_/g,' ')}.</b> {rec.reason}<br/>DO setpoint {r.current_control.do_setpoint} to {r.candidate?.so_ref??r.current_control.do_setpoint} mg/l: aeration energy {d.energy_pct>0?'+':'−'}{Math.abs(d.energy_pct)}% ({d.energy_kwh<0?'−':'+'}{Math.abs(Math.round(d.energy_kwh)).toLocaleString()} kWh over the window, about {d.cost_gbp<0?'−':'+'}£{Math.abs(Math.round(d.cost_gbp)).toLocaleString()} and {d.carbon_t<0?'−':'+'}{Math.abs(d.carbon_t)} t CO₂e). {rec.staged_setpoints.length>0&&'Staged steps: '+rec.staged_setpoints.join(', ')+'.'}</div>}
  {r.calibration&&<><h3>Calibration</h3>{r.calibration.used?<p>The plant was fitted to your first {r.calibration.train_days} days, then checked on the {r.calibration.test_days} days it never saw. Nitrifier activity {r.calibration.params?.mu_a_scale}× the benchmark; oxygen transfer {r.calibration.params?.alpha_scale}× the benchmark. On the held-out days the effluent ammonium error fell from {r.calibration.held_out?.nh4_error_before} to {r.calibration.held_out?.nh4_error_after} (standardised), a {r.calibration.held_out?.improvement_pct}% improvement. The model check below is judged on those held-out days only.</p>:<p><b>Calibration was not used</b> ({r.calibration.status.replace(/_/g,' ')}); the benchmark plant was kept.</p>}<ul>{(r.calibration.notes??[]).map(t=><li key={t}>{t}</li>)}</ul></>}
  <h3>1. Does the model match the records?</h3>{r.validation.evaluated_on&&<p className="muted">Judged on {r.validation.evaluated_on}.</p>}
  <table><thead><tr><th>Indicator</th><th>Days</th><th>Nash-Sutcliffe</th><th>Bias</th><th>R²</th><th>Mean abs. error</th></tr></thead><tbody>{Object.entries(r.validation.indicators).map(([k,m])=><tr key={k}><td>{k.replace(/_/g,' ')}</td><td>{m.n}</td><td>{m.kind==='level'?'not used':m.nse}</td><td>{m.bias_pct==null?'n/a':(m.bias_pct+0).toFixed(1)+'%'}</td><td>{m.r2}</td><td>{m.kind==='level'?m.mae+' mg/l':''}</td></tr>)}</tbody></table>
  <p className="muted">Pass mark: Nash-Sutcliffe ≥ {r.validation.thresholds.nse_min} and bias within {r.validation.thresholds.bias_max_pct}% (1 is a perfect match; 0 is no better than the average). DO is held near its setpoint, so it is judged by average error ≤ {r.validation.thresholds.do_mae_max??0.3} mg/l. These pass marks are the tool author's choice, not a standard.</p>
  <ul>{r.validation.reasons.map(t=><li key={t}>{t}</li>)}</ul>
  <Lines s={r.series.effluent_nh4} title="Effluent ammonium, daily (mg N/l)" unit="mg N/l"/><Lines s={r.series.aeration_kwh_d} title="Aeration energy per day (kWh/d)" unit="kWh/d"/>
  <h3>2. Permit-style limits</h3>
  {r.consents.length?<table><thead><tr><th>Limit</th><th>Today's control</th><th>Candidate</th></tr></thead><tbody>{r.consents.map(c=><tr key={c.baseline.name}><td>{c.baseline.name}</td><td className={c.baseline.status==='within'?'ok':'bad'}>{c.baseline.status}: {c.baseline.detail}</td><td className={c.candidate.status==='within'?'ok':'bad'}>{c.candidate.status}: {c.candidate.detail}</td></tr>)}</tbody></table>:<p>No limits configured.</p>}
  <p>Time with DO below 0.5 mg/l (a nitrous oxide risk): today {(100*r.low_do_share.baseline).toFixed(1)}%, candidate {(100*r.low_do_share.candidate).toFixed(1)}%.</p>
  <h3>3. Energy, cost and carbon</h3>
  <table><thead><tr><th></th><th>Today's control</th><th>Candidate</th></tr></thead><tbody>{([['Energy over the window (kWh)','energy_kwh'],['Energy per day (kWh)','energy_kwh_per_day'],['Cost (£)','cost_gbp'],['Carbon (t CO₂e)','carbon_t']] as const).map(([l,k])=><tr key={k}><td>{l}</td><td>{ap.baseline[k].toLocaleString()}</td><td>{ap.candidate[k].toLocaleString()}</td></tr>)}</tbody></table>
  <p className="muted">Cost range (tariff uncertainty) £{ap.baseline.cost_gbp_range[0].toLocaleString()} to £{ap.baseline.cost_gbp_range[1].toLocaleString()}. {ap.baseline.calibrated?'Energy is scaled to your recorded blower energy.':'Energy is NOT calibrated to recorded blower power.'} Annualised today: {ap.baseline.annualised.energy_kwh.toLocaleString()} kWh, £{ap.baseline.annualised.cost_gbp.toLocaleString()}. {ap.baseline.annualised.note}</p>
  {r.sweep&&<><h3>4. What if the DO setpoint were different?</h3><table><thead><tr><th>Setpoint (mg/l)</th><th>Energy (kWh/d)</th><th>Cost over window (£)</th><th>Mean effluent NH₄</th><th>Below 0.5 mg/l</th><th>Limits exceeded</th></tr></thead><tbody>{r.sweep.map(t=><tr key={t.so_ref}><td>{t.so_ref}</td><td>{t.energy_kwh_per_day.toLocaleString()}</td><td>{t.cost_gbp.toLocaleString()}</td><td>{t.mean_effluent_nh4}</td><td>{t.low_do_pct}%</td><td>{t.consents_exceeded.join(', ')||'none'}</td></tr>)}</tbody></table></>}
  <h3>Data used</h3><p>{r.data_quality.file}: {r.data_quality.rows_read.toLocaleString()} rows over {r.data_quality.days} days. {r.data_quality.issues.length?r.data_quality.issues.length+' thing(s) to look at:':'No data problems found.'}</p><ul>{[...r.data_quality.issues,...r.data_quality.notes].map(t=><li key={t}>{t}</li>)}</ul>
  <h3>What this does not tell you</h3><ul>{r.assumptions.map(t=><li key={t}>{t}</li>)}</ul>
  {rec&&<p className="muted">{rec.statement}</p>}
 </section>
}
