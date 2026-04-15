import { useState, useCallback } from 'react';
import { Search, X, Loader2 } from 'lucide-react';
import { useAppContext } from '../context/AppContext';
import { usePhotoAgent } from '../hooks/usePhotoAgent';
import type { SearchResult } from '../types/cli';

interface SamplePhoto {
  id: number;
  filename: string;
  tags: string[];
  caption: string;
  dateTaken: string;
  camera: string;
  resolution: string;
  fileSize: string;
}

const samplePhotos: SamplePhoto[] = [
  { id: 1, filename: 'IMG_2401.jpg', tags: ['sunset', 'beach', 'landscape'], caption: 'Golden sunset over the Pacific coast', dateTaken: '2024-08-15', camera: 'iPhone 15 Pro', resolution: '4032x3024', fileSize: '4.2 MB' },
  { id: 2, filename: 'DSC_0892.jpg', tags: ['portrait', 'family'], caption: 'Family portrait at the park', dateTaken: '2024-07-22', camera: 'Nikon Z6', resolution: '6048x4024', fileSize: '12.1 MB' },
  { id: 3, filename: 'IMG_2455.jpg', tags: ['food', 'restaurant'], caption: 'Brunch spread at the cafe', dateTaken: '2024-08-20', camera: 'iPhone 15 Pro', resolution: '4032x3024', fileSize: '3.8 MB' },
  { id: 4, filename: 'DSC_1204.jpg', tags: ['architecture', 'city'], caption: 'Downtown skyline at dusk', dateTaken: '2024-09-01', camera: 'Nikon Z6', resolution: '6048x4024', fileSize: '14.3 MB' },
  { id: 5, filename: 'IMG_2510.jpg', tags: ['nature', 'hiking', 'mountains'], caption: 'Mountain trail panorama', dateTaken: '2024-09-10', camera: 'iPhone 15 Pro', resolution: '4032x3024', fileSize: '5.1 MB' },
  { id: 6, filename: 'DSCF_0045.jpg', tags: ['street', 'night'], caption: 'Neon reflections on wet pavement', dateTaken: '2024-09-15', camera: 'Fuji X-T5', resolution: '6240x4160', fileSize: '18.2 MB' },
  { id: 7, filename: 'IMG_2601.jpg', tags: ['pet', 'dog'], caption: 'Dog playing fetch in the yard', dateTaken: '2024-10-01', camera: 'iPhone 15 Pro', resolution: '4032x3024', fileSize: '3.4 MB' },
  { id: 8, filename: 'DSC_1350.jpg', tags: ['wedding', 'portrait'], caption: 'Ceremony exit with confetti', dateTaken: '2024-10-12', camera: 'Nikon Z6', resolution: '6048x4024', fileSize: '11.7 MB' },
  { id: 9, filename: 'screenshot_1.png', tags: ['screenshot'], caption: 'Desktop screenshot', dateTaken: '2024-10-20', camera: 'Screen Capture', resolution: '2560x1440', fileSize: '1.2 MB' },
  { id: 10, filename: 'IMG_2780.jpg', tags: ['travel', 'landmark'], caption: 'Ancient temple at sunrise', dateTaken: '2024-11-05', camera: 'iPhone 15 Pro', resolution: '4032x3024', fileSize: '4.8 MB' },
  { id: 11, filename: 'DSCF_0112.jpg', tags: ['macro', 'flowers'], caption: 'Close-up of cherry blossoms', dateTaken: '2024-11-15', camera: 'Fuji X-T5', resolution: '6240x4160', fileSize: '16.4 MB' },
  { id: 12, filename: 'IMG_2850.jpg', tags: ['snow', 'winter', 'landscape'], caption: 'First snowfall of the season', dateTaken: '2024-12-01', camera: 'iPhone 15 Pro', resolution: '4032x3024', fileSize: '4.0 MB' },
];

const placeholderColors = [
  '#312E81', '#1E3A5F', '#3B0764', '#14532D', '#713F12',
  '#1C1917', '#172554', '#4A1D96', '#064E3B', '#78350F',
  '#1E1B4B', '#0C4A6E',
];

// Convert SearchResult to SamplePhoto shape for unified rendering
function searchResultToPhoto(r: SearchResult): SamplePhoto {
  return {
    id: r.id,
    filename: r.filename,
    tags: r.tags,
    caption: r.caption,
    dateTaken: r.date_taken ?? '',
    camera: r.camera_model ?? '',
    resolution: '',
    fileSize: r.file_size ? `${(r.file_size / (1024 * 1024)).toFixed(1)} MB` : '',
  };
}

