"use client";

// Knowledge Explorer (/knowledge) - documentation/06_Product_Execution_Master_Plan.md
// Product 5: "Graph visualizer for enterprise entity relationships (products,
// suppliers, parts, failure modes)." Scoped here to BOM & Suppliers
// (Product/Part/Supplier nodes) per the literal build request - Specification
// detail is surfaced on click rather than as separate graph nodes, to keep
// the graph legible at this dataset's scale.

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ReactFlow,
  Background,
  Controls,
  Handle,
  Position,
  useNodesState,
  useEdgesState,
  type Node,
  type Edge,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { api, GraphNode as KgNode, KnowledgeGraphSnapshot } from "@/lib/api";
import { useHasToken } from "@/lib/useHasToken";

type EntityNode = Node<{ node: KgNode }>;

const NODE_ACCENT: Record<KgNode["type"], { border: string; text: string; bg: string }> = {
  PRODUCT: { border: "border-purple/50", text: "text-purple", bg: "bg-purple/10" },
  PART: { border: "border-cobalt/50", text: "text-cobalt", bg: "bg-cobalt/10" },
  SUPPLIER: { border: "border-emerald/50", text: "text-emerald", bg: "bg-emerald/10" },
};

function EntityNodeCard({ data }: NodeProps<EntityNode>) {
  const { node } = data;
  const accent = NODE_ACCENT[node.type];
  return (
    <div className={`min-w-[170px] rounded-lg border ${accent.border} ${accent.bg} backdrop-blur-md px-4 py-2.5 shadow-lg`}>
      <Handle type="target" position={Position.Left} style={{ background: "var(--border-subtle)" }} />
      <div className={`text-[10px] font-mono font-bold ${accent.text}`}>{node.type}</div>
      <div className="truncate text-xs font-semibold text-text-primary">{node.label}</div>
      <div className="truncate text-[10px] font-mono text-text-secondary">{node.id}</div>
      <Handle type="source" position={Position.Right} style={{ background: "var(--border-subtle)" }} />
    </div>
  );
}

const NODE_TYPES = { entity: EntityNodeCard };

const COLUMN_X: Record<KgNode["type"], number> = { PRODUCT: 40, PART: 400, SUPPLIER: 760 };
const EDGE_COLOR: Record<string, string> = { BOM: "#3b82f6", SUPPLIES: "#10b981", SUBSTITUTE: "#f59e0b" };

function layoutSnapshot(snapshot: KnowledgeGraphSnapshot): { nodes: EntityNode[]; edges: Edge[] } {
  const byType: Record<KgNode["type"], KgNode[]> = { PRODUCT: [], PART: [], SUPPLIER: [] };
  snapshot.nodes.forEach((n) => byType[n.type]?.push(n));

  const nodes: EntityNode[] = [];
  (Object.keys(byType) as Array<KgNode["type"]>).forEach((type) => {
    const group = byType[type];
    const spacingY = 110;
    const offsetY = ((group.length - 1) * spacingY) / 2;
    group.forEach((n, i) => {
      nodes.push({
        id: n.id,
        type: "entity",
        position: { x: COLUMN_X[type], y: i * spacingY - offsetY + 260 },
        data: { node: n },
      });
    });
  });

  const edges: Edge[] = snapshot.edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    label: e.label ?? undefined,
    type: "smoothstep",
    animated: e.type === "SUBSTITUTE",
    style: { stroke: EDGE_COLOR[e.type] },
    labelStyle: { fill: EDGE_COLOR[e.type], fontSize: 10 },
    labelBgStyle: { fill: "var(--bg-card)" },
  }));

  return { nodes, edges };
}

function prettifyKey(key: string): string {
  return key.replace(/([A-Z])/g, " $1").replace(/^./, (c) => c.toUpperCase());
}

