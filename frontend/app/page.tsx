import { ChatLayout } from "@/components/chat-layout"
import { Suspense } from "react"

function Loading() {
  return (
    <div className="h-screen flex items-center justify-center">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
    </div>
  )
}

export default function Home() {
  return (
    <div className="h-screen">
      <Suspense fallback={<Loading />}>
        <ChatLayout />
      </Suspense>
    </div>
  )
}
