import { createContext, useContext, useReducer, type ReactNode, type Dispatch } from 'react';
import type {
  CatalogStatus,
  SearchResult,
  OrganizationPlan,
  HistoryEntry,
} from '../types/cli';

export type ScreenName = 'welcome' | 'dashboard' | 'grid' | 'planner' | 'history' | 'settings';

export interface AppState {
  folderPath: string | null;
  recentFolders: { path: string; lastScanned: string }[];
  currentScreen: ScreenName;
  catalogStatus: CatalogStatus | null;
  catalogLoading: boolean;
  searchResults: SearchResult[];
  searchQuery: string;
  selectedPhotoId: number | null;
  currentPlan: OrganizationPlan | null;
  planLoading: boolean;
  history: HistoryEntry[];
  executionProgress: { current: number; total: number; stage: string } | null;
}

export type AppAction =
  | { type: 'SET_FOLDER'; payload: string }
  | { type: 'SET_SCREEN'; payload: ScreenName }
  | { type: 'SET_CATALOG_STATUS'; payload: CatalogStatus }
  | { type: 'SET_CATALOG_LOADING'; payload: boolean }
  | { type: 'SET_SEARCH_RESULTS'; payload: SearchResult[] }
  | { type: 'SET_SEARCH_QUERY'; payload: string }
  | { type: 'SET_SELECTED_PHOTO'; payload: number | null }
  | { type: 'SET_PLAN'; payload: OrganizationPlan | null }
  | { type: 'SET_PLAN_LOADING'; payload: boolean }
  | { type: 'SET_HISTORY'; payload: HistoryEntry[] }
  | { type: 'SET_EXECUTION_PROGRESS'; payload: { current: number; total: number; stage: string } | null }
  | { type: 'RESET' };

const initialState: AppState = {
  folderPath: null,
  recentFolders: [
    { path: '/Users/demo/Photos/2024-Vacation', lastScanned: '2026-04-10' },
    { path: '/Users/demo/Pictures/Family', lastScanned: '2026-04-08' },
  ],
  currentScreen: 'welcome',
  catalogStatus: null,
  catalogLoading: false,
  searchResults: [],
  searchQuery: '',
  selectedPhotoId: null,
  currentPlan: null,
  planLoading: false,
  history: [],
  executionProgress: null,
};

function appReducer(state: AppState, action: AppAction): AppState {
  switch (action.type) {
    case 'SET_FOLDER':
      return { ...state, folderPath: action.payload, currentScreen: 'dashboard' };
    case 'SET_SCREEN':
      return { ...state, currentScreen: action.payload };
    case 'SET_CATALOG_STATUS':
      return { ...state, catalogStatus: action.payload };
    case 'SET_CATALOG_LOADING':
      return { ...state, catalogLoading: action.payload };
    case 'SET_SEARCH_RESULTS':
      return { ...state, searchResults: action.payload };
    case 'SET_SEARCH_QUERY':
      return { ...state, searchQuery: action.payload };
    case 'SET_SELECTED_PHOTO':
      return { ...state, selectedPhotoId: action.payload };
    case 'SET_PLAN':
      return { ...state, currentPlan: action.payload };
    case 'SET_PLAN_LOADING':
      return { ...state, planLoading: action.payload };
    case 'SET_HISTORY':
      return { ...state, history: action.payload };
    case 'SET_EXECUTION_PROGRESS':
      return { ...state, executionProgress: action.payload };
    case 'RESET':
      return initialState;
    default:
      return state;
  }
}

interface AppContextValue {
  state: AppState;
  dispatch: Dispatch<AppAction>;
}

const AppContext = createContext<AppContextValue | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(appReducer, initialState);
  return (
    <AppContext.Provider value={{ state, dispatch }}>
      {children}
    </AppContext.Provider>
  );
}

export function useAppContext(): AppContextValue {
  const ctx = useContext(AppContext);
  if (!ctx) throw new Error('useAppContext must be used within AppProvider');
  return ctx;
}
