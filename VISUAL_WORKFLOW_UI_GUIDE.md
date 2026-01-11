# Visual Workflow Designer - UI Layout Guide

## Dialog Layout

When you click "Define Workflow" in Agent Mode, you'll see a large dialog with this layout:

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│ Agent Mode Workflow                                                           × │
│ Define the workflow steps that will be appended to your goal.                  │
├─────────────────────────────────────────────────────────────────────────────────┤
│                                                                                 │
│  ┌────────────────────┬────────────────────┐                                   │
│  │  Visual Designer   │   Text Editor      │  ◄─── Tabs                        │
│  └────────────────────┴────────────────────┘                                   │
│                                                                                 │
│  ┌───────────────┬──────────────────────────────────────┬─────────────────┐   │
│  │               │                                       │                 │   │
│  │  Available    │         Workflow Canvas              │   Step Details  │   │
│  │   Agents      │                                       │                 │   │
│  │               │                                       │                 │   │
│  │ ┌───────────┐ │   ┌───┐         ┌───┐              │  Agent:          │   │
│  │ │ Agent 1   │ │   │ 1 │─────────│ 2 │              │  [Selected]      │   │
│  │ │ Image Gen │ │   │ ⬡ │    ───► │ ⬡ │              │                 │   │
│  │ └───────────┘ │   └───┘         └───┘              │  Step Order:     │   │
│  │               │    Agent 1       Agent 2             │  [↑] [↓]        │   │
│  │ ┌───────────┐ │                                      │                 │   │
│  │ │ Agent 2   │ │           ┌───┐                     │  Description:    │   │
│  │ │ Branding  │ │           │ 3 │                     │  ┌─────────────┐ │   │
│  │ └───────────┘ │           │ ⬡ │                     │  │ Use the...  │ │   │
│  │               │           └───┘                     │  │             │ │   │
│  │ ┌───────────┐ │          Agent 3                     │  │             │ │   │
│  │ │ Agent 3   │ │                                      │  └─────────────┘ │   │
│  │ │ Analysis  │ │  [Reset View] [Clear All]           │                 │   │
│  │ └───────────┘ │                                      │  [Delete Step]  │   │
│  │               │                                       │                 │   │
│  │    (Scroll)   │  Tips: Drag to pan • Scroll to zoom │                 │   │
│  │               │                                       │                 │   │
│  └───────────────┴──────────────────────────────────────┴─────────────────┘   │
│                                                                                 │
│  Generated Workflow Text:                                                      │
│  ┌───────────────────────────────────────────────────────────────────────────┐ │
│  │ 1. Use the Image Generator agent to create initial image                  │ │
│  │ 2. Use the Branding Agent to provide branding guidelines                  │ │
│  │ 3. Use the Image Analysis agent to review the result                      │ │
│  └───────────────────────────────────────────────────────────────────────────┘ │
│                                                                                 │
│                                     [Clear]  [Save Workflow]                   │
└─────────────────────────────────────────────────────────────────────────────────┘
```

## Visual Designer Components

### 1. Agent Palette (Left Panel)

```
┌─────────────────┐
│ Available Agents│
├─────────────────┤
│ ┌─────────────┐ │
│ │ Agent Name  │ │ ◄─── Draggable card
│ │ Description │ │      (with colored left border)
│ └─────────────┘ │
│                 │
│ ┌─────────────┐ │
│ │ Agent Name  │ │
│ │ Description │ │
│ └─────────────┘ │
│                 │
│     (scroll)    │
└─────────────────┘
```

**Features:**
- Scroll to see all available agents
- Colored left border matches agent's canvas color
- Drag any agent onto canvas to add to workflow

### 2. Workflow Canvas (Center)

```
     Canvas Controls: Reset View | Clear All
┌─────────────────────────────────────────┐
│  • • • • Grid background • • • • •      │
│                                          │
│       ┌───┐                              │
│       │ 1 │  ◄─── Step order badge       │
│       └───┘                              │
│        ⬡    ◄─── Agent icon (hexagon)   │
│     Agent Name                           │
│        │                                 │
│        │  ──────►  Dashed connection     │
│        ↓           with arrow            │
│       ┌───┐                              │
│       │ 2 │                              │
│       └───┘                              │
│        ⬡                                 │
│     Agent Name                           │
│                                          │
└─────────────────────────────────────────┘
  Tips: Drag to pan • Scroll to zoom
