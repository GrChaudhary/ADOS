# ADOS Demo & Product Experience Blueprint

## Goal
The live demo should make judges remember one thing:

> **When a factory doesn't know what to do next, ADOS does.**

Don't sell AI or architecture. Sell the outcome:
**Reduce production recovery from days to minutes.**

---

# Story

Meet **Emma**, a Quality Engineer at **Nova Motors**.

A motor housing fails QA inspection.

Traditional process:
- Emails
- Meetings
- Supplier calls
- SAP updates
- ServiceNow tickets

Recovery: **2–5 days**

With ADOS:
Emma uploads the inspection.
ADOS investigates, recommends, orchestrates execution, and resumes production in minutes.

---

# Demo Flow

## 1. Healthy Factory
Dashboard:
- Production Health: 98.7%
- Open Incidents: 0
- Autonomous Decisions Today: 17
- Line 1 🟢
- Line 2 🟢
- Line 3 🟢

## 2. Incident
Popup:
'Quality Alert – Motor Housing – Tolerance exceeded'

Line 2 turns 🔴.

## 3. Incident Workspace
Tabs:
- Overview
- Evidence
- Reasoning
- Recommendations
- Execution
- Audit

Evidence:
- Inspection Image
- CAD Overlay
- Measured: 0.031 mm
- Allowed: 0.020 mm

## 4. Live Timeline
09:41 Vision ✓
09:41 CAD ✓
09:42 Knowledge Graph ✓
09:42 Supplier Analysis ✓
09:43 Simulation ✓
09:43 Recommendation ✓

## 5. Recommendation Screen

Option A ⭐⭐⭐⭐⭐
Switch to Supplier B
Delay: 8 hrs
Savings: $430K
Confidence: 94%

Option B
Wait for Supplier A
Delay: 5 days
Revenue Loss: $2.1M

Option C
Adjust CNC Parameters
Delay: 0
Quality Risk: 8%

## 6. Approval
Emma clicks Approve.

Progress:
- Create ServiceNow Incident ✓
- Reserve Inventory ✓
- Create SAP PO ✓
- Update MES ✓
- Notify Operators ✓

## 7. Recovery
Line 2 becomes 🟢.

Display:
- Downtime: 6 min
- Revenue Protected: $417K
- Confidence: 94%

## 8. Executive Mode
Dashboard:
- Revenue Protected
- MTTR
- Supplier Risk
- Autonomy Index
- Production Availability
- Recommendations

Ask:
'Why was Supplier B selected?'

Response:
- Approved supplier
- Stock available
- Lowest lead time
- Best quality history

---

# Product Experience

Think of ADOS as Mission Control or JARVIS for manufacturing.

AI Specialists:
- 👁 Vision
- 📐 CAD
- 🧠 Root Cause
- 📦 Procurement
- 🚚 Logistics
- 📈 Executive Advisor

IBM Orchestrate is the COO coordinating them.

---

# Demo Dataset

Company:
Nova Motors

Products:
- Motor Housing
- Rotor
- Bearing
- Cooling Plate
- Gear Assembly

Machines:
- CNC-101
- CNC-102
- Robot Arm
- Inspection Cell
- Assembly Line

Suppliers:
- PrecisionCast
- SteelCore
- Titan Metals
- ForgeWorks
- Rapid Components

Generate ~100 historical incidents:
- Humidity
- Tolerance drift
- Supplier defects
- Tool wear
- Calibration
- Machine vibration
- Material mismatch
- Shipping delays

Use these for Knowledge Graph and Decision Memory.

---

# Live Digital Twin

Always show:
- Line 1 🟢
- Line 2 🔴→🟢
- Line 3 🟢
- Warehouse 🟢

---

# IBM Workflow View

Vision ✓
CAD ✓
Knowledge ✓
Simulation ✓
Approval ✓
ServiceNow ✓
SAP ✓
MES ✓

---

# Messaging

Never start with:
- Knowledge Graph
- Kafka
- Redis
- Neo4j

Start with:

Observe
↓
Understand
↓
Decide
↓
Coordinate
↓
Learn

Reveal the architecture only after the story.

---

# One Sentence

**When a factory doesn't know what to do next, ADOS does.**
