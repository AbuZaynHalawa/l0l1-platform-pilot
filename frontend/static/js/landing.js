// ================================================================
// HV Transformer Landing + Sign-In reveal
//
// Ported from design_handoff_hv_transformer_signin/source/HV Transformer
// Landing v5.dc.html at pixel-accurate, behavior-accurate fidelity. The
// source is a React-style class component (DCLogic/refs/setState) from a
// design-tool prototype; this app has no React and no build step, so the
// same logic is rewritten as plain functions closing over one `state`
// object and real DOM elements grabbed by id -- the same idiom the rest
// of this app already uses everywhere (see app.js).
//
// Structural changes from the source (see the approved plan,
// snug-moseying-lemon.md, for the full reasoning on each):
//   - onSubmit no longer opens a new tab -- it tears the overlay down and
//     reveals the app underneath, which has already decided (during its
//     own normal boot, running the whole time behind this overlay)
//     whether that's the locked first-time walkthrough or the dashboard.
//   - .shell gets `inert` + aria-hidden while this overlay is mounted, so
//     keyboard input in the sign-in form can't leak into the hidden
//     tour's own listeners, and Tab can't focus into it.
//   - body.style.overflow is saved and restored, not blanked to '', in
//     case the tour underneath is also holding a scroll lock.
//   - destroy() is a real, complete teardown (WebGL context loss, both
//     rAF loops stopped, AudioContext closed, every window/document
//     listener removed) -- the source's componentWillUnmount ported in
//     full, plus renderer.forceContextLoss() which the source itself
//     never needed since it only ever ran inside a designer preview.
// ================================================================
import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

// ---------------- data (verbatim from the source) ----------------
const COMPONENT_INFO = {
  bushingHV1: { title: '400 kV HV Bushing 01', category: 'HV SYSTEM', desc: 'Insulated terminal assembly connecting the transformer winding to the 400 kV external network.', specs: [['System', '400 kV'], ['Phase', 'L1'], ['Location', 'Tank cover, HV side']] },
  bushingHV2: { title: '400 kV HV Bushing 02', category: 'HV SYSTEM', desc: 'Insulated terminal assembly connecting the transformer winding to the 400 kV external network.', specs: [['System', '400 kV'], ['Phase', 'L2'], ['Location', 'Tank cover, HV side']] },
  bushingHV3: { title: '400 kV HV Bushing 03', category: 'HV SYSTEM', desc: 'Insulated terminal assembly connecting the transformer winding to the 400 kV external network.', specs: [['System', '400 kV'], ['Phase', 'L3'], ['Location', 'Tank cover, HV side']] },
  bushingLV1: { title: '132 kV LV Bushing 01', category: 'LV SYSTEM', desc: 'Terminal assembly carrying the low-voltage winding connection out to the 132 kV network.', specs: [['System', '132 kV'], ['Phase', 'L1'], ['Location', 'Tank cover, LV side']] },
  bushingLV2: { title: '132 kV LV Bushing 02', category: 'LV SYSTEM', desc: 'Terminal assembly carrying the low-voltage winding connection out to the 132 kV network.', specs: [['System', '132 kV'], ['Phase', 'L2'], ['Location', 'Tank cover, LV side']] },
  bushingLV3: { title: '132 kV LV Bushing 03', category: 'LV SYSTEM', desc: 'Terminal assembly carrying the low-voltage winding connection out to the 132 kV network.', specs: [['System', '132 kV'], ['Phase', 'L3'], ['Location', 'Tank cover, LV side']] },
  bushingNeutral: { title: 'Neutral Bushing', category: 'LV SYSTEM', desc: 'Brings the winding neutral point out of the tank for connection to the earthing arrangement.', specs: [['Function', 'Neutral terminal'], ['Location', 'Tank cover']] },
  hvCableBox: { title: 'HV Cable Box', category: 'HV SYSTEM', desc: 'Enclosure terminating high-voltage cabling at the tank wall.', specs: [['System', '400 kV'], ['Location', 'Front tank wall']] },
  lvCableBox: { title: 'LV Cable Box', category: 'LV SYSTEM', desc: 'Enclosure terminating low-voltage cabling at the tank wall.', specs: [['System', '132 kV'], ['Location', 'Front tank wall']] },
  radiatorBankL: { title: 'Radiator Bank — LV End', category: 'COOLING SYSTEM', desc: 'Finned oil-to-air radiator bank with its own header pipes and forced-air fans.', specs: [['Cooling', 'ONAN / ONAF'], ['Plates', '10'], ['Fans', '4']] },
  radiatorBankR: { title: 'Radiator Bank — HV End', category: 'COOLING SYSTEM', desc: 'Finned oil-to-air radiator bank with its own header pipes and forced-air fans.', specs: [['Cooling', 'ONAN / ONAF'], ['Plates', '10'], ['Fans', '4']] },
  oilPumps: { title: 'Oil Pumps', category: 'COOLING SYSTEM', desc: 'Motor-driven pumps circulating insulating oil through the radiator banks.', specs: [['Function', 'Forced oil circulation'], ['Units', '2']] },
  oilPipework: { title: 'Oil Pipework', category: 'COOLING SYSTEM', desc: 'Header runs, elbows and flanges routing oil between tank, pumps and radiators.', specs: [['Function', 'Oil circuit'], ['Location', 'Tank perimeter']] },
  onLoadTapChanger: { title: 'On-Load Tap Changer', category: 'OLTC', desc: 'Selects winding taps under load to regulate the output voltage without interrupting supply.', specs: [['Operation', 'On-load'], ['Location', 'HV side, front']] },
  oltcDriveMechanism: { title: 'OLTC Drive Mechanism', category: 'OLTC', desc: 'Motor drive unit that operates the tap changer and reports its position.', specs: [['Drive', 'Motorised'], ['Interface', 'Local / remote']] },
  buchholzRelay: { title: 'Buchholz Relay', category: 'PROTECTION', desc: 'Gas and oil-surge relay in the pipe between tank and conservator, alarming on internal faults.', specs: [['Function', 'Gas detection'], ['Location', 'Conservator pipe']] },
  conservatorAssembly: { title: 'Conservator Tank', category: 'PROTECTION', desc: 'Expansion vessel that accommodates oil volume change and carries the breather and oil level gauge.', specs: [['Function', 'Oil expansion'], ['Fitted', 'Breather, level gauge']] },
  marshallingControlBox: { title: 'Marshalling / Control Box', category: 'PROTECTION', desc: 'Terminates instrument and control wiring from the transformer accessories.', specs: [['Function', 'Control marshalling'], ['Location', 'Front tank wall']] },
  valvesAccessories: { title: 'Valves & Accessories', category: 'PROTECTION', desc: 'Isolating and drain valves serving the oil circuit and sampling points.', specs: [['Function', 'Oil isolation'], ['Location', 'Tank perimeter']] },
  earthingTerminals: { title: 'Earthing Terminals', category: 'PROTECTION', desc: 'Copper pads and straps bonding the tank and base frame to the substation earth grid.', specs: [['Function', 'Earth bonding'], ['Material', 'Copper']] },
  coreAndWindings: { title: 'Core & Windings', category: 'CORE & WINDINGS', desc: 'Three-limb laminated core carrying the concentric high- and low-voltage windings, clamped top and bottom.', specs: [['Phases', '3'], ['Rated power', '500 MVA'], ['Frequency', '50 Hz']] },
  tankCover: { title: 'Tank Cover', category: 'CORE & WINDINGS', desc: 'Bolted cover plate carrying the bushing turrets and the pressure relief device.', specs: [['Fixing', 'Bolted flange'], ['Carries', 'Bushings, PRD']] },
  tankWallFront: { title: 'Tank Wall — Front', category: 'CORE & WINDINGS', desc: 'Stiffened tank wall carrying the rating plate and the front-mounted accessories.', specs: [['Function', 'Oil containment'], ['Carries', 'Rating plate']] },
  tankWallBack: { title: 'Tank Wall — Back', category: 'CORE & WINDINGS', desc: 'Stiffened tank wall on the rear face of the oil-filled tank.', specs: [['Function', 'Oil containment']] },
  tankWallLeft: { title: 'Tank Wall — LV End', category: 'CORE & WINDINGS', desc: 'End wall of the tank at the low-voltage side.', specs: [['Function', 'Oil containment']] },
  tankWallRight: { title: 'Tank Wall — HV End', category: 'CORE & WINDINGS', desc: 'End wall of the tank at the high-voltage side.', specs: [['Function', 'Oil containment']] },
  tankFloor: { title: 'Tank Floor Pan', category: 'CORE & WINDINGS', desc: 'Base pan of the tank, seated on the base frame.', specs: [['Function', 'Oil containment']] },
  baseFrame: { title: 'Base Frame', category: 'CORE & WINDINGS', desc: 'Structural steel frame transferring the load of the assembly to the plinth.', specs: [['Function', 'Structural support']] },
  wheelsRollers: { title: 'Wheels / Rollers', category: 'CORE & WINDINGS', desc: 'Flanged rollers and axle boxes allowing the unit to be moved along rails.', specs: [['Function', 'Transport'], ['Type', 'Flanged roller']] },
};

const GROUPS = [
  { id: 'hv', num: '01', label: 'HV SYSTEM', key: 'bushingHV2' },
  { id: 'lv', num: '02', label: 'LV SYSTEM', key: 'bushingLV2' },
  { id: 'cooling', num: '03', label: 'COOLING', key: 'radiatorBankR' },
  { id: 'oltc', num: '04', label: 'OLTC', key: 'onLoadTapChanger' },
  { id: 'protection', num: '05', label: 'PROTECTION', key: 'conservatorAssembly' },
  { id: 'core', num: '06', label: 'CORE & WINDINGS', key: 'coreAndWindings' },
];

const SECTION_VIEWS = [
  { pos: [15.4, 10.2, 21.0], tgt: [-4.2, 4.4, 0], view: 'assembled' },
];

// ---------------- module-level state (replaces this.state / instance fields) ----------------
const state = {
  soundOn: true,
  exploring: false,
  selected: null,
  isTouch: false,
  signinOpen: false,
};

let stopped = true; // flips false once mount() actually runs
let mouse = { x: 0, y: 0, px: 0, py: 0, inside: false };
let hover = 0, hoverTarget = 0;
let explode = 0, explodeTarget = 0;
let insideAmt = 0, insideTarget = 0;
let focus = 0, focusTarget = 0;
let outro = 0, outroTarget = 0;
let frameCount = 0;
let viewOverride = null;
let section = 0;
let sectionF = 0;
let freeCam = false;
let mouseSpeed = 0;
let clock = 0;
let lastMs = 0;
let sparkAcc = 0;
let audio = null;
let audioSuspendT = null;
let signinT = null;
let ro = null; // canvas ResizeObserver
let dustRo = null;
let controls = null;
let resumeAudio = null;
let savedBodyOverflow = null; // §3 -- captured once, restored (not blanked) on release
let listenersBound = false;

// 'click' and 'mousedown' are the two events browsers reliably treat as a
// real "user activation" for unlocking an autoplay-blocked AudioContext --
// mousemove/wheel/scroll never do (continuous input, not a discrete
// activation-triggering gesture), so those three were never actually
// unlocking anything on their own; kept here anyway since they're harmless
// and do widen the surface for keyboard/touch users.
const AUDIO_UNLOCK_EVENTS = ['click', 'mousedown', 'pointerdown', 'mousemove', 'keydown', 'touchstart', 'wheel', 'scroll'];

const els = {}; // filled in mount() from getElementById

function el(id) { return document.getElementById(id); }

