import React, { useEffect, useRef } from "react";
import * as THREE from "three";

// All geometry is original. No model files, image textures or animation framework.
export default function ThreeScene({ selected, onUnavailable }) {
  const host = useRef(null);
  const controller = useRef(null);
  useEffect(() => {
    const element = host.current;
    let renderer;
    try {
      renderer = new THREE.WebGLRenderer({
        alpha: true,
        antialias: true,
        powerPreference: "low-power",
      });
    } catch {
      onUnavailable();
      return;
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 0.85;
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    renderer.setClearColor(0xf0f1e9, 0);
    renderer.domElement.setAttribute("aria-hidden", "true");
    element.appendChild(renderer.domElement);
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 60);
    camera.position.set(0, 5.2, 10.8);
    camera.lookAt(0, 0.65, 0);
    scene.add(new THREE.HemisphereLight(0xffffff, 0x8e977f, 3));
    const light = new THREE.DirectionalLight(0xfffcdf, 5);
    light.position.set(-4, 8, 6);
    light.castShadow = true;
    light.shadow.mapSize.set(1024, 1024);
    light.shadow.camera.left = -8;
    light.shadow.camera.right = 8;
    light.shadow.camera.top = 8;
    light.shadow.camera.bottom = -8;
    light.shadow.normalBias = 0.035;
    scene.add(light);
    const root = new THREE.Group();
    scene.add(root);
    const geometries = new Set();
    const materials = new Set();
    const material = (color) => {
      const value = new THREE.MeshStandardMaterial({
        color,
        roughness: 0.52,
        metalness: 0.08,
      });
      materials.add(value);
      return value;
    };
    const white = material(0xfafbf6),
      yellow = material(0xf5d84c),
      dark = material(0x30392e);
    const line = material(0xaeb7a3),
      muted = material(0xe0e5d7);
    function box(parent, w, h, d, x, y, z, surface) {
      const geometry = new THREE.BoxGeometry(w, h, d);
      geometries.add(geometry);
      const mesh = new THREE.Mesh(geometry, surface);
      mesh.position.set(x, y, z);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      parent.add(mesh);
      return mesh;
    }
    // Low plinth and offset rails make depth, occlusion and cast shadows legible.
    box(root, 8.4, 0.26, 4.2, 0, -0.75, 0, white);
    box(root, 8.1, 0.12, 3.9, 0.12, -0.97, -0.12, muted);
    for (let i = 0; i < 3; i++)
      box(root, 0.06, 0.06, 3.3, (i - 1) * 2.5, -0.58, 0, line);
    const panels = [];
    const surfaces = [yellow, dark, white];
    const positions = [
      [0, 0.6, 0.55],
      [-2.7, 0.2, -0.45],
      [2.7, 0.25, -0.6],
    ];
    for (let i = 0; i < 3; i++) {
      const panel = new THREE.Group();
      root.add(panel);
      panel.position.set(...positions[i]);
      panel.rotation.set(-0.15, i === 1 ? 0.18 : i === 2 ? -0.2 : 0, 0);
      box(panel, 2.28, 2.8, 0.18, 0, 0.45, 0, surfaces[i]);
      box(panel, 2.08, 0.07, 0.1, 0, 1.62, 0.14, i === 1 ? yellow : dark);
      const ink = i === 1 ? muted : dark;
      box(panel, 0.3, 0.3, 0.12, -0.77, 1.23, 0.15, i === 0 ? white : yellow);
      box(panel, 0.95, 0.12, 0.09, 0.1, 1.28, 0.15, ink);
      box(panel, 1.75, 0.07, 0.08, 0, 0.84, 0.15, ink);
      if (i === 2) {
        for (let j = 0; j < 3; j++) {
          box(
            panel,
            0.45,
            0.55,
            0.12,
            (j - 1) * 0.6,
            0.24,
            0.16,
            j === 1 ? yellow : muted,
          );
          box(panel, 0.34, 0.05, 0.08, (j - 1) * 0.6, -0.16, 0.16, line);
        }
      } else {
        for (let j = 0; j < 4; j++)
          box(
            panel,
            1.65 - (j % 3) * 0.28,
            0.08,
            0.08,
            -(j % 3) * 0.14,
            0.46 - j * 0.28,
            0.16,
            i === 1 && j === 2 ? yellow : ink,
          );
      }
      box(panel, 1.75, 0.04, 0.08, 0, -0.61, 0.16, line);
      box(panel, 0.58, 0.12, 0.1, -0.56, -0.77, 0.16, i === 1 ? yellow : line);
      panels.push(panel);
    }
    const floor = box(scene, 200, 0.08, 200, 0, -1.2, 0, material(0xf0f1e9));
    floor.castShadow = false;
    let frame = 0,
      visible = false,
      stopped = false,
      previousTime = 0;
    let chapter = 0,
      pointerX = 0,
      pointerY = 0,
      scroll = 0,
      entrance = 0;
    root.rotation.y = -0.9;
    function invalidate() {
      if (!frame && visible && !document.hidden && !stopped)
        frame = requestAnimationFrame(render);
    }
    function render(time) {
      frame = 0;
      const dt = Math.min((time - previousTime) / 1000 || 0.016, 0.05);
      previousTime = time;
      const ease = 1 - Math.exp(-dt * 5);
      entrance += (1 - entrance) * ease;
      const targetY =
        (chapter === 1 ? 0.43 : chapter === 2 ? -0.43 : -0.16) +
        pointerX * 0.12 +
        scroll * 0.55;
      root.rotation.y += (targetY - root.rotation.y) * ease;
      root.rotation.x += (pointerY * 0.045 - root.rotation.x) * ease;
      let moving =
        Math.abs(targetY - root.rotation.y) > 0.0005 ||
        Math.abs(pointerY * 0.045 - root.rotation.x) > 0.0005 ||
        entrance < 0.999;
      for (let i = 0; i < panels.length; i++) {
        const target =
          positions[i][1] +
          (i === chapter ? 0.36 : 0) +
          scroll * (i + 1) * 0.22;
        panels[i].position.y += (target - panels[i].position.y) * ease;
        panels[i].position.x = positions[i][0] * (1 + (1 - entrance) * 0.5);
        panels[i].rotation.z = (1 - entrance) * (i - 1) * 0.45;
        moving ||= Math.abs(target - panels[i].position.y) > 0.0005;
      }
      renderer.render(scene, camera);
      if (moving) invalidate();
    }
    function resize() {
      const { width, height } = element.getBoundingClientRect();
      if (!width || !height) return;
      renderer.setSize(width, height);
      camera.aspect = width / height;
      camera.position.z = camera.aspect < 1.2 ? 17 : 10.8;
      camera.lookAt(0, 0.65, 0);
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
      scroll = Math.max(
        -0.35,
        Math.min(1, -element.getBoundingClientRect().top / window.innerHeight),
      );
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
    const observer = new IntersectionObserver(
      ([entry]) => {
        visible = entry.isIntersecting && entry.intersectionRatio >= 0.35;
        if (visible) {
          onScroll();
          invalidate();
        } else {
          cancelAnimationFrame(frame);
          frame = 0;
        }
      },
      { threshold: [0, 0.35] },
    );
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
      renderer.dispose();
      renderer.forceContextLoss();
      renderer.domElement.remove();
    };
  }, [onUnavailable]);
  // Synchronize a React control with the external renderer; no mirrored UI state.
  useEffect(() => {
    controller.current?.(selected);
  }, [selected]);
  return <div className="three-scene" ref={host} aria-hidden="true" />;
}