function formatDetailValue(key: string, value: unknown): string {
  if (typeof value === "number") {
    return /usd/i.test(key) ? `$${value.toLocaleString("en-US")}` : value.toLocaleString("en-US");
  }
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

export default function KnowledgeExplorerPage() {
  const hasToken = useHasToken();
  const [selectedNode, setSelectedNode] = useState<KgNode | null>(null);
  const [nodes, setNodes, onNodesChange] = useNodesState<EntityNode>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

  const graphQuery = useQuery<KnowledgeGraphSnapshot>({
    queryKey: ["knowledge-graph"],
    queryFn: api.getKnowledgeGraph,
    enabled: hasToken,
  });

  useEffect(() => {
    if (!graphQuery.data) return;
    const layout = layoutSnapshot(graphQuery.data);
    setNodes(layout.nodes);
    setEdges(layout.edges);
  }, [graphQuery.data, setNodes, setEdges]);

  const counts = useMemo(() => {
    const data = graphQuery.data;
    if (!data) return { products: 0, parts: 0, suppliers: 0, edges: 0 };
    return {
      products: data.nodes.filter((n) => n.type === "PRODUCT").length,
      parts: data.nodes.filter((n) => n.type === "PART").length,
      suppliers: data.nodes.filter((n) => n.type === "SUPPLIER").length,
      edges: data.edges.length,
    };
  }, [graphQuery.data]);

  return (
    <div className="flex flex-col gap-6 pb-8">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 rounded-xl border border-border-subtle bg-card/60 p-5 shadow-lg backdrop-blur-md">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-text-primary">Knowledge Explorer</h1>
            <span className="rounded-full border border-purple/30 bg-purple/10 px-2.5 py-0.5 text-xs font-mono text-purple">
              BOM &amp; Supplier Graph
            </span>
          </div>
          <p className="mt-1 text-sm text-text-secondary">
            Interactive view of the Enterprise Knowledge Graph — products, parts, and approved suppliers.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3 text-xs font-mono text-text-secondary">
          <span className="rounded-lg border border-border-subtle bg-glass px-3 py-1.5">
            <span className="text-purple font-bold">{counts.products}</span> Products
          </span>
          <span className="rounded-lg border border-border-subtle bg-glass px-3 py-1.5">
            <span className="text-cobalt font-bold">{counts.parts}</span> Parts
          </span>
          <span className="rounded-lg border border-border-subtle bg-glass px-3 py-1.5">
            <span className="text-emerald font-bold">{counts.suppliers}</span> Suppliers
          </span>
          <span className="rounded-lg border border-border-subtle bg-glass px-3 py-1.5">
            <span className="text-text-primary font-bold">{counts.edges}</span> Relationships
          </span>
        </div>
      </div>

      {!hasToken && <p className="text-sm text-text-secondary">Enter a service token to load the knowledge graph.</p>}
      {hasToken && graphQuery.isLoading && <p className="text-sm text-text-secondary">Loading knowledge graph…</p>}
      {hasToken && graphQuery.isError && (
        <p className="text-sm text-status-red">Could not load the knowledge graph (check token).</p>
      )}

      {/* Graph canvas + detail panel */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        <div className="lg:col-span-8 h-[70vh] overflow-hidden rounded-xl border border-border-subtle bg-card/60 shadow-lg">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            nodeTypes={NODE_TYPES}
            onNodeClick={(_, node) => setSelectedNode((node as EntityNode).data.node)}
            onPaneClick={() => setSelectedNode(null)}
            fitView
            proOptions={{ hideAttribution: true }}
          >
            <Background color="var(--border-subtle)" gap={24} />
            <Controls style={{ background: "var(--bg-card)", border: "1px solid var(--border-subtle)" }} />
          </ReactFlow>
        </div>

        {/* Detail Panel */}
        <div className="lg:col-span-4 rounded-xl border border-border-subtle bg-card/60 p-6 shadow-lg backdrop-blur-md">
          {selectedNode ? (
            <div className="space-y-4">
              <div className="flex items-center justify-between border-b border-border-subtle pb-3">
                <div>
                  <span className={`text-[10px] font-mono font-bold ${NODE_ACCENT[selectedNode.type].text}`}>
                    {selectedNode.type}
                  </span>
                  <h2 className="text-base font-bold text-text-primary">{selectedNode.label}</h2>
                </div>
              </div>
              <div className="space-y-2 font-mono text-xs">
                {Object.entries(selectedNode.detail).map(([key, value]) => (
                  <div key={key} className="flex items-center justify-between rounded-lg border border-border-subtle bg-glass px-3 py-2">
                    <span className="text-text-secondary">{prettifyKey(key)}</span>
                    <span className="text-text-primary font-semibold">{formatDetailValue(key, value)}</span>
                  </div>
                ))}
              </div>
            </div>
          ) : (
            <div className="py-12 text-center text-xs font-mono text-text-secondary">
              Click a node to inspect its details. Drag to rearrange, scroll to zoom.
            </div>
          )}

          <div className="mt-6 space-y-2 border-t border-border-subtle pt-4 text-[11px] font-mono text-text-secondary">
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full" style={{ background: EDGE_COLOR.BOM }} />
              BOM (Product → Part)
            </div>
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full" style={{ background: EDGE_COLOR.SUPPLIES }} />
              Supplies (Part → Supplier)
            </div>
            <div className="flex items-center gap-2">
              <span className="h-2 w-2 rounded-full" style={{ background: EDGE_COLOR.SUBSTITUTE }} />
              Substitute (Part → Part)
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
