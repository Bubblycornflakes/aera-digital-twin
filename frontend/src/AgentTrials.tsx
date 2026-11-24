import {useEffect,useRef,useState} from 'react'
import * as echarts from 'echarts'
import snapshot from './aerobench-results.json'

type Failure={scenario:string,rule:string,share:number,reference:number,excess:number}
type Scenario={aeration_energy_kwh_d:number,reference_energy_kwh_d:number,feasible:boolean,failures:{rule:string}[]}
type Params={so_ref:number,k_do:number,ti_do:number,kla_max:number}
type Run={tuner:string,plant:string,seed:number,trials:number,answer:Params,feasible:boolean,aeration_energy_kwh_d:number,reference_energy_kwh_d:number,saving_pct:number,failures:Failure[],scenarios:Record<string,Scenario>,history:{params:Params,energy:number,feasible:boolean}[]}
type Row={tuner:string,runs:number,feasible_rate:number,feasible_ci:[number,number],mean_saving_feasible_pct:number|null,common_failures:[string,number][]}
type Data={leaderboard:Row[],runs:Run[]}
const DEFAULT:Params={so_ref:2,k_do:25,ti_do:.002,kla_max:360}
const label=(r:Run)=>`${r.tuner} · ${r.plant.replace('_',' ')} · seed ${r.seed}`

function History({run}:{run:Run}){
 const el=useRef<HTMLDivElement>(null)
 useEffect(()=>{if(!el.current)return;const c=echarts.init(el.current)
  const point=(h:Run['history'][number],i:number)=>({value:[i+1,h.energy],itemStyle:{color:h.feasible?'#51e1ca':'#d9776b'}})
  c.setOption({animation:false,grid:{left:52,right:16,top:16,bottom:32},textStyle:{color:'#92aaa9'},tooltip:{trigger:'item',valueFormatter:(v:number)=>Number(v).toFixed(0)+' kWh/d'},
   xAxis:{type:'value',name:'Trial',nameLocation:'middle',nameGap:22,min:1,max:Math.max(run.history.length,2),splitLine:{show:false}},
   yAxis:{type:'value',scale:true,name:'Aeration kWh/d',splitLine:{lineStyle:{color:'#26363e'}}},
   series:[{type:'scatter',symbolSize:9,data:run.history.map(point),
    markLine:{silent:true,symbol:'none',label:{formatter:'BSM1 default',position:'insideEndTop',color:'#bba97c',fontSize:10},lineStyle:{type:'dashed',color:'#c6ad82'},data:[{yAxis:run.reference_energy_kwh_d}]}}]})
  const obs=new ResizeObserver(()=>c.resize());obs.observe(el.current);return()=>{obs.disconnect();c.dispose()}},[run])
 return <div ref={el} className="plot" role="img" aria-label="Trial history: aeration energy per trial, green feasible, red infeasible"/>
}

export default function AgentTrials(){
 const [data,setData]=useState<Data>(snapshot as unknown as Data),[source,setSource]=useState('Bundled snapshot'),[pick,setPick]=useState(0)
 useEffect(()=>{fetch('/api/aerobench/results').then(r=>r.ok?r.json():Promise.reject()).then((d:Data)=>{if(d.runs.length){setData(d);setSource('Live results')}}).catch(()=>{})},[])
 const runs=data.runs,run=runs[Math.min(pick,runs.length-1)]
 if(!runs.length)return <section className="panel content"><small>AEROBENCH · BSM1</small><h2>Agent trials</h2><p>No results yet. Run <code>python -m aera.run_benchmark</code>, then reload.</p></section>
 return <section className="panel content"><small>AEROBENCH · BSM1 DO CONTROLLER TUNING · {source.toUpperCase()}</small><h2>Agent trials</h2>
  <p>Each tuner gets a fixed trial budget on dry weather and is then scored on unseen scenarios and plants. A run is feasible only if, in every held-out scenario, no effluent limit is exceeded for longer than under the BSM1 default controller and DO stays above 0.5 g/m³ for at least 99% of the time. Energy is compared only after feasibility.</p>
  <h3>Leaderboard</h3>
  <table><thead><tr><th>Tuner</th><th>Runs</th><th>Feasible (95% interval)</th><th>Saving vs default, feasible runs</th><th>Common failures</th></tr></thead><tbody>{data.leaderboard.map(r=><tr key={r.tuner}><td>{r.tuner}</td><td>{r.runs}</td><td>{Math.round(100*r.feasible_rate)}% <small>({Math.round(100*r.feasible_ci[0])} to {Math.round(100*r.feasible_ci[1])}%)</small></td><td>{r.mean_saving_feasible_pct==null?'n/a':r.mean_saving_feasible_pct+'%'}</td><td>{r.common_failures.map(([k,v])=>`${k} (${v})`).join(', ')||'none'}</td></tr>)}</tbody></table>
  <h3>Run detail</h3>
  <label>Run <select aria-label="Select run" value={pick} onChange={e=>setPick(+e.target.value)}>{runs.map((r,i)=><option key={i} value={i}>{label(r)}</option>)}</select></label>
  <p><b>{run.feasible?'Feasible':'Infeasible'}</b> · {run.trials} trials used · held-out aeration {run.aeration_energy_kwh_d.toFixed(0)} kWh/d against {run.reference_energy_kwh_d.toFixed(0)} for the default ({run.saving_pct>0?'−':'+'}{Math.abs(run.saving_pct).toFixed(1)}%)</p>
  <table><thead><tr><th>Parameter</th><th>BSM1 default</th><th>Submitted</th></tr></thead><tbody>{(Object.keys(DEFAULT) as (keyof Params)[]).map(k=><tr key={k}><td>{k}</td><td>{DEFAULT[k]}</td><td>{run.answer[k].toPrecision(3)}</td></tr>)}</tbody></table>
  <h3>Held-out scenarios</h3>
  <table><thead><tr><th>Scenario</th><th>Aeration kWh/d</th><th>Default kWh/d</th><th>Result</th><th>Limits exceeded more than default</th></tr></thead><tbody>{Object.entries(run.scenarios).map(([n,s])=><tr key={n}><td>{n.replace(/_/g,' ')}</td><td>{s.aeration_energy_kwh_d.toFixed(0)}</td><td>{s.reference_energy_kwh_d.toFixed(0)}</td><td className={s.feasible?'ok':'bad'}>{s.feasible?'pass':'fail'}</td><td>{s.failures.map(f=>f.rule).join(', ')||'none'}</td></tr>)}</tbody></table>
  <h3>Trial history</h3><History run={run}/>
  <p>Green trials passed the training scenario, red failed it. Training feasibility does not guarantee held-out feasibility, which is the point of the benchmark. The simulator is BSM1 at fixed temperature, not a calibrated plant.</p></section>
}
