"use client"

import { useState, useRef } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Badge } from "@/components/ui/badge"
import { Upload, Loader2, FileVideo, X, CheckCircle2, Search } from "lucide-react"
import { toast } from "sonner"
import Link from "next/link"
import { buttonVariants } from "@/components/ui/button"
import { useUploadStore, type QueueStatus } from "@/lib/upload-store"

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

const STATUS_BADGE: Record<QueueStatus, "secondary" | "outline" | "default" | "destructive"> = {
  uploading:  "secondary",
  indexing:   "outline",
  searchable: "default",
  error:      "destructive",
}

export default function UploadPage() {
  const { queue, addItem, updateItem } = useUploadStore()
  const [file, setFile] = useState<File | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [isIndexing, setIsIndexing] = useState(false)
  const [progress, setProgress] = useState<number | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  function handleFileSelect(f: File) {
    if (!f.type.startsWith("video/")) {
      toast.error("Please select a video file.")
      return
    }
    setFile(f)
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setIsDragging(false)
    const f = e.dataTransfer.files[0]
    if (f) handleFileSelect(f)
  }

  async function handleIngest() {
    if (!file) return

    const id = `${Date.now()}`
    addItem({ id, name: file.name, status: "uploading", progress: 0, indexed: null })
    setIsIndexing(true)
    setProgress(0)
    setFile(null)

    const fd = new FormData()
    fd.append("video", file)

    try {
      updateItem(id, { status: "indexing" })
      const res = await fetch(`${API_URL}/ingest`, { method: "POST", body: fd })
      if (!res.ok) throw new Error(await res.text())

      const reader = res.body!.getReader()
      const decoder = new TextDecoder()

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        const text = decoder.decode(value, { stream: true })
        for (const line of text.split("\n")) {
          if (!line.startsWith("data: ")) continue
          const data = JSON.parse(line.slice(6))
          setProgress(data.progress)
          updateItem(id, { progress: data.progress })
          if (data.done) {
            if (data.error) {
              updateItem(id, { status: "error" })
              toast.error(`Indexing failed: ${data.error}`)
            } else if (data.indexed === 0) {
              updateItem(id, { status: "searchable", indexed: 0, progress: 100 })
              toast.warning("No frames admitted. Try a video with more motion.")
            } else {
              updateItem(id, { status: "searchable", indexed: data.indexed, progress: 100 })
              toast.success(`${data.indexed} frames indexed — ready to search.`)
            }
          }
        }
      }
    } catch (err) {
      updateItem(id, { status: "error" })
      toast.error(`Ingestion failed: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setIsIndexing(false)
      setProgress(null)
    }
  }

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Upload</h1>
        <p className="text-sm text-muted-foreground">
          Index a video file into the searchable archive.
        </p>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Video File</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {/* Drop zone */}
          <div
            role="button"
            tabIndex={0}
            aria-label="Select video file"
            className={[
              "border-2 border-dashed rounded-xl p-8 text-center transition-colors cursor-pointer outline-none",
              "focus-visible:ring-2 focus-visible:ring-ring",
              isDragging
                ? "border-primary bg-primary/5"
                : "border-border hover:border-primary/40",
            ].join(" ")}
            onDragOver={(e) => { e.preventDefault(); setIsDragging(true) }}
            onDragLeave={() => setIsDragging(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            onKeyDown={(e) => e.key === "Enter" && fileInputRef.current?.click()}
          >
            <input
              ref={fileInputRef}
              type="file"
              accept="video/*"
              className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) handleFileSelect(f) }}
            />
            {file ? (
              <div className="flex items-center justify-center gap-2">
                <FileVideo className="size-5 text-primary" />
                <span className="text-sm font-medium">{file.name}</span>
                <button
                  type="button"
                  aria-label="Remove file"
                  className="ml-2 text-muted-foreground hover:text-foreground transition-colors"
                  onClick={(e) => { e.stopPropagation(); setFile(null) }}
                >
                  <X className="size-4" />
                </button>
              </div>
            ) : (
              <div className="space-y-2">
                <Upload className="size-8 mx-auto text-muted-foreground" />
                <p className="text-sm text-muted-foreground">
                  Drag &amp; drop a video or{" "}
                  <span className="text-primary underline underline-offset-2">browse</span>
                </p>
                <p className="text-xs text-muted-foreground">MP4 · AVI · MOV · MKV</p>
              </div>
            )}
          </div>

          <Button onClick={handleIngest} disabled={!file || isIndexing} className="w-full">
            {isIndexing ? (
              <><Loader2 className="size-4 animate-spin" /> Indexing — please wait…</>
            ) : (
              <><Upload className="size-4" /> Index Video</>
            )}
          </Button>

          {progress !== null && (
            <div className="space-y-1.5">
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>Indexing frames…</span>
                <span>{progress}%</span>
              </div>
              <div className="w-full h-1.5 rounded-full bg-muted overflow-hidden">
                <div
                  className="h-full bg-primary rounded-full transition-all duration-300"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Queue */}
      {queue.length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Queue</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <ul className="divide-y divide-border">
              {queue.map((item) => (
                <li key={item.id} className="flex items-center gap-3 px-4 py-3">
                  {item.status === "searchable" ? (
                    <CheckCircle2 className="size-4 text-green-400 shrink-0" />
                  ) : item.status === "error" ? (
                    <X className="size-4 text-destructive shrink-0" />
                  ) : (
                    <Loader2 className="size-4 text-muted-foreground animate-spin shrink-0" />
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm truncate">{item.name}</p>
                    {item.status === "indexing" && item.progress > 0 && (
                      <div className="mt-1 w-full h-1 rounded-full bg-muted overflow-hidden">
                        <div
                          className="h-full bg-primary rounded-full transition-all"
                          style={{ width: `${item.progress}%` }}
                        />
                      </div>
                    )}
                    {item.status === "searchable" && item.indexed !== null && (
                      <p className="text-[10px] text-muted-foreground mt-0.5">
                        {item.indexed} frames indexed
                      </p>
                    )}
                  </div>
                  <Badge variant={STATUS_BADGE[item.status]} className="text-[10px] shrink-0">
                    {item.status}
                  </Badge>
                  {item.status === "searchable" && (
                    <Link
                    href="/search"
                    className={buttonVariants({ variant: "ghost", size: "sm", className: "h-7 text-xs gap-1 shrink-0" })}
                  >
                    <Search className="size-3" /> Search
                  </Link>
                  )}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
