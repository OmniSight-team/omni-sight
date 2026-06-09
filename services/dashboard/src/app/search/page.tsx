"use client"

import { useRef, useState } from "react"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { Badge } from "@/components/ui/badge"
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
} from "@/components/ui/dialog"
import { Search, Loader2, Video, Clock, Tag, Layers } from "lucide-react"
import { toast } from "sonner"
import Link from "next/link"

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"

/** Clips within this many seconds of the cluster seed are merged. */
const CLUSTER_WINDOW_SEC = 1.5

type SearchResult = {
  frame_id: string
  score: number
  timestamp: string   // frame index as string
  camera_id: string   // source_id of the upload
  source_id: string
  fps: number
  thumb: string
}

type Cluster = {
  best: SearchResult   // highest-scoring frame — shown as thumbnail
  members: SearchResult[]
}

const CAMERA_OPTIONS = ["All cameras", "cam-01", "cam-02", "cam-03", "cam-04"]
const DATE_OPTIONS   = ["Any time", "Today", "Last 7 days", "Last 30 days"]
const DOMAIN_OPTIONS = ["All domains", "Security", "Safety", "Operations"]

/** Group results by source + temporal proximity. Returns one cluster per distinct moment. */
function clusterResults(results: SearchResult[]): Cluster[] {
  const sorted = [...results].sort((a, b) => b.score - a.score)
  const used = new Set<string>()
  const clusters: Cluster[] = []

  for (const best of sorted) {
    if (used.has(best.frame_id)) continue
    const bestSec = parseFloat(best.timestamp) || 0
    const members: SearchResult[] = [best]
    used.add(best.frame_id)

    for (const other of sorted) {
      if (used.has(other.frame_id)) continue
      if (other.source_id !== best.source_id) continue
      const otherSec = parseFloat(other.timestamp) || 0
      if (Math.abs(otherSec - bestSec) <= CLUSTER_WINDOW_SEC) {
        members.push(other)
        used.add(other.frame_id)
      }
    }

    clusters.push({ best, members })
  }

  return clusters
}

function formatTime(timestamp: string): string {
  const secs = parseFloat(timestamp) || 0
  const m = Math.floor(secs / 60)
  const s = Math.floor(secs % 60)
  return `${m}:${s.toString().padStart(2, "0")}`
}

function VideoPlayer({ sourceId, timestamp }: { sourceId: string; timestamp: string }) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const targetSec = parseFloat(timestamp) || 0
  // Browsers snap #t= to the nearest preceding keyframe. Seeking via
  // currentTime after metadata loads is more precise — we still nudge
  // +0.1 s to land on a decoded frame rather than the keyframe boundary.
  const seekSec = targetSec + 0.1

  function handleLoadedMetadata() {
    const el = videoRef.current
    if (el) el.currentTime = seekSec
  }

  return (
    <video
      ref={videoRef}
      src={`${API_URL}/video/${sourceId}#t=${seekSec.toFixed(3)}`}
      controls
      playsInline
      className="w-full rounded-lg border border-border bg-black"
      onLoadedMetadata={handleLoadedMetadata}
    />
  )
}

