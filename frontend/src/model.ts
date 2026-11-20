export const api = '/api/assetgate';

export type Asset = {
  asset_id: string;
  name: string;
  asset_type: string;
  created_at: string;
  current_version_id: string;
};
export type AssetRow = Asset & {
  version_number: number;
  file_format: string;
  preview_file: string | null;
  versions: number;
  active_runs: number;
  approved: number;
};
export type Version = {
  version_id: string;
  version_number: number;
  parent_version_id: string | null;
  source_file: string;
  file_hash: string;
  file_format: string;
  created_at: string;
  preview_file: string | null;
  freshness: 'CURRENT' | 'STALE';
};
export type State = 'PENDING' | 'RUNNING' | 'SUCCEEDED' | 'FAILED' | 'CANCELED';
export type Run = {
  run_id: string;
  asset_id?: string;
  asset_name?: string;
  asset_version_id: string;
  output_version_id: string | null;
  operation_type: 'inspect' | 'process' | 'export';
  status: State;
  freshness: 'CURRENT' | 'STALE';
  parameters: Record<string, unknown>;
  nodes: { name: string; status: State; error_message?: string }[];
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  error_message: string | null;
  cancel_requested: number;
  retry_of: string | null;
  export_file: string | null;
};
export type CheckState = 'PASS' | 'FAIL' | 'WARNING' | 'NOT_CHECKED';
export type Finding = {
  rule_id: string;
  rule_name: string;
  severity: 'block' | 'warning' | 'info';
  status: CheckState;
  actual_value: unknown;
  expected_value: unknown;
  evidence: unknown;
  suggestion: string;
};
export type Metrics = {
  objects: number;
  vertices: number;
  edges: number;
  faces: number;
  triangles: number;
  materials: number;
  dimensions: number[] | null;
  bounds: { min: number[]; max: number[] } | null;
  meshes: { slots: number; uv: { layers: number } }[];
};
export type Report = {
  report_id: string;
  asset_version_id: string;
  ruleset_version: string;
  created_at: string;
  findings: Finding[];
  summary: {
    counts: Record<CheckState, number>;
    metrics: Metrics | null;
    blender_version: string | null;
    adapter_mode: string;
    preview_error: string | null;
  };
};
export type Review = {
  review_id: string;
  asset_version_id: string;
  report_id: string;
  reviewer: string;
  decision: 'APPROVED' | 'REJECTED';
  note: string;
  created_at: string;
};
export type AssetDetail = Asset & { versions: Version[]; reports: Report[]; runs: Run[]; reviews: Review[] };
export type Engine = { blender_detected: boolean; max_upload_bytes: number; ruleset_version: string };

export async function request<T>(path: string, method = 'GET', body?: FormData | object): Promise<T> {
  const options: RequestInit = { method, cache: 'no-store' };
  if (body instanceof FormData) {
    options.body = body;
  } else if (body) {
    options.headers = { 'Content-Type': 'application/json' };
    options.body = JSON.stringify(body);
  }
  const response = await fetch(api + path, options);
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    const detail = payload.detail;
    const error = Array.isArray(detail) ? detail.map(item => item.msg).join(' · ') : detail;
    throw new Error(error || `请求失败（${response.status}）`);
  }
  return response.json();
}

export const label: Record<string, string> = {
  PASS: '通过', FAIL: '阻断', WARNING: '提醒', NOT_CHECKED: '未检查',
  block: '阻断', warning: '警告', info: '提示',
  PENDING: '排队中', RUNNING: '运行中', SUCCEEDED: '已完成', FAILED: '失败', CANCELED: '已取消',
  STALE: '已过时', APPROVED: '审核通过', REJECTED: '审核驳回',
  inspect: '质量检查', process: '模型处理', export: '资产导出',
  inspect_source: '检查原模型', apply_transforms: '应用变换', recalculate_normals: '重计算法线',
  smart_uv: 'Smart UV Project', convert: '写出最终模型', recheck: '重新导入并复检', package: '生成 ZIP',
};

export const isActive = (run: Run) => run.status === 'PENDING' || run.status === 'RUNNING';
export const number = (value: number) => value.toLocaleString('zh-CN');
export const date = (value: string) => new Date(value).toLocaleString('zh-CN', {
  month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false,
});
export const format = (value: unknown): string => {
  if (value === null || value === undefined || value === '') return '—';
  if (typeof value === 'boolean') return value ? '是' : '否';
  if (typeof value === 'number') return number(value);
  if (typeof value === 'string') return value;
  return JSON.stringify(value);
};
