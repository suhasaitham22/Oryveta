import React, { useEffect, useRef } from "react";
import * as THREE from "three";
import { productArtifacts } from "./productArtifacts";

// Original UI artwork is drawn once, not on animation frames. The same document
// content is available in ProductScene's semantic, non-WebGL presentation.
function artifactTexture(artifact, index) {
  const canvas = document.createElement("canvas");
  canvas.width = 1200;
  canvas.height = 840;
  const ctx = canvas.getContext("2d");
  const dark = index === 1;
  const ink = dark ? "#f4f6ef" : "#232521";
  const muted = dark ? "#b7c1ac" : "#626959";
  const border = dark ? "#414a3b" : "#e0e4d9";
  function text(value, x, y, size = 24, color = ink, weight = 400) {
    ctx.fillStyle = color;
    ctx.font = `${weight} ${size}px ${index === 1 ? "monospace" : "Arial, sans-serif"}`;
    ctx.fillText(value, x, y);
  }
  function rule(y) {
    ctx.fillStyle = border;
    ctx.fillRect(0, y, 1200, 2);
  }
  ctx.fillStyle = dark ? "#242c24" : "#fdfefb";
  ctx.fillRect(0, 0, 1200, 840);
  ctx.fillStyle = dark ? "#30392d" : "#f0f2e9";
  ctx.fillRect(0, 0, 1200, 84);
  ["#87917d", "#aab29f", "#f5d84c"].forEach((color, i) => {
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(43 + i * 27, 42, 7, 0, Math.PI * 2);
    ctx.fill();
  });
  text(artifact.file, 162, 50, 23, muted);
  rule(84);
  text(artifact.label.toUpperCase(), 62, 155, 22, muted, 600);
  text(artifact.heading, 62, 226, index === 1 ? 47 : 56, ink, 600);
  ctx.fillStyle = dark ? "#f5d84c" : "#f4e59b";
  ctx.beginPath();
  ctx.roundRect(62, 263, 365, 47, 10);
  ctx.fill();
  text(artifact.tag, 80, 295, 22, "#393a27", 600);
  artifact.rows.forEach(([label, value], row) => {
    const y = 368 + row * 119;
    ctx.fillStyle = dark ? "#30392d" : "#f3f5ee";
    ctx.beginPath();
    ctx.roundRect(62, y - 23, 1076, 100, 10);
    ctx.fill();
    ctx.fillStyle = row === 0 ? "#e7cc48" : border;
    ctx.fillRect(62, y - 9, 4, 69);
    text(label, 90, y + 7, 23, muted, 600);
    text(value, 90, y + 47, 25, ink);
  });
  rule(751);
  text(artifact.footer, 62, 801, 22, muted);
  text("ORYVETA", 985, 801, 20, muted, 600);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function roundedPanel(width, height, radius) {
  const shape = new THREE.Shape();
  const left = -width / 2;
  const bottom = -height / 2;
  shape.moveTo(left + radius, bottom);
  shape.lineTo(left + width - radius, bottom);
  shape.quadraticCurveTo(left + width, bottom, left + width, bottom + radius);
  shape.lineTo(left + width, bottom + height - radius);
  shape.quadraticCurveTo(left + width, bottom + height, left + width - radius, bottom + height);
  shape.lineTo(left + radius, bottom + height);
  shape.quadraticCurveTo(left, bottom + height, left, bottom + height - radius);
  shape.lineTo(left, bottom + radius);
  shape.quadraticCurveTo(left, bottom, left + radius, bottom);
  return shape;
}

export default function ThreeScene({ selected, onUnavailable }) {
  const host = useRef(null);
  const controller = useRef(null);
  useEffect(() => {
    const element = host.current;
    let renderer;
    try {
      renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, powerPreference: "low-power" });
    } catch {
      onUnavailable();
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFShadowMap;
    renderer.domElement.setAttribute("aria-hidden", "true");
    element.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 40);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x8e9885, 2.5));
    const light = new THREE.DirectionalLight(0xffffff, 3.5);
    light.position.set(-3, 7, 6);
    light.castShadow = true;
    light.shadow.mapSize.set(1024, 1024);
    Object.assign(light.shadow.camera, { left: -6, right: 6, top: 6, bottom: -6 });
    light.shadow.normalBias = 0.025;
    light.shadow.bias = -0.0002;
    light.shadow.radius = 4;
    scene.add(light);
    const rim = new THREE.DirectionalLight(0xffe6a0, 2);
    rim.position.set(5, 2, -3);
    scene.add(rim);
    const root = new THREE.Group();
    scene.add(root);
    const geometries = new Set();
    const materials = new Set();
    const textures = new Set();
    const width = 5.4;
    const height = 3.78;
    const shape = roundedPanel(width, height, 0.12);
    const shellGeometry = new THREE.ExtrudeGeometry(shape, {
      depth: 0.055, bevelEnabled: true, bevelSegments: 3,
      steps: 1, bevelSize: 0.025, bevelThickness: 0.025, curveSegments: 8,
    });
    geometries.add(shellGeometry);
    const faceGeometry = new THREE.ShapeGeometry(shape, 8);
    const positions = faceGeometry.attributes.position;
    const uv = faceGeometry.attributes.uv;
    for (let i = 0; i < positions.count; i++)
      uv.setXY(i, positions.getX(i) / width + 0.5, positions.getY(i) / height + 0.5);
    geometries.add(faceGeometry);
    const panels = productArtifacts.map((artifact, index) => {
      const panel = new THREE.Group();
      const shellMaterial = new THREE.MeshStandardMaterial({
        color: index === 1 ? 0x424c40 : 0xbcc3b3, roughness: 0.32, metalness: 0.55,
      });
      materials.add(shellMaterial);
      const shell = new THREE.Mesh(shellGeometry, shellMaterial);
      shell.castShadow = true;
      shell.receiveShadow = true;
      panel.add(shell);
      const texture = artifactTexture(artifact, index);
      texture.anisotropy = Math.min(4, renderer.capabilities.getMaxAnisotropy());
      textures.add(texture);
      // Unlit printed faces keep the actual text crisp; beveled metal edges carry the light.
      const faceMaterial = new THREE.MeshBasicMaterial({ map: texture });
      materials.add(faceMaterial);
      const face = new THREE.Mesh(faceGeometry, faceMaterial);
      face.position.z = 0.083;
      panel.add(face);
      panel.position.set((index - 1) * 2.5, -0.5, -2);
      root.add(panel);
      return panel;
    });
    const floorGeometry = new THREE.PlaneGeometry(30, 30);
    geometries.add(floorGeometry);
    const floorMaterial = new THREE.ShadowMaterial({ opacity: 0.13 });
    materials.add(floorMaterial);
    const floor = new THREE.Mesh(floorGeometry, floorMaterial);
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -2.8;
    floor.receiveShadow = true;
    scene.add(floor);
    let frame = 0;
    let visible = false;
    let stopped = false;
    let previousTime = 0;
    let chapter = 0;
    let pointerX = 0;
    let pointerY = 0;
    let scroll = 0;
    let ease = 0;
    let moving = false;
    function settle(object, property, target) {
      object[property] += (target - object[property]) * ease;
      if (Math.abs(target - object[property]) > 0.0004) moving = true;
    }
    function invalidate() {
      if (!frame && visible && !document.hidden && !stopped)
        frame = requestAnimationFrame(render);
    }
    function render(time) {
      frame = 0;
      const dt = Math.min((time - previousTime) / 1000 || 0.016, 0.05);
      previousTime = time;
      ease = 1 - Math.exp(-dt * 5.5);
      moving = false;
      settle(root.rotation, "y", -0.12 + pointerX * 0.07 + scroll * 0.14);
      settle(root.rotation, "x", -0.04 + pointerY * 0.035);
      for (let index = 0; index < panels.length; index++) {
        const panel = panels[index];
        const slot = (index - chapter + panels.length) % panels.length;
        const front = slot === 0;
        const side = slot === 1 ? -1 : 1;
        settle(panel.position, "x", front ? 0 : side * 0.72);
        settle(panel.position, "y", front ? -0.26 : 0.45 + slot * 0.12);
        settle(panel.position, "z", front ? 0.9 : -0.55 - slot * 0.16);
        settle(panel.rotation, "y", front ? 0.04 : side * 0.13);
        settle(panel.rotation, "z", front ? -0.025 : side * 0.09);
      }
      renderer.render(scene, camera);
      if (moving) invalidate();
    }
    function resize() {
      const { width: viewWidth, height: viewHeight } = element.getBoundingClientRect();
      if (!viewWidth || !viewHeight) return;
      renderer.setSize(viewWidth, viewHeight);
      camera.aspect = viewWidth / viewHeight;
      camera.position.set(0, 0.55, camera.aspect < 1.15 ? 11.8 : 9.8);
      camera.lookAt(0, 0.1, 0);
      camera.updateProjectionMatrix();
      invalidate();
    }
    function onPointer(event) {
      if (event.pointerType !== "mouse") return;
      const rect = element.getBoundingClientRect();
      pointerX = ((event.clientX - rect.left) / rect.width) * 2 - 1;
      pointerY = ((event.clientY - rect.top) / rect.height) * 2 - 1;
      invalidate();
    }
    function onLeave() {
      pointerX = 0;
      pointerY = 0;
      invalidate();
    }
    function onScroll() {
      if (!visible) return;
      scroll = Math.max(-0.25, Math.min(1, -element.getBoundingClientRect().top / window.innerHeight));
      invalidate();
    }
    function onVisibility() {
      if (document.hidden) {
        cancelAnimationFrame(frame);
        frame = 0;
      } else invalidate();
    }
    function lost(event) {
      event.preventDefault();
      onUnavailable();
    }
    const observer = new IntersectionObserver(([entry]) => {
      visible = entry.isIntersecting && entry.intersectionRatio >= 0.25;
      if (visible) {
        onScroll();
        invalidate();
      } else {
        cancelAnimationFrame(frame);
        frame = 0;
      }
    }, { threshold: [0, 0.25] });
    observer.observe(element);
    const sizing = new ResizeObserver(resize);
    sizing.observe(element);
    element.addEventListener("pointermove", onPointer);
    element.addEventListener("pointerleave", onLeave);
    renderer.domElement.addEventListener("webglcontextlost", lost);
    window.addEventListener("scroll", onScroll, { passive: true });
    document.addEventListener("visibilitychange", onVisibility);
    controller.current = (value) => {
      chapter = value;
      invalidate();
    };
    resize();
    return () => {
      stopped = true;
      controller.current = null;
      cancelAnimationFrame(frame);
      observer.disconnect();
      sizing.disconnect();
      element.removeEventListener("pointermove", onPointer);
      element.removeEventListener("pointerleave", onLeave);
      renderer.domElement.removeEventListener("webglcontextlost", lost);
      window.removeEventListener("scroll", onScroll);
      document.removeEventListener("visibilitychange", onVisibility);
      geometries.forEach((value) => value.dispose());
      materials.forEach((value) => value.dispose());
      textures.forEach((value) => value.dispose());
      light.shadow.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
    };
  }, [onUnavailable]);
  // Only the external renderer is synchronized; artifact selection belongs to React.
  useEffect(() => {
    controller.current?.(selected);
  }, [selected]);
  return <div className="three-scene" ref={host} aria-hidden="true" />;
}
