"use client"

import { useState } from "react"
import { Card, CardContent } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter,
} from "@/components/ui/dialog"
import {
  AlertTriangle, ShieldAlert, Info, CheckCheck, X, FileText,
  Clock, Video, ChevronRight, Bot,
} from "lucide-react"
import Link from "next/link"
import { buttonVariants } from "@/components/ui/button"

type Domain = "Security" | "Safety" | "Operations"
type Severity = "critical" | "warning" | "info"
type Status = "open" | "confirmed" | "dismissed"

type Alert = {
  id: string
  severity: Severity
  domain: Domain
  event: string
  camera: string
  time: string
  eta: string
  confidence: number
  status: Status
  trace: string[]
}

const INITIAL: Alert[] = [
  {
    id: "a1",
    severity: "critical",
    domain: "Security",
    event: "Unattended object detected",
    camera: "cam-01",
    time: "09:12",
    eta: "~2 min",
    confidence: 94,
    status: "open",
    trace: [
      "[Tier 1 — PFM] Motion anomaly flagged at t=09:12:01 on cam-01.",
      "[Tier 2 — SigLIP2] Embedding matched 'unattended-object' cluster (cosine 0.94).",
      "[Tier 3 — VLM] \"A backpack-like object left unattended for >60 s near the entrance.\"",
      "[Policy] Severity: CRITICAL — exceeds Security domain threshold.",
    ],
  },
  {
    id: "a2",
    severity: "critical",
    domain: "Safety",
    event: "Emergency exit blocked",
    camera: "cam-02",
    time: "09:05",
    eta: "Immediate",
    confidence: 91,
    status: "open",
    trace: [
      "[Tier 1 — PFM] Static obstruction detected at cam-02 exit corridor.",
      "[Tier 2 — SigLIP2] Matched 'blocked-exit' cluster (cosine 0.91).",
      "[Tier 3 — VLM] \"Large boxes stacked against fire exit door — exit appears impassable.\"",
      "[Policy] Severity: CRITICAL — zero-tolerance Safety rule triggered.",
    ],
  },
  {
    id: "a3",
    severity: "warning",
    domain: "Operations",
    event: "Vehicle in restricted zone",
    camera: "cam-04",
    time: "08:54",
    eta: "~3 min",
    confidence: 82,
    status: "open",
    trace: [
      "[Tier 1 — PFM] Vehicle-class object motion detected inside loading bay perimeter.",
      "[Tier 2 — SigLIP2] Matched 'vehicle-restricted' cluster (cosine 0.82).",
      "[Tier 3 — VLM] \"A forklift operating in a pedestrian-only marked zone.\"",
      "[Policy] Severity: WARNING — Operations zone violation detected.",
    ],
  },
  {
    id: "a4",
    severity: "warning",
    domain: "Security",
    event: "Motion outside business hours",
    camera: "cam-04",
    time: "08:42",
    eta: "—",
    confidence: 78,
    status: "open",
    trace: [
      "[Tier 1 — PFM] Human-class motion detected at 06:42 (off-hours window).",
      "[Tier 2 — SigLIP2] Matched 'after-hours-presence' cluster (cosine 0.78).",
      "[Tier 3 — VLM] \"One individual moving through loading bay before shift start.\"",
      "[Policy] Severity: WARNING — Security temporal rule triggered.",
    ],
  },
  {
    id: "a5",
    severity: "warning",
    domain: "Safety",
    event: "Slip/fall risk — wet surface",
    camera: "cam-02",
    time: "08:31",
    eta: "~8 min",
    confidence: 76,
    status: "open",
    trace: [
      "[Tier 1 — PFM] Reflective surface anomaly detected near cam-02 walkway.",
      "[Tier 2 — SigLIP2] Matched 'wet-floor-hazard' cluster (cosine 0.76).",
      "[Tier 3 — VLM] \"Water pooling visible on floor tiles — no wet-floor sign present.\"",
      "[Policy] Severity: WARNING — Safety hazard reporting threshold met.",
    ],
  },
  {
    id: "a6",
    severity: "info",
    domain: "Operations",
    event: "Camera 3 connectivity loss",
    camera: "cam-03",
    time: "07:30",
    eta: "—",
    confidence: 100,
    status: "open",
    trace: [
      "[System] Heartbeat timeout from cam-03 at 07:30:00.",
      "[System] No stream data received for >30 s.",
      "[System] Camera marked offline; recordings paused.",
      "[Policy] Severity: INFO — monitoring gap logged.",
    ],
  },
]

const SEVERITY_ICON: Record<Severity, React.ReactNode> = {
  critical: <ShieldAlert   className="size-4 text-destructive mt-0.5 shrink-0" />,
  warning:  <AlertTriangle className="size-4 text-yellow-500 mt-0.5 shrink-0" />,
  info:     <Info          className="size-4 text-blue-400 mt-0.5 shrink-0" />,
}

const SEVERITY_BADGE: Record<Severity, "destructive" | "outline" | "secondary"> = {
  critical: "destructive",
  warning: "outline",
  info: "secondary",
}

