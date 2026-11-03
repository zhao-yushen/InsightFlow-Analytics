"""Animated instruments, hand-built on canvas and SVG with no external libraries.

Each one animates because motion explains something: money leaves the river where it
actually leaves, simulated futures land where they actually land. All of them run
offline, pause when off screen and honour the reduced-motion setting.
"""

from __future__ import annotations

from importlib import resources
from typing import Any

import streamlit as st

_SHARED_JS = r"""
const RGB = { flow: [56, 214, 196], profit: [255, 196, 77], leak: [255, 123, 107] };
const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const mix = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));
const rgba = (c, a) => `rgba(${c[0]},${c[1]},${c[2]},${a})`;
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const easeOut = (t) => 1 - Math.pow(1 - t, 3);
const esc = (text) => String(text ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function fitCanvas(canvas, width, height) {
  const ratio = Math.min(window.devicePixelRatio || 1, 2);
  canvas.width = Math.round(width * ratio);
  canvas.height = Math.round(height * ratio);
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  const context = canvas.getContext("2d");
  context.setTransform(ratio, 0, 0, ratio, 0, 0);
  return context;
}

function whenVisible(element, onChange) {
  const observer = new IntersectionObserver(([entry]) => onChange(entry.isIntersecting));
  observer.observe(element);
  return observer;
}
"""

_TOOLTIP_CSS = """
.tip {
  position: absolute; z-index: 5; pointer-events: none; opacity: 0;
  min-width: 9rem; max-width: 16rem; padding: .5rem .65rem;
  background: #17345C; border: 1px solid #274A78; border-radius: 6px;
  color: #EAF4FF; font-size: .8rem; line-height: 1.55;
  transition: opacity .12s ease;
}
.tip.on { opacity: 1; }
.tip b { display: block; font-weight: 600; }
.tip span { display: block; color: #B4C7DF; }
"""

