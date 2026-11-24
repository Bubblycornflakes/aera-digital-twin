import React,{useEffect,useMemo,useRef} from 'react'
import {Canvas,useFrame,useThree} from '@react-three/fiber'
import {OrbitControls,Html} from '@react-three/drei'
import * as T from 'three'
import {mergeGeometries} from 'three/examples/jsm/utils/BufferGeometryUtils.js'
import type {Sample} from './types'

type Props={basinId?:string;s:Sample;playing:boolean;view:string;cameraKey:number;labels:boolean;selected:string;select:(name:string)=>void}
const steel='#728995',yellow='#e2a742',blue='#26778b'
function plant(cut:boolean){
 const groups=new Map<string,T.BufferGeometry[]>()
 let seed=123;const rand=()=>((seed=seed*16807%2147483647)/2147483647)
 function add(g:T.BufferGeometry,c:string,x:number,y:number,z:number,q=new T.Quaternion()){
  g.applyMatrix4(new T.Matrix4().compose(new T.Vector3(x,y,z),q,new T.Vector3(1,1,1)))
  if(!groups.has(c)) groups.set(c,[])
  groups.get(c)!.push(g)
 }
 const box=(x:number,y:number,z:number,w:number,h:number,d:number,c:string)=>add(new T.BoxGeometry(w,h,d),c,x,y,z)
 const cyl=(x:number,y:number,z:number,r:number,h:number,c:string)=>add(new T.CylinderGeometry(r,r,h,32),c,x,y,z)
 function pipe(a:number[],b:number[],r:number,c=steel){
  const p=new T.Vector3(...a),d=new T.Vector3(...b).sub(p),m=p.clone().addScaledVector(d,.5)
  add(new T.CylinderGeometry(r,r,d.length(),12),c,m.x,m.y,m.z,new T.Quaternion().setFromUnitVectors(new T.Vector3(0,1,0),d.normalize()))
 }
 function rail(x:number,z:number,X:number,Z:number,y:number){
  const n=Math.ceil(Math.hypot(X-x,Z-z)/2)
  for(let i=0;i<=n;i++){const a=x+(X-x)*i/n,b=z+(Z-z)*i/n;pipe([a,y,b],[a,y+1.05,b],.044,yellow)}
  for(const h of [.48,1.05])pipe([x,y+h,z],[X,y+h,Z],.05,yellow)
 }
 box(0,-.48,0,290,.7,230,'#374246')
 box(0,-.07,0,34,.25,23,'#60696a')
 box(0,.12,0,24,.35,12,'#495b59')
 for(const z of [-6,6]){
  if(z<0||!cut)box(0,2.1,z,24.5,4.2,.47,'concrete')
  box(0,4.23,z,25,.23,1.1,'#65716f');rail(-12,z+.45,12,z+.45,4.35)
  for(let x=-12;x<12;x+=.38)box(x,4.36,z,.035,.035,.91,'#929992')
 }
 for(const x of [-12,12]){
  if(x<0||!cut)box(x,2.1,0,.48,4.2,12,'concrete')
  box(x,4.23,0,1,.23,12,'#63716f');rail(x, -6,x,6,4.35)
 }
 pipe([-11,.65,-4.6],[11,.65,-4.6],.24)
 for(let x=-9;x<=9;x+=3){pipe([x,.62,-4.6],[x,.62,4.4],.12);for(let z=-3;z<=3;z+=2)cyl(x,.76,z,.36,.13,'#222e33')}
 for(const x of [-9,-4]){
  box(x,.42,9,3.9,.55,2.5,'concrete');pipe([x-1.45,1.42,9],[x+.55,1.42,9],.63,blue)
  for(let i=0;i<15;i++)pipe([x-1.45+i*.12,1.42,9],[x-1.40+i*.12,1.42,9],.71,blue)
  pipe([x+.55,1.52,9],[x+1.36,1.52,9],.92,'#3a6775')
  pipe([x+1,1.6,9],[x+1,3.25,9],.27);pipe([x+1,3.25,9],[x+1,3.25,6.2],.27)
  for(const z of [7.1,8.4])pipe([x+1,3.25,z],[x+1,3.25,z+.1],.38)
 }
 for(const x of [-7,7]){pipe([x,4.7,-6],[x,4.7,-3],.07);pipe([x,4.7,-3],[x,3.1,-3],.09);box(x,4.9,-6,.52,.65,.3,'#acb4ac')}
 for(const x of [-30,-11,10,29]){
  cyl(x,2,-26,5.9,4.1,'concrete');add(new T.SphereGeometry(5.82,36,16,0,Math.PI*2,0,Math.PI/2), '#849298',x,4,-26)
  for(let k=0;k<32;k++){const a=k*Math.PI/16;pipe([x+5.92*Math.cos(a),.1,-26+5.92*Math.sin(a)],[x+5.92*Math.cos(a),4,-26+5.92*Math.sin(a)],.033)}
  cyl(x,10,-26,.18,.7,steel)
 }
 for(const x of [-24,25]){cyl(x,1,-4,6.7,2,'concrete');cyl(x,2.06,-4,6.25,.1,'#285452');box(x,2.65,-4,13,.16,.65,steel);rail(x-6,-4,x+6,-4,2.75)}
 for(const x of [-35,21,35]){box(x,2.3,-15,10,4.6,5,'#566369');box(x,4.68,-15,10.8,.25,5.7,'#788286');for(let k=-4;k<5;k++)box(x+k,3.2,-12.46,.62,.85,.06,'lamp')}
 for(let k=0;k<120;k++){const x=rand()*180-90,z=-42-rand()*35,h=2+rand()*7;add(new T.DodecahedronGeometry(h*.48,1),'#263e3b',x,h*.28,z)}
 for(const x of [-12,12])for(const z of [-6,6]){pipe([x,4.4,z],[x,8,z],.065);box(x,8,z,.68,.23,.45,steel);box(x,7.85,z,.61,.08,.4,'lamp')}
 // Shared utility headers, paired pipe shoes and bolted collars.
 for(const z of [7.1,7.85]){
  pipe([-11,1.05,z],[10,1.05,z],.16)
  for(let x=-10;x<11;x+=2.6){pipe([x,1.05,z],[x+.10,1.05,z],.23);box(x,.47,z,.29,.85,.34,'#495c60')}
 }
 for(let i=0;i<11;i++){const y=.35+i*.36,z=-6.8-i*.4;box(10,y,z,1.2,.11,.48,steel)}
 rail(9.4,-11,9.4,-6.8,4.15)
 for(const x of [-6,6]){box(x,4.9,-6.15,.8,1.2,.45,'#6a7877');box(x,5.1,-5.9,.45,.27,.02,'#103b42')}
 const canvas=document.createElement('canvas');canvas.width=canvas.height=256;const ctx=canvas.getContext('2d')!,im=ctx.createImageData(256,256)
 for(let i=0;i<im.data.length;i+=4){const x=i/4%256,y=Math.floor(i/1024),v=149+rand()*30+6*Math.sin(x*.18)+6*Math.cos(y*.09)-(x%64<2||y%128<2?23:0);im.data.set([v,v*.98,v*.94,255],i)}
 ctx.putImageData(im,0,0);const tex=new T.CanvasTexture(canvas);tex.wrapS=tex.wrapT=T.RepeatWrapping;tex.repeat.set(4,1);tex.colorSpace=T.SRGBColorSpace
 const scene=new T.Group()
 for(const [c,parts] of groups){const m=new T.MeshStandardMaterial({color:c==='concrete'?'white':c==='lamp'?'#ffdeb0':c,map:c==='concrete'?tex:null,roughness:c==='concrete'?.93:.52,metalness:c===steel?.7:.15,emissive:c==='lamp'?'#ffab52':'black',emissiveIntensity:2})
 const mesh=new T.Mesh(mergeGeometries(parts)!,m);mesh.castShadow=true;mesh.receiveShadow=true;scene.add(mesh);parts.forEach(g=>g.dispose())}
 return scene
}
function Rig({view,cameraKey}:Pick<Props,'view'|'cameraKey'>){
 const {camera,size}=useThree();const ref=useRef<React.ComponentRef<typeof OrbitControls>>(null)
 useEffect(()=>{const top=view==='Plan';camera.position.set(...(top?[0,43,1]:(size.width/size.height>1.8?[15,9,18]:[19,12,23])) as [number,number,number]);ref.current?.target.set(0,2.8,1);ref.current?.update()},[view,cameraKey,camera,size.width,size.height])
 return <OrbitControls ref={ref} makeDefault enableDamping maxPolarAngle={Math.PI*.48} minDistance={9} maxDistance={80}/>
}
function Basin(p:Props){
 const cut=p.view==='Cutaway',site=useMemo(()=>plant(cut),[cut])
 useEffect(()=>()=>{site.traverse(o=>{if(o instanceof T.Mesh){o.geometry.dispose();o.material.map?.dispose();o.material.dispose()}})},[site])
 const bubbles=useRef<T.Points>(null),water=useRef<T.ShaderMaterial>(null)
 const positions=useMemo(()=>new Float32Array(2400*3),[])
 const rotor=useRef<T.Group>(null);const phase=useRef(0)
 useFrame((_,dt)=>{if(p.playing)phase.current+=Math.min(dt,.1);const t=phase.current,u=p.s.airflow
 if(rotor.current&&p.playing)rotor.current.rotation.x+=dt*u*24
 if(water.current){water.current.uniforms.t.value=t;water.current.uniforms.air.value=u;water.current.uniforms.opacity.value=cut?.49:.93}
 const b=bubbles.current;if(!b)return;const count=Math.floor(u*2400);b.geometry.setDrawRange(0,count)
 for(let i=0;i<count;i++){const h=(i*.618034+t*(.28+.09*Math.sin(i)))%1;positions[i*3]=-9+(i%7)*3+Math.sin(i*12.3+t)*(.09+.52*h);positions[i*3+2]=-3+(Math.floor(i/7)%4)*2+Math.cos(i*19.2+t)*(.1+.58*h);positions[i*3+1]=.84+3.12*h}
 b.geometry.attributes.position.needsUpdate=true})
 // Stable attribute identity avoids replacing the animated particle buffer on each playback tick.
 const attribute=useMemo(()=>new T.BufferAttribute(positions,3).setUsage(T.DynamicDrawUsage),[positions])
 const uniforms=useMemo(()=>({t:{value:0},air:{value:.4},opacity:{value:.9}}),[])
 return <><primitive object={site}/>
 <group position={[-10.48,1.42,9]} ref={rotor}>{Array.from({length:9},(_,i)=><mesh key={i} rotation={[i*Math.PI/9,0,0]}><boxGeometry args={[.08,1.16,.055]}/><meshStandardMaterial color="#a8bab9" metalness={.7} roughness={.35}/></mesh>)}</group>
 {[-9,-3,3,9].map(x=><pointLight key={x} position={[x,3,4]} intensity={32} distance={9} color="#50deed"/>)}<mesh position={[0,3.83,0]} rotation={[-Math.PI/2,0,0]}><planeGeometry args={[23.5,11.5,160,84]}/><shaderMaterial ref={water} transparent depthWrite={false} uniforms={uniforms} vertexShader={`varying vec3 pos;uniform float t,air;void main(){vec3 p=position;p.z+=.045*sin(p.x*2.+t*2.)*cos(p.y*3.-t)+air*.04*sin(p.y*7.+t);pos=p;gl_Position=projectionMatrix*modelViewMatrix*vec4(p,1.);}`} fragmentShader={`varying vec3 pos;uniform float t,air,opacity;void main(){vec2 p=pos.xy;float n=sin(p.x*4.+sin(p.y*6.+t)+t)*cos(p.y*5.-t+sin(p.x*3.));float w=sin(p.x*11.+n*5.+t*2.)*cos(p.y*10.+t+n);float r=length(mod(p+vec2(10.5,4.),vec2(3.,2.))-vec2(1.5,1.));float foam=air*exp(-r*r*3.)*smoothstep(.15,.9,w);vec3 c=mix(vec3(.025,.17,.20),vec3(.14,.39,.40),n*.5+.5);c+=vec3(.37,.5,.49)*pow(max(w,0.),7.)+foam*1.15;gl_FragColor=vec4(c,opacity);}`}/></mesh>
 {cut&&<group><mesh position={[0,2.02,5.85]}><planeGeometry args={[23.6,3.63]}/><meshPhysicalMaterial color="#2197a1" transparent opacity={.22} metalness={.38} roughness={.19} depthWrite={false} side={T.DoubleSide}/></mesh><mesh position={[11.82,2.02,0]} rotation={[0,Math.PI/2,0]}><planeGeometry args={[11.7,3.63]}/><meshPhysicalMaterial color="#278791" transparent opacity={.28} depthWrite={false} side={T.DoubleSide}/></mesh></group>}
 <points renderOrder={2} ref={bubbles} frustumCulled={false}><bufferGeometry><primitive attach="attributes-position" object={attribute}/></bufferGeometry><pointsMaterial toneMapped={false} color="#b1fffa" size={.10} transparent opacity={.87} depthWrite={false}/></points>
 {(['Basin','Blowers','DO probe','NH₄ probe'] as const).map((name,i)=><group key={name} position={([[-10,7,-5],[-6,3,9],[8,6.5,-3],[-4,5.3,1]] as const)[i]}><mesh onClick={e=>{e.stopPropagation();p.select(name)}}><sphereGeometry args={[.2,12,10]}/><meshBasicMaterial color={p.selected===name?'#ffcb78':'#58dfd0'}/></mesh>{p.labels&&<Html center distanceFactor={29} zIndexRange={[5,1]}><button className={'tag '+(p.selected===name?'sel':'')} onClick={()=>p.select(name)}>{name}<b>{[ p.basinId??'S1',Math.round(p.s.airflow*100)+'%',p.s.do.toFixed(2)+' mg/L',p.s.nh4.toFixed(2)+' mg/L'][i]}</b></button></Html>}</group>)}
 <Rig view={p.view} cameraKey={p.cameraKey}/></>
}
export default function Scene(p:Props){return <Canvas shadows dpr={[1,1.5]} camera={{position:[20,13,22],fov:45}} gl={{antialias:true}}><color attach="background" args={['#334955']}/><fog attach="fog" args={['#495664',44,120]}/><hemisphereLight args={['#b9d8fa','#3f5558',1.7]}/><directionalLight position={[-17,22,-5]} intensity={3.3} color="#ffd099" castShadow shadow-mapSize={[2048,2048]} shadow-camera-left={-32} shadow-camera-right={32} shadow-camera-top={27} shadow-camera-bottom={-27} shadow-bias={-.0004}/><mesh scale={170}><sphereGeometry args={[1,40,20]}/><shaderMaterial side={T.BackSide} depthWrite={false} vertexShader={`varying vec3 dir;void main(){dir=position;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}`} fragmentShader={`varying vec3 dir;void main(){float h=max(normalize(dir).y,0.);vec3 c=mix(vec3(.64,.48,.39),vec3(.12,.22,.34),smoothstep(0.,.37,h));gl_FragColor=vec4(c,1.);}`}/></mesh><Basin {...p}/></Canvas>}
