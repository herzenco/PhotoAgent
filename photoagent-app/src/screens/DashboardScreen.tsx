import { useEffect } from 'react';
import { Image, Sparkles, Copy, Monitor, RefreshCw, ArrowRight, Loader2 } from 'lucide-react';
import { useAppContext } from '../context/AppContext';
import { usePhotoAgent } from '../hooks/usePhotoAgent';
import type { CatalogStatus } from '../types/cli';

// Sample data used as fallback while loading
const sampleStats = {
  total: 4826,
  analyzed: 3214,
  duplicates: 187,
  screenshots: 342,
};

const sampleYearlyData = [
  { year: '2024', count: 1842 },
  { year: '2023', count: 1356 },
  { year: '2022', count: 892 },
  { year: '2021', count: 534 },
  { year: '2020', count: 202 },
];

export default function DashboardScreen() {
  const { state, dispatch } = useAppContext();
  const { execute, loading, error } = usePhotoAgent<CatalogStatus>();

  useEffect(() => {
    if (state.folderPath) {
      dispatch({ type: 'SET_CATALOG_LOADING', payload: true });
      execute(['status', state.folderPath, '--json']).then((data) => {
        if (data) {
          dispatch({ type: 'SET_CATALOG_STATUS', payload: data });
        }
        dispatch({ type: 'SET_CATALOG_LOADING', payload: false });
      });
    }
  }, [state.folderPath]);

  const handleRescan = () => {
    if (state.folderPath) {
      dispatch({ type: 'SET_CATALOG_LOADING', payload: true });
      execute(['status', state.folderPath, '--json']).then((data) => {
        if (data) {
          dispatch({ type: 'SET_CATALOG_STATUS', payload: data });
        }
        dispatch({ type: 'SET_CATALOG_LOADING', payload: false });
      });
    }
  };

  // Use real data if available, otherwise fall back to sample data
  const catalog = state.catalogStatus;
  const stats = catalog
    ? {
        total: catalog.total_images,
        analyzed: catalog.analyzed_count,
        duplicates: catalog.duplicate_count,
        screenshots: catalog.screenshot_count,
      }
    : sampleStats;

  const yearlyData = catalog && catalog.by_year
    ? Object.entries(catalog.by_year)
        .map(([year, count]) => ({ year, count }))
        .sort((a, b) => b.year.localeCompare(a.year))
    : sampleYearlyData;

  const maxCount = Math.max(...yearlyData.map((d) => d.count), 1);

  const statCards = [
    { label: 'Total Photos', value: stats.total, icon: Image, color: '#6366F1' },
    { label: 'Analyzed', value: stats.analyzed, icon: Sparkles, color: '#6366F1' },
    { label: 'Duplicates', value: stats.duplicates, icon: Copy, color: '#F59E0B' },
    { label: 'Screenshots', value: stats.screenshots, icon: Monitor, color: '#6366F1' },
  ];

  const isLoading = loading || state.catalogLoading;

  return (
    <div className="p-8 max-w-5xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-xl font-semibold text-[#FAFAFA] mb-1">{state.folderPath}</h1>
          <p className="text-sm text-[#71717A]">
            {isLoading ? 'Loading catalog...' : catalog ? 'Catalog loaded' : 'Last scanned 2 hours ago'}
          </p>
        </div>
        <button
          onClick={handleRescan}
          disabled={isLoading}
          className="flex items-center gap-2 px-3 py-2 text-sm text-[#A1A1AA] hover:text-[#FAFAFA] hover:bg-[#27272A] rounded-lg transition-colors duration-150 disabled:opacity-40"
        >
          {isLoading ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
          {isLoading ? 'Loading...' : 'Rescan'}
        </button>
      </div>

      {/* Error message */}
      {error && (
        <div className="mb-6 px-4 py-3 bg-[#7F1D1D]/30 border border-[#DC2626]/40 rounded-xl text-sm text-[#FCA5A5]">
          {error}
        </div>
      )}

      {/* Stats grid */}
      <div className="grid grid-cols-4 gap-4 mb-8">
        {statCards.map((card) => {
          const Icon = card.icon;
          return (
            <div
              key={card.label}
              className={`bg-[#18181B] border border-[#27272A] rounded-xl p-5 ${isLoading ? 'animate-pulse' : ''}`}
            >
              <Icon size={20} style={{ color: card.color }} className="mb-3" />
              <p className="text-[22px] font-semibold text-[#FAFAFA]">
                {card.value.toLocaleString()}
              </p>
              <p className="text-xs text-[#71717A] mt-1">{card.label}</p>
            </div>
          );
        })}
      </div>

      {/* Yearly breakdown */}
      <div className={`bg-[#18181B] border border-[#27272A] rounded-xl p-5 mb-8 ${isLoading ? 'animate-pulse' : ''}`}>
        <h2 className="text-[15px] font-semibold text-[#FAFAFA] mb-4">Yearly Breakdown</h2>
        <div className="space-y-3">
          {yearlyData.map((item) => (
            <div key={item.year} className="flex items-center gap-3">
              <span className="text-xs text-[#A1A1AA] w-10 shrink-0">{item.year}</span>
              <div className="flex-1 h-6 bg-[#27272A] rounded-md overflow-hidden">
                <div
                  className="h-full bg-[#6366F1] rounded-md transition-all duration-300"
                  style={{ width: `${(item.count / maxCount) * 100}%` }}
                />
              </div>
              <span className="text-xs text-[#A1A1AA] w-12 text-right shrink-0">
                {item.count.toLocaleString()}
              </span>
            </div>
          ))}
        </div>
      </div>

      {/* Action cards */}
      <div className="grid grid-cols-2 gap-4">
        <button
          onClick={() => dispatch({ type: 'SET_SCREEN', payload: 'grid' })}
          className="bg-[#18181B] border border-[#27272A] rounded-xl p-6 text-left hover:border-[#3F3F46] transition-colors duration-150 group cursor-pointer"
        >
          <div className="flex items-center justify-between mb-2">
            <Sparkles size={20} className="text-[#6366F1]" />
            <ArrowRight size={16} className="text-[#71717A] group-hover:text-[#A1A1AA] transition-colors duration-150" />
          </div>
          <h3 className="text-[15px] font-semibold text-[#FAFAFA] mb-1">Browse Photos</h3>
          <p className="text-xs text-[#71717A]">
            Search and explore your analyzed photo library with AI-powered tags and captions.
          </p>
        </button>

        <button
          onClick={() => dispatch({ type: 'SET_SCREEN', payload: 'planner' })}
          className="bg-[#18181B] border border-[#27272A] rounded-xl p-6 text-left hover:border-[#3F3F46] transition-colors duration-150 group cursor-pointer"
        >
          <div className="flex items-center justify-between mb-2">
            <Copy size={20} className="text-[#6366F1]" />
            <ArrowRight size={16} className="text-[#71717A] group-hover:text-[#A1A1AA] transition-colors duration-150" />
          </div>
          <h3 className="text-[15px] font-semibold text-[#FAFAFA] mb-1">Organize</h3>
          <p className="text-xs text-[#71717A]">
            Describe how you want your photos organized and let AI create a plan.
          </p>
        </button>
      </div>
    </div>
  );
}
