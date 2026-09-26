"use client";

import { useEffect, useRef, useState } from "react";
import { markUploaded, pendingParts, putPart, sha256, StoredPart } from "../src/storage";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";
type Segment = { id:string; start_ms:number; end_ms:number; source:string; translation:string };
type Schedule = { id:string; kind:string; title:string; datetime:string|null; status:string };
type Draft = { summary:string; key_points:string[]; schedule:Schedule[]; mindmap:unknown[]; pending_confirmation:string[] };
type Session = { id:string; course:string; title:string; status:string; transcript:Segment[]; parts:number[]; draft?:Draft; published_path?:string; error?:string };

async function api(path:string, init?:RequestInit) {
  const response = await fetch(`${API}${path}`, {...init, credentials:"include"});
  if (!response.ok) throw new Error((await response.json()).detail || response.statusText);
  return response.json();
}

function Window({title, tag, className="", children}:{title:string;tag?:string;className?:string;children:React.ReactNode}) {
  return <section className={`window ${className}`}><div className="bar"><span>{title}</span><span>{tag || "SYS"}</span></div><div className="content">{children}</div></section>;
}

export default function Home() {
  const [course,setCourse]=useState("NTU Visual Storytelling"); const [title,setTitle]=useState("课堂记录");
  const [hotwords,setHotwords]=useState("mise-en-scène, production design, deadline");
  const [session,setSession]=useState<Session|null>(null); const [error,setError]=useState("");
  const [elapsed,setElapsed]=useState(0); const [level,setLevel]=useState(0); const [uploading,setUploading]=useState(false);
  const [online,setOnline]=useState(true);
  const [transport,setTransport]=useState<"idle"|"connecting"|"live"|"retrying">("idle");
  const [user,setUser]=useState<{login:string}|null>(null); const [authReady,setAuthReady]=useState(false);
  const recorder=useRef<MediaRecorder|null>(null); const stream=useRef<MediaStream|null>(null); const seq=useRef(0);
  const socket=useRef<WebSocket|null>(null); const startAt=useRef(0); const speaking=useRef(false);
  const flushing=useRef(false);

  useEffect(()=>{navigator.serviceWorker?.register("/sw.js").catch(()=>{});api("/auth/me").then(x=>setUser(x.user)).catch(()=>setUser(null)).finally(()=>setAuthReady(true));const sync=()=>setOnline(navigator.onLine);sync();addEventListener("online",sync);addEventListener("offline",sync);return()=>{removeEventListener("online",sync);removeEventListener("offline",sync)}},[]);
  useEffect(()=>{if(online&&session)flushAll(session.id).catch(()=>{})},[online]);
  useEffect(()=>{if(!session||session.status!=="recording")return;const id=setInterval(()=>setElapsed(Date.now()-startAt.current),500);return()=>clearInterval(id)},[session?.status]);
  useEffect(()=>{if(!session||session.status!=="recording")return;const id=setInterval(()=>flushAll(session.id).catch(()=>{}),3000);return()=>clearInterval(id)},[session?.id,session?.status]);
  useEffect(()=>{if(!session||!["uploading","transcribing","organizing"].includes(session.status))return;const id=setInterval(async()=>{const next=await api(`/api/sessions/${session.id}`);setSession(next)},900);return()=>clearInterval(id)},[session?.id,session?.status]);

  async function flush(part:StoredPart) {
    if(!navigator.onLine)return;
    const digest=await sha256(part.blob); const form=new FormData(); form.append("audio",part.blob,"part.webm");
    const result=await api(`/api/sessions/${part.sessionId}/audio-parts?sequence=${part.sequence}&sha256=${digest}`,{method:"POST",body:form});
    await markUploaded(part);
    setSession(current=>current&&current.id===part.sessionId?{...current,parts:result.received,
      transcript:result.caption&&!current.transcript.some(x=>x.id===result.caption.id)?[...current.transcript,result.caption].sort((a,b)=>a.start_ms-b.start_ms):current.transcript}:current);
  }
  async function flushAll(id:string) { if(flushing.current)return;flushing.current=true;setUploading(true);try{for(const p of await pendingParts(id))await flush(p);setTransport(socket.current?.readyState===1?"live":"retrying")}finally{flushing.current=false;setUploading(false)} }

  async function start() {
    setError("");
    try {
      const created:Session=await api("/api/sessions",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({course,title,source_language:"en",target_language:"zh-CN",timezone:Intl.DateTimeFormat().resolvedOptions().timeZone,hotwords:hotwords.split(",").map(x=>x.trim()).filter(Boolean),recording_consent:true})});
      const media=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,channelCount:1}}); stream.current=media;
      setTransport("connecting");const wsBase=API.replace(/^http/,"ws"); const ws=new WebSocket(`${wsBase}/api/sessions/${created.id}/live`); socket.current=ws;
      ws.onopen=()=>setTransport("live");ws.onclose=()=>setTransport("retrying");ws.onerror=()=>setTransport("retrying");
      ws.onmessage=e=>{const msg=JSON.parse(e.data);if(msg.type==="caption")setSession(s=>s?{...s,transcript:[...s.transcript,msg.segment]}:s)};
      const rec=new MediaRecorder(media,{mimeType:MediaRecorder.isTypeSupported("audio/webm;codecs=opus")?"audio/webm;codecs=opus":"audio/webm"}); recorder.current=rec; seq.current=0;
      rec.ondataavailable=async e=>{if(!e.data.size||speaking.current)return;const p={key:`${created.id}:${seq.current}`,sessionId:created.id,sequence:seq.current++,blob:e.data,uploaded:false};await putPart(p);socket.current?.readyState===1&&socket.current.send(e.data);flushAll(created.id).catch(()=>{})};
      const ctx=new AudioContext(); const analyser=ctx.createAnalyser(); ctx.createMediaStreamSource(media).connect(analyser); const data=new Uint8Array(analyser.frequencyBinCount);
      const meter=()=>{if(!stream.current)return;analyser.getByteFrequencyData(data);setLevel(Math.min(100,data.reduce((a,b)=>a+b,0)/data.length));requestAnimationFrame(meter)};meter();
      try{await (navigator as Navigator & {wakeLock?:{request:(x:string)=>Promise<unknown>}}).wakeLock?.request("screen")}catch{}
      startAt.current=Date.now();setElapsed(0);setSession(created);rec.start(3000);
    } catch(e){setError(e instanceof Error?e.message:String(e))}
  }

  async function stop() {
    if(!session)return; recorder.current?.stop(); stream.current?.getTracks().forEach(t=>t.stop());stream.current=null;socket.current?.close();
    await new Promise(r=>setTimeout(r,250)); await flushAll(session.id);
    const next=await api(`/api/sessions/${session.id}/finish`,{method:"POST",headers:{"Idempotency-Key":crypto.randomUUID()}});setSession(next);
  }
  function speak() { const text=session?.transcript.at(-1)?.translation;if(!text)return;speaking.current=true;const utter=new SpeechSynthesisUtterance(text);utter.lang="zh-CN";utter.onend=()=>speaking.current=false;utter.onerror=()=>speaking.current=false;speechSynthesis.speak(utter) }
  async function saveDraft(summary:string){if(!session?.draft)return;const next=await api(`/api/sessions/${session.id}/draft`,{method:"PATCH",headers:{"Content-Type":"application/json"},body:JSON.stringify({...session.draft,summary})});setSession(next)}
  async function publish(){if(!session)return;try{const next=await api(`/api/sessions/${session.id}/publish`,{method:"POST",headers:{"Idempotency-Key":crypto.randomUUID()}});setSession(next)}catch(e){setError(e instanceof Error?e.message:String(e))}}
  const active=session?.status==="recording"; const seconds=Math.floor(elapsed/1000); const stages=["recording","uploading","transcribing","organizing","draft_ready","published"];

  return <main className="shell">
    <header className="top"><div><div className="brand">NTU//COURSE_AGENT</div><small>REC · TRANSLATE · ORGANIZE · PUBLISH</small></div><span className="badge">{online?"ONLINE":"OFFLINE"}{user?` · ${user.login}`:""}</span></header>
    <div className="steps">{stages.map(x=><span className={`step ${session?.status===x?"on":""}`} key={x}>{x}</span>)}</div>
    <div className="grid">
      {authReady&&!user&&<Window title="AUTH_REQUIRED" tag="GITHUB" className="wide"><p>此服务仅允许配置的 GitHub 账号进入。</p><a className="btn primary" href={`${API}/auth/github/login?return_to=${encodeURIComponent(location.href)}`}>使用 GitHub 登录</a></Window>}
      {!session&&user&&<Window title="SESSION_SETUP" tag="01" className="wide"><div className="field"><span>COURSE</span><input value={course} onChange={e=>setCourse(e.target.value)}/></div><div className="field"><span>TITLE</span><input value={title} onChange={e=>setTitle(e.target.value)}/></div><div className="field"><span>HOTWORDS / comma separated</span><input value={hotwords} onChange={e=>setHotwords(e.target.value)}/></div><p className="time">开始即确认你已获得课堂录音许可。录音时请保持本页在前台。</p></Window>}
      {session&&<><Window title="CAPTURE_MONITOR" tag={session.status}><div style={{fontSize:38,fontWeight:800}}>{String(Math.floor(seconds/60)).padStart(2,"0")}:{String(seconds%60).padStart(2,"0")}</div><div className="meter"><i style={{width:`${level}%`}}/></div><div className="statusline"><span>UPLOADED {session.parts.length}</span><span>{uploading?"SYNCING":"SYNCED"}</span><span>CAPTION {transport.toUpperCase()}</span><span>KEEP SCREEN ON</span></div>{transport==="retrying"&&<p className="warn">实时字幕连接已断开；录音仍会保存并持续上传。</p>}{session.error&&<p className="warn">{session.error}</p>}</Window>
      <Window title="LIVE_TRANSCRIPT" tag="EN→ZH"><div>{session.transcript.length?session.transcript.map(s=><div className="caption" key={s.id}><span className="time">{(s.start_ms/1000).toFixed(1)}s · {s.id}</span><p>{s.source}</p><p className="zh">{s.translation}</p></div>):<p className="time">等待语音片段…</p>}</div></Window></>}
      {session?.draft&&<><Window title="REVIEW_DRAFT" tag="EDIT" className="wide"><div className="field"><span>SUMMARY</span><textarea value={session.draft.summary} onChange={e=>setSession({...session,draft:{...session.draft!,summary:e.target.value}})} onBlur={e=>saveDraft(e.target.value)}/></div><h3>KEY POINTS</h3>{session.draft.key_points.map(x=><p key={x}>› {x}</p>)}<h3>SCHEDULE / DDL</h3><div className="schedule">{session.draft.schedule.map(x=><div key={x.id}><strong>{x.title}</strong><br/><small>{x.datetime||"待确认"} · {x.status}</small></div>)}</div>{session.draft.pending_confirmation.map(x=><p className="warn" key={x}>⚠ {x}</p>)}</Window></>}
      {session?.published_path&&<Window title="PUBLISHED" tag="GIT" className="wide"><p>✓ 已发布到 Obsidian</p><code>{session.published_path}</code></Window>}
    </div>
    {error&&<p className="warn">ERROR: {error}</p>}
    <div className="actions">{!session&&user&&<button className="btn primary" onClick={start}>● 开始录音</button>}{active&&<><button className="btn stop" onClick={stop}>■ 停止并整理</button><button className="btn" onClick={speak}>朗读最近译文</button></>}{session?.status==="draft_ready"&&<><button className="btn primary" onClick={publish}>确认并发布</button><button className="btn" onClick={()=>setSession(null)}>暂存并返回</button></>}</div>
    <footer className="footer">LOCAL AUDIO QUEUE / EVIDENCE TIMESTAMPS / REVIEW BEFORE PUBLISH</footer>
  </main>
}
