import { ChatLayout } from "@/components/chat-layout"

// Force dynamic rendering since we use searchParams in child components
export const dynamic = 'force-dynamic'

export default function Home() {
  // Using a div here to ensure it fills the full height of the viewport.
  return (
    <div className="h-screen">
      <ChatLayout />
    </div>
  )
}
