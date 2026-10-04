.pragma library

// Eye and mouth shapes for the glyph face, ported from
// faces/blender/shapes2d.py so the live face matches the renders. Each
// shape is a band: a top and bottom edge over the same x columns, so
// blending shapes is blending numbers and the morph never tears.

var N = 41;

function columns() {
    var xs = [];
    for (var i = 0; i < N; i++) xs.push(-Math.cos(Math.PI * i / (N - 1)));
    return xs;
}

function rrTop(x) {
    var h = 1.15, r = 0.55, ax = Math.abs(x);
    if (ax <= 1 - r) return h;
    return h - r + Math.sqrt(Math.max(0, r * r - Math.pow(ax - (1 - r), 2)));
}

function band(xs, top, bot) {
    var t = [];
    for (var i = 0; i < xs.length; i++) t.push(Math.max(top[i], bot[i] + 0.02));
    return { xs: xs, top: t, bot: bot };
}

function map(xs, f) {
    var out = [];
    for (var i = 0; i < xs.length; i++) out.push(f(xs[i], i));
    return out;
}

function eyeShapes() {
    var xs = columns();
    var bt = map(xs, rrTop), bb = map(bt, function (t) { return -t; });
    var s = { Basis: { xs: xs, top: bt, bot: bb } };
    var c = map(xs, function (x) { return -0.32 - 0.12 * (1 - x * x); });
    var th = map(xs, function (x) { return 0.035 + 0.06 * Math.sqrt(1 - x * x); });
    s.close = { xs: xs, top: map(xs, function (x, i) { return c[i] + th[i]; }), bot: map(xs, function (x, i) { return c[i] - th[i]; }) };
    s.lid_flat = band(xs, map(bt, function (t) { return Math.min(t, 0.12); }), bb);
    var at = map(xs, function (x) { return -0.25 + 1.35 * Math.pow(Math.sqrt(1 - x * x), 0.9); });
    s.happy = { xs: xs, top: at, bot: map(xs, function (x, i) { return at[i] - (0.1 + 0.5 * Math.sqrt(1 - x * x)); }) };
    s.sad = band(xs, map(xs, function (x, i) { return Math.min(bt[i], 0.5 - 0.8 * x); }), bb);
    s.angry = band(xs, map(xs, function (x, i) { return Math.min(bt[i], 0.5 + 0.8 * x); }), bb);
    var rt = map(xs, function (x) { return 1.2 * Math.sqrt(Math.max(0, 1 - x * x)); });
    s.round = { xs: xs, top: rt, bot: map(rt, function (t) { return -t; }) };
    return s;
}

function mouthShapes() {
    var xs = columns();
    var th = map(xs, function (x) { return 0.035 + 0.09 * Math.pow(Math.sqrt(1 - x * x), 0.5); });
    var bt = th, bb = map(th, function (t) { return -t; });
    var s = { Basis: { xs: xs, top: bt, bot: bb } };
    function shifted(f) {
        return { xs: xs, top: map(xs, function (x, i) { return bt[i] + f(x); }), bot: map(xs, function (x, i) { return bb[i] + f(x); }) };
    }
    s.smile = shifted(function (x) { return 0.42 * x * x - 0.12; });
    s.frown = shifted(function (x) { return -0.34 * x * x + 0.1; });
    s.skew = shifted(function (x) { return 0.16 * x + 0.22 * Math.pow(Math.max(0, x), 2) - 0.04; });
    s.open = { xs: xs, top: map(xs, function (x, i) { return bt[i] + 0.1 * Math.sqrt(1 - x * x); }),
               bot: map(xs, function (x, i) { return bb[i] - 0.75 * Math.sqrt(1 - x * x); }) };
    s.narrow = { xs: map(xs, function (x) { return 0.5 * x; }), top: bt, bot: bb };
    s.wide = { xs: map(xs, function (x) { return 1.25 * x; }), top: bt, bot: bb };
    return s;
}

// Basis plus weighted deltas, like Blender shape keys.
function blend(shapes, w) {
    var b = shapes.Basis;
    var xs = b.xs.slice(), top = b.top.slice(), bot = b.bot.slice();
    for (var k in w) {
        var v = w[k], s = shapes[k];
        if (!s || !v) continue;
        for (var i = 0; i < N; i++) {
            xs[i] += v * (s.xs[i] - b.xs[i]);
            top[i] += v * (s.top[i] - b.top[i]);
            bot[i] += v * (s.bot[i] - b.bot[i]);
        }
    }
    return { xs: xs, top: top, bot: bot };
}

function clamp01(v) { return Math.min(1, Math.max(0, v)); }

function eyeWeights(c, s) {
    var li = clamp01(c["lid_" + s]);
    return {
        lid_flat: li < 0.5 ? li * 2 : 2 - li * 2,
        close: clamp01(li * 2 - 1),
        happy: clamp01(c["squint_" + s]),
        sad: clamp01(-c["slant_" + s] + 0.6 * c["worry_" + s]),
        angry: clamp01(c["slant_" + s] - 0.6 * c["worry_" + s]),
        round: clamp01((c.eye_size - 1) * 2.5)
    };
}

function mouthWeights(c) {
    return {
        smile: clamp01(c.smile), frown: clamp01(-c.smile), open: clamp01(c.mouth_open),
        narrow: clamp01(-c.mouth_wide), wide: clamp01(c.mouth_wide),
        skew: Math.max(-1, Math.min(1, c.mouth_skew))
    };
}

// Band -> closed outline in face units, transformed by f(x, y) -> point.
function outline(b, f) {
    var pts = [];
    for (var i = 0; i < N; i++) pts.push(f(b.xs[i], b.top[i]));
    for (var j = N - 1; j >= 0; j--) pts.push(f(b.xs[j], b.bot[j]));
    pts.push(pts[0]);
    return pts;
}
