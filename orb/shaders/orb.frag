#version 440
// The orb as a hologram rather than a sphere. A tick-marked dial ring faces
// the viewer, two gyroscope rings tumble through it in 3D, and at the center
// a point of light sits inside two waveform loops that ride the voice level.
// Nothing is filled in; it's all lines of light over a faint dark lens.
//
// States read through motion as much as color:
//   idle       slow drift, dim, waveforms nearly round
//   listening  cyan accent, waveforms follow the mic, pings leave the core
//   thinking   rings spin up and wobble, comets chase around them, the
//              waveforms turn into a dashed spinner
//   speaking   waveforms follow the TTS level, rings swell with it
//
// Rotation phases (dial, gyro, wave) are integrated in Orb.qml, so a speed
// change never makes the rings jump.

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;
    float level;    // 0..1 voice loudness (mic or TTS), eased
    float appear;   // 0 hidden .. 1 fully grown (overshoots a little)
    float dial;     // dial rotation, radians
    float gyro;     // gyroscope precession, radians
    float wave;     // waveform phase, radians
    float listen;   // 0..1 state weights, eased
    float think;
    float speak;
    vec4 colA;      // ring base
    vec4 colB;      // bright lines
    vec4 colC;      // accent: waveform, comets, ticks, core
};

const float TAU = 6.2831853;

// A glowing line: crisp core plus a soft tail. dist and w in uv units.
float glow(float dist, float w) {
    return exp(-dist * dist / (w * w)) + 0.3 * exp(-abs(dist) / (w * 5.0));
}

vec3 normalFrom(float tilt, float az) {
    return vec3(sin(tilt) * cos(az), sin(tilt) * sin(az), cos(tilt));
}

// A circle of radius r in the plane with normal n, seen orthographically,
// is an ellipse. Returns the screen distance to it. th is the angle around
// the ring (for dashes and comets); depth is -1 on the far side, 1 near.
float ring(vec2 p, vec3 n, float r, out float th, out float depth) {
    float l = length(n.xy);
    vec2 U = l > 1e-4 ? vec2(-n.y, n.x) / l : vec2(1.0, 0.0);
    vec2 V = vec2(-U.y, U.x);
    float b = max(abs(n.z), 0.02) * r;
    vec2 e = vec2(dot(p, U) / r, dot(p, V) / b);
    float el = max(length(e), 1e-4);
    vec2 g = vec2(e.x / r, e.y / b) / el;
    float s = e.y * (n.z < 0.0 ? -1.0 : 1.0) / el;
    th = atan(s, e.x / el);
    depth = s * min(1.0, l * 2.0);   // face-on rings have no near side
    return (el - 1.0) / max(length(g), 1e-4);
}

