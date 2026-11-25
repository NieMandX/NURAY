// Measurements live in world space for the lifetime of this viewer.
const SVG = 'http://www.w3.org/2000/svg';
let nextOverlay = 0;
const numbers = new Intl.NumberFormat('ru-RU', {maximumFractionDigits: 2});
const worldDistance = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
const footprint = point => [point[0], point[2]];
const cross = (a, b, c) => (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);

export function footprintArea(points) {
  if (points.length < 3) return 0;
  const origin = footprint(points[0]);
  let twiceArea = 0;
  for (let i = 2; i < points.length; i++) {
    twiceArea += cross(origin, footprint(points[i - 1]), footprint(points[i]));
  }
  return Math.abs(twiceArea) / 2;
}

function between(a, b, p) {
  return p[0] >= Math.min(a[0], b[0]) && p[0] <= Math.max(a[0], b[0]) &&
    p[1] >= Math.min(a[1], b[1]) && p[1] <= Math.max(a[1], b[1]);
}

function intersects(a, b, c, d) {
  const ac = cross(a, b, c), ad = cross(a, b, d), ca = cross(c, d, a), cb = cross(c, d, b);
  if (ac === 0 && between(a, b, c) || ad === 0 && between(a, b, d) ||
      ca === 0 && between(c, d, a) || cb === 0 && between(c, d, b)) return true;
  return ac * ad < 0 && ca * cb < 0;
}

function newEdgeCrosses(points, next, closing) {
  if (!points.length) return false;
  const a = footprint(points.at(-1)), b = footprint(next);
  if (Math.hypot(a[0] - b[0], a[1] - b[1]) < 0.001) return true;
  // Adjacent edges may share their vertex but may not double back over it.
  const foldsBack = (before, joint, after) => cross(before, joint, after) === 0 &&
    (before[0] - joint[0]) * (after[0] - joint[0]) + (before[1] - joint[1]) * (after[1] - joint[1]) > 0;
  if (points.length > 1 && foldsBack(footprint(points.at(-2)), a, b)) return true;
  if (closing && foldsBack(a, b, footprint(points[1]))) return true;
  for (let i = closing ? 1 : 0; i < points.length - 2; i++) {
    if (intersects(a, b, footprint(points[i]), footprint(points[i + 1]))) return true;
  }
  return false;
}

function distanceToSegment(p, a, b) {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy || 1)));
  return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
}

function scanline(points, y) {
  const intersections = [];
  for (let i = 0; i < points.length; i++) {
    const a = points[i], b = points[(i + 1) % points.length];
    if ((a[1] > y) !== (b[1] > y)) {
      intersections.push(a[0] + (y - a[1]) * (b[0] - a[0]) / (b[1] - a[1]));
    }
  }
  return intersections.sort((a, b) => a - b);
}

function areaLabel(points, width, height) {
  const ys = points.map(p => p[1]);
  const top = Math.max(0, Math.min(...ys)), bottom = Math.min(height, Math.max(...ys));
  if (bottom < top) return null;
  const y = (top + bottom) / 2, xs = scanline(points, y);
  let best = 0, x = null;
  for (let i = 0; i + 1 < xs.length; i += 2) {
    const left = Math.max(0, xs[i]), right = Math.min(width, xs[i + 1]);
    if (right - left > best) { best = right - left; x = (right + left) / 2; }
  }
  return x === null ? null : [x, y];
}

// Clip at the camera's near plane before projecting. An endpoint behind the
// viewer must not invert or remove the visible portion of a measurement.
function visiblePoints(points, closed, geometry) {
  if (!points.length) return [];
  const output = [];
  let a = closed ? points.at(-1) : points[0], da = geometry.depth(a);
  for (const b of points) {
    const db = geometry.depth(b);
    if ((da >= geometry.near) !== (db >= geometry.near)) {
      const t = (geometry.near - da) / (db - da);
      output.push(geometry.project(a.map((n, i) => n + (b[i] - n) * t)));
    }
    if (db >= geometry.near) output.push(geometry.project(b));
    a = b; da = db;
  }
  return output.filter(Boolean);
}

function svgNode(name, attrs = {}) {
  const node = document.createElementNS(SVG, name);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
  return node;
}

function lengthLabel(points) {
  return numbers.format(worldDistance(points[0], points[1])) + ' м';
}
function sizeLabel(points) {
  return numbers.format(footprintArea(points)) + ' м²';
}