// ================================================================
// mount / destroy
// ================================================================
export function mount() {
  if (!stopped) return; // already mounted -- mount() must only ever run once per real page load
  stopped = false;

  els.root = el('hvLanding');
  els.shell = document.querySelector('.shell');
  els.canvas = el('hvCanvas');
  els.dustCanvas = el('hvDustCanvas');
  els.sceneWrap = el('hvSceneWrap');
  els.label = el('hvLabel');
  els.labelText = el('hvLabelText');
  els.labelCat = el('hvLabelCat');
  els.sections = el('hvSections');
  els.controls = el('hvControls');
  els.navV = el('hvNavV');
  els.navH = el('hvNavH');
  els.soundBtn = el('hvSoundBtn');
  els.exploreOverlay = el('hvExploreOverlay');
  els.exitExploreBtn = el('hvExitExplore');
  els.hintRotate = el('hvHintRotate');
  els.hintZoom = el('hvHintZoom');
  els.hintPick = el('hvHintPick');
  els.signin = el('hvSignin');
  els.signinPanel = el('hvSigninPanel');
  els.signinForm = el('hvSigninForm');
  els.specPanel = el('hvSpecPanel');
  els.specCategory = el('hvSpecCategory');
  els.specTitle = el('hvSpecTitle');
  els.specDesc = el('hvSpecDesc');
  els.specSpecs = el('hvSpecSpecs');

  // .shell is neutralized (§2) the instant this overlay exists -- it's
  // already true on page load since #hvLanding starts un-hidden and
  // .shell starts covered, but set explicitly here too so mount() is the
  // single source of truth for that invariant.
  neutralizeShell(true);

  mouse = { x: 0, y: 0, px: 0, py: 0, inside: false };
  const touch = window.matchMedia('(pointer: coarse)').matches;
  state.isTouch = touch;
  applyHints();

  bindStaticUI();
  buildScene();
  initDust();
  initAudio();

  resumeAudio = () => {
    if (audio && audio.on && audio.ctx.state === 'suspended') audio.ctx.resume();
  };
  AUDIO_UNLOCK_EVENTS.forEach((ev) => window.addEventListener(ev, resumeAudio, { passive: true }));
  listenersBound = true;
}

export function destroy() {
  if (stopped) return;
  stopped = true; // both rAF loops (animate/draw) check this before rescheduling

  if (listenersBound) {
    AUDIO_UNLOCK_EVENTS.forEach((ev) => window.removeEventListener(ev, resumeAudio));
  }
  if (onWinOut) { window.removeEventListener('blur', onWinOut); document.removeEventListener('pointerleave', onWinOut); }
  if (onWinMove) window.removeEventListener('pointermove', onWinMove);
  if (onWinDown) window.removeEventListener('pointerdown', onWinDown);
  if (onWinUp) window.removeEventListener('pointerup', onWinUp);
  if (onKey) window.removeEventListener('keydown', onKey);
  document.removeEventListener('visibilitychange', resizeCanvasIfNeeded);
  document.removeEventListener('visibilitychange', resizeDustIfNeeded);
  document.body.style.cursor = '';
  if (ro) { ro.disconnect(); ro = null; }
  if (dustRo) { dustRo.disconnect(); dustRo = null; }
  if (controls) { controls.dispose(); controls = null; }
  if (audioSuspendT) clearTimeout(audioSuspendT);
  if (signinT) clearTimeout(signinT);
  if (renderer) {
    try { renderer.dispose(); } catch (e) {}
    try { renderer.forceContextLoss(); } catch (e) {}
    renderer = null;
  }
  if (audio) {
    try { audio.ctx.close(); } catch (e) {}
    if (window.__hvAudio === audio) window.__hvAudio = null;
    audio = null;
  }
  // §3: restore whatever body.style.overflow was before the landing ever
  // touched it, not a hardcoded '' -- the tour underneath may hold its
  // own scroll lock independently.
  if (savedBodyOverflow !== null) {
    document.body.style.overflow = savedBodyOverflow;
    savedBodyOverflow = null;
  }
  neutralizeShell(false);
}

function neutralizeShell(on) {
  if (!els.shell) els.shell = document.querySelector('.shell');
  if (!els.shell) return;
  if (on) {
    els.shell.setAttribute('inert', '');
    els.shell.setAttribute('aria-hidden', 'true');
  } else {
    els.shell.removeAttribute('inert');
    els.shell.removeAttribute('aria-hidden');
  }
}

function setBodyOverflow(hidden) {
  if (hidden) {
    if (savedBodyOverflow === null) savedBodyOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
  } else if (savedBodyOverflow !== null) {
    document.body.style.overflow = savedBodyOverflow;
    savedBodyOverflow = null;
  }
}

function applyHints() {
  if (els.hintRotate) els.hintRotate.textContent = state.isTouch ? 'SWIPE TO ROTATE' : 'DRAG TO ROTATE';
  if (els.hintZoom) els.hintZoom.textContent = state.isTouch ? 'PINCH TO ZOOM' : 'SCROLL TO ZOOM';
  if (els.hintPick) els.hintPick.textContent = state.isTouch ? 'TAP A COMPONENT TO INSPECT' : 'CLICK A COMPONENT TO INSPECT';
}

// ================================================================
// static UI wiring (nav rail, sound, controls, sign-in, spec panel)
// ================================================================
function bindStaticUI() {
  document.querySelectorAll('.hv-nav-group[data-hv-group]').forEach((btn) => {
    btn.addEventListener('click', () => exploreTo(btn.dataset.hvKey));
  });
  if (els.soundBtn) els.soundBtn.addEventListener('click', toggleSound);
  const explodeBtn = el('hvExplodeBtn'), insideBtn = el('hvInsideBtn'), resetBtn = el('hvResetBtn');
  if (explodeBtn) explodeBtn.addEventListener('click', onExplode);
  if (insideBtn) insideBtn.addEventListener('click', onInside);
  if (resetBtn) resetBtn.addEventListener('click', onReset);
  if (els.exitExploreBtn) els.exitExploreBtn.addEventListener('click', onExitExplore);

  const heroSignInBtn = el('hvHeroSignIn');
  if (heroSignInBtn) heroSignInBtn.addEventListener('click', onSignin);
  const exploreBtn = el('hvExploreBtn');
  if (exploreBtn) exploreBtn.addEventListener('click', onExplore);

  if (els.signin) els.signin.addEventListener('click', (e) => { if (e.target === e.currentTarget) closeSignin(); });
  const signinClose = el('hvSigninClose');
  if (signinClose) signinClose.addEventListener('click', closeSignin);
  if (els.signinForm) els.signinForm.addEventListener('submit', onSubmit);

  const specClose = el('hvSpecClose');
  if (specClose) specClose.addEventListener('click', clearSelection);
  const viewAssemblyBtn = el('hvViewAssembly');
  if (viewAssemblyBtn) viewAssemblyBtn.addEventListener('click', onViewAssembly);
}

function setSoundLabel() {
  if (els.soundBtn) els.soundBtn.textContent = state.soundOn ? 'SOUND ON' : 'SOUND OFF';
}

function showExploreOverlay(on) {
  if (els.exploreOverlay) els.exploreOverlay.hidden = !on;
}

function showSignin(on) {
  if (!els.signin) return;
  if (on) {
    els.signin.hidden = false;
    // Re-trigger the CSS animations every open, same as the source's
    // sc-if remount (a fresh element each time it appears).
    els.signin.style.animation = 'none';
    els.signinPanel.style.animation = 'none';
    // Force reflow so the animation restarts even if it was shown before.
    void els.signin.offsetWidth;
    els.signin.style.animation = '';
    els.signinPanel.style.animation = '';
  } else {
    els.signin.hidden = true;
  }
}

function renderSpecPanel() {
  const sel = state.selected ? COMPONENT_INFO[state.selected] : null;
  if (!els.specPanel) return;
  if (!sel) { els.specPanel.hidden = true; return; }
  els.specPanel.hidden = false;
  els.specPanel.style.animation = 'none';
  void els.specPanel.offsetWidth;
  els.specPanel.style.animation = '';
  els.specCategory.textContent = sel.category;
  els.specTitle.textContent = sel.title;
  els.specDesc.textContent = sel.desc;
  els.specSpecs.innerHTML = '';
  sel.specs.forEach((row) => {
    const r = document.createElement('div');
    r.style.cssText = 'display:flex;align-items:center;justify-content:space-between;gap:14px;border-top:2px solid var(--rule);padding-top:9px;';
    r.innerHTML = '<span style="font-size:10px;letter-spacing:0.16em;color:var(--ink-faint);">' + row[0] +
      '</span><span style="font-family:var(--font-heading);font-weight:700;font-size:12px;letter-spacing:0.06em;color:var(--ink);">' + row[1] + '</span>';
    els.specSpecs.appendChild(r);
  });
}

// ================================================================
// interaction handlers (verbatim logic from the source, `this.` -> module state)
// ================================================================
let focusOnPart = null, resetCamera = null, zoomInside = null, pickAt = null, setHoverNull = null, syncSelectionVisual = null, applyControlMode = null;

function selectPart(name) {
  const prev = state.selected;
  if (prev === name) return;
  if (syncSelectionVisual) syncSelectionVisual(prev, name);
  state.selected = name;
  renderSpecPanel();
  if (focusOnPart) focusOnPart(name);
}

function clearSelection() {
  const prev = state.selected;
  if (syncSelectionVisual) syncSelectionVisual(prev, null);
  state.selected = null;
  renderSpecPanel();
  if (resetCamera) resetCamera();
}

function onViewAssembly() {
  viewOverride = viewOverride === 'exploded' ? null : 'exploded';
  if (state.selected && focusOnPart) focusOnPart(state.selected);
}

function onExplode() { viewOverride = viewOverride === 'exploded' ? null : 'exploded'; }
function onInside() { viewOverride = viewOverride === 'inside' ? null : 'inside'; }
function onReset() {
  viewOverride = null;
  clearSelection();
  if (resetCamera) resetCamera();
}

function onSignin() {
  if (state.signinOpen) return;
  if (state.exploring) onExitExplore();
  clearSelection();
  if (setHoverNull) setHoverNull();
  viewOverride = null;
  outroTarget = 1;
  if (zoomInside) zoomInside();
  if (els.sections) { els.sections.style.opacity = '0'; els.sections.style.pointerEvents = 'none'; }
  if (els.navV) { els.navV.style.opacity = '0'; els.navV.style.pointerEvents = 'none'; }
  if (els.navH) { els.navH.style.opacity = '0'; els.navH.style.pointerEvents = 'none'; }
  if (audio && audio.on) {
    const ct = audio.ctx.currentTime;
    audio.master.gain.cancelScheduledValues(ct);
    audio.master.gain.setValueAtTime(audio.master.gain.value, ct);
    audio.master.gain.linearRampToValueAtTime(0.55, ct + 0.06);
    discharge();
  }
  if (signinT) clearTimeout(signinT);
  signinT = setTimeout(() => {
    if (stopped) return;
    state.signinOpen = true;
    showSignin(true);
    if (audio && audio.on) {
      const ct = audio.ctx.currentTime;
      audio.master.gain.cancelScheduledValues(ct);
      audio.master.gain.setValueAtTime(audio.master.gain.value, ct);
      audio.master.gain.linearRampToValueAtTime(0, ct + 1.05);
    }
  }, 90);
}

function closeSignin() {
  if (signinT) clearTimeout(signinT);
  state.signinOpen = false;
  showSignin(false);
  outroTarget = 0;
  viewOverride = null;
  if (resetCamera) resetCamera();
  if (els.sections) { els.sections.style.opacity = '1'; els.sections.style.pointerEvents = ''; }
  if (els.navV) { els.navV.style.opacity = '1'; els.navV.style.pointerEvents = ''; }
  if (els.navH) { els.navH.style.opacity = '1'; els.navH.style.pointerEvents = ''; }
  if (audio && audio.on) {
    const ct = audio.ctx.currentTime, g = audio.master.gain;
    g.cancelScheduledValues(ct);
    g.setValueAtTime(g.value, ct);
    g.linearRampToValueAtTime(0.55, ct + 0.6);
  }
}

