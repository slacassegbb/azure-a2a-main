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

    const width = 500
    const height = 400
    svg.attr("width", "100%").attr("height", "100%").attr("viewBox", [0, 0, width, height])

    const simulation = d3
      .forceSimulation(nodes)
      .force(
        "link",
        d3
          .forceLink<Node, Link>(links)
          .id((d) => d.id)
          .distance(100),
      )
      .force("charge", d3.forceManyBody().strength(-250))
      .force("center", d3.forceCenter(width / 2, height / 2))

    svg.selectAll("*").remove() // Clear previous render

    const link = svg
      .append("g")
      .attr("stroke", "hsl(var(--border))")
      .attr("stroke-opacity", 0.6)
      .selectAll("line")
      .data(links)
      .join("line")
      .attr("stroke-width", 2)

    const node = svg.append("g").selectAll("g").data(nodes).join("g").call(drag(simulation))

    node
      .append("circle")
      .attr("r", 20)
      .attr("stroke", theme === "dark" ? "hsl(var(--background))" : "hsl(var(--foreground))")
      .attr("stroke-width", 1.5)
      .attr("fill", "hsl(var(--primary))")

    node
      .append("text")
      .attr("text-anchor", "middle")
      .attr("dy", "0.35em")
      .attr("fill", "hsl(var(--primary-foreground))")
      .attr("font-size", "8px")
      .text((d) => d.id)

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
      .attr("r", (d) => ((d as Node).id === activeNodeId ? 25 : 20))
      .attr("fill", (d) => ((d as Node).id === activeNodeId ? "hsl(var(--accent))" : "hsl(var(--primary))"))
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
