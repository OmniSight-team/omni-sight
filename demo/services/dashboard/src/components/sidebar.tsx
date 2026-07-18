"use client"

import Link from "next/link"
import { usePathname } from "next/navigation"
import {
  LayoutDashboard, Upload, Search, Bell, FileText,
  Users, Camera, Activity, Timer, Shield,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { useAuth } from "@/lib/auth"

type NavItem = { href: string; label: string; icon: React.ElementType }

const OPERATOR: NavItem[] = [
  { href: "/",         label: "Dashboard",       icon: LayoutDashboard },
  { href: "/upload",   label: "Upload",           icon: Upload },
  { href: "/search",   label: "Semantic Search",  icon: Search },
  { href: "/alerts",   label: "Alerts",           icon: Bell },
  { href: "/forensic", label: "Forensic Dossier", icon: FileText },
]

const ADMIN: NavItem[] = [
  { href: "/admin/users",     label: "Users & Roles",    icon: Users },
  { href: "/admin/cameras",   label: "Camera Config",    icon: Camera },
  { href: "/admin/health",    label: "System Health",    icon: Activity },
  { href: "/admin/retention", label: "Retention Policy", icon: Timer },
]

function NavLink({ href, label, icon: Icon, active }: NavItem & { active: boolean }) {
  return (
    <Link
      href={href}
      className={cn(
        "flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm transition-colors",
        active
          ? "bg-sidebar-accent text-sidebar-accent-foreground font-medium"
          : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-accent-foreground"
      )}
    >
      <Icon className="size-4 shrink-0" />
      {label}
    </Link>
  )
}

function NavSection({ title, items, pathname }: { title: string; items: NavItem[]; pathname: string }) {
  return (
    <div className="space-y-0.5">
      <p className="px-3 pb-1 pt-3 text-[10px] font-semibold text-muted-foreground uppercase tracking-widest">
        {title}
      </p>
      {items.map((item) => (
        <NavLink key={item.href} {...item} active={pathname === item.href} />
      ))}
    </div>
  )
}

export function Sidebar() {
  const pathname = usePathname()
  const { user } = useAuth()

  return (
    <aside className="w-52 shrink-0 flex flex-col border-r border-sidebar-border bg-sidebar h-screen sticky top-0">
      <div className="px-4 py-3.5 border-b border-sidebar-border flex items-center gap-2">
        <Shield className="size-4 text-primary shrink-0" />
        <span className="font-semibold text-sm tracking-wide text-sidebar-foreground">
          OmniSight
        </span>
      </div>

      <nav className="flex-1 p-2 overflow-y-auto">
        <NavSection title="Workspace" items={OPERATOR} pathname={pathname} />
        {user?.role === "admin" && (
          <>
            <div className="my-2 border-t border-sidebar-border" />
            <NavSection title="Admin" items={ADMIN} pathname={pathname} />
          </>
        )}
      </nav>

      <div className="p-3 border-t border-sidebar-border">
        <p className="px-1 text-[10px] text-muted-foreground/60">v0.1 · Phase A</p>
      </div>
    </aside>
  )
}
