import * as THREE from "three";
import { OrbitControls } from "./vendor/OrbitControls.js";
import { decodeTexture } from "./textures.js";

const COMPONENTS = ["head", "berd", "hair", "uppr", "lowr", "hand", "feet", "teef", "accs", "task", "decl", "jbib"];
const LABELS = {
  head: "Kopf", berd: "Maske", hair: "Haare", uppr: "Arme/Torso", lowr: "Hose", hand: "Tasche",
  feet: "Schuhe", teef: "Accessoire", accs: "Unterhemd", task: "Weste", decl: "Decal", jbib: "Oberteil",
};
const SOURCE_LABELS = { addon: "Addon", ersatz: "Ersatz", basis: "Basis" };
const BODY_DEFAULTS = ["head", "uppr", "lowr", "feet"];  // ohne gespeicherte Auswahl: kleinste Basis-Nummer

const $ = (sel) => document.querySelector(sel);
const status = (text) => { $("#status").textContent = text || ""; };

let catalog = [];
let gender = loadSetting("gender", "f");
let selection = {};  // type -> { id, letter }

// ---------- Szene ----------
const canvas = $("#view");
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
renderer.setPixelRatio(window.devicePixelRatio);
renderer.outputColorSpace = THREE.SRGBColorSpace;
const scene = new THREE.Scene();
const viewColor = () => getComputedStyle(document.documentElement).getPropertyValue("--view").trim() || "#d9dadd";
scene.background = new THREE.Color(viewColor());
const camera = new THREE.PerspectiveCamera(35, 1, 0.01, 100);
camera.position.set(0, 0.2, 3.2);
const controls = new OrbitControls(camera, canvas);
controls.target.set(0, 0, 0);
controls.enableDamping = true;
scene.add(new THREE.HemisphereLight(0xffffff, 0x6b6b70, 1.6));
const sun = new THREE.DirectionalLight(0xffffff, 1.6);
sun.position.set(2, 3, 4);
scene.add(sun);
const grid = new THREE.GridHelper(2, 10, 0x888888, 0xaaaaaa);
grid.position.y = -1;
scene.add(grid);
// GTA ist Z-oben, three.js Y-oben
const root = new THREE.Group();
root.rotation.x = -Math.PI / 2;
scene.add(root);
const slotGroups = {};

function resize() {
  const { clientWidth: w, clientHeight: h } = canvas.parentElement;
  renderer.setSize(w, h, false);
  camera.aspect = w / Math.max(h, 1);
  camera.updateProjectionMatrix();
}
window.addEventListener("resize", resize);
resize();
renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera); });

// ---------- Daten ----------
function loadSetting(key, fallback) {
  try { return JSON.parse(localStorage.getItem("glab_preview_" + key)) ?? fallback; } catch { return fallback; }
}
function saveSetting(key, value) {
  try { localStorage.setItem("glab_preview_" + key, JSON.stringify(value)); } catch { /* privat / blockiert */ }
}
function bytes(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}
async function api(path, body) {
  const res = body === undefined ? await fetch(path) : await fetch(path, {
    method: "POST", headers: { "Content-Type": "application/json", "X-ClothTool": "1" }, body: JSON.stringify(body),
  });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

const modelCache = new Map();
const textureCache = new Map();

function loadModel(id) {
  if (!modelCache.has(id)) modelCache.set(id, api(`/api/model?id=${id}`));
  return modelCache.get(id);
}

function loadTexture(id, letter) {
  const key = `${id}/${letter}`;
  if (!textureCache.has(key)) {
    textureCache.set(key, api(`/api/texture?id=${id}&letter=${letter}`).then((t) => {
      const data = bytes(t.data);
      if (t.format === "BC7") {
        if (!renderer.extensions.has("EXT_texture_compression_bptc")) return { texture: null, note: "BC7 wird von dieser Grafikkarte nicht unterstützt" };
        const tex = new THREE.CompressedTexture([{ data, width: t.width, height: t.height }], t.width, t.height, THREE.RGBA_BPTC_Format);
        tex.colorSpace = THREE.SRGBColorSpace;
        tex.minFilter = THREE.LinearFilter;
        tex.needsUpdate = true;
        return { texture: tex, alpha: true };
      }
      const decoded = decodeTexture(t.format, t.width, t.height, data);
      if (!decoded) return { texture: null, note: `Texturformat ${t.format} wird nicht angezeigt` };
      const tex = new THREE.DataTexture(decoded.rgba, t.width, t.height, THREE.RGBAFormat);
      tex.colorSpace = THREE.SRGBColorSpace;
      tex.magFilter = THREE.LinearFilter;
      tex.minFilter = THREE.LinearMipmapLinearFilter;
      tex.generateMipmaps = true;
      tex.wrapS = tex.wrapT = THREE.RepeatWrapping;
      tex.needsUpdate = true;
      return { texture: tex, alpha: decoded.alpha };
    }));
  }
  return textureCache.get(key);
}

function buildMeshes(model, tex) {
  const material = new THREE.MeshStandardMaterial({
    color: tex?.texture ? 0xffffff : 0xb9b9be, map: tex?.texture || null, side: THREE.DoubleSide,
    roughness: 0.85, metalness: 0, alphaTest: tex?.alpha ? 0.4 : 0, transparent: false,
  });
  return model.geometries.map((g) => {
    const geo = new THREE.BufferGeometry();
    geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(bytes(g.positions).buffer), 3));
    if (g.uvs) geo.setAttribute("uv", new THREE.BufferAttribute(new Float32Array(bytes(g.uvs).buffer), 2));
    geo.setIndex(new THREE.BufferAttribute(new Uint16Array(bytes(g.indices).buffer), 1));
    geo.computeVertexNormals();
    return new THREE.Mesh(geo, material);
  });
}

