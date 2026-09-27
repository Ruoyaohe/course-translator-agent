"use client";

import { useEffect, useRef, useState } from "react";
import { markUploaded, pendingParts, putPart, sha256, StoredPart } from "../src/storage";
import { CaptureController, startPcmCapture } from "../src/audio";
import { Button, Input, Progress, Select, TextArea, Window } from "../src/srcl/Srcl";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
type Segment = { id:string; start_ms:number; end_ms:number; source:string; translation:string };
type Schedule = { id:string; kind:string; title:string; datetime:string|null; status:string };
type Draft = { summary:string; key_points:string[]; schedule:Schedule[]; mindmap:unknown[]; pending_confirmation:string[] };
type Session = { id:string; course:string; title:string; status:string; transcript:Segment[]; parts:number[]; draft?:Draft; draft_source?:string; published_path?:string; error?:string };
type OrganizeEstimate = { model:string; currency:"CNY"; estimated_input_tokens:number; estimated_output_tokens:number; estimated_total_tokens:number; estimated_input_cost:number; estimated_output_cost:number; estimated_total_cost:number; estimated_duration_seconds:number; input_rate_per_million:number; output_rate_per_million:number; pricing_tier:string; pricing_region:string; is_estimate:boolean; cache_assumed:boolean };
type AudioInput = { deviceId:string; label:string };

async function api(path:string, init?:RequestInit) {
  const response = await fetch(`${API}${path}`, {...init, credentials:"include"});
  if (!response.ok) throw new Error((await response.json()).detail || response.statusText);
  return response.json();
}

