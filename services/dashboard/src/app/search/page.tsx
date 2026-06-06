"use client"

import { useState, useRef } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Upload, Search, Loader2, FileVideo, X } from "lucide-react"
import { toast } from "sonner"

const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

type SearchResult = {
  frame_id: string
  score: number
  timestamp: string
  camera_id: string
  thumb: string
}

export default function SearchPage() {
  const [file, setFile] = useState<File | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [isIndexing, setIsIndexing] = useState(false)
  const [framesIndexed, setFramesIndexed] = useState<number | null>(null)

  const [query, setQuery] = useState("")
  const [isSearching, setIsSearching] = useState(false)
  const [results, setResults] = useState<SearchResult[]>([])

  const fileInputRef = useRef<HTMLInputElement>(null)

  function handleFileSelect(f: File) {
    if (!f.type.startsWith("video/")) {
      toast.error("Please select a video file.")
      return
    }
    setFile(f)
    setFramesIndexed(null)
    setResults([])
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setIsDragging(false)
    const f = e.dataTransfer.files[0]
    if (f) handleFileSelect(f)
  }

  async function handleIngest() {
    if (!file) return
    setIsIndexing(true)
    const fd = new FormData()
    fd.append("video", file)
    try {
      const res = await fetch(`${API_URL}/ingest`, { method: "POST", body: fd })
      if (!res.ok) throw new Error(await res.text())
      const data: { frames_indexed: number } = await res.json()
      setFramesIndexed(data.frames_indexed)
      if (data.frames_indexed === 0) {
        toast.warning("No frames were admitted by the ROI sampler. Try a video with more motion.")
      } else {
        toast.success(`${data.frames_indexed} frames indexed.`)
      }
    } catch (err) {
      toast.error(`Ingestion failed: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setIsIndexing(false)
    }
  }

  async function handleSearch() {
    if (!query.trim()) return
    setIsSearching(true)
    try {
      const res = await fetch(`${API_URL}/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query.trim(), limit: 12 }),
      })
      if (!res.ok) throw new Error(await res.text())
      const data: { results: SearchResult[] } = await res.json()
      setResults(data.results)
      if (data.results.length === 0) {
        toast.info("No matching frames found.")
      }
    } catch (err) {
      toast.error(`Search failed: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      setIsSearching(false)
    }
  }

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Semantic Search</h1>
        <p className="text-sm text-muted-foreground">
          Upload a video to index with SigLIP2, then search frames by natural language.
        </p>
      </div>

      {/* ── Step 1: Upload ──────────────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle>1. Upload &amp; Index Video</CardTitle>
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
                : "border-border hover:border-primary/50",
            ].join(" ")}
            onDragOver={(e) => {
              e.preventDefault()
              setIsDragging(true)
            }}
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
              onChange={(e) => {
                const f = e.target.files?.[0]
                if (f) handleFileSelect(f)
              }}
            />
            {file ? (
              <div className="flex items-center justify-center gap-2">
                <FileVideo className="size-5 text-primary" />
                <span className="text-sm font-medium">{file.name}</span>
                <button
                  type="button"
                  aria-label="Remove file"
                  className="ml-2 text-muted-foreground hover:text-foreground transition-colors"
                  onClick={(e) => {
                    e.stopPropagation()
                    setFile(null)
                    setFramesIndexed(null)
                    setResults([])
                  }}
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
                <p className="text-xs text-muted-foreground">MP4, AVI, MOV, MKV</p>
              </div>
            )}
          </div>

          <Button
            onClick={handleIngest}
            disabled={!file || isIndexing}
            className="w-full"
          >
            {isIndexing ? (
              <>
                <Loader2 className="size-4 animate-spin" />
                Indexing — this may take a moment…
              </>
            ) : (
              <>
                <Upload className="size-4" />
                Index Video
              </>
            )}
          </Button>

          {framesIndexed !== null && (
            <p className="text-sm text-center text-green-600 dark:text-green-400">
              {framesIndexed} frame{framesIndexed !== 1 ? "s" : ""} indexed and ready to search.
            </p>
          )}
        </CardContent>
      </Card>

      {/* ── Step 2: Search ──────────────────────────────────── */}
      <Card>
        <CardHeader>
          <CardTitle>2. Search by Text</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="flex gap-2">
            <Input
              placeholder='e.g. "person walking near a door"'
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && !isSearching && handleSearch()}
              disabled={isSearching}
            />
            <Button
              onClick={handleSearch}
              disabled={!query.trim() || isSearching}
              size="icon"
              aria-label="Search"
            >
              {isSearching ? (
                <Loader2 className="size-4 animate-spin" />
              ) : (
                <Search className="size-4" />
              )}
            </Button>
          </div>

          {results.length > 0 && (
            <div className="grid grid-cols-3 gap-3 lg:grid-cols-4">
              {results.map((r) => (
                <div
                  key={r.frame_id}
                  className="rounded-lg overflow-hidden border border-border bg-muted"
                >
                  {r.thumb ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={`data:image/jpeg;base64,${r.thumb}`}
                      alt={`Frame at t=${r.timestamp}`}
                      className="w-full aspect-video object-cover"
                    />
                  ) : (
                    <div className="w-full aspect-video flex items-center justify-center">
                      <span className="text-xs text-muted-foreground">No preview</span>
                    </div>
                  )}
                  <div className="px-2 py-1.5 text-xs text-muted-foreground space-y-0.5">
                    <div>Score: <span className="text-foreground font-medium">{r.score}</span></div>
                    <div>t = {r.timestamp}</div>
                  </div>
                </div>
              ))}
            </div>
          )}

          {results.length === 0 && !isSearching && query && (
            <p className="text-sm text-center text-muted-foreground py-6">
              No results yet — try searching after indexing a video.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
