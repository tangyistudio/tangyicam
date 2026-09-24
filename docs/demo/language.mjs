const menu=document.querySelector('.language-menu');
// Native links remain usable without JavaScript. Preserve the current section
// when switching full static pages; a new page starts a fresh practice take.
for(const link of menu.querySelectorAll('a'))link.addEventListener('click',()=>{
  const url=new URL(link.href);url.hash=location.hash;link.href=url.href;
});
document.addEventListener('click',event=>{if(!menu.contains(event.target))menu.open=false;});
menu.addEventListener('keydown',event=>{if(event.key==='Escape'){menu.open=false;menu.querySelector('summary').focus();}});
const nav=document.querySelector('.nav');
new ResizeObserver(()=>document.documentElement.style.setProperty('--nav-clearance',Math.ceil(nav.getBoundingClientRect().height+20)+'px')).observe(nav);
