import {useEffect,useRef} from 'react'
import * as echarts from 'echarts'
import type {Run,Sample} from './types'
export function Plot({run,base,index,metric}:{run:Run;base:Run;index:number;metric:keyof Sample}){
 const el=useRef<HTMLDivElement>(null),chart=useRef<echarts.ECharts|null>(null)
 useEffect(()=>{if(!el.current)return;const c=echarts.init(el.current);chart.current=c
 const data=(r:Run)=>r.records.map(s=>[s.hour,s[metric]])
 const areas=[...(run.settings.storm?[[{name:'Storm',xAxis:12},{xAxis:18}]]:[]),...(run.settings.returns?[[{name:'Return',xAxis:9},{xAxis:15}]]:[])]
 c.setOption({animation:false,grid:{left:42,right:20,top:24,bottom:28},tooltip:{trigger:'axis',valueFormatter:(v:number)=>Number(v).toFixed(2)},textStyle:{color:'#92aaa9'},xAxis:{type:'value',max:24,interval:4,axisLabel:{formatter:'{value}h'},splitLine:{show:false}},yAxis:{type:'value',splitLine:{lineStyle:{color:'#26363e'}}},dataZoom:[{type:'inside'}],series:[{name:'Baseline',type:'line',data:data(base),showSymbol:false,lineStyle:{type:'dashed',color:'#c6ad82',width:1.5}},{name:'Trial',type:'line',data:data(run),showSymbol:false,color:'#51e1ca',lineStyle:{width:2},markArea:{silent:true,itemStyle:{color:'rgba(197,160,91,.11)'},label:{color:'#bba97c',fontSize:9},data:areas}}]})
 const obs=new ResizeObserver(()=>c.resize());obs.observe(el.current);return()=>{obs.disconnect();c.dispose()}},[run,base,metric])
 useEffect(()=>{chart.current?.setOption({series:[{},{markLine:{symbol:'none',silent:true,label:{show:false},lineStyle:{color:'#afc6cc'},data:[{xAxis:index/60}]}}]})},[index,run,metric])
 return <div ref={el} className="plot"/>
}
