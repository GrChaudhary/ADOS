"use client";

import React, { useEffect, useRef, useState } from "react";

interface Node3D {
  x: number;
  y: number;
  z: number;
  vx: number;
  vy: number;
  vz: number;
  baseX: number;
  baseY: number;
  baseZ: number;
  size: number;
  colorHue: number;
}

export function NovusParticleOrb() {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [mousePos, setMousePos] = useState({ x: 0, y: 0, clientX: 0, clientY: 0 });
  const [isHovered, setIsHovered] = useState(false);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let animationFrameId: number;
    let width = (canvas.width = containerRef.current?.clientWidth || 600);
    let height = (canvas.height = containerRef.current?.clientHeight || 600);

    const handleResize = () => {
      if (!canvas || !containerRef.current) return;
      width = canvas.width = containerRef.current.clientWidth;
      height = canvas.height = containerRef.current.clientHeight;
    };

    window.addEventListener("resize", handleResize);

    // Create 3D nodes for the network mesh (Active Theory style)
    const numNodes = 140;
    const nodes: Node3D[] = [];
    const sphereRadius = Math.min(width, height) * 0.32;

    for (let i = 0; i < numNodes; i++) {
      // Uniform distribution on a sphere
      const u = Math.random();
      const v = Math.random();
      const theta = u * 2.0 * Math.PI;
      const phi = Math.acos(2.0 * v - 1.0);
      
      const x = Math.sin(phi) * Math.cos(theta) * sphereRadius;
      const y = Math.sin(phi) * Math.sin(theta) * sphereRadius;
      const z = Math.cos(phi) * sphereRadius;

      nodes.push({
        x,
        y,
        z,
        baseX: x,
        baseY: y,
        baseZ: z,
        vx: (Math.random() - 0.5) * 0.4,
        vy: (Math.random() - 0.5) * 0.4,
        vz: (Math.random() - 0.5) * 0.4,
        size: Math.random() * 2 + 1,
        colorHue: Math.random() * 80 + 260, // Violet/Cyan to Pink gradient
      });
    }

    let rotX = 0.2;
    let rotY = 0.3;
    let time = 0;

    const render = () => {
      ctx.clearRect(0, 0, width, height);
      time += 0.005;

      // Draw subtle background grid lines (Active Theory signature)
      ctx.strokeStyle = "rgba(168, 85, 247, 0.06)";
      ctx.lineWidth = 1;
      const gridSpacing = 40;
      
      // Vertical grid lines
      for (let x = 0; x < width; x += gridSpacing) {
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
        ctx.stroke();
      }
      
      // Horizontal grid lines
      for (let y = 0; y < height; y += gridSpacing) {
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
      }

      // Dynamic rotation based on mouse or auto-rotation
      const targetRotY = isHovered ? mousePos.x * 0.5 : Math.sin(time * 0.2) * 0.3;
      const targetRotX = isHovered ? mousePos.y * 0.5 : Math.cos(time * 0.2) * 0.2;

      rotY += (targetRotY - rotY) * 0.05;
      rotX += (targetRotX - rotX) * 0.05;

      const cosX = Math.cos(rotX);
      const sinX = Math.sin(rotX);
      const cosY = Math.cos(rotY);
      const sinY = Math.sin(rotY);

      const fov = 400;
      const centerX = width / 2;
      const centerY = height / 2;

      // Transform nodes in 3D & apply mouse gravity warping
      const projected: { x: number; y: number; z: number; size: number; color: string; rawNode: Node3D }[] = [];

      nodes.forEach((node) => {
        // Slowly float nodes around base coordinates
        node.x = node.baseX + Math.sin(time * 2 + node.colorHue) * 10;
        node.y = node.baseY + Math.cos(time * 2.5 + node.colorHue) * 10;
        node.z = node.baseZ + Math.sin(time * 1.5 + node.colorHue) * 10;

        // 3D Rotation
        // Rotate around Y axis
        let x1 = node.x * cosY - node.z * sinY;
        const z1 = node.z * cosY + node.x * sinY;
        // Rotate around X axis
        let y2 = node.y * cosX - z1 * sinX;
        const z2 = z1 * cosX + node.y * sinX;

        // Mouse gravity pull (push points slightly away or pull them)
        if (isHovered) {
          const mouse3DX = mousePos.x * sphereRadius;
          const mouse3DY = mousePos.y * sphereRadius;
          const dx = x1 - mouse3DX;
          const dy = y2 - mouse3DY;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < 120) {
            const force = (120 - dist) * 0.12;
            x1 += (dx / dist) * force;
            y2 += (dy / dist) * force;
          }
        }

        // Project onto 2D viewport
        const scale = fov / (fov + z2 + 250);
        const projX = centerX + x1 * scale;
        const projY = centerY + y2 * scale;

        const alpha = Math.max(0.1, Math.min(0.9, (z2 + sphereRadius) / (2 * sphereRadius) + 0.1));
        const color = `hsla(${node.colorHue}, 90%, 65%, ${alpha})`;

        projected.push({
          x: projX,
          y: projY,
          z: z2,
          size: node.size * scale,
          color,
          rawNode: node,
        });
      });

      // Sort by depth (painters algorithm)
      projected.sort((a, b) => a.z - b.z);

      // Draw interactive network web lines (distance-based connectivity)
      ctx.lineWidth = 0.8;
      for (let i = 0; i < projected.length; i++) {
        const p1 = projected[i];
        let connectionsCount = 0;
        
        for (let j = i + 1; j < projected.length; j++) {
          const p2 = projected[j];
          const dx = p1.x - p2.x;
          const dy = p1.y - p2.y;
          const dist = Math.sqrt(dx * dx + dy * dy);

          // Connect points if close
          if (dist < 75) {
            connectionsCount++;
            const alpha = (1 - dist / 75) * 0.28 * Math.min(p1.rawNode.size, p2.rawNode.size);
            ctx.beginPath();
            ctx.moveTo(p1.x, p1.y);
            ctx.lineTo(p2.x, p2.y);
            const lineGrad = ctx.createLinearGradient(p1.x, p1.y, p2.x, p2.y);
            lineGrad.addColorStop(0, `rgba(236, 72, 153, ${alpha})`);
            lineGrad.addColorStop(1, `rgba(6, 182, 212, ${alpha})`);
            ctx.strokeStyle = lineGrad;
            ctx.stroke();
          }
          
          // Performance check: limit connections per node
          if (connectionsCount > 4) break;
        }
      }

      // Draw the nodes
      projected.forEach((p) => {
        ctx.beginPath();
        ctx.arc(p.x, p.y, Math.max(0.6, p.size), 0, Math.PI * 2);
        ctx.fillStyle = p.color;
        ctx.fill();

        // Subtle glowing highlight aura for front nodes
        if (p.z > sphereRadius * 0.2) {
          ctx.beginPath();
          ctx.arc(p.x, p.y, p.size * 2.5, 0, Math.PI * 2);
          ctx.fillStyle = p.color.replace(/[\d\.]+\)$/, "0.15)");
          ctx.fill();
        }
      });

      // Draw Active Theory coordinates & telemetry display overlay
      ctx.fillStyle = "rgba(233, 213, 255, 0.4)";
      ctx.font = "9px monospace";
      
      // Dynamic mouse coordinate tracking
      const coordX = isHovered ? Math.floor(mousePos.clientX) : 240;
      const coordY = isHovered ? Math.floor(mousePos.clientY) : 480;
      ctx.fillText(`LOC: [${coordX}.000, ${coordY}.000]`, 15, 25);
      
      // Cybernetic system logs
      ctx.fillText(`CORE.NODE_COUNT: [${numNodes}]`, 15, 40);
      ctx.fillText(`TENSION_FACTOR: ${(isHovered ? 1.45 : 1.0).toFixed(3)}`, 15, 55);
      
      // Draw crosshair telemetry target marker around mouse if hovered
      if (isHovered && mousePos.clientX > 0) {
        const mx = mousePos.clientX - (containerRef.current?.getBoundingClientRect().left || 0);
        const my = mousePos.clientY - (containerRef.current?.getBoundingClientRect().top || 0);
        
        ctx.strokeStyle = "rgba(236, 72, 153, 0.4)";
        ctx.lineWidth = 1;
        ctx.beginPath();
        // Crosshair reticle
        ctx.arc(mx, my, 8, 0, Math.PI * 2);
        ctx.moveTo(mx - 15, my); ctx.lineTo(mx + 15, my);
        ctx.moveTo(mx, my - 15); ctx.lineTo(mx, my + 15);
        ctx.stroke();
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
    setMousePos({ x, y, clientX: e.clientX, clientY: e.clientY });
  };

  return (
    <div
      ref={containerRef}
      className="relative flex items-center justify-center w-full max-w-[650px] aspect-square mx-auto cursor-none"
      onMouseMove={handleMouseMove}
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => {
        setIsHovered(false);
        setMousePos({ x: 0, y: 0, clientX: 0, clientY: 0 });
      }}
    >
      {/* Ambient background glow */}
      <div className="absolute inset-0 bg-gradient-to-r from-purple-500/10 via-cyan-600/15 to-pink-500/10 blur-3xl rounded-full animate-pulse opacity-70 pointer-events-none" />
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full z-10 pointer-events-none" />

      {/* Cybernetic Angle Brackets at the corners (Active Theory signature) */}
      <div className="absolute top-0 left-0 w-4 h-4 border-t-2 border-l-2 border-purple-500/40 pointer-events-none" />
      <div className="absolute top-0 right-0 w-4 h-4 border-t-2 border-r-2 border-purple-500/40 pointer-events-none" />
      <div className="absolute bottom-0 left-0 w-4 h-4 border-b-2 border-l-2 border-purple-500/40 pointer-events-none" />
      <div className="absolute bottom-0 right-0 w-4 h-4 border-b-2 border-r-2 border-purple-500/40 pointer-events-none" />

      {/* Center Floating NOVUS ADOS Badge (Glitch / Cybernetic visual details) */}
      <div className="relative z-20 transition-all duration-300 transform hover:scale-105 pointer-events-none">
        <div className="px-6 py-4 rounded-xl border border-purple-500/40 bg-[#070514]/80 backdrop-blur-xl text-center flex flex-col items-center shadow-[0_0_30px_rgba(168,85,247,0.2)]">
          <div className="flex items-center gap-2 mb-1">
            <span className="w-2.5 h-2.5 rounded-full bg-pink-500 animate-ping-slow" />
            <span className="text-2xl font-bold font-orbitron tracking-widest text-white jarvis-pink-glow">
              -84.2% <span className="text-cyan-400 font-syne">MTTR</span>
            </span>
          </div>
          <span className="text-[10px] uppercase tracking-widest text-purple-300/80 font-mono">
            RECOVERY COMPRESSION ACTIVE
          </span>
        </div>
      </div>
    </div>
  );
}

