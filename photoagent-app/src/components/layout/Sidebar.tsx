import {
  Home,
  LayoutDashboard,
  Image,
  FolderTree,
  History,
  Settings,
  ShieldCheck,
} from 'lucide-react';
import { useAppContext, type ScreenName } from '../../context/AppContext';

const navItems: { icon: typeof Home; label: string; screen: ScreenName }[] = [
  { icon: Home, label: 'Home', screen: 'dashboard' },
  { icon: LayoutDashboard, label: 'Dashboard', screen: 'dashboard' },
  { icon: Image, label: 'Photos', screen: 'grid' },
  { icon: FolderTree, label: 'Organize', screen: 'planner' },
  { icon: History, label: 'History', screen: 'history' },
  { icon: Settings, label: 'Settings', screen: 'settings' },
];

export default function Sidebar() {
  const { state, dispatch } = useAppContext();

  return (
    <aside className="w-[240px] min-w-[240px] bg-[#18181B] border-r border-[#27272A] flex flex-col h-screen">
      {/* Logo */}
      <div className="px-4 py-5">
        <h1 className="text-[15px] font-semibold text-[#FAFAFA] tracking-tight">
          PhotoAgent
        </h1>
      </div>

      {/* Nav */}
      <nav className="flex-1 px-3 space-y-1">
        {navItems.map((item) => {
          const active = state.currentScreen === item.screen;
          const Icon = item.icon;
          return (
            <button
              key={item.label}
              onClick={() => dispatch({ type: 'SET_SCREEN', payload: item.screen })}
              className={`
                w-full flex items-center gap-3 h-10 px-3 rounded-lg text-sm
                transition-colors duration-150 cursor-pointer
                ${
                  active
                    ? 'bg-[#27272A] text-[#FAFAFA] border-l-[3px] border-[#6366F1]'
                    : 'text-[#A1A1AA] hover:bg-[#27272A]/50 border-l-[3px] border-transparent'
                }
              `}
            >
              <Icon size={18} className={active ? 'text-[#6366F1]' : ''} />
              <span>{item.label}</span>
            </button>
          );
        })}
      </nav>

      {/* Privacy badge */}
      <div className="px-3 pb-4">
        <div className="bg-[#064E3B] rounded-xl px-3 py-3 flex items-start gap-2.5">
          <ShieldCheck size={18} className="text-[#34D399] mt-0.5 shrink-0" />
          <div>
            <p className="text-[#34D399] text-xs font-medium">Local Only</p>
            <p className="text-[#34D399]/70 text-[11px] mt-0.5 leading-snug">
              Photos never leave your device
            </p>
          </div>
        </div>
      </div>
    </aside>
  );
}
