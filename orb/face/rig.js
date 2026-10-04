.pragma library

// The expression rig, ported from faces/blender/expr.py. Every face style
// reads the same controls. A pose is a set of targets; each control chases
// its target with a damped spring, so a new mood mid-transition is always
// smooth. Blinks, glances, breathing and the talking mouth ride on top.

var DEFAULTS = {
    look_x: 0, look_y: 0,
    lid_L: 0.06, lid_R: 0.06, squint_L: 0, squint_R: 0, slant_L: 0, slant_R: 0,
    brow_L: 0, brow_R: 0, worry_L: 0, worry_R: 0, eye_size: 1,
    mouth_open: 0, smile: 0.1, mouth_wide: 0, mouth_skew: 0,
    head_roll: 0, head_yaw: 0, head_pitch: 0, glow: 1,
    col_r: 0, col_g: 0, col_b: 0
};

function both(o, name, v) { o[name + "_L"] = v; o[name + "_R"] = v; return o; }

function pose(color, extra, pairs) {
    var p = extra || {};
    for (var k in (pairs || {})) both(p, k, pairs[k]);
    p.color = color;
    return p;
}

var POSES = {
    idle: pose("#b07cf5"),
    listening: pose("#6ee7ff", { eye_size: 1.08, head_roll: 5, head_pitch: -3, smile: 0.15 }, { lid: -0.04, brow: 0.3 }),
    thinking: pose("#d07cff", { look_x: 0.55, look_y: 0.5, brow_L: 0.45, brow_R: -0.15, worry_R: -0.3, mouth_skew: 0.5,
                                smile: -0.05, mouth_wide: -0.2, head_roll: -6, head_yaw: 8 }, { lid: 0.18, squint: 0.25 }),
    speaking: pose("#c084fc", { smile: 0.3 }, { brow: 0.15, lid: 0.04 }),
    neutral: pose("#c084fc", { smile: 0.2 }, { brow: 0.1 }),
    happy: pose("#f0abfc", { smile: 1.0, mouth_open: 0.3, mouth_wide: 0.35, head_roll: 6, head_pitch: -4, glow: 1.25 },
                { squint: 0.85, lid: 0, brow: 0.35 }),
    confused: pose("#a78bfa", { brow_L: 0.75, brow_R: -0.35, worry_R: -0.4, lid_R: 0.3, lid_L: -0.05, slant_R: 0.3,
                                mouth_skew: -0.7, smile: -0.25, mouth_wide: -0.2, head_roll: -12, head_yaw: -6,
                                look_x: -0.2, look_y: 0.15 }),
    sad: pose("#7c8cff", { look_y: -0.45, smile: -0.7, head_pitch: 8, head_roll: 4, glow: 0.7 },
              { lid: 0.35, slant: -0.6, worry: 0.8, brow: -0.1 }),
    surprised: pose("#c7f9ff", { eye_size: 1.3, mouth_open: 0.7, mouth_wide: -0.55, smile: 0, head_pitch: -6, glow: 1.35 },
                    { lid: -0.25, brow: 1.0 }),
    sleepy: pose("#6d3fd9", { look_y: -0.3, smile: 0, head_pitch: 10, head_roll: -5, glow: 0.35 }, { lid: 0.93, brow: -0.25 }),
    error: pose("#ff5ea0", { smile: -0.4, mouth_skew: 0.3, head_roll: -6 }, { lid: 0.2, worry: 0.5 })
};

var SPRINGS = [
    [["look_"], 30, 1.0],
    [["lid_", "squint_", "slant_", "eye_size"], 20, 0.9],
    [["brow_", "worry_"], 15, 0.85],
    [["mouth_open"], 38, 1.0],
    [["smile", "mouth_"], 16, 0.9],
    [["head_"], 7, 0.62],
    [["glow", "col_"], 6, 1.0]
];

function springFor(name) {
    for (var i = 0; i < SPRINGS.length; i++)
        for (var j = 0; j < SPRINGS[i][0].length; j++)
            if (name.indexOf(SPRINGS[i][0][j]) === 0) return [SPRINGS[i][1], SPRINGS[i][2]];
    return [12, 1.0];
}

function hexRgb(h) {
    return [parseInt(h.substr(1, 2), 16) / 255, parseInt(h.substr(3, 2), 16) / 255, parseInt(h.substr(5, 2), 16) / 255];
}

function target(name) {
    var t = {}, p = POSES[name] || POSES.idle;
    for (var k in DEFAULTS) t[k] = DEFAULTS[k];
    for (var q in p) if (q !== "color") t[q] = p[q];
    var c = hexRgb(p.color);
    t.col_r = c[0]; t.col_g = c[1]; t.col_b = c[2];
    return t;
}

// Which pose to show. Listening always wins; a mood (from what he said or
// from Claude's tags) beats the generic thinking/speaking looks.
function poseFor(mode, mood) {
    if (mode === "listening") return "listening";
    if (mode === "error") return "error";
    if (mood && mood !== "neutral") return mood;
    if (mode === "thinking") return "thinking";
    if (mode === "speaking") return "speaking";
    if (mood === "neutral") return "neutral";
    return "idle";
}