_RIVER_HTML = '<div class="river" role="group"><div class="stage"></div><div class="tip"></div></div>'
_RIVER_CSS = (
    _TOOLTIP_CSS
    + """
.river { position: relative; width: 100%; font-family: inherit; color: #EAF4FF; }
.stage { position: relative; width: 100%; }
svg, canvas { position: absolute; inset: 0; display: block; }
canvas { pointer-events: none; mix-blend-mode: screen; }
.branch { cursor: pointer; transition: opacity .16s ease; outline: none; }
.river.focusing .branch { opacity: .32; }
.river.focusing .branch.active { opacity: 1; }
.label { position: absolute; line-height: 1.35; opacity: 0; transition: opacity .5s ease; }
.river.ready .label { opacity: 1; }
.label .name { color: #B4C7DF; font-size: .8rem; }
.label .value { color: #EAF4FF; font-weight: 600; letter-spacing: -.01em; }
.label .note { color: #8BA3C2; font-size: .74rem; }
.source { left: 0; top: 0; }
.source .value { font-size: 1.28rem; }
.sink { text-align: left; }
.sink .name { color: #FFC44D; }
.sink .value { color: #FFC44D; font-size: clamp(1.6rem, 2.6vw, 2.3rem); letter-spacing: -.03em; }
.leak { transform: translateX(-50%); text-align: center; width: 6.6rem; cursor: pointer; border-radius: 6px; }
.leak:focus-visible { outline: 2px solid #38D6C4; outline-offset: 3px; }
.leak.picked .name { color: #FF7B6B; text-decoration: underline; text-underline-offset: 3px; }
.leak .value { font-size: .95rem; }
.leak.active .name { color: #FF7B6B; }
.river.compact .leak { width: 3.5rem; }
.river.compact .leak .name { font-size: .64rem; line-height: 1.2; }
.river.compact .leak .value { font-size: .68rem; }
.river.compact .leak .note { display: none; }
.river.compact .sink { position: absolute; right: 0; text-align: right; }
"""
)
_RIVER_JS = (
    _SHARED_JS
    + r"""
const SVG = "http://www.w3.org/2000/svg";

function geometry(data, width) {
  const compact = width < 760;
  const height = compact ? 330 : 400;
  const x0 = 0;
  const x1 = compact ? width : width - 176;
  const top = compact ? 74 : 62;
  const thick = compact ? 96 : 136;
  const leaks = data.leaks.map((leak) => ({ ...leak, value: Math.max(0, leak.value) }));
  const outflow = leaks.reduce((sum, leak) => sum + leak.value, 0);
  const remaining = Math.max(0, data.end.value);
  const total = Math.max(data.start.value, outflow + remaining, 1);
  let cursor = total;
  const count = leaks.length;
  const span = x1 - x0;
  const baseY = height - (compact ? 62 : 74);
  leaks.forEach((leak, index) => {
    leak.u2 = cursor / total;
    cursor -= leak.value;
    leak.u1 = cursor / total;
    leak.x = x0 + span * (0.12 + (0.76 * index) / Math.max(count - 1, 1));
    leak.run = (span * 0.76) / Math.max(count - 1, 1) * 0.5;
    leak.t = (leak.u2 - leak.u1) * thick;
    leak.ex = leak.x + leak.run;
    leak.ey = baseY;
  });
  return { compact, height, width, x0, x1, top, thick, leaks, total, tail: remaining / total };
}

function branchPath(g, leak) {
  const a = g.top + leak.u1 * g.thick;
  const b = g.top + leak.u2 * g.thick;
  const half = Math.max(leak.t, 1.4) / 2;
  const d = leak.ex - leak.x;
  const upper = `M${leak.x},${a} C${leak.x + d * 0.8},${a} ${leak.ex + half},${g.top + (leak.ey - g.top) * 0.42} ${leak.ex + half},${leak.ey}`;
  const lower = `L${leak.ex - half},${leak.ey} C${leak.ex - half},${g.top + (leak.ey - g.top) * 0.55} ${leak.x + d * 0.5},${b} ${leak.x - 2},${b} Z`;
  return `${upper} ${lower}`;
}

function mainPath(g) {
  let path = `M${g.x0},${g.top} L${g.x1},${g.top} L${g.x1},${g.top + g.tail * g.thick}`;
  [...g.leaks].reverse().forEach((leak) => {
    const after = g.top + leak.u1 * g.thick;
    const before = g.top + leak.u2 * g.thick;
    const ease = Math.min(18, Math.max(leak.t, 6));
    path += ` L${leak.x + ease},${after} C${leak.x},${after} ${leak.x},${before} ${leak.x - ease},${before}`;
  });
  return `${path} L${g.x0},${g.top + g.thick} Z`;
}

function spawn(g, fresh) {
  const u = Math.random();
  const leak = g.leaks.find((item) => u >= item.u1 && u <= item.u2);
  const y = g.top + u * g.thick;
  return {
    u, y, leak,
    x: fresh ? g.x0 + Math.random() * (g.x1 - g.x0) * 0.2 : g.x0 + Math.random() * (g.x1 - g.x0),
    speed: 70 + Math.random() * 60,
    size: 0.7 + Math.random() * 1.1,
    t: 0,
  };
}

function bezier(p, t) {
  const m = 1 - t;
  return m * m * m * p[0] + 3 * m * m * t * p[1] + 3 * m * t * t * p[2] + t * t * t * p[3];
}

function createRiver(root, pick) {
  const stage = root.querySelector(".stage");
  const tip = root.querySelector(".tip");
  const svg = document.createElementNS(SVG, "svg");
  const canvas = document.createElement("canvas");
  stage.append(svg, canvas);
  let data = null, g = null, context = null, particles = [], frame = 0, visible = true, last = 0;

  function showTip(leak, event) {
    root.classList.add("focusing");
    root.querySelectorAll(`[data-key="${leak.key}"]`).forEach((node) => node.classList.add("active"));
    tip.innerHTML = `<b>${esc(leak.label)} ${esc(leak.display)}</b><span>${esc(leak.share)}</span><span>${esc(leak.delta)}</span>`;
    const box = root.getBoundingClientRect();
    const x = (event?.clientX ?? box.left + leak.ex) - box.left;
    tip.style.left = `${clamp(x + 14, 0, box.width - 180)}px`;
    tip.style.top = `${clamp((event?.clientY ?? box.top + leak.ey) - box.top - 70, 0, box.height - 80)}px`;
    tip.classList.add("on");
  }
  function hideTip() {
    root.classList.remove("focusing");
    root.querySelectorAll(".active").forEach((node) => node.classList.remove("active"));
    tip.classList.remove("on");
  }

  function draw(reveal) {
    const width = Math.max(stage.clientWidth, 320);
    g = geometry(data, width);
    root.classList.toggle("compact", g.compact);
    stage.style.height = `${g.height}px`;
    svg.setAttribute("width", width);
    svg.setAttribute("height", g.height);
    svg.innerHTML = `
      <defs>
        <linearGradient id="stream" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stop-color="rgb(${RGB.flow})" stop-opacity=".82"/>
          <stop offset=".62" stop-color="rgb(${RGB.flow})" stop-opacity=".66"/>
          <stop offset="1" stop-color="rgb(${RGB.profit})" stop-opacity=".92"/>
        </linearGradient>
        <linearGradient id="outflow" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stop-color="rgb(${RGB.leak})" stop-opacity=".78"/>
          <stop offset="1" stop-color="rgb(${RGB.leak})" stop-opacity=".12"/>
        </linearGradient>
        <clipPath id="reveal"><rect x="0" y="0" width="${reveal ? 0 : width}" height="${g.height}"/></clipPath>
      </defs>
      <g clip-path="url(#reveal)">
        ${g.leaks.map((leak) => `<path class="branch" data-key="${esc(leak.key)}" d="${branchPath(g, leak)}" fill="url(#outflow)"/>`).join("")}
        <path d="${mainPath(g)}" fill="url(#stream)"/>
      </g>`;
    stage.querySelectorAll(".label").forEach((node) => node.remove());
    const label = (cls, html, style, key) => {
      const node = document.createElement("div");
      node.className = `label ${cls}`;
      node.innerHTML = html;
      Object.assign(node.style, style);
      if (key) node.dataset.key = key;
      stage.append(node);
      return node;
    };
    label("source", `<div class="name">${esc(data.start.label)}</div><div class="value">${esc(data.start.display)}</div>`, {});
    const sinkY = g.top + (g.tail * g.thick) / 2 - 42;
    label(
      "sink",
      `<div class="name">${esc(data.end.label)}</div><div class="value">${esc(data.end.display)}</div><div class="note">${esc(data.end.note)}</div>`,
      g.compact ? { top: "0" } : { left: `${g.x1 + 14}px`, top: `${Math.max(sinkY, 0)}px` }
    );
    g.leaks.forEach((leak) => {
      const node = label(
        "leak",
        `<div class="name">${esc(leak.label)}</div><div class="value">${esc(leak.display)}</div><div class="note">${esc(leak.share)}</div>`,
        { left: `${leak.ex}px`, top: `${leak.ey + 6}px` },
        leak.key
      );
      node.tabIndex = 0;
      node.setAttribute("role", "button");
      node.setAttribute("aria-label", `${leak.label} ${leak.display}, ${leak.share}. ${data.pickHint}`);
      node.classList.toggle("picked", leak.key === data.picked);
      node.addEventListener("focus", () => showTip(leak));
      node.addEventListener("blur", hideTip);
      node.addEventListener("pointerenter", (event) => showTip(leak, event));
      node.addEventListener("pointerleave", hideTip);
      node.addEventListener("click", () => pick(leak.key));
      node.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        pick(leak.key);
      });
    });
    svg.querySelectorAll(".branch").forEach((path, index) => {
      const leak = g.leaks[index];
      path.addEventListener("pointermove", (event) => showTip(leak, event));
      path.addEventListener("pointerleave", hideTip);
      path.addEventListener("click", () => pick(leak.key));
    });
    root.setAttribute("aria-label", data.summary);
    context = fitCanvas(canvas, width, g.height);
    particles = Array.from({ length: Math.round(width / 2.6) }, () => spawn(g, false));
  }

  function step(time) {
    frame = requestAnimationFrame(step);
    if (!visible || document.hidden) { last = time; return; }
    const dt = Math.min((time - last) / 1000, 0.05);
    last = time;
    context.clearRect(0, 0, g.width, g.height);
    for (const dot of particles) {
      let x, y, color, alpha = 0.9;
      const leak = dot.leak;
      if (leak && dot.x >= leak.x) {
        dot.t += dt / 1.5;
        const half = leak.t / 2;
        const ratio = leak.u2 > leak.u1 ? (dot.u - leak.u1) / (leak.u2 - leak.u1) : 0.5;
        const end = leak.ex + half - ratio * leak.t;
        const d = leak.ex - leak.x;
        x = bezier([leak.x, leak.x + d * 0.65, end, end], dot.t);
        y = bezier([dot.y, dot.y, g.top + (leak.ey - g.top) * 0.5, leak.ey], dot.t);
        color = RGB.leak;
        alpha = 0.9 * (1 - dot.t * 0.8);
        if (dot.t >= 1) Object.assign(dot, spawn(g, true));
      } else {
        dot.x += dot.speed * dt;
        x = dot.x;
        y = dot.y;
        const along = clamp((x - g.x0) / (g.x1 - g.x0), 0, 1);
        color = mix(RGB.flow, RGB.profit, Math.pow(along, 3));
        if (dot.x >= g.x1) Object.assign(dot, spawn(g, true));
      }
      context.fillStyle = rgba(color, alpha);
      context.beginPath();
      context.arc(x, y, dot.size, 0, Math.PI * 2);
      context.fill();
    }
  }

  function playReveal() {
    const rect = svg.querySelector("#reveal rect");
    const started = performance.now();
    const tick = (time) => {
      const progress = clamp((time - started) / 1500, 0, 1);
      rect?.setAttribute("width", g.width * easeOut(progress));
      if (progress < 1) requestAnimationFrame(tick);
      else root.classList.add("ready");
    };
    requestAnimationFrame(tick);
    setTimeout(() => root.classList.add("ready"), 700);
  }

  const resize = new ResizeObserver(() => {
    if (data && stage.clientWidth && Math.abs(stage.clientWidth - g?.width) > 2) draw(false);
  });
  resize.observe(stage);
  const seen = whenVisible(root, (state) => { visible = state; });

  return {
    update(next, first) {
      data = next;
      const animate = first && !reduced();
      draw(animate);
      if (reduced()) {
        root.classList.add("ready");
        context.clearRect(0, 0, g.width, g.height);
        particles.slice(0, 70).forEach((dot) => {
          if (dot.leak && dot.x >= dot.leak.x) return;
          context.fillStyle = rgba(RGB.flow, 0.8);
          context.beginPath();
          context.arc(dot.x, dot.y, dot.size, 0, Math.PI * 2);
          context.fill();
        });
        return;
      }
      if (animate) playReveal(); else root.classList.add("ready");
      if (!frame) { last = performance.now(); frame = requestAnimationFrame(step); }
    },
    destroy() { cancelAnimationFrame(frame); frame = 0; resize.disconnect(); seen.disconnect(); },
  };
}

export default function ({ data, parentElement, setTriggerValue }) {
  const root = parentElement.querySelector(".river");
  root._pick = (key) => setTriggerValue("picked", key);
  const first = !root._river;
  if (first) root._river = createRiver(root, (key) => root._pick(key));
  root._river.update(data, first);
  return () => { root._river?.destroy(); root._river = null; };
}
"""
)

