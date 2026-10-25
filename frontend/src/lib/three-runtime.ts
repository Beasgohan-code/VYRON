/**
 * Named re-exports of the three.js pieces the visualiser uses.
 *
 * Importing the namespace (`import * as THREE from "three"`) defeats
 * tree-shaking, so the components dynamically import *this* module instead —
 * Rollup can then drop the ~60% of three.js we never touch.
 */
export {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  Clock,
  Color,
  Group,
  IcosahedronGeometry,
  Mesh,
  MeshBasicMaterial,
  OrthographicCamera,
  PerspectiveCamera,
  PlaneGeometry,
  Points,
  PointsMaterial,
  Scene,
  ShaderMaterial,
  Vector2,
  WebGLRenderer,
} from "three";