function Rig() {
    this.pos = target("idle");
    this.vel = {};
    for (var k in DEFAULTS) this.vel[k] = 0;
    this.t = 0;
    this.nextBlink = 1.2;
    this.blinkAt = -10;
    this.nextSacc = 0.5;
    this.sacc = [0, 0];
    this.lastPose = "idle";
    this.c = {};
}

// dt in seconds, level 0..1 voice loudness. Returns the control values.
Rig.prototype.step = function (dt, mode, mood, level) {
    dt = Math.min(dt, 0.05);
    this.t += dt;
    var t = this.t;
    var name = poseFor(mode, mood);
    var tgt = target(name);

    if (name !== this.lastPose) {
        // People blink when their attention shifts.
        if (Math.random() < 0.6 && t - this.blinkAt > 0.4) this.blinkAt = t + 0.04;
        this.lastPose = name;
    }
    if (t > this.nextSacc) {
        this.sacc = [(Math.random() - 0.5) * 0.28, (Math.random() - 0.5) * 0.16];
        this.nextSacc = t + 0.6 + Math.random() * 1.3;
    }
    if (name !== "thinking" && name !== "sleepy") {
        tgt.look_x += this.sacc[0];
        tgt.look_y += this.sacc[1];
    }
    if (name === "thinking") {
        tgt.look_x += 0.12 * Math.cos(t * 1.3);
        tgt.look_y += 0.10 * Math.sin(t * 1.7);
    }
    var talk = mode === "speaking" ? Math.min(1, level * 1.4) : 0;
    if (talk > 0 || mode === "speaking") {
        tgt.mouth_open = Math.max(tgt.mouth_open * 0.4, 0.85 * talk);
        tgt.mouth_wide += 0.25 * Math.sin(t * 9) * talk;
        tgt.brow_L += 0.25 * talk;
        tgt.brow_R += 0.25 * talk;
        tgt.head_pitch -= 2.5 * talk;
    }

    var sub = 4, h = dt / sub;
    for (var k in DEFAULTS) {
        var sp = springFor(k), w = sp[0], z = sp[1];
        var x = this.pos[k], v = this.vel[k];
        for (var i = 0; i < sub; i++) {
            v += (w * w * (tgt[k] - x) - 2 * z * w * v) * h;
            x += v * h;
        }
        this.pos[k] = x;
        this.vel[k] = v;
    }

    var c = this.c;
    for (var q in this.pos) c[q] = this.pos[q];
    var breath = name === "sleepy" ? 6.5 : 4.5;
    c.head_pitch += (name === "sleepy" ? 1.6 : 0.8) * Math.sin(2 * Math.PI * t / breath);
    c.glow *= 1 + 0.04 * Math.sin(2 * Math.PI * t / breath);

    if (t > this.nextBlink) {
        this.blinkAt = t;
        this.nextBlink = t + 2.2 + Math.random() * 2.6;
    }
    var bt = t - this.blinkAt, b = 0;
    if (bt >= 0 && bt <= 0.17)
        b = bt < 0.06 ? Math.sin(bt / 0.06 * Math.PI / 2) : Math.pow(Math.cos((bt - 0.06) / 0.11 * Math.PI / 2), 2);
    if (name !== "sleepy") {
        c.lid_L += (1 - c.lid_L) * b;
        c.lid_R += (1 - c.lid_R) * b;
    }
    c.talk = talk;
    c.time = t;
    c.pose = name;
    return c;
};

// Shape key order of the face-mesh models (holo, android), as exported.
var FACE_KEYS = ["jaw_open"];
["L", "R"].forEach(function (s) {
    ["smile", "frown", "wide", "pucker", "brow_up", "brow_down", "brow_worry", "blink", "eye_wide", "squint"]
        .forEach(function (k) { FACE_KEYS.push(k + "_" + s); });
});

// Controls -> face-mesh shape key weights (faces/blender/facemesh.py weights()).
function faceWeights(c) {
    var w = {}, pos = function (v) { return Math.max(0, v); };
    ["L", "R"].forEach(function (s) {
        w["blink_" + s] = Math.min(1, pos(c["lid_" + s]));
        w["eye_wide_" + s] = Math.min(1, pos(-c["lid_" + s]) * 3 + pos(c.eye_size - 1) * 1.5);
        w["squint_" + s] = Math.min(1, c["squint_" + s] * 0.9);
        w["brow_up_" + s] = pos(c["brow_" + s]);
        w["brow_down_" + s] = Math.min(1, pos(-c["brow_" + s]) + 0.8 * pos(-c["worry_" + s]) + 0.5 * pos(c["slant_" + s]));
        w["brow_worry_" + s] = Math.min(1, pos(c["worry_" + s]) + 0.4 * pos(-c["slant_" + s]));
        var sm = c.smile + (s === "L" ? 0.6 : -0.6) * c.mouth_skew;
        w["smile_" + s] = pos(sm);
        w["frown_" + s] = pos(-sm);
        w["wide_" + s] = pos(c.mouth_wide);
        w["pucker_" + s] = pos(-c.mouth_wide);
    });
    w.jaw_open = Math.min(1, c.mouth_open);
    return w;
}
