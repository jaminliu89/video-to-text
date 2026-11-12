/* DRE Studio utilities. Zero runtime JS dependencies. */
(function () {
  'use strict';
  const paths = {
    home:'<path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/>',
    film:'<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/>',
    'file-text':'<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h8"/>',
    activity:'<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    cpu:'<rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M9 1v3m6-3v3M9 20v3m6-3v3M1 9h3m-3 6h3m16-6h3m-3 6h3"/>',
    search:'<circle cx="11" cy="11" r="7"/><path d="m20 20-4-4"/>',
    plus:'<path d="M12 5v14M5 12h14"/>',
    menu:'<path d="M4 6h16M4 12h16M4 18h16"/>',
    x:'<path d="M5 5l14 14M19 5 5 19"/>',
    upload:'<path d="M12 16V3m-5 5 5-5 5 5"/><path d="M4 16v4h16v-4"/>',
    'arrow-right':'<path d="M5 12h14m-6-6 6 6-6 6"/>',
    'chevron-right':'<path d="m9 18 6-6-6-6"/>',
    'chevron-down':'<path d="m6 9 6 6 6-6"/>',
    check:'<path d="m4 12 5 5L20 6"/>',
    'check-circle':'<circle cx="12" cy="12" r="9"/><path d="m7 12 3 3 7-7"/>',
    loader:'<path d="M12 2a10 10 0 1 1-10 10"/>',
    play:'<path d="m7 4 13 8-13 8z"/>',
    pause:'<path d="M7 4v16M17 4v16"/>',
    sparkles:'<path d="m12 3 2.4 6.6L21 12l-6.6 2.4L12 21l-2.4-6.6L3 12l6.6-2.4z"/>',
    audio:'<path d="M4 10v4M8 6v12M12 3v18M16 7v10M20 11v2"/>',
    scan:'<path d="M8 3H5a2 2 0 0 0-2 2v3m13-5h3a2 2 0 0 1 2 2v3M8 21H5a2 2 0 0 1-2-2v-3m13 5h3a2 2 0 0 0 2-2v-3M7 11h10M7 15h8"/>',
    copy:'<rect x="8" y="8" width="12" height="12" rx="2"/><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2"/>',
    download:'<path d="M12 3v13m-5-5 5 5 5-5M4 18v3h16v-3"/>',
    folder:'<path d="M3 7V5a2 2 0 0 1 2-2h5l2 3h7a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    video:'<rect x="2" y="5" width="15" height="14" rx="2"/><path d="m17 10 5-3v10l-5-3"/>',
    clock:'<circle cx="12" cy="12" r="9"/><path d="M12 7v5l4 2"/>',
    edit:'<path d="M12 20h9M4 16l11-11 4 4L8 20H4zM13 7l4 4"/>',
    save:'<path d="M4 3h14l3 3v15H3V3zM7 3v6h10V3M7 21v-8h10v8"/>',
    retry:'<path d="M20 11a8 8 0 1 0-2 6M20 4v7h-7"/>',
    refresh:'<path d="M20 11a8 8 0 1 0-2 6M20 4v7h-7"/>',
    lock:'<rect x="4" y="10" width="16" height="12" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
    cloud:'<path d="M6 19h12a4 4 0 0 0 1-8 7 7 0 0 0-14-1 5 5 0 0 0 1 9z"/>',
    alert:'<path d="m12 3 10 18H2zM12 9v5m0 4v.1"/>',
    terminal:'<rect x="3" y="3" width="18" height="18" rx="2"/><path d="m7 8 4 4-4 4m6 0h4"/>',
    info:'<circle cx="12" cy="12" r="10"/><path d="M12 11v6M12 7v.2"/>',
    more:'<circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/>',
    list:'<path d="M8 6h13M8 12h13M8 18h13M3 6h.1M3 12h.1M3 18h.1"/>',
    book:'<path d="M12 6C9 4 5 4 2 5v14c3-1 7-1 10 1 3-2 7-2 10-1V5c-3-1-7-1-10 1zM12 6v14"/>',
    arrowup:'<path d="m5 15 7-7 7 7"/>',
    trash:'<path d="M3 6h18M8 6V4h8v2M6 6l1 15h10l1-15M10 10v7M14 10v7"/>'
  };
  function icon(name, size) {
    return '<svg xmlns="http://www.w3.org/2000/svg" width="' + (size||18) + '" height="' +
      (size||18) + '" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
      (paths[name]||paths.info) + '</svg>';
  }
  function h(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, function (m) {
      return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[m];
    });
  }
  const state = {
    view: 'home', media: [], jobs: [], caps: {}, provider: {}, selected: null,
    results: new Map(), currentTab: 'segments', query: '', time: 0,
    duration: 0, docMode: 'read', docDraft: '', activeDocument: null, editing: null,
    engine: 'auto', loaded: false
  };
  const $ = function (s, root) { return (root||document).querySelector(s); };
  const $$ = function (s, root) { return Array.from((root||document).querySelectorAll(s)); };
  function formatTime(n) {
    n = Math.max(0, Math.floor(Number(n)||0));
    const parts = [Math.floor(n/3600), Math.floor(n/60)%60, n%60];
    return parts[0] ? parts.map(x=>String(x).padStart(2,'0')).join(':') :
      parts.slice(1).map(x=>String(x).padStart(2,'0')).join(':');
  }
  function formatSize(bytes) {
    let n = Number(bytes||0);
    for (const u of ['B','KB','MB','GB','TB']) {
      if (n < 1024) return (u==='B'?Math.round(n):n.toFixed(1))+' '+u;
      n/=1024;
    }
    return n.toFixed(1)+' PB';
  }
  function fmtDate(value) {
    if (!value) return '—';
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return '—';
    return new Intl.DateTimeFormat('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(d);
  }
  function status(stateName) {
    return ({done:['完成','success'],running:['正在处理','running'],
      queued:['等待处理','warning'],error:['失败','error'],
      interrupted:['已中断','error'],cancelled:['已取消','subtle']})[stateName]||[stateName||'未开始','subtle'];
  }
  function pill(label, cls) {
    return '<span class="pill '+h(cls||'')+'">'+h(label)+'</span>';
  }
  function toast(message, error) {
    const parent=$('#toast-stack'), node=document.createElement('div');
    node.className='toast'+(error?' error':'');
    node.innerHTML=icon(error?'alert':'check-circle',16)+'<span>'+h(message)+'</span>';
    parent.appendChild(node);
    setTimeout(function () { node.remove(); }, 4600);
  }
  function modal(content, wide) {
    const root=$('#modal');
    root.innerHTML='<div class="modal-box'+(wide?' modal-wide':'')+'" role="dialog" aria-modal="true">'+content+'</div>';
    root.onclick=function (e) { if(e.target===root)closeModal(); };
    const first=$('input,button',root); if(first)first.focus();
  }
  function closeModal() { $('#modal').innerHTML=''; }
  async function api(path, opts) {
    opts=opts||{};
    const options={method:opts.method||'GET',credentials:'same-origin',headers:{}};
    if(options.method!=='GET' && options.method!=='HEAD')options.headers['X-DRE-UI']='1';
    if(opts.json!==undefined) {
      options.headers['Content-Type']='application/json';
      options.body=JSON.stringify(opts.json);
    }
    if(opts.body!==undefined)options.body=opts.body;
    const res=await fetch('/ui-api'+path,options);
    if(!res.ok) {
      let error;
      try { error=(await res.json()).detail; } catch(_e) { error='请求失败 '+res.status; }
      throw new Error(typeof error==='string'?error:'请求失败 '+res.status);
    }
    if(opts.raw)return res;
    return res.json();
  }
  function selectedMedia() { return state.media.find(m=>m.id===state.selected)||null; }
  function jobsFor(mediaId) { return state.jobs.filter(j=>j.media_id===mediaId); }
  function latest(mediaId, kind, doneOnly) {
    return jobsFor(mediaId).find(j=>j.kind===kind && (!doneOnly || j.state==='done'))||null;
  }
  function countJob(stateName) {return state.jobs.filter(j=>j.state===stateName).length;}
  async function load() {
    const [boot,library,jobs] = await Promise.all([
      api('/bootstrap'),api('/library'),api('/jobs')
    ]);
    state.caps=boot.capabilities||{};
    state.provider=boot.provider||{};
    state.media=library.media||[];
    state.jobs=jobs.jobs||[];
    if(!state.selected || !selectedMedia())state.selected=state.media[0]?.id||null;
    state.loaded=true;
    $('#sidebar-engine').textContent=(state.caps.engines||[]).some(e=>e.available&&e.engine!=='minutes')?'可用':'未配置';
  }
  async function refreshJobs() {
    const data=await api('/jobs');
    const next=data.jobs||[];
    const signature=arr=>arr.map(j=>j.id+':'+j.state).join(';');
    const changed=signature(next)!==signature(state.jobs);
    state.jobs=next;
    return changed;
  }
  async function getResult(jobId, force) {
    if(!jobId)return null;
    if(!force && state.results.has(jobId))return state.results.get(jobId);
    const res=await api('/jobs/'+encodeURIComponent(jobId)+'/result');
    state.results.set(jobId,res.data);
    return res.data;
  }
  async function loadMediaResults() {
    const media=selectedMedia();
    if(!media)return;
    const types=['digest','transcribe','ocr','storyboard','reason','distill'];
    await Promise.all(types.map(async kind=>{
      const job=latest(media.id,kind,true);
      if(job&&!state.results.has(job.id)) {
        try {await getResult(job.id);}catch(_e){}
      }
    }));
  }
  async function startJob(kind,engine) {
    const media=selectedMedia();
    if(!media)throw new Error('请先导入素材');
    const job=await api('/jobs',{method:'POST',json:{
      media_id:media.id,kind:kind,engine:engine||state.engine
    }});
    state.jobs.unshift(job);
    toast('已提交到本地任务队列');
    return job;
  }
  async function exportJob(jobId, format) {
    const res=await api('/jobs/'+encodeURIComponent(jobId)+'/export?format='+encodeURIComponent(format),{raw:true});
    const blob=await res.blob(), url=URL.createObjectURL(blob);
    const a=document.createElement('a');
    a.href=url;a.download='dre-'+jobId+'.'+format;
    document.body.appendChild(a);a.click();a.remove();
    setTimeout(()=>URL.revokeObjectURL(url),5000);
  }
  function renderStaticIcons() {
    $$('[data-icon]').forEach(el=>{el.innerHTML=icon(el.dataset.icon,el.dataset.size?Number(el.dataset.size):18);});
  }
  function nav(view) {
    state.view=view;
    $$('.nav-button').forEach(btn=>btn.classList.toggle('active',btn.dataset.view===view));
    $('#page-crumb').textContent={
      home:'空间总览',studio:'分析工作台',documents:'文稿与交付',
      jobs:'任务中心',capabilities:'模型与接入'
    }[view]||view;
    document.body.classList.remove('menu-open');
    window.location.hash='#'+view;
    if(window.DRE.render)window.DRE.render();
  }
  async function copy(text) {
    try {await navigator.clipboard.writeText(text);toast('已复制到剪贴板');}
    catch(_e){toast('剪贴板不可用',true);}
  }
  window.DRE={icon,h,state,$,$$,api,toast,modal,closeModal,formatTime,formatSize,
    fmtDate,status,pill,selectedMedia,jobsFor,latest,countJob,load,refreshJobs,
    loadMediaResults,getResult,startJob,exportJob,renderStaticIcons,nav,copy};
})();
