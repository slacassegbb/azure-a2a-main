import { ChatLayout } from "@/components/chat-layout"

export default function Home() {
  // Using a div here to ensure it fills the full height of the viewport.
  return (
    <div className="h-screen">
      <ChatLayout />
    </div>
  )
}
