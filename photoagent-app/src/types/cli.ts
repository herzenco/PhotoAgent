export interface CatalogStatus {
  total_images: number;
  analyzed_count: number;
  duplicate_count: number;
  screenshot_count: number;
  total_disk_usage: number;
  by_year: Record<string, number>;
  by_camera: Record<string, number>;
  by_location: Record<string, number>;
}

export interface ScanResult {
  total_found: number;
  new_images: number;
  skipped: number;
  errors: string[];
  duration: number;
}

export interface SearchResult {
  id: number;
  file_path: string;
  filename: string;
  score: number;
  caption: string;
  tags: string[];
  match_reason: string;
  date_taken?: string;
  city?: string;
  country?: string;
  camera_model?: string;
  ai_quality_score?: number;
  is_screenshot?: boolean;
  face_count?: number;
  file_size?: number;
}

export interface OrganizationPlan {
  folder_structure: string[];
  moves: PlanMove[];
  summary: string;
}

export interface PlanMove {
  id: number;
  from: string;
  to: string;
}

export interface ExecutionResult {
  total_planned: number;
  successful: number;
  skipped: number;
  errors: string[];
  conflicts_resolved: number;
  duration: number;
}

export interface HistoryEntry {
  id: number;
  timestamp: string;
  instruction: string;
  status: string;
  file_count: number;
}

export interface AppConfig {
  api_key_configured: boolean;
  preferred_device: string;
  default_template: string;
  default_extensions: string;
}

export interface ProgressInfo {
  stage: string;
  current: number;
  total: number;
  description?: string;
}
