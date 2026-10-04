VARYING vec3 vWorld;
VARYING vec3 vNormal;

void MAIN()
{
    vWorld = (MODEL_MATRIX * vec4(VERTEX, 1.0)).xyz;
    vNormal = normalize(NORMAL_MATRIX * NORMAL);
    POSITION = MODELVIEWPROJECTION_MATRIX * vec4(VERTEX, 1.0);
}
