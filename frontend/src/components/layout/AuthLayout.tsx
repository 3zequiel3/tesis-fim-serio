import { ShieldCheck } from 'lucide-react'
import type { ReactNode } from 'react'
import { ThemeToggle } from '@/components/ui/ThemeToggle'

interface AuthLayoutProps {
  children: ReactNode
}

export function AuthLayout({ children }: AuthLayoutProps) {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-surface px-4 py-10">
      <div className="absolute right-4 top-4">
        <ThemeToggle />
      </div>
      <div className="w-full max-w-md">
        <div className="mb-6 flex items-center gap-2.5 text-text">
          <ShieldCheck aria-hidden="true" size={28} className="text-accent" />
          <span className="text-xl font-semibold">FIM Platform</span>
        </div>
        {children}
      </div>
    </div>
  )
}