// [queued: real app integration] The one deliberate behavioral change
// from the source -- was e.preventDefault() + window.open(dashboard url,
// '_blank'). Dummy sign-in per Yasser's instruction: no credential check,
// submitting just reveals the app that's been booting underneath this
// whole time (already decided locked-tour-vs-dashboard on its own, see
// the plan's "key discovery").
function onSubmit(e) {
  e.preventDefault();
  els.root.classList.add('hv-dismissing');
  window.setTimeout(() => {
    destroy();
    if (els.root) els.root.hidden = true;
  }, 520); // matches the hvBurstOut CSS animation's own 0.5s duration
}

function exploreTo(key) {
  if (state.signinOpen) return;
  if (state.exploring) { selectPart(key); return; }
  onExplore();
  setTimeout(() => { if (!stopped) selectPart(key); }, 260);
}

function onExplore() {
  window.scrollTo(0, 0);
  sectionF = 0; section = 0;
  setBodyOverflow(true);
  state.exploring = true;
  if (applyControlMode) applyControlMode();
  if (els.sections) { els.sections.style.opacity = '0'; els.sections.style.pointerEvents = 'none'; }
  if (els.controls) { els.controls.style.opacity = '1'; els.controls.style.pointerEvents = 'auto'; }
  if (els.navH) { els.navH.style.opacity = '0'; els.navH.style.pointerEvents = 'none'; }
  showExploreOverlay(true);
}

function onExitExplore() {
  setBodyOverflow(false);
  viewOverride = null;
  clearSelection();
  state.exploring = false;
  if (applyControlMode) applyControlMode();
  if (els.sections) { els.sections.style.opacity = '1'; els.sections.style.pointerEvents = ''; }
  if (els.controls) { els.controls.style.opacity = '0'; els.controls.style.pointerEvents = 'none'; }
  if (els.navH) { els.navH.style.opacity = '1'; els.navH.style.pointerEvents = ''; }
  showExploreOverlay(false);
}

function toggleSound() {
  if (!audio) {
    initAudio();
    if (audio && audio.ctx.state === 'suspended') audio.ctx.resume();
  } else {
    const a = audio, ct = a.ctx.currentTime, g = a.master.gain;
    a.on = !a.on;
    if (audioSuspendT) { clearTimeout(audioSuspendT); audioSuspendT = null; }
    g.cancelScheduledValues(ct);
    if (a.on) {
      try { a.master.connect(a.ctx.destination); } catch (e) {}
      if (a.ctx.state === 'suspended') a.ctx.resume();
      g.setValueAtTime(0, ct);
      g.linearRampToValueAtTime(0.55, ct + 0.25);
    } else {
      g.setValueAtTime(g.value, ct);
      g.linearRampToValueAtTime(0, ct + 0.18);
      audioSuspendT = setTimeout(() => {
        if (!audio || audio.on) return;
        try { audio.master.disconnect(); } catch (e) {}
        (window.__hvAudioAll || []).forEach((c) => { try { if (c.state === 'running') c.suspend(); } catch (e) {} });
      }, 220);
    }
  }
  state.soundOn = !!(audio && audio.on);
  setSoundLabel();
}

// ================================================================
// window-level pointer/keyboard listeners (module-scoped so destroy() can remove them)
// ================================================================
let onWinMove = null, onWinDown = null, onWinUp = null, onWinOut = null, onKey = null;
let downX = 0, downY = 0, downT = 0;
let renderer = null;

function resizeCanvasIfNeeded() { if (resizeFn) resizeFn(); }
function resizeDustIfNeeded() { if (dustSizeFn) dustSizeFn(); }
let resizeFn = null, dustSizeFn = null;

// ================================================================
// three.js scene (ported ~1:1 from buildScene() in the source)
// ================================================================
async function buildScene() {
  try { await doBuildScene(); } catch (err) { console.error('HV landing scene build failed', err); }
}

