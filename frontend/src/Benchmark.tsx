import {useState} from 'react'
import snapshot from './bsm1-report.json'

export default function Benchmark(){
 const [report,setReport]=useState(snapshot),[status,setStatus]=useState('Recorded reference run')
 async function rerun(){
  setStatus('Integrating…')
  try{const response=await fetch('/api/asm1/benchmark',{method:'POST'})
   if(!response.ok)throw Error('Verification request failed')
   const result=await response.json();setReport(result)
   setStatus('Computed · '+result.diagnostics.method+' · '+result.diagnostics.nfev+' evaluations · '+result.diagnostics.seconds.toFixed(2)+' s')
  }catch(e){setStatus(String(e))}
 }
 const rows=[
  ['Effluent ammonium','mg N/L',report.effluent[9],1.7333],
  ['Effluent oxidised nitrogen','mg N/L',report.effluent[8],10.4152],
  ['Effluent suspended solids','mg SS/L',report.layer_tss[0],12.4969],
  ['Return sludge suspended solids','mg SS/L',report.layer_tss[9],6393.9844],
 ] as const
 return <section className="panel content"><small>ASM1 · OPEN-LOOP VERIFICATION</small><h2>Whole-plant benchmark</h2><button className="run" disabled={status==='Integrating…'} onClick={rerun}>Run numerical verification</button><p role="status">{status}</p><p>Recorded 150-day constant-influent experiment. Five biological reactors discharge to a ten-layer settler. Internal recycle, return sludge and wasting close the process balances.</p>
 <table><thead><tr><th>Quantity</th><th>AERA</th><th>Published</th><th>Signed error</th><th>Relative error</th><th>Unit</th></tr></thead><tbody>{rows.map(([label,unit,value,expected])=><tr key={label}><td>{label}</td><td>{value.toFixed(4)}</td><td>{expected.toFixed(4)}</td><td>{(value-expected).toExponential(2)}</td><td>{(100*(value-expected)/expected).toExponential(2)}%</td></tr>)}</tbody></table>
 <h3>Ammonium across the treatment train</h3><table><thead><tr>{report.tanks.map((_,i)=><th key={i}>Tank {i+1}</th>)}</tr></thead><tbody><tr>{report.tanks.map((v,i)=><td key={i}>{v[9].toFixed(2)} mg N/L</td>)}</tr></tbody></table>
 <p>Reference: U. Jeppsson, Lund University, open-loop steady-state results (2009). This comparison tests implementation against a published simulation. Site-specific predictions require plant data.</p></section>
}
