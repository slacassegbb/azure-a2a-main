# Visual Workflow Designer

## Overview

The Visual Workflow Designer is a new feature that allows you to design agent workflows visually by dragging and dropping agents onto a canvas, connecting them sequentially, and adding step descriptions.

## Features

### 🎨 Visual Canvas
- **Drag & Drop**: Drag agents from the left palette onto the canvas to add workflow steps
- **Sequential Connections**: Steps are automatically connected in order with numbered badges
- **Interactive Canvas**: Pan (drag), zoom (scroll wheel), and double-click to reset view
- **Agent Styling**: Each agent has a unique color matching the Agent Network DAG visualization

### ✏️ Step Editing
- **Select Steps**: Click on any step in the canvas to edit it
- **Edit Descriptions**: Customize what each agent should do in the workflow
- **Reorder Steps**: Use "Move Up" and "Move Down" buttons to change step order
- **Delete Steps**: Remove unwanted steps with the delete button or Del/Backspace key

### 🔄 Dual Mode Interface
- **Visual Designer**: Interactive canvas for building workflows visually
- **Text Editor**: Traditional text-based workflow definition
- **Seamless Sync**: Changes in visual mode generate workflow text automatically
- **Import from Text**: Parse existing text workflows into visual format (when possible)

## How to Use

### 1. Enable Agent Mode
First, enable Agent Mode in the left sidebar's Agent Network panel.

### 2. Open Workflow Designer
Click the "Define Workflow" or "Edit Workflow" button that appears when Agent Mode is enabled.

### 3. Build Your Workflow

#### Visual Mode (Default)
1. **Drag Agents**: From the "Available Agents" panel on the left, drag an agent onto the canvas
2. **Position**: Place the agent where you want it in the workflow
3. **Add Steps**: Continue dragging agents to add more steps
4. **Edit Details**: Click on a step to select it, then edit its description in the right panel
5. **Reorder**: Use "Move Up" / "Move Down" buttons to change step sequence
6. **Delete**: Select a step and click "Delete Step" or press Del/Backspace

#### Text Mode
Switch to the "Text Editor" tab to manually write or edit workflow steps in text format:

```
1. Use the image generator agent to create an image based on the user's request
2. Use the branding agent to get branding guidelines
3. Use the image generator to refine the image based on branding
4. Use the image analysis agent to review the result
```

### 4. Save Workflow
Click "Save Workflow" to apply your workflow. The workflow will guide the Host Agent's orchestration.

## Canvas Controls

- **Pan**: Click and drag anywhere on the canvas (cursor changes to grabbing hand)
- **Zoom**: Scroll mouse wheel up/down
- **Reset View**: Click "Reset View" button or press `0` key
- **Select Step**: Click on any agent icon
- **Delete Step**: Select a step and press `Delete` or `Backspace` key

## Generated Workflow Text

The visual workflow automatically generates text that is sent to the backend:

```
1. Use the Image Generator agent to create initial image
2. Use the Branding Agent to provide branding guidelines
3. Use the Image Generator agent to refine based on branding
```

This text is injected into the orchestration prompt as a mandatory workflow that the Host Agent must follow.

## Technical Details

### Components

- **VisualWorkflowDesigner** (`components/visual-workflow-designer.tsx`)
  - Main visual workflow designer component
  - Canvas-based rendering using HTML5 Canvas
  - Drag-and-drop agent palette
  - Step editor panel
  - Workflow text generation

- **AgentNetwork** (`components/agent-network.tsx`)
  - Updated to include tabbed workflow dialog
  - Tabs for switching between Visual Designer and Text Editor modes

### Workflow Format

The visual workflow is converted to a simple numbered text format that the backend expects:

```
1. [Step description with agent name]
2. [Step description with agent name]
...
```

The backend's orchestration system parses this workflow and ensures all steps are completed sequentially.

### Canvas Rendering

The canvas uses a similar visual style to the Agent Network DAG:
- **Background**: Dark gradient matching the app theme
- **Grid**: Subtle grid for spatial reference
- **Agent Icons**: Hexagonal icons with unique colors per agent
- **Connections**: Dashed lines with arrows showing flow direction
- **Order Badges**: Numbered circles indicating step sequence

## Future Enhancements

Potential improvements for future versions:

1. **Branching Workflows**: Support for conditional paths and parallel execution
2. **Step Parameters**: Add input fields for step-specific configuration
3. **Workflow Templates**: Save and load common workflow patterns
4. **Export/Import**: Download workflows as JSON for sharing
5. **Visual Validation**: Real-time validation of workflow completeness
6. **Agent Constraints**: Visual indicators for agent compatibility/requirements
7. **Workflow History**: Track and restore previous workflow versions

## Troubleshooting

### Agents Not Appearing in Palette
- Ensure agents are properly registered in the system
- Check that the WebSocket connection is active
- Verify agents are showing in the Agent Network sidebar

### Steps Not Connecting
- Steps are connected in order based on their order number (badge)
- Use "Move Up"/"Move Down" to adjust step sequence
- Connections update automatically when step order changes

### Canvas Too Small/Large
- Use scroll wheel to zoom in/out
- Press `0` to reset zoom to 100%
- Click and drag to pan around the canvas

### Workflow Not Saving
- Ensure you click "Save Workflow" button
- Check browser console for any error messages
- Verify Agent Mode is enabled

## Related Documentation

- [Agent Mode Documentation](./documentation.md)
- [Agent Network DAG](./frontend/components/agent-network-dag.tsx)
- [Backend Orchestration](./backend/hosts/multiagent/foundry_agent_a2a.py)

