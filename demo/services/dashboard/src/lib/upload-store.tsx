"use client"

import { createContext, useContext, useState, type ReactNode } from "react"

export type QueueStatus = "uploading" | "indexing" | "searchable" | "error"

export type QueueItem = {
  id: string
  name: string
  status: QueueStatus
  progress: number
  indexed: number | null
}

type UploadCtx = {
  queue: QueueItem[]
  addItem: (item: QueueItem) => void
  updateItem: (id: string, patch: Partial<QueueItem>) => void
}

const UploadContext = createContext<UploadCtx | null>(null)

export function UploadProvider({ children }: { children: ReactNode }) {
  const [queue, setQueue] = useState<QueueItem[]>([])

  function addItem(item: QueueItem) {
    setQueue((prev) => [item, ...prev])
  }

  function updateItem(id: string, patch: Partial<QueueItem>) {
    setQueue((prev) => prev.map((q) => q.id === id ? { ...q, ...patch } : q))
  }

  return (
    <UploadContext.Provider value={{ queue, addItem, updateItem }}>
      {children}
    </UploadContext.Provider>
  )
}

export function useUploadStore() {
  const ctx = useContext(UploadContext)
  if (!ctx) throw new Error("useUploadStore must be used within UploadProvider")
  return ctx
}