void main() {
    vec2 uv = qt_TexCoord0 * 2.0 - 1.0;
    uv.y = -uv.y;
    vec2 p = uv / max(appear, 0.05);   // everything grows out of the center
    float d = length(p);
    float ang = atan(p.y, p.x);
    float t = time;
    float lv = level;
    float act = max(listen, speak);     // how much the voice drives things
    float busy = max(act, think);

    vec3 col = vec3(0.0);
    float alpha = 0.0;

    // ---- faint dark lens so the lines read over a bright window
    alpha += smoothstep(0.97, 0.55, d) * 0.5;

    // ---- dial: nearly face-on, 72 ticks (every 6th long), slow turn
    {
        float th, dep;
        vec3 n = normalFrom(0.3 + 0.05 * sin(t * 0.4), 1.2 + gyro * 0.15);
        float r = 0.80 + 0.03 * lv * speak;
        float dist = ring(p, n, r, th, dep);
        float a = th - dial;

        float line = glow(dist, 0.005) * (0.45 + 0.25 * busy);
        float idx = floor(a / TAU * 72.0 + 0.5);
        float f = abs(a / TAU * 72.0 - idx);
        float major = 1.0 - step(0.5, mod(idx, 6.0));
        float len = mix(0.028, 0.06, major);
        float tick = smoothstep(0.14, 0.05, f)
                   * smoothstep(-len - 0.006, -len, dist) * smoothstep(0.004, -0.004, dist);
        tick *= 0.35 + 0.35 * major + 1.1 * lv * act;

        // Thinking: a bright scan arc sweeps the dial.
        float scan = pow(0.5 + 0.5 * cos(th - dial * 3.0), 30.0) * think;
        float scanL = glow(dist, 0.011) * scan;

        col += colA.rgb * 1.3 * line + colC.rgb * tick + mix(colC.rgb, vec3(1.0), 0.3) * scanL * 1.4;
        alpha += line * 0.5 + tick * 0.6 + scanL * 0.5;
    }

    // ---- two gyroscope rings tumbling through the dial
    for (int i = 0; i < 2; i++) {
        float fi = float(i);
        float th, dep;
        float tilt = mix(1.12, 1.32, fi) + think * 0.22 * sin(gyro * 0.7 + fi * 2.0);
        float az = i == 0 ? gyro : -gyro * 0.8 + 2.1;
        vec3 n = normalFrom(tilt, az);
        float r = mix(0.64, 0.55, fi) + 0.03 * lv * act;
        float dist = ring(p, n, r, th, dep);

        float near = mix(0.28, 1.0, smoothstep(-0.5, 0.5, dep));
        // Ring 0 is dashed, ring 1 solid; the dashes crawl along the ring.
        float f = fract((th + gyro * 1.7) / TAU * 16.0);
        float dash = i == 0 ? smoothstep(0.0, 0.05, f) * smoothstep(0.72, 0.66, f) : 1.0;
        float line = glow(dist, 0.005) * near * dash * (0.55 + 0.5 * lv * act);

        float comet = pow(0.5 + 0.5 * cos(th - gyro * 2.4 - fi * 3.1416), 36.0)
                    * (0.3 + 1.4 * think) * near;
        float cometL = glow(dist, 0.012) * comet;

        col += mix(colA.rgb, colB.rgb, 0.65) * line * 1.2 + colC.rgb * cometL * 1.5;
        alpha += line * 0.6 + cometL * 0.5;
    }

    // ---- waveform loops around the core (integer harmonics, so they close)
    {
        float amp = (0.014 + 0.17 * lv * act) * (1.0 - think);
        float r0 = 0.30 - 0.05 * think;
        for (int k = 0; k < 2; k++) {
            float fk = float(k);
            float ph = wave * (k == 0 ? 1.0 : -1.3) + fk * 1.7;
            float e1 = 0.6 + 0.4 * sin(t * 2.3 + fk);
            float e2 = 0.6 + 0.4 * sin(t * 3.1 + 2.0 + fk);
            float w  = 0.5 * e1 * sin(3.0 * ang + ph)
                     + 0.3 * e2 * sin(5.0 * ang - ph * 1.6 + 1.0)
                     + 0.2 * sin(9.0 * ang + ph * 2.3 + 2.0);
            float dw = 1.5 * e1 * cos(3.0 * ang + ph)
                     + 1.5 * e2 * cos(5.0 * ang - ph * 1.6 + 1.0)
                     + 1.8 * cos(9.0 * ang + ph * 2.3 + 2.0);
            float s = k == 0 ? 1.0 : 0.75;
            float rw = r0 + amp * s * w + fk * 0.012 * think;
            float slope = amp * s * dw / max(d, 0.05);
            float dist = (d - rw) / sqrt(1.0 + slope * slope);

            // Thinking: the loops become a dashed spinner.
            float f = fract((ang + wave * (k == 0 ? 0.7 : -0.45)) / TAU * 12.0);
            float dash = mix(1.0, smoothstep(0.0, 0.06, f) * smoothstep(0.55, 0.49, f), think);
            float L = glow(dist, 0.006) * dash * (0.55 + 0.9 * lv * act + 0.3 * think);
            col += (k == 0 ? colC.rgb : colB.rgb) * L;
            alpha += L * 0.6;
        }
    }

    // ---- listening pings: rings leaving the core
    for (int k = 0; k < 2; k++) {
        float ph = fract(t * 0.6 + float(k) * 0.5);
        float ping = glow(d - (0.1 + ph * 0.72), 0.004) * (1.0 - ph) * (1.0 - ph)
                   * listen * (0.35 + 1.2 * lv);
        col += colC.rgb * ping;
        alpha += ping * 0.35;
    }

    // ---- the core: a point of light with a soft bloom
    {
        float cr = 0.03 + 0.045 * lv * act + 0.008 * sin(t * 1.8) + 0.012 * think;
        float core = exp(-d * d / (cr * cr));
        float bloom = exp(-d * 7.5) * (0.22 + 0.5 * lv * act + 0.2 * think);
        col += mix(colC.rgb, vec3(1.0), 0.55) * core + colB.rgb * bloom;
        alpha += core * 0.9 + bloom * 0.2;
    }

    // Dimmer at rest; never reaches the quad edge; fades in as it grows.
    float fade = smoothstep(0.0, 0.35, appear) * smoothstep(1.0, 0.92, length(uv));
    col *= (0.72 + 0.28 * busy) * fade;
    alpha = clamp(alpha * fade, 0.0, 1.0) * qt_Opacity;
    // Premultiplied output; col is light, so clamp rather than scale down.
    fragColor = vec4(min(col, vec3(1.4)) * qt_Opacity, alpha);
}
