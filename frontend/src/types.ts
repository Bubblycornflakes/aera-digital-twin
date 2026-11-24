export type Sample={hour:number;do:number;nh4:number;airflow:number;power_kw:number;energy_kwh:number;flow_m3h:number;inlet_n:number}
export type Config={kp:number;ki:number;kd:number;target:number;storm:boolean;returns:boolean}
export type Run={records:Sample[];settings:Config;version:string}
export const defaults:Config={kp:.12,ki:.8,kd:0,target:2,storm:false,returns:false}
export async function requestRun(config:Config):Promise<Run>{const r=await fetch('/api/simulation',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(config)});if(!r.ok)throw Error('Simulation request failed ('+r.status+')');return r.json()}
