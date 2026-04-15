import { useState } from 'react';
import {
  Sparkles,
  Calendar,
  FileType,
  MapPin,
  Trash2,
  Folder,
  File,
  ShieldCheck,
  Loader2,
} from 'lucide-react';
import { useAppContext } from '../context/AppContext';
import { usePhotoAgent } from '../hooks/usePhotoAgent';
import type { OrganizationPlan, ExecutionResult } from '../types/cli';

interface Template {
  icon: typeof Calendar;
  label: string;
  name: string;
  description: string;
  instruction: string;
}

const templates: Template[] = [
  { icon: Calendar, label: 'By Date', name: 'by-date', description: 'Organize into year/month folders', instruction: 'Organize my photos into folders by year and month, like 2024/August/' },
  { icon: FileType, label: 'By Type', name: 'by-type', description: 'Separate photos, videos, screenshots', instruction: 'Sort photos by type: regular photos, screenshots, and videos in separate folders' },
  { icon: MapPin, label: 'By Location', name: 'by-location', description: 'Group by city and country', instruction: 'Organize photos by location, grouping by country then city' },
  { icon: Trash2, label: 'Cleanup', name: 'cleanup', description: 'Remove duplicates and screenshots', instruction: 'Find and move duplicates and screenshots into a _cleanup folder' },
];

const samplePlan = {
  folders: [
    { name: '2024/', depth: 0 },
    { name: 'August/', depth: 1 },
    { name: 'Vacation/', depth: 2 },
    { name: 'September/', depth: 1 },
    { name: 'City/', depth: 2 },
    { name: 'Nature/', depth: 2 },
    { name: 'October/', depth: 1 },
  ],
  moves: [
    { from: 'IMG_2401.jpg', to: '2024/August/Vacation/' },
    { from: 'DSC_0892.jpg', to: '2024/July/' },
    { from: 'IMG_2455.jpg', to: '2024/August/' },
    { from: 'DSC_1204.jpg', to: '2024/September/City/' },
    { from: 'IMG_2510.jpg', to: '2024/September/Nature/' },
    { from: 'DSCF_0045.jpg', to: '2024/September/City/' },
  ],
  summary: 'Moving 6 files into 5 folders',
};