function groupFor(type) {
  if (!slotGroups[type]) {
    slotGroups[type] = new THREE.Group();
    root.add(slotGroups[type]);
  }
  return slotGroups[type];
}

async function showSlot(type) {
  const sel = selection[type];
  const group = groupFor(type);
  const token = (group.userData.token || 0) + 1;
  group.userData.token = token;
  if (!sel?.id) { group.clear(); return; }
  const item = catalog.find((i) => i.id === sel.id);
  try {
    status(`Lade ${item.file} …`);
    const [model, tex] = await Promise.all([
      loadModel(item.id),
      sel.letter ? loadTexture(item.id, sel.letter) : Promise.resolve(null),
    ]);
    if (group.userData.token !== token) return;  // inzwischen etwas anderes gewählt
    group.clear();
    buildMeshes(model, tex).forEach((m) => group.add(m));
    if (tex?.note) status(tex.note);
    else if ($("#status").textContent.startsWith("Lade ")) status("");
  } catch (err) {
    status(`${item.file}: ${err.message}`);
  }
}

function frame() {
  const box = new THREE.Box3().setFromObject(root);
  if (box.isEmpty()) return;
  const center = box.getCenter(new THREE.Vector3());
  const size = box.getSize(new THREE.Vector3()).length();
  controls.target.copy(center);
  camera.position.set(center.x, center.y + size * 0.1, center.z + size * 1.9);
  grid.position.y = box.min.y;
}

// ---------- Oberfläche ----------
function itemLabel(i) {
  const dlc = i.dlc ? ` · ${i.dlc}` : "";
  return `${String(i.number).padStart(3, "0")} · ${i.placeholder ? "Platzhalter" : SOURCE_LABELS[i.source]}${dlc}`;
}

// ---------- Löschen ----------
let canUndo = false;

function activeItem() {
  const sel = selection[activeSlot];
  return sel ? catalog.find((i) => i.id === sel.id) : null;
}

function renderActions() {
  const item = activeItem();
  const editable = item && item.source !== "basis";
  $("#delPart").disabled = !editable || item.placeholder;
  $("#delTex").disabled = !editable || item.textures.length < 2 || item.placeholderTextures.includes(selection[activeSlot]?.letter);
  $("#undo").disabled = !canUndo;
  $("#actionTarget").textContent = item ? `${LABELS[item.type]} ${itemLabel(item)}` : `${LABELS[activeSlot]}: nichts gewählt`;
}

async function deleteItem(item, letter) {
  if (!item || item.source === "basis") return;
  const name = `${LABELS[item.type]} ${String(item.number).padStart(3, "0")}${item.dlc ? " (" + item.dlc + ")" : ""}`;
  const what = letter ? `Textur ${letter} von ${name}` : name;
  const how = item.source === "ersatz"
    ? "Die Ersatz-Datei wird entfernt – im Spiel ist dann wieder das Original zu sehen."
    : "An seine Stelle kommt ein unsichtbarer Platzhalter, damit sich keine IDs verschieben (ist es das letzte, wird es ganz entfernt).";
  if (!confirm(`${what} löschen?\n\n${how}\n\nDie Dateien landen im Ordner _geloescht neben der Resource und lassen sich rückgängig machen. Danach die Resource neu starten.`)) return;
  await runEdit("/api/delete", { id: item.id, letter: letter || null });
}

async function runEdit(path, body) {
  try {
    status("Wird geändert …");
    const result = await api(path, body);
    canUndo = result.canUndo;
    await reloadCatalog();
    status(`${result.message} – Resource neu starten (restart …), damit es im Spiel ankommt.`);
  } catch (err) {
    status(err.message);
  }
  renderActions();
}

