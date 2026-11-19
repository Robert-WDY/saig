"use strict";

// Both map screens use the same local board, Mercator projection and camera controls.
const WuhanMap = (() => {
  const bounds = L.latLngBounds([29.89,113.62],[31.42,115.16]);
  // Hankou, Wuchang, Hanyang, East Lake and Optics Valley: where nearly every visitor stop is.
  const core = L.latLngBounds([30.475,114.185],[30.64,114.43]);
  const attribution = '市界 <a href="https://datav.aliyun.com/portal/school/atlas/area_selector">DataV</a> · © <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> · <a href="https://openfreemap.org/">OpenFreeMap</a> / <a href="https://openmaptiles.org/">OpenMapTiles</a>';
  async function readJSON(url){
    for(let attempt=0;attempt<2;attempt++){
      let res;
      try{res=await fetch(url);}catch(err){if(attempt)throw err;}
      if(res?.ok)return res.json();
      if(attempt || (res && res.status!==503))throw new Error("地图资料暂时不可用");
      await new Promise(resolve=>setTimeout(resolve,300));
    }
  }
  function smoothWheel(map, cityCenter) {
    const container=map.getContainer(), reduced=matchMedia("(prefers-reduced-motion: reduce)");
    let frame=0, active=false, target=0, cursor, anchor, previous=0, internal=false;
    function finish(){
      if (!active) return;
      cancelAnimationFrame(frame);frame=0;active=false;
      map._moveEnd(true);
      map.fire("viewreset");
    }
    function step(now){
      if(!active)return;
      const z=map.getZoom(), gap=target-z;
      const alpha=reduced.matches?1:1-Math.exp(-Math.min(48,Math.max(8,now-previous))/58);
      const next=Math.abs(gap)<.009?target:z+gap*alpha;
      previous=now;
      const offset=cursor.subtract(map.getSize().divideBy(2));
      const center=map.unproject(map.project(anchor,next).subtract(offset),next);
      // Follow Leaflet 1.9's native touch-zoom path. Hold the detailed tile level until the gesture settles.
      map._move(cityCenter(map._limitCenter(center,next,bounds),next),next,{pinch:true,round:false});
      if(next===target)finish();else frame=requestAnimationFrame(step);
    }
    function wheel(e){
      if(!map._loaded || map._animatingZoom)return;
      e.preventDefault();
      const pixels=e.deltaY*(e.deltaMode===1?16:e.deltaMode===2?container.clientHeight:1);
      if(!pixels)return;
      cursor=map.mouseEventToContainerPoint(e);anchor=map.containerPointToLatLng(cursor);
      if(!active){
        map.stop();target=map.getZoom();previous=performance.now();
      }
      target=Math.max(map.getMinZoom(),Math.min(map.getMaxZoom(),target-Math.max(-240,Math.min(240,pixels))/235));
      if(!active && target!==map.getZoom()){
        active=true;internal=true;map._moveStart(true,false);internal=false;frame=requestAnimationFrame(step);
      }
    }
    container.addEventListener("wheel",wheel,{passive:false});
    container.addEventListener("pointerdown",finish);
    container.addEventListener("touchstart",finish,{passive:true});
    container.addEventListener("keydown",finish);
    map.on("movestart",()=>{if(active&&!internal)finish();});
    map.on("unload",()=>{cancelAnimationFrame(frame);container.removeEventListener("wheel",wheel);
      container.removeEventListener("pointerdown",finish);container.removeEventListener("touchstart",finish);container.removeEventListener("keydown",finish);});
  }
  function create(id){
    const map=L.map(id,{preferCanvas:true,fadeAnimation:false,zoomSnap:0,zoomDelta:.75,minZoom:7,maxZoom:15.5,scrollWheelZoom:false,
      touchZoom:true,bounceAtZoomLimits:false,maxBounds:bounds,maxBoundsViscosity:1,worldCopyJump:false});
    map.attributionControl.setPrefix(false);
    const container=map.getContainer();container.classList.add("wuhan-board");
    const status=document.createElement("div");status.className="board-status";status.setAttribute("role","status");
    const retry=document.createElement("button");retry.type="button";retry.textContent="重新加载";retry.hidden=true;
    const value=document.createElement("span");status.append(value,retry);container.append(status);
    L.DomEvent.disableClickPropagation(status);
    let baseReady=false,baseError=false,indexReady=false,indexError=false,tileError=false,slow;
    let streets=null, outline=[];
    function cityCenter(center,zoom){
      if(!outline.length || zoom<10.5)return center;
      const p=map.project(center,0);let inside=false,best=Infinity,nearest;
      for(let i=1;i<outline.length;i++){
        const a=outline[i-1],b=outline[i];
        if((a.y>p.y)!==(b.y>p.y) && p.x<(b.x-a.x)*(p.y-a.y)/(b.y-a.y)+a.x)inside=!inside;
        const dx=b.x-a.x,dy=b.y-a.y;
        const t=Math.max(0,Math.min(1,((p.x-a.x)*dx+(p.y-a.y)*dy)/(dx*dx+dy*dy||1)));
        const x=a.x+t*dx,y=a.y+t*dy,ds=(p.x-x)**2+(p.y-y)**2;
        if(ds<best){best=ds;nearest=[x,y];}
      }
      const margin=Math.min(map.getSize().x,map.getSize().y)*.32/(2**zoom);
      return inside||best<=margin*margin?center:map.unproject(L.point(nearest),0);
    }
    map.on("moveend",()=>{
      const c=map.getCenter(),limited=cityCenter(c,map.getZoom());
      if(limited!==c)map.panTo(limited,{animate:false});
    });
    function state(){
      clearTimeout(slow);
      const detail=map.getZoom()>=11;
      const error=baseError||(detail&&(indexError||tileError));
      const loading=!baseReady || (detail&&(!indexReady||streets?.isLoading()));
      const msg=baseError?"武汉底图加载失败":error?"街区细节加载失败":!baseReady?"正在加载武汉底图…":"正在加载街区细节…";
      container.dataset.mapState=error?"error":loading?"loading":"ready";
      retry.hidden=!error;
      if(error){value.textContent=msg;status.hidden=false;}
      else if(loading){slow=setTimeout(()=>{value.textContent=msg;status.hidden=false;},160);}
      else {status.hidden=true;value.textContent="";}
    }
    const shell=L.imageOverlay("/web/atlas/wuhan-board.webp",bounds,{attribution,pane:"tilePane",zIndex:0,className:"wuhan-board-surface"});
    shell.on("load",()=>{baseReady=true;baseError=false;state();});
    shell.on("error",()=>{baseError=true;state();});shell.addTo(map);
    const LocalTiles=L.TileLayer.extend({
      // Overlap neighbours by one pixel so fractional zoom never shows hairline seams.
      _initTile(tile){L.TileLayer.prototype._initTile.call(this,tile);const s=this.getTileSize();tile.style.width=(s.x+1)+"px";tile.style.height=(s.y+1)+"px";},
      getTileUrl(coords){const key=coords.x+"-"+coords.y;
        return this.options.available.has(key)?"/web/island/"+key+".svg":L.Util.emptyImageUrl;}
    });
    async function loadIndex(){
      try{
        const index=await readJSON("/web/island/tiles.json");const available=new Set(index.tiles);
        outline=index.outline.map(ll=>map.project(L.latLng(ll),0));indexReady=true;indexError=false;
        streets=new LocalTiles("",{available,minZoom:11,maxZoom:16,minNativeZoom:12,maxNativeZoom:12,
          bounds,noWrap:true,updateWhenZooming:false,keepBuffer:1,zIndex:2,className:"wuhan-streets"});
        streets.on("loading",()=>{tileError=false;state();});
        streets.on("tileerror",()=>{tileError=true;state();});streets.on("load",state);streets.addTo(map);
      }catch{indexError=true;}state();
    }
    retry.onclick=()=>{
      if(baseError){baseReady=false;baseError=false;shell.setUrl("/web/atlas/wuhan-board.webp?retry="+Date.now());}
      if(indexError){indexError=false;loadIndex();}else if(tileError){tileError=false;streets?.redraw();}state();
    };
    L.control.scale({imperial:false,maxWidth:85,position:"bottomleft"}).addTo(map);
    const art=L.layerGroup().addTo(map);
    const artPane=map.createPane("landmarks");artPane.style.zIndex="450";artPane.style.pointerEvents="none";
    let lastBand=-1;
    function landmarkArt(){
      const z=map.getZoom(),band=z<10.7?0:z<12.4?1:2;
      container.dataset.boardScale=String(band);
      if(band===lastBand)return;lastBand=band;art.clearLayers();
      for(const [name,position,cell,minBand,size] of [
        ["黄鹤楼",[30.54694,114.29694],"tower",0,85],["木兰山",[31.103895, 114.389476],"mountain",0,92],
        ["九真山",[30.483688, 113.949607],"mountain",0,58],["清凉寨",[31.30055, 114.210498],"mountain",0,54],
        ["武汉大学",[30.54083,114.36111],"campus",1,76],["武汉长江大桥",[30.5505,114.2848],"bridge",2,88]]){
        if(band<minBand)continue;
        const width=band===0?size:Math.round(size*.87);
        const icon=L.divIcon({className:"board-model model-"+cell,iconSize:[width,width],iconAnchor:[width/2,width-4]});
        L.marker(position,{icon,pane:"landmarks",interactive:false,keyboard:false,alt:name}).addTo(art);
      }
    }
    function minimum(){
      const min=Math.min(11,map.getBoundsZoom(bounds,false,[36,36]));
      if(map.getZoom()<min)map.setZoom(min,{animate:false});
      map.setMinZoom(min);
    }
    map.on("zoomend",()=>{landmarkArt();state();});map.on("resize",minimum);
    map.fitBounds(bounds,{padding:[12,12],animate:false});minimum();map.fitBounds(core,{padding:[8,8],animate:false});smoothWheel(map,cityCenter);loadIndex();landmarkArt();state();
    return map;
  }
  function stops(card,points){
    const contract=card.contract, result=[], visits=card.audit?.stops||[], legs=card.audit?.legs||[];
    if(contract.origin && contract.origin!==visits[0]?.place)result.push({name:contract.origin,time:routeTime.exact(contract.start)+" 出发"});
    for(const stop of visits)result.push({name:stop.place,time:routeTime.stop(stop,contract),exactTime:routeTime.exact(stop.start)+"–"+routeTime.exact(stop.end)});
    if(contract.destination && contract.destination!==result[result.length-1]?.name){
      const deadline=contract.end-(contract.buffer||0);
      result.push({name:contract.destination,time:"预计 "+routeTime.arrival(card.audit.arrival,deadline)+" 到 · 最晚 "+routeTime.exact(deadline),exactTime:routeTime.exact(card.audit.arrival)});
    }
    return result.map((stop,i)=>{const p=points[stop.name];return {...stop,coords:p&&Number.isFinite(p.lat)&&Number.isFinite(p.lon)?[p.lat,p.lon]:null,
      leg:legs.find(l=>l.origin===result[i-1]?.name&&l.destination===stop.name)};});
  }
  return {create,bounds,core,stops,readJSON};
})();