_GAUGES_HTML = '<div class="strip"></div>'
_GAUGES_CSS = """
.strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(10.5rem, 1fr));
  border-top: 1px solid #1C3A63;
  border-bottom: 1px solid #1C3A63;
  font-family: inherit;
}
.gauge { padding: .95rem 1.1rem .8rem 0; min-width: 0; }
.gauge + .gauge { padding-left: 1.1rem; box-shadow: -1px 0 0 #1C3A63; }
.name { color: #B4C7DF; font-size: .8rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.value { color: #EAF4FF; font-size: clamp(1.35rem, 2vw, 1.72rem); font-weight: 600; letter-spacing: -.025em; margin-top: .2rem; }
.delta { display: flex; align-items: center; gap: .3rem; margin-top: .15rem; font-size: .78rem; color: #8BA3C2; }
.delta b { font-weight: 600; }
.delta.good b { color: #2DBE6C; }
.delta.bad b { color: #F0616D; }
svg { display: block; width: 100%; height: 30px; margin-top: .4rem; overflow: visible; }
"""
_GAUGES_JS = (
    _SHARED_JS
    + r"""
function format(item, value) {
  if (item.kind === "percent") return `${(value * 100).toFixed(1)}%`;
  if (item.kind === "count") return Math.round(value).toLocaleString("en-US");
  const size = Math.abs(value);
  const sign = value < 0 ? "−" : "";
  const [scaled, unit] = size >= 1e9 ? [size / 1e9, "B"] : size >= 1e6 ? [size / 1e6, "M"] : size >= 1e3 ? [size / 1e3, "K"] : [size, ""];
  const text = unit === "K" ? scaled.toFixed(1) : unit ? scaled.toFixed(2) : Math.round(scaled).toLocaleString("en-US");
  return `${sign}${item.symbol}${text}${unit}`;
}

function sparkline(points) {
  if (!points || points.length < 2) return "";
  const low = Math.min(...points), high = Math.max(...points);
  const range = high - low || 1;
  const coords = points.map((v, i) => [(i / (points.length - 1)) * 100, 26 - ((v - low) / range) * 22]);
  const line = coords.map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
  const [ex, ey] = coords[coords.length - 1];
  return `<svg viewBox="0 0 100 30" preserveAspectRatio="none" aria-hidden="true">
    <polygon points="0,30 ${line} 100,30" fill="rgba(56,214,196,.1)"/>
    <polyline points="${line}" fill="none" stroke="#38D6C4" stroke-width="1.5" vector-effect="non-scaling-stroke"/>
  </svg>`;
}

export default function ({ data, parentElement }) {
  const strip = parentElement.querySelector(".strip");
  const previous = strip._values || {};
  strip.innerHTML = data.items.map((item, index) => `
    <div class="gauge">
      <div class="name" title="${esc(item.label)}">${esc(item.label)}</div>
      <div class="value" data-index="${index}">${esc(item.display)}</div>
      <div class="delta ${esc(item.tone)}"><b>${esc(item.delta)}</b><span>${esc(item.note)}</span></div>
      ${sparkline(item.spark)}
    </div>`).join("");
  const nodes = [...strip.querySelectorAll(".value")];
  if (!reduced()) {
    const started = performance.now();
    const tick = (time) => {
      const progress = clamp((time - started) / 1000, 0, 1);
      nodes.forEach((node, index) => {
        const item = data.items[index];
        const from = previous[item.label] ?? 0;
        node.textContent = progress < 1 ? format(item, from + (item.raw - from) * easeOut(progress)) : item.display;
      });
      if (progress < 1) strip._frame = requestAnimationFrame(tick);
    };
    cancelAnimationFrame(strip._frame);
    strip._frame = requestAnimationFrame(tick);
  }
  strip._values = Object.fromEntries(data.items.map((item) => [item.label, item.raw]));
  return () => cancelAnimationFrame(strip._frame);
}
"""
)

