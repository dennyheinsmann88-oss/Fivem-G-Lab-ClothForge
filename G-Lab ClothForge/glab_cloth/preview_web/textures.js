// Dekodiert GTA-Texturformate (Mip 0) nach RGBA8. BC7 wird direkt an die Grafikkarte gegeben.

function rgb565(c) {
  return [((c >> 11) & 31) * 255 / 31 | 0, ((c >> 5) & 63) * 255 / 63 | 0, (c & 31) * 255 / 31 | 0];
}

function colorBlock(src, o, out, w, x0, y0, allowAlpha) {
  const c0 = src[o] | (src[o + 1] << 8), c1 = src[o + 2] | (src[o + 3] << 8);
  const a = rgb565(c0), b = rgb565(c1);
  const pal = [a, b];
  if (c0 > c1 || !allowAlpha) {
    pal.push(a.map((v, i) => (2 * v + b[i]) / 3 | 0), a.map((v, i) => (v + 2 * b[i]) / 3 | 0));
  } else {
    pal.push(a.map((v, i) => (v + b[i]) / 2 | 0), [0, 0, 0]);
  }
  const bits = src[o + 4] | (src[o + 5] << 8) | (src[o + 6] << 16) | (src[o + 7] << 24);
  for (let i = 0; i < 16; i++) {
    const x = x0 + (i & 3), y = y0 + (i >> 2);
    if (x >= w || y * w + x >= out.length / 4) continue;
    const k = (bits >>> (2 * i)) & 3, p = (y * w + x) * 4;
    out[p] = pal[k][0]; out[p + 1] = pal[k][1]; out[p + 2] = pal[k][2];
    out[p + 3] = (allowAlpha && c0 <= c1 && k === 3) ? 0 : 255;
  }
}

function dxt5Alpha(src, o, out, w, x0, y0) {
  const a0 = src[o], a1 = src[o + 1];
  const pal = [a0, a1];
  if (a0 > a1) for (let k = 1; k < 7; k++) pal.push(((7 - k) * a0 + k * a1) / 7 | 0);
  else { for (let k = 1; k < 5; k++) pal.push(((5 - k) * a0 + k * a1) / 5 | 0); pal.push(0, 255); }
  let lo = src[o + 2] | (src[o + 3] << 8) | (src[o + 4] << 16), hi = src[o + 5] | (src[o + 6] << 8) | (src[o + 7] << 16);
  for (let i = 0; i < 16; i++) {
    const idx = i < 8 ? (lo >> (3 * i)) & 7 : (hi >> (3 * (i - 8))) & 7;
    const x = x0 + (i & 3), y = y0 + (i >> 2);
    if (x < w) out[(y * w + x) * 4 + 3] = pal[idx];
  }
}

function dxt3Alpha(src, o, out, w, x0, y0) {
  for (let i = 0; i < 16; i++) {
    const v = (src[o + (i >> 1)] >> ((i & 1) * 4)) & 15;
    const x = x0 + (i & 3), y = y0 + (i >> 2);
    if (x < w) out[(y * w + x) * 4 + 3] = v * 17;
  }
}

function blocks(src, w, h, size, fn) {
  const out = new Uint8Array(w * h * 4);
  const bw = Math.max(1, (w + 3) >> 2), bh = Math.max(1, (h + 3) >> 2);
  for (let by = 0; by < bh; by++) {
    for (let bx = 0; bx < bw; bx++) {
      const o = (by * bw + bx) * size;
      if (o + size > src.length) return out;
      fn(src, o, out, bx * 4, by * 4);
    }
  }
  return out;
}

// Liefert { rgba: Uint8Array, alpha: bool } oder null (Format nicht dekodierbar, z.B. BC7)
export function decodeTexture(format, w, h, src) {
  switch (format) {
    case "DXT1":
      return { rgba: blocks(src, w, h, 8, (s, o, out, x, y) => colorBlock(s, o, out, w, x, y, true)), alpha: false };
    case "DXT3":
      return { rgba: blocks(src, w, h, 16, (s, o, out, x, y) => { colorBlock(s, o + 8, out, w, x, y, false); dxt3Alpha(s, o, out, w, x, y); }), alpha: true };
    case "DXT5":
      return { rgba: blocks(src, w, h, 16, (s, o, out, x, y) => { colorBlock(s, o + 8, out, w, x, y, false); dxt5Alpha(s, o, out, w, x, y); }), alpha: true };
    case "A8R8G8B8":
    case "X8R8G8B8": {
      const out = new Uint8Array(w * h * 4);
      for (let i = 0; i < w * h; i++) {
        out[i * 4] = src[i * 4 + 2]; out[i * 4 + 1] = src[i * 4 + 1]; out[i * 4 + 2] = src[i * 4];
        out[i * 4 + 3] = format === "X8R8G8B8" ? 255 : src[i * 4 + 3];
      }
      return { rgba: out, alpha: format === "A8R8G8B8" };
    }
    case "A8B8G8R8":
      return { rgba: new Uint8Array(src.subarray(0, w * h * 4)), alpha: true };
    case "L8": {
      const out = new Uint8Array(w * h * 4);
      for (let i = 0; i < w * h; i++) { out[i * 4] = out[i * 4 + 1] = out[i * 4 + 2] = src[i]; out[i * 4 + 3] = 255; }
      return { rgba: out, alpha: false };
    }
    case "A1R5G5B5": {
      const out = new Uint8Array(w * h * 4);
      for (let i = 0; i < w * h; i++) {
        const v = src[i * 2] | (src[i * 2 + 1] << 8);
        out[i * 4] = ((v >> 10) & 31) * 255 / 31; out[i * 4 + 1] = ((v >> 5) & 31) * 255 / 31;
        out[i * 4 + 2] = (v & 31) * 255 / 31; out[i * 4 + 3] = v & 0x8000 ? 255 : 0;
      }
      return { rgba: out, alpha: true };
    }
    default:
      return null;
  }
}
