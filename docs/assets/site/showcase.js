/* InsightFlow showcase: the motion layer.
 * The page is complete without this file. Everything here is decoration: it starts
 * only when needed, pauses off screen, and stays still when the system asks for
 * reduced motion. */
(() => {
  "use strict";

  const doc = document.documentElement;
  const motion = !matchMedia("(prefers-reduced-motion: reduce)").matches;
  const finePointer = matchMedia("(hover: hover) and (pointer: fine)").matches;
  const raf = (fn) => requestAnimationFrame(fn);
  const clamp01 = (v) => Math.min(1, Math.max(0, v));
  const pageTop = (el) => {
    let top = 0;
    for (let node = el; node; node = node.offsetParent) top += node.offsetTop;
    return top;
  };

  /* Navigation: transparent over the hero, a progress line, and the current section. */
  function initNav() {
    const nav = document.querySelector(".toc");
    if (!nav) return;
    const bar = document.createElement("span");
    bar.className = "toc-progress";
    bar.setAttribute("aria-hidden", "true");
    nav.append(bar);
    let queued = false;
    const paint = () => {
      queued = false;
      const max = doc.scrollHeight - innerHeight;
      const y = scrollY;
      bar.style.transform = `scaleX(${max > 0 ? clamp01(y / max).toFixed(4) : 0})`;
      nav.classList.toggle("is-top", y < 24);
    };
    const queue = () => {
      if (!queued) {
        queued = true;
        raf(paint);
      }
    };
    addEventListener("scroll", queue, { passive: true });
    addEventListener("resize", queue, { passive: true });
    paint();

    if (!("IntersectionObserver" in window)) return;
    const strip = nav.querySelector(".links");
    const links = [...nav.querySelectorAll('.links a[href^="#"]')];
    const byId = new Map(links.map((a) => [a.getAttribute("href").slice(1), a]));
    const spy = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          const active = byId.get(entry.target.id);
          for (const a of links) {
            a.classList.toggle("is-active", a === active);
            if (a === active) a.setAttribute("aria-current", "location");
            else a.removeAttribute("aria-current");
          }
          if (active && strip && strip.scrollWidth > strip.clientWidth + 2) {
            const left = active.offsetLeft - (strip.clientWidth - active.offsetWidth) / 2;
            strip.scrollTo({ left, behavior: motion ? "smooth" : "auto" });
          }
        }
      },
      { rootMargin: "-40% 0px -55% 0px" }
    );
    for (const id of byId.keys()) {
      const target = document.getElementById(id);
      if (target) spy.observe(target);
    }
  }

  /* Counters roll up to the published figure; screen readers get the figure itself. */
  function prepareCounter(b) {
    const text = b.textContent.trim();
    const match = text.match(/^(\D*?)(\d[\d,]*(?:\.\d+)?)(.*)$/);
    if (!match) return null;
    const [, prefix, digits, suffix] = match;
    const decimals = (digits.split(".")[1] || "").length;
    const grouped = digits.includes(",");
    const target = Number(digits.replace(/,/g, ""));
    const format = (value) =>
      prefix +
      value.toLocaleString("en-US", {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
        useGrouping: grouped,
      }) +
      suffix;
    const label = document.createElement("span");
    label.className = "sr-only";
    label.textContent = text;
    const shown = document.createElement("span");
    shown.setAttribute("aria-hidden", "true");
    shown.textContent = format(0);
    b.replaceChildren(label, shown);
    return () => {
      const started = performance.now();
      const duration = 1600;
      let last = 0;
      const step = (now) => {
        const p = Math.min(1, (now - started) / duration);
        if (target === 0) {
          // A zero has nothing to count toward, so its digits scan before they settle.
          if (p < 0.75) {
            if (now - last > 70) {
              last = now;
              shown.textContent = format(Math.random() * 9.99);
            }
          } else {
            shown.textContent = format(0);
          }
        } else {
          shown.textContent = format(target * (p < 1 ? 1 - Math.pow(2, -10 * p) : 1));
        }
        if (p < 1) raf(step);
        else shown.textContent = text;
      };
      raf(step);
    };
  }

  /* Scroll reveals: text rises out of a soft blur, screenshots lift into place. */
  function initReveal() {
    if (!motion || !("IntersectionObserver" in window)) return;
    const tagged = [];
    const counters = new Map();
    const tag = (el, variant, index) => {
      if (!el || el.classList.contains("rv")) return;
      el.classList.add("rv");
      if (variant) el.classList.add(variant);
      if (index) el.style.setProperty("--rv-i", String(index));
      tagged.push(el);
    };
    const group = (selector, children, variant) => {
      for (const parent of document.querySelectorAll(selector)) {
        parent.querySelectorAll(children).forEach((el, i) => tag(el, variant, i));
      }
    };

    for (const section of document.querySelectorAll("section")) {
      section.classList.add("rv-line");
      tagged.push(section);
      [...section.children]
        .filter((el) => el.matches(".chapter, h2, h3, .section-lede"))
        .forEach((el, i) => tag(el, null, i));
    }
    group(".feature-text", "h3, p, li", null);
    for (const block of document.querySelectorAll(".feature, .pair")) {
      block.querySelectorAll("figure").forEach((figure, i) => tag(figure, "rv-rise", i));
    }
    for (const figure of document.querySelectorAll("figure.wide")) tag(figure, "rv-rise", 0);
    for (const pipe of document.querySelectorAll(".pipeline")) {
      pipe.classList.add("rv-pipe");
      tag(pipe, "rv-fade", 0);
    }
    group(".stages", ":scope > div", "rv-fade");
    group(".stats", ".stat", "rv-fade");
    group(".cards", ".card", "rv-fade");
    group(".lessons tbody", "tr", "rv-row");
    for (const el of document.querySelectorAll(".table-scroll, pre")) tag(el, "rv-fade", 0);
    for (const b of document.querySelectorAll(".stat b")) {
      const run = prepareCounter(b);
      if (run) counters.set(b.closest(".stat"), run);
    }

    const show = (el) => {
      el.classList.add("is-in");
      const run = counters.get(el);
      if (run) {
        counters.delete(el);
        run();
      }
    };
    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          show(entry.target);
          io.unobserve(entry.target);
        }
      },
      { rootMargin: "0px 0px -10% 0px", threshold: 0 }
    );
    // Anything already on screen (a reload mid-page, an anchor link) appears at once.
    const limit = innerHeight * 0.9;
    for (const el of tagged) {
      const box = el.getBoundingClientRect();
      if (box.top < limit && box.bottom > 0) show(el);
      else io.observe(el);
    }
  }

  /* The title assembles letter by letter. */
  function splitTitle() {
    const h1 = document.querySelector(".hero h1");
    if (!h1 || !motion) return;
    const spoken = h1.textContent.replace(/\s+/g, " ").trim();
    let index = 0;
    const split = (node) => {
      for (const child of [...node.childNodes]) {
        if (child.nodeType === Node.TEXT_NODE) {
          // Letters are grouped by word so a line can only break between words.
          const pieces = document.createDocumentFragment();
          for (const part of child.nodeValue.split(/(\s+)/)) {
            if (!part) continue;
            if (/^\s+$/.test(part)) {
              pieces.append(part);
              index += part.length;
              continue;
            }
            const word = document.createElement("span");
            word.className = "word";
            word.setAttribute("aria-hidden", "true");
            for (const character of part) {
              const span = document.createElement("span");
              span.className = "ch";
              span.textContent = character;
              span.style.setProperty("--c", String(index++));
              word.append(span);
            }
            pieces.append(word);
          }
          child.replaceWith(pieces);
        } else if (child.nodeType === Node.ELEMENT_NODE) {
          split(child);
        }
      }
    };
    split(h1);
    const label = document.createElement("span");
    label.className = "sr-only";
    label.textContent = spoken;
    h1.append(label);
    h1.classList.add("is-split");
  }

  /* A spotlight follows the pointer along the edge of frames, cards and figures. */
  function initPointer() {
    if (!finePointer) return;
    let frame = 0;
    let current = null;
    let px = 0;
    let py = 0;
    const apply = () => {
      frame = 0;
      if (!current) return;
      const box = current.getBoundingClientRect();
      current.style.setProperty("--mx", `${(px - box.left).toFixed(0)}px`);
      current.style.setProperty("--my", `${(py - box.top).toFixed(0)}px`);
    };
    for (const el of document.querySelectorAll(".shot, .card, .stat")) {
      el.addEventListener(
        "pointermove",
        (event) => {
          current = el;
          px = event.clientX;
          py = event.clientY;
          if (!frame) frame = raf(apply);
        },
        { passive: true }
      );
      el.addEventListener("pointerleave", () => {
        if (current === el) current = null;
      });
    }
  }

  /* Depth: the nebula drifts slower than the page, the hero text lifts away,
   * and the product shot straightens out of a tilt as it scrolls into view. */
  function initParallax() {
    if (!motion) return;
    const nebula = document.querySelector(".backdrop-nebula");
    const stage = document.querySelector(".hero-stage");
    const hero = stage && stage.querySelector(".hero");
    const shot = document.querySelector("figure.hero-shot");
    let stageHeight = 1;
    let range = 1;
    let shotTop = 0;
    const measure = () => {
      stageHeight = stage ? stage.offsetHeight : 1;
      range = Math.max(1, doc.scrollHeight - innerHeight);
      shotTop = shot ? pageTop(shot) : 0;
    };
    let queued = false;
    const paint = () => {
      queued = false;
      const y = scrollY;
      if (nebula) nebula.style.transform = `translate3d(0, ${(-(y / range) * innerHeight * 0.05).toFixed(1)}px, 0)`;
      if (hero && y < stageHeight * 1.1) {
        const p = Math.min(1, y / stageHeight);
        hero.style.transform = p > 0 ? `translate3d(0, ${(y * 0.32).toFixed(1)}px, 0)` : "";
        hero.style.opacity = p > 0 ? Math.max(0, 1 - p * 1.4).toFixed(3) : "";
      }
      if (shot) {
        const p = clamp01((y + innerHeight - shotTop) / (innerHeight * 0.85));
        const e = 1 - Math.pow(1 - p, 3);
        if (e < 1) {
          shot.style.transform = `perspective(2000px) translate3d(0, ${((1 - e) * 80).toFixed(1)}px, 0) rotateX(${((1 - e) * 28).toFixed(2)}deg) scale(${(0.88 + 0.12 * e).toFixed(4)})`;
          shot.style.opacity = (0.2 + 0.8 * e).toFixed(3);
        } else {
          shot.style.transform = "";
          shot.style.opacity = "";
        }
      }
    };
    const queue = () => {
      if (!queued) {
        queued = true;
        raf(paint);
      }
    };
    measure();
    addEventListener("scroll", queue, { passive: true });
    addEventListener(
      "resize",
      () => {
        measure();
        queue();
      },
      { passive: true }
    );
    addEventListener("load", () => {
      measure();
      queue();
    });
    paint();
  }

  /* ---------- Hero: the money river as strands of light (WebGL2 with bloom) ---------- */

  const QUAD_VERTEX = `#version 300 es
out vec2 vUv;
void main() {
  vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
  vUv = p;
  gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}`;

  const BACKGROUND = `#version 300 es
precision highp float;
uniform vec2 uRes;
uniform float uTime;
uniform float uHorizon;
uniform float uReveal;
uniform vec3 uMouse;
uniform vec4 uRipple;
out vec4 outColor;

float hash(vec2 p) {
  p = fract(p * vec2(234.34, 435.345));
  p += dot(p, p + 34.23);
  return fract(p.x * p.y);
}

void main() {
  vec2 q = vec2(gl_FragCoord.x / uRes.x, 1.0 - gl_FragCoord.y / uRes.y);
  float aspect = uRes.x / uRes.y;
  float lit = clamp(uReveal, 0.0, 1.0);
  vec3 col = vec3(0.0);

  // Sparse stars that breathe slowly and shift a little with the pointer.
  vec2 sp = vec2(q.x * aspect, q.y) * 46.0 + (uMouse.xy - 0.5) * vec2(2.4, 1.6);
  vec2 cell = floor(sp);
  float h = hash(cell);
  if (h > 0.972) {
    vec2 c = vec2(hash(cell + 1.7), hash(cell + 9.1)) * 0.8 + 0.1;
    float d = length(fract(sp) - c);
    float tw = 0.6 + 0.4 * sin(uTime * (0.4 + 1.6 * h) + h * 70.0);
    float s = smoothstep(0.07, 0.0, d) * tw * (1.0 - smoothstep(uHorizon - 0.35, uHorizon - 0.05, q.y));
    col += vec3(0.78, 0.88, 1.0) * s * 0.55;
  }

  // A faint sheet of light under the river, like a reflection on glass.
  float depth = q.y - uHorizon;
  float sheet = exp(-pow(depth * 16.0, 2.0)) * 0.06 + (depth > 0.0 ? exp(-depth * 5.0) * 0.025 : 0.0);
  float spread = 1.0 - smoothstep(0.2, 0.75, abs(q.x - 0.55) * 1.2);
  col += vec3(0.24, 0.86, 0.79) * sheet * spread * lit;

  // The ring a click sends out.
  if (uRipple.w > 0.0) {
    vec2 rd = (q - uRipple.xy) * vec2(aspect, 1.0);
    float r = length(rd);
    float ring = exp(-pow((r - uRipple.z * 0.55) * 30.0, 2.0)) * exp(-uRipple.z * 1.4) * uRipple.w;
    col += vec3(0.55, 1.0, 0.95) * ring * 0.32;
  }

  float a = clamp(max(col.r, max(col.g, col.b)), 0.0, 1.0);
  outColor = vec4(col, a);
}`;

  const STRANDS_VERTEX = `#version 300 es
precision highp float;
layout(location = 0) in vec4 aSeed;
layout(location = 1) in vec2 aKind;
uniform vec2 uRes;
uniform float uTime;
uniform float uReveal;
uniform float uTop;
uniform float uWidth;
uniform float uFall;
uniform float uRate;
uniform float uPx;
uniform vec3 uMouse;
uniform vec4 uRipple;
uniform float uShare[8];
uniform float uOffset[8];
uniform float uBranch[8];
out vec2 vUv;
out vec3 vColor;
out float vAlpha;
out float vPacket;

const vec3 TEAL = vec3(0.24, 0.86, 0.79);
const vec3 AQUA = vec3(0.70, 0.98, 0.95);
const vec3 GOLD = vec3(0.96, 0.77, 0.40);
const vec3 CORAL = vec3(1.0, 0.5, 0.44);

float wave(float x) {
  return 0.014 * sin(x * 4.6 + uTime * 0.28) + 0.007 * sin(x * 10.3 - uTime * 0.41) + 0.009 * sin(x * 2.1 + 1.7);
}

// Where a strand of stream k sits at progress s: x across, y down, and how visible it is.
vec3 path(float s, int k, float lane) {
  float y0 = uTop + (uOffset[k] + lane * uShare[k]) * uWidth;
  float bx = uBranch[k];
  if (s <= bx) return vec3(s, y0 + wave(s), 1.0);
  float d = s - bx;
  float x = bx + d * 0.45;
  float y = y0 + wave(bx) + pow(d / 0.3, 1.7) * uFall + (lane - 0.5) * uShare[k] * uWidth * d * 2.5;
  return vec3(x, y, 1.0 - smoothstep(0.1, 0.3, d));
}

vec2 place(vec2 p, float depth) {
  vec2 aspect = vec2(uRes.x / uRes.y, 1.0);
  // Depth gives the river some body; near strands follow the pointer more than far ones.
  p.y += (depth - 0.5) * uWidth * 0.14;
  p += (uMouse.xy - 0.5) * (depth - 0.5) * vec2(-0.016, -0.01);
  vec2 d = (p - uMouse.xy) * aspect;
  float r = max(length(d), 1e-4);
  p += (d / r) / aspect * exp(-r * r / 0.012) * 0.04 * uMouse.z;
  if (uRipple.w > 0.0) {
    vec2 e = (p - uRipple.xy) * aspect;
    float re = max(length(e), 1e-4);
    float push = exp(-pow((re - uRipple.z * 0.55) * 11.0, 2.0)) * exp(-uRipple.z * 1.4) * uRipple.w;
    p += (e / re) / aspect * push * 0.03;
  }
  return p;
}

void main() {
  int k = int(aKind.x + 0.5);
  float depth = aKind.y;
  float packet = step(0.985, aSeed.w);
  float lane = aSeed.x;
  float life = k == 7 ? 1.12 : uBranch[k] + 0.3;
  float speed = uRate * (0.8 + 0.4 * aSeed.z) * (0.85 + 0.3 * depth) * (1.0 + packet * 0.9);
  float s = mod(aSeed.y * life + uTime * speed, life);
  float trail = mix(0.03 + 0.1 * aSeed.z, 0.045, packet);
  vec3 head = path(s, k, lane);
  vec3 tail = path(max(s - trail, 0.0), k, lane);
  head.xy = place(head.xy, depth);
  tail.xy = place(tail.xy, depth);

  vec2 hp = head.xy * uRes;
  vec2 tp = tail.xy * uRes;
  vec2 dir = hp - tp;
  float len = length(dir);
  dir = len > 0.001 ? dir / len : vec2(1.0, 0.0);
  vec2 nrm = vec2(-dir.y, dir.x);
  float want = mix(0.3 + 0.6 * depth, 1.3, packet);
  float halfWidth = max(want, 0.75);
  float cover = want / halfWidth;
  float thick = halfWidth * uPx;
  float cx = float(gl_VertexID & 1);
  float cy = float((gl_VertexID >> 1) & 1) * 2.0 - 1.0;
  vec2 pos = mix(tp, hp, cx) + nrm * cy * thick + dir * (cx * 2.0 - 1.0) * thick;

  vec3 col;
  if (k < 7) col = mix(TEAL, CORAL, smoothstep(uBranch[k] - 0.01, uBranch[k] + 0.08, s));
  else col = mix(mix(TEAL, AQUA, 0.25 * aSeed.z), GOLD, smoothstep(0.7, 0.97, head.x));
  col = mix(col, vec3(1.0), packet * 0.45);

  float a = head.z;
  a *= smoothstep(0.0, 0.05, head.x) * (1.0 - smoothstep(0.97, 1.03, head.x));
  float front = uReveal * 1.15 - 0.05;
  a *= smoothstep(front + 0.015, front - 0.06, head.x);
  a *= 1.0 + 2.0 * exp(-pow((head.x - front + 0.02) * 28.0, 2.0)) * (1.0 - smoothstep(0.95, 1.0, uReveal));
  float base = mix((0.05 + 0.3 * aSeed.w * aSeed.w) * (0.5 + 0.5 * depth), 0.9, packet);
  if (k == 7) base *= 1.0 + 0.7 * smoothstep(0.7, 1.0, head.x);
  else base *= 1.0 + 0.8 * smoothstep(uBranch[k], uBranch[k] + 0.06, s);

  vColor = col;
  vAlpha = a * base * cover;
  vPacket = packet;
  vUv = vec2(cx, cy);
  vec2 clip = pos / uRes * 2.0 - 1.0;
  gl_Position = vec4(clip.x, -clip.y, 0.0, 1.0);
}`;

  const STRANDS_FRAGMENT = `#version 300 es
precision highp float;
in vec2 vUv;
in vec3 vColor;
in float vAlpha;
in float vPacket;
out vec4 outColor;
void main() {
  float across = 1.0 - abs(vUv.y);
  float along = mix(vUv.x, pow(vUv.x, 4.0), vPacket);
  float a = vAlpha * across * across * along;
  outColor = vec4(vColor * a, a);
}`;

  const DOWNSAMPLE = `#version 300 es
precision highp float;
in vec2 vUv;
uniform sampler2D uTex;
uniform vec2 uTexel;
out vec4 outColor;
void main() {
  vec4 c = texture(uTex, vUv + uTexel * vec2(-0.5, -0.5));
  c += texture(uTex, vUv + uTexel * vec2(0.5, -0.5));
  c += texture(uTex, vUv + uTexel * vec2(-0.5, 0.5));
  c += texture(uTex, vUv + uTexel * vec2(0.5, 0.5));
  outColor = c * 0.25;
}`;

  const BLUR = `#version 300 es
precision highp float;
in vec2 vUv;
uniform sampler2D uTex;
uniform vec2 uDir;
out vec4 outColor;
void main() {
  vec4 c = texture(uTex, vUv) * 0.2270270270;
  c += texture(uTex, vUv + uDir * 1.3846153846) * 0.3162162162;
  c += texture(uTex, vUv - uDir * 1.3846153846) * 0.3162162162;
  c += texture(uTex, vUv + uDir * 3.2307692308) * 0.0702702703;
  c += texture(uTex, vUv - uDir * 3.2307692308) * 0.0702702703;
  outColor = c;
}`;

  const COMPOSITE = `#version 300 es
precision highp float;
in vec2 vUv;
uniform sampler2D uScene;
uniform sampler2D uNear;
uniform sampler2D uFar;
uniform float uGlow;
out vec4 outColor;
void main() {
  vec4 scene = texture(uScene, vUv);
  vec3 c = scene.rgb + texture(uNear, vUv).rgb * (0.85 * uGlow) + texture(uFar, vUv).rgb * (1.3 * uGlow);
  // A soft shoulder lets dense light roll off into white instead of clipping.
  c = 1.0 - exp(-c * 1.25);
  float a = clamp(max(scene.a, max(c.r, max(c.g, c.b))), 0.0, 1.0);
  outColor = vec4(c, a);
}`;

  // Each stream's share of gross sales, in the order the outflows leave the river.
  // The last entry is what remains as contribution profit.
  const SHARES = [0.06, 0.05, 0.36, 0.08, 0.03, 0.09, 0.04, 0.29];
  const BRANCH = [0.33, 0.4, 0.48, 0.57, 0.64, 0.71, 0.78, 9.0];
  const OFFSET = (() => {
    // Profit rides the top edge; outflows sit underneath in leaving order, so each peels off the bottom.
    const offsets = new Float32Array(8);
    let below = SHARES[7];
    for (let k = 6; k >= 0; k--) {
      offsets[k] = below;
      below += SHARES[k];
    }
    return offsets;
  })();

  function compile(gl, type, source) {
    const shader = gl.createShader(type);
    gl.shaderSource(shader, source);
    gl.compileShader(shader);
    if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
      const log = gl.getShaderInfoLog(shader);
      gl.deleteShader(shader);
      throw new Error(log || "shader failed to compile");
    }
    return shader;
  }

  function program(gl, vertex, fragment) {
    const prog = gl.createProgram();
    gl.attachShader(prog, compile(gl, gl.VERTEX_SHADER, vertex));
    gl.attachShader(prog, compile(gl, gl.FRAGMENT_SHADER, fragment));
    gl.linkProgram(prog);
    if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) throw new Error(gl.getProgramInfoLog(prog) || "link failed");
    const uniforms = {};
    const count = gl.getProgramParameter(prog, gl.ACTIVE_UNIFORMS);
    for (let i = 0; i < count; i++) {
      const name = gl.getActiveUniform(prog, i).name.replace(/\[0\]$/, "");
      uniforms[name] = gl.getUniformLocation(prog, name);
    }
    return { prog, uniforms };
  }

  function strands(count) {
    const weights = SHARES.map((share, k) => Math.max(share, 0.035) * (k === 7 ? 1.12 : BRANCH[k] + 0.3));
    const total = weights.reduce((sum, w) => sum + w, 0);
    const data = new Float32Array(count * 6);
    let o = 0;
    for (let i = 0; i < count; i++) {
      let r = Math.random() * total;
      let k = 0;
      while (k < 7 && (r -= weights[k]) > 0) k++;
      data[o++] = Math.random();
      data[o++] = Math.random();
      data[o++] = Math.random();
      data[o++] = Math.random();
      data[o++] = k;
      data[o++] = Math.random();
    }
    return data;
  }

  function initRiver() {
    const stage = document.querySelector(".hero-stage");
    const canvas = stage && stage.querySelector(".hero-canvas");
    if (!canvas) return;
    const gl = canvas.getContext("webgl2", {
      alpha: true,
      premultipliedAlpha: true,
      antialias: false,
      depth: false,
      stencil: false,
      powerPreference: "high-performance",
    });
    if (!gl) return;

    const hero = stage.querySelector(".hero");
    const tagBox = stage.querySelector(".river-tags");
    const names = (canvas.dataset.labels || "").split("|");
    const count = innerWidth < 700 ? 3600 : 9000;
    let drawCount = count;
    let quality = 1;

    let progs;
    try {
      progs = {
        background: program(gl, QUAD_VERTEX, BACKGROUND),
        strands: program(gl, STRANDS_VERTEX, STRANDS_FRAGMENT),
        down: program(gl, QUAD_VERTEX, DOWNSAMPLE),
        blur: program(gl, QUAD_VERTEX, BLUR),
        composite: program(gl, QUAD_VERTEX, COMPOSITE),
      };
    } catch (error) {
      console.warn("InsightFlow showcase: the light river is off.", error);
      return;
    }
    const emptyVao = gl.createVertexArray();
    const vao = gl.createVertexArray();
    gl.bindVertexArray(vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ARRAY_BUFFER, strands(count), gl.STATIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 4, gl.FLOAT, false, 24, 0);
    gl.vertexAttribDivisor(0, 1);
    gl.enableVertexAttribArray(1);
    gl.vertexAttribPointer(1, 2, gl.FLOAT, false, 24, 16);
    gl.vertexAttribDivisor(1, 1);
    gl.bindVertexArray(null);

    // Render targets for the glow: the scene at full size, then half and quarter size blurs.
    let targets = null;
    const makeTarget = (w, h) => {
      const tex = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, tex);
      gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA8, w, h, 0, gl.RGBA, gl.UNSIGNED_BYTE, null);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
      const fb = gl.createFramebuffer();
      gl.bindFramebuffer(gl.FRAMEBUFFER, fb);
      gl.framebufferTexture2D(gl.FRAMEBUFFER, gl.COLOR_ATTACHMENT0, gl.TEXTURE_2D, tex, 0);
      const ok = gl.checkFramebufferStatus(gl.FRAMEBUFFER) === gl.FRAMEBUFFER_COMPLETE;
      gl.bindFramebuffer(gl.FRAMEBUFFER, null);
      return ok ? { tex, fb, w, h } : null;
    };
    const dropTargets = () => {
      if (!targets) return;
      for (const t of Object.values(targets)) {
        gl.deleteFramebuffer(t.fb);
        gl.deleteTexture(t.tex);
      }
      targets = null;
    };
    const buildTargets = () => {
      dropTargets();
      const w = canvas.width;
      const h = canvas.height;
      const made = {
        scene: makeTarget(w, h),
        nearA: makeTarget(Math.ceil(w / 2), Math.ceil(h / 2)),
        nearB: makeTarget(Math.ceil(w / 2), Math.ceil(h / 2)),
        farA: makeTarget(Math.ceil(w / 4), Math.ceil(h / 4)),
        farB: makeTarget(Math.ceil(w / 4), Math.ceil(h / 4)),
      };
      if (Object.values(made).every(Boolean)) targets = made;
      else for (const t of Object.values(made)) if (t) {
        gl.deleteFramebuffer(t.fb);
        gl.deleteTexture(t.tex);
      }
    };

    const view = { w: 1, h: 1, top: 0.62, width: 0.14, fall: 0.18, horizon: 0.82, dpr: 1 };
    const tags = [];
    const placeTags = () => {
      if (!tagBox || names.length < 9) return;
      if (!tags.length) {
        names.forEach((name, i) => {
          const tag = document.createElement("span");
          tag.className = "river-tag" + (i === 0 ? " gross" : i === 8 ? " profit" : "");
          tag.textContent = name;
          tagBox.append(tag);
          tags.push({ el: tag, x: i === 0 ? 0 : i === 8 ? 0.9 : BRANCH[i - 1] + 0.09, on: false });
        });
      }
      const topPx = view.top * view.h;
      const widthPx = view.width * view.h;
      const fallPx = view.fall * view.h;
      tags.forEach((tag, i) => {
        let x;
        let y;
        if (i === 0) {
          x = view.w * 0.025;
          y = topPx - 34;
        } else if (i === 8) {
          x = view.w * 0.975;
          y = topPx - 34;
        } else {
          const k = i - 1;
          x = (BRANCH[k] + 0.2 * 0.45) * view.w;
          y = topPx + (OFFSET[k] + SHARES[k] / 2) * widthPx + Math.pow(0.2 / 0.3, 1.7) * fallPx + 34 + (k % 2) * 22;
        }
        tag.el.style.left = `${x.toFixed(1)}px`;
        tag.el.style.top = `${y.toFixed(1)}px`;
      });
    };

    const measure = () => {
      const w = stage.clientWidth;
      const textBottom = hero ? pageTop(hero) - pageTop(stage) + hero.offsetHeight : w * 0.3;
      // Sized from the viewport, not the stage, so growing the stage cannot feed back into it.
      const widthPx = Math.min(130, Math.max(80, innerHeight * 0.13));
      const fallPx = Math.min(170, Math.max(96, innerHeight * 0.16));
      const topPx = textBottom + (w < 700 ? 18 : 40);
      const needed = Math.ceil(topPx + widthPx + fallPx * 0.9 + 40);
      if (needed > stage.clientHeight + 1) stage.style.minHeight = `${needed}px`;
      const h = stage.clientHeight;
      view.w = w;
      view.h = h;
      view.top = topPx / h;
      view.width = widthPx / h;
      view.fall = fallPx / h;
      view.horizon = Math.min(0.97, (topPx + widthPx + fallPx * 0.45) / h);
      view.dpr = Math.min(devicePixelRatio || 1, w < 700 ? 1.5 : 1.75) * quality;
      canvas.width = Math.max(1, Math.round(w * view.dpr));
      canvas.height = Math.max(1, Math.round(h * view.dpr));
      buildTargets();
      placeTags();
    };

    // Pointer: near strands drift with it, the river parts around it, a click sends a ring through.
    const pointer = { x: 0.5, y: 0.5, tx: 0.5, ty: 0.5, s: 0, ts: 0 };
    const ripple = { x: 0.5, y: 0.5, start: -10, strength: 0 };
    let clock = 0;
    if (motion && finePointer) {
      stage.addEventListener(
        "pointermove",
        (event) => {
          const box = stage.getBoundingClientRect();
          pointer.tx = (event.clientX - box.left) / box.width;
          pointer.ty = (event.clientY - box.top) / box.height;
          pointer.ts = 1;
        },
        { passive: true }
      );
      stage.addEventListener("pointerleave", () => {
        pointer.tx = 0.5;
        pointer.ty = 0.5;
        pointer.ts = 0;
      });
    }
    if (motion) {
      stage.addEventListener("pointerdown", (event) => {
        if (event.target.closest("a, button")) return;
        const box = stage.getBoundingClientRect();
        ripple.x = (event.clientX - box.left) / box.width;
        ripple.y = (event.clientY - box.top) / box.height;
        ripple.start = clock;
        ripple.strength = 1;
      });
    }

    const pass = (prog, target, textures, setup) => {
      gl.bindFramebuffer(gl.FRAMEBUFFER, target ? target.fb : null);
      gl.viewport(0, 0, target ? target.w : canvas.width, target ? target.h : canvas.height);
      gl.useProgram(prog.prog);
      textures.forEach((tex, i) => {
        gl.activeTexture(gl.TEXTURE0 + i);
        gl.bindTexture(gl.TEXTURE_2D, tex);
      });
      setup(prog.uniforms);
      gl.bindVertexArray(emptyVao);
      gl.drawArrays(gl.TRIANGLES, 0, 3);
    };

    const draw = (time, reveal) => {
      const age = time - ripple.start;
      const rippleOn = ripple.strength > 0 && age < 3 ? ripple.strength : 0;
      gl.bindFramebuffer(gl.FRAMEBUFFER, targets ? targets.scene.fb : null);
      gl.viewport(0, 0, canvas.width, canvas.height);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.enable(gl.BLEND);

      const b = progs.background.uniforms;
      gl.useProgram(progs.background.prog);
      gl.blendFunc(gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
      gl.uniform2f(b.uRes, canvas.width, canvas.height);
      gl.uniform1f(b.uTime, time);
      gl.uniform1f(b.uHorizon, view.horizon);
      gl.uniform1f(b.uReveal, reveal);
      gl.uniform3f(b.uMouse, pointer.x, pointer.y, pointer.s);
      gl.uniform4f(b.uRipple, ripple.x, ripple.y, age, rippleOn);
      gl.bindVertexArray(emptyVao);
      gl.drawArrays(gl.TRIANGLES, 0, 3);

      const u = progs.strands.uniforms;
      gl.useProgram(progs.strands.prog);
      gl.blendFunc(gl.ONE, gl.ONE);
      gl.uniform2f(u.uRes, canvas.width, canvas.height);
      gl.uniform1f(u.uTime, time);
      gl.uniform1f(u.uReveal, reveal);
      gl.uniform1f(u.uTop, view.top);
      gl.uniform1f(u.uWidth, view.width);
      gl.uniform1f(u.uFall, view.fall);
      gl.uniform1f(u.uRate, 0.062);
      gl.uniform1f(u.uPx, view.dpr);
      gl.uniform3f(u.uMouse, pointer.x, pointer.y, pointer.s);
      gl.uniform4f(u.uRipple, ripple.x, ripple.y, age, rippleOn);
      gl.uniform1fv(u.uShare, SHARES);
      gl.uniform1fv(u.uOffset, OFFSET);
      gl.uniform1fv(u.uBranch, BRANCH);
      gl.bindVertexArray(vao);
      gl.drawArraysInstanced(gl.TRIANGLE_STRIP, 0, 4, drawCount);
      gl.disable(gl.BLEND);
      if (!targets) return;

      const t = targets;
      const down = progs.down;
      const blur = progs.blur;
      pass(down, t.nearA, [t.scene.tex], (v) => {
        gl.uniform1i(v.uTex, 0);
        gl.uniform2f(v.uTexel, 1 / t.scene.w, 1 / t.scene.h);
      });
      pass(blur, t.nearB, [t.nearA.tex], (v) => {
        gl.uniform1i(v.uTex, 0);
        gl.uniform2f(v.uDir, 1 / t.nearA.w, 0);
      });
      pass(blur, t.nearA, [t.nearB.tex], (v) => {
        gl.uniform1i(v.uTex, 0);
        gl.uniform2f(v.uDir, 0, 1 / t.nearA.h);
      });
      pass(down, t.farA, [t.nearA.tex], (v) => {
        gl.uniform1i(v.uTex, 0);
        gl.uniform2f(v.uTexel, 1 / t.nearA.w, 1 / t.nearA.h);
      });
      pass(blur, t.farB, [t.farA.tex], (v) => {
        gl.uniform1i(v.uTex, 0);
        gl.uniform2f(v.uDir, 1 / t.farA.w, 0);
      });
      pass(blur, t.farA, [t.farB.tex], (v) => {
        gl.uniform1i(v.uTex, 0);
        gl.uniform2f(v.uDir, 0, 1 / t.farA.h);
      });
      pass(progs.composite, null, [t.scene.tex, t.nearA.tex, t.farA.tex], (v) => {
        gl.uniform1i(v.uScene, 0);
        gl.uniform1i(v.uNear, 1);
        gl.uniform1i(v.uFar, 2);
        gl.uniform1f(v.uGlow, 1);
      });
    };

    const showTags = (reveal) => {
      const front = reveal * 1.15 - 0.05;
      for (const tag of tags) {
        if (!tag.on && front >= tag.x) {
          tag.on = true;
          tag.el.classList.add("is-on");
        }
      }
    };

    measure();
    if (!motion) {
      draw(6, 1);
      showTags(1);
      canvas.classList.add("is-live");
      new ResizeObserver(() => {
        measure();
        draw(6, 1);
      }).observe(stage);
      return;
    }

    let visible = true;
    let running = false;
    let last = 0;
    let revealClock = 0;
    const samples = [];
    let checks = 0;

    const loop = (now) => {
      if (!visible || document.hidden) {
        running = false;
        return;
      }
      const dt = last ? Math.min(0.05, (now - last) / 1000) : 0.016;
      last = now;
      clock += dt;
      revealClock += dt;
      pointer.x += (pointer.tx - pointer.x) * 0.06;
      pointer.y += (pointer.ty - pointer.y) * 0.06;
      pointer.s += (pointer.ts - pointer.s) * 0.05;
      const p = Math.min(1, revealClock / 3.2);
      const reveal = p < 0.5 ? 4 * p * p * p : 1 - Math.pow(-2 * p + 2, 3) / 2;
      draw(clock, reveal);
      showTags(reveal);

      // Drop resolution, then strands, if this device cannot keep up.
      if (revealClock > 3.5 && checks < 2) {
        samples.push(dt);
        if (samples.length === 90) {
          const mean = samples.reduce((a, b) => a + b, 0) / samples.length;
          samples.length = 0;
          checks++;
          if (mean > 0.021) {
            quality = Math.max(0.55, quality * 0.75);
            drawCount = Math.round(drawCount * 0.7);
            measure();
          }
        }
      }
      raf(loop);
    };
    const start = () => {
      if (running || !visible || document.hidden) return;
      running = true;
      last = 0;
      raf(loop);
    };

    new IntersectionObserver((entries) => {
      visible = entries[0].isIntersecting;
      start();
    }).observe(stage);
    document.addEventListener("visibilitychange", start);
    new ResizeObserver(() => measure()).observe(stage);
    canvas.addEventListener("webglcontextlost", (event) => {
      event.preventDefault();
      visible = false;
      canvas.classList.remove("is-live");
    });
    raf(() => canvas.classList.add("is-live"));
    start();
  }

  /* ---------- Pipeline: a quiet dot grid that ripples under the pointer (Canvas 2D) ---------- */
  function initMatrix() {
    const pipe = document.querySelector(".pipeline");
    if (!pipe) return;
    const canvas = document.createElement("canvas");
    canvas.className = "matrix";
    canvas.setAttribute("aria-hidden", "true");
    pipe.prepend(canvas);
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const gap = 16;
    let w = 0;
    let h = 0;
    const rings = [];
    let time = 0;
    let lastSpawn = 0;

    const size = () => {
      w = pipe.clientWidth;
      h = pipe.clientHeight;
      const dpr = Math.min(devicePixelRatio || 1, 2);
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const paint = () => {
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = "#8BEFE3";
      const band = ((time * 0.12) % 1.5) - 0.25;
      for (let y = gap / 2; y < h; y += gap) {
        for (let x = gap / 2; x < w; x += gap) {
          let glow = 0.07 + 0.03 * Math.sin(x * 0.04 + time * 0.7) * Math.sin(y * 0.06 - time * 0.5);
          glow += 0.12 * Math.exp(-Math.pow((x / w - band) * 7, 2));
          for (const ring of rings) {
            const r = Math.hypot(x - ring.x, y - ring.y);
            const age = time - ring.t;
            glow += ring.power * Math.exp(-Math.pow((r - age * 240) / 18, 2)) * Math.exp(-age * 1.8);
          }
          const radius = 0.55 + Math.min(1.1, glow * 2.2);
          ctx.globalAlpha = Math.min(0.7, glow);
          ctx.fillRect(x - radius, y - radius, radius * 2, radius * 2);
        }
      }
      ctx.globalAlpha = 1;
    };

    size();
    if (!motion) {
      paint();
      new ResizeObserver(() => {
        size();
        paint();
      }).observe(pipe);
      return;
    }

    const spawn = (event, power) => {
      const box = pipe.getBoundingClientRect();
      rings.push({ x: event.clientX - box.left, y: event.clientY - box.top, t: time, power });
      if (rings.length > 8) rings.shift();
    };
    pipe.addEventListener(
      "pointermove",
      (event) => {
        if (time - lastSpawn > 0.16) {
          lastSpawn = time;
          spawn(event, 0.22);
        }
      },
      { passive: true }
    );
    pipe.addEventListener("pointerdown", (event) => spawn(event, 0.6));

    let visible = false;
    let running = false;
    let last = 0;
    const loop = (now) => {
      if (!visible || document.hidden) {
        running = false;
        return;
      }
      const dt = last ? Math.min(0.05, (now - last) / 1000) : 0.016;
      last = now;
      time += dt;
      while (rings.length && time - rings[0].t > 2.5) rings.shift();
      paint();
      raf(loop);
    };
    const start = () => {
      if (running || !visible || document.hidden) return;
      running = true;
      last = 0;
      raf(loop);
    };
    new IntersectionObserver((entries) => {
      visible = entries[0].isIntersecting;
      start();
    }).observe(pipe);
    document.addEventListener("visibilitychange", start);
    new ResizeObserver(size).observe(pipe);
  }

  const boot = () => {
    initNav();
    splitTitle();
    initReveal();
    initPointer();
    initParallax();
    initRiver();
    initMatrix();
  };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
