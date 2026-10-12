'use strict';/* Motion is progressive enhancement, never required for a working UI. */
(function(){
 const reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;
 const elements=Array.from(document.querySelectorAll('.rise'));
 if(!reduce&&'IntersectionObserver' in window){
  const io=new IntersectionObserver(entries=>entries.forEach(e=>{if(e.isIntersecting){e.target.classList.add('shown');io.unobserve(e.target)}}),{threshold:.12});
  elements.forEach(el=>io.observe(el));
 }else elements.forEach(el=>el.classList.add('shown'));
 let ticking=false;
 function progress(){ticking=false;const max=Math.max(1,document.documentElement.scrollHeight-innerHeight);document.querySelector('#scroll-progress')?.style.setProperty('--fraction',Math.min(100,Math.max(0,scrollY/max*100))+'%')}
 addEventListener('scroll',()=>{if(!ticking){ticking=true;requestAnimationFrame(progress)}},{passive:true});progress();
 function select(key,focus=false){
  for(const tab of document.querySelectorAll('[data-story]')){
   const active=tab.dataset.story===key;tab.classList.toggle('active',active);tab.setAttribute('aria-selected',String(active));tab.tabIndex=active?0:-1;
   if(active&&focus)tab.focus();
  }
  for(const panel of document.querySelectorAll('.story-panel'))panel.hidden=panel.id!=='story-panel-'+key;
  const idx={build:'01',evolve:'02',proof:'03'}[key];
  if(idx)document.querySelector('#story-position').textContent=idx+' / 03';
 }
 document.querySelector('.story-tabs')?.addEventListener('click',e=>{const tab=e.target.closest('[data-story]');if(tab)select(tab.dataset.story)});
 document.querySelector('.story-tabs')?.addEventListener('keydown',e=>{
  const tab=e.target.closest('[data-story]');if(!tab||!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
  e.preventDefault();const keys=['build','evolve','proof'],index=keys.indexOf(tab.dataset.story);
  select(keys[e.key==='Home'?0:e.key==='End'?2:(index+(e.key==='ArrowRight'?1:2))%3],true);
 });
 document.querySelector('#story-explore')?.addEventListener('click',()=>document.querySelector('#preview-login')?.click());
 if(!reduce&&matchMedia('(pointer:fine)').matches){
  document.addEventListener('pointermove',e=>{const card=e.target.closest('.action-card,.workspace-card,.glass-hover');if(!card)return;
   const r=card.getBoundingClientRect();card.style.setProperty('--gx',(e.clientX-r.left)+'px');card.style.setProperty('--gy',(e.clientY-r.top)+'px');
  },{passive:true});
 }
})();
