import { useState, useCallback } from 'react';
import { Upload, FolderOpen, Clock } from 'lucide-react';
import { open } from '@tauri-apps/plugin-dialog';
import { useAppContext } from '../context/AppContext';

export default function WelcomeScreen() {
  const { state, dispatch } = useAppContext();
  const [dragOver, setDragOver] = useState(false);

  const selectFolder = useCallback((path: string) => {
    dispatch({ type: 'SET_FOLDER', payload: path });
  }, [dispatch]);

  const handleBrowse = useCallback(async () => {
    try {
      const selected = await open({ directory: true, multiple: false });
      if (selected) {
        selectFolder(selected as string);
      }
    } catch {
      // User cancelled the dialog or error occurred — do nothing
    }
  }, [selectFolder]);

  return (
    <div className="min-h-screen bg-[#09090B] flex flex-col items-center justify-center px-4">
      <div className="max-w-lg w-full mx-auto text-center">
        {/* Title */}
        <h1 className="text-[28px] font-bold text-[#FAFAFA] mb-2">
          PhotoAgent
        </h1>
        <p className="text-sm text-[#A1A1AA] mb-10">
          Your photos stay on this device. Always.
        </p>

        {/* Drop zone */}
        <div
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            const items = e.dataTransfer.files;
            if (items.length > 0) {
              selectFolder(items[0].name);
            }
          }}
          className={`
            border-2 border-dashed rounded-2xl p-12 mb-8
            transition-colors duration-150 cursor-pointer
            ${dragOver
              ? 'border-[#6366F1]/60 bg-[#6366F1]/5'
              : 'border-[#3F3F46] hover:border-[#6366F1]/60'
            }
          `}
          onClick={handleBrowse}
        >
          <Upload size={64} className="text-[#71717A] mx-auto mb-4" />
          <p className="text-[#FAFAFA] text-sm font-medium mb-2">
            Drop a folder here
          </p>
          <p className="text-[#71717A] text-xs mb-4">or</p>
          <button
            onClick={(e) => { e.stopPropagation(); handleBrowse(); }}
            className="px-5 py-2.5 bg-[#6366F1] hover:bg-[#818CF8] text-white text-sm font-medium rounded-lg transition-colors duration-150"
          >
            <FolderOpen size={16} className="inline mr-2 -mt-0.5" />
            Browse Folder
          </button>
        </div>

        {/* Recent folders */}
        {state.recentFolders.length > 0 && (
          <div className="text-left">
            <h3 className="text-xs font-medium text-[#71717A] uppercase tracking-wider mb-3">
              Recent Folders
            </h3>
            <div className="space-y-2">
              {state.recentFolders.map((folder) => (
                <button
                  key={folder.path}
                  onClick={() => selectFolder(folder.path)}
                  className="w-full flex items-center gap-3 px-4 py-3 bg-[#18181B] border border-[#27272A] rounded-xl hover:border-[#3F3F46] transition-colors duration-150 cursor-pointer"
                >
                  <FolderOpen size={16} className="text-[#A1A1AA] shrink-0" />
                  <div className="flex-1 text-left min-w-0">
                    <p className="text-sm text-[#FAFAFA] truncate">{folder.path}</p>
                  </div>
                  <div className="flex items-center gap-1.5 text-[#71717A] shrink-0">
                    <Clock size={12} />
                    <span className="text-xs">{folder.lastScanned}</span>
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
