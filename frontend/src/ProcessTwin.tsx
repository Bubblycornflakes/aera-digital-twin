import {useEffect,useRef,useState} from 'react'
import * as echarts from 'echarts'
import Scene from './Scene'

type Frame={minute:number;do:number[];nh4:number[];effluent_nh4:number;effluent_tss:number;energy_kwh:number[]}
type ProcessRun={records:Frame[];model:string;air_m3h:number[];power_kw:number[];command:number[];volume:number[];kla_day:number[];internal:number;ras:number;waste:number;train_flow:number;effluent_flow:number;pulse:boolean}

function Trends({run,tank,index}:{run:ProcessRun;tank:number;index:number}){
 const el=useRef<HTMLDivElement>(null),chart=useRef<echarts.ECharts|null>(null)
 useEffect(()=>{
  const c=echarts.init(el.current!);chart.current=c
  const traces=[['Reactor DO','#66dbc7',(f:Frame)=>f.do[tank]],['Reactor NH₄-N','#f3c074',(f:Frame)=>f.nh4[tank]],['Effluent NH₄-N','#ac95eb',(f:Frame)=>f.effluent_nh4]] as const
  c.setOption({animation:false,legend:{textStyle:{color:'#bacccd'}},tooltip:{trigger:'axis'},grid:{left:50,right:30,top:44,bottom:30},xAxis:{type:'value',max:24,name:'h'},yAxis:{type:'value',name:'mg/L',splitLine:{lineStyle:{color:'#293c41'}}},series:traces.map(([name,color,value])=>({name,type:'line',color,showSymbol:false,data:run.records.map(f=>[f.minute/60,value(f)])}))})
  const obs=new ResizeObserver(()=>c.resize());obs.observe(el.current!);return()=>{obs.disconnect();c.dispose()}
 },[tank,run])
 useEffect(()=>{chart.current?.setOption({series:[{markLine:{symbol:'none',data:[{xAxis:run.records[index].minute/60}]}}]})},[tank,run,index])
 return <div className="plot" ref={el}/>
}