export default function Home() {
  const [course,setCourse]=useState("NTU Visual Storytelling"); const [title,setTitle]=useState("课堂记录");
  const [hotwords,setHotwords]=useState("mise-en-scène, production design, deadline");
  const [session,setSession]=useState<Session|null>(null); const [error,setError]=useState("");
  const [elapsed,setElapsed]=useState(0); const [level,setLevel]=useState(0); const [uploading,setUploading]=useState(false);
  const [online,setOnline]=useState(true);
  const [transport,setTransport]=useState<"idle"|"connecting"|"live"|"retrying">("idle");
  const [providerName,setProviderName]=useState("unknown");
  const [audioInputs,setAudioInputs]=useState<AudioInput[]>([]); const [selectedAudioInput,setSelectedAudioInput]=useState("");
  const [activeAudioLabel,setActiveAudioLabel]=useState("系统默认麦克风"); const [deviceLoading,setDeviceLoading]=useState(false);
  const [estimate,setEstimate]=useState<OrganizeEstimate|null>(null); const [estimateOpen,setEstimateOpen]=useState(false);
  const [estimateLoading,setEstimateLoading]=useState(false); const [organizing,setOrganizing]=useState(false); const [estimateError,setEstimateError]=useState("");
  const [organizeRemaining,setOrganizeRemaining]=useState<number|null>(null); const organizeDeadline=useRef(0);
  const [user,setUser]=useState<{login:string}|null>(null); const [authReady,setAuthReady]=useState(false);
  const capture=useRef<CaptureController|null>(null); const stream=useRef<MediaStream|null>(null); const seq=useRef(0);
  const socket=useRef<WebSocket|null>(null); const startAt=useRef(0); const speaking=useRef(false);
  const flushing=useRef(false);

  useEffect(()=>{if(process.env.NODE_ENV==="development"){navigator.serviceWorker?.getRegistrations().then(items=>items.forEach(item=>item.unregister()));caches?.keys().then(keys=>keys.filter(key=>key.startsWith("ntu-agent-")).forEach(key=>caches.delete(key)))}else{navigator.serviceWorker?.register("/sw.js").catch(()=>{})}api("/health").then(x=>setProviderName(x.provider)).catch(()=>{});api("/auth/me").then(x=>setUser(x.user)).catch(()=>setUser(null)).finally(()=>setAuthReady(true));const sync=()=>setOnline(navigator.onLine);const devices=()=>refreshAudioInputs(false).catch(()=>{});sync();devices();addEventListener("online",sync);addEventListener("offline",sync);navigator.mediaDevices?.addEventListener("devicechange",devices);return()=>{removeEventListener("online",sync);removeEventListener("offline",sync);navigator.mediaDevices?.removeEventListener("devicechange",devices);capture.current?.stop().catch(()=>{});stream.current?.getTracks().forEach(track=>track.stop())}},[]);
  useEffect(()=>{if(online&&session)flushAll(session.id).catch(()=>{})},[online]);
  useEffect(()=>{if(!session||session.status!=="recording")return;const id=setInterval(()=>setElapsed(Date.now()-startAt.current),500);return()=>clearInterval(id)},[session?.status]);
  useEffect(()=>{if(!session||session.status!=="recording")return;const id=setInterval(()=>flushAll(session.id).catch(()=>{}),3000);return()=>clearInterval(id)},[session?.id,session?.status]);
  useEffect(()=>{if(!session||!["uploading","transcribing","organizing"].includes(session.status))return;const id=setInterval(async()=>{const next=await api(`/api/sessions/${session.id}`);setSession(next)},900);return()=>clearInterval(id)},[session?.id,session?.status]);
  useEffect(()=>{if(session?.status!=="organizing")return;if(!organizeDeadline.current)organizeDeadline.current=Date.now()+30_000;const tick=()=>setOrganizeRemaining(Math.max(0,Math.ceil((organizeDeadline.current-Date.now())/1000)));tick();const id=setInterval(tick,250);return()=>clearInterval(id)},[session?.status]);
  useEffect(()=>{if(session?.status==="draft_ready"||session?.status==="failed"){setOrganizeRemaining(null);organizeDeadline.current=0}},[session?.status]);

  async function flush(part:StoredPart) {
    if(!navigator.onLine)return;
    const digest=await sha256(part.blob); const form=new FormData(); form.append("audio",part.blob,"part.wav");
    const result=await api(`/api/sessions/${part.sessionId}/audio-parts?sequence=${part.sequence}&sha256=${digest}`,{method:"POST",body:form});
    await markUploaded(part);
    setSession(current=>current&&current.id===part.sessionId?{...current,parts:result.received,
      transcript:result.caption&&!current.transcript.some(x=>x.id===result.caption.id)?[...current.transcript,result.caption].sort((a,b)=>a.start_ms-b.start_ms):current.transcript}:current);
  }
  async function flushAll(id:string) { if(flushing.current)return;flushing.current=true;setUploading(true);try{for(const p of await pendingParts(id))await flush(p);setTransport(socket.current?.readyState===1?"live":"retrying")}finally{flushing.current=false;setUploading(false)} }

  async function refreshAudioInputs(requestPermission=true) {
    setDeviceLoading(true); setError("");
    try {
      if(requestPermission){const probe=await navigator.mediaDevices.getUserMedia({audio:true});probe.getTracks().forEach(track=>track.stop())}
      const devices=(await navigator.mediaDevices.enumerateDevices()).filter(device=>device.kind==="audioinput"&&device.deviceId!=="default"&&!/(iphone|ipad|手机)/i.test(device.label));
      const inputs=devices.map((device,index)=>({deviceId:device.deviceId,label:device.label||`音频输入 ${index+1}`}));
      setAudioInputs(inputs);setSelectedAudioInput(current=>current&&inputs.some(input=>input.deviceId===current)?current:"");
    } finally { setDeviceLoading(false) }
  }

  async function attachAudioInput(sessionId:string,deviceId:string) {
    await capture.current?.stop(); capture.current=null; stream.current?.getTracks().forEach(track=>track.stop()); stream.current=null;
    const media=await navigator.mediaDevices.getUserMedia({audio:{deviceId:deviceId?{exact:deviceId}:undefined,echoCancellation:true,noiseSuppression:true,channelCount:1}});stream.current=media;
    const track=media.getAudioTracks()[0];setActiveAudioLabel(track?.label||"系统默认麦克风");
    capture.current=await startPcmCapture(media,async blob=>{if(!blob.size||speaking.current)return;const p={key:`${sessionId}:${seq.current}`,sessionId,sequence:seq.current++,blob,uploaded:false};await putPart(p);flushAll(sessionId).catch(()=>{})},setLevel);
    await refreshAudioInputs(false);
  }

  async function chooseAudioInput(deviceId:string) {
    setSelectedAudioInput(deviceId);if(session?.status!=="recording")return;
    try{await attachAudioInput(session.id,deviceId)}catch(e){setError(`切换收声设备失败：${e instanceof Error?e.message:String(e)}`)}
  }

  async function start() {
    setError("");
    try {
      const created:Session=await api("/api/sessions",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({course,title,source_language:"en",target_language:"zh-CN",timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,hotwords:hotwords.split(",").map(x=>x.trim()).filter(Boolean),recording_consent:true})});
      setTransport("connecting");const wsBase=API.replace(/^http/,"ws"); const ws=new WebSocket(`${wsBase}/api/sessions/${created.id}/live`); socket.current=ws;
      ws.onopen=()=>setTransport("live");ws.onclose=()=>setTransport("retrying");ws.onerror=()=>setTransport("retrying");
      ws.onmessage=e=>{const msg=JSON.parse(e.data);if(msg.type==="caption")setSession(s=>s?{...s,transcript:[...s.transcript,msg.segment]}:s)};
      seq.current=0;await attachAudioInput(created.id,selectedAudioInput);
      try{await (navigator as Navigator & {wakeLock?:{request:(x:string)=>Promise<unknown>}}).wakeLock?.request("screen")}catch{}
      startAt.current=Date.now();setElapsed(0);setSession(created);
    } catch(e){setError(e instanceof Error?e.message:String(e))}
  }

  async function stop() {
    if(!session)return;await capture.current?.stop();capture.current=null;stream.current?.getTracks().forEach(t=>t.stop());stream.current=null;socket.current?.close();
    await new Promise(r=>setTimeout(r,250)); await flushAll(session.id);
    const next=await api(`/api/sessions/${session.id}/finish`,{method:"POST",headers:{"Idempotency-Key":crypto.randomUUID()}});setSession(next);
  }
  function speak() { const text=session?.transcript.at(-1)?.translation;if(!text)return;speaking.current=true;const utter=new SpeechSynthesisUtterance(text);utter.lang="zh-CN";utter.onend=()=>speaking.current=false;utter.onerror=()=>speaking.current=false;speechSynthesis.speak(utter) }
  async function saveDraft(summary:string){if(!session?.draft)return;const next=await api(`/api/sessions/${session.id}/draft`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({...session.draft,summary})});setSession(next)}
  async function publish(){if(!session)return;try{const next=await api(`/api/sessions/${session.id}/publish`,{method:"POST",headers:{"Idempotency-Key":crypto.randomUUID()}});setSession(next)}catch(e){setError(e instanceof Error?e.message:String(e))}}
  async function requestOrganize(){if(!session)return;setEstimateOpen(true);setEstimate(null);setEstimateError("");setEstimateLoading(true);try{setEstimate(await api(`/api/sessions/${session.id}/organize-estimate`))}catch(e){setEstimateError(e instanceof Error?e.message:String(e))}finally{setEstimateLoading(false)}}
  async function confirmOrganize(){if(!session||!estimate)return;setOrganizing(true);setError("");organizeDeadline.current=Date.now()+estimate.estimated_duration_seconds*1000;setOrganizeRemaining(estimate.estimated_duration_seconds);try{const next=await api(`/api/sessions/${session.id}/organize`,{method:"POST",headers:{"Idempotency-Key":crypto.randomUUID()}});setSession(next);setEstimateOpen(false)}catch(e){organizeDeadline.current=0;setOrganizeRemaining(null);setEstimateError(e instanceof Error?e.message:String(e))}finally{setOrganizing(false)}}
  const token=(value:number)=>new Intl.NumberFormat("zh-CN").format(value);
  const money=(value:number)=>`¥${value < .01 ? value.toFixed(4) : value.toFixed(3)}`;
  const eta=(value:number)=>`${String(Math.floor(value/60)).padStart(2,"0")}:${String(value%60).padStart(2,"0")}`;
  const active=session?.status==="recording"; const seconds=Math.floor(elapsed/1000); const stages=["recording","uploading","transcribing","organizing","draft_ready","published"];

  return <main className="shell">
    <header className="top"><div><div className="brand">NTU//COURSE_AGENT</div><small>REC · TRANSLATE · ORGANIZE · PUBLISH</small></div><span className="badge">{online?"ONLINE":"OFFLINE"} · {providerName.toUpperCase()}{user?` · ${user.login}`:""}</span></header>
    <div className="steps">{stages.map(x=><span className={`step ${session?.status===x?"on":""}`} key={x}>{x}</span>)}</div>
    <div className="grid">
      {authReady&&!user&&<Window title="AUTH_REQUIRED" tag="GITHUB" className="wide"><p>此服务仅允许配置的 GitHub 账号进入。</p><a className="btn primary" href={`${API}/auth/github/login?return_to=${encodeURIComponent(location.href)}`}>使用 GitHub 登录</a></Window>}
      {!session&&user&&<Window title="SESSION_SETUP" tag="DESKTOP MIC" className="wide"><Input label="COURSE" value={course} onChange={e=>setCourse(e.target.value)}/><Input label="TITLE" value={title} onChange={e=>setTitle(e.target.value)}/><Input label="HOTWORDS / comma separated" value={hotwords} onChange={e=>setHotwords(e.target.value)}/><div className="audio-source"><Select label="AUDIO INPUT" value={selectedAudioInput} onChange={e=>chooseAudioInput(e.target.value)}><option value="">系统默认麦克风</option>{audioInputs.map(input=><option key={input.deviceId} value={input.deviceId}>{input.label}</option>)}</Select><Button type="button" onClick={()=>refreshAudioInputs(true).catch(e=>setError(e instanceof Error?e.message:String(e)))} disabled={deviceLoading}>{deviceLoading?"扫描中…":"刷新 / 授权设备"}</Button></div><p className="time">电脑直接收声；连接蓝牙耳机或麦克风后，点击刷新并选择对应输入。手机仅用于控制页面。</p><p className="time">开始即确认你已获得课堂录音许可。录音时请保持本页在前台。</p></Window>}
      {session&&<><Window title="CAPTURE_MONITOR" tag={session.status}><div style={{fontSize:38,fontWeight:800}}>{String(Math.floor(seconds/60)).padStart(2,"0")}:{String(seconds%60).padStart(2,"0")}</div><Progress value={level}/><div className="statusline"><span>INPUT {activeAudioLabel}</span><span>UPLOADED {session.parts.length}</span><span>{uploading?"SYNCING":"SYNCED"}</span><span>CAPTION {transport.toUpperCase()}</span><span>KEEP SCREEN ON</span></div>{session.status==="recording"&&<Select label="SWITCH INPUT" value={selectedAudioInput} onChange={e=>chooseAudioInput(e.target.value)}><option value="">系统默认麦克风</option>{audioInputs.map(input=><option key={input.deviceId} value={input.deviceId}>{input.label}</option>)}</Select>}{session.status==="organizing"&&<div className="organize-countdown"><div className="countdown-head"><span>QWEN // STRUCTURING REVIEW_DRAFT</span><strong>{organizeRemaining===null?"CALCULATING":organizeRemaining>0?`ETA ${eta(organizeRemaining)}`:"FINALIZING"}</strong></div><div className={`terminal-progress ${organizeRemaining===0?"indeterminate":""}`}><i style={organizeRemaining!==null?{width:`${Math.min(96,Math.max(4,(1-organizeRemaining/(estimate?.estimated_duration_seconds||30))*100))}%`}:undefined}/></div><small>{organizeRemaining===0?"模型仍在生成结构化内容，请保持页面开启…":"正在提取摘要、知识点、日程与 DDL…"}</small></div>}{transport==="retrying"&&session.status==="recording"&&<p className="warn">实时字幕连接已断开；录音仍会保存并持续上传。</p>}{session.error&&<p className="warn">{session.error}</p>}</Window>
      <Window title="LIVE_TRANSCRIPT" tag="EN→ZH"><div>{session.transcript.length?session.transcript.map(s=><div className="caption" key={s.id}><span className="time">{(s.start_ms/1000).toFixed(1)}s · {s.id}</span><p>{s.source}</p><p className="zh">{s.translation}</p></div>):<p className="time">等待语音片段…</p>}</div></Window></>}
      {session?.draft&&<><Window title="REVIEW_DRAFT" tag={session.draft_source==="qwen_mcp"?"QWEN MCP":"AI SETUP REQUIRED"} className="wide"><TextArea label="SUMMARY" value={session.draft.summary} onChange={e=>setSession({...session,draft:{...session.draft!,summary:e.target.value}})} onBlur={e=>saveDraft(e.target.value)}/><h3>KEY POINTS</h3>{session.draft.key_points.map(x=><p key={x}>› {x}</p>)}<h3>SCHEDULE / DDL</h3><div className="schedule">{session.draft.schedule.map(x=><div key={x.id}><strong>{x.title}</strong><br/><small>{x.datetime||"待确认"} · {x.status}</small></div>)}</div>{session.draft.pending_confirmation.map(x=><p className="warn" key={x}>⚠ {x}</p>)}</Window></>}
      {session?.published_path&&<Window title="PUBLISHED" tag="GIT" className="wide"><p>✓ 已发布到 Obsidian</p><code>{session.published_path}</code></Window>}
    </div>
    {error&&<p className="warn">ERROR: {error}</p>}
    <div className="actions">{!session&&user&&<Button theme="primary" onClick={start}>● 开始录音</Button>}{active&&<><Button theme="danger" onClick={stop}>■ 停止并整理</Button><Button onClick={speak}>朗读最近译文</Button></>}{session?.status==="draft_ready"&&<><Button onClick={requestOrganize}>AI 重新整理</Button><Button theme="primary" disabled={session.draft_source!=="qwen_mcp"} onClick={publish}>确认并发布</Button><Button onClick={()=>setSession(null)}>暂存并返回</Button></>}</div>
    {estimateOpen&&<div className="dialog-backdrop" role="presentation" onMouseDown={e=>{if(e.target===e.currentTarget&&!organizing)setEstimateOpen(false)}}><section className="dialog" role="dialog" aria-modal="true" aria-labelledby="cost-dialog-title">
      <div className="bar"><span id="cost-dialog-title">AI_ORGANIZE // COST_CHECK</span><button className="dialog-close" aria-label="关闭" disabled={organizing} onClick={()=>setEstimateOpen(false)}>×</button></div>
      <div className="dialog-content">
        <div className="dialog-status"><span className="pulse">●</span><div><strong>即将重新生成课程纪要</strong><small>提交后将调用千问模型，现有草稿会在生成成功后更新。</small></div></div>
        {estimateLoading&&<div className="estimate-loading"><i/><span>正在读取转写并估算 Token…</span></div>}
        {estimateError&&<p className="warn">ERROR: {estimateError}</p>}
        {estimate&&<>
          <div className="cost-total"><span>预计本次费用</span><strong>{money(estimate.estimated_total_cost)}</strong><small>{estimate.currency} · 预估值</small></div>
          <div className="cost-grid">
            <div><span>INPUT</span><strong>{token(estimate.estimated_input_tokens)}</strong><small>TOKENS</small></div>
            <div><span>OUTPUT</span><strong>≈ {token(estimate.estimated_output_tokens)}</strong><small>TOKENS</small></div>
            <div><span>TOTAL</span><strong>≈ {token(estimate.estimated_total_tokens)}</strong><small>TOKENS</small></div>
          </div>
          <div className="rate-table"><div><span>MODEL</span><b>{estimate.model}</b></div><div><span>ESTIMATED TIME</span><b>≈ {eta(estimate.estimated_duration_seconds)}</b></div><div><span>PRICING TIER</span><b>{estimate.pricing_tier}</b></div><div><span>INPUT RATE</span><b>¥{estimate.input_rate_per_million} / 1M</b></div><div><span>OUTPUT RATE</span><b>¥{estimate.output_rate_per_million} / 1M</b></div><div><span>REGION</span><b>{estimate.pricing_region}</b></div></div>
          <p className="estimate-note">* 根据当前转写与结构化输出长度估算；实际 Token 和费用以千问账单为准。未假设缓存命中。</p>
        </>}
      </div>
      <div className="dialog-actions"><button className="btn" disabled={organizing} onClick={()=>setEstimateOpen(false)}>取消</button><button className="btn primary" disabled={!estimate||estimateLoading||organizing} onClick={confirmOrganize}>{organizing?"提交中…":"确认并开始整理"}</button></div>
    </section></div>}
    <footer className="footer">LOCAL AUDIO QUEUE / EVIDENCE TIMESTAMPS / REVIEW BEFORE PUBLISH</footer>
  </main>
}
