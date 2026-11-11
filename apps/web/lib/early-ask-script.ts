// The inline half of the question kept before hydration: why and how in
// lib/early-ask.ts. A plain module, so the server layout can import the string.
export const EARLY_ASK_SCRIPT = `(function(){
if(window.__adeliaEarly)return;var q=window.__adeliaEarly={};
function fld(t){return t&&t.closest?t.closest("textarea[data-early-ask]"):null}
function box(el){return el.closest("[data-early-scope]")||el.parentNode}
function min(f){return Number(f.getAttribute("data-early-min")||1)}
function keep(f,sent){var k=f.getAttribute("data-early-ask");q[k]={text:f.value,sent:sent};
var b=box(f).querySelector("[data-early-send]");if(b)b.disabled=f.value.trim().length<min(f)}
function send(f,e){e.preventDefault();e.stopImmediatePropagation();
if(f.readOnly||f.value.trim().length<min(f))return;keep(f,true);
f.readOnly=true;f.setAttribute("aria-busy","true")}
document.addEventListener("input",function(e){var f=fld(e.target);if(f&&!f.__adeliaLive)keep(f,false)},true);
document.addEventListener("keydown",function(e){var f=fld(e.target);
if(f&&!f.__adeliaLive&&e.key==="Enter"&&!e.shiftKey&&!e.isComposing)send(f,e)},true);
document.addEventListener("click",function(e){var b=e.target&&e.target.closest?e.target.closest("[data-early-send]"):null;
var f=b&&box(b).querySelector("textarea[data-early-ask]");if(f&&!f.__adeliaLive)send(f,e)},true);
document.addEventListener("submit",function(e){var f=e.target.querySelector&&e.target.querySelector("textarea[data-early-ask]");
if(f&&!f.__adeliaLive){e.preventDefault();e.stopImmediatePropagation()}},true);
})();`;
