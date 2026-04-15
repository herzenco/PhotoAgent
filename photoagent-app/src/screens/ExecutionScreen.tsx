import { useEffect, useState } from 'react';
import { CheckCircle2, XCircle, Undo2, FolderTree, Loader2 } from 'lucide-react';
import { useAppContext } from '../context/AppContext';
import { usePhotoAgent } from '../hooks/usePhotoAgent';
import type { HistoryEntry } from '../types/cli';

interface SampleHistoryItem {
  id: number;
  timestamp: string;
  instruction: string;
  status: 'success' | 'error';
  fileCount: number;
  folderCount: number;
}

const sampleHistory: SampleHistoryItem[] = [
  {
    id: 1,
    timestamp: '2026-04-14 10:32 AM',
    instruction: 'Organize photos by year and month',
    status: 'success',
    fileCount: 342,
    folderCount: 18,
  },
  {
    id: 2,
    timestamp: '2026-04-12 03:15 PM',
    instruction: 'Move duplicates into _cleanup folder',
    status: 'success',
    fileCount: 87,
    folderCount: 1,
  },
  {
    id: 3,
    timestamp: '2026-04-10 09:45 AM',
    instruction: 'Sort screenshots into a separate folder',
    status: 'error',
    fileCount: 12,
    folderCount: 1,
  },
];

// Convert HistoryEntry to the display shape
function toDisplayItem(entry: HistoryEntry): SampleHistoryItem {
  return {
    id: entry.id,
    timestamp: entry.timestamp,
    instruction: entry.instruction,
    status: entry.status === 'success' ? 'success' : 'error',
    fileCount: entry.file_count,
    folderCount: 0,
  };
}

export default function ExecutionScreen() {
  const { state, dispatch } = useAppContext();
  const { execute, loading, error } = usePhotoAgent<HistoryEntry[]>();
  const { execute: executeUndo, loading: undoLoading, error: undoError } = usePhotoAgent<unknown>();
  const [undoingId, setUndoingId] = useState<number | null>(null);

  useEffect(() => {
    if (state.folderPath) {
      execute(['history', state.folderPath, '--json']).then((data) => {
        if (data) {
          dispatch({ type: 'SET_HISTORY', payload: data });
        }
      });
    }
  }, [state.folderPath]);

  const handleUndo = async (id: number) => {
    if (!state.folderPath) return;
    setUndoingId(id);
    await executeUndo(['undo', state.folderPath, '--json']);
    // Reload history after undo
    const data = await execute(['history', state.folderPath, '--json']);
    if (data) {
      dispatch({ type: 'SET_HISTORY', payload: data });
    }
    setUndoingId(null);
  };

  // Use real history from context if available, otherwise sample data
  const hasRealHistory = state.history.length > 0;
  const displayHistory: SampleHistoryItem[] = hasRealHistory
    ? state.history.map(toDisplayItem)
    : sampleHistory;

  const displayError = error || undoError;

  return (
    <div className="p-8 max-w-4xl">
      <h1 className="text-xl font-semibold text-[#FAFAFA] mb-6">History</h1>

      {/* Error message */}
      {displayError && (
        <div className="mb-6 px-4 py-3 bg-[#7F1D1D]/30 border border-[#DC2626]/40 rounded-xl text-sm text-[#FCA5A5]">
          {displayError}
        </div>
      )}

      {/* Loading state */}
      {loading && !hasRealHistory && (
        <div className="flex items-center justify-center py-16">
          <div className="text-center">
            <Loader2 size={32} className="text-[#6366F1] animate-spin mx-auto mb-3" />
            <p className="text-sm text-[#71717A]">Loading history...</p>
          </div>
        </div>
      )}

      {!loading && displayHistory.length === 0 ? (
        <div className="text-center py-20">
          <FolderTree size={48} className="text-[#3F3F46] mx-auto mb-4" />
          <p className="text-sm text-[#71717A] mb-3">No operations yet</p>
          <button
            onClick={() => dispatch({ type: 'SET_SCREEN', payload: 'planner' })}
            className="text-sm text-[#6366F1] hover:text-[#818CF8] transition-colors duration-150"
          >
            Go to Organizer
          </button>
        </div>
      ) : !loading || hasRealHistory ? (
        <div className="space-y-3">
          {displayHistory.map((item) => (
            <div
              key={item.id}
              className="bg-[#18181B] border border-[#27272A] rounded-xl p-4 group"
            >
              <div className="flex items-start gap-3">
                {/* Status icon */}
                {item.status === 'success' ? (
                  <CheckCircle2 size={18} className="text-[#22C55E] mt-0.5 shrink-0" />
                ) : (
                  <XCircle size={18} className="text-[#EF4444] mt-0.5 shrink-0" />
                )}

                <div className="flex-1 min-w-0">
                  {/* Timestamp */}
                  <p className="text-xs text-[#71717A] mb-1">{item.timestamp}</p>

                  {/* Instruction */}
                  <p className="text-sm text-[#FAFAFA] mb-2">
                    &ldquo;{item.instruction}&rdquo;
                  </p>

                  {/* Stats */}
                  <div className="flex gap-4">
                    <span className="text-xs text-[#A1A1AA]">
                      {item.fileCount} files moved
                    </span>
                    {item.folderCount > 0 && (
                      <span className="text-xs text-[#A1A1AA]">
                        {item.folderCount} {item.folderCount === 1 ? 'folder' : 'folders'}
                      </span>
                    )}
                  </div>
                </div>

                {/* Undo button */}
                <button
                  onClick={() => handleUndo(item.id)}
                  disabled={undoLoading && undoingId === item.id}
                  className="opacity-0 group-hover:opacity-100 px-3 py-1.5 text-xs text-[#A1A1AA] hover:text-[#FAFAFA] hover:bg-[#27272A] rounded-lg transition-all duration-150 flex items-center gap-1.5 disabled:opacity-50"
                >
                  {undoLoading && undoingId === item.id ? (
                    <Loader2 size={12} className="animate-spin" />
                  ) : (
                    <Undo2 size={12} />
                  )}
                  {undoLoading && undoingId === item.id ? 'Undoing...' : 'Undo'}
                </button>
              </div>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
