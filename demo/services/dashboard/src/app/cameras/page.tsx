import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Video, Plus } from "lucide-react"

const CAMERAS = [
  { id: "cam-01", name: "Entrance", status: "online", fps: 30, res: "1920×1080" },
  { id: "cam-02", name: "Parking Lot", status: "online", fps: 25, res: "1280×720" },
  { id: "cam-03", name: "Warehouse A", status: "offline", fps: 0, res: "1920×1080" },
  { id: "cam-04", name: "Loading Bay", status: "online", fps: 30, res: "1920×1080" },
]

export default function CamerasPage() {
  return (
    <div className="p-6 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">Cameras</h1>
          <p className="text-sm text-muted-foreground">Manage connected camera sources.</p>
        </div>
        <Button size="sm">
          <Plus className="size-4" />
          Add Camera
        </Button>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        {CAMERAS.map((cam) => (
          <Card key={cam.id}>
            <CardHeader>
              <div className="flex items-center justify-between">
                <CardTitle className="flex items-center gap-2 text-base">
                  <Video className="size-4" />
                  {cam.name}
                </CardTitle>
                <Badge variant={cam.status === "online" ? "default" : "destructive"}>
                  {cam.status}
                </Badge>
              </div>
            </CardHeader>
            <CardContent className="space-y-3">
              <div className="bg-muted rounded-lg aspect-video flex items-center justify-center">
                <p className="text-sm text-muted-foreground">
                  {cam.status === "online" ? "Live feed (mock)" : "Offline"}
                </p>
              </div>
              <div className="grid grid-cols-3 gap-2 text-xs text-muted-foreground">
                <span>ID: {cam.id}</span>
                <span>Res: {cam.res}</span>
                <span>FPS: {cam.fps}</span>
              </div>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  )
}