```

**Visual Elements:**
- **Grid**: Subtle background grid for alignment reference
- **Order Badge**: Numbered circle showing step sequence
- **Agent Icon**: Hexagonal shape with unique color per agent
- **Agent Name**: Below the icon, word-wrapped if long
- **Connections**: Dashed lines with arrows showing flow
- **Glow Effect**: Selected step has glowing halo

**Canvas Interactions:**
- **Drag to Pan**: Click and drag anywhere to move view
- **Scroll to Zoom**: Mouse wheel to zoom in/out
- **Click to Select**: Click on any agent icon to select
- **Drop Agent**: Drag from palette and drop on canvas
- **Delete**: Press Del or Backspace to remove selected step

### 3. Step Editor (Right Panel)

```
┌───────────────────┐
│ Edit Step         │
├───────────────────┤
│ Agent:            │
│ ┌───────────────┐ │
│ │ Agent Name    │ │ ◄─── Read-only, colored border
│ └───────────────┘ │
│                   │
│ Step Order:       │
│ ┌───────┬───────┐ │
│ │↑ Move │↓ Move │ │ ◄─── Reorder buttons
│ │  Up   │ Down  │ │
│ └───────┴───────┘ │
│                   │
│ Step Description: │
│ ┌───────────────┐ │
│ │ Use the...    │ │
│ │               │ │ ◄─── Editable textarea
│ │               │ │
│ │               │ │
│ └───────────────┘ │
│                   │
│ ┌───────────────┐ │
│ │ 🗑 Delete Step│ │ ◄─── Delete button
│ └───────────────┘ │
└───────────────────┘
```

**When No Step Selected:**
```
┌───────────────────┐
│ Step Details      │
├───────────────────┤
│                   │
│                   │
│  Select a step    │
│  on the canvas    │
│  to edit its      │
│  details          │
│                   │
│                   │
└───────────────────┘
```

### 4. Generated Workflow Preview (Bottom)

```
Generated Workflow Text:
┌─────────────────────────────────────────────────────────────┐
│ 1. Use the Image Generator agent to create initial image    │
│ 2. Use the Branding Agent to provide branding guidelines    │
│ 3. Use the Image Analysis agent to review the result        │
└─────────────────────────────────────────────────────────────┘
```

This shows the final text that will be sent to the backend for orchestration.

## Text Editor Mode

Switch to "Text Editor" tab to see the traditional interface:

```
┌─────────────────────────────────────────────────────────────┐
│ Text Editor                                                  │
├─────────────────────────────────────────────────────────────┤
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Example:                                                 │ │
│ │ 1. Use the image generator agent to create an image     │ │
│ │ 2. Use the branding agent to get branding guidelines    │ │
│ │ 3. Use the image generator to refine based on branding  │ │
│ │ 4. Use the image analysis agent to review the result    │ │
│ │                                                          │ │
│ │                                                          │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                              │
│ Current workflow:                                           │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ 1. Use the Image Generator agent...                     │ │
│ │ 2. Use the Branding Agent...                            │ │
│ └─────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Color Scheme

The visual workflow designer uses the same color palette as the Agent Network DAG:

```
Agent Colors (rotating):
┌────┬────┬────┬────┬────┬────┬────┬────┬────┬────┐
│ 1  │ 2  │ 3  │ 4  │ 5  │ 6  │ 7  │ 8  │ 9  │ 10 │
├────┼────┼────┼────┼────┼────┼────┼────┼────┼────┤
│ 🌸 │ 🟣 │ 🔵 │ 🟢 │ 🟡 │ 🔴 │ 🔵 │ 🟦 │ 🟠 │ 🟪 │
│Pink│Pur.│Cyan│Emer│Amb.│Red │Blue│Teal│Ora.│Vio.│
└────┴────┴────┴────┴────┴────┴────┴────┴────┴────┘
```

