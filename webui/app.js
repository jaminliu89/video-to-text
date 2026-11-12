/* DRE Media Studio — primary product experience */
(function(){
'use strict';
const D=window.DRE, S=D.state, h=D.h, I=D.icon, $=D.$, $$=D.$$;
let pollBusy=false;
let editingDocumentDirty=false;

function pageHead(kicker,title,sub,actions){
  return '<div class="page-head"><div><div class="eyebrow">'+h(kicker)+'</div>'+
  '<h1 class="heading-xl">'+h(title)+'</h1><div class="body-copy">'+h(sub)+'</div></div>'+
  '<div class="page-head-actions">'+(actions||'')+'</div></div>';
}
function btn(label,action,cls,iconName,attrs){
  return '<button type="button" class="button '+(cls||'button-neutral')+'" data-action="'+h(action)+'" '+
    (attrs||'')+'>'+(iconName?I(iconName,16):'')+h(label)+'</button>';
}
function empty(iconName,title,description,button){
  return '<div class="empty"><div class="empty-icon">'+I(iconName,28)+'</div>'+
    '<strong>'+h(title)+'</strong><p>'+h(description)+'</p>'+(button||'')+'</div>';
}
function labelStatus(j){
  if(!j)return D.pill('未开始','subtle');
  const status=D.status(j.state);return D.pill(status[0],status[1]);
}
function resolveMediaJobs(){
  const media=D.selectedMedia();
  if(!media)return {};
  const jobs=D.jobsFor(media.id);
  const done=(kind)=>jobs.find(j=>j.kind===kind && j.state==='done')||null;
  return {
    digest:done('digest'), transcribe:done('transcribe'),
    ocr:done('ocr'), storyboard:done('storyboard'),
    reason:done('reason'), distill:done('distill')
  };
}
function bundle(){
  const jobs=resolveMediaJobs();
  const asrJob=jobs.digest||jobs.transcribe;
  const ocrJob=(jobs.ocr && (!jobs.digest || jobs.ocr.created_at > jobs.digest.created_at))? jobs.ocr:jobs.digest||jobs.ocr;
  const asr=asrJob && S.results.get(asrJob.id)||{};
  const ocr=ocrJob && S.results.get(ocrJob.id)||{};
  return {jobs,asrJob,ocrJob,speech:asr.segments||[],
    screen:ocr.ocr_segments||[],shots:(
      jobs.storyboard && S.results.get(jobs.storyboard.id)||
      asr.storyboard||{}
    )};
}
function projectCard(media){
  const folder=media.kind==='folder';
  const latest=media.latest_job||D.jobsFor(media.id)[0];
  return '<button type="button" class="card project-card" data-action="choose" data-id="'+h(media.id)+'">'+
   '<div class="project-cover">'+(folder?I('folder',38):
    '<img loading="lazy" src="/ui-api/media/'+encodeURIComponent(media.id)+'/thumbnail" alt="" onerror="this.style.display=\'none\'">'+I('film',35))+
    '<span class="project-kind">'+(folder?'批量项目':'本地视频')+'</span></div>'+
   '<div class="project-info"><div class="project-name" title="'+h(media.title)+'">'+h(media.title)+'</div>'+
    '<div class="project-path" title="'+h(media.source)+'">'+h(media.source)+'</div>'+
    '<div class="project-meta">'+(latest?labelStatus(latest):D.pill('等待分析','subtle'))+
    '<span class="tiny">'+D.formatSize(media.size)+'</span></div></div></button>';
}
function homeView(){
  const media=S.media, total=S.jobs.length, completed=S.jobs.filter(j=>j.state==='done').length;
  const cards=media.slice(0,9).map(projectCard).join('');
  return '<div class="page-head">'+
    '<div><div class="eyebrow">YOUR INTELLIGENCE WORKSPACE</div>'+
    '<h1 class="heading-xl">媒体智能空间</h1><div class="body-copy">将视频变成可复查、可编辑、可交付的知识资产。</div></div>'+
    btn('开始新项目','import','button-primary','plus')+'</div>'+
    '<section class="hero"><div class="hero-copy"><div class="hero-tag">DRE · LOCAL-FIRST MEDIA INTELLIGENCE</div>'+
    '<h1>让每一条视频，<br>变成真正可用的知识。</h1>'+
    '<p>本地识别声音和画面、还原完整证据；需要更深入的分析时，再由你选择大模型增强推理。</p>'+
    btn('导入视频开始分析','import','button-neutral','upload')+
    '</div><div class="hero-figure" aria-hidden="true"></div></section>'+
    '<section class="stats-row">'+
    metric('媒体资产',String(media.length),'film')+
    metric('已完成任务',String(completed),'check-circle')+
    metric('任务总数',String(total),'activity')+
    '</section>'+
    '<div class="section-heading"><h2>最近的媒体项目</h2>'+
    (media.length?btn('查看全部','projects','button-quiet','arrow-right'):'')+'</div>'+
    (media.length?'<div class="project-grid">'+cards+'</div>':
      '<div class="card">'+empty('video','还没有媒体项目',
       '导入第一条视频，工作台会以时间轴组织语音、画面文字和后续写作结果。',
       btn('选择视频','import','button-primary','plus'))+'</div>');
}
function metric(name,value,ic){
  return '<div class="card metric"><span class="metric-icon">'+I(ic,20)+'</span>'+
  '<div><label>'+h(name)+'</label><strong>'+h(value)+'</strong></div></div>';
}
function projectView(){
  return pageHead('MEDIA LIBRARY','项目与素材','视频文件和批量课程都集中保留在同一个工作空间。',
    btn('导入素材','import','button-primary','plus'))+
    (S.media.length?'<div class="project-grid">'+S.media.map(projectCard).join('')+'</div>':
      '<div class="card">'+empty('folder','媒体库是空的','从本地导入视频，或登记一个课程文件夹。',
       btn('导入素材','import','button-primary','plus'))+'</div>');
}
function workflowStep(index,title,phase){
  return '<div class="workflow-step '+phase+'"><span class="workflow-index">'+
    (phase==='done'?I('check',13):String(index))+'</span><span class="workflow-label">'+h(title)+'</span></div>';
}
function workflow(phase){
  const steps=['导入素材','本地感知','证据校对','全量撰写','资产交付'];
  return '<div class="card workflow">'+steps.map((label,i)=>{
    const status=i<phase?'done':i===phase?'current':'';
    return (i?'<div class="workflow-line"></div>':'')+workflowStep(i+1,label,status);
  }).join('')+'</div>';
}
function studioView(){
  const media=D.selectedMedia();
  if(!media)return pageHead('MEDIA STUDIO','分析工作台','先选一个媒体项目，再开始分析。')+
      '<div class="card">'+empty('film','选择一条视频开始','从素材库中选择项目，或直接导入本地视频。',
      btn('导入素材','import','button-primary','plus'))+'</div>';
  const jobs=D.jobsFor(media.id), b=bundle();
  let phase=1;
  if(b.asrJob||b.ocrJob)phase=2;
  if(b.jobs.digest)phase=3;
  if(b.jobs.reason)phase=4;
  const lastJob=jobs[0];
  const title='<div class="breadcrumb"><button type="button" data-action="projects">媒体项目</button>'+
     I('chevron-right',12)+'<span>分析工作台</span></div>'+
     '<div class="studio-title-row"><div><h1 class="studio-title">'+h(media.title)+'</h1>'+
     '<div class="studio-sub">'+D.pill('本地存储','accent')+
     '<span>'+D.formatSize(media.size)+'</span><span class="path-note" title="'+h(media.source)+'">'+h(media.source)+'</span></div></div>'+
     '<div class="page-head-actions">'+(lastJob?labelStatus(lastJob):D.pill('尚未分析','subtle'))+
     btn('切换项目','projects','button-neutral','folder')+'</div></div>';
  const primary=media.kind==='folder'?
    btn('蒸馏整个文件夹','run-distill','button-primary','sparkles'):
    btn('开始完整分析','run-digest','button-primary','sparkles');
  const dropdown='<label class="visually-hidden" for="engine-select">语音识别模型</label>'+
    '<select class="input-select" id="engine-select" aria-label="本地 ASR 模型"><option value="auto">自动选择本地模型</option>'+
    (S.caps.engines||[]).filter(e=>e.available&&e.engine!=='minutes').map(e=>
      '<option value="'+h(e.engine)+'"'+(S.engine===e.engine?' selected':'')+'>'+h(e.engine)+'</option>'
    ).join('')+'</select>';
  const actions='<div class="action-bar"><div class="action-group">'+primary+
    (media.kind==='video'?btn('仅转写','run-transcribe','button-neutral','audio')+
     btn('识别画面文字','run-ocr','button-neutral','scan')+
     btn('镜头索引','run-storyboard','button-neutral','film'):'')+
    (b.jobs.digest?btn('AI 深度撰写','reason','button-soft','sparkles'):'')+
    '</div><div class="action-group">'+dropdown+
    btn('刷新','refresh','button-neutral button-icon','refresh','aria-label="刷新任务"')+'</div></div>';
  const statusList=jobs.slice(0,4).map(j=>{
    const names={transcribe:'语音识别',ocr:'画面文字 OCR',storyboard:'镜头故事板',
      digest:'本地综合分析',reason:'大模型撰写',distill:'课程蒸馏'};
    return '<div class="status-item"><div class="status-item-left"><div class="status-icon">'+I(
      j.kind==='reason'?'sparkles':j.kind==='ocr'?'scan':j.kind==='transcribe'?'audio':'activity',16)+'</div>'+
      '<div><strong>'+h(names[j.kind]||j.kind)+'</strong><small>'+D.fmtDate(j.created_at)+' · '+h(j.engine)+'</small></div></div>'+
      labelStatus(j)+'</div>';
  }).join('');
  const docJob=b.jobs.reason;
  const doc=docJob&&S.results.get(docJob.id);
  const snippet=doc&&doc.analysis_markdown?doc.analysis_markdown.slice(0,240):'';
  const lower='<div class="workspace-lower">'+
    '<div class="card card-pad"><div class="card-head"><div class="card-title">处理记录</div>'+
    btn('全部任务','jobs','button-quiet','arrow-right')+'</div>'+
    (jobs.length?'<div class="status-list">'+statusList+'</div>':
      '<div class="preview-empty">提交分析后，这里会展示每一步的真实执行状态。</div>')+'</div>'+
    '<div class="card card-pad"><div class="card-head"><div class="card-title">完整文稿</div>'+
    (docJob?btn('打开编辑','documents','button-quiet','arrow-right'):'')+'</div>'+
    (docJob&&snippet?'<div class="preview-text">'+h(snippet)+'</div>'+
     '<div style="margin-top:15px">'+btn('进入文稿编辑器','documents','button-soft','file-text')+'</div>':
     '<div class="preview-empty">本地证据完成后，可授权 API 深度撰写，也可以导出原始转写和 OCR。</div>')+
     (b.asrJob?'<div style="margin-top:12px">'+btn('导出原始证据','export-md','button-neutral','download')+'</div>':'')+
    '</div></div>';
  return title+workflow(phase)+actions+
    '<div class="studio-grid">'+
    '<div><div class="card media-panel">'+
    '<div class="card-head"><div class="panel-overline">SOURCE / 视频预览</div>'+
    '<span class="tiny">'+(media.kind==='folder'?'批量项目':'原片未修改')+'</span></div>'+
    '<div class="media-frame">'+(media.kind==='video'?
      '<video id="studio-video" controls preload="metadata" playsinline src="/ui-api/media/'+encodeURIComponent(media.id)+'/stream"></video>':
      '<div class="folder-graphic">'+I('folder',52)+'<span>批量媒体文件夹</span></div>')+'</div>'+
    '<div class="media-toolbar"><span class="timecode" id="timecode">00:00 / 00:00</span>'+
    '<span class="media-hint">点击证据时间戳即可定位原片</span></div></div>'+
    '<div class="card timeline-card"><div class="timeline-head"><div class="card-title">证据时间轴</div>'+
    '<span class="tiny">ASR · OCR</span></div><div id="timeline-body"></div></div></div>'+
    '<section class="card evidence-panel"><div class="evidence-header"><div class="card-title">内容证据</div>'+
    D.pill('可回溯','accent')+'</div>'+
    '<div class="evidence-tools"><div class="evidence-filter">'+I('search',15)+
    '<input id="evidence-search" placeholder="搜索这条视频中的文字" aria-label="搜索内容证据" value="'+h(S.query)+'"></div></div>'+
    '<div class="tabs" role="tablist" aria-label="证据类型">'+
    tabButton('segments','语音逐字稿')+tabButton('ocr_segments','画面文字')+
    tabButton('shots','镜头索引')+'</div>'+
    '<div class="evidence-list" id="evidence-list"></div>'+
    '<div class="evidence-note">原始识别结果会保留；人工修改单独保存并标记。抽帧 OCR 可能遗漏短暂出现的文字。</div>'+
    '</section></div>'+lower;
}
function tabButton(key,label){
  return '<button role="tab" class="tab'+(S.currentTab===key?' active':'')+
   '" data-action="tab" data-tab="'+key+'" aria-selected="'+(S.currentTab===key)+'">'+label+'</button>';
}
function evidenceBundleForTab(){
  const b=bundle();
  if(S.currentTab==='segments')return {items:b.speech,job:b.asrJob,channel:'segments'};
  if(S.currentTab==='ocr_segments')return {items:b.screen,job:b.ocrJob,channel:'ocr_segments'};
  return {items:[],job:b.jobs.storyboard||b.jobs.digest,channel:'shots'};
}
function renderEvidence(){
  const root=$('#evidence-list');if(!root)return;
  if(S.currentTab==='shots'){renderShots(root);return;}
  const e=evidenceBundleForTab(), q=S.query.trim().toLowerCase();
  const all=e.items||[];
  const filtered=all.map((row,index)=>({row,index})).filter(x=>!q||String(x.row.text||'').toLowerCase().includes(q));
  if(!e.job||!all.length){
    root.innerHTML=empty(S.currentTab==='segments'?'audio':'scan',
       S.currentTab==='segments'?'还没有逐字稿':'尚无画面文字',
       S.currentTab==='segments'?'点击「开始完整分析」或「仅转写」生成真实语音证据。':
       '点击「识别画面文字」执行 Apple Vision OCR。','');
    return;
  }
  if(!filtered.length){root.innerHTML=empty('search','没有找到匹配内容','尝试更换搜索关键词。','');return;}
  root.innerHTML=filtered.map(({row,index})=>{
    const corrected=!!(e.job&&S.results.get(e.job.id)&&row.text!==undefined&&
       e.job.state==='done'&&S.editedKeys&&S.editedKeys.has(e.job.id+':'+e.channel+':'+index));
    const time=Number(row.start||row.time||0);
    return '<div class="evidence-entry" data-evidence-index="'+index+'">'+
      '<button class="evidence-time" data-action="seek" data-time="'+time+'" title="跳转视频">'+
      D.formatTime(time)+'</button>'+
      '<div><div class="evidence-text">'+h(row.text||'')+'</div>'+
      (corrected?'<div class="evidence-edited">已人工校对</div>':'')+'</div>'+
      '<button class="evidence-edit" data-action="edit-evidence" data-index="'+index+
      '" data-channel="'+e.channel+'" aria-label="校对文字">'+I('edit',15)+'</button></div>';
  }).join('');
}
function renderShots(root){
  const b=bundle();
  const shots=b.shots||{}, pages=shots.pages||shots.storyboard?.pages||[];
  if(!pages.length){
    root.innerHTML=empty('film','尚无镜头索引',
      '可运行「镜头索引」生成时间戳故事板。生成结果保留在本地资产目录中。','');
    return;
  }
  root.innerHTML='<div style="padding:14px"><div class="card-subtitle">已输出 '+pages.length+
    ' 页故事板。帧时间可能来自旧算法的估计值，请勿直接作为镜头切点真值。</div>'+
    '<div class="status-list">'+pages.map((p,i)=>
    '<div class="status-item"><span style="font-size:12px;font-weight:650">故事板 '+(i+1)+'</span>'+
    '<span class="tiny" title="'+h(p)+'">已保存至本地资产目录</span></div>').join('')+'</div></div>';
}
function renderTimeline(){
  const root=$('#timeline-body');if(!root)return;
  const b=bundle();
  let dur=S.duration;
  for(const a of [b.speech,b.screen])for(const x of a)dur=Math.max(dur,Number(x.end||x.start||0));
  dur=Math.max(1,dur);
  S.duration=dur;
  function row(name,items,cls){
    const bars=(items||[]).slice(0,900).map(x=>{
      const t=Number(x.start||0),end=Number(x.end||t+1);
      const left=(100*t/dur).toFixed(3), width=Math.max(.18,100*Math.max(.1,end-t)/dur).toFixed(3);
      return '<button type="button" class="track-segment '+cls+'" data-action="seek" data-time="'+t+
      '" style="left:'+left+'%;width:'+width+'%" title="'+h(D.formatTime(t)+' · '+String(x.text||'').slice(0,75))+'"></button>';
    }).join('');
    return '<div class="track"><span class="track-label">'+name+'</span><div class="track-bar">'+
      (bars||'<span class="track-empty">无数据</span>')+
      '<div class="track-cursor" style="left:'+(100*S.time/dur).toFixed(3)+'%"></div></div></div>';
  }
  root.innerHTML='<div class="timeline-tracks">'+row('ASR',b.speech,'')+
    row('OCR',b.screen,'ocr')+'</div><div class="track-times"><span>00:00</span><span>'+
    D.formatTime(dur/2)+'</span><span>'+D.formatTime(dur)+'</span></div>';
}
function bindVideo(){
  const video=$('#studio-video');if(!video)return;
  video.addEventListener('loadedmetadata',function(){
    S.duration=video.duration||S.duration;
    if(S.time>0&&S.time<video.duration)video.currentTime=S.time;
    updateTimecode();renderTimeline();
  });
  video.addEventListener('timeupdate',function(){
    S.time=video.currentTime;updateTimecode();
    $$('.track-cursor').forEach(el=>el.style.left=(100*S.time/Math.max(S.duration,1))+'%');
  });
  video.addEventListener('error',()=>D.toast('当前浏览器无法播放此视频编码，可使用原生媒体播放器。',true));
  updateTimecode();
}
function updateTimecode(){
  const n=$('#timecode');if(n)n.textContent=D.formatTime(S.time)+' / '+D.formatTime(S.duration);
}
function seek(ts){
  const video=$('#studio-video');if(!video){D.toast('当前项目没有可以播放的单条视频',true);return;}
  if(video.readyState>=1){video.currentTime=Number(ts)||0;}
  else {video.addEventListener('loadedmetadata',()=>video.currentTime=Number(ts)||0,{once:true});}
}
