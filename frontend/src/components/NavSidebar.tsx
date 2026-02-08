import { useState } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import {
  MessageSquare,
  FileText,
  Settings,
  StickyNote,
  Database,
  BookOpen,
  MessageCircle,
  Menu,
  X,
  Send,
  BarChart3
} from 'lucide-react'

interface NavItem {
  id: string
  icon: React.ElementType
  label: string
  path: string
  color?: string
}

const navItems: NavItem[] = [
  { id: 'chat', icon: MessageSquare, label: 'Chat', path: '/' },
  { id: 'documents', icon: FileText, label: 'Documents', path: '/documents' },
  { id: 'notes', icon: StickyNote, label: 'Notes', path: '/notes', color: 'text-amber-500' },
  { id: 'whatsapp', icon: MessageCircle, label: 'WhatsApp', path: '/admin/whatsapp', color: 'text-green-500' },
  { id: 'telegram', icon: Send, label: 'Telegram', path: '/admin/telegram', color: 'text-blue-500' },
  { id: 'maintenance', icon: Database, label: 'Database', path: '/admin/maintenance', color: 'text-cyan-500' },
  { id: 'docs', icon: BookOpen, label: 'Docs', path: '/docs', color: 'text-purple-500' },
  { id: 'dashboard', icon: BarChart3, label: 'Dashboard', path: '/dashboard', color: 'text-indigo-500' },
  { id: 'settings', icon: Settings, label: 'Settings', path: '/settings' },
]

export function NavSidebar() {
  const navigate = useNavigate()
  const location = useLocation()
  const [isMobileMenuOpen, setIsMobileMenuOpen] = useState(false)

  const isActive = (path: string) => {
    if (path === '/') {
      // Chat is active for home and any /chat/* paths
      return location.pathname === '/' || location.pathname.startsWith('/chat/')
    }
    return location.pathname === path || location.pathname.startsWith(path + '/')
  }

  const handleNavigation = (path: string) => {
    navigate(path)
    setIsMobileMenuOpen(false) // Close mobile menu after navigation
  }

  return (
    <>
      {/* Mobile Menu Button - Only visible on small screens */}
      <button
        onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
        className="md:hidden fixed top-4 left-4 z-[60] w-11 h-11 flex items-center justify-center bg-light-sidebar dark:bg-dark-sidebar border border-light-border dark:border-dark-border rounded-lg shadow-lg"
        aria-label={isMobileMenuOpen ? 'Close menu' : 'Open menu'}
      >
        {isMobileMenuOpen ? (
          <X size={24} className="text-light-text dark:text-dark-text" />
        ) : (
          <Menu size={24} className="text-light-text dark:text-dark-text" />
        )}
      </button>

      {/* Mobile Overlay */}
      {isMobileMenuOpen && (
        <div
          className="md:hidden fixed inset-0 bg-black/50 z-[45]"
          onClick={() => setIsMobileMenuOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* Navigation Sidebar */}
      <nav className={`
        w-16 bg-light-sidebar dark:bg-dark-sidebar border-r border-light-border dark:border-dark-border
        flex flex-col h-screen fixed left-0 top-0 z-50
        transition-transform duration-300 ease-in-out
        ${isMobileMenuOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'}
      `}>
        {/* Logo / Brand */}
        <div className="h-16 flex items-center justify-center border-b border-light-border dark:border-dark-border">
          <div className="w-10 h-10 rounded-xl bg-primary flex items-center justify-center">
            <MessageSquare size={20} className="text-white" />
          </div>
        </div>

        {/* Navigation Items */}
        <div className="flex-1 flex flex-col items-center py-4 gap-2">
          {navItems.slice(0, 2).map((item) => {
            const Icon = item.icon
            const active = isActive(item.path)
            return (
              <button
                key={item.id}
                onClick={() => handleNavigation(item.path)}
                className={`
                  w-12 h-12 rounded-xl flex items-center justify-center transition-all duration-200
                  ${active
                    ? 'bg-primary text-white shadow-lg'
                    : 'text-light-text-secondary dark:text-dark-text-secondary hover:bg-light-border dark:hover:bg-dark-border hover:text-light-text dark:hover:text-dark-text'
                  }
                `}
                title={item.label}
                aria-label={item.label}
                aria-current={active ? 'page' : undefined}
              >
                <Icon size={22} />
              </button>
            )
          })}

          {/* Divider */}
          <div className="w-8 h-px bg-light-border dark:bg-dark-border my-2" />

          {/* Secondary nav items */}
          {navItems.slice(2, -1).map((item) => {
            const Icon = item.icon
            const active = isActive(item.path)
            return (
              <button
                key={item.id}
                onClick={() => handleNavigation(item.path)}
                className={`
                  w-12 h-12 rounded-xl flex items-center justify-center transition-all duration-200
                  ${active
                    ? 'bg-primary/10 text-primary'
                    : `${item.color || 'text-light-text-secondary dark:text-dark-text-secondary'} hover:bg-light-border dark:hover:bg-dark-border`
                  }
                `}
                title={item.label}
                aria-label={item.label}
                aria-current={active ? 'page' : undefined}
              >
                <Icon size={20} />
              </button>
            )
          })}
        </div>

        {/* Settings at bottom */}
        <div className="pb-4 flex flex-col items-center">
          <button
            onClick={() => handleNavigation('/settings')}
            className={`
              w-12 h-12 rounded-xl flex items-center justify-center transition-all duration-200
              ${isActive('/settings')
                ? 'bg-primary/10 text-primary'
                : 'text-light-text-secondary dark:text-dark-text-secondary hover:bg-light-border dark:hover:bg-dark-border hover:text-light-text dark:hover:text-dark-text'
              }
            `}
            title="Settings"
            aria-label="Settings"
            aria-current={isActive('/settings') ? 'page' : undefined}
          >
            <Settings size={22} />
          </button>
        </div>
      </nav>
    </>
  )
}

export default NavSidebar