**Background:** Dark slate gradient (matches app theme)
**Text:** Light slate for readability
**Grid:** Subtle gray for reference
**Connections:** Indigo blue dashed lines
**Selection:** Glowing halo in agent's color

## State Indicators

### Agent Icon States

```
Normal:          Selected:         In Workflow:
  ⬡                ⬡ ✨               1
  │                │ glow            ⬡
Agent            Agent             Agent
```

### Canvas States

```
Empty Canvas:
┌─────────────────────────────────┐
│                                 │
│  Drag agents from the left      │
│  panel onto this canvas         │
│  to build your workflow         │
│                                 │
└─────────────────────────────────┘

Drag Over:
┌┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┐
┆ Dashed border indicates        ┆
┆ drop target ready               ┆
└┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┘

With Steps:
┌─────────────────────────────────┐
│    ┌───┐     ┌───┐     ┌───┐   │
│    │ 1 │────►│ 2 │────►│ 3 │   │
│    │ ⬡ │     │ ⬡ │     │ ⬡ │   │
│    └───┘     └───┘     └───┘   │
└─────────────────────────────────┘
```

## Keyboard Shortcuts

```
Key         Action
────────────────────────────────────
Delete      Delete selected step
Backspace   Delete selected step
0           Reset zoom and pan
+           Zoom in (or scroll up)
-           Zoom out (or scroll down)
Esc         Close dialog (from text)
```

## Mouse Interactions

```
Action              Result
────────────────────────────────────────────
Click agent         Select for editing
Drag canvas         Pan view
Scroll wheel        Zoom in/out
Double-click        Reset zoom/pan
Drag from palette   Add new step
```

## Responsive Behavior

The dialog is sized for optimal viewing:
- **Width:** 95% of viewport (max-w-[95vw])
- **Height:** 900px (with scrolling if needed)
- **Canvas:** 680px height for workflow area
- **Panels:** Fixed widths (250px palette, 320px editor)

## Dark Theme Integration

The visual workflow designer seamlessly integrates with the app's dark theme:

```
Component           Color
───────────────────────────────────────
Background          Slate-900 gradient
Panel borders       Slate-800
Text (primary)      Slate-200
Text (secondary)    Slate-400
Grid lines          Slate-800 (5% opacity)
Agent icons         Vibrant accent colors
Connections         Indigo-500 (40% opacity)
Selected glow       Agent color (20% opacity)
```

## Loading States

```
Initial Load:
┌───────────────┐
│ Available     │
│ Agents        │
├───────────────┤
│ Loading...    │
└───────────────┘

No Agents:
┌───────────────┐
│ Available     │
│ Agents        │
├───────────────┤
│ No agents     │
│ registered    │
└───────────────┘
```

## Tips for Best Experience

1. **Start Simple**: Add 2-3 steps first to get familiar
2. **Use Descriptions**: Edit step descriptions to be specific
3. **Check Preview**: Review generated workflow text before saving
4. **Switch Modes**: Use text mode for quick edits, visual for planning
5. **Save Often**: Click "Save Workflow" to preserve your work
6. **Pan & Zoom**: Adjust view for complex workflows with many steps

## Example Workflow

Here's how a complete workflow looks in the visual designer:

```
Step 1: Image Generation
   ↓
Step 2: Branding Guidelines
   ↓
Step 3: Image Refinement
   ↓
Step 4: Quality Analysis
```

Visual representation on canvas:

```
    ┌───┐
    │ 1 │    "Generate initial image based on request"
    │ ⬡ │
    └─┬─┘
      │ ───►
      ↓
    ┌───┐
    │ 2 │    "Get branding guidelines and requirements"
    │ ⬡ │
    └─┬─┘
      │ ───►
      ↓
    ┌───┐
    │ 3 │    "Refine image applying branding standards"
    │ ⬡ │
    └─┬─┘
      │ ───►
      ↓
    ┌───┐
    │ 4 │    "Analyze final result for quality check"
    │ ⬡ │
    └───┘
```

Generated text:
```
1. Generate initial image based on request
2. Get branding guidelines and requirements
3. Refine image applying branding standards
4. Analyze final result for quality check
```

This workflow ensures the orchestrator follows these steps sequentially!

