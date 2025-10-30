"use client"

import * as React from "react"
import * as d3 from "d3"
import { useTheme } from "next-themes"

interface Node extends d3.SimulationNodeDatum {
  id: string
  group: string
}

interface Link extends d3.SimulationLinkDatum<Node> {
  source: string | Node
  target: string | Node
}

interface D3DagProps {
  nodes: Node[]
  links: Link[]
  activeNodeId: string | null
}

export function D3Dag({ nodes, links, activeNodeId }: D3DagProps) {
  const ref = React.useRef<SVGSVGElement>(null)
  const { theme } = useTheme()

  React.useEffect(() => {
    const svg = d3.select(ref.current)
    if (!svg || !nodes || !links) return

    const width = 520
    const height = 420
    svg.attr("width", "100%").attr("height", "100%").attr("viewBox", [0, 0, width, height])

    // Fix positions for User and Host Agent
    nodes.forEach((node) => {
      if (node.group === "user") {
        node.fx = width / 2
        node.fy = 50 // Top center
      } else if (node.group === "host") {
        node.fx = width / 2
        node.fy = height / 2 + 40 // Slightly lower to give breathing room
      }
    })

    // Arrange agent nodes in an ellipse around the Host Agent
    const agentNodes = nodes.filter((node) => node.group === "agent")
    if (agentNodes.length > 0) {
      const radiusX = Math.max(140, Math.min(width, height) / 2 - 80)
      const radiusY = Math.max(100, Math.min(width, height) / 2 - 120)
      const angleStep = (2 * Math.PI) / agentNodes.length

      agentNodes.forEach((node, index) => {
        const angle = -Math.PI / 2 + index * angleStep // Start at top
        node.fx = width / 2 + radiusX * Math.cos(angle)
        node.fy = height / 2 + 40 + radiusY * Math.sin(angle)
      })
    }

    const simulation = d3
      .forceSimulation(nodes)
      .force(
        "link",
        d3
          .forceLink<Node, Link>(links)
          .id((d) => d.id)
          .distance(140)
          .strength(0.4),
      )
      .force("charge", d3.forceManyBody().strength(-120))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide().radius(45))
      .alphaDecay(0.12)

    svg.selectAll("*").remove() // Clear previous render

    const link = svg
      .append("g")
      .attr("stroke", "hsl(var(--border))")
      .attr("stroke-opacity", 0.35)
      .selectAll("line")
      .data(links)
      .join("line")
      .attr("stroke-width", 2)

    const node = svg.append("g").selectAll("g").data(nodes).join("g").call(drag(simulation))

    node
      .append("circle")
      .attr("r", (d) => {
        if (d.group === "user") return 25
        if (d.group === "host") return 35
        return 28 // agents
      })
      .attr("stroke", theme === "dark" ? "hsl(var(--background))" : "hsl(var(--foreground))")
      .attr("stroke-width", 2)
      .attr("fill", (d) => {
        if (d.group === "user") return "hsl(220 70% 50%)" // Blue
        if (d.group === "host") return "hsl(142 76% 36%)" // Green
        return "hsl(var(--primary))" // Default for agents
      })

    node
      .append("text")
      .attr("text-anchor", "middle")
      .attr("dy", "0.35em")
      .attr("fill", "white")
      .attr("font-size", "10px")
      .attr("font-weight", "600")
      .style("pointer-events", "none")
      .each(function(d) {
        const text = d3.select(this)
        const words = d.id.split(/\s+/)
        
        if (words.length > 2 || d.id.length > 15) {
          // Multi-line text for long names
          text.text("")
          words.forEach((word, i) => {
            text.append("tspan")
              .attr("x", 0)
              .attr("dy", i === 0 ? "-0.3em" : "1.1em")
              .text(word.length > 12 ? word.substring(0, 10) + "..." : word)
          })
        } else {
          text.text(d.id)
        }
      })

    simulation.on("tick", () => {
      link
        .attr("x1", (d) => (d.source as Node).x!)
        .attr("y1", (d) => (d.source as Node).y!)
        .attr("x2", (d) => (d.target as Node).x!)
        .attr("y2", (d) => (d.target as Node).y!)

      node.attr("transform", (d) => `translate(${d.x},${d.y})`)
    })

    function drag(simulation: d3.Simulation<Node, undefined>) {
      function dragstarted(event: d3.D3DragEvent<SVGGElement, Node, Node>) {
        if (!event.active) simulation.alphaTarget(0.3).restart()
        event.subject.fx = event.subject.x
        event.subject.fy = event.subject.y
      }
      function dragged(event: d3.D3DragEvent<SVGGElement, Node, Node>) {
        event.subject.fx = event.x
        event.subject.fy = event.y
      }
      function dragended(event: d3.D3DragEvent<SVGGElement, Node, Node>) {
        if (!event.active) simulation.alphaTarget(0)
        event.subject.fx = null
        event.subject.fy = null
      }
      return d3.drag<SVGGElement, Node>().on("start", dragstarted).on("drag", dragged).on("end", dragended)
    }

    return () => {
      simulation.stop()
    }
  }, [nodes, links, theme])

  React.useEffect(() => {
    const svg = d3.select(ref.current)
    svg
      .selectAll("circle")
      .transition()
      .duration(300)
      .attr("r", (d) => {
        const node = d as Node
        const baseSize = node.group === "user" ? 25 : node.group === "host" ? 35 : 28
        return node.id === activeNodeId ? baseSize + 5 : baseSize
      })
      .attr("stroke-width", (d) => ((d as Node).id === activeNodeId ? 3 : 2))
      .style("filter", (d) => ((d as Node).id === activeNodeId ? "url(#glow)" : null))
  }, [activeNodeId])

  return (
    <div className="w-full flex justify-center">
      <svg ref={ref}>
        <defs>
          <filter id="glow">
            <feGaussianBlur stdDeviation="3.5" result="coloredBlur" />
            <feMerge>
              <feMergeNode in="coloredBlur" />
              <feMergeNode in="SourceGraphic" />
            </feMerge>
          </filter>
        </defs>
      </svg>
    </div>
  )
}