async function reloadCatalog() {
  const data = await api("/api/catalog");
  catalog = data.items;
  modelCache.clear();
  textureCache.clear();
  restoreSelection();
  renderSlots();
  renderList();
  showNow(activeSlot);
}

let activeSlot = loadSetting("active", "jbib");

function slotItems(type) {
  return catalog.filter((i) => i.gender === gender && !i.prop && i.type === type);
}

// Nächstes/vorheriges Teil im Slot ("nichts" ist Teil der Runde)
function stepItem(type, dir) {
  const items = slotItems(type);
  if (!items.length) return;
  const ids = ["", ...items.map((i) => i.id)];
  const cur = ids.indexOf(selection[type]?.id || "");
  setSlot(type, ids[(cur + dir + ids.length) % ids.length]);
}

function stepTexture(type, dir) {
  const sel = selection[type];
  const letters = sel ? catalog.find((i) => i.id === sel.id)?.textures || [] : [];
  if (letters.length < 2) return;
  const cur = letters.indexOf(sel.letter);
  setSlot(type, sel.id, letters[(cur + dir + letters.length) % letters.length]);
}

function setActive(type) {
  activeSlot = type;
  saveSetting("active", type);
  document.querySelectorAll(".slot").forEach((r) => r.classList.toggle("active", r.dataset.type === type));
  renderActions();
}

// Mausrad: ein Schritt pro "Raste", Touchpads liefern viele kleine Events
let wheelTime = 0;
function onWheel(ev, step) {
  ev.preventDefault();
  const now = performance.now();
  if (now - wheelTime < 90 || Math.abs(ev.deltaY) < 1) return;
  wheelTime = now;
  step(ev.deltaY > 0 ? 1 : -1);
}

function showNow(type) {
  const sel = selection[type];
  const item = sel && catalog.find((i) => i.id === sel.id);
  if (!item) { $("#now").textContent = `${LABELS[type]}: nichts`; return; }
  const n = item.textures.indexOf(sel.letter);
  const tex = item.textures.length ? ` · Textur ${sel.letter} (${n + 1}/${item.textures.length})` : "";
  $("#now").textContent = `${LABELS[type]} ${itemLabel(item)}${tex}`;
}

function setSlot(type, id, letter) {
  const item = catalog.find((i) => i.id === id);
  selection[type] = id ? { id, letter: letter ?? item?.textures[0] ?? "" } : null;
  saveSetting(`sel_${gender}`, Object.fromEntries(Object.entries(selection).map(([t, s]) => [t, s && { file: catalog.find((i) => i.id === s.id)?.file, letter: s.letter }])));
  setActive(type);
  renderSlots();
  renderList();
  showNow(type);
  showSlot(type);
}

function renderSlots() {
  const box = $("#slots");
  box.replaceChildren();
  for (const type of COMPONENTS) {
    const items = catalog.filter((i) => i.gender === gender && !i.prop && i.type === type);
    const row = document.createElement("div");
    row.className = "slot" + (type === activeSlot ? " active" : "");
    row.dataset.type = type;
    row.onpointerdown = () => setActive(type);
    const label = document.createElement("label");
    label.textContent = LABELS[type];
    label.title = type;
    const pick = document.createElement("select");
    pick.append(new Option("— nichts —", ""));
    for (const i of items) pick.append(new Option(itemLabel(i), i.id));
    const sel = selection[type];
    pick.value = sel?.id || "";
    pick.disabled = !items.length;
    pick.onchange = () => { setSlot(type, pick.value); };
    pick.onwheel = (ev) => onWheel(ev, (d) => stepItem(type, d));
    const prev = document.createElement("button");
    const next = document.createElement("button");
    prev.textContent = "◀"; next.textContent = "▶";
    prev.title = "Vorheriges Teil (↑)"; next.title = "Nächstes Teil (↓)";
    prev.disabled = next.disabled = !items.length;
    prev.onclick = () => stepItem(type, -1);
    next.onclick = () => stepItem(type, 1);
    const tex = document.createElement("select");
    const item = items.find((i) => i.id === sel?.id);
    for (const l of item?.textures || []) tex.append(new Option(l, l));
    tex.value = sel?.letter || "";
    tex.disabled = !item?.textures.length;
    tex.onchange = () => setSlot(type, sel.id, tex.value);
    tex.onwheel = (ev) => onWheel(ev, (d) => stepTexture(type, d));
    tex.title = "Textur (← →)";
    row.append(label, prev, pick, next, tex);
    box.append(row);
  }
}

