// Additive hologram: scanlines drifting down, a bright band sweeping the
// face, and (for the skin) only the edges lit. Same as holo_material() in
// faces/blender/holo.py. World units are cm; the face mesh unit is 12 cm.
VARYING vec3 vWorld;
VARYING vec3 vNormal;

void MAIN()
{
    float y = vWorld.y / 12.0;
    float scan = 0.78 + 0.22 * sin(y * 9.0 - time * 5.0);
    float dy = y - band;
    float k = (scan + 1.4 * exp(-0.6 * dy * dy)) * glow * base;
    if (rim > 0.5) {
        vec3 v = normalize(CAMERA_POSITION - vWorld);
        float f = 1.0 - abs(dot(normalize(vNormal), v));
        k *= pow(f, 2.0) + 0.05;
    }
    vec3 c = tint.rgb * k;
    FRAGCOLOR = vec4(c, clamp(max(c.r, max(c.g, c.b)), 0.0, 1.0));
}