_DROP_HTML = '<div class="drop"><canvas></canvas><div class="tip"></div></div>'
_DROP_CSS = (
    _TOOLTIP_CSS
    + """
.drop { position: relative; width: 100%; height: 340px; font-family: inherit; }
canvas { display: block; }
"""
)
_DROP_JS = (
    _SHARED_JS
    + r"""
function runDrop(root, data) {
  const canvas = root.querySelector("canvas");
  const tip = root.querySelector(".tip");
  const width = Math.max(root.clientWidth, 320);
  const height = 340;
  const context = fitCanvas(canvas, width, height);
  const plot = { left: 8, right: width - 8, top: 46, bottom: height - 40 };
  const bins = data.counts.length;
  const barWidth = (plot.right - plot.left) / bins;
  const peak = Math.max(...data.counts, 1);
  const unit = (plot.bottom - plot.top) / peak;
  const total = data.counts.reduce((sum, v) => sum + v, 0) || 1;
  const xAt = (value) => plot.left + ((value - data.edges[0]) / (data.edges[bins] - data.edges[0])) * (plot.right - plot.left);
  const positive = (index) => (data.edges[index] + data.edges[index + 1]) / 2 >= 0;
  const landed = new Array(bins).fill(0);
  const dots = [];
  data.counts.forEach((count, index) => {
    const share = Math.round((count / total) * 620);
    for (let i = 0; i < share; i += 1) {
      dots.push({ bin: index, delay: Math.random() * 1500, weight: count / Math.max(share, 1), jitter: Math.random() });
    }
  });
  const duration = 2100, fall = 460;
  const started = performance.now();

  function paint(progress, time) {
    context.clearRect(0, 0, width, height);
    context.strokeStyle = "#1C3A63";
    context.lineWidth = 1;
    context.beginPath();
    context.moveTo(plot.left, plot.bottom + 0.5);
    context.lineTo(plot.right, plot.bottom + 0.5);
    context.stroke();
    for (let index = 0; index < bins; index += 1) {
      const heightNow = (progress >= 1 ? data.counts[index] : landed[index]) * unit;
      if (heightNow <= 0) continue;
      context.fillStyle = rgba(positive(index) ? RGB.flow : RGB.leak, 0.82);
      const x = plot.left + index * barWidth + 1;
      const w = Math.max(barWidth - 2, 1);
      context.beginPath();
      context.roundRect(x, plot.bottom - heightNow, w, heightNow, [2, 2, 0, 0]);
      context.fill();
    }
    if (time !== undefined) {
      landed.fill(0);
      for (const dot of dots) {
        const age = time - dot.delay;
        if (age < 0) continue;
        const stage = age / fall;
        if (stage >= 1) { landed[dot.bin] += dot.weight; continue; }
        const x = plot.left + (dot.bin + dot.jitter) * barWidth;
        const y = plot.top - 30 + (plot.bottom - plot.top + 30) * stage * stage;
        context.fillStyle = rgba(positive(dot.bin) ? RGB.flow : RGB.leak, 0.9);
        context.beginPath();
        context.arc(x, y, 1.5, 0, Math.PI * 2);
        context.fill();
      }
    }
    context.font = "12px Sora, 'Microsoft YaHei', sans-serif";
    context.textBaseline = "alphabetic";
    context.fillStyle = "#8BA3C2";
    data.ticks.forEach((tick) => {
      context.textAlign = "center";
      context.fillText(tick.label, clamp(xAt(tick.value), 30, width - 30), height - 16);
    });
    const reach = easeOut(clamp((progress - 0.55) / 0.45, 0, 1));
    if (reach > 0) {
      const mark = (value, color, text, align, row) => {
        const x = xAt(value);
        context.strokeStyle = color;
        context.globalAlpha = reach;
        context.lineWidth = 1.5;
        context.beginPath();
        context.moveTo(x + 0.5, plot.top - 8);
        context.lineTo(x + 0.5, plot.bottom);
        context.stroke();
        context.fillStyle = "#EAF4FF";
        context.textAlign = align;
        context.fillText(text, x + (align === "left" ? 6 : -6), plot.top - 12 - row * 16);
        context.globalAlpha = 1;
      };
      const middle = xAt(data.median) > width / 2;
      const crowded = Math.abs(xAt(data.median) - xAt(0)) < 90;
      if (!crowded) mark(0, "#8BA3C2", data.labels.zero, xAt(0) > width / 2 ? "right" : "left", 0);
      mark(data.median, "#FFC44D", data.labels.median, middle ? "right" : "left", 0);
    }
  }

  function tick(now) {
    const elapsed = now - started;
    const progress = clamp(elapsed / duration, 0, 1);
    paint(progress, elapsed);
    if (progress < 1) root._frame = requestAnimationFrame(tick);
    else paint(1);
  }
  cancelAnimationFrame(root._frame);
  if (reduced()) paint(1); else root._frame = requestAnimationFrame(tick);

  canvas.onpointermove = (event) => {
    const box = canvas.getBoundingClientRect();
    const index = Math.floor((event.clientX - box.left - plot.left) / barWidth);
    if (index < 0 || index >= bins) { tip.classList.remove("on"); return; }
    tip.innerHTML = `<b>${esc(data.binLabels[index])}</b><span>${esc(data.binShares[index])}</span>`;
    tip.style.left = `${clamp(event.clientX - box.left + 12, 0, width - 170)}px`;
    tip.style.top = `${clamp(event.clientY - box.top - 56, 0, height - 70)}px`;
    tip.classList.add("on");
  };
  canvas.onpointerleave = () => tip.classList.remove("on");
}

export default function ({ data, parentElement }) {
  const root = parentElement.querySelector(".drop");
  if (root._signature !== data.signature) {
    root._signature = data.signature;
    root.setAttribute("role", "img");
    root.setAttribute("aria-label", data.summary);
    runDrop(root, data);
  }
  return () => cancelAnimationFrame(root._frame);
}
"""
)