function renderList() {
  const q = $("#filter").value.trim().toLowerCase();
  const items = catalog.filter((i) => i.gender === gender && !i.prop && i.source !== "basis")
    .filter((i) => !q || `${i.file} ${i.type} ${i.label} ${i.dlc} ${String(i.number).padStart(3, "0")}`.toLowerCase().includes(q));
  $("#count").textContent = `(${items.length})`;
  const list = $("#list");
  list.replaceChildren();
  for (const i of items) {
    const li = document.createElement("li");
    li.className = selection[i.type]?.id === i.id ? "active" : "";
    const name = document.createElement("span");
    name.textContent = `${LABELS[i.type]} ${String(i.number).padStart(3, "0")}${i.dlc ? " · " + i.dlc : ""}`;
    name.title = i.file;
    const tag = document.createElement("span");
    tag.className = `tag ${i.placeholder ? "placeholder" : i.source}`;
    tag.textContent = i.placeholder ? "Platzhalter" : SOURCE_LABELS[i.source];
    const del = document.createElement("button");
    del.className = "del";
    del.textContent = "🗑";
    del.title = "Löschen";
    del.disabled = i.placeholder;
    del.onclick = (ev) => { ev.stopPropagation(); deleteItem(i); };
    li.append(name, tag, del);
    li.onclick = () => setSlot(i.type, i.id);
    list.append(li);
  }
}

function restoreSelection() {
  selection = {};
  const saved = loadSetting(`sel_${gender}`, null);
  for (const type of COMPONENTS) {
    const items = catalog.filter((i) => i.gender === gender && !i.prop && i.type === type);
    const s = saved?.[type];
    let item = s && items.find((i) => i.file === s.file);
    if (!saved && BODY_DEFAULTS.includes(type)) item = items.find((i) => i.source !== "addon");
    if (item) selection[type] = { id: item.id, letter: item.textures.includes(s?.letter) ? s.letter : item.textures[0] ?? "" };
  }
  Promise.all(COMPONENTS.map(showSlot)).then(frame);
}

function setGender(g) {
  gender = g;
  saveSetting("gender", g);
  document.querySelectorAll(".gender button").forEach((b) => b.classList.toggle("active", b.dataset.gender === g));
  restoreSelection();
  renderSlots();
  renderList();
  renderActions();
}

document.querySelectorAll(".gender button").forEach((b) => (b.onclick = () => setGender(b.dataset.gender)));

// Tastatur: ↑/↓ Teil, ←/→ Textur im aktiven Slot; Bild ↑/↓ wechselt den Slot
const KEYS = {
  ArrowDown: () => stepItem(activeSlot, 1), ArrowUp: () => stepItem(activeSlot, -1),
  ArrowRight: () => stepTexture(activeSlot, 1), ArrowLeft: () => stepTexture(activeSlot, -1),
  PageDown: () => stepSlot(1), PageUp: () => stepSlot(-1),
};

function stepSlot(dir) {  // springt zum nächsten Slot, für den es Teile gibt
  const n = COMPONENTS.length;
  for (let k = 1; k <= n; k++) {
    const type = COMPONENTS[(COMPONENTS.indexOf(activeSlot) + dir * k + n * k) % n];
    if (slotItems(type).length) return setActive(type);
  }
}
document.addEventListener("keydown", (ev) => {
  if (ev.target.matches?.("input, select, textarea")) return;
  if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "z" && canUndo) { ev.preventDefault(); runEdit("/api/undo", {}); return; }
  if (ev.key === "Delete") { ev.preventDefault(); deleteItem(activeItem(), ev.shiftKey ? selection[activeSlot]?.letter : null); return; }
  if (ev.altKey || ev.ctrlKey || ev.metaKey) return;
  const action = KEYS[ev.key];
  if (!action) return;
  ev.preventDefault();
  action();
  showNow(activeSlot);
});
document.addEventListener("change", (ev) => { if (ev.target.matches("#slots select")) ev.target.blur(); });
$("#filter").oninput = renderList;
$("#delPart").onclick = () => deleteItem(activeItem());
$("#delTex").onclick = () => deleteItem(activeItem(), selection[activeSlot]?.letter);
$("#undo").onclick = () => runEdit("/api/undo", {});

api("/api/catalog").then((data) => {
  catalog = data.items;
  const info = [];
  if (!data.base) info.push("Kein Grundkörper-Ordner gewählt – nur die Kleidung wird angezeigt.");
  if (!catalog.length) info.push("Keine Teile gefunden.");
  $("#info").textContent = info.join(" ");
  if (!catalog.some((i) => i.gender === gender) && catalog.length) gender = catalog[0].gender;
  setGender(gender);
}).catch((err) => status(`Katalog: ${err.message}`));
