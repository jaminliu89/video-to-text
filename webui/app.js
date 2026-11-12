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

function documentsView(){
  const media=D.selectedMedia();
  if(!media)return pageHead('DELIVERABLES','文稿与交付','首先选择一个媒体项目。')+
    '<div class="card">'+empty('file-text','还没有可以交付的内容','导入并分析视频，才能从证据生成文稿。',
      btn('导入视频','import','button-primary','plus'))+'</div>';
  const records=D.jobsFor(media.id).filter(j=>j.state==='done');
  const reasons=records.filter(j=>j.kind==='reason');
  if(!S.activeDocument || !reasons.some(j=>j.id===S.activeDocument))S.activeDocument=reasons[0]?.id||null;
  const docJob=reasons.find(j=>j.id===S.activeDocument);
  const doc=docJob&&S.results.get(docJob.id);
  const article=(S.docMode==='edit'&&S.docDraft)?S.docDraft:(doc?.analysis_markdown||'');
  const header=pageHead('DELIVERABLES / DOCUMENTS','文稿与交付',
    '原始证据永久保留；生成稿可二次编辑、验证和导出。',
    docJob?btn('下载 Markdown','doc-download','button-primary','download'):'');
  const list=records.map(j=>{
    const title=({reason:'完整蒸馏文稿',digest:'多模态证据汇总',
      transcribe:'语音逐字稿',ocr:'画面文字',storyboard:'镜头索引',distill:'课程知识包'})[j.kind]||j.kind;
    const selected=docJob&&docJob.id===j.id;
    return '<button type="button" class="doc-option'+(selected?' active':'')+
      '" data-action="'+(j.kind==='reason'?'pick-document':'download-record')+
      '" data-id="'+h(j.id)+'"><strong>'+h(title)+'</strong><span>'+
      D.fmtDate(j.created_at)+' · '+h(j.engine)+'</span></button>';
  }).join('');
  const content=docJob&&doc?
    '<div class="doc-toolbar"><span class="pill accent">来源可回溯 · 模型生成</span>'+
    '<div class="action-group"><div class="doc-mode">'+
    '<button data-action="doc-mode" data-mode="read" class="'+(S.docMode==='read'?'active':'')+'">阅读</button>'+
    '<button data-action="doc-mode" data-mode="edit" class="'+(S.docMode==='edit'?'active':'')+'">编辑</button>'+
    '</div>'+btn('保存修改','doc-save','button-soft','save',
        S.docMode!=='edit'?'disabled':'')+'</div></div>'+
    (S.docMode==='edit'?
      '<textarea class="doc-editor" id="document-editor" aria-label="编辑 Markdown 文稿" spellcheck="false">'+h(article)+'</textarea>':
      '<article class="doc-article">'+renderMarkdown(article)+'</article>')+
    '<div class="doc-foot"><span>'+String(article.length)+' 字 · 人工修改不会覆盖模型原始结果</span>'+
    '<span>'+h(docJob.engine)+'</span></div>':
    empty('book','还没有生成完整文稿',
      '先回到分析工作台完成本地证据汇总，再选择已配置的推理 API 并授权生成。',
      btn('返回分析工作台','studio','button-primary','arrow-right'));
  return header+'<div class="docs-layout"><aside class="card docs-left">'+
    '<div class="card-head"><span class="card-title">项目交付物</span>'+D.pill(String(records.length),'subtle')+'</div>'+
    '<div class="divider"></div>'+(records.length?list:
    '<div class="preview-empty">暂无完成的任务</div>')+
    '<div class="divider"></div><div class="tiny">点击非文稿结果可下载对应的完整 Markdown。</div>'+
    '</aside><section class="card docs-main">'+content+'</section></div>';
}
function renderMarkdown(text){
  const lines=String(text||'').split(/\r?\n/),out=[];
  let paragraph=[],code=[],inCode=false;
  function flush(){if(paragraph.length){out.push('<p>'+paragraph.map(h).join('<br>')+'</p>');paragraph=[];}}
  for(const line of lines){
    if(/^\s*(?:~{3}|\x60{3})/.test(line)){
      flush();
      if(inCode){out.push('<div class="md-code">'+h(code.join('\n'))+'</div>');code=[];}
      inCode=!inCode;continue;
    }
    if(inCode){code.push(line);continue;}
    const heading=line.match(/^(#{1,3})\s+(.*)/);
    if(heading){
      flush();const lvl=heading[1].length;
      out.push('<h'+lvl+'>'+h(heading[2])+'</h'+lvl+'>');
    }else if(!line.trim())flush();
    else if(/^[-*]\s/.test(line)){flush();out.push('<p>• '+h(line.slice(2))+'</p>');}
    else paragraph.push(line);
  }
  flush();
  return out.join('')||'<div class="preview-empty">文稿为空。</div>';
}
function jobsView(){
  const rows=S.jobs;
  const data=rows.map(j=>{
    const m=S.media.find(x=>x.id===j.media_id);
    const names={transcribe:'语音转写',digest:'完整分析',ocr:'画面文字 OCR',
      storyboard:'镜头索引',distill:'知识蒸馏',reason:'大模型撰写'};
    const action=j.state==='error'||j.state==='cancelled'||j.state==='interrupted'?
      '<button class="text-button" data-action="retry-job" data-id="'+h(j.id)+'">重新执行</button>':
      j.state==='queued'?
      '<button class="text-button" data-action="cancel-job" data-id="'+h(j.id)+'">取消排队</button>':
      j.state==='done'?
      '<button class="text-button" data-action="inspect-job" data-id="'+h(j.id)+
      '" data-media="'+h(j.media_id)+'">查看结果</button>':'<span class="tiny">执行中</span>';
    return '<tr><td><span class="job-title">'+h(names[j.kind]||j.kind)+'</span>'+
      '<span class="job-secondary">'+h(j.engine||'')+' · '+h(j.id.slice(0,10))+'</span></td>'+
      '<td><span title="'+h(m?.source||'')+'">'+h(m?.title||'未知项目')+'</span></td>'+
      '<td>'+labelStatus(j)+'</td><td>'+D.fmtDate(j.created_at)+'</td><td>'+action+'</td></tr>';
  }).join('');
  return pageHead('PROCESS MONITOR','任务中心','任务真实状态、失败原因与重试记录都集中在这里。',
      btn('刷新任务','refresh','button-neutral','refresh'))+
    '<div class="card"><div class="table-wrap"><table class="data-table"><thead><tr>'+
    '<th>任务</th><th>媒体项目</th><th>状态</th><th>提交时间</th><th>操作</th></tr></thead><tbody>'+
    (rows.length?data:'<tr><td colspan="5">'+empty('activity','暂无任务','提交分析后，这里会显示处理队列。','')+'</td></tr>')+
    '</tbody></table></div></div>'+
    '<div class="body-copy">Mac 单机持久化队列：运行中的任务无法立即取消；中断和失败的任务可重新提交。不会显示未经计算的虚假进度条。</div>';
}
function capabilitiesView(){
  const engines=S.caps.engines||[], abilities=S.caps.abilities||[];
  const provider=S.provider||{};
  const table=engines.filter(e=>e.engine!=='minutes').map(e=>
    '<div class="setting-row"><div><strong>'+h(e.engine)+'</strong>'+
    '<p>'+h(e.reason||'由运行环境自动检测')+'</p></div>'+
    D.pill(e.available?'本机可用':'未就绪',e.available?'success':'subtle')+'</div>').join('');
  const indicators=abilities.map(a=>
    '<div class="setting-row"><strong>'+h(a.name)+'</strong>'+
    D.pill(a.status==='available'?'可用':a.status==='not_integrated'?'尚未接入':a.status,
       a.status==='available'?'success':'subtle')+'</div>').join('');
  return pageHead('CAPABILITY CENTER','模型与 Agent 接入',
     '本地负责感知，模型服务按需参与推理；任何 Agent 可调用同一任务 API。')+
    '<div class="settings-grid">'+
    '<div><section class="card card-pad"><div class="card-head"><div class="card-title">本地模型</div>'+
    D.pill('Apple Silicon','accent')+'</div><div class="card-subtitle" style="margin-top:7px">ASR 模型状态来自真实运行环境，不按安装文档猜测可用性。</div>'+
    '<div class="status-list">'+(table||'<div class="preview-empty">尚无模型检测结果。</div>')+'</div></section>'+
    '<section class="card card-pad" style="margin-top:16px"><div class="card-head"><div class="card-title">能力状态</div></div>'+
    '<div class="status-list">'+indicators+'</div></section></div>'+
    '<div><section class="card card-pad"><div class="card-head"><div class="card-title">增强推理 API</div>'+
    D.pill(provider.configured?'已配置 · 未测速':'未配置',provider.configured?'accent':'subtle')+'</div>'+
    '<p class="card-subtitle" style="margin-top:9px">本地识别先生成证据。只有具体视频经过你确认，才会发送 ASR/OCR 文本给这里的模型。</p>'+
    '<form id="provider-form">'+
    '<div class="form-field"><label for="provider-base">OpenAI 兼容 API Base URL</label>'+
    '<input id="provider-base" autocomplete="url" placeholder="https://api.example.com/v1" value="'+h(provider.base_url||'')+'"></div>'+
    '<div class="form-field"><label for="provider-model">模型名称</label>'+
    '<input id="provider-model" placeholder="model-id" value="'+h(provider.model||'')+'"></div>'+
    '<div class="form-field"><label for="provider-key">API Key</label>'+
    '<input id="provider-key" type="password" autocomplete="off" placeholder="同一地址留空则保留已有 Key"></div>'+
    '<p class="form-help">API 密钥只存于本机配置文件，不会显示在工作台。远端地址必须使用 HTTPS。</p>'+
    '<button class="button button-primary" type="submit">'+I('save',16)+'保存模型配置</button>'+
    '</form></section>'+
    '<section class="card card-pad" style="margin-top:16px">'+
    '<div class="card-head"><div class="card-title">Agent · MCP 接入</div>'+D.pill('本地服务','accent')+'</div>'+
    '<p class="card-subtitle" style="margin-top:9px">Codex、Cursor、Claude Code 可以通过 stdio MCP 共享本地识别能力，不必自己加载 Qwen 或 Apple Vision。</p>'+
    '<div class="copy-code" style="margin-top:16px"><code>python -m v2t.workbench_mcp</code>'+
    '<button class="button button-neutral" data-action="copy-mcp" type="button">'+I('copy',13)+'复制</button></div>'+
    '<p class="form-help" style="margin-top:11px">为 Agent 指定授权文件目录：V2T_AGENT_ALLOWED_ROOTS。兼容 REST API 与 MCP 使用同一任务服务。</p>'+
    '</section></div></div>';
}
function render(){
  let markup='';
  if(S.view==='home')markup=homeView();
  else if(S.view==='projects')markup=projectView();
  else if(S.view==='studio')markup=studioView();
  else if(S.view==='documents')markup=documentsView();
  else if(S.view==='jobs')markup=jobsView();
  else if(S.view==='capabilities')markup=capabilitiesView();
  $('#content').innerHTML=markup;
  D.renderStaticIcons();
  if(S.view==='studio'){
    renderEvidence();renderTimeline();bindVideo();
    const input=$('#evidence-search');
    if(input)input.addEventListener('input',e=>{S.query=e.target.value;renderEvidence();});
    const select=$('#engine-select');
    if(select)select.addEventListener('change',e=>{S.engine=e.target.value;});
  }
  if(S.view==='capabilities'){
    const form=$('#provider-form');
    if(form)form.addEventListener('submit',saveProvider);
  }
  if(S.view==='documents'&&S.docMode==='edit'){
    const textarea=$('#document-editor');
    if(textarea)textarea.addEventListener('input',e=>{
      S.docDraft=e.target.value;editingDocumentDirty=true;
    });
  }
}
D.render=render;

async function choose(id){
  S.selected=id;S.time=0;S.duration=0;S.currentTab='segments';S.query='';
  await D.loadMediaResults();D.nav('studio');
}
function setView(view){
  if(view==='studio'||view==='documents')D.loadMediaResults().then(()=>D.nav(view));
  else D.nav(view);
}
function showImport(){
  const html='<div class="modal-title">导入媒体到工作台</div>'+
    '<p class="modal-sub">直接选择或拖入本地视频。文件只保存在这台 Mac 的工作空间中，不会自动上传外部云服务。</p>'+
    '<div class="dropzone" id="dropzone" role="button" tabindex="0">'+
    '<div class="dropzone-icon">'+I('upload',26)+'</div>'+
    '<strong>拖拽视频到这里，或点击选择文件</strong>'+
    '<span>MP4 / MOV / MKV / WebM 等 · 多文件可依次导入</span>'+
    '<button class="button button-soft" id="choose-files">'+I('folder',15)+'浏览本地文件</button></div>'+
    '<div class="import-progress hidden" id="upload-progress"><div id="upload-progress-bar"></div></div>'+
    '<details style="margin-top:18px"><summary class="text-button" style="cursor:pointer;list-style:none">导入本机文件夹或已有路径</summary>'+
    '<div class="form-field"><label for="import-path">Mac 本地文件或文件夹路径</label>'+
    '<input type="text" id="import-path" placeholder="/Users/.../Movies/课程">'+
    '<span class="form-help">适合包含很多视频的课程目录；此操作只登记路径，不复制整个文件夹。</span>'+
    '<button class="button button-neutral" type="button" id="import-by-path">登记此路径</button></div></details>'+
    '<div class="modal-actions">'+btn('取消','close-modal','button-neutral')+'</div>';
  D.modal(html,true);
  const zone=$('#dropzone'),input=$('#upload-input');
  function open(){input.click();}
  zone.addEventListener('click',e=>{if(e.target.closest('#choose-files'))return;open();});
  zone.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();open();}});
  $('#choose-files').addEventListener('click',open);
  zone.addEventListener('dragover',e=>{e.preventDefault();zone.classList.add('dragover');});
  zone.addEventListener('dragleave',()=>zone.classList.remove('dragover'));
  zone.addEventListener('drop',e=>{
    e.preventDefault();zone.classList.remove('dragover');
    uploadFiles(Array.from(e.dataTransfer.files));
  });
  $('#import-by-path').addEventListener('click',async()=>{
    const path=$('#import-path').value.trim();
    if(!path){D.toast('请输入存在的本地路径',true);return;}
    try{
      const m=await D.api('/import/path',{method:'POST',json:{path}});
      D.closeModal();await D.load();await choose(m.id);
      D.toast('素材已加入工作空间');
    }catch(err){D.toast(err.message,true);}
  });
}
async function uploadFiles(files){
  if(!files||!files.length)return;
  const progress=$('#upload-progress'),bar=$('#upload-progress-bar');
  if(progress)progress.classList.remove('hidden');
  let last=null,failed=0;
  for(let i=0;i<files.length;i++){
    const file=files[i];
    try{
      last=await uploadOne(file,p=>{
        if(bar)bar.style.width=(((i+p)/files.length)*100).toFixed(1)+'%';
      });
    }catch(err){failed++;D.toast(file.name+'：'+err.message,true);}
  }
  if(failed===files.length)return;
  D.closeModal();await D.load();
  if(last)await choose(last.id);
  D.toast('已导入 '+(files.length-failed)+' 个媒体文件');
}
function uploadOne(file,onProgress){
  return new Promise((resolve,reject)=>{
    const xhr=new XMLHttpRequest();
    xhr.open('POST','/ui-api/upload',true);
    xhr.withCredentials=true;
    xhr.setRequestHeader('X-DRE-UI','1');
    xhr.setRequestHeader('X-File-Name',encodeURIComponent(file.name));
    xhr.upload.onprogress=e=>{if(e.lengthComputable)onProgress(e.loaded/e.total);};
    xhr.onerror=()=>reject(new Error('文件上传失败'));
    xhr.onload=()=>{
      let data;
      try{data=JSON.parse(xhr.responseText);}catch(_e){data=null;}
      if(xhr.status>=200&&xhr.status<300)resolve(data);
      else reject(new Error(data?.detail||'HTTP '+xhr.status));
    };
    xhr.send(file);
  });
}
function showSearch(){
  const html='<div class="modal-title">在工作台中查找</div>'+
    '<div class="form-field"><input id="search-modal-input" placeholder="输入视频或项目名称…" autofocus></div>'+
    '<div id="search-modal-results" style="max-height:50vh;overflow:auto;margin-top:12px"></div>'+
    '<div class="modal-actions">'+btn('关闭','close-modal','button-neutral')+'</div>';
  D.modal(html);
  const input=$('#search-modal-input'),out=$('#search-modal-results');
  function refresh(){
    const q=input.value.trim().toLowerCase();
    const found=S.media.filter(m=>!q||m.title.toLowerCase().includes(q)).slice(0,30);
    out.innerHTML=found.map(m=>
      '<button class="doc-option" data-action="choose" data-id="'+h(m.id)+'">'+
      '<strong>'+h(m.title)+'</strong><span>'+h(m.source)+'</span></button>'
    ).join('')||(empty('search','没有匹配项目','尝试更短的搜索词',''));
  }
  input.addEventListener('input',refresh);refresh();input.focus();
}
async function confirmReasoning(){
  const media=D.selectedMedia(),source=resolveMediaJobs().digest;
  if(!media||!source){D.toast('请先运行「开始完整分析」得到本地证据',true);return;}
  let preview;
  try{preview=await D.api('/reason/preview?source_job_id='+encodeURIComponent(source.id));}
  catch(err){D.toast(err.message,true);return;}
  if(!preview.provider?.configured){
    D.toast('请先到「模型与接入」配置推理 API',true);
    D.nav('capabilities');return;
  }
  const box='<div class="modal-title">授权 AI 深度撰写</div>'+
    '<p class="modal-sub">此步骤会把你指定的本地文字证据发送给下方服务商。原视频、图片和原始文件不会发送。</p>'+
    '<div class="modal-disclosure"><div><b>目标模型：</b>'+h(preview.provider.model)+'</div>'+
    '<div><b>服务端点：</b>'+h(preview.provider.base_url)+'</div>'+
    '<div><b>发送范围：</b>'+h(preview.scope)+'</div>'+
    '<div><b>预计输入：</b>'+Number(preview.characters).toLocaleString()+' 字符，'+
    Number(preview.segments)+' 条证据</div></div>'+
    '<label class="consent-box"><input type="checkbox" id="reason-consent">'+
    '<span>我已经了解以上数据范围，并明确授权该次视频分析使用这个推理 API。</span></label>'+
    '<div class="modal-actions">'+btn('取消','close-modal','button-neutral')+
    btn('授权并生成完整文稿','reason-submit','button-primary','sparkles')+'</div>';
  D.modal(box);
  const submit=$('[data-action="reason-submit"]');
  if(submit)submit.addEventListener('click',async()=>{
    if(!$('#reason-consent')?.checked){D.toast('请先勾选本次数据授权',true);return;}
    submit.disabled=true;
    try{
      await D.api('/reason',{method:'POST',json:{media_id:media.id,
        source_job_id:source.id,consent:true}});
      D.closeModal();await D.refreshJobs();render();
      D.toast('文稿生成任务已提交。可在任务中心查看状态。');
    }catch(err){submit.disabled=false;D.toast(err.message,true);}
  },{once:true});
}
async function start(kind){
  try{await D.startJob(kind,S.engine);render();}
  catch(err){D.toast(err.message,true);}
}
async function editEvidence(index,channel){
  const e=evidenceBundleForTab();
  if(!e.job||channel!==e.channel)return;
  const row=$('.evidence-entry[data-evidence-index="'+index+'"]');
  const source=e.items[Number(index)];
  if(!row||!source)return;
  const editor=document.createElement('div');
  editor.className='review-editor';
  editor.innerHTML='<textarea aria-label="校对转写文字">'+h(source.text||'')+'</textarea>'+
    '<div class="review-actions"><button class="button button-neutral" data-action="discard-edit">取消</button>'+
    '<button class="button button-primary" data-action="save-evidence">保存校对</button></div>';
  row.appendChild(editor);
  $('.evidence-edit',row).disabled=true;
  const textarea=$('textarea',editor);textarea.focus();
  $('[data-action="discard-edit"]',editor).addEventListener('click',()=>renderEvidence());
  $('[data-action="save-evidence"]',editor).addEventListener('click',async()=>{
    try{
      await D.api('/jobs/'+e.job.id+'/evidence',{method:'PUT',json:{
        channel:e.channel,index:Number(index),text:textarea.value
      }});
      source.text=textarea.value;
      if(!S.editedKeys)S.editedKeys=new Set();
      S.editedKeys.add(e.job.id+':'+e.channel+':'+index);
      renderEvidence();renderTimeline();D.toast('校对已保存，原始模型结果仍保留');
    }catch(err){D.toast(err.message,true);}
  });
}
async function saveProvider(e){
  e.preventDefault();
  try{
    const data=await D.api('/provider',{method:'POST',json:{
      base_url:$('#provider-base').value,
      model:$('#provider-model').value,api_key:$('#provider-key').value
    }});
    S.provider=data;
    D.toast('API 已保存。连通性与实际输出仍需运行时验证。');
    render();
  }catch(err){D.toast(err.message,true);}
}
async function saveDocument(){
  const jobId=S.activeDocument;
  if(!jobId)return;
  const textarea=$('#document-editor');
  const content=textarea?textarea.value:S.docDraft;
  try{
    await D.api('/jobs/'+jobId+'/document',{method:'PUT',json:{content}});
    if(S.results.has(jobId))S.results.get(jobId).analysis_markdown=content;
    S.docDraft=content;editingDocumentDirty=false;
    D.toast('文稿修改已保存到独立版本');render();
  }catch(err){D.toast(err.message,true);}
}
