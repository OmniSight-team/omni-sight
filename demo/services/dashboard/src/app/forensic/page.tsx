import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { FileText, Camera, Clock, AlertTriangle, MapPin } from "lucide-react"

const INCIDENT = {
  id: "INC-2024-0047",
  type: "Unattended Object — High Confidence",
  detected: "08:51:03",
  window: "08:51:03 – 08:55:10",
  cameras: ["cam-01", "cam-02", "cam-04"],
  confidence: 94,
  severity: "CRITICAL",
  domain: "Security",
}

type EvtCamera = "cam-01" | "cam-02" | "cam-04"

type TimelineEvent = {
  time: string
  camera: EvtCamera
  description: string
  clip: string
  citation: string
}

const TIMELINE: TimelineEvent[] = [
  {
    time: "08:51:03",
    camera: "cam-01",
    description: "Subject enters frame from the north entrance carrying a backpack.",
    clip: "clip_a1_08-51-03.mp4",
    citation: "CAM-01 · 08:51:03",
  },
  {
    time: "08:52:17",
    camera: "cam-02",
    description: "Subject places backpack on bench and steps back approximately 3 m. Object remains stationary.",
    clip: "clip_a1_08-52-17.mp4",
    citation: "CAM-02 · 08:52:17",
  },
  {
    time: "08:53:44",
    camera: "cam-02",
    description: "Subject leaves the area without retrieving the backpack. Object unattended for >60 s.",
    clip: "clip_a1_08-53-44.mp4",
    citation: "CAM-02 · 08:53:44",
  },
  {
    time: "08:55:10",
    camera: "cam-04",
    description: "Subject re-observed at loading bay — possible secondary exit route taken.",
    clip: "clip_a1_08-55-10.mp4",
    citation: "CAM-04 · 08:55:10",
  },
]

const CAMERA_THUMBS: Record<EvtCamera, string[]> = {
  "cam-01": ["08:51:03", "08:51:28"],
  "cam-02": ["08:52:17", "08:53:44", "08:54:01"],
  "cam-04": ["08:55:10"],
}

const CAMERA_LABEL: Record<EvtCamera, string> = {
  "cam-01": "Entrance",
  "cam-02": "Parking Lot",
  "cam-04": "Loading Bay",
}

function CitationTag({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center gap-1 mx-1 px-1.5 py-0.5 rounded bg-primary/10 border border-primary/20 text-[10px] font-mono text-primary whitespace-nowrap">
      <FileText className="size-2.5" />
      {label}
    </span>
  )
}

export default function ForensicPage() {
  return (
    <div className="p-6 space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold">Forensic Dossier</h1>
          <p className="text-sm text-muted-foreground">
            Evidence-grounded incident report — every claim cited to a specific clip.
          </p>
        </div>
        <div className="flex flex-col items-end gap-1">
          <Badge variant="destructive">Confirmed Alert #a1</Badge>
          <span className="text-[10px] text-muted-foreground font-mono">{INCIDENT.id}</span>
        </div>
      </div>

      {/* Incident summary */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="flex items-center gap-2 text-base">
            <AlertTriangle className="size-4 text-destructive" />
            Incident Summary
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-x-8 gap-y-1.5 text-sm">
            {[
              ["Type",             INCIDENT.type],
              ["Severity",         INCIDENT.severity],
              ["Domain",           INCIDENT.domain],
              ["First detected",   INCIDENT.detected],
              ["Time window",      INCIDENT.window],
              ["Cameras involved", INCIDENT.cameras.join(", ")],
              ["Confidence",       `${INCIDENT.confidence}%`],
            ].map(([k, v]) => (
              <div key={k} className="contents">
                <span className="text-muted-foreground">{k}</span>
                <span className="text-foreground font-medium">{v}</span>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Multi-camera timeline */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Multi-Camera Timeline</CardTitle>
        </CardHeader>
        <CardContent>
          <ol className="relative border-l border-border space-y-6 pl-6">
            {TIMELINE.map((evt) => (
              <li key={`${evt.time}-${evt.camera}`} className="relative space-y-1">
                <div className="absolute -left-[1.5625rem] top-0.5 size-3 rounded-full border-2 border-background bg-primary" />
                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                  <span className="flex items-center gap-1"><Clock className="size-3" />{evt.time}</span>
                  <span className="flex items-center gap-1"><Camera className="size-3" />{evt.camera.toUpperCase()}</span>
                  <span className="flex items-center gap-1"><MapPin className="size-3" />{CAMERA_LABEL[evt.camera]}</span>
                </div>
                <p className="text-sm leading-relaxed">
                  {evt.description}
                  <CitationTag label={evt.citation} />
                </p>
                <p className="text-xs text-muted-foreground font-mono flex items-center gap-1 mt-0.5">
                  <FileText className="size-3" />
                  {evt.clip}
                </p>
              </li>
            ))}
          </ol>
        </CardContent>
      </Card>

      {/* Evidence thumbnails grouped by camera */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base">Evidence Thumbnails</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {(Object.keys(CAMERA_THUMBS) as EvtCamera[]).map((cam) => (
            <div key={cam}>
              <div className="flex items-center gap-2 mb-2">
                <Camera className="size-3.5 text-muted-foreground" />
                <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                  {cam.toUpperCase()} — {CAMERA_LABEL[cam]}
                </span>
              </div>
              <div className="flex gap-2 flex-wrap">
                {CAMERA_THUMBS[cam].map((ts) => (
                  <div
                    key={ts}
                    className="relative rounded-lg bg-muted border border-border overflow-hidden"
                    style={{ width: 140, height: 80 }}
                  >
                    <div className="absolute inset-0 flex flex-col items-center justify-center gap-0.5">
                      <FileText className="size-4 text-muted-foreground/50" />
                      <span className="text-[9px] font-mono text-muted-foreground/60">{ts}</span>
                    </div>
                    <div className="absolute bottom-1 right-1.5">
                      <CitationTag label={`${cam.toUpperCase()} · ${ts}`} />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </CardContent>
      </Card>

      <p className="text-xs text-muted-foreground text-center">
        Automated dossier generation (FR-7) is a Phase B feature — this is a curated static preview.
      </p>
    </div>
  )
}