export function createMeasureTools({canvas, distanceButton, areaButton, geometry}) {
  const abort = new AbortController(), listener = {signal: abort.signal};
  const overlay = document.createElement('div');
  overlay.className = 'measure-overlay';
  const svg = svgNode('svg', {'aria-hidden': 'true', class: 'measure-lines'});
  const defs = svgNode('defs');
  const patternId = 'measurement-hatch-' + ++nextOverlay;
  const pattern = svgNode('pattern', {id: patternId, patternUnits: 'userSpaceOnUse', width: 10, height: 10});
  pattern.append(svgNode('path', {d: 'M-2 2 L2 -2 M0 10 L10 0 M8 12 L12 8', class: 'measure-hatch'}));
  defs.append(pattern); svg.append(defs);
  const labels = document.createElement('div');
  const hint = document.createElement('div');
  hint.className = 'measure-hint'; hint.setAttribute('role', 'status'); hint.hidden = true;
  overlay.append(svg, labels, hint);
  canvas.after(overlay);

  const items = new Map(), pointers = new Set(), clicks = [];
  let mode = null, selected = null, draft = [], hover = null, draftView = null, nextId = 1;
  let generation = 0, previewVersion = 0, nextPreview = null, lastCursor = null, frame = 0, busy = false;
  let gesture = null, message = '', disposed = false;

  function position(e) {
    const rect = canvas.getBoundingClientRect();
    return {x: e.clientX - rect.left, y: e.clientY - rect.top, shift: e.shiftKey, ctrl: e.ctrlKey, touch: e.pointerType === 'touch'};
  }

  function createView(id, kind) {
    const group = svgNode('g', {class: id ? 'measure-object' : 'measure-draft'});
    group.dataset.measureKind = kind;
    if (id) group.dataset.measureId = String(id);
    const area = svgNode('polygon', {class: 'measure-area', fill: 'url(#' + patternId + ')'});
    const line = svgNode('path', {class: 'measure-edge'}), dots = svgNode('g');
    group.append(area, line, dots); svg.append(group);
    const label = document.createElement('div'); label.className = 'measure-tag';
    const value = document.createElement(id ? 'button' : 'span');
    value.className = 'measure-label';
    label.append(value);
    let remove = null;
    if (id) {
      value.type = 'button';
      value.addEventListener('click', () => select(id));
      remove = document.createElement('button');
      remove.type = 'button'; remove.className = 'measure-delete'; remove.textContent = '×';
      remove.title = 'Удалить измерение'; remove.setAttribute('aria-label', remove.title);
      remove.addEventListener('click', () => removeItem(id));
      label.append(remove);
    }
    labels.append(label);
    return {id, kind, group, area, line, dots, label, value, remove, screen: []};
  }

  function discardView(view) {
    if (view) { view.group.remove(); view.label.remove(); }
  }

  function draw(view, points, tentative = false) {
    const closed = view.kind === 'area' && !tentative;
    const screen = visiblePoints(points, closed, geometry);
    view.screen = screen;
    const shape = screen.map(p => p.map(n => n.toFixed(2)).join(','));
    view.area.setAttribute('points', closed ? shape.join(' ') : '');
    view.line.setAttribute('d', shape.length ? 'M' + shape.join(' L') + (closed ? ' Z' : '') : '');
    view.group.dataset.selected = String(view.id === selected && !!selected);
    const vertices = tentative || view.id === selected ? points : [];
    const dots = vertices.map(p => geometry.depth(p) >= geometry.near ? geometry.project(p) : null);
    while (view.dots.childElementCount > dots.length) view.dots.lastChild.remove();
    dots.forEach((p, i) => {
      const dot = view.dots.children[i] ?? view.dots.appendChild(svgNode('circle'));
      const start = tentative && view.kind === 'area' && i === 0 && draft.length >= 3;
      dot.setAttribute('r', p ? start ? 6 : 3 : 0);
      dot.setAttribute('class', start ? 'measure-close-dot' : 'measure-dot');
      if (p) {dot.setAttribute('cx', p[0]); dot.setAttribute('cy', p[1]);}
    });
    let anchor = null, value = '';
    if (view.kind === 'distance' && points.length === 2 && screen.length >= 2) {
      const a = screen[0], b = screen.at(-1);
      anchor = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]; value = lengthLabel(points);
    } else if (view.kind === 'area' && screen.length >= 3) {
      anchor = areaLabel(screen, overlay.clientWidth, overlay.clientHeight); value = sizeLabel(points);
    }
    view.label.hidden = !anchor;
    if (view.remove) view.remove.hidden = selected !== view.id;
    if (anchor) {
      view.label.style.left = anchor[0] + 'px'; view.label.style.top = anchor[1] + 'px';
      view.value.textContent = value;
      if (view.id) view.value.setAttribute('aria-label', 'Выбрать измерение ' + value);
      view.label.dataset.selected = view.group.dataset.selected;
    }
  }

  function showHint() {
    let text = message;
    if (!text && mode === 'distance') text = draft.length
      ? 'Укажите вторую точку · Shift — вертикаль · Ctrl — перпендикуляр к поверхности'
      : 'Укажите начало отрезка';
    if (!text && mode === 'area') text = draft.length >= 3
      ? 'Продолжайте контур или замкните его нажатием на первую точку · Enter — завершить'
      : 'Укажите ' + (draft.length ? 'следующую' : 'первую') + ' точку контура';
    if (!text && selected) text = 'Delete — удалить измерение';
    hint.hidden = !text;
    if (hint.textContent !== text) hint.textContent = text;
  }

  function drawDraft() {
    if (!draft.length) {discardView(draftView); draftView = null; return;}
    if (!draftView) draftView = createView(null, mode);
    const points = draft.map(hit => hit.point);
    if (hover) points.push(hover);
    draw(draftView, points, true);
  }

  function redraw() {
    for (const item of items.values()) draw(item.view, item.points);
    drawDraft(); showHint();
  }

  function clearPreview() {
    nextPreview = null; hover = null; previewVersion++;
  }

  function cancelDraft() {
    generation++; clicks.length = 0; draft = [];
    clearPreview(); message = '';
  }

  function setMode(nextMode) {
    cancelDraft(); mode = nextMode; selected = null; lastCursor = null; gesture = null;
    canvas.classList.toggle('measure-active', !!mode);
    distanceButton.setAttribute('aria-pressed', String(mode === 'distance'));
    areaButton.setAttribute('aria-pressed', String(mode === 'area'));
    redraw();
  }

  function select(id) {
    cancelDraft(); selected = id; redraw();
  }

  function removeItem(id) {
    const item = items.get(id);
    if (!item) return;
    discardView(item.view); items.delete(id);
    if (selected === id) selected = null;
    showHint();
  }

  function finish() {
    const points = draft.map(hit => hit.point);
    if (mode === 'area') {
      if (points.length < 3) return;
      if (!footprintArea(points) || newEdgeCrosses(points, points[0], true)) {
        message = 'Для площади нужен замкнутый контур без пересечений'; showHint(); return;
      }
    }
    const id = nextId++;
    items.set(id, {points, view: createView(id, mode)});
    draft = []; selected = id; clearPreview(); message = ''; redraw();
  }

  function hitItem(x, y, includeInterior) {
    const p = [x, y];
    for (const item of [...items.values()].reverse()) {
      const {screen, kind, id} = item.view;
      const closed = kind === 'area';
      for (let i = 0; i < screen.length - (closed ? 0 : 1); i++) {
        if (distanceToSegment(p, screen[i], screen[(i + 1) % screen.length]) <= 6) return id;
      }
      if (closed && includeInterior && scanline(screen, y).filter(n => n > x).length % 2) return id;
    }
    return null;
  }

  function closeToStart(cursor) {
    if (mode !== 'area' || draft.length < 3 || geometry.depth(draft[0].point) < geometry.near) return false;
    const p = geometry.project(draft[0].point);
    return p && Math.hypot(p[0] - cursor.x, p[1] - cursor.y) <= (cursor.touch ? 16 : 9);
  }

  function resolveHit(cursor) {
    if (mode === 'distance' && draft.length && (cursor.shift || cursor.ctrl)) {
      const anchor = draft[0];
      const point = geometry.constrain(anchor, cursor.x, cursor.y, cursor.shift ? 'vertical' : 'normal');
      return point && {point, normal: anchor.normal};
    }
    return geometry.pick(cursor.x, cursor.y);
  }

  async function commit(cursor) {
    if (cursor.finish || closeToStart(cursor)) {if (mode === 'area') finish(); return;}
    if (!draft.length) {
      const existing = hitItem(cursor.x, cursor.y, !mode);
      if (existing) {selected = existing; message = ''; redraw(); return;}
      selected = null;
      if (!mode) {redraw(); return;}
    }
    const token = generation;
    const hit = await resolveHit(cursor);
    if (token !== generation || disposed) return;
    if (!hit) {
      message = 'Выберите точку на видимой поверхности';
      if (mode === 'distance' && draft.length && (cursor.shift || cursor.ctrl)) {
        message = cursor.ctrl && !cursor.shift && !draft[0].normal
          ? 'Перпендикуляр не определён · начните отрезок внутри плоского участка'
          : 'Ось направлена вдоль взгляда · немного поверните камеру';
      }
      redraw(); return;
    }
    message = '';
    if (draft.length && worldDistance(draft.at(-1).point, hit.point) < 0.001) return;
    if (mode === 'area' && newEdgeCrosses(draft.map(p => p.point), hit.point, false)) {
      message = 'Ребро пересекает контур · выберите другую точку'; showHint(); return;
    }
    draft.push(hit); clearPreview();
    if (mode === 'distance' && draft.length === 2) finish();
    else {redraw(); if (lastCursor && !clicks.length) requestPreview(lastCursor);}
  }

  async function drain() {
    if (busy || disposed) return;
    busy = true;
    try {
      while (!disposed && (clicks.length || nextPreview)) {
        if (clicks.length) {await commit(clicks.shift()); continue;}
        const cursor = nextPreview, version = previewVersion;
        nextPreview = null;
        const point = closeToStart(cursor) ? draft[0].point : (await resolveHit(cursor))?.point;
        if (version === previewVersion && !disposed) {
          hover = point ?? null; drawDraft();
        }
      }
    } catch (error) {
      console.warn('Не удалось выбрать поверхность для измерения', error);
      message = 'Не удалось определить точку на поверхности'; showHint();
    } finally {
      busy = false;
      if (!disposed && (clicks.length || nextPreview)) schedule();
    }
  }

  function schedule() {
    if (!frame && !busy && !disposed) frame = requestAnimationFrame(() => {frame = 0; void drain();});
  }

  function requestPreview(cursor) {
    if (!draft.length || pointers.size) return;
    // Present the last completed sample during a continuous move. Replacing
    // every mouse move's result on a slower GPU would freeze the live ruler.
    nextPreview = cursor; schedule();
  }

  function update() {
    if (!items.size && !draft.length) return;
    previewVersion++;
    redraw();
    if (lastCursor) requestPreview(lastCursor);
  }

  distanceButton.addEventListener('click', () => setMode(mode === 'distance' ? null : 'distance'), listener);
  areaButton.addEventListener('click', () => setMode(mode === 'area' ? null : 'area'), listener);
  canvas.addEventListener('pointerdown', event => {
    if (!mode && !items.size) return;
    pointers.add(event.pointerId);
    gesture = event.button === 0 && pointers.size === 1 ? {id: event.pointerId, x: event.clientX, y: event.clientY} : null;
    clearPreview(); drawDraft();
  }, listener);
  canvas.addEventListener('pointermove', event => {
    if (!mode && !items.size) return;
    if (gesture && Math.hypot(event.clientX - gesture.x, event.clientY - gesture.y) > 5) gesture = null;
    lastCursor = position(event);
    requestPreview(lastCursor);
  }, listener);
  canvas.addEventListener('pointerup', event => {
    pointers.delete(event.pointerId);
    if (!mode && !items.size) {gesture = null; return;}
    const click = gesture?.id === event.pointerId && Math.hypot(event.clientX - gesture.x, event.clientY - gesture.y) <= 5;
    gesture = null;
    lastCursor = event.pointerType === 'touch' ? null : position(event);
    if (click && (mode || items.size)) {clearPreview(); clicks.push(position(event)); schedule();}
    else if (lastCursor) requestPreview(lastCursor);
  }, listener);
  const releasePointer = event => {
    pointers.delete(event.pointerId);
    if (gesture?.id === event.pointerId) gesture = null;
  };
  canvas.addEventListener('pointercancel', releasePointer, listener);
  canvas.addEventListener('lostpointercapture', releasePointer, listener);
  canvas.addEventListener('pointerleave', () => {lastCursor = null; clearPreview(); drawDraft();}, listener);

  function updateModifiers(event) {
    if (lastCursor && (event.key === 'Shift' || event.key === 'Control')) {
      previewVersion++;
      lastCursor = {...lastCursor, shift: event.shiftKey, ctrl: event.ctrlKey};
      requestPreview(lastCursor);
    }
  }
  document.addEventListener('keydown', event => {
    if (event.defaultPrevented || event.target.closest?.('input, select, textarea, [contenteditable=true], .viewer-panel')) return;
    updateModifiers(event);
    if (event.key === 'Escape' && (mode || selected)) {
      if (draft.length || clicks.length || busy) {cancelDraft(); redraw();} else setMode(null);
    } else if ((event.key === 'Delete' || event.key === 'Backspace') && selected) {
      removeItem(selected);
    } else if (event.key === 'Enter' && mode === 'area' && draft.length && !event.target.closest?.('button.measure-label, .measure-delete')) {
      clicks.push({finish: true}); schedule();
    } else return;
    event.preventDefault();
  }, listener);
  document.addEventListener('keyup', updateModifiers, listener);
  const observer = new ResizeObserver(update);
  observer.observe(canvas);

  return {update, dispose() {
    disposed = true; cancelDraft(); abort.abort(); cancelAnimationFrame(frame); observer.disconnect();
    overlay.remove(); canvas.classList.remove('measure-active');
    distanceButton.setAttribute('aria-pressed', 'false'); areaButton.setAttribute('aria-pressed', 'false');
    items.clear();
  }};
}
