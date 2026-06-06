import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Button } from "@/components/ui/button"

export default function SettingsPage() {
  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Settings</h1>
        <p className="text-sm text-muted-foreground">System configuration (mock — not persisted).</p>
      </div>

      <div className="max-w-xl space-y-4">
        <Card>
          <CardHeader>
            <CardTitle>API Server</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="space-y-1">
              <p className="text-sm font-medium">URL</p>
              <Input defaultValue="http://localhost:8000" />
            </div>
            <Button size="sm" variant="outline">Save</Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Qdrant</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <p className="text-sm font-medium">Host</p>
                <Input defaultValue="localhost" />
              </div>
              <div className="space-y-1">
                <p className="text-sm font-medium">Port</p>
                <Input defaultValue="6333" />
              </div>
            </div>
            <Button size="sm" variant="outline">Save</Button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>ROI Sampler</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1">
                <p className="text-sm font-medium">Grid size (G)</p>
                <Input defaultValue="8" type="number" min={1} />
              </div>
              <div className="space-y-1">
                <p className="text-sm font-medium">Threshold (τ)</p>
                <Input defaultValue="25" type="number" min={0} max={255} />
              </div>
              <div className="space-y-1">
                <p className="text-sm font-medium">Min active cells (k)</p>
                <Input defaultValue="4" type="number" min={1} />
              </div>
              <div className="space-y-1">
                <p className="text-sm font-medium">Buffer delta (Δ)</p>
                <Input defaultValue="15" type="number" min={1} />
              </div>
            </div>
            <Button size="sm" variant="outline">Save</Button>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
