export type CaptureController = { stop: () => Promise<void> };

function wavBlob(samples: Float32Array, inputRate: number): Blob {
  const outputRate = 16000;
  const ratio = inputRate / outputRate;
  const length = Math.max(1, Math.floor(samples.length / ratio));
  const buffer = new ArrayBuffer(44 + length * 2);
  const view = new DataView(buffer);
  const text = (offset:number, value:string) => [...value].forEach((c,i)=>view.setUint8(offset+i,c.charCodeAt(0)));
  text(0,"RIFF"); view.setUint32(4,36+length*2,true); text(8,"WAVE"); text(12,"fmt ");
  view.setUint32(16,16,true); view.setUint16(20,1,true); view.setUint16(22,1,true);
  view.setUint32(24,outputRate,true); view.setUint32(28,outputRate*2,true); view.setUint16(32,2,true); view.setUint16(34,16,true);
  text(36,"data"); view.setUint32(40,length*2,true);
  for(let i=0;i<length;i++){
    const start=Math.floor(i*ratio), end=Math.max(start+1,Math.floor((i+1)*ratio)); let sum=0;
    for(let j=start;j<end&&j<samples.length;j++)sum+=samples[j];
    const value=Math.max(-1,Math.min(1,sum/(end-start))); view.setInt16(44+i*2,value<0?value*32768:value*32767,true);
  }
  return new Blob([buffer],{type:"audio/wav"});
}

export async function startPcmCapture(stream:MediaStream,onChunk:(blob:Blob)=>Promise<void>,onLevel:(level:number)=>void):Promise<CaptureController>{
  const context=new AudioContext(); const source=context.createMediaStreamSource(stream); const processor=context.createScriptProcessor(4096,1,1);
  const silent=context.createGain(); silent.gain.value=0; const frames:Float32Array[]=[]; let samples=0; let stopping=false;let hasVoice=false;let silentSamples=0;
  source.connect(processor);processor.connect(silent);silent.connect(context.destination);
  const flush=async()=>{if(!samples)return;const merged=new Float32Array(samples);let offset=0;for(const frame of frames){merged.set(frame,offset);offset+=frame.length}frames.length=0;samples=0;hasVoice=false;silentSamples=0;await onChunk(wavBlob(merged,context.sampleRate))};
  processor.onaudioprocess=event=>{if(stopping)return;const frame=new Float32Array(event.inputBuffer.getChannelData(0));frames.push(frame);samples+=frame.length;
    let energy=0;for(const x of frame)energy+=x*x;const rms=Math.sqrt(energy/frame.length);onLevel(Math.min(100,rms*500));
    if(rms>.008){hasVoice=true;silentSamples=0}else if(hasVoice)silentSamples+=frame.length;
    if((hasVoice&&silentSamples>=context.sampleRate*.6&&samples>=context.sampleRate*.8)||samples>=context.sampleRate*4){
      if(hasVoice)void flush();else{frames.length=0;samples=0;silentSamples=0}
    }};
  return {stop:async()=>{stopping=true;processor.disconnect();source.disconnect();silent.disconnect();await flush();await context.close()}};
}
