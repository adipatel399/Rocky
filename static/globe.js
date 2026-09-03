/* JARVIS globe — realistic, always-on Earth (globe.gl + three.js).
   Photoreal blue-marble surface, topographic bump, drifting cloud layer, star
   field, and a fly-to Geospatial Intelligence Layer with live data cards. */
"use strict";

const GlobeStage = (() => {
  const IMG = "/static/vendor/img/";
  let world = null, canvas = null, labelEl = null, cardEl = null, ready = false;
  let clouds = null;

  function el(tag, cls, html) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (html != null) e.innerHTML = html;
    return e;
  }

  async function init() {
    canvas = document.getElementById("globe-canvas");
    labelEl = document.getElementById("globe-label");
    cardEl = document.getElementById("geo-card");

    world = Globe()(canvas)
      .backgroundColor("rgba(0,0,0,0)")
      .backgroundImageUrl(IMG + "night-sky.png")
      .globeImageUrl(IMG + "earth-blue-marble.jpg")
      .bumpImageUrl(IMG + "earth-topology.png")
      .showAtmosphere(true)
      .atmosphereColor("#5db7ff")
      .atmosphereAltitude(0.16)
      .htmlElementsData([])
      .htmlElement(pinElement)
      .htmlAltitude(0.02)
      .ringsData([])
      .ringColor(() => "rgba(255,190,80,0.65)")
      .ringMaxRadius(6)
      .ringPropagationSpeed(3)
      .ringRepeatPeriod(1000);

    const controls = world.controls();
    controls.autoRotate = true;
    controls.autoRotateSpeed = 0.28;
    controls.enableZoom = true;
    controls.enableDamping = true;
    controls.dampingFactor = 0.1;
    controls.minDistance = 180;
    controls.maxDistance = 600;

    world.pointOfView({ lat: 20, lng: 30, altitude: 2.4 }, 0);
    addClouds();
    resize();
    window.addEventListener("resize", resize);
    ready = true;
  }

  function addClouds() {
    try {
      const R = world.getGlobeRadius();
      const geo = new THREE.SphereGeometry(R * 1.015, 64, 64);
      const tex = new THREE.TextureLoader().load(IMG + "clouds.png");
      const mat = new THREE.MeshPhongMaterial({
        map: tex, transparent: true, opacity: 0.38, depthWrite: false,
      });
      clouds = new THREE.Mesh(geo, mat);
      world.scene().add(clouds);
      (function drift() {
        if (clouds) clouds.rotation.y += 0.00028;
        requestAnimationFrame(drift);
      })();
    } catch (e) { /* clouds are optional polish */ }
  }

  function pinElement(d) {
    const wrap = el("div", "globe-pin");
    wrap.appendChild(el("span", "pin-core"));
    wrap.appendChild(el("span", "pin-ping"));
    if (d.label) wrap.appendChild(el("span", "pin-label", d.label));
    return wrap;
  }

  function resize() {
    if (!world) return;
    world.width(window.innerWidth).height(window.innerHeight);
  }

  let seq = 0;

  function show(m) {
    if (!ready) { init().then(() => show(m)); return; }
    const controls = world.controls();
    if (m.action === "spin") {
      seq++;  // cancel any in-flight fly sequence
      world.htmlElementsData([]).ringsData([]);
      controls.autoRotateSpeed = 1.1;
      world.pointOfView({ lat: 15, lng: 10, altitude: 2.4 }, 1400);
      labelEl.textContent = m.label || "";
    } else {
      flyTo(+m.lat, +m.lng, +(m.zoom || 1.5), m.label || "");
    }
  }

  /* Cinematic 3-stage move: pull back → rotate across → zoom in. */
  function flyTo(lat, lng, alt, label) {
    const my = ++seq;
    const controls = world.controls();
    controls.autoRotateSpeed = 0.08;
    labelEl.textContent = label;
    world.ringsData([]).htmlElementsData([]);
    const cur = world.pointOfView();
    world.pointOfView({ lat: cur.lat, lng: cur.lng, altitude: 2.7 }, 750);
    setTimeout(() => {
      if (my !== seq) return;
      world.pointOfView({ lat, lng, altitude: 2.7 }, 1250);   // rotate across
    }, 780);
    setTimeout(() => {
      if (my !== seq) return;
      world.pointOfView({ lat, lng, altitude: alt }, 1050);   // descend
      world.ringsData([{ lat, lng }]);
      world.htmlElementsData([{ lat, lng, label }]);
    }, 2080);
  }

  function toggle() {
    world.controls().autoRotateSpeed = 1.1;
    world.pointOfView({ altitude: 2.4 }, 1000);
  }

  return { init, show, toggle };
})();