export default function SearchPage() {
  const [query, setQuery] = useState("")
  const [isSearching, setIsSearching] = useState(false)
  const [clusters, setClusters] = useState<Cluster[]>([])
  const [hasSearched, setHasSearched] = useState(false)
  const [camera, setCamera] = useState(CAMERA_OPTIONS[0])
  const [date, setDate] = useState(DATE_OPTIONS[0])
  const [domain, setDomain] = useState(DOMAIN_OPTIONS[0])
  const [selected, setSelected] = useState<Cluster | null>(null)

  async function handleSearch() {
    if (!query.trim()) return
    setIsSearching(true)
    setHasSearched(true)
    try {
      const res = await fetch(`${API_URL}/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: query.trim(), limit: 32 }),
      })
      if (!res.ok) throw new Error(await res.text())
      const data: { results: SearchResult[] } = await res.json()
      const grouped = clusterResults(data.results)
      setClusters(grouped)
      if (grouped.length === 0) toast.info("No matching clips found.")
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
          Search indexed footage by natural-language description.
        </p>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Search Footage</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground -mt-1">
            No video indexed yet?{" "}
            <Link href="/upload" className="text-primary underline underline-offset-2">
              Upload one first.
            </Link>
          </p>

          {/* Search bar */}
          <div className="flex gap-2">
            <Input
              placeholder='e.g. "person leaving a bag on a bench"'
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

          {/* Filters */}
          <div className="flex flex-wrap gap-2">
            {[
              { label: "Camera", value: camera, options: CAMERA_OPTIONS, setter: setCamera },
              { label: "Date",   value: date,   options: DATE_OPTIONS,   setter: setDate },
              { label: "Domain", value: domain, options: DOMAIN_OPTIONS, setter: setDomain },
            ].map(({ label, value, options, setter }) => (
              <div key={label} className="flex items-center gap-1.5">
                <span className="text-xs text-muted-foreground">{label}:</span>
                <select
                  value={value}
                  onChange={(e) => setter(e.target.value)}
                  className="text-xs bg-muted border border-border rounded-md px-2 py-1 text-foreground outline-none focus:ring-1 focus:ring-ring cursor-pointer"
                >
                  {options.map((o) => (
                    <option key={o} value={o}>{o}</option>
                  ))}
                </select>
              </div>
            ))}
          </div>

          {/* Clustered results */}
          {clusters.length > 0 && (
            <>
              <p className="text-xs text-muted-foreground">
                {clusters.length} distinct moment{clusters.length !== 1 ? "s" : ""} found
                {clusters.reduce((n, c) => n + c.members.length, 0) > clusters.length && (
                  <> · {clusters.reduce((n, c) => n + c.members.length, 0)} total frames clustered</>
                )}
              </p>
              <div className="grid grid-cols-3 gap-3 lg:grid-cols-4">
                {clusters.map((cluster) => (
                  <button
                    key={cluster.best.frame_id}
                    className="rounded-lg overflow-hidden border border-border bg-muted text-left hover:ring-1 hover:ring-primary transition-all group"
                    onClick={() => setSelected(cluster)}
                  >
                    {cluster.best.thumb ? (
                      // eslint-disable-next-line @next/next/no-img-element
                      <img
                        src={`data:image/jpeg;base64,${cluster.best.thumb}`}
                        alt={`Frame at t=${cluster.best.timestamp}`}
                        className="w-full aspect-video object-cover group-hover:opacity-90 transition-opacity"
                      />
                    ) : (
                      <div className="w-full aspect-video flex items-center justify-center">
                        <Video className="size-5 text-muted-foreground" />
                      </div>
                    )}
                    <div className="px-2 py-1.5 text-xs text-muted-foreground space-y-0.5">
                      <div className="flex items-center justify-between">
                        <span className="flex items-center gap-1">
                          <Tag className="size-2.5" />
                          <span className="font-mono text-[10px]">{cluster.best.source_id.slice(0, 8)}</span>
                        </span>
                        <span className="font-mono text-foreground font-medium">
                          {cluster.best.score.toFixed(2)}
                        </span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="flex items-center gap-1">
                          <Clock className="size-2.5" />
                          {formatTime(cluster.best.timestamp)}
                        </span>
                        {cluster.members.length > 1 && (
                          <Badge variant="secondary" className="text-[9px] px-1 py-0 h-4 gap-0.5">
                            <Layers className="size-2.5" />
                            {cluster.members.length}
                          </Badge>
                        )}
                      </div>
                    </div>
                  </button>
                ))}
              </div>
            </>
          )}

          {hasSearched && clusters.length === 0 && !isSearching && (
            <p className="text-sm text-center text-muted-foreground py-8">
              No results — try a different description or upload more footage.
            </p>
          )}
        </CardContent>
      </Card>

      {/* Clip playback dialog */}
      <Dialog open={!!selected} onOpenChange={(o) => { if (!o) setSelected(null) }}>
        <DialogContent className="sm:max-w-xl">
          {selected && (
            <>
              <DialogHeader>
                <DialogTitle>Clip Preview</DialogTitle>
                <div className="flex items-center gap-3 text-xs text-muted-foreground pt-0.5">
                  <span className="flex items-center gap-1">
                    <Tag className="size-3" />
                    <span className="font-mono">{selected.best.source_id.slice(0, 8)}</span>
                  </span>
                  <span className="flex items-center gap-1">
                    <Clock className="size-3" />
                    {formatTime(selected.best.timestamp)}
                  </span>
                  <span className="font-mono">score {selected.best.score.toFixed(3)}</span>
                  {selected.members.length > 1 && (
                    <span className="text-muted-foreground">
                      ({selected.members.length} frames in this moment)
                    </span>
                  )}
                </div>
              </DialogHeader>

              <VideoPlayer
                sourceId={selected.best.source_id}
                timestamp={selected.best.timestamp}
              />

              {/* Filmstrip of all frames in this cluster */}
              {selected.members.length > 1 && (
                <div className="space-y-1.5">
                  <p className="text-xs text-muted-foreground">Frames in this moment</p>
                  <div className="flex gap-2 overflow-x-auto pb-1">
                    {selected.members.map((m) => (
                      <div
                        key={m.frame_id}
                        className="shrink-0 rounded overflow-hidden border border-border cursor-pointer hover:ring-1 hover:ring-primary"
                        style={{ width: 96, height: 54 }}
                        onClick={() => setSelected({ ...selected, best: m })}
                      >
                        {m.thumb ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img
                            src={`data:image/jpeg;base64,${m.thumb}`}
                            alt=""
                            className="w-full h-full object-cover"
                          />
                        ) : (
                          <div className="w-full h-full bg-muted flex items-center justify-center">
                            <Video className="size-3 text-muted-foreground" />
                          </div>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