_GLOBE_HTML = '<div class="globe" tabindex="0" role="application"><canvas></canvas><div class="tip" aria-live="polite"></div></div>'
_GLOBE_CSS = (
    _TOOLTIP_CSS
    + """
.globe { position: relative; width: 100%; height: 520px; touch-action: none; cursor: grab; outline: none; font-family: inherit; }
.globe:active { cursor: grabbing; }
.globe:focus-visible { outline: 2px solid #38D6C4; outline-offset: 2px; border-radius: 6px; }
canvas { display: block; }
"""
)
_GLOBE_JS = (
    _SHARED_JS
    + r"""
const LAND = __LAND__;
const RAD = Math.PI / 180;
const landCount = LAND.length / 2;
const landCos = new Float32Array(landCount), landSin = new Float32Array(landCount), landLon = new Float32Array(landCount);
for (let i = 0; i < landCount; i += 1) {
  landCos[i] = Math.cos(LAND[i * 2] * RAD);
  landSin[i] = Math.sin(LAND[i * 2] * RAD);
  landLon[i] = LAND[i * 2 + 1] * RAD;
}

function createGlobe(root, onSelect) {
  const canvas = root.querySelector("canvas");
  const tip = root.querySelector(".tip");
  let markets = [], width = 0, height = 0, context = null, radius = 0, cx = 0, cy = 0;
  let spin = 0, tilt = 0.32, frame = 0, visible = true, last = 0, selected = null;
  let dragging = false, moved = 0, hover = null, startX = 0, startY = 0, baseSpin = 0, baseTilt = 0;
  let cursor = -1;

  const resize = () => {
    width = Math.max(root.clientWidth, 300);
    height = root.clientHeight;
    context = fitCanvas(canvas, width, height);
    radius = Math.min(width, height) * 0.46;
    cx = width / 2;
    cy = height / 2;
  };

  function project(cosLat, sinLat, lon) {
    const relative = lon + spin;
    const x = cosLat * Math.sin(relative);
    const y0 = sinLat;
    const z0 = cosLat * Math.cos(relative);
    const cosT = Math.cos(tilt), sinT = Math.sin(tilt);
    return { x: cx + radius * x, y: cy - radius * (y0 * cosT - z0 * sinT), z: y0 * sinT + z0 * cosT };
  }

  function draw() {
    context.clearRect(0, 0, width, height);
    const sea = context.createRadialGradient(cx - radius * 0.35, cy - radius * 0.4, radius * 0.1, cx, cy, radius);
    sea.addColorStop(0, "#1A3F70");
    sea.addColorStop(1, "#0C2342");
    context.fillStyle = sea;
    context.beginPath();
    context.arc(cx, cy, radius, 0, Math.PI * 2);
    context.fill();
    context.strokeStyle = "#274A78";
    context.lineWidth = 1;
    context.stroke();

    for (let i = 0; i < landCount; i += 1) {
      const point = project(landCos[i], landSin[i], landLon[i]);
      if (point.z <= 0.02) continue;
      context.fillStyle = `rgba(180,199,223,${0.22 + 0.6 * point.z})`;
      context.fillRect(point.x - 1, point.y - 1, 2, 2);
    }

    const placed = markets
      .map((market) => ({ market, point: project(Math.cos(market.lat * RAD), Math.sin(market.lat * RAD), market.lon * RAD) }))
      .filter((item) => item.point.z > 0.04)
      .sort((a, b) => b.market.share - a.market.share);
    placed.forEach(({ market, point }) => {
      const size = 3 + 19 * Math.sqrt(market.share / markets[0].share);
      const color = market.strong ? RGB.flow : RGB.leak;
      context.fillStyle = rgba(color, 0.55);
      context.strokeStyle = market.name === selected ? "#FFC44D" : rgba(color, 1);
      context.lineWidth = market.name === selected || market === hover ? 2.5 : 1.25;
      context.beginPath();
      context.arc(point.x, point.y, size, 0, Math.PI * 2);
      context.fill();
      context.stroke();
      market._x = point.x; market._y = point.y; market._r = size; market._seen = true;
    });
    markets.forEach((market) => { if (!placed.find((item) => item.market === market)) market._seen = false; });
  }

  function step(time) {
    frame = requestAnimationFrame(step);
    if (!visible || document.hidden) { last = time; return; }
    const dt = Math.min((time - last) / 1000, 0.05);
    last = time;
    if (!dragging && !hover) spin += dt * 0.045;
    draw();
  }

  function pick(event) {
    const box = canvas.getBoundingClientRect();
    const x = event.clientX - box.left, y = event.clientY - box.top;
    let best = null, distance = Infinity;
    for (const market of markets) {
      if (!market._seen) continue;
      const gap = Math.hypot(market._x - x, market._y - y);
      if (gap < Math.max(market._r, 12) && gap < distance) { best = market; distance = gap; }
    }
    return { best, x, y };
  }

  function describe(market, x, y) {
    tip.innerHTML = `<b>${esc(market.label)}</b><span>${esc(market.revenue)}</span><span>${esc(market.margin)}</span><span>${esc(market.shareText)}</span>`;
    tip.style.left = `${clamp(x + 14, 0, width - 180)}px`;
    tip.style.top = `${clamp(y - 30, 0, height - 110)}px`;
    tip.classList.add("on");
  }

  function stepTo(index) {
    cursor = (index + markets.length) % markets.length;
    hover = markets[cursor];
    spin = -hover.lon * RAD;
    draw();
    describe(hover, hover._x, hover._y);
  }

  root.addEventListener("pointerdown", (event) => {
    dragging = true; moved = 0; startX = event.clientX; startY = event.clientY; baseSpin = spin; baseTilt = tilt;
    root.setPointerCapture(event.pointerId);
  });
  root.addEventListener("pointermove", (event) => {
    if (dragging) {
      moved += Math.abs(event.movementX) + Math.abs(event.movementY);
      spin = baseSpin + (event.clientX - startX) * 0.006;
      tilt = clamp(baseTilt + (event.clientY - startY) * 0.005, -1.1, 1.1);
      draw();
      return;
    }
    const { best, x, y } = pick(event);
    hover = best;
    if (best) {
      describe(best, x, y);
      root.style.cursor = "pointer";
    } else {
      tip.classList.remove("on");
      root.style.cursor = "";
    }
    if (reduced()) draw();
  });
  root.addEventListener("pointerup", (event) => {
    dragging = false;
    if (moved < 6) {
      const { best } = pick(event);
      if (best) { selected = best.name; onSelect(best.name); draw(); }
    }
  });
  root.addEventListener("pointerleave", () => { hover = null; tip.classList.remove("on"); });
  root.addEventListener("keydown", (event) => {
    const moves = { ArrowLeft: 0.2, ArrowRight: -0.2 };
    if (event.key in moves) { spin += moves[event.key]; draw(); event.preventDefault(); }
    if (!markets.length) return;
    if (event.key === "ArrowDown") { stepTo(cursor + 1); event.preventDefault(); }
    if (event.key === "ArrowUp") { stepTo(Math.max(cursor, 0) - 1); event.preventDefault(); }
    if (event.key === "Enter" && hover) { selected = hover.name; onSelect(hover.name); draw(); event.preventDefault(); }
  });
  root.addEventListener("blur", () => { hover = null; cursor = -1; tip.classList.remove("on"); });

  const observer = new ResizeObserver(() => { resize(); draw(); });
  observer.observe(root);
  const seen = whenVisible(root, (state) => { visible = state; });
  resize();

  return {
    update(data) {
      const first = markets.length === 0;
      markets = data.markets;
      selected = data.selected;
      if (first && markets.length) spin = -markets[0].lon * RAD;
      root.setAttribute("aria-label", data.summary);
      draw();
      if (!reduced() && !frame) { last = performance.now(); frame = requestAnimationFrame(step); }
    },
    destroy() { cancelAnimationFrame(frame); frame = 0; observer.disconnect(); seen.disconnect(); },
  };
}

export default function ({ data, parentElement, setTriggerValue }) {
  const root = parentElement.querySelector(".globe");
  root._emit = (name) => setTriggerValue("selected", name);
  if (!root._globe) root._globe = createGlobe(root, (name) => root._emit(name));
  root._globe.update(data);
  return () => { root._globe?.destroy(); root._globe = null; };
}
"""
)


