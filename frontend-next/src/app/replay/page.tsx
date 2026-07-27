"use client";

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, EventEnvelope } from "@/lib/api";

export default function DecisionReplayPage() {
  const queryClient = useQueryClient();
  // Explicit user selection only; falls back to the first discovered
  // incident below. Deriving the effective ID during render (rather than
  // syncing it into state via an effect) avoids an extra render pass and
  // needing to call setState from inside an effect body.
  const [explicitIncidentId, setExplicitIncidentId] = useState<string>("");
  const [currentStep, setCurrentStep] = useState(0);
  const [isPlaying, setIsPlaying] = useState(false);
  const [playbackSpeed, setPlaybackSpeed] = useState(1);

  // Fetch all recent events from backend event bus to discover active incident IDs
  const allEventsQuery = useQuery<EventEnvelope[]>({
    queryKey: ["replay-all-events"],
    queryFn: () => api.listAllEvents(200),
    refetchInterval: 5000,
  });

  const allEvents = allEventsQuery.data ?? [];

  // Extract unique incident IDs published on backend event bus
  const incidentIds = Array.from(
    new Set(allEvents.map((evt) => evt.incidentId).filter(Boolean))
  );

  const selectedIncidentId = explicitIncidentId || incidentIds[0] || "";

  // Fetch real events for the selected incident ID
  const incidentEventsQuery = useQuery<EventEnvelope[]>({
    queryKey: ["replay-incident-events", selectedIncidentId],
    queryFn: () => (selectedIncidentId ? api.listIncidentEvents(selectedIncidentId) : Promise.resolve([])),
    enabled: Boolean(selectedIncidentId),
  });

  const incidentEvents = incidentEventsQuery.data ?? [];

  // Trigger live incident mutation
  const triggerIncidentMutation = useMutation({
    mutationFn: () =>
      api.startIncident({
        plant_id: "PLANT-04-AUSTIN",
        line_id: "Line 2",
        part_number: "MH-8820",
        vision_data: { defect: "BORE_TOLERANCE_EXCEEDED", offset_mm: 0.031 },
        priority: {
          safety_impact: 1,
          customer_impact: 4,
          line_down_cost_per_hour_usd: 510000,
          production_priority: 5,
          is_systemic: false,
        },
      }),
    onSuccess: (res) => {
      setExplicitIncidentId(res.incident_id);
      queryClient.invalidateQueries({ queryKey: ["replay-all-events"] });
      queryClient.invalidateQueries({ queryKey: ["replay-incident-events", res.incident_id] });
    },
  });

  // Playback timer effect
  useEffect(() => {
    let timer: NodeJS.Timeout;
    if (isPlaying && incidentEvents.length > 0) {
      timer = setInterval(() => {
        setCurrentStep((prev) => {
          if (prev >= incidentEvents.length - 1) {
            setIsPlaying(false);
            return prev;
          }
          return prev + 1;
        });
      }, 2500 / playbackSpeed);
    }
    return () => clearInterval(timer);
  }, [isPlaying, playbackSpeed, incidentEvents.length]);

  const activeEvent = incidentEvents[currentStep] ?? incidentEvents[0];

  return (
    <div className="space-y-6 pb-8">
      {/* Header Banner */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 p-5 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle shadow-lg">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold text-text-primary">Decision Replay Studio</h1>
            <span className="px-2.5 py-0.5 rounded-full text-xs font-mono bg-emerald/10 text-emerald border border-emerald/30">
              Backend Event Bus Replay
            </span>
          </div>
          <p className="text-sm text-text-secondary mt-1">
            Time-travel audit player reading real immutable <code className="text-cobalt">EventEnvelope</code> objects from backend event bus.
          </p>
        </div>

        {/* Live Incident Generator Button */}
        <button
          onClick={() => triggerIncidentMutation.mutate()}
          disabled={triggerIncidentMutation.isPending}
          className="px-4 py-2 rounded-lg bg-emerald text-white font-mono text-xs font-bold hover:bg-emerald/80 transition-all border border-emerald/40 shadow-lg disabled:opacity-50 flex items-center gap-2"
        >
          {triggerIncidentMutation.isPending ? "Starting Incident..." : "⚡ Trigger Live Incident (Line 2)"}
        </button>
      </div>

      {/* Incident ID Selection Bar */}
      <div className="flex flex-wrap items-center gap-3 p-4 rounded-xl bg-card/60 border border-border-subtle font-mono text-xs shadow">
        <span className="text-text-secondary">Discovered Incidents ({incidentIds.length}):</span>
        {incidentIds.length === 0 ? (
          <span className="text-amber font-semibold">No incidents found in backend bus. Click &quot;Trigger Live Incident&quot; above!</span>
        ) : (
          incidentIds.map((id) => (
            <button
              key={id}
              onClick={() => {
                setExplicitIncidentId(id);
                setCurrentStep(0);
                setIsPlaying(false);
              }}
              className={`px-3 py-1.5 rounded-lg border transition-all ${
                selectedIncidentId === id
                  ? "bg-cobalt text-white border-cobalt font-bold shadow"
                  : "bg-glass text-text-secondary border-border-subtle hover:border-border-accent"
              }`}
            >
              {id}
            </button>
          ))
        )}
      </div>

      {/* Time-Travel Control Bar */}
      {incidentEvents.length > 0 ? (
        <div className="rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-6 space-y-5 shadow-lg">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-border-subtle pb-4">
            <div className="flex items-center gap-3">
              <button
                onClick={() => setIsPlaying(!isPlaying)}
                className="px-4 py-2 rounded-lg bg-cobalt text-white font-mono text-xs font-bold hover:bg-cobalt/80 transition-all border border-cobalt/40 flex items-center gap-2"
              >
                {isPlaying ? "⏸️ PAUSE REPLAY" : "⏯️ PLAY REPLAY"}
              </button>
              <button
                onClick={() => setCurrentStep((prev) => Math.min(prev + 1, incidentEvents.length - 1))}
                disabled={currentStep >= incidentEvents.length - 1}
                className="px-3 py-2 rounded-lg bg-glass text-text-primary font-mono text-xs hover:border-border-accent border border-border-subtle disabled:opacity-40"
              >
                ⏩ STEP FORWARD
              </button>
              <button
                onClick={() => {
                  setCurrentStep(0);
                  setIsPlaying(false);
                }}
                className="px-3 py-2 rounded-lg bg-glass text-text-secondary font-mono text-xs hover:border-border-accent border border-border-subtle"
              >
                🔄 RESET
              </button>
            </div>

            <div className="flex items-center gap-2 text-xs font-mono text-text-secondary">
              <span>Event Step: {currentStep + 1} / {incidentEvents.length}</span>
              <span className="ml-3">Speed:</span>
              {[1, 2, 5].map((speed) => (
                <button
                  key={speed}
                  onClick={() => setPlaybackSpeed(speed)}
                  className={`px-2.5 py-1 rounded border ${
                    playbackSpeed === speed
                      ? "bg-cobalt/20 text-cobalt border-cobalt font-bold"
                      : "bg-glass text-text-secondary border-border-subtle"
                  }`}
                >
                  {speed}x
                </button>
              ))}
            </div>
          </div>

          {/* Dynamic Scrubber Timeline Stepper */}
          <div className="grid grid-cols-2 sm:grid-cols-4 md:grid-cols-6 gap-2 pt-2 overflow-x-auto">
            {incidentEvents.map((evt, idx) => {
              const isCompleted = idx < currentStep;
              const isCurrent = idx === currentStep;

              return (
                <div
                  key={evt.eventId || idx}
                  onClick={() => {
                    setCurrentStep(idx);
                    setIsPlaying(false);
                  }}
                  className={`p-3 rounded-lg border text-center cursor-pointer transition-all ${
                    isCurrent
                      ? "bg-cobalt/20 border-cobalt shadow-lg scale-[1.02]"
                      : isCompleted
                      ? "bg-emerald/10 border-emerald/40 text-emerald"
                      : "bg-glass border-border-subtle opacity-60 hover:opacity-100"
                  }`}
                >
                  <div className="text-xs font-mono font-bold text-text-primary truncate">{evt.eventType}</div>
                  <div className="text-[10px] font-mono text-text-secondary mt-1">
                    {new Date(evt.occurredAt).toLocaleTimeString()}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      ) : (
        <div className="rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-12 text-center text-xs font-mono text-text-secondary space-y-3 shadow-lg">
          <div className="text-2xl">🎬</div>
          <div className="text-text-primary font-bold text-sm">No Audit Events for Incident {selectedIncidentId || "Selection"}</div>
          <p>Click &quot;Trigger Live Incident (Line 2)&quot; above to publish real events to the backend event bus!</p>
        </div>
      )}

      {/* Replay Stage Inspector & Event Envelope Viewer */}
      {activeEvent && (
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Active Event Details */}
          <div className="lg:col-span-6 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-6 space-y-4 shadow-lg">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2.5">
                <span className="text-2xl">⚡</span>
                <div>
                  <span className="px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-cobalt/20 text-cobalt border border-cobalt/30">
                    {activeEvent.eventType}
                  </span>
                  <h2 className="text-base font-bold text-text-primary mt-0.5">Produced By: {activeEvent.producedBy}</h2>
                </div>
              </div>
              <span className="text-xs font-mono text-text-secondary">
                {new Date(activeEvent.occurredAt).toLocaleTimeString()}
              </span>
            </div>

            <div className="p-4 rounded-lg bg-glass border border-border-subtle text-xs text-text-primary space-y-2 font-mono">
              <div>Event ID: <span className="text-cobalt">{activeEvent.eventId}</span></div>
              <div>Schema Version: <span className="text-text-secondary">{activeEvent.schemaVersion}</span></div>
              <div>Incident ID: <span className="text-emerald">{activeEvent.incidentId}</span></div>
            </div>
          </div>

          {/* Event Envelope JSON Inspector */}
          <div className="lg:col-span-6 rounded-xl bg-card/60 backdrop-blur-md border border-border-subtle p-6 space-y-4 shadow-lg">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <span className="text-lg">📜</span>
                <h2 className="text-sm font-semibold text-text-primary">Wire EventEnvelope JSON</h2>
              </div>
              <span className="text-[10px] font-mono text-purple px-2 py-0.5 rounded bg-purple/10 border border-purple/20">
                Immutable Ledger
              </span>
            </div>

            <div className="p-3.5 rounded-lg bg-glass border border-border-subtle font-mono text-[11px] overflow-x-auto max-h-[300px]">
              <pre className="text-emerald">{JSON.stringify(activeEvent, null, 2)}</pre>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