const DOMAIN_COLOR: Record<Domain, string> = {
  Security:   "text-red-400",
  Safety:     "text-yellow-400",
  Operations: "text-blue-400",
}

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<Alert[]>(INITIAL)
  const [selected, setSelected] = useState<Alert | null>(null)

  function confirm(id: string) {
    setAlerts((prev) => prev.map((a) => a.id === id ? { ...a, status: "confirmed" } : a))
    setSelected((prev) => prev?.id === id ? { ...prev, status: "confirmed" } : prev)
  }

  function dismiss(id: string) {
    setAlerts((prev) => prev.map((a) => a.id === id ? { ...a, status: "dismissed" } : a))
    setSelected((prev) => prev?.id === id ? { ...prev, status: "dismissed" } : prev)
  }

  const open     = alerts.filter((a) => a.status === "open")
  const resolved = alerts.filter((a) => a.status !== "open")

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Alerts</h1>
        <p className="text-sm text-muted-foreground">
          Predictive alerts across Security, Safety, and Operations domains.
        </p>
      </div>

      {/* Open alerts */}
      {open.length > 0 && (
        <Card>
          <CardContent className="pt-1 pb-0">
            <ul className="divide-y divide-border">
              {open.map((a) => (
                <li
                  key={a.id}
                  className="flex items-center gap-3 py-3.5 cursor-pointer hover:bg-muted/30 -mx-6 px-6 transition-colors"
                  onClick={() => setSelected(a)}
                >
                  {SEVERITY_ICON[a.severity]}
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium">{a.event}</p>
                    <p className="text-xs text-muted-foreground mt-0.5">
                      <span className={DOMAIN_COLOR[a.domain]}>{a.domain}</span>
                      {" · "}{a.camera}{" · "}{a.time}
                      {a.eta !== "—" && <> · ETA <span className="text-foreground">{a.eta}</span></>}
                    </p>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <Badge variant={SEVERITY_BADGE[a.severity]}>{a.severity}</Badge>
                    <span className="text-xs text-muted-foreground font-mono">{a.confidence}%</span>
                    <ChevronRight className="size-4 text-muted-foreground" />
                  </div>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {open.length === 0 && (
        <Card>
          <CardContent className="py-8 text-center text-sm text-muted-foreground">
            No open alerts.
          </CardContent>
        </Card>
      )}

      {/* Resolved alerts */}
      {resolved.length > 0 && (
        <div className="space-y-2">
          <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Resolved</p>
          <Card>
            <CardContent className="pt-1 pb-0">
              <ul className="divide-y divide-border">
                {resolved.map((a) => (
                  <li key={a.id} className="flex items-center gap-3 py-3 opacity-55">
                    {SEVERITY_ICON[a.severity]}
                    <div className="flex-1 min-w-0">
                      <p className="text-sm line-through">{a.event}</p>
                      <p className="text-xs text-muted-foreground">{a.camera} · {a.time}</p>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <Badge variant="secondary">{a.status}</Badge>
                      {a.status === "confirmed" && (
                        <Link
                          href="/forensic"
                          className={buttonVariants({ variant: "outline", size: "sm", className: "h-7 text-xs gap-1" })}
                        >
                          <FileText className="size-3" /> Dossier
                        </Link>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Alert detail dialog */}
      <Dialog open={!!selected} onOpenChange={(o) => { if (!o) setSelected(null) }}>
        <DialogContent className="sm:max-w-lg">
          {selected && (
            <>
              <DialogHeader>
                <div className="flex items-center gap-2 mb-1">
                  <Badge variant={SEVERITY_BADGE[selected.severity]}>{selected.severity}</Badge>
                  <span className={`text-xs font-medium ${DOMAIN_COLOR[selected.domain]}`}>
                    {selected.domain}
                  </span>
                </div>
                <DialogTitle>{selected.event}</DialogTitle>
                <div className="flex items-center gap-3 text-xs text-muted-foreground pt-1">
                  <span className="flex items-center gap-1"><Video className="size-3" />{selected.camera}</span>
                  <span className="flex items-center gap-1"><Clock className="size-3" />{selected.time}</span>
                  <span className="font-mono">{selected.confidence}% confidence</span>
                </div>
              </DialogHeader>

              {/* Triggering clip placeholder */}
              <div className="rounded-lg bg-muted border border-border aspect-video flex items-center justify-center">
                <div className="text-center space-y-1">
                  <Video className="size-6 text-muted-foreground mx-auto" />
                  <p className="text-xs text-muted-foreground">{selected.camera} · t={selected.time}</p>
                </div>
              </div>

              {/* Verification reasoning trace */}
              <div className="space-y-2">
                <div className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  <Bot className="size-3.5" />
                  Verification Trace
                </div>
                <ol className="space-y-1.5">
                  {selected.trace.map((step, i) => (
                    <li key={i} className="flex gap-2 text-xs">
                      <span className="shrink-0 size-4 rounded-full bg-muted border border-border flex items-center justify-center text-[9px] font-mono text-muted-foreground mt-0.5">
                        {i + 1}
                      </span>
                      <span className="text-muted-foreground leading-relaxed">{step}</span>
                    </li>
                  ))}
                </ol>
              </div>

              <DialogFooter>
                {selected.status === "open" ? (
                  <>
                    <Button
                      size="sm"
                      variant="outline"
                      className="gap-1.5 text-muted-foreground"
                      onClick={() => dismiss(selected.id)}
                    >
                      <X className="size-3.5" /> Dismiss
                    </Button>
                    <Button size="sm" className="gap-1.5" onClick={() => confirm(selected.id)}>
                      <CheckCheck className="size-3.5" /> Confirm
                    </Button>
                  </>
                ) : selected.status === "confirmed" ? (
                  <>
                    <Badge variant="secondary" className="mr-auto">Confirmed</Badge>
                    <Link
                      href="/forensic"
                      className={buttonVariants({ size: "sm", className: "gap-1.5" })}
                    >
                      <FileText className="size-3.5" /> Generate Dossier
                    </Link>
                  </>
                ) : (
                  <Badge variant="secondary" className="mr-auto">Dismissed</Badge>
                )}
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  )
}
