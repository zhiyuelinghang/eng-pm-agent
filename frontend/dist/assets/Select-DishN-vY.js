import{bd as Te,x as M,r as P,Q as Je,d as ue,N as vo,C as c,bx as Co,E as gt,bD as Oo,ag as We,bE as bt,bs as pt,b2 as ho,bF as Po,bC as mt,bG as Ze,aa as le,bc as He,aI as go,bH as Ct,bI as io,K as Fe,L as Mo,B as Ne,Y as L,$ as _,W as de,aT as $o,H as De,a3 as Ce,a6 as Ve,aZ as Q,z as bo,A as xt,bJ as Pe,bK as po,T as Bo,Z as ee,aS as ke,aR as _o,aJ as Qe,bb as yt,S as wt,aQ as St,I as mo,aX as Le,bL as zt,bM as Me,bN as Rt,aF as D,ac as kt,a9 as ge,bO as xo,aG as Tt,bi as Ft,bP as It,F as Ot,bk as Pt,J as Mt,aM as $t,aN as Bt,aO as _t,aU as fo,h as Et,G as At,P as yo,a4 as wo,aV as Ht,a2 as Lt,aP as Wt,aW as Nt,bQ as Dt,bj as Vt}from"./index-CAMHUpSy.js";import{u as Eo,N as jt}from"./Suffix-DeVr0LRM.js";function So(e){return e&-e}class Ao{constructor(t,n){this.l=t,this.min=n;const l=new Array(t+1);for(let r=0;r<t+1;++r)l[r]=0;this.ft=l}add(t,n){if(n===0)return;const{l,ft:r}=this;for(t+=1;t<=l;)r[t]+=n,t+=So(t)}get(t){return this.sum(t+1)-this.sum(t)}sum(t){if(t===void 0&&(t=this.l),t<=0)return 0;const{ft:n,min:l,l:r}=this;if(t>r)throw new Error("[FinweckTree.sum]: `i` is larger than length.");let s=t*l;for(;t>0;)s+=n[t],t-=So(t);return s}getBound(t){let n=0,l=this.l;for(;l>n;){const r=Math.floor((n+l)/2),s=this.sum(r);if(s>t){l=r;continue}else if(s<t){if(n===r)return this.sum(n+1)<=t?n+1:r;n=r}else return r}return n}}let Ye;function Kt(){return typeof document>"u"?!1:(Ye===void 0&&("matchMedia"in window?Ye=window.matchMedia("(pointer:coarse)").matches:Ye=!1),Ye)}let ao;function zo(){return typeof document>"u"?1:(ao===void 0&&(ao="chrome"in window?window.devicePixelRatio:1),ao)}const Ho="VVirtualListXScroll";function Ut({columnsRef:e,renderColRef:t,renderItemWithColsRef:n}){const l=P(0),r=P(0),s=M(()=>{const p=e.value;if(p.length===0)return null;const v=new Ao(p.length,0);return p.forEach((m,F)=>{v.add(F,m.width)}),v}),a=Te(()=>{const p=s.value;return p!==null?Math.max(p.getBound(r.value)-1,0):0}),i=p=>{const v=s.value;return v!==null?v.sum(p):0},f=Te(()=>{const p=s.value;return p!==null?Math.min(p.getBound(r.value+l.value)+1,e.value.length-1):0});return Je(Ho,{startIndexRef:a,endIndexRef:f,columnsRef:e,renderColRef:t,renderItemWithColsRef:n,getLeft:i}),{listWidthRef:l,scrollLeftRef:r}}const Ro=ue({name:"VirtualListRow",props:{index:{type:Number,required:!0},item:{type:Object,required:!0}},setup(){const{startIndexRef:e,endIndexRef:t,columnsRef:n,getLeft:l,renderColRef:r,renderItemWithColsRef:s}=vo(Ho);return{startIndex:e,endIndex:t,columns:n,renderCol:r,renderItemWithCols:s,getLeft:l}},render(){const{startIndex:e,endIndex:t,columns:n,renderCol:l,renderItemWithCols:r,getLeft:s,item:a}=this;if(r!=null)return r({itemIndex:this.index,startColIndex:e,endColIndex:t,allColumns:n,item:a,getLeft:s});if(l!=null){const i=[];for(let f=e;f<=t;++f){const p=n[f];i.push(l({column:p,left:s(f),item:a}))}return i}return null}}),Gt=Ze(".v-vl",{maxHeight:"inherit",height:"100%",overflow:"auto",minWidth:"1px"},[Ze("&:not(.v-vl--show-scrollbar)",{scrollbarWidth:"none"},[Ze("&::-webkit-scrollbar, &::-webkit-scrollbar-track-piece, &::-webkit-scrollbar-thumb",{width:0,height:0,display:"none"})])]),qt=ue({name:"VirtualList",inheritAttrs:!1,props:{showScrollbar:{type:Boolean,default:!0},columns:{type:Array,default:()=>[]},renderCol:Function,renderItemWithCols:Function,items:{type:Array,default:()=>[]},itemSize:{type:Number,required:!0},itemResizable:Boolean,itemsStyle:[String,Object],visibleItemsTag:{type:[String,Object],default:"div"},visibleItemsProps:Object,ignoreItemResize:Boolean,onScroll:Function,onWheel:Function,onResize:Function,defaultScrollKey:[Number,String],defaultScrollIndex:Number,keyField:{type:String,default:"key"},paddingTop:{type:[Number,String],default:0},paddingBottom:{type:[Number,String],default:0}},setup(e){const t=Po();Gt.mount({id:"vueuc/virtual-list",head:!0,anchorMetaName:Oo,ssr:t}),We(()=>{const{defaultScrollIndex:h,defaultScrollKey:S}=e;h!=null?k({index:h}):S!=null&&k({key:S})});let n=!1,l=!1;bt(()=>{if(n=!1,!l){l=!0;return}k({top:R.value,left:a.value})}),pt(()=>{n=!0,l||(l=!0)});const r=Te(()=>{if(e.renderCol==null&&e.renderItemWithCols==null||e.columns.length===0)return;let h=0;return e.columns.forEach(S=>{h+=S.width}),h}),s=M(()=>{const h=new Map,{keyField:S}=e;return e.items.forEach((H,V)=>{h.set(H[S],V)}),h}),{scrollLeftRef:a,listWidthRef:i}=Ut({columnsRef:le(e,"columns"),renderColRef:le(e,"renderCol"),renderItemWithColsRef:le(e,"renderItemWithCols")}),f=P(null),p=P(void 0),v=new Map,m=M(()=>{const{items:h,itemSize:S,keyField:H}=e,V=new Ao(h.length,S);return h.forEach((K,Y)=>{const j=K[H],G=v.get(j);G!==void 0&&V.add(Y,G)}),V}),F=P(0),R=P(0),b=Te(()=>Math.max(m.value.getBound(R.value-ho(e.paddingTop))-1,0)),C=M(()=>{const{value:h}=p;if(h===void 0)return[];const{items:S,itemSize:H}=e,V=b.value,K=Math.min(V+Math.ceil(h/H+1),S.length-1),Y=[];for(let j=V;j<=K;++j)Y.push(S[j]);return Y}),k=(h,S)=>{if(typeof h=="number"){W(h,S,"auto");return}const{left:H,top:V,index:K,key:Y,position:j,behavior:G,debounce:q=!0}=h;if(H!==void 0||V!==void 0)W(H,V,G);else if(K!==void 0)I(K,G,q);else if(Y!==void 0){const ae=s.value.get(Y);ae!==void 0&&I(ae,G,q)}else j==="bottom"?W(0,Number.MAX_SAFE_INTEGER,G):j==="top"&&W(0,0,G)};let z,w=null;function I(h,S,H){const{value:V}=m,K=V.sum(h)+ho(e.paddingTop);if(!H)f.value.scrollTo({left:0,top:K,behavior:S});else{z=h,w!==null&&window.clearTimeout(w),w=window.setTimeout(()=>{z=void 0,w=null},16);const{scrollTop:Y,offsetHeight:j}=f.value;if(K>Y){const G=V.get(h);K+G<=Y+j||f.value.scrollTo({left:0,top:K+G-j,behavior:S})}else f.value.scrollTo({left:0,top:K,behavior:S})}}function W(h,S,H){f.value.scrollTo({left:h,top:S,behavior:H})}function N(h,S){var H,V,K;if(n||e.ignoreItemResize||oe(S.target))return;const{value:Y}=m,j=s.value.get(h),G=Y.get(j),q=(K=(V=(H=S.borderBoxSize)===null||H===void 0?void 0:H[0])===null||V===void 0?void 0:V.blockSize)!==null&&K!==void 0?K:S.contentRect.height;if(q===G)return;q-e.itemSize===0?v.delete(h):v.set(h,q-e.itemSize);const se=q-G;if(se===0)return;Y.add(j,se);const d=f.value;if(d!=null){if(z===void 0){const x=Y.sum(j);d.scrollTop>x&&d.scrollBy(0,se)}else if(j<z)d.scrollBy(0,se);else if(j===z){const x=Y.sum(j);q+x>d.scrollTop+d.offsetHeight&&d.scrollBy(0,se)}J()}F.value++}const A=!Kt();let U=!1;function X(h){var S;(S=e.onScroll)===null||S===void 0||S.call(e,h),(!A||!U)&&J()}function re(h){var S;if((S=e.onWheel)===null||S===void 0||S.call(e,h),A){const H=f.value;if(H!=null){if(h.deltaX===0&&(H.scrollTop===0&&h.deltaY<=0||H.scrollTop+H.offsetHeight>=H.scrollHeight&&h.deltaY>=0))return;h.preventDefault(),H.scrollTop+=h.deltaY/zo(),H.scrollLeft+=h.deltaX/zo(),J(),U=!0,mt(()=>{U=!1})}}}function ie(h){if(n||oe(h.target))return;if(e.renderCol==null&&e.renderItemWithCols==null){if(h.contentRect.height===p.value)return}else if(h.contentRect.height===p.value&&h.contentRect.width===i.value)return;p.value=h.contentRect.height,i.value=h.contentRect.width;const{onResize:S}=e;S!==void 0&&S(h)}function J(){const{value:h}=f;h!=null&&(R.value=h.scrollTop,a.value=h.scrollLeft)}function oe(h){let S=h;for(;S!==null;){if(S.style.display==="none")return!0;S=S.parentElement}return!1}return{listHeight:p,listStyle:{overflow:"auto"},keyToIndex:s,itemsStyle:M(()=>{const{itemResizable:h}=e,S=He(m.value.sum());return F.value,[e.itemsStyle,{boxSizing:"content-box",width:He(r.value),height:h?"":S,minHeight:h?S:"",paddingTop:He(e.paddingTop),paddingBottom:He(e.paddingBottom)}]}),visibleItemsStyle:M(()=>(F.value,{transform:`translateY(${He(m.value.sum(b.value))})`})),viewportItems:C,listElRef:f,itemsElRef:P(null),scrollTo:k,handleListResize:ie,handleListScroll:X,handleListWheel:re,handleItemResize:N}},render(){const{itemResizable:e,keyField:t,keyToIndex:n,visibleItemsTag:l}=this;return c(Co,{onResize:this.handleListResize},{default:()=>{var r,s;return c("div",gt(this.$attrs,{class:["v-vl",this.showScrollbar&&"v-vl--show-scrollbar"],onScroll:this.handleListScroll,onWheel:this.handleListWheel,ref:"listElRef"}),[this.items.length!==0?c("div",{ref:"itemsElRef",class:"v-vl-items",style:this.itemsStyle},[c(l,Object.assign({class:"v-vl-visible-items",style:this.visibleItemsStyle},this.visibleItemsProps),{default:()=>{const{renderCol:a,renderItemWithCols:i}=this;return this.viewportItems.map(f=>{const p=f[t],v=n.get(p),m=a!=null?c(Ro,{index:v,item:f}):void 0,F=i!=null?c(Ro,{index:v,item:f}):void 0,R=this.$slots.default({item:f,renderedCols:m,renderedItemWithCols:F,index:v})[0];return e?c(Co,{key:p,onResize:b=>this.handleItemResize(p,b)},{default:()=>R}):(R.key=p,R)})}})]):(s=(r=this.$slots).empty)===null||s===void 0?void 0:s.call(r)])}})}}),ye="v-hidden",Xt=Ze("[v-hidden]",{display:"none!important"}),ko=ue({name:"Overflow",props:{getCounter:Function,getTail:Function,updateCounter:Function,onUpdateCount:Function,onUpdateOverflow:Function},setup(e,{slots:t}){const n=P(null),l=P(null);function r(a){const{value:i}=n,{getCounter:f,getTail:p}=e;let v;if(f!==void 0?v=f():v=l.value,!i||!v)return;v.hasAttribute(ye)&&v.removeAttribute(ye);const{children:m}=i;if(a.showAllItemsBeforeCalculate)for(const I of m)I.hasAttribute(ye)&&I.removeAttribute(ye);const F=i.offsetWidth,R=[],b=t.tail?p==null?void 0:p():null;let C=b?b.offsetWidth:0,k=!1;const z=i.children.length-(t.tail?1:0);for(let I=0;I<z-1;++I){if(I<0)continue;const W=m[I];if(k){W.hasAttribute(ye)||W.setAttribute(ye,"");continue}else W.hasAttribute(ye)&&W.removeAttribute(ye);const N=W.offsetWidth;if(C+=N,R[I]=N,C>F){const{updateCounter:A}=e;for(let U=I;U>=0;--U){const X=z-1-U;A!==void 0?A(X):v.textContent=`${X}`;const re=v.offsetWidth;if(C-=R[U],C+re<=F||U===0){k=!0,I=U-1,b&&(I===-1?(b.style.maxWidth=`${F-re}px`,b.style.boxSizing="border-box"):b.style.maxWidth="");const{onUpdateCount:ie}=e;ie&&ie(X);break}}}}const{onUpdateOverflow:w}=e;k?w!==void 0&&w(!0):(w!==void 0&&w(!1),v.setAttribute(ye,""))}const s=Po();return Xt.mount({id:"vueuc/overflow",head:!0,anchorMetaName:Oo,ssr:s}),We(()=>r({showAllItemsBeforeCalculate:!1})),{selfRef:n,counterRef:l,sync:r}},render(){const{$slots:e}=this;return go(()=>this.sync({showAllItemsBeforeCalculate:!1})),c("div",{class:"v-overflow",ref:"selfRef"},[Ct(e,"default"),e.counter?e.counter():c("span",{style:{display:"inline-block"},ref:"counterRef"}),e.tail?e.tail():null])}});function Lo(e,t){t&&(We(()=>{const{value:n}=e;n&&io.registerHandler(n,t)}),Fe(e,(n,l)=>{l&&io.unregisterHandler(l)},{deep:!1}),Mo(()=>{const{value:n}=e;n&&io.unregisterHandler(n)}))}function To(e){switch(typeof e){case"string":return e||void 0;case"number":return String(e);default:return}}function so(e){const t=e.filter(n=>n!==void 0);if(t.length!==0)return t.length===1?t[0]:n=>{e.forEach(l=>{l&&l(n)})}}const Yt=ue({name:"Checkmark",render(){return c("svg",{xmlns:"http://www.w3.org/2000/svg",viewBox:"0 0 16 16"},c("g",{fill:"none"},c("path",{d:"M14.046 3.486a.75.75 0 0 1-.032 1.06l-7.93 7.474a.85.85 0 0 1-1.188-.022l-2.68-2.72a.75.75 0 1 1 1.068-1.053l2.234 2.267l7.468-7.038a.75.75 0 0 1 1.06.032z",fill:"currentColor"})))}}),Zt=ue({name:"Empty",render(){return c("svg",{viewBox:"0 0 28 28",fill:"none",xmlns:"http://www.w3.org/2000/svg"},c("path",{d:"M26 7.5C26 11.0899 23.0899 14 19.5 14C15.9101 14 13 11.0899 13 7.5C13 3.91015 15.9101 1 19.5 1C23.0899 1 26 3.91015 26 7.5ZM16.8536 4.14645C16.6583 3.95118 16.3417 3.95118 16.1464 4.14645C15.9512 4.34171 15.9512 4.65829 16.1464 4.85355L18.7929 7.5L16.1464 10.1464C15.9512 10.3417 15.9512 10.6583 16.1464 10.8536C16.3417 11.0488 16.6583 11.0488 16.8536 10.8536L19.5 8.20711L22.1464 10.8536C22.3417 11.0488 22.6583 11.0488 22.8536 10.8536C23.0488 10.6583 23.0488 10.3417 22.8536 10.1464L20.2071 7.5L22.8536 4.85355C23.0488 4.65829 23.0488 4.34171 22.8536 4.14645C22.6583 3.95118 22.3417 3.95118 22.1464 4.14645L19.5 6.79289L16.8536 4.14645Z",fill:"currentColor"}),c("path",{d:"M25 22.75V12.5991C24.5572 13.0765 24.053 13.4961 23.5 13.8454V16H17.5L17.3982 16.0068C17.0322 16.0565 16.75 16.3703 16.75 16.75C16.75 18.2688 15.5188 19.5 14 19.5C12.4812 19.5 11.25 18.2688 11.25 16.75L11.2432 16.6482C11.1935 16.2822 10.8797 16 10.5 16H4.5V7.25C4.5 6.2835 5.2835 5.5 6.25 5.5H12.2696C12.4146 4.97463 12.6153 4.47237 12.865 4H6.25C4.45507 4 3 5.45507 3 7.25V22.75C3 24.5449 4.45507 26 6.25 26H21.75C23.5449 26 25 24.5449 25 22.75ZM4.5 22.75V17.5H9.81597L9.85751 17.7041C10.2905 19.5919 11.9808 21 14 21L14.215 20.9947C16.2095 20.8953 17.842 19.4209 18.184 17.5H23.5V22.75C23.5 23.7165 22.7165 24.5 21.75 24.5H6.25C5.2835 24.5 4.5 23.7165 4.5 22.75Z",fill:"currentColor"}))}}),Jt=ue({props:{onFocus:Function,onBlur:Function},setup(e){return()=>c("div",{style:"width: 0; height: 0",tabindex:0,onFocus:e.onFocus,onBlur:e.onBlur})}}),Qt={iconSizeTiny:"28px",iconSizeSmall:"34px",iconSizeMedium:"40px",iconSizeLarge:"46px",iconSizeHuge:"52px"};function en(e){const{textColorDisabled:t,iconColor:n,textColor2:l,fontSizeTiny:r,fontSizeSmall:s,fontSizeMedium:a,fontSizeLarge:i,fontSizeHuge:f}=e;return Object.assign(Object.assign({},Qt),{fontSizeTiny:r,fontSizeSmall:s,fontSizeMedium:a,fontSizeLarge:i,fontSizeHuge:f,textColor:t,iconColor:n,extraTextColor:l})}const Wo={name:"Empty",common:Ne,self:en},on=L("empty",`
 display: flex;
 flex-direction: column;
 align-items: center;
 font-size: var(--n-font-size);
`,[_("icon",`
 width: var(--n-icon-size);
 height: var(--n-icon-size);
 font-size: var(--n-icon-size);
 line-height: var(--n-icon-size);
 color: var(--n-icon-color);
 transition:
 color .3s var(--n-bezier);
 `,[de("+",[_("description",`
 margin-top: 8px;
 `)])]),_("description",`
 transition: color .3s var(--n-bezier);
 color: var(--n-text-color);
 `),_("extra",`
 text-align: center;
 transition: color .3s var(--n-bezier);
 margin-top: 12px;
 color: var(--n-extra-text-color);
 `)]),tn=Object.assign(Object.assign({},Ce.props),{description:String,showDescription:{type:Boolean,default:!0},showIcon:{type:Boolean,default:!0},size:{type:String,default:"medium"},renderIcon:Function}),nn=ue({name:"Empty",props:tn,slots:Object,setup(e){const{mergedClsPrefixRef:t,inlineThemeDisabled:n,mergedComponentPropsRef:l}=De(e),r=Ce("Empty","-empty",on,Wo,e,t),{localeRef:s}=Eo("Empty"),a=M(()=>{var v,m,F;return(v=e.description)!==null&&v!==void 0?v:(F=(m=l==null?void 0:l.value)===null||m===void 0?void 0:m.Empty)===null||F===void 0?void 0:F.description}),i=M(()=>{var v,m;return((m=(v=l==null?void 0:l.value)===null||v===void 0?void 0:v.Empty)===null||m===void 0?void 0:m.renderIcon)||(()=>c(Zt,null))}),f=M(()=>{const{size:v}=e,{common:{cubicBezierEaseInOut:m},self:{[Q("iconSize",v)]:F,[Q("fontSize",v)]:R,textColor:b,iconColor:C,extraTextColor:k}}=r.value;return{"--n-icon-size":F,"--n-font-size":R,"--n-bezier":m,"--n-text-color":b,"--n-icon-color":C,"--n-extra-text-color":k}}),p=n?Ve("empty",M(()=>{let v="";const{size:m}=e;return v+=m[0],v}),f,e):void 0;return{mergedClsPrefix:t,mergedRenderIcon:i,localizedDescription:M(()=>a.value||s.value.description),cssVars:n?void 0:f,themeClass:p==null?void 0:p.themeClass,onRender:p==null?void 0:p.onRender}},render(){const{$slots:e,mergedClsPrefix:t,onRender:n}=this;return n==null||n(),c("div",{class:[`${t}-empty`,this.themeClass],style:this.cssVars},this.showIcon?c("div",{class:`${t}-empty__icon`},e.icon?e.icon():c($o,{clsPrefix:t},{default:this.mergedRenderIcon})):null,this.showDescription?c("div",{class:`${t}-empty__description`},e.default?e.default():this.localizedDescription):null,e.extra?c("div",{class:`${t}-empty__extra`},e.extra()):null)}}),ln={height:"calc(var(--n-option-height) * 7.6)",paddingTiny:"4px 0",paddingSmall:"4px 0",paddingMedium:"4px 0",paddingLarge:"4px 0",paddingHuge:"4px 0",optionPaddingTiny:"0 12px",optionPaddingSmall:"0 12px",optionPaddingMedium:"0 12px",optionPaddingLarge:"0 12px",optionPaddingHuge:"0 12px",loadingSize:"18px"};function rn(e){const{borderRadius:t,popoverColor:n,textColor3:l,dividerColor:r,textColor2:s,primaryColorPressed:a,textColorDisabled:i,primaryColor:f,opacityDisabled:p,hoverColor:v,fontSizeTiny:m,fontSizeSmall:F,fontSizeMedium:R,fontSizeLarge:b,fontSizeHuge:C,heightTiny:k,heightSmall:z,heightMedium:w,heightLarge:I,heightHuge:W}=e;return Object.assign(Object.assign({},ln),{optionFontSizeTiny:m,optionFontSizeSmall:F,optionFontSizeMedium:R,optionFontSizeLarge:b,optionFontSizeHuge:C,optionHeightTiny:k,optionHeightSmall:z,optionHeightMedium:w,optionHeightLarge:I,optionHeightHuge:W,borderRadius:t,color:n,groupHeaderTextColor:l,actionDividerColor:r,optionTextColor:s,optionTextColorPressed:a,optionTextColorDisabled:i,optionTextColorActive:f,optionOpacityDisabled:p,optionCheckColor:f,optionColorPending:v,optionColorActive:"rgba(0, 0, 0, 0)",optionColorActivePending:v,actionTextColor:s,loadingColor:f})}const No=bo({name:"InternalSelectMenu",common:Ne,peers:{Scrollbar:xt,Empty:Wo},self:rn}),Fo=ue({name:"NBaseSelectGroupHeader",props:{clsPrefix:{type:String,required:!0},tmNode:{type:Object,required:!0}},setup(){const{renderLabelRef:e,renderOptionRef:t,labelFieldRef:n,nodePropsRef:l}=vo(po);return{labelField:n,nodeProps:l,renderLabel:e,renderOption:t}},render(){const{clsPrefix:e,renderLabel:t,renderOption:n,nodeProps:l,tmNode:{rawNode:r}}=this,s=l==null?void 0:l(r),a=t?t(r,!1):Pe(r[this.labelField],r,!1),i=c("div",Object.assign({},s,{class:[`${e}-base-select-group-header`,s==null?void 0:s.class]}),a);return r.render?r.render({node:i,option:r}):n?n({node:i,option:r,selected:!1}):i}});function an(e,t){return c(Bo,{name:"fade-in-scale-up-transition"},{default:()=>e?c($o,{clsPrefix:t,class:`${t}-base-select-option__check`},{default:()=>c(Yt)}):null})}const Io=ue({name:"NBaseSelectOption",props:{clsPrefix:{type:String,required:!0},tmNode:{type:Object,required:!0}},setup(e){const{valueRef:t,pendingTmNodeRef:n,multipleRef:l,valueSetRef:r,renderLabelRef:s,renderOptionRef:a,labelFieldRef:i,valueFieldRef:f,showCheckmarkRef:p,nodePropsRef:v,handleOptionClick:m,handleOptionMouseEnter:F}=vo(po),R=Te(()=>{const{value:z}=n;return z?e.tmNode.key===z.key:!1});function b(z){const{tmNode:w}=e;w.disabled||m(z,w)}function C(z){const{tmNode:w}=e;w.disabled||F(z,w)}function k(z){const{tmNode:w}=e,{value:I}=R;w.disabled||I||F(z,w)}return{multiple:l,isGrouped:Te(()=>{const{tmNode:z}=e,{parent:w}=z;return w&&w.rawNode.type==="group"}),showCheckmark:p,nodeProps:v,isPending:R,isSelected:Te(()=>{const{value:z}=t,{value:w}=l;if(z===null)return!1;const I=e.tmNode.rawNode[f.value];if(w){const{value:W}=r;return W.has(I)}else return z===I}),labelField:i,renderLabel:s,renderOption:a,handleMouseMove:k,handleMouseEnter:C,handleClick:b}},render(){const{clsPrefix:e,tmNode:{rawNode:t},isSelected:n,isPending:l,isGrouped:r,showCheckmark:s,nodeProps:a,renderOption:i,renderLabel:f,handleClick:p,handleMouseEnter:v,handleMouseMove:m}=this,F=an(n,e),R=f?[f(t,n),s&&F]:[Pe(t[this.labelField],t,n),s&&F],b=a==null?void 0:a(t),C=c("div",Object.assign({},b,{class:[`${e}-base-select-option`,t.class,b==null?void 0:b.class,{[`${e}-base-select-option--disabled`]:t.disabled,[`${e}-base-select-option--selected`]:n,[`${e}-base-select-option--grouped`]:r,[`${e}-base-select-option--pending`]:l,[`${e}-base-select-option--show-checkmark`]:s}],style:[(b==null?void 0:b.style)||"",t.style||""],onClick:so([p,b==null?void 0:b.onClick]),onMouseenter:so([v,b==null?void 0:b.onMouseenter]),onMousemove:so([m,b==null?void 0:b.onMousemove])}),c("div",{class:`${e}-base-select-option__content`},R));return t.render?t.render({node:C,option:t,selected:n}):i?i({node:C,option:t,selected:n}):C}}),sn=L("base-select-menu",`
 line-height: 1.5;
 outline: none;
 z-index: 0;
 position: relative;
 border-radius: var(--n-border-radius);
 transition:
 background-color .3s var(--n-bezier),
 box-shadow .3s var(--n-bezier);
 background-color: var(--n-color);
`,[L("scrollbar",`
 max-height: var(--n-height);
 `),L("virtual-list",`
 max-height: var(--n-height);
 `),L("base-select-option",`
 min-height: var(--n-option-height);
 font-size: var(--n-option-font-size);
 display: flex;
 align-items: center;
 `,[_("content",`
 z-index: 1;
 white-space: nowrap;
 text-overflow: ellipsis;
 overflow: hidden;
 `)]),L("base-select-group-header",`
 min-height: var(--n-option-height);
 font-size: .93em;
 display: flex;
 align-items: center;
 `),L("base-select-menu-option-wrapper",`
 position: relative;
 width: 100%;
 `),_("loading, empty",`
 display: flex;
 padding: 12px 32px;
 flex: 1;
 justify-content: center;
 `),_("loading",`
 color: var(--n-loading-color);
 font-size: var(--n-loading-size);
 `),_("header",`
 padding: 8px var(--n-option-padding-left);
 font-size: var(--n-option-font-size);
 transition: 
 color .3s var(--n-bezier),
 border-color .3s var(--n-bezier);
 border-bottom: 1px solid var(--n-action-divider-color);
 color: var(--n-action-text-color);
 `),_("action",`
 padding: 8px var(--n-option-padding-left);
 font-size: var(--n-option-font-size);
 transition: 
 color .3s var(--n-bezier),
 border-color .3s var(--n-bezier);
 border-top: 1px solid var(--n-action-divider-color);
 color: var(--n-action-text-color);
 `),L("base-select-group-header",`
 position: relative;
 cursor: default;
 padding: var(--n-option-padding);
 color: var(--n-group-header-text-color);
 `),L("base-select-option",`
 cursor: pointer;
 position: relative;
 padding: var(--n-option-padding);
 transition:
 color .3s var(--n-bezier),
 opacity .3s var(--n-bezier);
 box-sizing: border-box;
 color: var(--n-option-text-color);
 opacity: 1;
 `,[ee("show-checkmark",`
 padding-right: calc(var(--n-option-padding-right) + 20px);
 `),de("&::before",`
 content: "";
 position: absolute;
 left: 4px;
 right: 4px;
 top: 0;
 bottom: 0;
 border-radius: var(--n-border-radius);
 transition: background-color .3s var(--n-bezier);
 `),de("&:active",`
 color: var(--n-option-text-color-pressed);
 `),ee("grouped",`
 padding-left: calc(var(--n-option-padding-left) * 1.5);
 `),ee("pending",[de("&::before",`
 background-color: var(--n-option-color-pending);
 `)]),ee("selected",`
 color: var(--n-option-text-color-active);
 `,[de("&::before",`
 background-color: var(--n-option-color-active);
 `),ee("pending",[de("&::before",`
 background-color: var(--n-option-color-active-pending);
 `)])]),ee("disabled",`
 cursor: not-allowed;
 `,[ke("selected",`
 color: var(--n-option-text-color-disabled);
 `),ee("selected",`
 opacity: var(--n-option-opacity-disabled);
 `)]),_("check",`
 font-size: 16px;
 position: absolute;
 right: calc(var(--n-option-padding-right) - 4px);
 top: calc(50% - 7px);
 color: var(--n-option-check-color);
 transition: color .3s var(--n-bezier);
 `,[_o({enterScale:"0.5"})])])]),cn=ue({name:"InternalSelectMenu",props:Object.assign(Object.assign({},Ce.props),{clsPrefix:{type:String,required:!0},scrollable:{type:Boolean,default:!0},treeMate:{type:Object,required:!0},multiple:Boolean,size:{type:String,default:"medium"},value:{type:[String,Number,Array],default:null},autoPending:Boolean,virtualScroll:{type:Boolean,default:!0},show:{type:Boolean,default:!0},labelField:{type:String,default:"label"},valueField:{type:String,default:"value"},loading:Boolean,focusable:Boolean,renderLabel:Function,renderOption:Function,nodeProps:Function,showCheckmark:{type:Boolean,default:!0},onMousedown:Function,onScroll:Function,onFocus:Function,onBlur:Function,onKeyup:Function,onKeydown:Function,onTabOut:Function,onMouseenter:Function,onMouseleave:Function,onResize:Function,resetMenuOnOptionsChange:{type:Boolean,default:!0},inlineThemeDisabled:Boolean,scrollbarProps:Object,onToggle:Function}),setup(e){const{mergedClsPrefixRef:t,mergedRtlRef:n,mergedComponentPropsRef:l}=De(e),r=mo("InternalSelectMenu",n,t),s=Ce("InternalSelectMenu","-internal-select-menu",sn,No,e,le(e,"clsPrefix")),a=P(null),i=P(null),f=P(null),p=M(()=>e.treeMate.getFlattenedNodes()),v=M(()=>zt(p.value)),m=P(null);function F(){const{treeMate:d}=e;let x=null;const{value:Z}=e;Z===null?x=d.getFirstAvailableNode():(e.multiple?x=d.getNode((Z||[])[(Z||[]).length-1]):x=d.getNode(Z),(!x||x.disabled)&&(x=d.getFirstAvailableNode())),V(x||null)}function R(){const{value:d}=m;d&&!e.treeMate.getNode(d.key)&&(m.value=null)}let b;Fe(()=>e.show,d=>{d?b=Fe(()=>e.treeMate,()=>{e.resetMenuOnOptionsChange?(e.autoPending?F():R(),go(K)):R()},{immediate:!0}):b==null||b()},{immediate:!0}),Mo(()=>{b==null||b()});const C=M(()=>ho(s.value.self[Q("optionHeight",e.size)])),k=M(()=>Me(s.value.self[Q("padding",e.size)])),z=M(()=>e.multiple&&Array.isArray(e.value)?new Set(e.value):new Set),w=M(()=>{const d=p.value;return d&&d.length===0}),I=M(()=>{var d,x;return(x=(d=l==null?void 0:l.value)===null||d===void 0?void 0:d.Select)===null||x===void 0?void 0:x.renderEmpty});function W(d){const{onToggle:x}=e;x&&x(d)}function N(d){const{onScroll:x}=e;x&&x(d)}function A(d){var x;(x=f.value)===null||x===void 0||x.sync(),N(d)}function U(){var d;(d=f.value)===null||d===void 0||d.sync()}function X(){const{value:d}=m;return d||null}function re(d,x){x.disabled||V(x,!1)}function ie(d,x){x.disabled||W(x)}function J(d){var x;Le(d,"action")||(x=e.onKeyup)===null||x===void 0||x.call(e,d)}function oe(d){var x;Le(d,"action")||(x=e.onKeydown)===null||x===void 0||x.call(e,d)}function h(d){var x;(x=e.onMousedown)===null||x===void 0||x.call(e,d),!e.focusable&&d.preventDefault()}function S(){const{value:d}=m;d&&V(d.getNext({loop:!0}),!0)}function H(){const{value:d}=m;d&&V(d.getPrev({loop:!0}),!0)}function V(d,x=!1){m.value=d,x&&K()}function K(){var d,x;const Z=m.value;if(!Z)return;const he=v.value(Z.key);he!==null&&(e.virtualScroll?(d=i.value)===null||d===void 0||d.scrollTo({index:he}):(x=f.value)===null||x===void 0||x.scrollTo({index:he,elSize:C.value}))}function Y(d){var x,Z;!((x=a.value)===null||x===void 0)&&x.contains(d.target)&&((Z=e.onFocus)===null||Z===void 0||Z.call(e,d))}function j(d){var x,Z;!((x=a.value)===null||x===void 0)&&x.contains(d.relatedTarget)||(Z=e.onBlur)===null||Z===void 0||Z.call(e,d)}Je(po,{handleOptionMouseEnter:re,handleOptionClick:ie,valueSetRef:z,pendingTmNodeRef:m,nodePropsRef:le(e,"nodeProps"),showCheckmarkRef:le(e,"showCheckmark"),multipleRef:le(e,"multiple"),valueRef:le(e,"value"),renderLabelRef:le(e,"renderLabel"),renderOptionRef:le(e,"renderOption"),labelFieldRef:le(e,"labelField"),valueFieldRef:le(e,"valueField")}),Je(Rt,a),We(()=>{const{value:d}=f;d&&d.sync()});const G=M(()=>{const{size:d}=e,{common:{cubicBezierEaseInOut:x},self:{height:Z,borderRadius:he,color:xe,groupHeaderTextColor:fe,actionDividerColor:ce,optionTextColorPressed:we,optionTextColor:be,optionTextColorDisabled:pe,optionTextColorActive:$e,optionOpacityDisabled:Be,optionCheckColor:ze,actionTextColor:Re,optionColorPending:_e,optionColorActive:Ee,loadingColor:Ae,loadingSize:Ie,optionColorActivePending:Oe,[Q("optionFontSize",d)]:ve,[Q("optionHeight",d)]:u,[Q("optionPadding",d)]:y}}=s.value;return{"--n-height":Z,"--n-action-divider-color":ce,"--n-action-text-color":Re,"--n-bezier":x,"--n-border-radius":he,"--n-color":xe,"--n-option-font-size":ve,"--n-group-header-text-color":fe,"--n-option-check-color":ze,"--n-option-color-pending":_e,"--n-option-color-active":Ee,"--n-option-color-active-pending":Oe,"--n-option-height":u,"--n-option-opacity-disabled":Be,"--n-option-text-color":be,"--n-option-text-color-active":$e,"--n-option-text-color-disabled":pe,"--n-option-text-color-pressed":we,"--n-option-padding":y,"--n-option-padding-left":Me(y,"left"),"--n-option-padding-right":Me(y,"right"),"--n-loading-color":Ae,"--n-loading-size":Ie}}),{inlineThemeDisabled:q}=e,ae=q?Ve("internal-select-menu",M(()=>e.size[0]),G,e):void 0,se={selfRef:a,next:S,prev:H,getPendingTmNode:X};return Lo(a,e.onResize),Object.assign({mergedTheme:s,mergedClsPrefix:t,rtlEnabled:r,virtualListRef:i,scrollbarRef:f,itemSize:C,padding:k,flattenedNodes:p,empty:w,mergedRenderEmpty:I,virtualListContainer(){const{value:d}=i;return d==null?void 0:d.listElRef},virtualListContent(){const{value:d}=i;return d==null?void 0:d.itemsElRef},doScroll:N,handleFocusin:Y,handleFocusout:j,handleKeyUp:J,handleKeyDown:oe,handleMouseDown:h,handleVirtualListResize:U,handleVirtualListScroll:A,cssVars:q?void 0:G,themeClass:ae==null?void 0:ae.themeClass,onRender:ae==null?void 0:ae.onRender},se)},render(){const{$slots:e,virtualScroll:t,clsPrefix:n,mergedTheme:l,themeClass:r,onRender:s}=this;return s==null||s(),c("div",{ref:"selfRef",tabindex:this.focusable?0:-1,class:[`${n}-base-select-menu`,`${n}-base-select-menu--${this.size}-size`,this.rtlEnabled&&`${n}-base-select-menu--rtl`,r,this.multiple&&`${n}-base-select-menu--multiple`],style:this.cssVars,onFocusin:this.handleFocusin,onFocusout:this.handleFocusout,onKeyup:this.handleKeyUp,onKeydown:this.handleKeyDown,onMousedown:this.handleMouseDown,onMouseenter:this.onMouseenter,onMouseleave:this.onMouseleave},Qe(e.header,a=>a&&c("div",{class:`${n}-base-select-menu__header`,"data-header":!0,key:"header"},a)),this.loading?c("div",{class:`${n}-base-select-menu__loading`},c(yt,{clsPrefix:n,strokeWidth:20})):this.empty?c("div",{class:`${n}-base-select-menu__empty`,"data-empty":!0},St(e.empty,()=>{var a;return[((a=this.mergedRenderEmpty)===null||a===void 0?void 0:a.call(this))||c(nn,{theme:l.peers.Empty,themeOverrides:l.peerOverrides.Empty,size:this.size})]})):c(wt,Object.assign({ref:"scrollbarRef",theme:l.peers.Scrollbar,themeOverrides:l.peerOverrides.Scrollbar,scrollable:this.scrollable,container:t?this.virtualListContainer:void 0,content:t?this.virtualListContent:void 0,onScroll:t?void 0:this.doScroll},this.scrollbarProps),{default:()=>t?c(qt,{ref:"virtualListRef",class:`${n}-virtual-list`,items:this.flattenedNodes,itemSize:this.itemSize,showScrollbar:!1,paddingTop:this.padding.top,paddingBottom:this.padding.bottom,onResize:this.handleVirtualListResize,onScroll:this.handleVirtualListScroll,itemResizable:!0},{default:({item:a})=>a.isGroup?c(Fo,{key:a.key,clsPrefix:n,tmNode:a}):a.ignored?null:c(Io,{clsPrefix:n,key:a.key,tmNode:a})}):c("div",{class:`${n}-base-select-menu-option-wrapper`,style:{paddingTop:this.padding.top,paddingBottom:this.padding.bottom}},this.flattenedNodes.map(a=>a.isGroup?c(Fo,{key:a.key,clsPrefix:n,tmNode:a}):c(Io,{clsPrefix:n,key:a.key,tmNode:a})))}),Qe(e.action,a=>a&&[c("div",{class:`${n}-base-select-menu__action`,"data-action":!0,key:"action"},a),c(Jt,{onFocus:this.onTabOut,key:"focus-detector"})]))}}),dn={closeIconSizeTiny:"12px",closeIconSizeSmall:"12px",closeIconSizeMedium:"14px",closeIconSizeLarge:"14px",closeSizeTiny:"16px",closeSizeSmall:"16px",closeSizeMedium:"18px",closeSizeLarge:"18px",padding:"0 7px",closeMargin:"0 0 0 4px"};function un(e){const{textColor2:t,primaryColorHover:n,primaryColorPressed:l,primaryColor:r,infoColor:s,successColor:a,warningColor:i,errorColor:f,baseColor:p,borderColor:v,opacityDisabled:m,tagColor:F,closeIconColor:R,closeIconColorHover:b,closeIconColorPressed:C,borderRadiusSmall:k,fontSizeMini:z,fontSizeTiny:w,fontSizeSmall:I,fontSizeMedium:W,heightMini:N,heightTiny:A,heightSmall:U,heightMedium:X,closeColorHover:re,closeColorPressed:ie,buttonColor2Hover:J,buttonColor2Pressed:oe,fontWeightStrong:h}=e;return Object.assign(Object.assign({},dn),{closeBorderRadius:k,heightTiny:N,heightSmall:A,heightMedium:U,heightLarge:X,borderRadius:k,opacityDisabled:m,fontSizeTiny:z,fontSizeSmall:w,fontSizeMedium:I,fontSizeLarge:W,fontWeightStrong:h,textColorCheckable:t,textColorHoverCheckable:t,textColorPressedCheckable:t,textColorChecked:p,colorCheckable:"#0000",colorHoverCheckable:J,colorPressedCheckable:oe,colorChecked:r,colorCheckedHover:n,colorCheckedPressed:l,border:`1px solid ${v}`,textColor:t,color:F,colorBordered:"rgb(250, 250, 252)",closeIconColor:R,closeIconColorHover:b,closeIconColorPressed:C,closeColorHover:re,closeColorPressed:ie,borderPrimary:`1px solid ${D(r,{alpha:.3})}`,textColorPrimary:r,colorPrimary:D(r,{alpha:.12}),colorBorderedPrimary:D(r,{alpha:.1}),closeIconColorPrimary:r,closeIconColorHoverPrimary:r,closeIconColorPressedPrimary:r,closeColorHoverPrimary:D(r,{alpha:.12}),closeColorPressedPrimary:D(r,{alpha:.18}),borderInfo:`1px solid ${D(s,{alpha:.3})}`,textColorInfo:s,colorInfo:D(s,{alpha:.12}),colorBorderedInfo:D(s,{alpha:.1}),closeIconColorInfo:s,closeIconColorHoverInfo:s,closeIconColorPressedInfo:s,closeColorHoverInfo:D(s,{alpha:.12}),closeColorPressedInfo:D(s,{alpha:.18}),borderSuccess:`1px solid ${D(a,{alpha:.3})}`,textColorSuccess:a,colorSuccess:D(a,{alpha:.12}),colorBorderedSuccess:D(a,{alpha:.1}),closeIconColorSuccess:a,closeIconColorHoverSuccess:a,closeIconColorPressedSuccess:a,closeColorHoverSuccess:D(a,{alpha:.12}),closeColorPressedSuccess:D(a,{alpha:.18}),borderWarning:`1px solid ${D(i,{alpha:.35})}`,textColorWarning:i,colorWarning:D(i,{alpha:.15}),colorBorderedWarning:D(i,{alpha:.12}),closeIconColorWarning:i,closeIconColorHoverWarning:i,closeIconColorPressedWarning:i,closeColorHoverWarning:D(i,{alpha:.12}),closeColorPressedWarning:D(i,{alpha:.18}),borderError:`1px solid ${D(f,{alpha:.23})}`,textColorError:f,colorError:D(f,{alpha:.1}),colorBorderedError:D(f,{alpha:.08}),closeIconColorError:f,closeIconColorHoverError:f,closeIconColorPressedError:f,closeColorHoverError:D(f,{alpha:.12}),closeColorPressedError:D(f,{alpha:.18})})}const hn={common:Ne,self:un},fn={color:Object,type:{type:String,default:"default"},round:Boolean,size:String,closable:Boolean,disabled:{type:Boolean,default:void 0}},vn=L("tag",`
 --n-close-margin: var(--n-close-margin-top) var(--n-close-margin-right) var(--n-close-margin-bottom) var(--n-close-margin-left);
 white-space: nowrap;
 position: relative;
 box-sizing: border-box;
 cursor: default;
 display: inline-flex;
 align-items: center;
 flex-wrap: nowrap;
 padding: var(--n-padding);
 border-radius: var(--n-border-radius);
 color: var(--n-text-color);
 background-color: var(--n-color);
 transition: 
 border-color .3s var(--n-bezier),
 background-color .3s var(--n-bezier),
 color .3s var(--n-bezier),
 box-shadow .3s var(--n-bezier),
 opacity .3s var(--n-bezier);
 line-height: 1;
 height: var(--n-height);
 font-size: var(--n-font-size);
`,[ee("strong",`
 font-weight: var(--n-font-weight-strong);
 `),_("border",`
 pointer-events: none;
 position: absolute;
 left: 0;
 right: 0;
 top: 0;
 bottom: 0;
 border-radius: inherit;
 border: var(--n-border);
 transition: border-color .3s var(--n-bezier);
 `),_("icon",`
 display: flex;
 margin: 0 4px 0 0;
 color: var(--n-text-color);
 transition: color .3s var(--n-bezier);
 font-size: var(--n-avatar-size-override);
 `),_("avatar",`
 display: flex;
 margin: 0 6px 0 0;
 `),_("close",`
 margin: var(--n-close-margin);
 transition:
 background-color .3s var(--n-bezier),
 color .3s var(--n-bezier);
 `),ee("round",`
 padding: 0 calc(var(--n-height) / 3);
 border-radius: calc(var(--n-height) / 2);
 `,[_("icon",`
 margin: 0 4px 0 calc((var(--n-height) - 8px) / -2);
 `),_("avatar",`
 margin: 0 6px 0 calc((var(--n-height) - 8px) / -2);
 `),ee("closable",`
 padding: 0 calc(var(--n-height) / 4) 0 calc(var(--n-height) / 3);
 `)]),ee("icon, avatar",[ee("round",`
 padding: 0 calc(var(--n-height) / 3) 0 calc(var(--n-height) / 2);
 `)]),ee("disabled",`
 cursor: not-allowed !important;
 opacity: var(--n-opacity-disabled);
 `),ee("checkable",`
 cursor: pointer;
 box-shadow: none;
 color: var(--n-text-color-checkable);
 background-color: var(--n-color-checkable);
 `,[ke("disabled",[de("&:hover","background-color: var(--n-color-hover-checkable);",[ke("checked","color: var(--n-text-color-hover-checkable);")]),de("&:active","background-color: var(--n-color-pressed-checkable);",[ke("checked","color: var(--n-text-color-pressed-checkable);")])]),ee("checked",`
 color: var(--n-text-color-checked);
 background-color: var(--n-color-checked);
 `,[ke("disabled",[de("&:hover","background-color: var(--n-color-checked-hover);"),de("&:active","background-color: var(--n-color-checked-pressed);")])])])]),gn=Object.assign(Object.assign(Object.assign({},Ce.props),fn),{bordered:{type:Boolean,default:void 0},checked:Boolean,checkable:Boolean,strong:Boolean,triggerClickOnClose:Boolean,onClose:[Array,Function],onMouseenter:Function,onMouseleave:Function,"onUpdate:checked":Function,onUpdateChecked:Function,internalCloseFocusable:{type:Boolean,default:!0},internalCloseIsButtonTag:{type:Boolean,default:!0},onCheckedChange:Function}),bn=Tt("n-tag"),co=ue({name:"Tag",props:gn,slots:Object,setup(e){const t=P(null),{mergedBorderedRef:n,mergedClsPrefixRef:l,inlineThemeDisabled:r,mergedRtlRef:s,mergedComponentPropsRef:a}=De(e),i=M(()=>{var C,k;return e.size||((k=(C=a==null?void 0:a.value)===null||C===void 0?void 0:C.Tag)===null||k===void 0?void 0:k.size)||"medium"}),f=Ce("Tag","-tag",vn,hn,e,l);Je(bn,{roundRef:le(e,"round")});function p(){if(!e.disabled&&e.checkable){const{checked:C,onCheckedChange:k,onUpdateChecked:z,"onUpdate:checked":w}=e;z&&z(!C),w&&w(!C),k&&k(!C)}}function v(C){if(e.triggerClickOnClose||C.stopPropagation(),!e.disabled){const{onClose:k}=e;k&&ge(k,C)}}const m={setTextContent(C){const{value:k}=t;k&&(k.textContent=C)}},F=mo("Tag",s,l),R=M(()=>{const{type:C,color:{color:k,textColor:z}={}}=e,w=i.value,{common:{cubicBezierEaseInOut:I},self:{padding:W,closeMargin:N,borderRadius:A,opacityDisabled:U,textColorCheckable:X,textColorHoverCheckable:re,textColorPressedCheckable:ie,textColorChecked:J,colorCheckable:oe,colorHoverCheckable:h,colorPressedCheckable:S,colorChecked:H,colorCheckedHover:V,colorCheckedPressed:K,closeBorderRadius:Y,fontWeightStrong:j,[Q("colorBordered",C)]:G,[Q("closeSize",w)]:q,[Q("closeIconSize",w)]:ae,[Q("fontSize",w)]:se,[Q("height",w)]:d,[Q("color",C)]:x,[Q("textColor",C)]:Z,[Q("border",C)]:he,[Q("closeIconColor",C)]:xe,[Q("closeIconColorHover",C)]:fe,[Q("closeIconColorPressed",C)]:ce,[Q("closeColorHover",C)]:we,[Q("closeColorPressed",C)]:be}}=f.value,pe=Me(N);return{"--n-font-weight-strong":j,"--n-avatar-size-override":`calc(${d} - 8px)`,"--n-bezier":I,"--n-border-radius":A,"--n-border":he,"--n-close-icon-size":ae,"--n-close-color-pressed":be,"--n-close-color-hover":we,"--n-close-border-radius":Y,"--n-close-icon-color":xe,"--n-close-icon-color-hover":fe,"--n-close-icon-color-pressed":ce,"--n-close-icon-color-disabled":xe,"--n-close-margin-top":pe.top,"--n-close-margin-right":pe.right,"--n-close-margin-bottom":pe.bottom,"--n-close-margin-left":pe.left,"--n-close-size":q,"--n-color":k||(n.value?G:x),"--n-color-checkable":oe,"--n-color-checked":H,"--n-color-checked-hover":V,"--n-color-checked-pressed":K,"--n-color-hover-checkable":h,"--n-color-pressed-checkable":S,"--n-font-size":se,"--n-height":d,"--n-opacity-disabled":U,"--n-padding":W,"--n-text-color":z||Z,"--n-text-color-checkable":X,"--n-text-color-checked":J,"--n-text-color-hover-checkable":re,"--n-text-color-pressed-checkable":ie}}),b=r?Ve("tag",M(()=>{let C="";const{type:k,color:{color:z,textColor:w}={}}=e;return C+=k[0],C+=i.value[0],z&&(C+=`a${xo(z)}`),w&&(C+=`b${xo(w)}`),n.value&&(C+="c"),C}),R,e):void 0;return Object.assign(Object.assign({},m),{rtlEnabled:F,mergedClsPrefix:l,contentRef:t,mergedBordered:n,handleClick:p,handleCloseClick:v,cssVars:r?void 0:R,themeClass:b==null?void 0:b.themeClass,onRender:b==null?void 0:b.onRender})},render(){var e,t;const{mergedClsPrefix:n,rtlEnabled:l,closable:r,color:{borderColor:s}={},round:a,onRender:i,$slots:f}=this;i==null||i();const p=Qe(f.avatar,m=>m&&c("div",{class:`${n}-tag__avatar`},m)),v=Qe(f.icon,m=>m&&c("div",{class:`${n}-tag__icon`},m));return c("div",{class:[`${n}-tag`,this.themeClass,{[`${n}-tag--rtl`]:l,[`${n}-tag--strong`]:this.strong,[`${n}-tag--disabled`]:this.disabled,[`${n}-tag--checkable`]:this.checkable,[`${n}-tag--checked`]:this.checkable&&this.checked,[`${n}-tag--round`]:a,[`${n}-tag--avatar`]:p,[`${n}-tag--icon`]:v,[`${n}-tag--closable`]:r}],style:this.cssVars,onClick:this.handleClick,onMouseenter:this.onMouseenter,onMouseleave:this.onMouseleave},v||p,c("span",{class:`${n}-tag__content`,ref:"contentRef"},(t=(e=this.$slots).default)===null||t===void 0?void 0:t.call(e)),!this.checkable&&r?c(kt,{clsPrefix:n,class:`${n}-tag__close`,disabled:this.disabled,onClick:this.handleCloseClick,focusable:this.internalCloseFocusable,round:a,isButtonTag:this.internalCloseIsButtonTag,absolute:!0}):null,!this.checkable&&this.mergedBordered?c("div",{class:`${n}-tag__border`,style:{borderColor:s}}):null)}}),pn={paddingSingle:"0 26px 0 12px",paddingMultiple:"3px 26px 0 12px",clearSize:"16px",arrowSize:"16px"};function mn(e){const{borderRadius:t,textColor2:n,textColorDisabled:l,inputColor:r,inputColorDisabled:s,primaryColor:a,primaryColorHover:i,warningColor:f,warningColorHover:p,errorColor:v,errorColorHover:m,borderColor:F,iconColor:R,iconColorDisabled:b,clearColor:C,clearColorHover:k,clearColorPressed:z,placeholderColor:w,placeholderColorDisabled:I,fontSizeTiny:W,fontSizeSmall:N,fontSizeMedium:A,fontSizeLarge:U,heightTiny:X,heightSmall:re,heightMedium:ie,heightLarge:J,fontWeight:oe}=e;return Object.assign(Object.assign({},pn),{fontSizeTiny:W,fontSizeSmall:N,fontSizeMedium:A,fontSizeLarge:U,heightTiny:X,heightSmall:re,heightMedium:ie,heightLarge:J,borderRadius:t,fontWeight:oe,textColor:n,textColorDisabled:l,placeholderColor:w,placeholderColorDisabled:I,color:r,colorDisabled:s,colorActive:r,border:`1px solid ${F}`,borderHover:`1px solid ${i}`,borderActive:`1px solid ${a}`,borderFocus:`1px solid ${i}`,boxShadowHover:"none",boxShadowActive:`0 0 0 2px ${D(a,{alpha:.2})}`,boxShadowFocus:`0 0 0 2px ${D(a,{alpha:.2})}`,caretColor:a,arrowColor:R,arrowColorDisabled:b,loadingColor:a,borderWarning:`1px solid ${f}`,borderHoverWarning:`1px solid ${p}`,borderActiveWarning:`1px solid ${f}`,borderFocusWarning:`1px solid ${p}`,boxShadowHoverWarning:"none",boxShadowActiveWarning:`0 0 0 2px ${D(f,{alpha:.2})}`,boxShadowFocusWarning:`0 0 0 2px ${D(f,{alpha:.2})}`,colorActiveWarning:r,caretColorWarning:f,borderError:`1px solid ${v}`,borderHoverError:`1px solid ${m}`,borderActiveError:`1px solid ${v}`,borderFocusError:`1px solid ${m}`,boxShadowHoverError:"none",boxShadowActiveError:`0 0 0 2px ${D(v,{alpha:.2})}`,boxShadowFocusError:`0 0 0 2px ${D(v,{alpha:.2})}`,colorActiveError:r,caretColorError:v,clearColor:C,clearColorHover:k,clearColorPressed:z})}const Do=bo({name:"InternalSelection",common:Ne,peers:{Popover:Ft},self:mn}),Cn=de([L("base-selection",`
 --n-padding-single: var(--n-padding-single-top) var(--n-padding-single-right) var(--n-padding-single-bottom) var(--n-padding-single-left);
 --n-padding-multiple: var(--n-padding-multiple-top) var(--n-padding-multiple-right) var(--n-padding-multiple-bottom) var(--n-padding-multiple-left);
 position: relative;
 z-index: auto;
 box-shadow: none;
 width: 100%;
 max-width: 100%;
 display: inline-block;
 vertical-align: bottom;
 border-radius: var(--n-border-radius);
 min-height: var(--n-height);
 line-height: 1.5;
 font-size: var(--n-font-size);
 `,[L("base-loading",`
 color: var(--n-loading-color);
 `),L("base-selection-tags","min-height: var(--n-height);"),_("border, state-border",`
 position: absolute;
 left: 0;
 right: 0;
 top: 0;
 bottom: 0;
 pointer-events: none;
 border: var(--n-border);
 border-radius: inherit;
 transition:
 box-shadow .3s var(--n-bezier),
 border-color .3s var(--n-bezier);
 `),_("state-border",`
 z-index: 1;
 border-color: #0000;
 `),L("base-suffix",`
 cursor: pointer;
 position: absolute;
 top: 50%;
 transform: translateY(-50%);
 right: 10px;
 `,[_("arrow",`
 font-size: var(--n-arrow-size);
 color: var(--n-arrow-color);
 transition: color .3s var(--n-bezier);
 `)]),L("base-selection-overlay",`
 display: flex;
 align-items: center;
 white-space: nowrap;
 pointer-events: none;
 position: absolute;
 top: 0;
 right: 0;
 bottom: 0;
 left: 0;
 padding: var(--n-padding-single);
 transition: color .3s var(--n-bezier);
 `,[_("wrapper",`
 flex-basis: 0;
 flex-grow: 1;
 overflow: hidden;
 text-overflow: ellipsis;
 `)]),L("base-selection-placeholder",`
 color: var(--n-placeholder-color);
 `,[_("inner",`
 max-width: 100%;
 overflow: hidden;
 `)]),L("base-selection-tags",`
 cursor: pointer;
 outline: none;
 box-sizing: border-box;
 position: relative;
 z-index: auto;
 display: flex;
 padding: var(--n-padding-multiple);
 flex-wrap: wrap;
 align-items: center;
 width: 100%;
 vertical-align: bottom;
 background-color: var(--n-color);
 border-radius: inherit;
 transition:
 color .3s var(--n-bezier),
 box-shadow .3s var(--n-bezier),
 background-color .3s var(--n-bezier);
 `),L("base-selection-label",`
 height: var(--n-height);
 display: inline-flex;
 width: 100%;
 vertical-align: bottom;
 cursor: pointer;
 outline: none;
 z-index: auto;
 box-sizing: border-box;
 position: relative;
 transition:
 color .3s var(--n-bezier),
 box-shadow .3s var(--n-bezier),
 background-color .3s var(--n-bezier);
 border-radius: inherit;
 background-color: var(--n-color);
 align-items: center;
 `,[L("base-selection-input",`
 font-size: inherit;
 line-height: inherit;
 outline: none;
 cursor: pointer;
 box-sizing: border-box;
 border:none;
 width: 100%;
 padding: var(--n-padding-single);
 background-color: #0000;
 color: var(--n-text-color);
 transition: color .3s var(--n-bezier);
 caret-color: var(--n-caret-color);
 `,[_("content",`
 text-overflow: ellipsis;
 overflow: hidden;
 white-space: nowrap; 
 `)]),_("render-label",`
 color: var(--n-text-color);
 `)]),ke("disabled",[de("&:hover",[_("state-border",`
 box-shadow: var(--n-box-shadow-hover);
 border: var(--n-border-hover);
 `)]),ee("focus",[_("state-border",`
 box-shadow: var(--n-box-shadow-focus);
 border: var(--n-border-focus);
 `)]),ee("active",[_("state-border",`
 box-shadow: var(--n-box-shadow-active);
 border: var(--n-border-active);
 `),L("base-selection-label","background-color: var(--n-color-active);"),L("base-selection-tags","background-color: var(--n-color-active);")])]),ee("disabled","cursor: not-allowed;",[_("arrow",`
 color: var(--n-arrow-color-disabled);
 `),L("base-selection-label",`
 cursor: not-allowed;
 background-color: var(--n-color-disabled);
 `,[L("base-selection-input",`
 cursor: not-allowed;
 color: var(--n-text-color-disabled);
 `),_("render-label",`
 color: var(--n-text-color-disabled);
 `)]),L("base-selection-tags",`
 cursor: not-allowed;
 background-color: var(--n-color-disabled);
 `),L("base-selection-placeholder",`
 cursor: not-allowed;
 color: var(--n-placeholder-color-disabled);
 `)]),L("base-selection-input-tag",`
 height: calc(var(--n-height) - 6px);
 line-height: calc(var(--n-height) - 6px);
 outline: none;
 display: none;
 position: relative;
 margin-bottom: 3px;
 max-width: 100%;
 vertical-align: bottom;
 `,[_("input",`
 font-size: inherit;
 font-family: inherit;
 min-width: 1px;
 padding: 0;
 background-color: #0000;
 outline: none;
 border: none;
 max-width: 100%;
 overflow: hidden;
 width: 1em;
 line-height: inherit;
 cursor: pointer;
 color: var(--n-text-color);
 caret-color: var(--n-caret-color);
 `),_("mirror",`
 position: absolute;
 left: 0;
 top: 0;
 white-space: pre;
 visibility: hidden;
 user-select: none;
 -webkit-user-select: none;
 opacity: 0;
 `)]),["warning","error"].map(e=>ee(`${e}-status`,[_("state-border",`border: var(--n-border-${e});`),ke("disabled",[de("&:hover",[_("state-border",`
 box-shadow: var(--n-box-shadow-hover-${e});
 border: var(--n-border-hover-${e});
 `)]),ee("active",[_("state-border",`
 box-shadow: var(--n-box-shadow-active-${e});
 border: var(--n-border-active-${e});
 `),L("base-selection-label",`background-color: var(--n-color-active-${e});`),L("base-selection-tags",`background-color: var(--n-color-active-${e});`)]),ee("focus",[_("state-border",`
 box-shadow: var(--n-box-shadow-focus-${e});
 border: var(--n-border-focus-${e});
 `)])])]))]),L("base-selection-popover",`
 margin-bottom: -3px;
 display: flex;
 flex-wrap: wrap;
 margin-right: -8px;
 `),L("base-selection-tag-wrapper",`
 max-width: 100%;
 display: inline-flex;
 padding: 0 7px 3px 0;
 `,[de("&:last-child","padding-right: 0;"),L("tag",`
 font-size: 14px;
 max-width: 100%;
 `,[_("content",`
 line-height: 1.25;
 text-overflow: ellipsis;
 overflow: hidden;
 `)])])]),xn=ue({name:"InternalSelection",props:Object.assign(Object.assign({},Ce.props),{clsPrefix:{type:String,required:!0},bordered:{type:Boolean,default:void 0},active:Boolean,pattern:{type:String,default:""},placeholder:String,selectedOption:{type:Object,default:null},selectedOptions:{type:Array,default:null},labelField:{type:String,default:"label"},valueField:{type:String,default:"value"},multiple:Boolean,filterable:Boolean,clearable:Boolean,disabled:Boolean,size:{type:String,default:"medium"},loading:Boolean,autofocus:Boolean,showArrow:{type:Boolean,default:!0},inputProps:Object,focused:Boolean,renderTag:Function,onKeydown:Function,onClick:Function,onBlur:Function,onFocus:Function,onDeleteOption:Function,maxTagCount:[String,Number],ellipsisTagPopoverProps:Object,onClear:Function,onPatternInput:Function,onPatternFocus:Function,onPatternBlur:Function,renderLabel:Function,status:String,inlineThemeDisabled:Boolean,ignoreComposition:{type:Boolean,default:!0},onResize:Function}),setup(e){const{mergedClsPrefixRef:t,mergedRtlRef:n}=De(e),l=mo("InternalSelection",n,t),r=P(null),s=P(null),a=P(null),i=P(null),f=P(null),p=P(null),v=P(null),m=P(null),F=P(null),R=P(null),b=P(!1),C=P(!1),k=P(!1),z=Ce("InternalSelection","-internal-selection",Cn,Do,e,le(e,"clsPrefix")),w=M(()=>e.clearable&&!e.disabled&&(k.value||e.active)),I=M(()=>e.selectedOption?e.renderTag?e.renderTag({option:e.selectedOption,handleClose:()=>{}}):e.renderLabel?e.renderLabel(e.selectedOption,!0):Pe(e.selectedOption[e.labelField],e.selectedOption,!0):e.placeholder),W=M(()=>{const u=e.selectedOption;if(u)return u[e.labelField]}),N=M(()=>e.multiple?!!(Array.isArray(e.selectedOptions)&&e.selectedOptions.length):e.selectedOption!==null);function A(){var u;const{value:y}=r;if(y){const{value:te}=s;te&&(te.style.width=`${y.offsetWidth}px`,e.maxTagCount!=="responsive"&&((u=F.value)===null||u===void 0||u.sync({showAllItemsBeforeCalculate:!1})))}}function U(){const{value:u}=R;u&&(u.style.display="none")}function X(){const{value:u}=R;u&&(u.style.display="inline-block")}Fe(le(e,"active"),u=>{u||U()}),Fe(le(e,"pattern"),()=>{e.multiple&&go(A)});function re(u){const{onFocus:y}=e;y&&y(u)}function ie(u){const{onBlur:y}=e;y&&y(u)}function J(u){const{onDeleteOption:y}=e;y&&y(u)}function oe(u){const{onClear:y}=e;y&&y(u)}function h(u){const{onPatternInput:y}=e;y&&y(u)}function S(u){var y;(!u.relatedTarget||!(!((y=a.value)===null||y===void 0)&&y.contains(u.relatedTarget)))&&re(u)}function H(u){var y;!((y=a.value)===null||y===void 0)&&y.contains(u.relatedTarget)||ie(u)}function V(u){oe(u)}function K(){k.value=!0}function Y(){k.value=!1}function j(u){!e.active||!e.filterable||u.target!==s.value&&u.preventDefault()}function G(u){J(u)}const q=P(!1);function ae(u){if(u.key==="Backspace"&&!q.value&&!e.pattern.length){const{selectedOptions:y}=e;y!=null&&y.length&&G(y[y.length-1])}}let se=null;function d(u){const{value:y}=r;if(y){const te=u.target.value;y.textContent=te,A()}e.ignoreComposition&&q.value?se=u:h(u)}function x(){q.value=!0}function Z(){q.value=!1,e.ignoreComposition&&h(se),se=null}function he(u){var y;C.value=!0,(y=e.onPatternFocus)===null||y===void 0||y.call(e,u)}function xe(u){var y;C.value=!1,(y=e.onPatternBlur)===null||y===void 0||y.call(e,u)}function fe(){var u,y;if(e.filterable)C.value=!1,(u=p.value)===null||u===void 0||u.blur(),(y=s.value)===null||y===void 0||y.blur();else if(e.multiple){const{value:te}=i;te==null||te.blur()}else{const{value:te}=f;te==null||te.blur()}}function ce(){var u,y,te;e.filterable?(C.value=!1,(u=p.value)===null||u===void 0||u.focus()):e.multiple?(y=i.value)===null||y===void 0||y.focus():(te=f.value)===null||te===void 0||te.focus()}function we(){const{value:u}=s;u&&(X(),u.focus())}function be(){const{value:u}=s;u&&u.blur()}function pe(u){const{value:y}=v;y&&y.setTextContent(`+${u}`)}function $e(){const{value:u}=m;return u}function Be(){return s.value}let ze=null;function Re(){ze!==null&&window.clearTimeout(ze)}function _e(){e.active||(Re(),ze=window.setTimeout(()=>{N.value&&(b.value=!0)},100))}function Ee(){Re()}function Ae(u){u||(Re(),b.value=!1)}Fe(N,u=>{u||(b.value=!1)}),We(()=>{Mt(()=>{const u=p.value;u&&(e.disabled?u.removeAttribute("tabindex"):u.tabIndex=C.value?-1:0)})}),Lo(a,e.onResize);const{inlineThemeDisabled:Ie}=e,Oe=M(()=>{const{size:u}=e,{common:{cubicBezierEaseInOut:y},self:{fontWeight:te,borderRadius:oo,color:to,placeholderColor:no,textColor:je,paddingSingle:Ke,paddingMultiple:Ue,caretColor:lo,colorDisabled:ro,textColorDisabled:Ge,placeholderColorDisabled:Se,colorActive:o,boxShadowFocus:g,boxShadowActive:T,boxShadowHover:B,border:O,borderFocus:$,borderHover:E,borderActive:ne,arrowColor:me,arrowColorDisabled:jo,loadingColor:Ko,colorActiveWarning:Uo,boxShadowFocusWarning:Go,boxShadowActiveWarning:qo,boxShadowHoverWarning:Xo,borderWarning:Yo,borderFocusWarning:Zo,borderHoverWarning:Jo,borderActiveWarning:Qo,colorActiveError:et,boxShadowFocusError:ot,boxShadowActiveError:tt,boxShadowHoverError:nt,borderError:lt,borderFocusError:rt,borderHoverError:it,borderActiveError:at,clearColor:st,clearColorHover:ct,clearColorPressed:dt,clearSize:ut,arrowSize:ht,[Q("height",u)]:ft,[Q("fontSize",u)]:vt}}=z.value,qe=Me(Ke),Xe=Me(Ue);return{"--n-bezier":y,"--n-border":O,"--n-border-active":ne,"--n-border-focus":$,"--n-border-hover":E,"--n-border-radius":oo,"--n-box-shadow-active":T,"--n-box-shadow-focus":g,"--n-box-shadow-hover":B,"--n-caret-color":lo,"--n-color":to,"--n-color-active":o,"--n-color-disabled":ro,"--n-font-size":vt,"--n-height":ft,"--n-padding-single-top":qe.top,"--n-padding-multiple-top":Xe.top,"--n-padding-single-right":qe.right,"--n-padding-multiple-right":Xe.right,"--n-padding-single-left":qe.left,"--n-padding-multiple-left":Xe.left,"--n-padding-single-bottom":qe.bottom,"--n-padding-multiple-bottom":Xe.bottom,"--n-placeholder-color":no,"--n-placeholder-color-disabled":Se,"--n-text-color":je,"--n-text-color-disabled":Ge,"--n-arrow-color":me,"--n-arrow-color-disabled":jo,"--n-loading-color":Ko,"--n-color-active-warning":Uo,"--n-box-shadow-focus-warning":Go,"--n-box-shadow-active-warning":qo,"--n-box-shadow-hover-warning":Xo,"--n-border-warning":Yo,"--n-border-focus-warning":Zo,"--n-border-hover-warning":Jo,"--n-border-active-warning":Qo,"--n-color-active-error":et,"--n-box-shadow-focus-error":ot,"--n-box-shadow-active-error":tt,"--n-box-shadow-hover-error":nt,"--n-border-error":lt,"--n-border-focus-error":rt,"--n-border-hover-error":it,"--n-border-active-error":at,"--n-clear-size":ut,"--n-clear-color":st,"--n-clear-color-hover":ct,"--n-clear-color-pressed":dt,"--n-arrow-size":ht,"--n-font-weight":te}}),ve=Ie?Ve("internal-selection",M(()=>e.size[0]),Oe,e):void 0;return{mergedTheme:z,mergedClearable:w,mergedClsPrefix:t,rtlEnabled:l,patternInputFocused:C,filterablePlaceholder:I,label:W,selected:N,showTagsPanel:b,isComposing:q,counterRef:v,counterWrapperRef:m,patternInputMirrorRef:r,patternInputRef:s,selfRef:a,multipleElRef:i,singleElRef:f,patternInputWrapperRef:p,overflowRef:F,inputTagElRef:R,handleMouseDown:j,handleFocusin:S,handleClear:V,handleMouseEnter:K,handleMouseLeave:Y,handleDeleteOption:G,handlePatternKeyDown:ae,handlePatternInputInput:d,handlePatternInputBlur:xe,handlePatternInputFocus:he,handleMouseEnterCounter:_e,handleMouseLeaveCounter:Ee,handleFocusout:H,handleCompositionEnd:Z,handleCompositionStart:x,onPopoverUpdateShow:Ae,focus:ce,focusInput:we,blur:fe,blurInput:be,updateCounter:pe,getCounter:$e,getTail:Be,renderLabel:e.renderLabel,cssVars:Ie?void 0:Oe,themeClass:ve==null?void 0:ve.themeClass,onRender:ve==null?void 0:ve.onRender}},render(){const{status:e,multiple:t,size:n,disabled:l,filterable:r,maxTagCount:s,bordered:a,clsPrefix:i,ellipsisTagPopoverProps:f,onRender:p,renderTag:v,renderLabel:m}=this;p==null||p();const F=s==="responsive",R=typeof s=="number",b=F||R,C=c(It,null,{default:()=>c(jt,{clsPrefix:i,loading:this.loading,showArrow:this.showArrow,showClear:this.mergedClearable&&this.selected,onClear:this.handleClear},{default:()=>{var z,w;return(w=(z=this.$slots).arrow)===null||w===void 0?void 0:w.call(z)}})});let k;if(t){const{labelField:z}=this,w=h=>c("div",{class:`${i}-base-selection-tag-wrapper`,key:h.value},v?v({option:h,handleClose:()=>{this.handleDeleteOption(h)}}):c(co,{size:n,closable:!h.disabled,disabled:l,onClose:()=>{this.handleDeleteOption(h)},internalCloseIsButtonTag:!1,internalCloseFocusable:!1},{default:()=>m?m(h,!0):Pe(h[z],h,!0)})),I=()=>(R?this.selectedOptions.slice(0,s):this.selectedOptions).map(w),W=r?c("div",{class:`${i}-base-selection-input-tag`,ref:"inputTagElRef",key:"__input-tag__"},c("input",Object.assign({},this.inputProps,{ref:"patternInputRef",tabindex:-1,disabled:l,value:this.pattern,autofocus:this.autofocus,class:`${i}-base-selection-input-tag__input`,onBlur:this.handlePatternInputBlur,onFocus:this.handlePatternInputFocus,onKeydown:this.handlePatternKeyDown,onInput:this.handlePatternInputInput,onCompositionstart:this.handleCompositionStart,onCompositionend:this.handleCompositionEnd})),c("span",{ref:"patternInputMirrorRef",class:`${i}-base-selection-input-tag__mirror`},this.pattern)):null,N=F?()=>c("div",{class:`${i}-base-selection-tag-wrapper`,ref:"counterWrapperRef"},c(co,{size:n,ref:"counterRef",onMouseenter:this.handleMouseEnterCounter,onMouseleave:this.handleMouseLeaveCounter,disabled:l})):void 0;let A;if(R){const h=this.selectedOptions.length-s;h>0&&(A=c("div",{class:`${i}-base-selection-tag-wrapper`,key:"__counter__"},c(co,{size:n,ref:"counterRef",onMouseenter:this.handleMouseEnterCounter,disabled:l},{default:()=>`+${h}`})))}const U=F?r?c(ko,{ref:"overflowRef",updateCounter:this.updateCounter,getCounter:this.getCounter,getTail:this.getTail,style:{width:"100%",display:"flex",overflow:"hidden"}},{default:I,counter:N,tail:()=>W}):c(ko,{ref:"overflowRef",updateCounter:this.updateCounter,getCounter:this.getCounter,style:{width:"100%",display:"flex",overflow:"hidden"}},{default:I,counter:N}):R&&A?I().concat(A):I(),X=b?()=>c("div",{class:`${i}-base-selection-popover`},F?I():this.selectedOptions.map(w)):void 0,re=b?Object.assign({show:this.showTagsPanel,trigger:"hover",overlap:!0,placement:"top",width:"trigger",onUpdateShow:this.onPopoverUpdateShow,theme:this.mergedTheme.peers.Popover,themeOverrides:this.mergedTheme.peerOverrides.Popover},f):null,J=(this.selected?!1:this.active?!this.pattern&&!this.isComposing:!0)?c("div",{class:`${i}-base-selection-placeholder ${i}-base-selection-overlay`},c("div",{class:`${i}-base-selection-placeholder__inner`},this.placeholder)):null,oe=r?c("div",{ref:"patternInputWrapperRef",class:`${i}-base-selection-tags`},U,F?null:W,C):c("div",{ref:"multipleElRef",class:`${i}-base-selection-tags`,tabindex:l?void 0:0},U,C);k=c(Ot,null,b?c(Pt,Object.assign({},re,{scrollable:!0,style:"max-height: calc(var(--v-target-height) * 6.6);"}),{trigger:()=>oe,default:X}):oe,J)}else if(r){const z=this.pattern||this.isComposing,w=this.active?!z:!this.selected,I=this.active?!1:this.selected;k=c("div",{ref:"patternInputWrapperRef",class:`${i}-base-selection-label`,title:this.patternInputFocused?void 0:To(this.label)},c("input",Object.assign({},this.inputProps,{ref:"patternInputRef",class:`${i}-base-selection-input`,value:this.active?this.pattern:"",placeholder:"",readonly:l,disabled:l,tabindex:-1,autofocus:this.autofocus,onFocus:this.handlePatternInputFocus,onBlur:this.handlePatternInputBlur,onInput:this.handlePatternInputInput,onCompositionstart:this.handleCompositionStart,onCompositionend:this.handleCompositionEnd})),I?c("div",{class:`${i}-base-selection-label__render-label ${i}-base-selection-overlay`,key:"input"},c("div",{class:`${i}-base-selection-overlay__wrapper`},v?v({option:this.selectedOption,handleClose:()=>{}}):m?m(this.selectedOption,!0):Pe(this.label,this.selectedOption,!0))):null,w?c("div",{class:`${i}-base-selection-placeholder ${i}-base-selection-overlay`,key:"placeholder"},c("div",{class:`${i}-base-selection-overlay__wrapper`},this.filterablePlaceholder)):null,C)}else k=c("div",{ref:"singleElRef",class:`${i}-base-selection-label`,tabindex:this.disabled?void 0:0},this.label!==void 0?c("div",{class:`${i}-base-selection-input`,title:To(this.label),key:"input"},c("div",{class:`${i}-base-selection-input__content`},v?v({option:this.selectedOption,handleClose:()=>{}}):m?m(this.selectedOption,!0):Pe(this.label,this.selectedOption,!0))):c("div",{class:`${i}-base-selection-placeholder ${i}-base-selection-overlay`,key:"placeholder"},c("div",{class:`${i}-base-selection-placeholder__inner`},this.placeholder)),C);return c("div",{ref:"selfRef",class:[`${i}-base-selection`,this.rtlEnabled&&`${i}-base-selection--rtl`,this.themeClass,e&&`${i}-base-selection--${e}-status`,{[`${i}-base-selection--active`]:this.active,[`${i}-base-selection--selected`]:this.selected||this.active&&this.pattern,[`${i}-base-selection--disabled`]:this.disabled,[`${i}-base-selection--multiple`]:this.multiple,[`${i}-base-selection--focus`]:this.focused}],style:this.cssVars,onClick:this.onClick,onMouseenter:this.handleMouseEnter,onMouseleave:this.handleMouseLeave,onKeydown:this.onKeydown,onFocusin:this.handleFocusin,onFocusout:this.handleFocusout,onMousedown:this.handleMouseDown},k,a?c("div",{class:`${i}-base-selection__border`}):null,a?c("div",{class:`${i}-base-selection__state-border`}):null)}});function eo(e){return e.type==="group"}function Vo(e){return e.type==="ignored"}function uo(e,t){try{return!!(1+t.toString().toLowerCase().indexOf(e.trim().toLowerCase()))}catch{return!1}}function yn(e,t){return{getIsGroup:eo,getIgnored:Vo,getKey(l){return eo(l)?l.name||l.key||"key-required":l[e]},getChildren(l){return l[t]}}}function wn(e,t,n,l){if(!t)return e;function r(s){if(!Array.isArray(s))return[];const a=[];for(const i of s)if(eo(i)){const f=r(i[l]);f.length&&a.push(Object.assign({},i,{[l]:f}))}else{if(Vo(i))continue;t(n,i)&&a.push(i)}return a}return r(e)}function Sn(e,t,n){const l=new Map;return e.forEach(r=>{eo(r)?r[n].forEach(s=>{l.set(s[t],s)}):l.set(r[t],r)}),l}function zn(e){const{boxShadow2:t}=e;return{menuBoxShadow:t}}const Rn=bo({name:"Select",common:Ne,peers:{InternalSelection:Do,InternalSelectMenu:No},self:zn}),kn=de([L("select",`
 z-index: auto;
 outline: none;
 width: 100%;
 position: relative;
 font-weight: var(--n-font-weight);
 `),L("select-menu",`
 margin: 4px 0;
 box-shadow: var(--n-menu-box-shadow);
 `,[_o({originalTransition:"background-color .3s var(--n-bezier), box-shadow .3s var(--n-bezier)"})])]),Tn=Object.assign(Object.assign({},Ce.props),{to:fo.propTo,bordered:{type:Boolean,default:void 0},clearable:Boolean,clearCreatedOptionsOnClear:{type:Boolean,default:!0},clearFilterAfterSelect:{type:Boolean,default:!0},options:{type:Array,default:()=>[]},defaultValue:{type:[String,Number,Array],default:null},keyboard:{type:Boolean,default:!0},value:[String,Number,Array],placeholder:String,menuProps:Object,multiple:Boolean,size:String,menuSize:{type:String},filterable:Boolean,disabled:{type:Boolean,default:void 0},remote:Boolean,loading:Boolean,filter:Function,placement:{type:String,default:"bottom-start"},widthMode:{type:String,default:"trigger"},tag:Boolean,onCreate:Function,fallbackOption:{type:[Function,Boolean],default:void 0},show:{type:Boolean,default:void 0},showArrow:{type:Boolean,default:!0},maxTagCount:[Number,String],ellipsisTagPopoverProps:Object,consistentMenuWidth:{type:Boolean,default:!0},virtualScroll:{type:Boolean,default:!0},labelField:{type:String,default:"label"},valueField:{type:String,default:"value"},childrenField:{type:String,default:"children"},renderLabel:Function,renderOption:Function,renderTag:Function,"onUpdate:value":[Function,Array],inputProps:Object,nodeProps:Function,ignoreComposition:{type:Boolean,default:!0},showOnFocus:Boolean,onUpdateValue:[Function,Array],onBlur:[Function,Array],onClear:[Function,Array],onFocus:[Function,Array],onScroll:[Function,Array],onSearch:[Function,Array],onUpdateShow:[Function,Array],"onUpdate:show":[Function,Array],displayDirective:{type:String,default:"show"},resetMenuOnOptionsChange:{type:Boolean,default:!0},status:String,showCheckmark:{type:Boolean,default:!0},scrollbarProps:Object,onChange:[Function,Array],items:Array}),On=ue({name:"Select",props:Tn,slots:Object,setup(e){const{mergedClsPrefixRef:t,mergedBorderedRef:n,namespaceRef:l,inlineThemeDisabled:r,mergedComponentPropsRef:s}=De(e),a=Ce("Select","-select",kn,Rn,e,t),i=P(e.defaultValue),f=le(e,"value"),p=wo(f,i),v=P(!1),m=P(""),F=Dt(e,["items","options"]),R=P([]),b=P([]),C=M(()=>b.value.concat(R.value).concat(F.value)),k=M(()=>{const{filter:o}=e;if(o)return o;const{labelField:g,valueField:T}=e;return(B,O)=>{if(!O)return!1;const $=O[g];if(typeof $=="string")return uo(B,$);const E=O[T];return typeof E=="string"?uo(B,E):typeof E=="number"?uo(B,String(E)):!1}}),z=M(()=>{if(e.remote)return F.value;{const{value:o}=C,{value:g}=m;return!g.length||!e.filterable?o:wn(o,k.value,g,e.childrenField)}}),w=M(()=>{const{valueField:o,childrenField:g}=e,T=yn(o,g);return Vt(z.value,T)}),I=M(()=>Sn(C.value,e.valueField,e.childrenField)),W=P(!1),N=wo(le(e,"show"),W),A=P(null),U=P(null),X=P(null),{localeRef:re}=Eo("Select"),ie=M(()=>{var o;return(o=e.placeholder)!==null&&o!==void 0?o:re.value.placeholder}),J=[],oe=P(new Map),h=M(()=>{const{fallbackOption:o}=e;if(o===void 0){const{labelField:g,valueField:T}=e;return B=>({[g]:String(B),[T]:B})}return o===!1?!1:g=>Object.assign(o(g),{value:g})});function S(o){const g=e.remote,{value:T}=oe,{value:B}=I,{value:O}=h,$=[];return o.forEach(E=>{if(B.has(E))$.push(B.get(E));else if(g&&T.has(E))$.push(T.get(E));else if(O){const ne=O(E);ne&&$.push(ne)}}),$}const H=M(()=>{if(e.multiple){const{value:o}=p;return Array.isArray(o)?S(o):[]}return null}),V=M(()=>{const{value:o}=p;return!e.multiple&&!Array.isArray(o)?o===null?null:S([o])[0]||null:null}),K=Ht(e,{mergedSize:o=>{var g,T;const{size:B}=e;if(B)return B;const{mergedSize:O}=o||{};if(O!=null&&O.value)return O.value;const $=(T=(g=s==null?void 0:s.value)===null||g===void 0?void 0:g.Select)===null||T===void 0?void 0:T.size;return $||"medium"}}),{mergedSizeRef:Y,mergedDisabledRef:j,mergedStatusRef:G}=K;function q(o,g){const{onChange:T,"onUpdate:value":B,onUpdateValue:O}=e,{nTriggerFormChange:$,nTriggerFormInput:E}=K;T&&ge(T,o,g),O&&ge(O,o,g),B&&ge(B,o,g),i.value=o,$(),E()}function ae(o){const{onBlur:g}=e,{nTriggerFormBlur:T}=K;g&&ge(g,o),T()}function se(){const{onClear:o}=e;o&&ge(o)}function d(o){const{onFocus:g,showOnFocus:T}=e,{nTriggerFormFocus:B}=K;g&&ge(g,o),B(),T&&fe()}function x(o){const{onSearch:g}=e;g&&ge(g,o)}function Z(o){const{onScroll:g}=e;g&&ge(g,o)}function he(){var o;const{remote:g,multiple:T}=e;if(g){const{value:B}=oe;if(T){const{valueField:O}=e;(o=H.value)===null||o===void 0||o.forEach($=>{B.set($[O],$)})}else{const O=V.value;O&&B.set(O[e.valueField],O)}}}function xe(o){const{onUpdateShow:g,"onUpdate:show":T}=e;g&&ge(g,o),T&&ge(T,o),W.value=o}function fe(){j.value||(xe(!0),W.value=!0,e.filterable&&Ue())}function ce(){xe(!1)}function we(){m.value="",b.value=J}const be=P(!1);function pe(){e.filterable&&(be.value=!0)}function $e(){e.filterable&&(be.value=!1,N.value||we())}function Be(){j.value||(N.value?e.filterable?Ue():ce():fe())}function ze(o){var g,T;!((T=(g=X.value)===null||g===void 0?void 0:g.selfRef)===null||T===void 0)&&T.contains(o.relatedTarget)||(v.value=!1,ae(o),ce())}function Re(o){d(o),v.value=!0}function _e(){v.value=!0}function Ee(o){var g;!((g=A.value)===null||g===void 0)&&g.$el.contains(o.relatedTarget)||(v.value=!1,ae(o),ce())}function Ae(){var o;(o=A.value)===null||o===void 0||o.focus(),ce()}function Ie(o){var g;N.value&&(!((g=A.value)===null||g===void 0)&&g.$el.contains(Wt(o))||ce())}function Oe(o){if(!Array.isArray(o))return[];if(h.value)return Array.from(o);{const{remote:g}=e,{value:T}=I;if(g){const{value:B}=oe;return o.filter(O=>T.has(O)||B.has(O))}else return o.filter(B=>T.has(B))}}function ve(o){u(o.rawNode)}function u(o){if(j.value)return;const{tag:g,remote:T,clearFilterAfterSelect:B,valueField:O}=e;if(g&&!T){const{value:$}=b,E=$[0]||null;if(E){const ne=R.value;ne.length?ne.push(E):R.value=[E],b.value=J}}if(T&&oe.value.set(o[O],o),e.multiple){const $=Oe(p.value),E=$.findIndex(ne=>ne===o[O]);if(~E){if($.splice(E,1),g&&!T){const ne=y(o[O]);~ne&&(R.value.splice(ne,1),B&&(m.value=""))}}else $.push(o[O]),B&&(m.value="");q($,S($))}else{if(g&&!T){const $=y(o[O]);~$?R.value=[R.value[$]]:R.value=J}Ke(),ce(),q(o[O],o)}}function y(o){return R.value.findIndex(T=>T[e.valueField]===o)}function te(o){N.value||fe();const{value:g}=o.target;m.value=g;const{tag:T,remote:B}=e;if(x(g),T&&!B){if(!g){b.value=J;return}const{onCreate:O}=e,$=O?O(g):{[e.labelField]:g,[e.valueField]:g},{valueField:E,labelField:ne}=e;F.value.some(me=>me[E]===$[E]||me[ne]===$[ne])||R.value.some(me=>me[E]===$[E]||me[ne]===$[ne])?b.value=J:b.value=[$]}}function oo(o){o.stopPropagation();const{multiple:g,tag:T,remote:B,clearCreatedOptionsOnClear:O}=e;!g&&e.filterable&&ce(),T&&!B&&O&&(R.value=J),se(),g?q([],[]):q(null,null)}function to(o){!Le(o,"action")&&!Le(o,"empty")&&!Le(o,"header")&&o.preventDefault()}function no(o){Z(o)}function je(o){var g,T,B,O,$;if(!e.keyboard){o.preventDefault();return}switch(o.key){case" ":if(e.filterable)break;o.preventDefault();case"Enter":if(!(!((g=A.value)===null||g===void 0)&&g.isComposing)){if(N.value){const E=(T=X.value)===null||T===void 0?void 0:T.getPendingTmNode();E?ve(E):e.filterable||(ce(),Ke())}else if(fe(),e.tag&&be.value){const E=b.value[0];if(E){const ne=E[e.valueField],{value:me}=p;e.multiple&&Array.isArray(me)&&me.includes(ne)||u(E)}}}o.preventDefault();break;case"ArrowUp":if(o.preventDefault(),e.loading)return;N.value&&((B=X.value)===null||B===void 0||B.prev());break;case"ArrowDown":if(o.preventDefault(),e.loading)return;N.value?(O=X.value)===null||O===void 0||O.next():fe();break;case"Escape":N.value&&(Nt(o),ce()),($=A.value)===null||$===void 0||$.focus();break}}function Ke(){var o;(o=A.value)===null||o===void 0||o.focus()}function Ue(){var o;(o=A.value)===null||o===void 0||o.focusInput()}function lo(){var o;N.value&&((o=U.value)===null||o===void 0||o.syncPosition())}he(),Fe(le(e,"options"),he);const ro={focus:()=>{var o;(o=A.value)===null||o===void 0||o.focus()},focusInput:()=>{var o;(o=A.value)===null||o===void 0||o.focusInput()},blur:()=>{var o;(o=A.value)===null||o===void 0||o.blur()},blurInput:()=>{var o;(o=A.value)===null||o===void 0||o.blurInput()}},Ge=M(()=>{const{self:{menuBoxShadow:o}}=a.value;return{"--n-menu-box-shadow":o}}),Se=r?Ve("select",void 0,Ge,e):void 0;return Object.assign(Object.assign({},ro),{mergedStatus:G,mergedClsPrefix:t,mergedBordered:n,namespace:l,treeMate:w,isMounted:Lt(),triggerRef:A,menuRef:X,pattern:m,uncontrolledShow:W,mergedShow:N,adjustedTo:fo(e),uncontrolledValue:i,mergedValue:p,followerRef:U,localizedPlaceholder:ie,selectedOption:V,selectedOptions:H,mergedSize:Y,mergedDisabled:j,focused:v,activeWithoutMenuOpen:be,inlineThemeDisabled:r,onTriggerInputFocus:pe,onTriggerInputBlur:$e,handleTriggerOrMenuResize:lo,handleMenuFocus:_e,handleMenuBlur:Ee,handleMenuTabOut:Ae,handleTriggerClick:Be,handleToggle:ve,handleDeleteOption:u,handlePatternInput:te,handleClear:oo,handleTriggerBlur:ze,handleTriggerFocus:Re,handleKeydown:je,handleMenuAfterLeave:we,handleMenuClickOutside:Ie,handleMenuScroll:no,handleMenuKeydown:je,handleMenuMousedown:to,mergedTheme:a,cssVars:r?void 0:Ge,themeClass:Se==null?void 0:Se.themeClass,onRender:Se==null?void 0:Se.onRender})},render(){return c("div",{class:`${this.mergedClsPrefix}-select`},c($t,null,{default:()=>[c(Bt,null,{default:()=>c(xn,{ref:"triggerRef",inlineThemeDisabled:this.inlineThemeDisabled,status:this.mergedStatus,inputProps:this.inputProps,clsPrefix:this.mergedClsPrefix,showArrow:this.showArrow,maxTagCount:this.maxTagCount,ellipsisTagPopoverProps:this.ellipsisTagPopoverProps,bordered:this.mergedBordered,active:this.activeWithoutMenuOpen||this.mergedShow,pattern:this.pattern,placeholder:this.localizedPlaceholder,selectedOption:this.selectedOption,selectedOptions:this.selectedOptions,multiple:this.multiple,renderTag:this.renderTag,renderLabel:this.renderLabel,filterable:this.filterable,clearable:this.clearable,disabled:this.mergedDisabled,size:this.mergedSize,theme:this.mergedTheme.peers.InternalSelection,labelField:this.labelField,valueField:this.valueField,themeOverrides:this.mergedTheme.peerOverrides.InternalSelection,loading:this.loading,focused:this.focused,onClick:this.handleTriggerClick,onDeleteOption:this.handleDeleteOption,onPatternInput:this.handlePatternInput,onClear:this.handleClear,onBlur:this.handleTriggerBlur,onFocus:this.handleTriggerFocus,onKeydown:this.handleKeydown,onPatternBlur:this.onTriggerInputBlur,onPatternFocus:this.onTriggerInputFocus,onResize:this.handleTriggerOrMenuResize,ignoreComposition:this.ignoreComposition},{arrow:()=>{var e,t;return[(t=(e=this.$slots).arrow)===null||t===void 0?void 0:t.call(e)]}})}),c(_t,{ref:"followerRef",show:this.mergedShow,to:this.adjustedTo,teleportDisabled:this.adjustedTo===fo.tdkey,containerClass:this.namespace,width:this.consistentMenuWidth?"target":void 0,minWidth:"target",placement:this.placement},{default:()=>c(Bo,{name:"fade-in-scale-up-transition",appear:this.isMounted,onAfterLeave:this.handleMenuAfterLeave},{default:()=>{var e,t,n;return this.mergedShow||this.displayDirective==="show"?((e=this.onRender)===null||e===void 0||e.call(this),Et(c(cn,Object.assign({},this.menuProps,{ref:"menuRef",onResize:this.handleTriggerOrMenuResize,inlineThemeDisabled:this.inlineThemeDisabled,virtualScroll:this.consistentMenuWidth&&this.virtualScroll,class:[`${this.mergedClsPrefix}-select-menu`,this.themeClass,(t=this.menuProps)===null||t===void 0?void 0:t.class],clsPrefix:this.mergedClsPrefix,focusable:!0,labelField:this.labelField,valueField:this.valueField,autoPending:!0,nodeProps:this.nodeProps,theme:this.mergedTheme.peers.InternalSelectMenu,themeOverrides:this.mergedTheme.peerOverrides.InternalSelectMenu,treeMate:this.treeMate,multiple:this.multiple,size:this.menuSize,renderOption:this.renderOption,renderLabel:this.renderLabel,value:this.mergedValue,style:[(n=this.menuProps)===null||n===void 0?void 0:n.style,this.cssVars],onToggle:this.handleToggle,onScroll:this.handleMenuScroll,onFocus:this.handleMenuFocus,onBlur:this.handleMenuBlur,onKeydown:this.handleMenuKeydown,onTabOut:this.handleMenuTabOut,onMousedown:this.handleMenuMousedown,show:this.mergedShow,showCheckmark:this.showCheckmark,resetMenuOnOptionsChange:this.resetMenuOnOptionsChange,scrollbarProps:this.scrollbarProps}),{empty:()=>{var l,r;return[(r=(l=this.$slots).empty)===null||r===void 0?void 0:r.call(l)]},header:()=>{var l,r;return[(r=(l=this.$slots).header)===null||r===void 0?void 0:r.call(l)]},action:()=>{var l,r;return[(r=(l=this.$slots).action)===null||r===void 0?void 0:r.call(l)]}}),this.displayDirective==="show"?[[At,this.mergedShow],[yo,this.handleMenuClickOutside,void 0,{capture:!0}]]:[[yo,this.handleMenuClickOutside,void 0,{capture:!0}]])):null}})})]}))}});export{Jt as F,On as N,qt as V,co as a,cn as b,yn as c,nn as d,Wo as e,No as i,so as m,Rn as s};