async function doBuildScene() {
  const canvas = els.canvas;
  if (!canvas || stopped) return;
  const parent = canvas.parentElement;

  renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, Math.min(window.innerWidth, window.innerHeight) < 780 ? 1.5 : 2));
  renderer.shadowMap.enabled = true;
  renderer.shadowMap.type = THREE.PCFShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;
  renderer.toneMappingExposure = 1.02;
  const scene = new THREE.Scene();

  const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 220);
  const camTarget0 = new THREE.Vector3(0, 3.9, 0);
  camera.position.set(19.2, 12.6, 26.2);

  const hemi = new THREE.HemisphereLight(0x9fb0c0, 0x171310, 0.42);
  scene.add(hemi);
  scene.environment = (() => {
    const c = document.createElement('canvas'); c.width = 64; c.height = 32;
    const cx = c.getContext('2d');
    const g = cx.createLinearGradient(0, 0, 0, 32);
    g.addColorStop(0, '#b9bfc4'); g.addColorStop(0.5, '#6c6f70'); g.addColorStop(0.52, '#37342f'); g.addColorStop(1, '#1a1815');
    cx.fillStyle = g; cx.fillRect(0, 0, 64, 32);
    const t = new THREE.CanvasTexture(c);
    t.mapping = THREE.EquirectangularReflectionMapping;
    return t;
  })();
  scene.environmentIntensity = 0.42;
  const key = new THREE.DirectionalLight(0xfff2e2, 2.15); key.position.set(9, 15, 10);
  key.castShadow = true;
  key.shadow.mapSize.set(2048, 2048);
  key.shadow.camera.left = -16; key.shadow.camera.right = 16;
  key.shadow.camera.top = 16; key.shadow.camera.bottom = -16;
  key.shadow.camera.near = 1; key.shadow.camera.far = 80;
  key.shadow.bias = -0.0006;
  scene.add(key);
  const fill = new THREE.DirectionalLight(0x8fa6b8, 0.55); fill.position.set(-13, 6, -9); scene.add(fill);
  const rim = new THREE.DirectionalLight(0xffffff, 0.85); rim.position.set(-5, 4, 13); scene.add(rim);
  const shadowPlane = new THREE.Mesh(new THREE.PlaneGeometry(52, 52), new THREE.ShadowMaterial({ opacity: 0.42 }));
  shadowPlane.rotation.x = -Math.PI / 2; shadowPlane.receiveShadow = true; scene.add(shadowPlane);
  const shadowTex = (() => {
    const c = document.createElement('canvas'); c.width = c.height = 256;
    const cx = c.getContext('2d');
    const g = cx.createRadialGradient(128, 128, 12, 128, 128, 128);
    g.addColorStop(0, 'rgba(8,7,6,0.5)'); g.addColorStop(1, 'rgba(8,7,6,0)');
    cx.fillStyle = g; cx.fillRect(0, 0, 256, 256);
    return new THREE.CanvasTexture(c);
  })();
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(22, 13),
    new THREE.MeshBasicMaterial({ map: shadowTex, transparent: true, depthWrite: false }));
  ground.rotation.x = -Math.PI / 2; ground.position.y = 0.002; scene.add(ground);

  // ---------- procedural transformer ----------
  const matBody = new THREE.MeshStandardMaterial({ name: 'tankPaintGrey', color: 0x9aa09c, roughness: 0.62, metalness: 0.25 });
  const matPanel = new THREE.MeshStandardMaterial({ name: 'radiatorGalvanised', color: 0xb0b5b1, roughness: 0.46, metalness: 0.5 });
  const matSteel = new THREE.MeshStandardMaterial({ name: 'steelFittings', color: 0x75797a, roughness: 0.48, metalness: 0.62 });
  const matBrown = new THREE.MeshStandardMaterial({ name: 'porcelainBrown', color: 0x4a2a18, roughness: 0.26, metalness: 0.06 });
  const matAlu = new THREE.MeshStandardMaterial({ name: 'aluminium', color: 0xc8ccca, roughness: 0.27, metalness: 0.85 });
  const matCopper = new THREE.MeshStandardMaterial({ name: 'copperWinding', color: 0xb87333, roughness: 0.36, metalness: 0.82 });
  const matCore = new THREE.MeshStandardMaterial({ name: 'coreLamination', color: 0x4d545e, roughness: 0.28, metalness: 0.93 });
  const matRed = new THREE.MeshStandardMaterial({ name: 'nameplateRed', color: 0xb3271b, roughness: 0.5, metalness: 0.15 });
  const matBrass = new THREE.MeshStandardMaterial({ name: 'brass', color: 0xb08d3f, roughness: 0.32, metalness: 0.85 });
  const matValveRed = new THREE.MeshStandardMaterial({ name: 'valveRed', color: 0xa32a1c, roughness: 0.45, metalness: 0.2 });
  const matMotor = new THREE.MeshStandardMaterial({ name: 'motorBlue', color: 0x3f5a6b, roughness: 0.45, metalness: 0.4 });
  const matYellow = new THREE.MeshStandardMaterial({ name: 'hazardYellow', color: 0xd9a520, roughness: 0.5, metalness: 0.1 });
  const matWhite = new THREE.MeshStandardMaterial({ name: 'gaugeWhite', color: 0xe8e6e0, roughness: 0.4, metalness: 0.1 });
  const matBlack = new THREE.MeshStandardMaterial({ name: 'gasketBlack', color: 0x24262a, roughness: 0.68, metalness: 0.2 });

  const box = (w, h, d, m) => new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m);
  const cyl = (rt, rb, h, m, seg) => new THREE.Mesh(new THREE.CylinderGeometry(rt, rb, h, seg || 20), m);
  const at = (mesh, name, x, y, z) => { mesh.name = name; mesh.position.set(x, y, z); return mesh; };

  const root = new THREE.Group();
  root.name = 'hvPowerTransformer';
  scene.add(root);
  const explodables = [];
  const byName = {};
  const fans = [];
  const reg = (obj, dir, mag, name, label, parent) => {
    obj.name = name;
    obj.userData.origin = obj.position.clone();
    obj.userData.dir = new THREE.Vector3(dir[0], dir[1], dir[2]).normalize();
    obj.userData.mag = mag;
    obj.userData.label = label;
    obj.userData.solo = 0;
    obj.userData.phase = Math.random() * Math.PI * 2;
    obj.userData.delay = 0.1 + Math.random() * 0.75;
    obj.userData.introDist = 5 + Math.random() * 10;
    obj.userData.baseRot = obj.rotation.clone();
    obj.userData.introRot = new THREE.Euler((Math.random() - 0.5) * 1.1, (Math.random() - 0.5) * 1.1, (Math.random() - 0.5) * 1.1);
    explodables.push(obj);
    byName[name] = obj;
    (parent || root).add(obj);
    return obj;
  };

  // ================= base frame + wheels =================
  const frame = new THREE.Group();
  frame.add(at(box(6.4, 0.5, 3.6, matSteel), 'baseFrameBeam', 0, 0.6, 0));
  [-1.5, 1.5].forEach((z) => frame.add(at(box(7.0, 0.26, 0.4, matSteel), 'baseRail', 0, 0.35, z)));
  reg(frame, [0, -1, 0], 0.4, 'baseFrame', 'BASE FRAME / TANK');

  const wheels = new THREE.Group();
  [-2.7, -1.1, 1.1, 2.7].forEach((x) => [-1.5, 1.5].forEach((z) => {
    const w = cyl(0.28, 0.28, 0.34, matSteel, 18);
    w.rotation.x = Math.PI / 2; at(w, 'roller', x, 0.28, z); wheels.add(w);
    [-0.18, 0.18].forEach((o) => {
      const rimM = new THREE.Mesh(new THREE.TorusGeometry(0.29, 0.04, 8, 18), matSteel);
      rimM.rotation.x = Math.PI / 2; wheels.add(at(rimM, 'rollerFlange', x, 0.28, z + o));
    });
    wheels.add(at(box(0.34, 0.26, 0.4, matSteel), 'axleBox', x, 0.58, z));
  }));
  reg(wheels, [0, -1, 0], 0.85, 'wheelsRollers', 'WHEELS / ROLLERS');

  // ================= tank shell (four walls + floor) =================
  const wallFront = new THREE.Group();
  wallFront.add(at(box(5.6, 3.2, 0.12, matBody), 'tankWallPanel', 0, 0, 0));
  for (let i = 0; i < 8; i++) wallFront.add(at(box(0.14, 2.9, 0.16, matSteel), 'tankStiffener', -2.45 + i * 0.7, 0, 0.13));
  wallFront.add(at(box(0.46, 0.32, 0.03, matWhite), 'ratingPlate', 2.02, 0.5, 0.2));
  wallFront.add(at(box(0.5, 0.36, 0.02, matSteel), 'ratingPlateFrame', 2.02, 0.5, 0.185));
  wallFront.add(at(box(0.22, 0.22, 0.03, matYellow), 'hazardLabel', 1.55, 0.5, 0.2));
  wallFront.position.set(0, 2.45, 1.5);
  reg(wallFront, [0, 0, 1], 1.3, 'tankWallFront', 'TANK WALL (FRONT)');

  const wallBack = new THREE.Group();
  wallBack.add(at(box(5.6, 3.2, 0.12, matBody), 'tankWallPanel', 0, 0, 0));
  for (let i = 0; i < 8; i++) wallBack.add(at(box(0.14, 2.9, 0.16, matSteel), 'tankStiffener', -2.45 + i * 0.7, 0, -0.13));
  wallBack.position.set(0, 2.45, -1.5);
  reg(wallBack, [0, 0, -1], 1.3, 'tankWallBack', 'TANK WALL (BACK)');

  const wallLeft = new THREE.Group();
  wallLeft.add(at(box(0.12, 3.2, 2.9, matBody), 'tankWallPanel', 0, 0, 0));
  wallLeft.position.set(-2.79, 2.45, 0);
  reg(wallLeft, [-1, 0, 0], 0.85, 'tankWallLeft', 'TANK WALL (LV END)');

  const wallRight = new THREE.Group();
  wallRight.add(at(box(0.12, 3.2, 2.9, matBody), 'tankWallPanel', 0, 0, 0));
  wallRight.position.set(2.79, 2.45, 0);
  reg(wallRight, [1, 0, 0], 0.85, 'tankWallRight', 'TANK WALL (HV END)');

  const floorPan = box(5.6, 0.16, 3.0, matSteel);
  floorPan.position.set(0, 0.93, 0);
  reg(floorPan, [0, -1, 0], 0.9, 'tankFloor', 'TANK FLOOR PAN');

  // ================= tank cover =================
  const cover = new THREE.Group();
  cover.add(at(box(5.8, 0.12, 3.2, matSteel), 'tankRimFlange', 0, 4.08, 0));
  cover.add(at(box(5.5, 0.24, 2.9, matBody), 'tankCoverPlate', 0, 4.26, 0));
  const prd = cyl(0.16, 0.16, 0.34, matAlu, 14);
  cover.add(at(prd, 'pressureReliefDevice', -2.0, 4.55, 0.9));
  cover.add(at(box(5.7, 0.04, 3.1, matBlack), 'coverGasket', 0, 4.0, 0));
  for (let i = 0; i < 26; i++) {
    const x = -2.75 + (i / 25) * 5.5;
    [-1.52, 1.52].forEach((z) => cover.add(at(cyl(0.05, 0.05, 0.08, matSteel, 8), 'coverBolt', x, 4.16, z)));
  }
  for (let i = 0; i < 12; i++) {
    const z = -1.35 + (i / 11) * 2.7;
    [-2.82, 2.82].forEach((x) => cover.add(at(cyl(0.05, 0.05, 0.08, matSteel, 8), 'coverBolt', x, 4.16, z)));
  }
  reg(cover, [0, 1, 0], 0.8, 'tankCover', 'TANK COVER');

  // ================= core & windings =================
  const core = new THREE.Group();
  [-1.68, 0, 1.68].forEach((x, i) => {
    const yoke = box(0.46, 2.05, 0.52, matCore);
    core.add(at(yoke, 'coreLimb' + (i + 1), x, 2.4, 0));
    const hv = cyl(0.62, 0.62, 1.62, matCopper, 26);
    hv.material = matCopper;
    core.add(at(hv, 'hvWinding' + (i + 1), x, 2.4, 0));
    const lv = cyl(0.44, 0.44, 1.78, matCopper, 26);
    core.add(at(lv, 'lvWinding' + (i + 1), x, 2.4, 0));
    [1.9, 2.9].forEach((y, k) => core.add(at(box(0.72, 0.06, 0.72, matAlu), 'windingClamp' + k, x, y, 0)));
  });
  [1.45, 3.35].forEach((y, k) => core.add(at(box(4.35, 0.42, 0.52, matCore), k === 0 ? 'coreYokeBottom' : 'coreYokeTop', 0, y, 0)));
  [-0.36, 0.36].forEach((z) => core.add(at(box(4.6, 0.1, 0.1, matSteel), 'coreClampBeam', 0, 3.62, z)));
  reg(core, [0, 1, 0], 0.55, 'coreAndWindings', 'CORE & WINDINGS');

  // ================= bushings =================
  const buildBushing = (coreH, coreR, sheds, turretR, stemH, gradeRing) => {
    const g = new THREE.Group();
    g.add(at(cyl(turretR, turretR * 1.1, 0.4, matBody, 18), 'bushingTurret', 0, 0.2, 0));
    g.add(at(cyl(turretR * 1.25, turretR * 1.25, 0.09, matSteel, 18), 'bushingFlange', 0, 0.42, 0));
    g.add(at(cyl(coreR * 0.82, coreR, coreH, matBrown, 18), 'bushingInsulatorCore', 0, 0.47 + coreH / 2, 0));
    for (let i = 0; i < sheds; i++) {
      const t = (i + 0.5) / sheds;
      const r = coreR * (1.62 - 0.18 * t);
      g.add(at(cyl(r, r, 0.05, matBrown, 16), 'bushingShed', 0, 0.5 + t * (coreH - 0.1), 0));
    }
    g.add(at(cyl(coreR * 1.05, coreR * 1.12, 0.42, matAlu, 18), 'bushingUpperHousing', 0, 0.47 + coreH + 0.21, 0));
    g.add(at(cyl(coreR * 1.55, coreR * 1.3, 0.14, matAlu, 18), 'bushingTopCap', 0, 0.47 + coreH + 0.49, 0));
    g.add(at(cyl(coreR * 0.4, coreR * 0.4, stemH, matAlu, 14), 'bushingTerminalStem', 0, 0.47 + coreH + 0.56 + stemH / 2, 0));
    const ball = new THREE.Mesh(new THREE.SphereGeometry(coreR * 0.55, 14, 12), matAlu);
    g.add(at(ball, 'bushingTerminal', 0, 0.47 + coreH + 0.56 + stemH + coreR * 0.4, 0));
    for (let i = 0; i < 6; i++) {
      const a = (i / 6) * Math.PI * 2;
      g.add(at(cyl(0.035, 0.035, 0.07, matSteel, 6), 'turretBolt',
        Math.cos(a) * turretR * 1.1, 0.47, Math.sin(a) * turretR * 1.1));
    }
    if (gradeRing) {
      const gr = new THREE.Mesh(new THREE.TorusGeometry(coreR * 2.4, coreR * 0.28, 8, 24), matAlu);
      gr.rotation.x = Math.PI / 2;
      g.add(at(gr, 'coronaGradingRing', 0, 0.47 + coreH + 0.4, 0));
    }
    return g;
  };

  [-1.75, -0.35, 1.05].forEach((x, i) => {
    const b = buildBushing(2.35, 0.2, 17, 0.38, 0.55, true);
    b.position.set(x, 4.38, -0.85);
    reg(b, [Math.sign(x) * 0.18, 1, -0.28], 1.25, 'bushingHV' + (i + 1), '400 kV HV BUSHING ' + (i + 1));
  });
  [0.85, 1.65, 2.45].forEach((x, i) => {
    const b = buildBushing(1.15, 0.155, 10, 0.3, 0.4);
    b.position.set(x, 4.38, 0.85);
    reg(b, [Math.sign(x) * 0.2, 1, 0.32], 1.05, 'bushingLV' + (i + 1), '132 kV LV BUSHING ' + (i + 1));
  });
  const neutral = buildBushing(0.85, 0.13, 7, 0.26, 0.32);
  neutral.position.set(-2.25, 4.38, 0.9);
  reg(neutral, [-0.4, 1, 0.3], 1.0, 'bushingNeutral', 'NEUTRAL BUSHING');

  // ================= radiator banks (individual plates) + fans =================
  const buildFan = () => {
    const outer = new THREE.Group();
    const inner = new THREE.Group();
    inner.add((() => { const h = cyl(0.11, 0.11, 0.18, matSteel, 14); h.rotation.x = Math.PI / 2; h.name = 'fanHub'; return h; })());
    for (let i = 0; i < 6; i++) {
      const blade = box(0.3, 0.13, 0.02, matAlu);
      const a = (i / 6) * Math.PI * 2;
      blade.position.set(Math.cos(a) * 0.21, Math.sin(a) * 0.21, 0);
      blade.rotation.set(0.4, 0, a);
      blade.name = 'fanBlade';
      inner.add(blade);
    }
    outer.add(inner);
    const ring = new THREE.Mesh(new THREE.TorusGeometry(0.36, 0.045, 8, 26), matSteel);
    ring.name = 'fanHousingRing'; outer.add(ring);
    const shroud = cyl(0.36, 0.36, 0.16, matSteel, 24);
    shroud.material = new THREE.MeshStandardMaterial({ name: 'fanShroud', color: 0x8b8b83, roughness: 0.6, metalness: 0.4, side: THREE.DoubleSide });
    shroud.rotation.x = Math.PI / 2; shroud.position.z = -0.1; shroud.name = 'fanShroud';
    outer.add(shroud);
    [0.13, 0.23, 0.32].forEach((r) => {
      const gr = new THREE.Mesh(new THREE.TorusGeometry(r, 0.008, 5, 20), matSteel);
      gr.position.z = 0.1; gr.name = 'fanGuardRing'; outer.add(gr);
    });
    for (let i = 0; i < 6; i++) {
      const spoke = box(0.71, 0.016, 0.016, matSteel);
      spoke.rotation.z = (i / 6) * Math.PI;
      spoke.position.z = 0.1; spoke.name = 'fanGuardSpoke'; outer.add(spoke);
    }
    return { outer, inner };
  };

  [-1, 1].forEach((dir) => {
    const side = dir < 0 ? 'L' : 'R';
    const bankFrame = new THREE.Group();
    [0.95, 4.05].forEach((y, k) => {
      const header = cyl(0.14, 0.14, 1.9, matSteel, 14);
      header.rotation.z = Math.PI / 2;
      bankFrame.add(at(header, k === 0 ? 'radiatorHeaderBottom' : 'radiatorHeaderTop', dir * 1.0, y, 0));
    });
    [-0.6, 0.6].forEach((z) => bankFrame.add(at(cyl(0.12, 0.12, 3.2, matSteel, 14), 'radiatorRiser', dir * 0.16, 2.5, z)));
    bankFrame.position.set(dir * 2.85, 0, 0);
    reg(bankFrame, [dir, 0, 0], 1.2, 'radiatorBank' + side, 'RADIATOR BANK (' + (dir < 0 ? 'LV' : 'HV') + ' END)');

    for (let i = 0; i < 10; i++) {
      const plate = box(0.11, 3.0, 1.6, matPanel);
      plate.position.set(dir * (0.28 + i * 0.16), 2.5, 0);
      const spread = (i - 4.5) / 4.5;
      reg(plate, [dir * 1.0, 0.12, spread * 0.85], 0.55 + i * 0.055, 'radiatorPlate' + side + (i + 1),
        'RADIATOR PLATE ' + side + (i + 1), bankFrame);
    }

    [1.45, 2.2, 2.95, 3.7].forEach((y, i) => {
      const f = buildFan();
      f.outer.rotation.y = dir * Math.PI / 2;
      f.outer.position.set(dir * 1.85, y, 0.1);
      reg(f.outer, [dir, -0.15, 0.1], 1.1, 'coolingFan' + side + (i + 1), 'COOLING FAN ' + side + (i + 1), bankFrame);
      fans.push(f.inner);
    });
  });

  // ================= OLTC + drive =================
  const oltc = new THREE.Group();
  oltc.add(at(cyl(0.52, 0.52, 2.5, matBody, 22), 'oltcTank', 0, 2.35, 0));
  const dome = new THREE.Mesh(new THREE.SphereGeometry(0.52, 20, 12, 0, Math.PI * 2, 0, Math.PI / 2), matBody);
  oltc.add(at(dome, 'oltcDome', 0, 3.6, 0));
  [1.3, 2.4, 3.4].forEach((y) => oltc.add(at(cyl(0.58, 0.58, 0.1, matSteel, 22), 'oltcFlange', 0, y, 0)));
  oltc.add(at(cyl(0.1, 0.1, 0.12, matWhite, 14), 'oltcSightGlass', 0.48, 2.9, 0.18));
  oltc.add(at(box(0.34, 0.42, 0.3, matBody), 'oltcProtectionRelay', 0.62, 1.8, 0.12));
  oltc.add(at(cyl(0.14, 0.14, 0.2, matBrass, 12), 'oltcDrainValve', 0.4, 1.2, 0.35));
  oltc.position.set(2.15, 1.05, 1.95);
  reg(oltc, [0.3, 0, 1], 1.15, 'onLoadTapChanger', 'ON-LOAD TAP CHANGER');

  const drive = new THREE.Group();
  drive.add(at(box(0.62, 0.62, 0.5, matBody), 'oltcDriveBox', 0, 0.31, 0));
  const motor = cyl(0.17, 0.17, 0.42, matSteel, 14);
  motor.rotation.z = Math.PI / 2;
  motor.material = matMotor;
  drive.add(at(motor, 'oltcDriveMotor', -0.45, 0.31, 0));
  drive.add(at(box(0.2, 0.14, 0.02, matYellow), 'driveLabel', 0, 0.42, 0.26));
  drive.position.set(1.3, 1.5, 2.1);
  reg(drive, [0.1, -0.25, 1], 1.0, 'oltcDriveMechanism', 'OLTC DRIVE MECHANISM');

  // ================= marshalling box + cable boxes =================
  const marshal = new THREE.Group();
  marshal.add(at(box(1.25, 1.95, 0.48, matBody), 'marshallingCabinet', 0, 0.98, 0));
  marshal.add(at(box(0.02, 1.75, 0.02, matBlack), 'cabinetDoorSeam', 0, 0.98, 0.25));
  marshal.add(at(box(0.05, 0.24, 0.06, matAlu), 'cabinetHandle', 0.14, 0.98, 0.27));
  [0.34, 1.6].forEach((y, i) => marshal.add(at(box(0.07, 0.11, 0.07, matSteel), 'cabinetHinge' + i, -0.59, y, 0.23)));
  for (let i = 0; i < 4; i++) marshal.add(at(box(0.46, 0.03, 0.02, matBlack), 'cabinetLouver', -0.3, 0.3 + i * 0.1, 0.26));
  marshal.add(at(box(0.18, 0.18, 0.02, matYellow), 'warningLabel', -0.4, 1.6, 0.26));
  marshal.add(at(box(0.24, 0.14, 0.03, matRed), 'nameplate', 0.36, 1.62, 0.25));
  marshal.position.set(-0.55, 1.25, 1.72);
  reg(marshal, [0, 0, 1], 1.15, 'marshallingControlBox', 'MARSHALLING / CONTROL BOX');

  const hvBox = box(0.95, 1.05, 0.55, matBody);
  hvBox.position.set(-2.05, 1.9, 1.75);
  reg(hvBox, [-0.3, 0.1, 1], 1.0, 'hvCableBox', 'HV CABLE BOX');
  const logoTex = new THREE.TextureLoader().load('/static/img/landing/algihaz-logo-alpha.png');
  logoTex.colorSpace = THREE.SRGBColorSpace;
  logoTex.anisotropy = 4;
  const logoPlate = new THREE.Mesh(new THREE.PlaneGeometry(0.74, 0.368), new THREE.MeshStandardMaterial({
    name: 'algihazLogoDecal', map: logoTex, transparent: true, roughness: 0.45, metalness: 0.05,
  }));
  logoPlate.position.set(0, 0.16, 0.281);
  logoPlate.name = 'algihazLogoPlate';
  hvBox.add(logoPlate);
  const logoBack = new THREE.Mesh(new THREE.PlaneGeometry(0.86, 0.46), new THREE.MeshStandardMaterial({ name: 'logoBacking', color: 0xe8e6e0, roughness: 0.45, metalness: 0.05 }));
  logoBack.position.set(0, 0.16, 0.277);
  logoBack.name = 'algihazLogoBacking';
  hvBox.add(logoBack);
  const lvBox = box(0.75, 0.65, 0.5, matBody);
  lvBox.position.set(0.75, 1.35, 1.78);
  reg(lvBox, [0.15, -0.15, 1], 0.95, 'lvCableBox', 'LV CABLE BOX');

  // ================= piping, valves, pumps =================
  const pipes = new THREE.Group();
  [-1.85, 1.85].forEach((z) => {
    const runP = cyl(0.12, 0.12, 5.4, matSteel, 14);
    runP.rotation.z = Math.PI / 2;
    pipes.add(at(runP, 'oilPipeRun', 0, 1.0, z));
  });
  [-2.7, 2.7].forEach((x) => {
    const cross = cyl(0.12, 0.12, 3.7, matSteel, 14);
    cross.rotation.x = Math.PI / 2;
    pipes.add(at(cross, 'oilPipeCross', x, 1.0, 0));
  });
  [[-2.7, 1.85], [2.7, 1.85], [-2.7, -1.85], [2.7, -1.85]].forEach(([x, z], i) => {
    const elbow = new THREE.Mesh(new THREE.SphereGeometry(0.14, 12, 10), matSteel);
    pipes.add(at(elbow, 'pipeElbow' + i, x, 1.0, z));
  });
  [-1.6, 0.6, 2.0].forEach((x, i) => [-1.85, 1.85].forEach((z) => {
    const fl = cyl(0.18, 0.18, 0.06, matSteel, 12);
    fl.rotation.z = Math.PI / 2;
    pipes.add(at(fl, 'pipeFlange' + i, x, 1.0, z));
  }));
  reg(pipes, [0, -0.5, 0.4], 0.9, 'oilPipework', 'VALVES / PIPING');

  const valves = new THREE.Group();
  [[-2.2, 1.85], [0.1, 1.85], [2.2, 1.85], [-2.7, -1.0]].forEach(([x, z], i) => {
    const body2 = cyl(0.17, 0.17, 0.26, matBrass, 14);
    valves.add(at(body2, 'valveBody' + i, x, 1.32, z));
    valves.add(at(cyl(0.04, 0.04, 0.16, matValveRed, 8), 'valveStem' + i, x, 1.44, z));
    const wheelM = new THREE.Mesh(new THREE.TorusGeometry(0.14, 0.025, 6, 16), matValveRed);
    wheelM.rotation.x = Math.PI / 2;
    valves.add(at(wheelM, 'valveHandwheel' + i, x, 1.5, z));
  });
  reg(valves, [0.25, -0.3, 0.9], 1.0, 'valvesAccessories', 'VALVES & ACCESSORIES');

  const pumps = new THREE.Group();
  [-1.4, 0.9].forEach((x, i) => {
    const body3 = cyl(0.2, 0.2, 0.46, matSteel, 16);
    body3.rotation.z = Math.PI / 2;
    pumps.add(at(body3, 'oilPumpBody' + i, x, 1.0, 1.85));
    const mtr = cyl(0.15, 0.15, 0.34, matMotor, 14);
    mtr.rotation.z = Math.PI / 2;
    pumps.add(at(mtr, 'oilPumpMotor' + i, x + 0.38, 1.0, 1.85));
  });
  reg(pumps, [0, -0.35, 1], 1.0, 'oilPumps', 'OIL PUMPS');

  // ================= conservator + buchholz =================
  const cons = new THREE.Group();
  const consTank = cyl(0.56, 0.56, 3.0, matBody, 24);
  consTank.rotation.z = Math.PI / 2;
  cons.add(at(consTank, 'conservatorTank', 0, 5.5, 0));
  [-1.5, 1.5].forEach((x) => {
    const cap = new THREE.Mesh(new THREE.SphereGeometry(0.56, 20, 12, 0, Math.PI * 2, 0, Math.PI / 2), matBody);
    cap.rotation.z = x < 0 ? Math.PI / 2 : -Math.PI / 2;
    cons.add(at(cap, 'conservatorEndCap', x, 5.5, 0));
  });
  const oli = cyl(0.2, 0.2, 0.09, matSteel, 16);
  oli.rotation.z = Math.PI / 2;
  cons.add(at(oli, 'oilLevelIndicator', 1.55, 5.5, 0));
  [-1.15, 1.15].forEach((x) => {
    [-0.72, 0.72].forEach((z) => cons.add(at(box(0.16, 4.1, 0.16, matSteel), 'conservatorFrameLeg', x, 2.85, z)));
    const brace = box(0.1, 3.9, 0.1, matSteel);
    brace.rotation.x = 0.36;
    cons.add(at(brace, 'conservatorFrameBrace', x, 2.85, 0));
  });
  [4.85, 3.2].forEach((y) => [-0.72, 0.72].forEach((z) => cons.add(at(box(2.6, 0.14, 0.14, matSteel), 'conservatorFrameBeam', 0, y, z))));
  cons.add(at(cyl(0.09, 0.09, 1.0, matSteel, 12), 'breatherPipe', 1.35, 4.9, 0.35));
  cons.add(at(cyl(0.15, 0.15, 0.55, matWhite, 14), 'breather', 1.35, 4.15, 0.35));
  cons.add(at(cyl(0.17, 0.17, 0.14, matBrass, 14), 'breatherOilCup', 1.35, 3.85, 0.35));
  [-0.95, 0.95].forEach((x, i) => cons.add(at(box(0.3, 0.28, 1.25, matSteel), 'conservatorSaddle' + i, x, 5.02, 0)));
  cons.add(at(cyl(0.13, 0.13, 0.18, matBrass, 14), 'conservatorFillerCap', -0.55, 6.12, 0));
  for (let i = 0; i < 7; i++) cons.add(at(box(0.06, 0.05, 1.44, matSteel), 'frameLadderRung', 1.15, 1.2 + i * 0.52, 0));
  cons.add(at(cyl(0.13, 0.13, 0.06, matWhite, 16), 'oilGaugeFace', 1.61, 5.5, 0));
  cons.position.set(-3.3, 0, 0);
  reg(cons, [-0.8, 0.5, 0], 1.3, 'conservatorAssembly', 'CONSERVATOR TANK');

  const buch = new THREE.Group();
  const runB = cyl(0.11, 0.11, 1.9, matSteel, 12);
  runB.rotation.z = Math.PI / 2 - 0.25;
  buch.add(at(runB, 'conservatorPipe', -2.6, 4.85, 0));
  buch.add(at(box(0.36, 0.34, 0.36, matAlu), 'buchholzRelayBody', -1.95, 4.62, 0));
  buch.add(at(cyl(0.11, 0.11, 0.6, matSteel, 12), 'buchholzDownPipe', -1.75, 4.4, 0));
  reg(buch, [-0.5, 0.8, 0.1], 1.1, 'buchholzRelay', 'BUCHHOLZ RELAY');

  // ================= earthing terminals =================
  const earth = new THREE.Group();
  [[0.2, 1.9], [-2.4, -1.9]].forEach(([x, z], i) => {
    earth.add(at(box(0.3, 0.12, 0.3, matCopper), 'earthingPad' + i, x, 0.9, z));
    earth.add(at(cyl(0.05, 0.05, 0.5, matCopper, 10), 'earthingStrap' + i, x, 0.62, z));
  });
  reg(earth, [0.2, -0.9, 0.4], 0.9, 'earthingTerminals', 'EARTHING TERMINALS');

  root.traverse((o) => { if (o.isMesh) { o.castShadow = true; o.receiveShadow = true; } });
  logoPlate.castShadow = false; logoBack.castShadow = false;

  // ================= electric arcs between parts =================
  const anchor = (part, x, y, z) => { const o = new THREE.Object3D(); o.position.set(x, y, z); part.add(o); return o; };
  const arcDefs = [
    ['bushingHV1', [0, 0.15, 0], 'tankCover', [-1.75, 4.34, -0.85]],
    ['bushingHV2', [0, 0.15, 0], 'tankCover', [-0.35, 4.34, -0.85]],
    ['bushingHV3', [0, 0.15, 0], 'tankCover', [1.05, 4.34, -0.85]],
    ['bushingLV1', [0, 0.12, 0], 'tankCover', [0.85, 4.34, 0.85]],
    ['bushingLV2', [0, 0.12, 0], 'tankCover', [1.65, 4.34, 0.85]],
    ['bushingLV3', [0, 0.12, 0], 'tankCover', [2.45, 4.34, 0.85]],
    ['bushingNeutral', [0, 0.1, 0], 'tankCover', [-2.25, 4.34, 0.9]],
    ['tankCover', [0, 4.1, 0], 'coreAndWindings', [0, 3.66, 0]],
    ['coreAndWindings', [-1.68, 2.4, 0], 'tankWallFront', [-1.68, -0.05, -0.1]],
    ['coreAndWindings', [1.68, 2.4, 0], 'tankWallBack', [1.68, -0.05, 0.1]],
    ['coreAndWindings', [-1.68, 2.4, 0], 'tankWallLeft', [0.08, -0.05, 0]],
    ['coreAndWindings', [1.68, 2.4, 0], 'tankWallRight', [-0.08, -0.05, 0]],
    ['radiatorBankL', [0.2, 2.5, 0], 'tankWallLeft', [-0.08, 0.05, 0]],
    ['radiatorBankR', [-0.2, 2.5, 0], 'tankWallRight', [0.08, 0.05, 0]],
    ['conservatorAssembly', [1.35, 4.35, 0.35], 'buchholzRelay', [-1.95, 4.62, 0]],
    ['buchholzRelay', [-1.72, 4.15, 0], 'tankCover', [-1.72, 4.34, 0]],
    ['onLoadTapChanger', [0, 2.3, -0.5], 'tankWallFront', [2.15, 0.9, 0.12]],
    ['marshallingControlBox', [0, 1.0, -0.28], 'tankWallFront', [-0.55, -0.2, 0.12]],
    ['oilPumps', [0.9, 1.0, 1.85], 'oilPipework', [0.6, 1.0, 1.85]],
    ['earthingTerminals', [0.2, 0.85, 1.9], 'baseFrame', [0.2, 0.72, 1.5]],
    ['coolingFanR1', [0, 0, -0.2], 'radiatorBankR', [0.9, 1.45, 0]],
    ['coolingFanL4', [0, 0, -0.2], 'radiatorBankL', [-0.9, 3.7, 0]],
    ['hvCableBox', [0, 0.3, -0.3], 'tankWallFront', [-2.05, -0.55, 0.12]],
    ['lvCableBox', [0, 0.2, -0.3], 'tankWallFront', [0.75, -1.1, 0.12]],
    ['radiatorPlateL3', [0, 0, 0.8], 'radiatorBankL', [-0.6, 2.5, 0.9]],
    ['radiatorPlateL8', [0, 0, -0.8], 'radiatorBankL', [-1.2, 2.5, -0.9]],
    ['radiatorPlateR3', [0, 0, 0.8], 'radiatorBankR', [0.6, 2.5, 0.9]],
    ['radiatorPlateR8', [0, 0, -0.8], 'radiatorBankR', [1.2, 2.5, -0.9]],
    ['coolingFanR3', [0, 0, -0.25], 'radiatorBankR', [1.0, 2.95, 0]],
    ['coolingFanL2', [0, 0, -0.25], 'radiatorBankL', [-1.0, 2.2, 0]],
    ['valvesAccessories', [0.1, 1.4, 1.85], 'oilPipework', [-0.4, 1.0, 1.85]],
    ['wheelsRollers', [-2.7, 0.45, 1.5], 'baseFrame', [-2.7, 0.55, 1.5]],
    ['tankFloor', [0, 1.0, 0], 'coreAndWindings', [0, 1.4, 0]],
    ['oltcDriveMechanism', [0, 0.4, -0.2], 'onLoadTapChanger', [-0.5, 1.0, 0]],
    ['bushingHV2', [0, 2.9, 0], 'bushingHV3', [0, 2.9, 0]],
    ['bushingHV1', [0, 2.9, 0], 'bushingHV2', [0, 2.9, 0]],
  ];
  const ARC_SEGS = 15;
  const arcs = arcDefs.map(([an, ap, bn, bp]) => {
    const A = byName[an], B = byName[bn];
    if (!A || !B) return null;
    const layers = [
      { color: 0xffffff, jit: 0.09, gain: 1.0 },
      { color: 0x9ad8ff, jit: 0.2, gain: 0.8 },
      { color: 0x4f9bff, jit: 0.34, gain: 0.5 },
    ].map((cfg) => {
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array((ARC_SEGS + 1) * 3), 3));
      const mat = new THREE.LineBasicMaterial({ color: cfg.color, transparent: true, opacity: 0, blending: THREE.AdditiveBlending, depthWrite: false });
      const line = new THREE.Line(geo, mat);
      line.name = 'electricArc';
      line.frustumCulled = false;
      scene.add(line);
      return { geo, mat, jit: cfg.jit, gain: cfg.gain };
    });
    return { a: anchor(A, ap[0], ap[1], ap[2]), b: anchor(B, bp[0], bp[1], bp[2]), layers };
  }).filter(Boolean);

  const tetherGeo = new THREE.BufferGeometry();
  tetherGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(explodables.length * 6), 3));
  const tetherMat = new THREE.LineBasicMaterial({ color: 0x2b2723, transparent: true, opacity: 0 });
  const tethers = new THREE.LineSegments(tetherGeo, tetherMat);
  tethers.frustumCulled = false;
  tethers.name = 'partTetherLines';
  root.add(tethers);
  const tw = new THREE.Vector3();
  const updateTethers = (vis) => {
    const arr = tetherGeo.attributes.position.array;
    explodables.forEach((o, i) => {
      const u = o.userData;
      o.getWorldPosition(tw);
      root.worldToLocal(tw);
      const dx = tw.x - o.position.x, dy = tw.y - o.position.y, dz = tw.z - o.position.z;
      arr[i * 6] = u.origin.x + dx; arr[i * 6 + 1] = u.origin.y + dy; arr[i * 6 + 2] = u.origin.z + dz;
      arr[i * 6 + 3] = tw.x; arr[i * 6 + 4] = tw.y; arr[i * 6 + 5] = tw.z;
    });
    tetherGeo.attributes.position.needsUpdate = true;
    tetherMat.opacity = vis;
  };

  const va = new THREE.Vector3(), vb = new THREE.Vector3(), vd = new THREE.Vector3();
  const p1 = new THREE.Vector3(), p2 = new THREE.Vector3(), pt = new THREE.Vector3();
  const worldUp = new THREE.Vector3(0, 1, 0);
  const updateArcs = (energy) => {
    arcs.forEach((arc) => {
      arc.a.getWorldPosition(va); arc.b.getWorldPosition(vb);
      vd.subVectors(vb, va);
      const len = vd.length();
      p1.crossVectors(vd, worldUp);
      if (p1.lengthSq() < 1e-6) p1.set(1, 0, 0);
      p1.normalize();
      p2.crossVectors(vd, p1).normalize();
      const flick = Math.random() < 0.1 ? 0.3 : 0.7 + Math.random() * 0.3;
      arc.layers.forEach((L) => {
        const pos = L.geo.attributes.position.array;
        const jit = len * L.jit;
        for (let i = 0; i <= ARC_SEGS; i++) {
          const fr = i / ARC_SEGS;
          const edge = i === 0 || i === ARC_SEGS ? 0 : Math.sin(fr * Math.PI);
          pt.copy(va).addScaledVector(vd, fr)
            .addScaledVector(p1, (Math.random() - 0.5) * jit * edge)
            .addScaledVector(p2, (Math.random() - 0.5) * jit * edge);
          pos[i * 3] = pt.x; pos[i * 3 + 1] = pt.y; pos[i * 3 + 2] = pt.z;
        }
        L.geo.attributes.position.needsUpdate = true;
        L.mat.opacity = Math.min(1, energy * flick * L.gain * (0.75 + len * 0.3));
      });
    });
  };

  // ---------- curated, physically logical motion ----------
  const ZERO = [0, 0, 0];
  const motionRule = (o) => {
    const n = o.name, sx = Math.sign(o.position.x) || 1;
    if (n === 'baseFrame' || n === 'wheelsRollers') return [ZERO, 0, ZERO, 0];
    if (/^coolingFan/.test(n)) return [ZERO, 0, ZERO, 0];
    if (/^radiatorPlate/.test(n)) return [o.userData.dir.toArray(), 0.5, ZERO, 0];
    if (/^radiatorBank/.test(n)) return [[sx, 0, 0], 3.0, [sx, 0, 0], 1.1];
    if (/^bushingHV/.test(n)) return [[0, 1, 0.1], 3.7, [0, 1, 0], 1.5];
    if (/^bushingLV/.test(n)) return [[0, 1, -0.1], 2.9, [0, 1, 0], 1.2];
    if (n === 'bushingNeutral') return [[-0.15, 1, 0], 2.5, [0, 1, 0], 1.0];
    if (n === 'tankCover') return [[0, 1, 0], 2.9, [0, 1, 0], 2.6];
    if (n === 'tankWallFront') return [[0, 0, 1], 2.9, [0, 0, 1], 3.1];
    if (n === 'tankWallBack') return [[0, 0, -1], 2.9, [0, 0, -1], 3.1];
    if (n === 'tankWallLeft') return [[-1, 0, 0], 2.5, [-1, 0, 0], 2.7];
    if (n === 'tankWallRight') return [[1, 0, 0], 2.5, [1, 0, 0], 2.7];
    if (n === 'tankFloor') return [[0, -1, 0], 1.3, [0, -1, 0], 1.0];
    if (n === 'coreAndWindings') return [[0, 0.6, 0], 0.55, [0, 0.45, 0], 0.6];
    if (n === 'conservatorAssembly') return [[-0.55, 0.9, 0], 2.7, ZERO, 0];
    if (n === 'buchholzRelay') return [[-0.3, 1, 0.2], 2.3, ZERO, 0];
    if (n === 'onLoadTapChanger') return [[0.35, 0, 1], 2.5, ZERO, 0];
    if (n === 'oltcDriveMechanism') return [[0.2, 0, 1], 2.7, ZERO, 0];
    if (n === 'marshallingControlBox' || n === 'hvCableBox' || n === 'lvCableBox') return [[0, 0, 1], 2.2, ZERO, 0];
    if (n === 'oilPipework' || n === 'valvesAccessories' || n === 'oilPumps') return [[0, -0.3, 1], 2.0, ZERO, 0];
    if (n === 'earthingTerminals') return [[0.2, -0.9, 0.4], 1.4, ZERO, 0];
    return [o.userData.dir.toArray(), 1.5, ZERO, 0];
  };
  explodables.forEach((o) => {
    const [ex, exM, ins, insM] = motionRule(o);
    o.userData.exDir = new THREE.Vector3(ex[0], ex[1], ex[2]);
    if (o.userData.exDir.lengthSq() > 0) o.userData.exDir.normalize();
    o.userData.exMag = exM;
    o.userData.inDir = new THREE.Vector3(ins[0], ins[1], ins[2]);
    if (o.userData.inDir.lengthSq() > 0) o.userData.inDir.normalize();
    o.userData.inMag = insM;
  });

  // tank shell gets its own material instances so INSIDE can fade them
  const shellMats = [];
  ['tankWallFront', 'tankWallBack', 'tankWallLeft', 'tankWallRight', 'tankFloor'].forEach((n) => {
    const g = byName[n];
    if (!g) return;
    g.traverse((m) => {
      if (!m.isMesh) return;
      m.material = m.material.clone();
      m.material.transparent = true;
      shellMats.push(m.material);
    });
  });

  // highlight material variants, cached per source material
  const hiCache = new Map();
  const highlightOf = (mat, strong) => {
    const k = mat.uuid + (strong ? '_s' : '_h');
    if (hiCache.has(k)) return hiCache.get(k);
    const c = mat.clone();
    c.emissive = new THREE.Color(strong ? 0x3a0d05 : 0x1c1a17);
    c.emissiveIntensity = strong ? 1.0 : 0.7;
    if (c.color) c.color.multiplyScalar(strong ? 1.22 : 1.12);
    hiCache.set(k, c);
    return c;
  };
  const applyHighlight = (group, strong) => {
    if (!group) return;
    group.traverse((m) => {
      if (!m.isMesh) return;
      if (!m.userData.baseMat) m.userData.baseMat = m.material;
      m.material = highlightOf(m.userData.baseMat, strong);
    });
  };
  const clearHighlight = (group) => {
    if (!group) return;
    group.traverse((m) => { if (m.isMesh && m.userData.baseMat) m.material = m.userData.baseMat; });
  };

  // ---------- camera controls ----------
  controls = new OrbitControls(camera, parent);
  controls.enableDamping = true;
  controls.dampingFactor = 0.075;
  controls.rotateSpeed = 0.5;
  controls.enablePan = false;
  controls.enableZoom = false;
  controls.minDistance = 10;
  controls.maxDistance = 52;
  controls.minPolarAngle = 0.38;
  controls.maxPolarAngle = 1.44;
  controls.target.copy(camTarget0);
  controls.enabled = !state.isTouch;
  let dragging = false;
  controls.addEventListener('start', () => { dragging = true; freeCam = true; });
  controls.addEventListener('end', () => { dragging = false; });
  applyControlMode = () => {
    const ex = state.exploring;
    controls.enableZoom = !!ex;
    controls.enabled = ex ? true : !state.isTouch;
  };

  const goalPos = new THREE.Vector3().copy(camera.position);
  const goalTgt = new THREE.Vector3().copy(camTarget0);
  const va2 = new THREE.Vector3(), vb2 = new THREE.Vector3();
  const setSectionGoal = () => {
    const narrow = (window.innerWidth || 1200) <= 1000;
    const f = sectionF;
    const i = Math.max(0, Math.min(SECTION_VIEWS.length - 1, Math.floor(f)));
    const j = Math.min(SECTION_VIEWS.length - 1, i + 1);
    const t = f - i;
    va2.fromArray(SECTION_VIEWS[i].pos); vb2.fromArray(SECTION_VIEWS[j].pos);
    goalPos.lerpVectors(va2, vb2, t);
    va2.fromArray(SECTION_VIEWS[i].tgt); vb2.fromArray(SECTION_VIEWS[j].tgt);
    goalTgt.lerpVectors(va2, vb2, t);
    if (narrow) {
      goalPos.multiplyScalar(1.16);
      goalTgt.x -= 1.2;
      goalTgt.y += 1.1;
    }
  };
  const bb = new THREE.Box3(), bc = new THREE.Vector3(), bs = new THREE.Vector3(), dirv = new THREE.Vector3();
  focusOnPart = (name) => {
    const o = byName[name];
    if (!o) return;
    bb.setFromObject(o);
    bb.getCenter(bc); bb.getSize(bs);
    dirv.copy(camera.position).sub(controls.target);
    if (dirv.lengthSq() < 1e-4) dirv.set(1, 0.6, 1);
    dirv.normalize();
    goalTgt.copy(bc);
    goalPos.copy(bc).addScaledVector(dirv, Math.max(7.5, bs.length() * 2.3));
    freeCam = false;
  };
  resetCamera = () => {
    freeCam = false;
    controls.minDistance = 10;
    setSectionGoal();
  };
  zoomInside = () => {
    const o = byName['coreAndWindings'];
    freeCam = false;
    controls.minDistance = 1.5;
    if (!o) return;
    bb.setFromObject(o);
    bb.getCenter(bc); bb.getSize(bs);
    dirv.set(0.62, 0.3, 0.72).normalize();
    goalTgt.copy(bc);
    goalPos.copy(bc).addScaledVector(dirv, Math.max(3.4, bs.length() * 0.34));
  };

  // ---------- picking ----------
  const raycaster = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  let hovered = null;
  pickAt = () => {
    ndc.set(mouse.x, -mouse.y);
    raycaster.setFromCamera(ndc, camera);
    const hits = raycaster.intersectObjects(root.children, true);
    if (!hits.length) return null;
    let o = hits[0].object;
    while (o && o !== root) {
      if (o.userData && o.userData.exDir) return o;
      o = o.parent;
    }
    return null;
  };
  const setHover = (found) => {
    if (found === hovered) return;
    if (hovered && hovered.name !== state.selected) clearHighlight(hovered);
    hovered = found;
    const labelEl = els.label, txt = els.labelText, cat = els.labelCat;
    if (found) {
      if (found.name !== state.selected) applyHighlight(found, false);
      const info = COMPONENT_INFO[found.name];
      if (txt) txt.textContent = info ? info.title.toUpperCase() : found.userData.label;
      if (cat) cat.textContent = info ? info.category : 'ASSEMBLY';
      if (labelEl) labelEl.style.opacity = '1';
      document.body.style.cursor = 'pointer';
    } else {
      if (labelEl) labelEl.style.opacity = '0';
      document.body.style.cursor = '';
    }
  };
  setHoverNull = () => setHover(null);
  syncSelectionVisual = (prevName, nextName) => {
    if (prevName && byName[prevName]) clearHighlight(byName[prevName]);
    if (nextName && byName[nextName]) applyHighlight(byName[nextName], true);
  };

  // pointer handling — listened on the window, because the full-page sections
  // wrapper sits above the canvas and would otherwise swallow every event
  const uiHit = (t) => !!(t && t.closest && t.closest('button, a, input, label, form, textarea, select'));
  const track = (e) => {
    const rect = canvas.getBoundingClientRect();
    const px = e.clientX - rect.left, py = e.clientY - rect.top;
    const within = px >= 0 && py >= 0 && px <= rect.width && py <= rect.height;
    const dpx = px - mouse.px, dpy = py - mouse.py;
    mouseSpeed = Math.min(1, (mouseSpeed || 0) * 0.7 + Math.hypot(dpx, dpy) / 45);
    mouse.px = px;
    mouse.py = py;
    mouse.x = (px / rect.width) * 2 - 1;
    mouse.y = (py / rect.height) * 2 - 1;
    mouse.inside = within && !uiHit(e.target);
    return within;
  };
  onWinMove = (e) => {
    const was = mouse.inside;
    track(e);
    if (was && !mouse.inside) setHover(null);
  };
  onWinDown = (e) => { downX = e.clientX; downY = e.clientY; downT = performance.now(); };
  onWinUp = (e) => {
    if (uiHit(e.target)) return;
    const moved = Math.hypot(e.clientX - downX, e.clientY - downY);
    if (moved > 6 || performance.now() - downT > 600) return;
    if (!track(e) || !mouse.inside) return;
    const found = pickAt();
    if (found) exploreTo(found.name);
    else if (state.selected) clearSelection();
  };
  onWinOut = () => { mouse.inside = false; mouseSpeed = 0; setHover(null); };
  window.addEventListener('blur', onWinOut);
  document.addEventListener('pointerleave', onWinOut);
  window.addEventListener('pointermove', onWinMove, { passive: true });
  window.addEventListener('pointerdown', onWinDown, { passive: true });
  window.addEventListener('pointerup', onWinUp, { passive: true });
  onKey = (e) => {
    if (e.key !== 'Escape') return;
    if (state.signinOpen) { closeSignin(); return; }
    if (state.exploring) onExitExplore();
  };
  window.addEventListener('keydown', onKey);

  const resize = () => {
    const w = parent.clientWidth, h = parent.clientHeight;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };
  resizeFn = resize;
  resize();
  ro = new ResizeObserver(resize);
  ro.observe(parent);
  document.addEventListener('visibilitychange', resizeCanvasIfNeeded);
  const ensureSize = () => {
    const dpr = renderer.getPixelRatio();
    const w = Math.round(parent.clientWidth * dpr), h = Math.round(parent.clientHeight * dpr);
    if (w && h && (canvas.width !== w || canvas.height !== h)) resize();
  };

  setSectionGoal();

  const animate = () => {
    if (stopped) return;
    requestAnimationFrame(animate);
    try { frameBody(); } catch (err) { if (!animate._logged) { animate._logged = 1; console.error(err); } }
  };

  const frameBody = () => {
    frameCount++;
    if (frameCount % 15 === 0) ensureSize();

    const nowMs = performance.now();
    const dt = Math.min(0.05, lastMs ? (nowMs - lastMs) / 1000 : 0.016);
    lastMs = nowMs;
    clock = (clock || 0) + dt;
    const elT = clock;
    const intro = Math.min(1, elT / 3.0);

    if (mouse.inside && !dragging && frameCount % 3 === 0) setHover(pickAt());
    const lbl = els.label;
    if (lbl && lbl.style.opacity === '1') lbl.style.transform = 'translate(' + (mouse.px + 20) + 'px,' + (mouse.py - 40) + 'px)';

    const view = viewOverride || SECTION_VIEWS[section].view;
    explodeTarget = view === 'exploded' ? 1 : 0;
    insideTarget = view === 'inside' ? 1 : 0;
    hoverTarget = (hovered && !state.signinOpen) ? 1 : 0;
    focusTarget = state.selected ? 1 : 0;

    hover += (hoverTarget - hover) * 0.06;
    explode += (explodeTarget - explode) * 0.045;
    insideAmt += (insideTarget - insideAmt) * 0.045;
    focus += (focusTarget - focus) * 0.06;
    outro += (outroTarget - outro) * 0.055;

    const selName = state.selected;
    explodables.forEach((o) => {
      const u = o.userData;
      const isSel = o.name === selName;
      const soloTarget = (o === hovered || isSel) ? 1 : 0;
      u.solo += (soloTarget - u.solo) * 0.1;
      const idle = (0.16 + 0.12 * Math.sin(elT * 0.5 + u.phase)) * (1 - explode * 0.6);
      const raw = Math.min(1, Math.max(0, (elT - u.delay) / 1.7));
      const introP = 1 - Math.pow(1 - raw, 3);
      o.position.copy(u.origin)
        .addScaledVector(u.dir, u.mag * (idle + hover * 1.25 + u.solo * (isSel ? 0.9 : 0.7)) + Math.max(1 - introP, outro * 1.3) * u.introDist)
        .addScaledVector(u.exDir, u.exMag * explode)
        .addScaledVector(u.inDir, u.inMag * insideAmt);
      const sc = 1 + u.solo * (isSel ? 0.04 : 0.015);
      o.scale.setScalar(sc);
      const rk = Math.max(1 - introP, outro);
      if (rk > 0.001) {
        u.settled = false;
        o.rotation.set(u.baseRot.x + u.introRot.x * rk, u.baseRot.y + u.introRot.y * rk, u.baseRot.z + u.introRot.z * rk);
      } else if (!u.settled) { u.settled = true; o.rotation.copy(u.baseRot); }
    });

    const shellFade = Math.max(0.06, 1 - insideAmt * 0.62 - outro * 0.8);
    shellMats.forEach((m) => { m.opacity = shellFade; });

    // restrained arcs: intro, explode, inside and selection only
    const energy = Math.max(0, (1 - intro) * 1.15) + outro * 1.0 + hover * 0.85 + explode * 0.42 + insideAmt * 0.3 + focus * 0.16;
    if (energy > 0.02 && frameCount % 2 === 0) updateArcs(Math.min(1.2, energy));
    else if (energy <= 0.02 && frameCount % 2 === 0) updateArcs(0);
    updateTethers(Math.min(0.5, hover * 0.45 + explode * 0.4 + insideAmt * 0.3 + (1 - intro) * 0.2));

    const spin = 0.05 + hover * 0.2 + explode * 0.15;
    fans.forEach((f) => { f.rotation.z += spin; });

    // dim the rest slightly while inspecting
    const dim = 1 - focus * 0.2;
    key.intensity = 2.15 * dim;
    hemi.intensity = 0.42 * dim;
    scene.environmentIntensity = 0.42 * dim;

    if (audio && audio.on) {
      const a = audio, ct = a.ctx.currentTime;
      const drive = hover * Math.min(1, (mouseSpeed || 0) * 1.7);
      if (frameCount % 6 === 0) {
        const bed = drive * 0.085 + explode * 0.05;
        const bz = drive * 0.035;
        // Always ramp (setTargetAtTime), never snap straight to 0 -- an
        // instant setValueAtTime jump from an audible level is a real
        // discontinuity (a click/pop), which read as "the background
        // stopping and resetting" the moment hover+motion dropped out.
        // A short exponential ramp reaches inaudible in a couple hundred
        // ms either way, so this doesn't leave a lingering trail.
        a.bedGain.gain.setTargetAtTime(bed, ct, bed < a.bedGain.gain.value ? 0.12 : 0.15);
        a.buzzGain.gain.setTargetAtTime(bz, ct, bz < a.buzzGain.gain.value ? 0.12 : 0.2);
        a.bp.frequency.setTargetAtTime(1700 + drive * 2600 + explode * 900, ct, 0.25);
      }
      const rate = hover * 2.6 + (mouseSpeed || 0) * hover * 7 + explode * 3 + outro * 4;
      sparkAcc = (sparkAcc || 0) + rate * 0.016;
      if (sparkAcc >= 1) {
        sparkAcc = 0;
        spark(0.3 + hover * 0.6 + (mouseSpeed || 0) * 0.5 + outro * 0.6);
      }
    }
    mouseSpeed = (mouseSpeed || 0) * 0.94;

    if (!freeCam) {
      if (!state.selected) setSectionGoal();
      camera.position.lerp(goalPos, 0.055);
      controls.target.lerp(goalTgt, 0.07);
    }
    controls.update();

    const wrap = els.sceneWrap;
    if (wrap) {
      wrap._parX = (wrap._parX || 0) + ((mouse.inside ? mouse.x : 0) - (wrap._parX || 0)) * 0.045;
      wrap._parY = (wrap._parY || 0) + ((mouse.inside ? mouse.y : 0) - (wrap._parY || 0)) * 0.045;
      wrap.style.transform = 'translate3d(' + (-wrap._parX * 22).toFixed(2) + 'px,' + (-wrap._parY * 14).toFixed(2) + 'px,0) scale(1.03)';
    }
    renderer.render(scene, camera);
  };

  // Warm up every material's shader program before the first frame, off the
  // 3-second intro assembly's critical path. Without this, the driver
  // compiles each of the ~15 PBR materials + shadow/tonemap variants lazily
  // on their first actual draw call -- which happens to land right in the
  // middle of the visible intro animation (elT/3.0 below is real elapsed
  // time, uncompensated for stalls), so the assembly looked laggy/dropped
  // frames right when it should have been smooth. compileAsync polls
  // compile status without blocking the main thread, unlike the older sync
  // compile().
  if (renderer.compileAsync) {
    try { await renderer.compileAsync(scene, camera); } catch (err) { /* fall through and animate anyway */ }
  }
  animate();
}