def _land_dots() -> str:
    return (resources.files("insightflow") / "assets" / "land_dots.json").read_text(encoding="utf-8")


river = st.components.v2.component(
    "insightflow_river", html=_RIVER_HTML, css=_RIVER_CSS, js=_RIVER_JS
)
gauges = st.components.v2.component(
    "insightflow_gauges", html=_GAUGES_HTML, css=_GAUGES_CSS, js=_GAUGES_JS
)
drop = st.components.v2.component("insightflow_drop", html=_DROP_HTML, css=_DROP_CSS, js=_DROP_JS)
globe = st.components.v2.component(
    "insightflow_globe",
    html=_GLOBE_HTML,
    css=_GLOBE_CSS,
    js=_GLOBE_JS.replace("__LAND__", _land_dots()),
)


def money_river(payload: dict[str, Any], *, key: str) -> str | None:
    """Show the river and return the outflow clicked on this run, if any."""
    result = river(data=payload, key=key, on_picked_change=lambda: None)
    return getattr(result, "picked", None)


def gauge_strip(items: list[dict[str, Any]], *, key: str) -> None:
    gauges(data={"items": items}, key=key)


def simulation_drop(payload: dict[str, Any], *, key: str) -> None:
    drop(data=payload, key=key)


def market_globe(payload: dict[str, Any], *, key: str) -> str | None:
    """Show the globe and return the market clicked on this run, if any."""
    result = globe(data=payload, key=key, on_selected_change=lambda: None)
    return getattr(result, "selected", None)
