// A constellation body's surface (studio-upgrade-2 I1 "Body materials v2"). The standard
// material keeps its lambert / GGX and `NoToneMapping` (CanvasHost) so the instance colour — the
// status token — is what the lit face shows; `onBeforeCompile` adds two things a sphere needs
// to read as a sphere and not a disc:
//
//   • a FRESNEL RIM in the body's own status colour: on the light theme the rim DARKENS toward
//     `ink-2` (an object's edge turns away from the light), on dark it LIFTS additively toward
//     `accent-300` (an object catches the room's light). Either way the rim is a shade of the
//     status colour's own meaning — it never introduces a second hue per body.
//   • a soft SPECULAR DOT from the key light — one highlight, off-centre, small.
//
// Both are zero at the body's centre (`fresnelWeight(1) === 0`, `specularWeight(1) < 2 / 255`),
// so the centre pixel is still the standard material's own answer: the pin "body centre within
// ±2" is a pin on these two pure functions, which the GLSL mirrors term for term.
import { Color, MeshStandardMaterial } from 'three'
import type { IUniform, WebGLProgramParametersWithUniforms } from 'three'
import type { ThemeAttr } from '../../../theme/tokens'

/** Rim strength: how much of the rim colour the silhouette reaches. */
export const RIM_STRENGTH = 0.55
/** Fresnel exponent: 3 keeps the rim thin — a band, not a halo. */
export const RIM_POWER = 3
/** Specular exponent and weight: a soft dot, never a chrome glint. */
export const SPEC_POWER = 48
export const SPEC_WEIGHT = 0.18
/** The key light's direction in VIEW space (matches `lights.tsx` key at (4, 6, 5) for the
 * default orbit — a fixed key so the dot does not swim as the camera orbits). */
export const KEY_DIR: readonly [number, number, number] = [0.456, 0.684, 0.57]

/** The rim colour per theme: light darkens toward `ink-2`, dark lifts toward `accent-300`. */
export const RIM_TOKEN = { light: 'ink-2', dark: 'accent-300' } as const

export interface BodyUniforms {
  uRim: IUniform<number>
  /** 0 = darken toward `uRimColor` (light), 1 = add `uRimColor` (dark). */
  uRimMode: IUniform<number>
  uRimColor: IUniform<Color>
  uSpec: IUniform<number>
}

/** `(1 − cosθ)^RIM_POWER · RIM_STRENGTH`, θ between the normal and the view direction. 0 at the
 * centre of the disc (normal toward the camera), rising only at the silhouette. */
export function fresnelWeight(cosTheta: number): number {
  return Math.pow(1 - Math.max(0, Math.min(1, cosTheta)), RIM_POWER) * RIM_STRENGTH
}

/** `max(n·h, 0)^SPEC_POWER · SPEC_WEIGHT` for the half vector of the fixed key and the view. */
export function specularWeight(cosNormalHalf: number): number {
  return Math.pow(Math.max(0, Math.min(1, cosNormalHalf)), SPEC_POWER) * SPEC_WEIGHT
}

/** `n · h` at the body's centre: normal (0, 0, 1), half vector of `KEY_DIR` and the view. */
export function centreHalfCos(): number {
  const [kx, ky, kz] = KEY_DIR
  const hx = kx, hy = ky, hz = kz + 1
  return hz / Math.hypot(hx, hy, hz)
}

const RIM_DECL = /* glsl */ `
uniform float uRim;
uniform float uRimMode;
uniform vec3 uRimColor;
uniform float uSpec;
`

/** Appended after three's own output so tone mapping / colour space (none, sRGB) see it too. */
const RIM_BODY = /* glsl */ `
{
  vec3 bodyN = normalize(vNormal);
  vec3 bodyV = normalize(vViewPosition);
  float bodyCos = max(dot(bodyN, bodyV), 0.0);
  // Fresnel rim: (1 - cos)^RIM_POWER * uRim — zero at the centre of the disc.
  float rim = pow(1.0 - bodyCos, ${RIM_POWER.toFixed(1)}) * uRim;
  if (uRimMode > 0.5) {
    gl_FragColor.rgb += uRimColor * rim;
  } else {
    gl_FragColor.rgb = mix(gl_FragColor.rgb, uRimColor, rim);
  }
  // One soft specular dot from the fixed key light.
  vec3 bodyH = normalize(vec3(${KEY_DIR.map((v) => v.toFixed(3)).join(', ')}) + bodyV);
  gl_FragColor.rgb += pow(max(dot(bodyN, bodyH), 0.0), ${SPEC_POWER.toFixed(1)}) * uSpec;
}
`

export class BodyMaterial extends MeshStandardMaterial {
  readonly rim: BodyUniforms = {
    uRim: { value: RIM_STRENGTH },
    uRimMode: { value: 0 },
    uRimColor: { value: new Color('#3d3630') },
    uSpec: { value: SPEC_WEIGHT },
  }

  constructor(rimColor: Color, theme: ThemeAttr) {
    // Matte: a specular highlight on a sphere says "toy"; the one soft dot above is the exception.
    super({ roughness: 0.72, metalness: 0 })
    this.setRim(rimColor, theme)
    this.onBeforeCompile = (shader: WebGLProgramParametersWithUniforms) => this.patch(shader)
    // The uniforms are read by the program, so a material with a different rim must not share one.
    this.customProgramCacheKey = () => 'togo-body-v2'
  }

  /** Exposed so a node test can run the patch against a stand-in shader without a GPU. */
  patch(shader: Pick<WebGLProgramParametersWithUniforms, 'uniforms' | 'fragmentShader'>): void {
    shader.uniforms.uRim = this.rim.uRim
    shader.uniforms.uRimMode = this.rim.uRimMode
    shader.uniforms.uRimColor = this.rim.uRimColor
    shader.uniforms.uSpec = this.rim.uSpec
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', `#include <common>\n${RIM_DECL}`)
      .replace('#include <dithering_fragment>', `#include <dithering_fragment>\n${RIM_BODY}`)
  }

  /** Theme flip: the rim colour and whether it darkens (light) or lifts (dark). */
  setRim(rimColor: Color, theme: ThemeAttr): void {
    this.rim.uRimColor.value.copy(rimColor)
    this.rim.uRimMode.value = theme === 'dark' ? 1 : 0
  }
}