export default function PlannerScreen() {
  const { state, dispatch } = useAppContext();
  const { execute: executePlan, loading: planLoading, error: planError } = usePhotoAgent<OrganizationPlan>();
  const { execute: executeRun, loading: execLoading, error: execError } = usePhotoAgent<ExecutionResult>();
  const [instruction, setInstruction] = useState('');
  const [showPlan, setShowPlan] = useState(false);
  const [execDone, setExecDone] = useState(false);

  // Use real plan from context if available, otherwise sample plan
  const plan = state.currentPlan;
  const displayFolders = plan
    ? plan.folder_structure.map((f) => {
        const depth = (f.match(/\//g) || []).length - 1;
        const name = f.split('/').filter(Boolean).pop() + '/';
        return { name, depth: Math.max(0, depth) };
      })
    : samplePlan.folders;
  const displayMoves = plan
    ? plan.moves.map((m) => ({ from: m.from, to: m.to }))
    : samplePlan.moves;
  const displaySummary = plan ? plan.summary : samplePlan.summary;

  const handleSubmit = async () => {
    if (!instruction.trim() || !state.folderPath) return;
    dispatch({ type: 'SET_PLAN_LOADING', payload: true });
    const result = await executePlan(['organize', state.folderPath, instruction, '--dry-run', '--json']);
    if (result) {
      dispatch({ type: 'SET_PLAN', payload: result });
      setShowPlan(true);
    }
    dispatch({ type: 'SET_PLAN_LOADING', payload: false });
  };

  const handleTemplate = async (tmpl: Template) => {
    setInstruction(tmpl.instruction);
    if (!state.folderPath) return;
    dispatch({ type: 'SET_PLAN_LOADING', payload: true });
    const result = await executePlan([
      'organize-template', state.folderPath, '--template', tmpl.name, '--dry-run', '--json',
    ]);
    if (result) {
      dispatch({ type: 'SET_PLAN', payload: result });
      setShowPlan(true);
    }
    dispatch({ type: 'SET_PLAN_LOADING', payload: false });
  };

  const handleExecute = async () => {
    if (!instruction.trim() || !state.folderPath) return;
    setExecDone(false);
    const result = await executeRun(['organize', state.folderPath, instruction, '--json']);
    if (result) {
      setExecDone(true);
    }
  };

  const handleCancel = () => {
    setShowPlan(false);
    setExecDone(false);
    dispatch({ type: 'SET_PLAN', payload: null });
  };

  const isLoading = planLoading || state.planLoading;
  const error = planError || execError;

  return (
    <div className="p-8 max-w-4xl">
      <h1 className="text-xl font-semibold text-[#FAFAFA] mb-6">Organize Photos</h1>

      {/* Error message */}
      {error && (
        <div className="mb-6 px-4 py-3 bg-[#7F1D1D]/30 border border-[#DC2626]/40 rounded-xl text-sm text-[#FCA5A5]">
          {error}
        </div>
      )}

      {/* Instruction input */}
      <div className="relative mb-6">
        <Sparkles size={16} className="absolute left-4 top-4 text-[#6366F1]" />
        <textarea
          value={instruction}
          onChange={(e) => setInstruction(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' && e.metaKey) handleSubmit();
          }}
          placeholder="Describe how to organize your photos..."
          className="w-full bg-[#18181B] border border-[#3F3F46] rounded-xl p-4 pl-10 min-h-[100px] text-sm text-[#FAFAFA] placeholder:text-[#71717A] focus:outline-none focus:border-[#6366F1] transition-colors duration-150 resize-none"
        />
        <div className="flex justify-between items-center mt-2">
          <span className="text-[11px] text-[#71717A]">Cmd+Enter to submit</span>
          <button
            onClick={handleSubmit}
            disabled={!instruction.trim() || isLoading}
            className="px-4 py-2 bg-[#6366F1] hover:bg-[#818CF8] disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors duration-150 flex items-center gap-2"
          >
            {isLoading && <Loader2 size={14} className="animate-spin" />}
            {isLoading ? 'Generating...' : 'Generate Plan'}
          </button>
        </div>
      </div>

      {/* Templates */}
      {!showPlan && (
        <div className="mb-8">
          <h2 className="text-sm font-medium text-[#71717A] mb-3">Quick Templates</h2>
          <div className="grid grid-cols-2 gap-3">
            {templates.map((tmpl) => {
              const Icon = tmpl.icon;
              return (
                <button
                  key={tmpl.label}
                  onClick={() => handleTemplate(tmpl)}
                  disabled={isLoading}
                  className="bg-[#18181B] border border-[#27272A] rounded-xl p-4 text-left hover:border-[#3F3F46] transition-colors duration-150 cursor-pointer disabled:opacity-40"
                >
                  <Icon size={18} className="text-[#6366F1] mb-2" />
                  <p className="text-sm font-medium text-[#FAFAFA] mb-0.5">{tmpl.label}</p>
                  <p className="text-xs text-[#71717A]">{tmpl.description}</p>
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Loading state */}
      {isLoading && !showPlan && (
        <div className="flex items-center justify-center py-16">
          <div className="text-center">
            <Loader2 size={32} className="text-[#6366F1] animate-spin mx-auto mb-3" />
            <p className="text-sm text-[#71717A]">Generating organization plan...</p>
          </div>
        </div>
      )}

      {/* Plan preview */}
      {showPlan && (
        <div className="space-y-6">
          {/* Execution success message */}
          {execDone && (
            <div className="px-4 py-3 bg-[#064E3B]/50 border border-[#34D399]/40 rounded-xl text-sm text-[#34D399]">
              Plan executed successfully! Check the History tab for details.
            </div>
          )}

          {/* Folder tree */}
          <div className="bg-[#18181B] border border-[#27272A] rounded-xl p-5">
            <h2 className="text-[15px] font-semibold text-[#FAFAFA] mb-4">Folder Structure</h2>
            <div className="space-y-1 font-mono text-sm">
              {displayFolders.map((f, i) => (
                <div key={i} className="flex items-center gap-2" style={{ paddingLeft: f.depth * 20 }}>
                  <Folder size={14} className="text-[#6366F1]" />
                  <span className="text-[#A1A1AA]">{f.name}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Summary */}
          <p className="text-sm text-[#A1A1AA]">{displaySummary}</p>

          {/* Move table */}
          <div className="bg-[#18181B] border border-[#27272A] rounded-xl overflow-hidden">
            <div className="grid grid-cols-2 gap-4 px-5 py-3 border-b border-[#27272A]">
              <span className="text-xs font-medium text-[#71717A] uppercase tracking-wider">From</span>
              <span className="text-xs font-medium text-[#71717A] uppercase tracking-wider">To</span>
            </div>
            {displayMoves.map((move, i) => (
              <div
                key={i}
                className={`grid grid-cols-2 gap-4 px-5 py-2.5 text-sm font-mono ${
                  i % 2 === 0 ? 'bg-[#18181B]' : 'bg-[#1C1C1F]'
                }`}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <File size={12} className="text-[#71717A] shrink-0" />
                  <span className="text-[#A1A1AA] truncate">{move.from}</span>
                </div>
                <span className="text-[#A1A1AA] truncate">{move.to}</span>
              </div>
            ))}
          </div>

          {/* Privacy banner */}
          <div className="bg-[#064E3B]/50 rounded-xl px-4 py-3 flex items-center gap-3">
            <ShieldCheck size={16} className="text-[#34D399] shrink-0" />
            <p className="text-xs text-[#34D399]">
              Only text metadata was sent. No images left your device.
            </p>
          </div>

          {/* Action bar */}
          <div className="flex justify-end gap-3">
            <button
              onClick={handleCancel}
              disabled={execLoading}
              className="px-4 py-2.5 text-sm text-[#A1A1AA] hover:text-[#FAFAFA] hover:bg-[#27272A] rounded-lg transition-colors duration-150"
            >
              Cancel
            </button>
            <button
              onClick={handleExecute}
              disabled={execLoading || execDone}
              className="px-5 py-2.5 bg-[#6366F1] hover:bg-[#818CF8] disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors duration-150 flex items-center gap-2"
            >
              {execLoading && <Loader2 size={14} className="animate-spin" />}
              {execLoading ? 'Executing...' : execDone ? 'Done' : 'Execute Plan'}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