// ================================================================
// dust canvas (ported 1:1 from initDust())
// ================================================================
function initDust() {
  const c = els.dustCanvas;
  if (!c) return;
  const ctx = c.getContext('2d');
  const parent = c.parentElement;
  const grains = [];
  const small = Math.min(window.innerWidth, window.innerHeight) < 780;
  for (let i = 0; i < (small ? 120 : 300); i++) {
    grains.push({
      x: Math.random(), y: Math.random(),
      r: 0.35 + Math.random() * 1.9,
      sp: 0.0011 + Math.random() * 0.0055,
      drift: Math.random() * Math.PI * 2,
      a: 0.05 + Math.random() * 0.26,
      streak: Math.random() < 0.18,
    });
  }
  const size = () => {
    const w = parent.clientWidth, h = parent.clientHeight;
    if (!w || !h) return;
    const dpr = Math.min(window.devicePixelRatio || 1, Math.min(window.innerWidth, window.innerHeight) < 780 ? 1.5 : 2);
    c.width = Math.round(w * dpr);
    c.height = Math.round(h * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  };
  size();
  dustSizeFn = size;
  dustRo = new ResizeObserver(size);
  dustRo.observe(parent);
  document.addEventListener('visibilitychange', resizeDustIfNeeded);
  let n = 0;
  const draw = () => {
    if (stopped) return;
    requestAnimationFrame(draw);
    const w = parent.clientWidth, h = parent.clientHeight;
    if (!w || !h) return;
    if (++n % 15 === 0) {
      const dpr = Math.min(window.devicePixelRatio || 1, Math.min(window.innerWidth, window.innerHeight) < 780 ? 1.5 : 2);
      if (c.width !== Math.round(w * dpr) || c.height !== Math.round(h * dpr)) size();
    }
    ctx.clearRect(0, 0, w, h);
    const gust = 1 + 0.4 * Math.sin((clock || 0) * 0.32) + 0.2 * Math.sin((clock || 0) * 1.6);
    grains.forEach((g) => {
      g.x -= g.sp * gust;
      g.drift += 0.009;
      const y = g.y + Math.sin(g.drift) * 0.011;
      if (g.x < -0.05) { g.x = 1.05; g.y = Math.random(); }
      const px = g.x * w, py = y * h;
      ctx.globalAlpha = g.a * (0.5 + 0.5 * Math.sin(g.drift * 0.7));
      if (g.streak) {
        ctx.strokeStyle = 'rgba(226,208,178,0.8)';
        ctx.lineWidth = g.r * 0.55;
        ctx.beginPath(); ctx.moveTo(px, py); ctx.lineTo(px + 14 + g.r * 12 * gust, py + 1.4); ctx.stroke();
      } else {
        ctx.fillStyle = 'rgba(222,202,168,0.85)';
        ctx.beginPath(); ctx.arc(px, py, g.r, 0, Math.PI * 2); ctx.fill();
      }
    });
    ctx.globalAlpha = 1;
  };
  draw();
}

// ================================================================
// audio engine (ported 1:1 from initAudio/discharge/spark)
// ================================================================
function initAudio() {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx || audio) return;
  (window.__hvAudioAll || []).forEach((c) => { try { c.close(); } catch (e) {} });
  window.__hvAudioAll = [];
  window.__hvAudio = null;
  const ctx = new Ctx();
  const master = ctx.createGain();
  master.gain.value = 0.55;
  master.connect(ctx.destination);
  const noiseBuf = ctx.createBuffer(1, ctx.sampleRate * 2, ctx.sampleRate);
  const nd = noiseBuf.getChannelData(0);
  for (let i = 0; i < nd.length; i++) nd[i] = Math.random() * 2 - 1;
  const noise = ctx.createBufferSource();
  noise.buffer = noiseBuf; noise.loop = true;
  const bp = ctx.createBiquadFilter();
  bp.type = 'bandpass'; bp.frequency.value = 2000; bp.Q.value = 0.9;
  const hp = ctx.createBiquadFilter();
  hp.type = 'highpass'; hp.frequency.value = 700;
  const bedGain = ctx.createGain();
  bedGain.gain.value = 0;
  noise.connect(bp); bp.connect(hp); hp.connect(bedGain); bedGain.connect(master);
  noise.start();
  const buzz = ctx.createOscillator();
  buzz.type = 'sawtooth'; buzz.frequency.value = 118;
  const buzzBp = ctx.createBiquadFilter();
  buzzBp.type = 'bandpass'; buzzBp.frequency.value = 1100; buzzBp.Q.value = 2.2;
  const buzzGain = ctx.createGain();
  buzzGain.gain.value = 0;
  buzz.connect(buzzBp); buzzBp.connect(buzzGain); buzzGain.connect(master);
  buzz.start();
  const spaceGain = ctx.createGain();
  spaceGain.gain.value = 0;
  spaceGain.connect(master);
  audio = { ctx, master, bedGain, buzzGain, bp, spaceGain, on: true };
  window.__hvAudio = audio;
  (window.__hvAudioAll = window.__hvAudioAll || []).push(ctx);
  fetch('/static/audio/electric-shock.mp3')
    .then((r) => r.arrayBuffer())
    .then((b) => ctx.decodeAudioData(b))
    .then((buf) => { if (audio) audio.zapBuf = buf; })
    .catch(() => {});

  // Constant background ambience -- unlike bedGain/buzzGain (hover+motion
  // driven, silent at rest), this plays continuously at a fixed, low level
  // once unlocked, gated only by the master mute/unmute (toggleSound) and
  // by ctx.close() on teardown. space-ambience.mp3 is a pre-built seamless
  // loop (ffmpeg acrossfade of the tail back into the head), and looping
  // via AudioBufferSourceNode.loop is sample-accurate/gapless, unlike an
  // <audio loop> element. Kept quiet (0.04, well under bedGain's own
  // ~0.085-0.135 idle-interaction range and buzzGain/spark/discharge) so it
  // sits under the transformer's own interactive sounds, not over them --
  // lowered from an initial 0.06 once the longer replacement track read
  // louder than the original short one at the same gain value.
  fetch('/static/audio/space-ambience.mp3')
    .then((r) => r.arrayBuffer())
    .then((b) => ctx.decodeAudioData(b))
    .then((buf) => {
      if (!audio || stopped) return;
      const src = ctx.createBufferSource();
      src.buffer = buf; src.loop = true;
      src.connect(spaceGain);
      src.start();
      audio.spaceSource = src;
      spaceGain.gain.setValueAtTime(0, ctx.currentTime);
      spaceGain.gain.linearRampToValueAtTime(0.04, ctx.currentTime + 1.5);
    })
    .catch(() => {});

  if (ctx.state === 'suspended') ctx.resume();
}

