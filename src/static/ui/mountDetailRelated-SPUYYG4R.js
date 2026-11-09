import{a as J}from"./chunk-TNIMGNQP.js";import{a as N}from"./chunk-ICFAOPRW.js";import{a as X}from"./chunk-7I6ECAHD.js";import"./chunk-N43BHK3J.js";import"./chunk-NGJBTPTB.js";import"./chunk-S4H2XSCE.js";import"./chunk-YHLPE6B7.js";import"./chunk-EMLY66FE.js";import{c as _}from"./chunk-OYSKL43U.js";import{a as U}from"./chunk-SEK5WIY4.js";import{a as D,c as s,e as $,f as h,l as P,o as H}from"./chunk-T32GLZUJ.js";import{a as E,c as R}from"./chunk-DYNF63T6.js";import{b as p}from"./chunk-SQE76S5B.js";var ve=p(E());var M=p(E());var O=p(E());var r=p(R()),ee={showMore:"Show more",showLess:"Show less",dlcs:"DLCs",empty:"No related media available.",loading:"Loading related media\u2026",altTitle:"Show alternative title",nextEpisode:"Jump to next episode",noStatus:"No Status",rate:"Rate",close:"Close"},K={card:"#27272a",text:"#fafafa",textSecondary:"#d4d4d8",textMuted:"#a1a1aa",border:"#3f3f46",link:"#818cf8",star:"#facc15",chipBackground:"rgba(24, 24, 27, 0.92)",chipText:"#ffffff",placeholder:"#3f3f46",progressTrack:"rgba(24, 24, 27, 0.6)",progressFill:"#6366f1",progressPaused:"rgba(99, 102, 241, 0.4)",rating:{lit:"#facc15",unlit:"#52525b",muted:"#a1a1aa",focusStyle:{}}};function te(e){return{...K,...e||{},rating:{...K.rating,...e?.rating||{}}}}function oe(e){return{...ee,...e||{}}}function ae(e){if(e<=768)return 3;let t=16;return Math.max(3,Math.floor((e+t)/(150+t)))}function re({value:e,label:t,scaleMax:a,palette:o,onSelect:i}){return(0,r.jsx)(X,{scaleMax:a,value:e,label:t,onSelect:i,palette:o,renderStar:l=>(0,r.jsx)(h,{style:[n.star,{color:l?o.lit:o.unlit}],children:"\u2605"})})}function ne({item:e,width:t,labels:a,palette:o,onOpen:i,onOpenLink:l,onAction:m,onRate:y,renderRating:d,renderActionIcon:x}){let g=e?.model||e;if(!g)return null;let c=(0,r.jsx)(J,{model:g,width:t,labels:a,palette:o,style:void 0,onOpen:i?()=>i(g):void 0,onOpenLink:l,onAction:m?f=>m(g,f):void 0,onRate:y?f=>y(g,f):void 0,renderRating:d,renderActionIcon:x});return(0,r.jsx)(s,{style:[n.cardWrap,{width:t},e?.active&&n.activeCard,e?.active&&{borderColor:o.link}],children:c})}function ie({section:e,columns:t,cardWidth:a,expanded:o,onToggle:i,labels:l,palette:m,onOpen:y,onOpenLink:d,onAction:x,onRate:g,renderRating:c,renderActionIcon:f,web:T=!1}){let S=e.items||[];if(!S.length)return null;let C=Math.max(t,1)*2,L=o?S:S.slice(0,C);return(0,r.jsxs)(s,{style:n.section,children:[(0,r.jsx)(h,{accessibilityRole:"header","aria-level":2,style:[n.sectionTitle,{color:m.text}],children:e.label}),(0,r.jsx)(s,{style:n.grid,children:L.map((k,W)=>(0,r.jsx)(ne,{item:k,width:a,labels:l,palette:m,onOpen:y,onOpenLink:d,onAction:x,onRate:g,renderRating:c,renderActionIcon:f},k.key||k.model?.cardKey||W))}),S.length>C?(0,r.jsx)(P,{accessibilityRole:"button",onPress:i,style:n.toggle,children:(0,r.jsx)(h,{style:[n.toggleText,{color:m.link}],children:o?l.showLess:l.showMore})}):null]})}function le({dlc:e,width:t,palette:a}){return(0,r.jsxs)(s,{style:{width:t},children:[(0,r.jsx)(s,{style:[n.steamArtwork,{width:t,backgroundColor:a.placeholder,borderColor:a.border}],children:e.image?(0,r.jsx)($,{source:{uri:e.image},style:D.absoluteFill,resizeMode:"cover",accessible:!1,accessibilityElementsHidden:!0,importantForAccessibility:"no-hide-descendants"}):(0,r.jsx)(h,{numberOfLines:2,style:[n.steamPlaceholder,{color:a.textMuted}],children:e.title})}),(0,r.jsx)(h,{numberOfLines:2,style:[n.steamTitle,{color:a.text}],children:e.title})]})}function se({dlcs:e,width:t,labels:a,palette:o,onOpenExternal:i,web:l=!1}){if(!e?.length)return null;let y=l?"100%":Math.max(120,Math.floor((t-12)/2));return(0,r.jsxs)(s,{style:n.section,children:[(0,r.jsx)(h,{accessibilityRole:"header","aria-level":2,style:[n.sectionTitle,{color:o.text}],children:a.dlcs}),(0,r.jsx)(s,{style:n.grid,children:e.map((d,x)=>(0,r.jsx)(P,{accessibilityRole:"link",accessibilityLabel:d.title,disabled:!i,onPress:()=>i?.(d.url),style:n.steamCard,children:(0,r.jsx)(le,{dlc:d,width:y,palette:o})},`${d.url}-${x}`))})]})}function j({model:e,labels:t,palette:a,status:o="ready",onOpen:i,onOpenLink:l,onOpenExternal:m,onAction:y,onRate:d,renderRating:x=re,renderActionIcon:g,web:c=!1}){let f=oe(t),T=te(a),[S,C]=(0,O.useState)(0),[L,k]=(0,O.useState)({}),{width:W}=H(),w=S||320,A=c?ae(w):w>=720?4:w>=520?3:2,Y=c?w<=600||w<=768?12:16:12,z=Math.max(96,Math.floor((w-Y*(A-1))/A)),Z=c&&W<=600?Math.min(z,108):z,F=(e?.sections||[]).filter(u=>u?.items?.length),I=e?.steamDlcs||[];return o==="loading"?(0,r.jsxs)(s,{style:n.state,children:[(0,r.jsx)(h,{style:[n.stateText,{color:T.textMuted}],children:f.loading}),(0,r.jsx)(s,{style:[n.stateBar,{backgroundColor:T.placeholder}]})]}):!F.length&&!I.length?(0,r.jsx)(s,{style:n.state,children:(0,r.jsx)(h,{style:[n.stateText,{color:T.textMuted}],children:f.empty})}):(0,r.jsxs)(s,{style:[n.root,c&&n.rootWeb],onLayout:u=>C(u.nativeEvent.layout.width),children:[F.map(u=>(0,r.jsx)(ie,{section:u,columns:A,cardWidth:Z,expanded:!!L[u.id],onToggle:()=>k(B=>({...B,[u.id]:!B[u.id]})),labels:f,palette:T,onOpen:i,onOpenLink:l,onAction:y,onRate:d,renderRating:x,renderActionIcon:g,web:c},u.id||u.label)),(0,r.jsx)(se,{dlcs:I,width:w,labels:f,palette:T,onOpenExternal:m,web:c})]})}var n=D.create({root:{gap:24,width:"100%"},rootWeb:{gap:32,marginBottom:32},section:{gap:16,width:"100%"},sectionTitle:{fontSize:20,fontWeight:"700",lineHeight:28},grid:{flexDirection:"row",flexWrap:"wrap",gap:12,alignItems:"flex-start"},activeCard:{borderWidth:2,borderRadius:10},cardWrap:{minWidth:0},toggle:{alignSelf:"flex-start",paddingVertical:2},toggleText:{fontSize:14,fontWeight:"500"},steamCard:{gap:8},steamArtwork:{aspectRatio:460/215,borderRadius:8,borderWidth:1,overflow:"hidden",alignItems:"center",justifyContent:"center"},steamPlaceholder:{paddingHorizontal:10,textAlign:"center",fontSize:12,fontWeight:"600"},steamTitle:{fontSize:13,fontWeight:"500",lineHeight:18},state:{gap:8,width:"100%"},stateText:{fontSize:13,lineHeight:19},stateBar:{height:8,width:"60%",borderRadius:4},star:{fontSize:16}});var b=p(R()),V=document.createElement("canvas");V.width=V.height=1;var v=V.getContext("2d");function de(e,t){if(!e)return t;if(/^(?:#|rgba?\()/i.test(e.trim()))return e.trim();if(!v)return t;v.clearRect(0,0,1,1),v.fillStyle=t,v.fillStyle=e,v.fillRect(0,0,1,1);let[a,o,i,l]=v.getImageData(0,0,1,1).data;return`rgba(${a}, ${o}, ${i}, ${l/255})`}function q(){let e=getComputedStyle(document.documentElement),t=(o,i)=>e.getPropertyValue(o).trim()||i,a=(o,i)=>de(t(o,i),i);return{card:a("--color-surface","#27272a"),text:a("--color-text","#fafafa"),textSecondary:a("--color-text-secondary","#d4d4d8"),textMuted:a("--color-text-muted","#a1a1aa"),border:a("--color-surface-border","#3f3f46"),link:a("--color-link","#818cf8"),star:a("--color-warning","#facc15"),chipBackground:"rgba(24, 24, 27, 0.92)",chipText:"#ffffff",placeholder:a("--color-surface-strong","#3f3f46"),progressTrack:"rgba(24, 24, 27, 0.6)",progressFill:a("--color-accent","#6366f1"),progressPaused:"rgba(99, 102, 241, 0.4)",rating:{lit:a("--color-warning","#facc15"),unlit:a("--color-surface-muted","#52525b"),muted:a("--color-text-muted","#a1a1aa"),focusStyle:{}}}}var ce=`
  [data-detail-related-root] [data-detail-related-active="true"] {
    border-radius: 10px;
    outline: 2px solid #4338ca;
    outline-offset: 0;
  }
  [data-detail-related-root] .media-card-year {
    max-height: 0;
    margin-top: 0;
    overflow: hidden;
    opacity: 0;
    color: rgba(255, 255, 255, 0.82);
    font-weight: 400;
    text-shadow: 0 1px 2px rgba(0, 0, 0, 0.9);
    transition: max-height 0.2s ease, margin-top 0.2s ease, opacity 0.2s ease;
  }
  [data-detail-related-root] .media-card:hover .media-card-year {
    max-height: 2lh;
    margin-top: 0.25rem;
    opacity: 1;
  }
  [data-detail-related-root] .media-card .media-card-visual {
    aspect-ratio: 2 / 3;
  }
  [data-detail-related-root] .media-card .media-card-poster {
    height: auto !important;
    aspect-ratio: auto !important;
  }
  [data-detail-related-root] .media-card .media-card-body {
    position: absolute;
    left: 0;
    right: 0;
    bottom: 0;
    z-index: 10;
  }
  [data-detail-related-root] .media-card-title {
    display: block;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
    -webkit-line-clamp: unset;
    line-clamp: unset;
  }
  #detail-secondary-content [data-detail-section="recommendations"] ul {
    margin-top: 0;
    margin-bottom: 0;
  }
  #detail-secondary-content [data-detail-section="recommendations"] h3 {
    line-height: 28px;
  }
`;function fe(e,t){if(t){if(t.kind==="link"){t.href&&window.location.assign(t.href);return}if(t.kind==="post"){window.htmx?.ajax("POST",t.url,{target:t.target,swap:t.swap,values:t.vals,headers:{"X-CSRFToken":e?.csrfToken||e?.actions?.csrfToken||""}});return}N(t)}}function ue(e,t){let a=e?.rating?.rateUrl;a&&window.htmx?.ajax("POST",a,{swap:"none",headers:{"X-CSRFToken":e.csrfToken||""},values:{score:t??e.rating.value,toggle:!0}})}function me({props:e}){let[t,a]=(0,M.useState)(q);return(0,M.useEffect)(()=>{let o=()=>a(q());o();let i=new MutationObserver(o);i.observe(document.documentElement,{attributes:!0,attributeFilter:["class","style"]});let l=window.matchMedia("(prefers-color-scheme: dark)");return l.addEventListener("change",o),()=>{i.disconnect(),l.removeEventListener("change",o)}},[]),(0,b.jsxs)(b.Fragment,{children:[(0,b.jsx)("style",{children:ce}),(0,b.jsx)(j,{model:e.model,labels:e.labels,palette:t,web:!0,onOpen:o=>{o?.href&&window.location.assign(o.href)},onOpenLink:o=>{o&&window.location.assign(o)},onOpenExternal:o=>{o&&window.open(o,"_blank","noopener,noreferrer")},onAction:fe,onRate:ue,renderActionIcon:o=>(0,b.jsx)(_,{spec:o.icon})})]})}function G({host:e,props:t}){return(0,b.jsx)(me,{host:e,props:t})}var Q=p(R());function Le(e,t){return U(e,(0,Q.jsx)(G,{host:e,props:t}))}export{Le as mountDetailRelated};