export default function PhotoGridScreen() {
  const { state, dispatch } = useAppContext();
  const { execute, loading, error } = usePhotoAgent<SearchResult[]>();
  const [query, setQuery] = useState(state.searchQuery);
  const [selectedId, setSelectedId] = useState<number | null>(null);

  const handleSearch = useCallback(async (searchQuery: string) => {
    if (!searchQuery.trim() || !state.folderPath) return;
    dispatch({ type: 'SET_SEARCH_QUERY', payload: searchQuery });
    const args = ['search', state.folderPath, searchQuery, '--json'];
    const results = await execute(args);
    if (results) {
      dispatch({ type: 'SET_SEARCH_RESULTS', payload: results });
    }
  }, [state.folderPath, dispatch, execute]);

  // Use search results from context if available, otherwise sample data
  const hasSearchResults = state.searchResults.length > 0;
  const photos: SamplePhoto[] = hasSearchResults
    ? state.searchResults.map(searchResultToPhoto)
    : samplePhotos;

  // Client-side filter for sample data only (real search is server-side)
  const filtered = !hasSearchResults && query
    ? photos.filter(
        (p) =>
          p.filename.toLowerCase().includes(query.toLowerCase()) ||
          p.tags.some((t) => t.toLowerCase().includes(query.toLowerCase())) ||
          p.caption.toLowerCase().includes(query.toLowerCase())
      )
    : photos;

  const selected = selectedId ? filtered.find((p) => p.id === selectedId) ?? null : null;

  return (
    <div className="flex h-screen">
      {/* Main area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Search bar */}
        <div className="p-4 pb-0">
          <div className="relative">
            <Search size={16} className="absolute left-4 top-1/2 -translate-y-1/2 text-[#71717A]" />
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleSearch(query);
              }}
              placeholder="Search photos by name, tag, or description... (Enter to search)"
              className="w-full h-11 bg-[#18181B] border border-[#3F3F46] rounded-[10px] pl-10 pr-4 text-sm text-[#FAFAFA] placeholder:text-[#71717A] focus:outline-none focus:border-[#6366F1] transition-colors duration-150"
            />
            {loading && (
              <Loader2 size={16} className="absolute right-4 top-1/2 -translate-y-1/2 text-[#6366F1] animate-spin" />
            )}
          </div>
        </div>

        {/* Error message */}
        {error && (
          <div className="mx-4 mt-3 px-4 py-3 bg-[#7F1D1D]/30 border border-[#DC2626]/40 rounded-xl text-sm text-[#FCA5A5]">
            {error}
          </div>
        )}

        {/* Grid */}
        <div className="flex-1 p-4 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center h-full">
              <div className="text-center">
                <Loader2 size={32} className="text-[#6366F1] animate-spin mx-auto mb-3" />
                <p className="text-sm text-[#71717A]">Searching photos...</p>
              </div>
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex items-center justify-center h-full">
              <p className="text-sm text-[#71717A]">No photos found</p>
            </div>
          ) : (
            <div className="grid grid-cols-[repeat(auto-fill,minmax(200px,1fr))] gap-1">
              {filtered.map((photo, idx) => (
                <button
                  key={photo.id}
                  onClick={() => setSelectedId(photo.id === selectedId ? null : photo.id)}
                  className={`
                    aspect-square rounded-lg overflow-hidden relative group cursor-pointer
                    transition-all duration-150
                    ${photo.id === selectedId ? 'ring-2 ring-[#6366F1]' : ''}
                  `}
                  style={{ backgroundColor: placeholderColors[idx % placeholderColors.length] }}
                >
                  {/* Placeholder pattern */}
                  <div className="absolute inset-0 flex items-center justify-center">
                    <span className="text-white/20 text-xs font-mono">{photo.filename}</span>
                  </div>
                  {/* Hover overlay */}
                  <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/80 to-transparent p-2 pt-8 opacity-0 group-hover:opacity-100 transition-opacity duration-150">
                    <div className="flex flex-wrap gap-1">
                      {photo.tags.slice(0, 3).map((tag) => (
                        <span
                          key={tag}
                          className="text-[10px] px-1.5 py-0.5 rounded-full bg-white/20 text-white/90"
                        >
                          {tag}
                        </span>
                      ))}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Detail panel */}
      {selected && (
        <aside className="w-[320px] min-w-[320px] bg-[#18181B] border-l border-[#27272A] p-5 overflow-y-auto">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-sm font-semibold text-[#FAFAFA]">Details</h3>
            <button
              onClick={() => setSelectedId(null)}
              className="text-[#71717A] hover:text-[#FAFAFA] transition-colors duration-150"
            >
              <X size={16} />
            </button>
          </div>

          {/* Preview placeholder */}
          <div
            className="aspect-[4/3] rounded-lg mb-4"
            style={{ backgroundColor: placeholderColors[(selected.id - 1) % placeholderColors.length] }}
          />

          {/* Filename */}
          <p className="text-sm font-medium text-[#FAFAFA] mb-3">{selected.filename}</p>

          {/* Tags */}
          <div className="flex flex-wrap gap-1.5 mb-4">
            {selected.tags.map((tag) => (
              <span
                key={tag}
                className="text-xs px-2 py-1 rounded-lg bg-[#27272A] text-[#A1A1AA]"
              >
                {tag}
              </span>
            ))}
          </div>

          {/* Caption */}
          <div className="mb-4">
            <p className="text-xs text-[#71717A] mb-1">Caption</p>
            <p className="text-sm text-[#A1A1AA]">{selected.caption}</p>
          </div>

          {/* EXIF metadata */}
          <div className="space-y-2">
            <p className="text-xs text-[#71717A] mb-1">Metadata</p>
            {[
              { label: 'Date', value: selected.dateTaken },
              { label: 'Camera', value: selected.camera },
              { label: 'Resolution', value: selected.resolution },
              { label: 'Size', value: selected.fileSize },
            ].filter((item) => item.value).map((item) => (
              <div key={item.label} className="flex justify-between text-xs">
                <span className="text-[#71717A]">{item.label}</span>
                <span className="text-[#A1A1AA]">{item.value}</span>
              </div>
            ))}
          </div>
        </aside>
      )}
    </div>
  );
}