function discharge() {
  const a = audio;
  if (!a || !a.on || !a.zapBuf) return;
  const ctx = a.ctx, t = ctx.currentTime;
  const dur = Math.min(1, a.zapBuf.duration);
  const src = ctx.createBufferSource();
  src.buffer = a.zapBuf;
  const g = ctx.createGain();
  g.gain.setValueAtTime(0.28, t);
  g.gain.setValueAtTime(0.28, t + dur - 0.09);
  g.gain.linearRampToValueAtTime(0, t + dur);
  src.connect(g); g.connect(a.master);
  src.start(t, 0, dur);
  src.onended = () => { try { g.disconnect(); } catch (e) {} };
}

function spark(intensity) {
  const a = audio;
  if (!a || !a.on) return;
  const ctx = a.ctx, t = ctx.currentTime;
  const dur = 0.04 + Math.random() * 0.11;
  const n = Math.ceil(ctx.sampleRate * dur);
  const buf = ctx.createBuffer(1, n, ctx.sampleRate);
  const d = buf.getChannelData(0);
  for (let i = 0; i < n; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / n, 2.2);
  const src = ctx.createBufferSource(); src.buffer = buf;
  const sbp = ctx.createBiquadFilter();
  sbp.type = 'bandpass'; sbp.frequency.value = 1600 + Math.random() * 4800; sbp.Q.value = 1.1;
  const g = ctx.createGain(); g.gain.value = 0.1 * intensity;
  src.connect(sbp); sbp.connect(g); g.connect(a.master);
  src.start(t);
}

// Auto-mount on module load -- this IS the first thing visible on every
// page load (confirmed with Yasser: landing shows every visit, no skip
// flag), so building the scene immediately on mount is already "only
// when visible", no separate lazy-init trigger needed.
mount();
