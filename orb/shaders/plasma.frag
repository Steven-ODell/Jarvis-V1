#version 440
// The orb: a plasma sphere faked in 2D. Each pixel inside the disc gets a
// sphere normal, the normal is rotated over time and fed through
// domain-warped noise, and that noise picks between three colors. A fresnel
// rim, a soft core, thin bright filaments and an outer halo do the glowing.
// level (0..1, voice loudness) swells the radius and brightness.

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float time;
    float level;
    float appear;   // 0 hidden .. 1 fully grown
    float swirl;    // noise flow speed
    float think;    // 0..1 orbiting arcs while waiting on the brain
    float ripple;   // 0..1 listening rings
    vec4 colA;      // deep body color
    vec4 colB;      // bright body / rim color
    vec4 colC;      // filament highlight color
};

float hash(vec3 p) {
    p = fract(p * 0.3183099 + 0.1);
    p *= 17.0;
    return fract(p.x * p.y * p.z * (p.x + p.y + p.z));
}

float noise(vec3 x) {
    vec3 i = floor(x);
    vec3 f = fract(x);
    f = f * f * (3.0 - 2.0 * f);
    return mix(mix(mix(hash(i + vec3(0, 0, 0)), hash(i + vec3(1, 0, 0)), f.x),
                   mix(hash(i + vec3(0, 1, 0)), hash(i + vec3(1, 1, 0)), f.x), f.y),
               mix(mix(hash(i + vec3(0, 0, 1)), hash(i + vec3(1, 0, 1)), f.x),
                   mix(hash(i + vec3(0, 1, 1)), hash(i + vec3(1, 1, 1)), f.x), f.y), f.z);
}

float fbm(vec3 p) {
    float a = 0.5;
    float s = 0.0;
    for (int i = 0; i < 5; i++) {
        s += a * noise(p);
        p = p * 2.03 + vec3(1.7, 9.2, 3.1);
        a *= 0.5;
    }
    return s;
}

mat3 rotY(float a) { float c = cos(a), s = sin(a); return mat3(c, 0, -s, 0, 1, 0, s, 0, c); }
mat3 rotX(float a) { float c = cos(a), s = sin(a); return mat3(1, 0, 0, 0, c, s, 0, -s, c); }

void main() {
    vec2 uv = qt_TexCoord0 * 2.0 - 1.0;
    uv.y = -uv.y;
    float d = length(uv);
    float t = time;

    float breathe = 0.018 * sin(t * 1.7) + 0.01 * sin(t * 2.9 + 1.0);
    float R = (0.44 + 0.16 * level + breathe) * appear;
    R = max(R, 0.0001);

    vec3 col = vec3(0.0);
    float alpha = 0.0;

    // ---- halo, outside and under the sphere
    float outside = max(d - R, 0.0);
    // Fades to exactly zero before the quad edge so no square ever shows,
    // and is mostly additive: glow should brighten what's behind, not
    // paint a dark disc over it.
    float quadFade = smoothstep(1.0, 0.72, d);
    float halo = exp(-outside * (7.0 - 2.5 * level)) * smoothstep(0.0, 0.25, appear) * quadFade;
    vec3 haloCol = mix(colA.rgb, colB.rgb, 0.6) * (0.6 + 0.9 * level);
    col += haloCol * halo;
    alpha += halo * 0.22;

    // ---- listening ripples: rings leaving the surface, louder = stronger
    for (int k = 0; k < 2; k++) {
        float ph = fract(t * 0.55 + float(k) * 0.5);
        float rr = R + ph * 0.42;
        float ring = exp(-abs(d - rr) * 70.0) * (1.0 - ph) * ripple * (0.35 + 1.2 * level) * quadFade;
        col += colB.rgb * ring;
        alpha += ring * 0.3;
    }

    // ---- thinking arcs: two comets orbiting just outside the surface
    float ang = atan(uv.y, uv.x);
    float orbitR = R * 1.16 + 0.02;
    float band = exp(-abs(d - orbitR) * 90.0);
    float comet = pow(max(0.0, sin(ang - t * 3.2)), 18.0) + pow(max(0.0, sin(ang + 3.14159 - t * 3.2)), 18.0);
    float arcs = band * comet * think;
    col += mix(colC.rgb, vec3(1.0), 0.3) * arcs * 1.6;
    alpha += arcs * 0.5;

    // ---- the sphere
    if (d < R + 0.01) {
        vec2 p = uv / R;
        float r2 = min(dot(p, p), 1.0);
        float z = sqrt(1.0 - r2);
        vec3 n = vec3(p, z);
        vec3 q = rotY(t * 0.25 * swirl) * rotX(0.4 + t * 0.11 * swirl) * n;

        float w1 = fbm(q * 1.9 + vec3(0.0, 0.0, t * 0.12 * swirl));
        float w2 = fbm(q * 2.6 + w1 * 2.4 + vec3(t * 0.21 * swirl, 0.0, 0.0));

        float b = smoothstep(0.30, 0.78, w2);
        vec3 body = mix(colA.rgb, colB.rgb, b);

        // Thin bright veins where the warped field crosses its midline.
        float vein = pow(1.0 - abs(w2 * 2.0 - 1.0), 10.0);
        body += colC.rgb * vein * (0.55 + 1.3 * level);

        // Emissive core, fresnel rim, one soft specular glint.
        float core = exp(-r2 * 2.6) * (0.35 + 0.9 * level);
        float rim = pow(1.0 - z, 2.6);
        float spec = pow(max(dot(n, normalize(vec3(-0.45, 0.55, 0.75))), 0.0), 36.0);
        body = body * (0.55 + 0.45 * z) + mix(colB.rgb, colC.rgb, 0.5) * core
             + colB.rgb * rim * 1.1 + vec3(spec * 0.55);

        float edge = smoothstep(R, R - 0.012, d);
        col = mix(col, body, edge);
        alpha = mix(alpha, 0.97, edge);
    }

    alpha = clamp(alpha, 0.0, 1.0) * qt_Opacity;
    // Premultiplied output; col is already "light", so clamp instead of
    // multiplying it down twice.
    fragColor = vec4(min(col, vec3(1.4)) * qt_Opacity, alpha);
}
