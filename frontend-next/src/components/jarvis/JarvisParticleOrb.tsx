"use client";

import React, { useEffect, useRef, useState } from "react";

interface Point3D {
  x: number;
  y: number;
  z: number;
  baseX: number;
  baseY: number;
  baseZ: number;
  u: number;
  v: number;
  size: number;
  colorHue: number;
}

export function JarvisParticleOrb() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [mousePos, setMousePos] = useState({ x: 0, y: 0 });
  const [isHovered, setIsHovered] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animationFrameId: number;
    let width = (canvas.width = canvas.parentElement?.clientWidth || 600);
    let height = (canvas.height = canvas.parentElement?.clientHeight || 600);

    const handleResize = () => {
      if (!canvas || !canvas.parentElement) return;
      width = canvas.width = canvas.parentElement.clientWidth;
      height = canvas.height = canvas.parentElement.clientHeight;
    };

    window.addEventListener("resize", handleResize);

    // Create 3D points on a Fibonacci sphere
    const numPoints = 1400;
    const radius = Math.min(width, height) * 0.32;
    const points: Point3D[] = [];

    const phi = (1 + Math.sqrt(5)) / 2; // Golden ratio

    for (let i = 0; i < numPoints; i++) {
      // Fibonacci sphere distribution
      const theta = (2 * Math.PI * i) / phi;
      const y = 1 - (i / (numPoints - 1)) * 2; // y goes from 1 to -1
      const radiusAtY = Math.sqrt(1 - y * y);
      const x = Math.cos(theta) * radiusAtY;
      const z = Math.sin(theta) * radiusAtY;

      const px = x * radius;
      const py = y * radius;
      const pz = z * radius;

      points.push({
        x: px,
        y: py,
        z: pz,
        baseX: px,
        baseY: py,
        baseZ: pz,
        u: theta,
        v: Math.asin(y),
        size: Math.random() * 1.8 + 1.2,
        colorHue: Math.random() * 80 + 280, // Magenta to Pink/Violet
      });
    }

    let rotX = 0.2;
    let rotY = 0.3;
    let time = 0;

    const render = () => {
      ctx.clearRect(0, 0, width, height);

      time += 0.025;

      // Base rotation + mouse movement influence
      const targetRotY = mousePos.x * 0.4;
      const targetRotX = mousePos.y * 0.4;

      rotY += (targetRotY + 0.008 - rotY) * 0.05;
      rotX += (targetRotX + 0.003 - rotX) * 0.05;

      const cosX = Math.cos(rotX);
      const sinX = Math.sin(rotX);
      const cosY = Math.cos(rotY);
      const sinY = Math.sin(rotY);

      const fov = 500;
      const centerX = width / 2;
      const centerY = height / 2;

      // Ambient radial glow behind orb
      const bgGlow = ctx.createRadialGradient(centerX, centerY, 50, centerX, centerY, radius * 1.4);
      bgGlow.addColorStop(0, "rgba(236, 72, 153, 0.22)");
      bgGlow.addColorStop(0.4, "rgba(168, 85, 247, 0.15)");
      bgGlow.addColorStop(0.8, "rgba(99, 102, 241, 0.05)");
      bgGlow.addColorStop(1, "rgba(7, 5, 20, 0)");
      ctx.fillStyle = bgGlow;
      ctx.fillRect(0, 0, width, height);

      const projectedPoints: { px: number; py: number; pz: number; size: number; alpha: number; color: string }[] = [];

      const waveAmp = isHovered ? 24 : 16;

      for (let i = 0; i < points.length; i++) {
        const pt = points[i];

        // Pulsating wave math
        const wave = Math.sin(pt.u * 6 + time * 2.5) * Math.cos(pt.v * 5 + time * 2) * waveAmp;
        const currentRadius = radius + wave;

        // Re-calculate 3D vector with wave
        const normLen = Math.sqrt(pt.baseX * pt.baseX + pt.baseY * pt.baseY + pt.baseZ * pt.baseZ) || 1;
        const wx = (pt.baseX / normLen) * currentRadius;
        const wy = (pt.baseY / normLen) * currentRadius;
        const wz = (pt.baseZ / normLen) * currentRadius;

        // Rotate Y
        const x1 = wx * cosY - wz * sinY;
        const z1 = wz * cosY + wx * sinY;

        // Rotate X
        const y2 = wy * cosX - z1 * sinX;
        const z2 = z1 * cosX + wy * sinX;

        // Perspective scale
        const scale = fov / (fov + z2 + 300);
        const projX = centerX + x1 * scale;
        const projY = centerY + y2 * scale;

        // Alpha calculation based on depth
        const alpha = Math.max(0.1, Math.min(1, (z2 + radius) / (2 * radius) + 0.2));

        // Color interpolation (Magenta -> Pink -> Cyan -> Violet)
        const hueShift = (Math.sin(time + pt.u) * 40 + pt.colorHue) % 360;
        const color = `hsla(${hueShift}, 95%, 68%, ${alpha})`;

        projectedPoints.push({
          px: projX,
          py: projY,
          pz: z2,
          size: pt.size * scale,
          alpha,
          color,
        });
      }

      // Sort by depth (back to front rendering)
      projectedPoints.sort((a, b) => a.pz - b.pz);

      // Draw particle points
      for (let i = 0; i < projectedPoints.length; i++) {
        const p = projectedPoints[i];
        ctx.beginPath();
        ctx.arc(p.px, p.py, Math.max(0.5, p.size), 0, Math.PI * 2);
        ctx.fillStyle = p.color;
        ctx.fill();

        // Extra bloom glow for outer front points
        if (p.pz > radius * 0.4 && i % 3 === 0) {
          ctx.beginPath();
          ctx.arc(p.px, p.py, p.size * 2.2, 0, Math.PI * 2);
          ctx.fillStyle = p.color.replace(/[\d\.]+\)$/, `${p.alpha * 0.3})`);
          ctx.fill();
        }
      }

      animationFrameId = requestAnimationFrame(render);
    };

    render();

    return () => {
      cancelAnimationFrame(animationFrameId);
      window.removeEventListener("resize", handleResize);
    };
  }, [mousePos, isHovered]);

  const handleMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const x = ((e.clientX - rect.left) / rect.width - 0.5) * 2;
    const y = ((e.clientY - rect.top) / rect.height - 0.5) * 2;
    setMousePos({ x, y });
  };

  return (
    <div
      className="relative flex items-center justify-center w-full max-w-[650px] aspect-square mx-auto cursor-pointer"
      onMouseMove={handleMouseMove}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => {
        setIsHovered(false);
        setMousePos({ x: 0, y: 0 });
      }}
    >
      {/* Background radial aura */}
      <div className="absolute inset-0 bg-gradient-to-r from-pink-500/20 via-purple-600/25 to-cyan-500/20 blur-3xl rounded-full animate-pulse opacity-70 pointer-events-none" />

      {/* HTML5 Canvas 3D Particle Orb */}
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full z-10 pointer-events-none" />

      {/* Center Floating TRX Balance Badge (matching the reference design!) */}
      <div className="relative z-20 transition-all duration-300 transform hover:scale-105">
        <div className="px-7 py-4 rounded-2xl jarvis-glass-card border border-pink-500/40 shadow-2xl backdrop-blur-xl bg-purple-950/40 text-center flex flex-col items-center">
          <div className="flex items-center gap-2 mb-1">
            <span className="w-2.5 h-2.5 rounded-full bg-pink-500 animate-ping" />
            <span className="text-2xl font-bold font-orbitron tracking-wider text-white jarvis-pink-glow">
              664.999 <span className="text-pink-400 font-syne">TRX</span>
            </span>
          </div>
          <span className="text-xs uppercase tracking-widest text-purple-200/80 font-mono">
            Total TRX Balance
          </span>
        </div>
      </div>
    </div>
  );
}
