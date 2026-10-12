import React from "react";
import {AbsoluteFill,Composition,Sequence,useCurrentFrame} from "remotion";
import {TextReveal} from "@/components/snap-cn/text-reveal";
import stories from "../../public/demo-stories.json";
type Scene={eyebrow:string;headline:string;body:string;receipt:string};
const fps=30;
function SceneStory({scenes}:{scenes:Scene[]}){
 const frame=useCurrentFrame();return <AbsoluteFill style={{background:"linear-gradient(135deg,#111e40,#2d4273 60%,#1d315a)",fontFamily:"sans-serif",color:"#fff"}}>
 {scenes.map((scene,i)=><Sequence key={i} from={i*120} durationInFrames={120}><AbsoluteFill style={{padding:90,justifyContent:"center",alignItems:"flex-start"}}>
 <div style={{fontSize:21,color:"#b2c8ff",fontWeight:700,letterSpacing:5,marginBottom:32}}>{scene.eyebrow}</div>
 <div style={{width:930,height:180}}><TextReveal text={scene.headline} mode="dark"/></div>
 <div style={{marginTop:24,fontSize:31,color:"#cbd9f2",maxWidth:930,lineHeight:1.55}}>{scene.body}</div>
 <div style={{marginTop:36,fontSize:17,color:"#8fe0c5"}}>{scene.receipt}</div></AbsoluteFill></Sequence>)}
 </AbsoluteFill>;
}
export const RemotionRoot=()=> <>{stories.map(s=><Composition key={s.id} id={s.id} component={SceneStory} durationInFrames={s.scenes.length*120} fps={fps} width={1920} height={1080} defaultProps={{scenes:s.scenes}} />)}</>;