export default function ProcessTwin(){
 const [run,R]=useState<ProcessRun>(),[busy,B]=useState(true),[error,E]=useState(''),[tank,T]=useState(4),[index,I]=useState(0),[play,P]=useState(false),[speed,V]=useState(100)
 const [command,C]=useState(.35),[pulse,U]=useState(true),[selected,S]=useState('Basin'),[view,W]=useState('Cutaway')
 const request=useRef<AbortController|null>(null)
 async function execute(){
  request.current?.abort();const abort=new AbortController();request.current=abort;B(true);E('');P(false)
  try{const response=await fetch('/api/asm1/playback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({command,pulse}),signal:abort.signal})
   if(!response.ok)throw Error('Process simulation failed ('+response.status+')')
   const result:ProcessRun=await response.json();if(!abort.signal.aborted){I(0);R(result)}
  }catch(e){if(!abort.signal.aborted)E(String(e))}finally{if(!abort.signal.aborted)B(false)}
 }
 useEffect(()=>{void execute();return()=>request.current?.abort()},[])
 useEffect(()=>{if(!play||!run)return;const id=setInterval(()=>I(i=>Math.min(i+1,run.records.length-1)),300000/speed);return()=>clearInterval(id)},[play,run,speed])
 useEffect(()=>{if(run&&index===run.records.length-1)P(false)},[index,run])
 const f=run?.records[index]
 return <><div className="panel pad"><label>Reactor 5 fixed airflow command (%) <input type="number" min="0" max="100" value={Number.isFinite(command)?Math.round(command*100):''} onChange={e=>C(e.target.valueAsNumber/100)}/></label><label className="check"><input type="checkbox" checked={pulse} onChange={e=>U(e.target.checked)}/> Increase raw influent ammonium by 50% from 08:00 to 12:00</label><button disabled={busy||!(command>=0&&command<=1)} className="run" onClick={execute}>{busy?'Integrating five reactors and settler…':'Run ASM1 experiment'}</button>{error&&<p role="alert">{error}</p>}</div>
 {run&&f&&<><div className="panelTitle"><label>Inspect reactor <select value={tank} onChange={e=>T(+e.target.value)}>{run.volume.map((v,i)=><option key={i} value={i}>R{i+1} · {v} m³</option>)}</select></label><small>{run.model} · R5 applied {Math.round(run.command[4]*100)}% · pulse {run.pulse?'on':'off'}</small></div>
 <div className="metrics">{[['DO',f.do[tank],'mg O₂/L'],['NH₄-N',f.nh4[tank],'mg N/L'],['Air intake',run.air_m3h[tank],'m³/h'],['Estimated power',run.power_kw[tank],'kW'],['Reactor energy',f.energy_kwh[tank],'kWh']].map(([name,v,unit])=><div key={name}><small>{name}</small><strong>{Number(v).toFixed(2)} <sub>{unit}</sub></strong></div>)}</div>
 <div className="work"><div className="middle"><section className="panel"><div className="panelTitle"><b>R{tank+1} · {tank<2?'Anoxic':'Aerated'} reactor</b><select aria-label="Process camera" value={view} onChange={e=>W(e.target.value)}>{['Cutaway','Isometric','Plan'].map(v=><option key={v}>{v}</option>)}</select></div><div className="viewport"><Scene s={{hour:f.minute/60,do:f.do[tank],nh4:f.nh4[tank],power_kw:run.power_kw[tank],energy_kwh:f.energy_kwh[tank],airflow:run.command[tank],flow_m3h:run.train_flow/24,inlet_n:0}} basinId={'R'+(tank+1)} playing={play} view={view} cameraKey={0} labels selected={selected} select={S}/><span className="sceneId">Illustrative reactor geometry</span></div></section>
 <div className="transport"><button onClick={()=>{if(index===288)I(0);P(!play)}}>{play?'Pause':'Play'}</button><button onClick={()=>{P(false);I(Math.min(288,index+1))}}>Step</button><b>{String(Math.floor(f.minute/60)).padStart(2,'0')}:{String(f.minute%60).padStart(2,'0')}</b><input aria-label="ASM1 playback time" type="range" min="0" max={run.records.length-1} value={index} onChange={e=>I(+e.target.value)}/><select aria-label="ASM1 playback speed" value={speed} onChange={e=>V(+e.target.value)}>{[1,24,100,600].map(x=><option value={x} key={x}>{x}×</option>)}</select></div>
 <section className="panel"><div className="panelTitle">Process trends · simulated 24 hours</div><Trends run={run} tank={tank} index={index}/></section></div>
 <div className="right"><section className="panel pad"><small>EQUIPMENT INSPECTOR</small><h2>{selected} · R{tank+1}</h2><p>{selected==='Blowers'?run.air_m3h[tank].toFixed(1)+' m³/h intake':selected==='DO probe'?f.do[tank].toFixed(3)+' mg O₂/L':selected==='NH₄ probe'?f.nh4[tank].toFixed(3)+' mg N/L':run.volume[tank]+' m³ working volume'}</p><p>Transfer coefficient {run.kla_day[tank].toFixed(1)} /day</p></section>
 <section className="panel pad"><small>SECONDARY SETTLER</small><p>Effluent NH₄-N <b>{f.effluent_nh4.toFixed(3)} mg N/L</b></p><p>Effluent solids {f.effluent_tss.toFixed(2)} mg/L</p><p>Discharge {run.effluent_flow} m³/day</p><hr/><p>Internal recycle {run.internal} m³/day</p><p>Return sludge {run.ras} m³/day</p><p>Waste sludge {run.waste} m³/day</p></section><p>Air delivery and electricity use illustrative blower assumptions. Process playback uses five-minute samples.</p></div></div></>}</>
}
